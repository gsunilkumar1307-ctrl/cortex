from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from backend.core.contracts import RiskLevel, TaskCommand
except ImportError:
    from core.contracts import RiskLevel, TaskCommand


class MCPServerStatus(str, Enum):
    """Lifecycle status of a supervised MCP server subprocess."""
    STOPPED = "stopped"
    STARTING = "starting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    DEGRADED = "degraded"


@dataclass
class MCPServerConfig:
    """Validated configuration for a local MCP server subprocess."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True
    timeout_seconds: float = 30.0
    auto_restart: bool = True
    max_restarts: int = 3
    restart_window_seconds: float = 60.0
    allowed_tools: list[str] | None = None  # None = all tools allowed unless blocked
    blocked_tools: list[str] = field(default_factory=list)
    default_risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    irreversible: bool = False

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Determines whether a discovered tool name is permitted by policy."""
        if tool_name in self.blocked_tools:
            return False
        if self.allowed_tools is not None:
            return tool_name in self.allowed_tools
        return True


@dataclass
class MCPToolDefinition:
    """Metadata definition of an MCP tool discovered from an MCP server."""
    name: str
    server_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False
    irreversible: bool = False
    command: TaskCommand = TaskCommand.UNKNOWN


@dataclass
class MCPToolCall:
    """Invocation specification for an MCP tool."""
    tool_name: str
    arguments: dict[str, Any]
    call_id: str = ""


@dataclass
class MCPToolResult:
    """Structured result returned by an MCP tool invocation."""
    content: list[dict[str, Any]] | str | Any
    is_error: bool = False
    raw_response: dict[str, Any] | None = None

    def get_text_content(self) -> str:
        """Extracts text content from structured MCP content blocks."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            texts = []
            for item in self.content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and "text" in item:
                        texts.append(str(item["text"]))
                    elif "text" in item:
                        texts.append(str(item["text"]))
                    else:
                        texts.append(str(item))
                else:
                    texts.append(str(item))
            return "\n".join(texts)
        return str(self.content) if self.content is not None else ""
