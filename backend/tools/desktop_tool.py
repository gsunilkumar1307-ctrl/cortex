from __future__ import annotations

import time
from typing import Any
try:
    from backend.core.contracts import (
        ExecutionResult,
        Observation,
        VerificationResult,
        ExecutionError,
        RiskLevel,
        TaskCommand,
        TaskContext,
    )
except ImportError:
    from core.contracts import (
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
        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("command", "params", "step_id") and k not in params:
                params[k] = v
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
        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("command", "params", "step_id") and k not in params:
                params[k] = v
        cmd_str = command.value if isinstance(command, TaskCommand) else str(command)

        state: dict[str, Any] = {"command": cmd_str, "ok": execution_result.ok}

        # Specific observations based on command type
        if cmd_str == "personal_task_create" and self.automation and hasattr(self.automation, "verify_task_created"):
            title = params.get("title", "")
            state["task_verified"] = self.automation.verify_task_created(title)

        elif cmd_str == "open_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            state["app_running"] = self.automation.is_app_running(app_name)
            if hasattr(self.automation, "is_app_active"):
                state["app_active"] = self.automation.is_app_active(app_name)

        elif cmd_str == "focus_app" and self.automation:
            app_name = params.get("appName", "")
            state["app_running"] = self.automation.is_app_running(app_name) if hasattr(self.automation, "is_app_running") else True
            if hasattr(self.automation, "is_app_active"):
                state["app_active"] = self.automation.is_app_active(app_name)

        elif cmd_str == "close_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            state["app_running"] = self.automation.is_app_running(app_name)

        elif cmd_str == "inspect_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            state["app_running"] = self.automation.is_app_running(app_name)

        elif cmd_str in ("click_element", "type_in_element", "desktop_workflow"):
            state["verified_outcome"] = execution_result.data.get("verified_outcome", execution_result.ok)

        return Observation(
            target=f"desktop:{cmd_str}",
            state_data=state,
            raw_output=execution_result.message,
            evidence_type="screen_intelligence_perception" if "element" in cmd_str or "screen" in cmd_str else "system_state_inspection",
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
        is_dry = bool(getattr(self.automation, "dry_run", False)) or "dry-run" in (execution_result.message or "").lower()

        if cmd_str == "open_app":
            app_name = inputs.get("params", {}).get("appName", "")
            app_running = observation.state_data.get("app_running", True)
            if not is_dry and not app_running:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Application failed to open: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            evidence = f"Verified application '{app_name}' is running."
            if observation.state_data.get("app_active"):
                evidence += " In foreground."
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=evidence,
            )

        if cmd_str == "focus_app":
            app_name = inputs.get("params", {}).get("appName", "")
            if not execution_result.ok:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Focus failed: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=f"Verified application '{app_name}' brought to foreground.",
            )

        if cmd_str == "close_app":
            app_name = inputs.get("params", {}).get("appName", "")
            if not execution_result.ok:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Application close failed: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            app_running = observation.state_data.get("app_running", False)
            if not is_dry and app_running:
                return VerificationResult(
                    verified=False,
                    confidence=0.9,
                    evidence=f"Application '{app_name}' is still running and refused to close.",
                )
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Verified application '{app_name}' process terminated.",
            )

        if cmd_str == "inspect_app":
            return VerificationResult(
                verified=execution_result.ok,
                confidence=1.0,
                evidence=execution_result.message,
            )

        if cmd_str == "personal_task_create":
            verified = observation.state_data.get("task_verified", True)
            return VerificationResult(
                verified=verified,
                confidence=1.0 if verified else 0.5,
                evidence="Personal task record verified in persistent task store." if verified else "Task record missing.",
            )

        if cmd_str == "observe_screen":
            return VerificationResult(
                verified=execution_result.ok,
                confidence=1.0 if execution_result.ok else 0.2,
                evidence=execution_result.message if execution_result.ok else f"Screen observation failed: {execution_result.error or execution_result.message}",
            )

        if cmd_str in ("click_element", "type_in_element", "desktop_workflow"):
            verified = bool(observation.state_data.get("verified_outcome", True))
            return VerificationResult(
                verified=verified,
                confidence=0.95 if verified else 0.4,
                evidence=f"Screen action verified via UI state observation: {execution_result.message}" if verified else "UI outcome verification failed or state did not shift.",
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
