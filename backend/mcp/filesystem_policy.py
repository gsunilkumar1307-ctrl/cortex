from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .exceptions import MCPSecurityError


class FilesystemPermissionPolicy:
    """
    Permission Policy and Cryptographic Approval Verification for Filesystem Operations.

    Classifies operations into:
    - AUTOMATIC: Low-risk read-only or non-destructive operations (read, list, search, stat, mkdir,
                 or creating a brand-new file).
    - APPROVAL REQUIRED: Consequential, destructive, or mutating operations (overwriting existing
                         files, edits, moves/renames, mass operations, deletions).

    Enforces single-use cryptographic tokens (approved_hash), stale-approval rejection,
    and anti-replay validation.
    """

    AUTOMATIC_TOOLS = {
        "read_file",
        "read_text_file",
        "read_media_file",
        "read_multiple_files",
        "list_directory",
        "directory_tree",
        "search_files",
        "get_file_info",
        "list_allowed_directories",
        "create_directory",
    }

    CONSEQUENTIAL_TOOLS = {
        "edit_file",
        "move_file",
        "copy_file",
        "delete_file",
        "remove_file",
    }

    def __init__(self) -> None:
        self._consumed_approval_tokens: set[str] = set()

    def is_approval_required(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """
        Determines whether the specified tool call requires human / cryptographic approval.
        For write_file, approval is required ONLY if the target file already exists on disk (overwrite).
        Creating a new file is non-destructive and considered AUTOMATIC within approved roots.
        """
        tool_lower = tool_name.lower()

        # Tools that are inherently consequential
        if tool_lower in self.CONSEQUENTIAL_TOOLS:
            return True

        # write_file classification:
        if tool_lower == "write_file":
            target_path_raw = arguments.get("path")
            if target_path_raw:
                p = Path(target_path_raw).expanduser()
                # If target file exists, this is an overwrite -> APPROVAL REQUIRED
                if p.exists() and p.is_file():
                    return True
            # New file creation is automatic
            return False

        # If tool is known automatic, no approval required
        if tool_lower in self.AUTOMATIC_TOOLS:
            return False

        # Any unknown or unspecified tool defaults to requiring approval (fail-safe)
        return True

    def compute_operation_hash(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """
        Computes a deterministic SHA-256 approval token for a filesystem operation.
        Incorporates the tool name, canonical path(s), and content/mutation payload.
        Any modification to arguments after approval will cause an ApprovalMismatch.
        """
        tool_lower = tool_name.lower()
        hasher = hashlib.sha256()
        hasher.update(tool_lower.encode("utf-8"))

        if "path" in arguments:
            hasher.update(str(arguments["path"]).encode("utf-8"))

        if "paths" in arguments and isinstance(arguments["paths"], list):
            for p in sorted(arguments["paths"]):
                hasher.update(str(p).encode("utf-8"))

        if "source" in arguments:
            hasher.update(str(arguments["source"]).encode("utf-8"))

        if "destination" in arguments:
            hasher.update(str(arguments["destination"]).encode("utf-8"))

        if "content" in arguments:
            content_str = str(arguments["content"])
            hasher.update(hashlib.sha256(content_str.encode("utf-8")).digest())

        if "edits" in arguments:
            edits_str = json.dumps(arguments["edits"], sort_keys=True)
            hasher.update(hashlib.sha256(edits_str.encode("utf-8")).digest())

        return hasher.hexdigest()

    def generate_approval_hash(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Alias for compute_operation_hash."""
        return self.compute_operation_hash(tool_name, arguments)

    def validate_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        approved_hash: str | None,
        is_expired: bool = False,
    ) -> tuple[bool, str | None, str | None]:
        """
        Validates the provided cryptographic approval token.
        Returns: (success: bool, error_code: str | None, error_message: str | None)
        """
        if not approved_hash:
            return (
                False,
                "ApprovalRequired",
                f"Operation '{tool_name}' is consequential and requires single-use cryptographic approval.",
            )

        if is_expired:
            return (
                False,
                "ApprovalExpired",
                f"Approval token for '{tool_name}' has expired. A fresh approval is required.",
            )

        if approved_hash in self._consumed_approval_tokens:
            return (
                False,
                "ApprovalReplay",
                f"Security violation: approval token for '{tool_name}' has already been consumed. Replay rejected.",
            )

        expected_hash = self.compute_operation_hash(tool_name, arguments)
        if approved_hash != expected_hash:
            return (
                False,
                "ApprovalMismatch",
                f"Security violation: approval token mismatch for '{tool_name}'. Parameters modified after approval.",
            )

        # Mark token consumed on successful validation
        self._consumed_approval_tokens.add(approved_hash)
        return True, None, None

    def reset_consumed_tokens(self) -> None:
        """Utility for test isolation."""
        self._consumed_approval_tokens.clear()
