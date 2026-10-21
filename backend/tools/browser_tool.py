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


class BrowserTool(BaseTool):
    """Universal Web Browser Automation Tool."""

    def __init__(self, automation: Any = None) -> None:
        super().__init__(
            name="browser_tool",
            description="Controls browser navigation, clicking, typing, and scraping.",
            risk_level=RiskLevel.MEDIUM,
            command=TaskCommand.OPEN_URL,
            irreversible=False,
        )
        self.automation = automation

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        command = inputs.get("command")
        params = inputs.get("params", {})
        step_id = inputs.get("step_id", "browser-step")

        if not self.automation:
            return ExecutionResult(step_id=step_id, ok=False, message="Automation missing.", error="AdapterMissing")

        if isinstance(command, str):
            try:
                command = TaskCommand(command)
            except ValueError:
                command = TaskCommand.OPEN_URL

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
        url = inputs.get("params", {}).get("url", "")
        return Observation(
            target=f"browser:{url or 'page'}",
            state_data={"url": url, "ok": execution_result.ok},
            raw_output=execution_result.message,
            evidence_type="browser_page_state",
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
                evidence=f"Browser action failed: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )
        return VerificationResult(
            verified=True,
            confidence=0.95,
            evidence=f"Browser navigation / interaction succeeded: {execution_result.message}",
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
            "message": f"Browser interaction error: {error.message}.",
        }
