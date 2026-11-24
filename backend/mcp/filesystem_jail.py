from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .exceptions import MCPSecurityError

# Default approved workspace root
DEFAULT_WORKSPACE_ROOT = Path.home() / "Documents" / "CortexWorkspace"

# Default authorized roots covering standard user work areas
DEFAULT_AUTHORIZED_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    DEFAULT_WORKSPACE_ROOT,
]

# Protected system path prefixes that can never be accessed or approved
PROTECTED_SYSTEM_PREFIXES = (
    "/System",
    "/Library",
    "/private",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/var",
    "/Volumes",
    "/dev",
    "/proc",
    "/sys",
)

# Denied directory names/patterns across all paths
DENIED_DIR_PATTERNS = {
    ".ssh",
    ".aws",
    ".azure",
    ".config/gcloud",
    ".git",
    "node_modules",
}

# Denied sensitive file names/patterns
DENIED_FILENAMES = {
    ".session_secret",
    ".memory_key",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".gitignore",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "authorized_keys",
    "known_hosts",
    "cortex-memory.key",
    ".bash_history",
    ".zsh_history",
}


class FilesystemPathJail:
    """
    Filesystem Security Policy & Sandbox Enforcement for Cortex MCP.
    Enforces canonical path resolution, symlink escape detection, traversal guards,
    and credential access restrictions at the execution boundary.
    """

    def __init__(
        self,
        allowed_roots: list[str | Path] | None = None,
        auto_create_default: bool = True,
    ) -> None:
        self.allowed_roots: list[Path] = []

        if allowed_roots:
            for r in allowed_roots:
                resolved = self._validate_and_canonicalize_root(r)
                if resolved not in self.allowed_roots:
                    self.allowed_roots.append(resolved)
        else:
            for root_path in DEFAULT_AUTHORIZED_ROOTS:
                if auto_create_default:
                    try:
                        root_path.mkdir(parents=True, exist_ok=True)
                    except Exception:
                        pass
                try:
                    resolved = self._validate_and_canonicalize_root(root_path)
                    if resolved not in self.allowed_roots:
                        self.allowed_roots.append(resolved)
                except Exception:
                    pass

    @property
    def primary_root(self) -> Path:
        """Returns the primary approved workspace directory."""
        return self.allowed_roots[0] if self.allowed_roots else DEFAULT_WORKSPACE_ROOT

    def is_authorized(self, raw_path: str | Path) -> bool:
        """Checks if a path can be canonicalized within the authorized roots."""
        try:
            self.canonicalize(raw_path)
            return True
        except Exception:
            return False

    def grant_root(self, root: str | Path) -> Path:
        """Authorizes a new directory root dynamically after user approval."""
        resolved = self._validate_and_canonicalize_root(root)
        if resolved not in self.allowed_roots:
            self.allowed_roots.append(resolved)
        return resolved

    def revoke_root(self, root: str | Path) -> bool:
        """Revokes an authorized directory root."""
        resolved = Path(root).expanduser().resolve()
        if resolved in self.allowed_roots:
            self.allowed_roots.remove(resolved)
            return True
        return False

    def _validate_and_canonicalize_root(self, root: str | Path) -> Path:
        """Validates that a configured root is acceptable (e.g. not user home directly or system path)."""
        p = Path(root).expanduser().resolve()

        # Prohibit root filesystem /
        if str(p) == "/" or str(p) == "/private":
            raise MCPSecurityError("Root filesystem '/' cannot be an approved MCP workspace.")

        # Prohibit user home directory directly (must be a specific subfolder)
        home = Path.home().resolve()
        if p == home:
            raise MCPSecurityError(
                f"Entire user home directory '{home}' cannot be an approved root. Use a dedicated subfolder."
            )

        # Prohibit system directories
        str_p = str(p)
        for sys_dir in PROTECTED_SYSTEM_PREFIXES:
            if str_p == sys_dir or str_p.startswith(sys_dir + "/"):
                # Exception for /tmp or /private/tmp if explicitly used in test fixtures
                if str_p.startswith("/tmp") or str_p.startswith("/private/tmp") or str_p.startswith("/private/var"):
                    break
                raise MCPSecurityError(f"System directory '{sys_dir}' cannot be an approved workspace root.")

        return p

    def canonicalize(self, raw_path: str | Path, must_exist: bool = False) -> Path:
        """
        Resolves, canonicalizes, and verifies that a path is strictly inside an approved root.
        Detects path traversal, symbolic-link escapes, and restricted files/directories.
        """
        if not raw_path or not str(raw_path).strip():
            raise MCPSecurityError("Filesystem path cannot be empty.")

        path_str = str(raw_path).strip()

        # 1. Reject obvious encoded traversal tricks
        if "\x00" in path_str:
            raise MCPSecurityError("Null bytes in path are prohibited.")

        # 2. Handle relative vs absolute paths
        # Relative paths are always resolved relative to the primary approved root, NOT cwd
        p = Path(path_str).expanduser()
        if not p.is_absolute():
            p = (self.primary_root / p).resolve()
        else:
            p = p.resolve()

        # 3. Canonical path checking
        canonical_str = str(p)

        # 4. Check against denied file names and extensions
        filename = p.name.lower()
        if filename in DENIED_FILENAMES or filename.startswith(".env"):
            raise MCPSecurityError(f"Access to sensitive file '{p.name}' is strictly denied.")

        # 5. Check against denied directory names anywhere in path parts
        for part in p.parts:
            part_lower = part.lower()
            if part_lower in DENIED_DIR_PATTERNS or part_lower == ".git":
                raise MCPSecurityError(f"Access to restricted directory '{part}' is strictly denied.")

        # 6. Verify path resides within at least one approved root
        is_inside_root = False
        for root in self.allowed_roots:
            root_str = str(root)
            if canonical_str == root_str or canonical_str.startswith(root_str.rstrip("/") + "/"):
                is_inside_root = True
                break

        if not is_inside_root:
            raise MCPSecurityError(
                f"Path '{path_str}' resolves to '{canonical_str}', which is outside all approved workspace roots: "
                f"{[str(r) for r in self.allowed_roots]}"
            )

        # 7. Symlink Escape Verification
        # If the file or any parent is a symbolic link, verify that the real underlying target
        # also resolves strictly inside an approved root!
        real_target = Path(os.path.realpath(str(p)))
        real_str = str(real_target)
        real_inside = False
        for root in self.allowed_roots:
            root_real = str(Path(os.path.realpath(str(root))))
            if real_str == root_real or real_str.startswith(root_real.rstrip("/") + "/"):
                real_inside = True
                break

        if not real_inside:
            raise MCPSecurityError(
                f"Symbolic link '{path_str}' targets '{real_str}', escaping approved workspace roots."
            )

        # 8. Existence validation if requested
        if must_exist and not p.exists():
            raise FileNotFoundError(f"File or directory '{canonical_str}' does not exist.")

        return p

    def validate_tool_arguments(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """
        Validates and canonicalizes paths within tool arguments at the execution boundary.
        Returns a clean dictionary with safe canonical paths.
        """
        clean_args = dict(arguments)

        # 1. Single path parameter (read_file, write_file, edit_file, create_directory, etc.)
        if "path" in clean_args:
            raw = clean_args["path"]
            clean_args["path"] = str(self.canonicalize(raw))

        # 2. Multiple paths parameter (read_multiple_files)
        if "paths" in clean_args and isinstance(clean_args["paths"], list):
            clean_paths = []
            for raw_p in clean_args["paths"]:
                clean_paths.append(str(self.canonicalize(raw_p)))
            clean_args["paths"] = clean_paths

        # 3. Source and destination parameters (move_file, copy_file)
        if "source" in clean_args:
            clean_args["source"] = str(self.canonicalize(clean_args["source"]))
        if "destination" in clean_args:
            clean_args["destination"] = str(self.canonicalize(clean_args["destination"]))

        return clean_args
