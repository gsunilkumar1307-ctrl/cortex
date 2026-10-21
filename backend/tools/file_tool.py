from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
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


class FileTool(BaseTool):
    """Universal File Tool with sandbox isolation and disk-state verification."""

    def __init__(self, automation: Any = None) -> None:
        super().__init__(
            name="file_tool",
            description="Performs safe sandboxed file reading, writing, and directory searching.",
            risk_level=RiskLevel.MEDIUM,
            command=TaskCommand.WRITE_FILE,
            irreversible=False,
        )
        self.automation = automation

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        action = inputs.get("action", "read_file")
        path_str = str(inputs.get("path", ""))

        if not self.automation:
            return ExecutionResult(
                step_id=inputs.get("step_id", "file-step"),
                ok=False,
                message="Automation adapter missing.",
                error="AdapterMissing",
            )

        if action == "write_file":
            content = str(inputs.get("content", ""))
            res = self.automation.execute(TaskCommand.WRITE_FILE, {"path": path_str, "content": content})
            return ExecutionResult(
                step_id=inputs.get("step_id", "write-file-step"),
                ok=res.ok,
                message=res.message,
                data=res.data or {},
                error=None if res.ok else res.message,
                duration_ms=(time.time() - start_time) * 1000,
            )

        elif action == "read_file":
            res = self.automation.execute(TaskCommand.READ_FILE, {"path": path_str})
            return ExecutionResult(
                step_id=inputs.get("step_id", "read-file-step"),
                ok=res.ok,
                message=res.message,
                data=res.data or {},
                error=None if res.ok else res.message,
                duration_ms=(time.time() - start_time) * 1000,
            )

        elif action == "search_files":
            pattern = str(inputs.get("pattern", "*"))
            directory = str(inputs.get("directory", "."))
            res = self.automation.execute(TaskCommand.SEARCH_FILES, {"pattern": pattern, "directory": directory})
            return ExecutionResult(
                step_id=inputs.get("step_id", "search-files-step"),
                ok=res.ok,
                message=res.message,
                data=res.data or {},
                error=None if res.ok else res.message,
                duration_ms=(time.time() - start_time) * 1000,
            )

        return ExecutionResult(
            step_id=inputs.get("step_id", "unknown-file-step"),
            ok=False,
            message=f"Unsupported file action: {action}",
            error="UnsupportedAction",
        )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        action = inputs.get("action", "read_file")
        path_str = str(inputs.get("path", ""))
        state: dict[str, Any] = {"action": action, "path": path_str}

        if path_str:
            p = Path(path_str).expanduser()
            if p.exists() and p.is_file():
                try:
                    content_bytes = p.read_bytes()
                    state["exists"] = True
                    state["size_bytes"] = len(content_bytes)
                    state["sha256"] = hashlib.sha256(content_bytes).hexdigest()
                except Exception as e:
                    state["read_error"] = str(e)
            else:
                state["exists"] = False

        if action == "search_files":
            state["found_count"] = len(execution_result.data.get("files", []))

        return Observation(
            target=f"file:{path_str or inputs.get('directory', '.')}",
            state_data=state,
            raw_output=execution_result.message,
            evidence_type="filesystem_stat",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        action = inputs.get("action", "read_file")
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"File operation failed: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )

        if action == "write_file":
            exists = observation.state_data.get("exists", False)
            expected_content = str(inputs.get("content", ""))
            expected_hash = hashlib.sha256(expected_content.encode("utf-8")).hexdigest()
            actual_hash = observation.state_data.get("sha256")

            if exists and actual_hash == expected_hash:
                return VerificationResult(
                    verified=True,
                    confidence=1.0,
                    evidence=f"Verified file exists with exact sha256={actual_hash[:8]} and size={observation.state_data.get('size_bytes')}B",
                )
            else:
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence="File contents on disk do not match expected written content.",
                    uncertainty_reason="File content hash mismatch.",
                )

        elif action == "read_file":
            return VerificationResult(
                verified=bool(execution_result.data.get("content") is not None),
                confidence=1.0,
                evidence="File content successfully retrieved.",
            )

        return VerificationResult(
            verified=True,
            confidence=1.0,
            evidence=f"Search completed with {observation.state_data.get('found_count', 0)} items found.",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        return {
            "can_retry": attempt < 2 and "permission" not in error.message.lower(),
            "strategy": "retry" if attempt < 2 else "escalate",
            "message": f"File action failed: {error.message}. Please check path and permissions.",
        }
