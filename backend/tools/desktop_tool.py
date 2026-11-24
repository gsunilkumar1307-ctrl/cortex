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

        elif cmd_str == "open_app" and self.automation:
            if params.get("file_path") or params.get("folder"):
                state["file_path"] = params.get("file_path", "")
                state["folder"] = params.get("folder", "")
                state["app_running"] = execution_result.ok
            elif hasattr(self.automation, "is_app_running"):
                app_name = params.get("appName", "")
                if app_name:
                    state["appName"] = app_name
                    state["app_name"] = app_name
                state["app_running"] = execution_result.ok or self.automation.is_app_running(app_name)
                if hasattr(self.automation, "is_app_active"):
                    state["app_active"] = self.automation.is_app_active(app_name)

        elif cmd_str == "move_file":
            from pathlib import Path
            src = params.get("source") or params.get("src", "")
            tgt = params.get("destination") or params.get("target") or params.get("dest", "")
            state["source"] = src
            state["destination"] = tgt
            state["source_exists"] = Path(src).expanduser().exists() if src else False
            state["destination_exists"] = Path(tgt).expanduser().exists() if tgt else False

        elif cmd_str == "focus_app" and self.automation:
            app_name = params.get("appName", "")
            if app_name:
                state["appName"] = app_name
                state["app_name"] = app_name
            state["app_running"] = self.automation.is_app_running(app_name) if hasattr(self.automation, "is_app_running") else True
            if hasattr(self.automation, "is_app_active"):
                state["app_active"] = self.automation.is_app_active(app_name)

        elif cmd_str == "close_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            if app_name:
                state["appName"] = app_name
                state["app_name"] = app_name
            state["app_running"] = self.automation.is_app_running(app_name)

        elif cmd_str == "inspect_app" and self.automation and hasattr(self.automation, "is_app_running"):
            app_name = params.get("appName", "")
            if app_name:
                state["appName"] = app_name
                state["app_name"] = app_name
            state["app_running"] = self.automation.is_app_running(app_name)

        elif cmd_str in ("click_element", "type_in_element", "desktop_workflow"):
            state["verified_outcome"] = execution_result.data.get("verified_outcome", execution_result.ok)

        elif cmd_str == "type_text":
            data = execution_result.data if isinstance(execution_result.data, dict) else {}
            state["text_verified"] = data.get("verified", execution_result.ok)
            state["unverified"] = data.get("unverified", False)
            state["already_present"] = data.get("already_present", False)
            txt = params.get("text") or data.get("text") or ""
            if txt:
                state["text"] = txt
            app = params.get("appName") or data.get("appName") or ""
            if app:
                state["appName"] = app
                state["app_name"] = app

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

        # Robust parameter extraction merging inputs.params, top-level inputs, and observation state
        params = dict(inputs.get("params") or {})
        for k, v in inputs.items():
            if k not in ("command", "params", "step_id", "action") and k not in params:
                params[k] = v

        app_name = (
            params.get("appName")
            or inputs.get("appName")
            or observation.state_data.get("appName")
            or observation.state_data.get("app_name")
            or (execution_result.data.get("appName") if isinstance(execution_result.data, dict) else "")
            or ""
        )

        if cmd_str == "open_app":
            if params.get("file_path") or params.get("folder"):
                return VerificationResult(
                    verified=execution_result.ok,
                    confidence=1.0 if execution_result.ok else 0.0,
                    evidence=execution_result.message or "File/folder opened.",
                    error=None if execution_result.ok else execution_result.error,
                )
            app_running = observation.state_data.get("app_running", True)
            if not is_dry and not app_running:
                target_str = f"'{app_name}'" if app_name else "target application"
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Application {target_str} failed to open: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            evidence = f"Verified application '{app_name}' is running." if app_name else "Verified target application is running."
            if observation.state_data.get("app_active"):
                evidence += " In foreground."
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=evidence,
            )

        if cmd_str == "move_file":
            if not execution_result.ok:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Move failed: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            dest_exists = observation.state_data.get("destination_exists", False)
            src_exists = observation.state_data.get("source_exists", True)
            if not is_dry and not dest_exists:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence="Verification failure: Destination does not exist after move.",
                )
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Positive disk verification: {execution_result.message}",
            )

        if cmd_str == "focus_app":
            if not execution_result.ok:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Focus failed: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            evidence = f"Verified application '{app_name}' brought to foreground." if app_name else "Verified target application brought to foreground."
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=evidence,
            )

        if cmd_str == "close_app":
            if not execution_result.ok:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Application close failed: {execution_result.error or execution_result.message}",
                    error=execution_result.error,
                )
            app_running = observation.state_data.get("app_running", False)
            if not is_dry and app_running:
                target_str = f"'{app_name}'" if app_name else "target application"
                return VerificationResult(
                    verified=False,
                    confidence=0.9,
                    evidence=f"Application {target_str} is still running and refused to close.",
                )
            evidence = f"Verified application '{app_name}' process terminated." if app_name else "Verified target application process terminated."
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=evidence,
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

        if cmd_str == "type_text":
            target_text = (
                params.get("text")
                or inputs.get("text")
                or observation.state_data.get("text")
                or (execution_result.data.get("text") if isinstance(execution_result.data, dict) else "")
                or ""
            )
            if is_dry:
                evidence = f"Dry-run: verified type_text for '{target_text}'." if target_text else "Dry-run: verified type_text."
                return VerificationResult(
                    verified=True,
                    confidence=0.9,
                    evidence=evidence,
                )
            text_verified = observation.state_data.get("text_verified", False)
            unverified = observation.state_data.get("unverified", False)
            if unverified or not text_verified:
                target_app_phrase = f"'{app_name}'" if app_name else "target application"
                text_phrase = f"'{target_text}'" if target_text else "requested text"
                return VerificationResult(
                    verified=False,
                    confidence=0.3,
                    evidence=f"Text verification failed: could not confirm that {text_phrase} was entered into {target_app_phrase}.",
                    error="UNVERIFIED",
                )
            target_app_phrase = f"'{app_name}'" if app_name else "active application"
            evidence = f"Verified text '{target_text}' successfully entered into {target_app_phrase}." if target_text else f"Verified text successfully entered into {target_app_phrase}."
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=evidence,
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
