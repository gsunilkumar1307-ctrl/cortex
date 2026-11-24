from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .exceptions import MCPConfigurationError, MCPSecurityError
from .models import MCPServerConfig

try:
    from backend.core.contracts import RiskLevel
except ImportError:
    from core.contracts import RiskLevel

# Standard safe system environment variables passed to MCP child processes
SAFE_SYSTEM_ENV_VARS = {
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TERM",
    "NODE_PATH",
    "PYTHONPATH",
}

# Blocklist patterns for sensitive environment variable keys (case-insensitive)
SENSITIVE_ENV_KEY_PATTERNS = {
    "SECRET",
    "API_KEY",
    "APIKEY",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "AUTH",
    "SESSION",
    "PRIVATE_KEY",
    "CREDENTIAL",
    "GEMINI",
    "CORTEX",
    "OPENAI",
    "ANTHROPIC",
    "AWS",
    "GITHUB",
}

# Dangerous shell metacharacters prohibited in server commands and arguments
DANGEROUS_COMMAND_CHARS = re.compile(r"[;&|`$<>()\n\r]")


def sanitize_environment(custom_env: dict[str, str] | None = None) -> dict[str, str]:
    """
    Constructs a sanitized environment dictionary for an MCP child process.
    Strips all Cortex secrets, API keys, credentials, and session tokens.
    """
    clean_env: dict[str, str] = {}

    # 1. Inherit only safe system variables from os.environ
    for key, val in os.environ.items():
        if key in SAFE_SYSTEM_ENV_VARS:
            clean_env[key] = val

    # 2. Add custom env vars if they do not match any sensitive key pattern
    if custom_env:
        for k, v in custom_env.items():
            k_upper = k.upper().replace("-", "_")
            if any(pattern in k_upper for pattern in SENSITIVE_ENV_KEY_PATTERNS):
                continue  # Silently omit blocked sensitive variable
            clean_env[k] = str(v)

    # 3. Ensure a robust PATH containing local and standard system tool directories
    essential_dirs = [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    current_path_dirs = clean_env.get("PATH", "").split(":") if "PATH" in clean_env else []
    for d in essential_dirs:
        if d not in current_path_dirs:
            current_path_dirs.insert(0, d)
    clean_env["PATH"] = ":".join(d for d in current_path_dirs if d)

    return clean_env


def validate_server_config(config: MCPServerConfig) -> None:
    """
    Validates an MCPServerConfig against security restrictions.
    Prohibits shell execution and dangerous characters in commands.
    """
    if not config.name or not config.name.strip():
        raise MCPConfigurationError("MCP server name cannot be empty.")

    if not re.match(r"^[a-zA-Z0-9_\-]+$", config.name):
        raise MCPConfigurationError(
            f"Invalid server name '{config.name}'. Server names must be alphanumeric with underscores or dashes."
        )

    if not config.command or not config.command.strip():
        raise MCPConfigurationError(f"Server '{config.name}' must specify a valid executable command.")

    if DANGEROUS_COMMAND_CHARS.search(config.command):
        raise MCPSecurityError(
            f"Command '{config.command}' contains prohibited shell metacharacters. Shell injection is blocked."
        )

    for arg in config.args:
        if DANGEROUS_COMMAND_CHARS.search(arg):
            raise MCPSecurityError(
                f"Argument '{arg}' in server '{config.name}' contains prohibited shell metacharacters."
            )

    if config.timeout_seconds <= 0:
        raise MCPConfigurationError(f"Server '{config.name}' timeout_seconds must be positive.")


def load_mcp_config(config_source: str | Path | dict[str, Any]) -> dict[str, MCPServerConfig]:
    """
    Loads and validates MCP server configurations from a JSON file, path, or raw dictionary.
    """
    raw_data: dict[str, Any] = {}

    if isinstance(config_source, (str, Path)):
        p = Path(config_source)
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            raise MCPConfigurationError(f"Failed to parse MCP configuration file {p}: {e}") from e
    elif isinstance(config_source, dict):
        raw_data = config_source
    else:
        raise MCPConfigurationError(f"Unsupported configuration source type: {type(config_source)}")

    servers_dict = raw_data.get("mcpServers", raw_data)
    if not isinstance(servers_dict, dict):
        raise MCPConfigurationError("MCP configuration must contain a dictionary of server definitions.")

    validated_configs: dict[str, MCPServerConfig] = {}

    for name, srv_data in servers_dict.items():
        if not isinstance(srv_data, dict):
            continue

        raw_risk = srv_data.get("default_risk_level", "medium").lower()
        try:
            risk_level = RiskLevel(raw_risk)
        except ValueError:
            risk_level = RiskLevel.MEDIUM

        raw_cmd = srv_data.get("command", "")
        import shutil
        essential_dirs = [
            str(Path.home() / ".local" / "bin"),
            "/usr/local/bin",
            "/opt/homebrew/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
        search_path = ":".join(essential_dirs + [os.environ.get("PATH", "")])
        resolved_cmd = shutil.which(raw_cmd, path=search_path) if (raw_cmd and not os.path.isabs(raw_cmd)) else raw_cmd
        if not resolved_cmd:
            resolved_cmd = raw_cmd

        cfg = MCPServerConfig(
            name=name,
            command=resolved_cmd,
            args=srv_data.get("args", []),
            env=srv_data.get("env", {}),
            cwd=srv_data.get("cwd"),
            enabled=srv_data.get("enabled", True),
            timeout_seconds=float(srv_data.get("timeout_seconds", 30.0)),
            auto_restart=srv_data.get("auto_restart", True),
            max_restarts=int(srv_data.get("max_restarts", 3)),
            restart_window_seconds=float(srv_data.get("restart_window_seconds", 60.0)),
            allowed_tools=srv_data.get("allowed_tools"),
            blocked_tools=srv_data.get("blocked_tools", []),
            default_risk_level=risk_level,
            requires_approval=bool(srv_data.get("requires_approval", False)),
            irreversible=bool(srv_data.get("irreversible", False)),
        )
        validate_server_config(cfg)
        validated_configs[name] = cfg

    return validated_configs


def get_filesystem_server_config(
    allowed_dirs: list[str | Path] | None = None,
    allowed_dir: str | Path | None = None,
    server_version: str = "2.3.0",
) -> MCPServerConfig:
    """Generates the verified MCPServerConfig for the official filesystem MCP server."""
    if allowed_dirs:
        dirs = [Path(d).expanduser() for d in allowed_dirs]
    elif allowed_dir:
        dirs = [Path(allowed_dir).expanduser()]
    else:
        dirs = [
            Path.home() / "Desktop",
            Path.home() / "Documents",
            Path.home() / "Downloads",
            Path.home() / "Documents" / "CortexWorkspace",
        ]

    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    args = ["-y", f"@modelcontextprotocol/server-filesystem@{server_version}"] + [str(d.resolve()) for d in dirs]
    return MCPServerConfig(
        name="filesystem",
        command="npx",
        args=args,
        default_risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        timeout_seconds=30.0,
    )


def get_fetch_server_config(
    uvx_path: str | None = None,
    timeout_seconds: float = 30.0,
) -> MCPServerConfig:
    """Generates the verified MCPServerConfig for the official MCP Fetch server (mcp-server-fetch)."""
    import shutil
    cmd = uvx_path
    if not cmd:
        local_uvx = Path.home() / ".local" / "bin" / "uvx"
        if local_uvx.exists() and os.access(local_uvx, os.X_OK):
            cmd = str(local_uvx)
        else:
            cmd = shutil.which("uvx") or "uvx"

    return MCPServerConfig(
        name="fetch",
        command=cmd,
        args=["mcp-server-fetch"],
        default_risk_level=RiskLevel.LOW,
        requires_approval=False,
        timeout_seconds=timeout_seconds,
    )


def get_playwright_server_config(
    package_version: str = "0.0.85",
    headless: bool | None = None,
    timeout_seconds: float = 60.0,
) -> MCPServerConfig:
    """
    Generates the verified MCPServerConfig for the official Playwright MCP server (@playwright/mcp).
    By default on macOS, launches a headed (visible) browser session. Headless can be requested
    explicitly or via CORTEX_HEADLESS_BROWSER=1 in automated CI environments.
    """
    import shutil
    if headless is None:
        headless = os.getenv("CORTEX_HEADLESS_BROWSER") == "1"

    cmd = shutil.which("npx") or "npx"
    args = ["-y", f"@playwright/mcp@{package_version}", "--isolated"]
    if headless:
        args.append("--headless")
    return MCPServerConfig(
        name="playwright",
        command=cmd,
        args=args,
        default_risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        timeout_seconds=timeout_seconds,
    )


# Permitted initial tool surface for apple-mail MCP (P7.1 Safe Initial Tool Exposure)
SAFE_APPLE_MAIL_TOOLS = [
    "health-check",
    "doctor",
    "get-sync-status",
    "get-mail-stats",
    "list-mailboxes",
    "list-accounts",
    "get-unread-count",
    "search-messages",
    "list-messages",
    "get-message",
    "get-message-headers",
    "get-thread",
    "list-attachments",
    "get-attachment-metadata",
    "create-draft",
    "update-saved-draft",
]

# Explicitly blocked sending tools strictly prohibited from model execution in P7.1
BLOCKED_APPLE_MAIL_TOOLS = [
    "send-email",
    "send-serial-email",
    "reply-to-message",
    "forward-message",
]


def get_apple_mail_server_config(
    package_version: str = "2.20.57",
    timeout_seconds: float = 30.0,
) -> MCPServerConfig:
    """
    Generates the verified MCPServerConfig for the official Apple Mail MCP server (apple-mail-mcp).
    Restricts tool exposure strictly to read, search, status, and draft operations.
    Sending tools (send-email, send-serial-email, reply-to-message, forward-message) are strictly blocked.
    """
    import shutil

    essential_dirs = [
        str(Path.home() / ".local" / "bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    search_path = ":".join(essential_dirs + [os.environ.get("PATH", "")])
    cmd = shutil.which("npx", path=search_path) or "npx"

    return MCPServerConfig(
        name="apple-mail",
        command=cmd,
        args=["-y", f"apple-mail-mcp@{package_version}"],
        allowed_tools=list(SAFE_APPLE_MAIL_TOOLS),
        blocked_tools=list(BLOCKED_APPLE_MAIL_TOOLS),
        default_risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        timeout_seconds=timeout_seconds,
    )

