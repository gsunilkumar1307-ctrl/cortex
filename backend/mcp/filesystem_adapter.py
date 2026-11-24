from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time
from typing import Any

from .adapter import MCPToolAdapter, validate_input_schema
from .exceptions import MCPSecurityError, MCPTimeoutError, MCPValidationError
from .filesystem_jail import FilesystemPathJail
from .filesystem_policy import FilesystemPermissionPolicy
from .models import MCPToolDefinition, MCPToolResult

try:
    from backend.core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        TaskContext,
        VerificationResult,
    )
except ImportError:
    from core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        TaskContext,
        VerificationResult,
    )


class MCPFilesystemToolAdapter(MCPToolAdapter):
    """
    Specialized MCP Tool Adapter for the Model Context Protocol Filesystem Server.

    Enforces:
    1. Filesystem Path Jail validation at the execution boundary before dispatch.
    2. Consequential action policy & cryptographic approval hash verification.
    3. Positive verification on disk (SHA-256 matching, file/dir existence, 0-byte handling).
    4. Conservative recovery protocols preventing blind retries of mutations.
    """

    def __init__(
        self,
        definition: MCPToolDefinition,
        manager: Any,
        namespaced_name: str | None = None,
        jail: FilesystemPathJail | None = None,
        policy: FilesystemPermissionPolicy | None = None,
    ) -> None:
        super().__init__(definition, manager, namespaced_name=namespaced_name)
        self.jail = jail or FilesystemPathJail()
        self.policy = policy or FilesystemPermissionPolicy()

    def _hash_file(self, path: Path) -> str:
        """Computes SHA-256 hex digest of a local file."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"mcp-fs-step-{self.name}")

        # 1. Extract raw arguments
        try:
            raw_args = self._extract_call_arguments(inputs)
            validate_input_schema(raw_args, self.input_schema)
        except MCPValidationError as ve:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Argument validation failed for {self.name}: {ve}",
                error="ValidationError",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 2. Path Jail Canonicalization and Traversal Guard
        try:
            clean_args = self.jail.validate_tool_arguments(self.original_tool_name, raw_args)
        except MCPSecurityError as se:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Path security violation in {self.name}: {se}",
                error="SecurityViolation",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as pe:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Path validation failed in {self.name}: {pe}",
                error="PathValidationError",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 3. Policy Classification and Approval Verification
        if self.policy.is_approval_required(self.original_tool_name, clean_args):
            approved_hash = inputs.get("approved_hash") or inputs.get("approval_hash")
            is_expired = inputs.get("approval_expired", False)

            ok, err_code, err_msg = self.policy.validate_approval(
                self.original_tool_name,
                clean_args,
                approved_hash,
                is_expired=is_expired,
            )
            if not ok:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=err_msg or "Approval verification failed.",
                    error=err_code or "ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # 4. Pre-execution Disk Snapshot (for verification reference)
        pre_snapshot: dict[str, Any] = {}
        target_path_str = clean_args.get("path")
        if target_path_str:
            p = Path(target_path_str)
            if p.exists():
                pre_snapshot["exists"] = True
                pre_snapshot["is_dir"] = p.is_dir()
                pre_snapshot["size"] = p.stat().st_size
                if p.is_file():
                    pre_snapshot["sha256"] = self._hash_file(p)

        # 4b. Format-Aware Document Reading for non-plain-text files (PDF, PPTX, DOCX, XLSX, etc.)
        if self.original_tool_name in ("read_text_file", "read_file") and target_path_str:
            p_doc = Path(target_path_str)
            if p_doc.exists() and p_doc.suffix.lower() in (".pdf", ".pptx", ".potx", ".ppsx", ".docx", ".xlsx", ".key"):
                try:
                    from backend.capabilities.document_reader import read_document
                    doc_res = read_document(p_doc)
                    duration_ms = (time.time() - start_time) * 1000
                    if doc_res.ok:
                        return ExecutionResult(
                            step_id=step_id,
                            ok=True,
                            message=doc_res.content,
                            data={
                                "content": doc_res.content,
                                "server": self.server_name,
                                "tool": self.original_tool_name,
                                "clean_args": clean_args,
                                "file_type": doc_res.file_type,
                                "pre_snapshot": pre_snapshot,
                            },
                            duration_ms=duration_ms,
                        )
                    else:
                        return ExecutionResult(
                            step_id=step_id,
                            ok=False,
                            message=doc_res.error or "Failed to read document.",
                            error="DocumentReadError",
                            duration_ms=duration_ms,
                        )
                except Exception as e:
                    pass

        # 5. Dispatch call to MCP Server
        timeout = inputs.get("timeout")
        try:
            result: MCPToolResult = self.manager.call_tool(
                self.server_name,
                self.original_tool_name,
                clean_args,
                timeout=timeout,
            )

            duration_ms = (time.time() - start_time) * 1000

            if result.is_error:
                # If read_text_file failed on an unrecognized binary document, attempt document_reader fallback
                if self.original_tool_name in ("read_text_file", "read_file") and target_path_str:
                    try:
                        from backend.capabilities.document_reader import read_document
                        p_fallback = Path(target_path_str)
                        if p_fallback.exists():
                            fallback_res = read_document(p_fallback)
                            if fallback_res.ok:
                                return ExecutionResult(
                                    step_id=step_id,
                                    ok=True,
                                    message=fallback_res.content,
                                    data={"content": fallback_res.content, "clean_args": clean_args},
                                    duration_ms=duration_ms,
                                )
                    except Exception:
                        pass
                error_text = result.get_text_content() or "MCP filesystem tool reported an error."
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=error_text,
                    data={"raw": result.raw_response, "clean_args": clean_args},
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
                    "clean_args": clean_args,
                    "pre_snapshot": pre_snapshot,
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
        clean_args = (
            execution_result.data.get("clean_args")
            if execution_result.data
            else self._extract_call_arguments(inputs)
        )
        state_data: dict[str, Any] = {
            "server": self.server_name,
            "tool": self.original_tool_name,
            "ok": execution_result.ok,
            "clean_args": clean_args,
        }

        # Inspect on-disk target path if available
        target_path_str = clean_args.get("path")
        if target_path_str:
            p = Path(target_path_str)
            state_data["path"] = str(p)
            state_data["exists"] = p.exists()
            if p.exists():
                state_data["is_dir"] = p.is_dir()
                stat = p.stat()
                state_data["size_bytes"] = stat.st_size
                state_data["mtime"] = stat.st_mtime
                if p.is_file():
                    state_data["sha256"] = self._hash_file(p)

        # Inspect move_file / copy_file source & destination
        if "source" in clean_args:
            src = Path(clean_args["source"])
            state_data["source_exists"] = src.exists()
        if "destination" in clean_args:
            dst = Path(clean_args["destination"])
            state_data["destination_exists"] = dst.exists()
            if dst.exists():
                state_data["destination_size"] = dst.stat().st_size

        return Observation(
            target=f"mcp:filesystem:{self.original_tool_name}",
            state_data=state_data,
            raw_output=execution_result.message,
            evidence_type="filesystem_disk_observation",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        """
        Performs positive, empirical verification directly against the local filesystem.
        Never relies solely on the server claim.
        """
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Filesystem operation '{self.name}' failed: {execution_result.error or execution_result.message}",
                error=execution_result.error or "FilesystemOperationFailed",
            )

        state = observation.state_data
        tool = self.original_tool_name

        # 1. write_file verification
        if tool == "write_file":
            path_str = state.get("path")
            if not path_str or not state.get("exists"):
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence=f"Verification failure: Target file '{path_str}' does not exist on disk after write.",
                    uncertainty_reason="FileNotFoundAfterWrite",
                )

            # Check content integrity if content was supplied
            clean_args = state.get("clean_args", {})
            written_content = clean_args.get("content")
            if written_content is not None:
                expected_sha = hashlib.sha256(str(written_content).encode("utf-8")).hexdigest()
                actual_sha = state.get("sha256")
                if actual_sha != expected_sha:
                    return VerificationResult(
                        verified=False,
                        confidence=0.0,
                        evidence=f"Verification failure: Disk SHA-256 ({actual_sha}) does not match expected ({expected_sha}).",
                        uncertainty_reason="ContentChecksumMismatch",
                    )

            size_bytes = state.get("size_bytes", 0)
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Positive disk verification: file '{path_str}' exists ({size_bytes} bytes, sha256={state.get('sha256', '')[:12]}).",
            )

        # 2. edit_file verification
        if tool == "edit_file":
            path_str = state.get("path")
            if not path_str or not state.get("exists"):
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence=f"Verification failure: Target file '{path_str}' does not exist after edit.",
                    uncertainty_reason="FileNotFoundAfterEdit",
                )
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Positive disk verification: file '{path_str}' successfully edited ({state.get('size_bytes', 0)} bytes).",
            )

        # 3. read_file / read_text_file / read_media_file verification
        if tool in {"read_file", "read_text_file", "read_media_file"}:
            path_str = state.get("path")
            if not path_str or not state.get("exists"):
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence=f"Verification failure: File '{path_str}' does not exist on disk.",
                    uncertainty_reason="TargetNotFound",
                )

            size_bytes = state.get("size_bytes", 0)
            # Empty file handling: 0-byte file is valid when read returns empty
            if size_bytes == 0:
                return VerificationResult(
                    verified=True,
                    confidence=1.0,
                    evidence=f"Positive disk verification: 0-byte empty file '{path_str}' confirmed on disk.",
                )

            # If file has content, ensure output is non-empty
            if not execution_result.message:
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence=f"Verification failure: File '{path_str}' is {size_bytes} bytes on disk but read output was empty.",
                    uncertainty_reason="EmptyReadOutput",
                )

            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Positive disk verification: Read verified for '{path_str}' ({size_bytes} bytes).",
            )

        # 4. create_directory verification
        if tool == "create_directory":
            path_str = state.get("path")
            if not path_str or not state.get("exists") or not state.get("is_dir"):
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence=f"Verification failure: Directory '{path_str}' does not exist on disk.",
                    uncertainty_reason="DirectoryNotCreated",
                )
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence=f"Positive disk verification: Directory '{path_str}' exists on disk.",
            )

        # 5. move_file verification
        if tool == "move_file":
            dest_exists = state.get("destination_exists", False)
            src_exists = state.get("source_exists", True)
            if not dest_exists:
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence="Verification failure: Destination file does not exist after move.",
                    uncertainty_reason="MoveDestinationMissing",
                )
            if src_exists:
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence="Verification failure: Source file still exists after move.",
                    uncertainty_reason="MoveSourceStillPresent",
                )
            return VerificationResult(
                verified=True,
                confidence=1.0,
                evidence="Positive disk verification: Destination exists and source was removed.",
            )

        # 6. Fallback verification for query / list tools
        has_content = bool(
            execution_result.message
            or (execution_result.data and execution_result.data.get("content"))
        )
        if not has_content:
            return VerificationResult(
                verified=False,
                confidence=0.0,
                evidence=f"Verification failure: Tool '{tool}' returned no content.",
                uncertainty_reason="EmptyOutput",
            )

        return VerificationResult(
            verified=True,
            confidence=1.0,
            evidence=f"Positive verification: Output received and validated for '{tool}'.",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """
        Conservative recovery strategy:
        Consequential operations must not be retried automatically.
        """
        raw_args = self._extract_call_arguments(inputs)
        is_consequential = self.policy.is_approval_required(self.original_tool_name, raw_args)

        if is_consequential:
            return {
                "can_retry": False,
                "strategy": "escalate",
                "message": (
                    f"Filesystem mutation '{self.name}' failed with {error.message}. "
                    "Automatic retries of mutating operations are disabled to prevent corruption. Escalating to user."
                ),
            }

        can_retry = attempt < 3 and "validation" not in error.message.lower() and "security" not in error.message.lower()
        return {
            "can_retry": can_retry,
            "strategy": "retry" if can_retry else "escalate",
            "message": (
                f"Filesystem read operation '{self.name}' encountered error: {error.message}. "
                f"{'Attempting safe retry.' if can_retry else 'Escalating to user.'}"
            ),
        }
