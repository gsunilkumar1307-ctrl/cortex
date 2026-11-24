from __future__ import annotations


class MCPError(Exception):
    """Base exception for all Model Context Protocol (MCP) subsystem errors."""
    pass


class MCPConfigurationError(MCPError):
    """Raised when an MCP server or tool configuration is invalid."""
    pass


class MCPProcessError(MCPError):
    """Raised when an MCP subprocess fails to spawn, crashes, or exits unexpectedly."""
    pass


class MCPConnectionError(MCPError):
    """Raised when communication with an MCP server fails (e.g. broken pipe)."""
    pass


class MCPTimeoutError(MCPError):
    """Raised when an MCP protocol handshake, ping, or tool call exceeds timeout."""
    pass


class MCPProtocolError(MCPError):
    """Raised when a received JSON-RPC message violates the MCP protocol."""
    pass


class MCPToolNotFoundError(MCPError):
    """Raised when an invoked tool is not offered by the specified MCP server."""
    pass


class MCPValidationError(MCPError):
    """Raised when input parameters or output schemas fail validation."""
    pass


class MCPSecurityError(MCPError):
    """Raised when a security policy (path jail, blocked command, unauthorized action) is violated."""
    pass
