from __future__ import annotations

import asyncio
import concurrent.futures
import time
from typing import Any

from .exceptions import MCPError, MCPTimeoutError, MCPValidationError
from .models import MCPToolDefinition, MCPToolResult

try:
    from backend.core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )
    from backend.tools.base import BaseTool
except ImportError:
    from core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )
    from tools.base import BaseTool


def _run_async(coro: Any) -> Any:
    """Runs an asynchronous coroutine synchronously, handling running loops safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def validate_input_schema(inputs: dict[str, Any], schema: dict[str, Any]) -> None:
    """
    Validates arguments against JSON schema type and required field constraints.
    """
    if not schema or not isinstance(schema, dict):
        return

    required = schema.get("required", [])
    if isinstance(required, list):
        for req in required:
            if req not in inputs:
                raise MCPValidationError(f"Missing required parameter: '{req}'")

    properties = schema.get("properties", {})
    if isinstance(properties, dict):
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for prop_name, prop_spec in properties.items():
            if prop_name in inputs and isinstance(prop_spec, dict):
                expected_type_str = prop_spec.get("type")
                if expected_type_str in type_map:
                    expected_type = type_map[expected_type_str]
                    val = inputs[prop_name]
                    # Handle boolean vs integer edge case in Python
                    if expected_type_str == "integer" and isinstance(val, bool):
                        raise MCPValidationError(f"Parameter '{prop_name}' must be integer, got boolean.")
                    if not isinstance(val, expected_type):
                        raise MCPValidationError(
                            f"Parameter '{prop_name}' expected type '{expected_type_str}', got '{type(val).__name__}'."
                        )


class MCPToolAdapter(BaseTool):
    """
    Adapts an MCP tool into Cortex's native BaseTool contract.
    Implements the standard lifecycle:
    EXECUTE -> OBSERVE -> VERIFY -> RECOVER
    Preserves original name/description, validates schemas, enforces timeouts,
    and requires positive verification before claiming success.
    """

    def __init__(
        self,
        definition: MCPToolDefinition,
        manager: Any,
        namespaced_name: str | None = None,
    ) -> None:
        canonical_name = namespaced_name or f"mcp__{definition.server_name}__{definition.name}"
        super().__init__(
            name=canonical_name,
            description=definition.description,
            input_schema=definition.input_schema,
            risk_level=definition.risk_level,
            command=definition.command,
            irreversible=definition.irreversible,
        )
        self.server_name = definition.server_name
        self.original_tool_name = definition.name
        self.manager = manager
        self.requires_approval = definition.requires_approval

    def _extract_call_arguments(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Extracts tool arguments from step inputs dictionary."""
        # Check if parameters were passed nested in "arguments" or "params"
        if "arguments" in inputs and isinstance(inputs["arguments"], dict):
            return dict(inputs["arguments"])
        if "params" in inputs and isinstance(inputs["params"], dict):
            return dict(inputs["params"])

        # Filter out Cortex internal task execution fields
        excluded = {"step_id", "task_id", "command", "action", "approval_hash", "approved_hash"}
        return {k: v for k, v in inputs.items() if k not in excluded}

    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"mcp-step-{self.name}")

        # 1. Extract and validate arguments
        try:
            args = self._extract_call_arguments(inputs)
            validate_input_schema(args, self.input_schema)
        except MCPValidationError as ve:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Argument validation failed for {self.name}: {ve}",
                error="ValidationError",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 2. Invoke MCP server via manager
        timeout = inputs.get("timeout")
        try:
            result: MCPToolResult = self.manager.call_tool(
                self.server_name,
                self.original_tool_name,
                args,
                timeout=timeout,
            )

            duration_ms = (time.time() - start_time) * 1000

            if result.is_error:
                error_text = result.get_text_content() or "MCP tool reported an error."
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=error_text,
                    data={"raw": result.raw_response},
                    error="MCPExecutionError",
                    duration_ms=duration_ms,
                )

            output_text = result.get_text_content()
            return ExecutionResult(
                step_id=step_id,
                ok=True,
                message=output_text,
                data={
                    "content": result.content,
                    "server": self.server_name,
                    "tool": self.original_tool_name,
                    "raw": result.raw_response,
                },
                duration_ms=duration_ms,
            )

        except MCPTimeoutError as te:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"MCP tool '{self.name}' timed out: {te}",
                error="TimeoutError",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"MCP tool execution failed: {e}",
                error=type(e).__name__,
                duration_ms=(time.time() - start_time) * 1000,
            )

    def observe(
        self,
        inputs: dict[str, Any],
        execution_result: ExecutionResult,
    ) -> Observation:
        args = self._extract_call_arguments(inputs)
        state_data: dict[str, Any] = {
            "server": self.server_name,
            "tool": self.original_tool_name,
            "ok": execution_result.ok,
            "has_data": bool(execution_result.data),
        }
        if execution_result.ok and execution_result.data:
            state_data["result_keys"] = list(execution_result.data.keys())

        return Observation(
            target=f"mcp:{self.server_name}:{self.original_tool_name}",
            state_data=state_data,
            raw_output=execution_result.message,
            evidence_type="mcp_tool_observation",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        """
        Independently verifies that the tool executed successfully.
        Never claims success without positive verification evidence.
        """
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"MCP action '{self.name}' failed: {execution_result.error or execution_result.message}",
                error=execution_result.error or "MCPFailure",
            )

        # Enforce positive verification: outcome must contain verifiable output
        has_content = bool(
            execution_result.message
            or (execution_result.data and execution_result.data.get("content"))
        )
        if not has_content:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                evidence="MCP tool returned no content or verifiable side-effects.",
                uncertainty_reason="EmptyOutput",
            )

        return VerificationResult(
            verified=True,
            confidence=1.0,
            evidence=f"Verified output received from MCP tool '{self.name}'.",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """Provides safe recovery or diagnostic steps."""
        can_retry = not self.irreversible and attempt < 3 and "validation" not in error.message.lower()
        return {
            "can_retry": can_retry,
            "strategy": "retry" if can_retry else "escalate",
            "message": (
                f"MCP tool '{self.name}' encountered error: {error.message}. "
                f"{'Attempting safe retry.' if can_retry else 'Escalating to user.'}"
            ),
        }
