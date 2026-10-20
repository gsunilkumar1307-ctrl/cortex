from __future__ import annotations

import time
from typing import Any
from cortex_sdk import (
    ExecutionResult,
    Observation,
    VerificationResult,
    ExecutionError,
    RiskLevel,
    TaskCommand,
    TaskContext,
)
from .base import BaseTool


class DesktopTool(BaseTool):
    """Universal Desktop & OS Automation Tool."""

    def __init__(self, automation: Any = None) -> None:
        super().__init__(
            name="desktop_tool",
            description="Controls desktop applications, keyboard, window focus, notes, and personal tasks.",
            risk_level=RiskLevel.LOW,
            command=TaskCommand.OPEN_APP,
            irreversible=False,
        )
        self.automation = automation

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        command = inputs.get("command")
        params = inputs.get("params", {})
        step_id = inputs.get("step_id", "desktop-step")

        if not self.automation:
            return ExecutionResult(step_id=step_id, ok=False, message="Automation missing.", error="AdapterMissing")

        if isinstance(command, str):
            try:
                command = TaskCommand(command)
            except ValueError:
                command = TaskCommand.UNKNOWN

        res = self.automation.execute(command, params)
        duration_ms = (time.time() - start_time) * 1000

        return ExecutionResult(
            step_id=step_id,
            ok=res.ok,
            message=res.message,
            data=res.data or {},
            error=None if res.ok else res.message,
            duration_ms=duration_ms,
        )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        command = inputs.get("command")
        params = inputs.get("params", {})
        cmd_str = command.value if isinstance(command, TaskCommand) else str(command)

        state: dict[str, Any] = {"command": cmd_str, "ok": execution_result.ok}

        # Specific observations based on command type
        if cmd_str == "personal_task_create" and self.automation and hasattr(self.automation, "verify_task_created"):
            title = params.get("title", "")
            state["task_verified"] = self.automation.verify_task_created(title)

        elif cmd_str == "open_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            state["app_running"] = self.automation.is_app_running(app_name)

        return Observation(
            target=f"desktop:{cmd_str}",
            state_data=state,
            raw_output=execution_result.message,
            evidence_type="system_state_inspection",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Execution error: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )

        cmd_str = observation.state_data.get("command", "")
        if cmd_str == "personal_task_create":
            verified = observation.state_data.get("task_verified", True)
            return VerificationResult(
                verified=verified,
                confidence=1.0 if verified else 0.5,
                evidence="Personal task record verified in persistent task store." if verified else "Task record missing.",
            )

        return VerificationResult(
            verified=True,
            confidence=0.9,
            evidence=f"Action '{cmd_str}' executed successfully: {execution_result.message}",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        return {
            "can_retry": attempt < 2,
            "strategy": "retry" if attempt < 2 else "escalate",
            "message": f"Desktop command failed: {error.message}.",
        }
