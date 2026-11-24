from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from typing import Any, Callable

from .client import MCPClient
from .config import load_mcp_config
from .exceptions import (
    MCPConfigurationError,
    MCPConnectionError,
    MCPError,
    MCPProcessError,
    MCPSecurityError,
    MCPTimeoutError,
    MCPToolNotFoundError,
)
from .models import MCPServerConfig, MCPServerStatus, MCPToolDefinition, MCPToolResult
from .process import MCPProcess


class _ManagedServer:
    """Internal container tracking a single managed server instance and its client."""

    def __init__(self, config: MCPServerConfig, manager: MCPServerManager) -> None:
        self.config = config
        self.manager = manager
        self.process: MCPProcess = MCPProcess(config, on_exit=self._on_process_exit)
        self.client: MCPClient = MCPClient(self.process, on_tools_changed=self._on_tools_changed)
        self.tools: dict[str, MCPToolDefinition] = {}
        self.status: MCPServerStatus = MCPServerStatus.STOPPED

    def _on_process_exit(self, returncode: int | None) -> None:
        """Callback triggered when the underlying process terminates."""
        if self.status != MCPServerStatus.STOPPED:
            self.status = MCPServerStatus.DISCONNECTED
            if self.config.auto_restart and self.process.can_restart():
                asyncio.create_task(self._auto_restart())
            elif self.config.auto_restart and not self.process.can_restart():
                self.status = MCPServerStatus.DEGRADED

    async def _auto_restart(self) -> None:
        """Attempts an automated restart following unexpected process exit."""
        self.process.record_restart()
        try:
            await asyncio.sleep(1.0)
            await self.start()
        except Exception:
            self.status = MCPServerStatus.ERROR

    def _on_tools_changed(self) -> None:
        """Callback triggered when server notifies that available tools have changed."""
        asyncio.create_task(self.refresh_tools())

    async def start(self, timeout: float | None = None) -> None:
        """Starts the process, establishes protocol connection, and caches tools."""
        # If already connected with tools discovered and process is alive, no need to re-spawn
        if self.process.is_alive and self.status == MCPServerStatus.CONNECTED and self.tools:
            return

        effective_timeout = timeout if timeout is not None else self.config.timeout_seconds

        # Cleanly stop any lingering process or client if previously running/errored
        if self.process.is_alive or self.status != MCPServerStatus.STOPPED:
            try:
                await self.stop(timeout=2.0)
            except Exception:
                pass

        self.status = MCPServerStatus.STARTING
        try:
            connect_timeout = max(5.0, effective_timeout * 0.7)
            refresh_timeout = max(5.0, effective_timeout * 0.3)
            await self.client.connect(timeout=connect_timeout)
            await self.refresh_tools(timeout=refresh_timeout)
            self.status = MCPServerStatus.CONNECTED
        except Exception as e:
            self.status = MCPServerStatus.ERROR
            # Clean up lingering child process and client to prevent zombie processes and broken pipes
            try:
                await self.client.disconnect()
                await self.process.stop(timeout=2.0)
            except Exception:
                pass
            raise MCPProcessError(f"Failed to start server '{self.config.name}': {e}") from e

    async def refresh_tools(self, timeout: float = 10.0) -> list[MCPToolDefinition]:
        """Discovers tools and updates internal tool cache."""
        discovered = await self.client.list_tools(timeout=timeout)
        self.tools = {t.name: t for t in discovered}
        if self.manager.on_tools_updated:
            self.manager.on_tools_updated(self.config.name, list(self.tools.values()))
        return list(self.tools.values())

    async def stop(self, timeout: float = 3.0) -> None:
        """Gracefully disconnects client and terminates process."""
        self.status = MCPServerStatus.STOPPED
        await self.client.disconnect()
        await self.process.stop(timeout=timeout)
        self.tools.clear()


class MCPServerManager:
    """
    Coordinates lifecycle, health monitoring, and tool invocation across all local MCP servers.
    Operates a dedicated background asyncio event loop thread for robust, non-blocking stdio I/O
    compatible with synchronous and asynchronous Cortex callers alike.
    """

    def __init__(
        self,
        config_source: str | dict[str, Any] | None = None,
        on_tools_updated: Callable[[str, list[MCPToolDefinition]], None] | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self.on_tools_updated = on_tools_updated
        self._servers: dict[str, _ManagedServer] = {}

        if loop is not None:
            self._loop = loop
            self._own_loop = False
            self._thread = None
        else:
            self._loop = asyncio.new_event_loop()
            self._own_loop = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="Cortex-MCP-Loop")
            self._thread.start()

        if config_source:
            configs = load_mcp_config(config_source)
            for cfg in configs.values():
                self.register_server(cfg)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_sync(self, coro: Any, timeout: float | None = None) -> Any:
        """Executes a coroutine on the managed MCP background event loop safely from any thread."""
        if not self._loop.is_running():
            raise MCPConnectionError("MCP event loop is not running.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            future.cancel()
            raise MCPTimeoutError(f"Operation on MCP event loop timed out after {timeout}s") from e

    def register_server(self, config: MCPServerConfig) -> None:
        """Registers a server configuration without immediately starting the process."""
        if config.name in self._servers:
            server = self._servers[config.name]
            server.config = config
            server.process.config = config
        else:
            self._servers[config.name] = _ManagedServer(config, self)

    def unregister_server(self, name: str) -> None:
        """Removes a server from management."""
        self._servers.pop(name, None)

    def get_server_config(self, name: str) -> MCPServerConfig | None:
        server = self._servers.get(name)
        return server.config if server else None

    def get_server_status(self, name: str) -> MCPServerStatus:
        server = self._servers.get(name)
        if not server:
            return MCPServerStatus.STOPPED
        return server.status

    def list_servers(self) -> list[str]:
        return list(self._servers.keys())

    # ── Asynchronous Lifecycle Methods ────────────────────────────────────────

    async def start_server_async(self, name: str, timeout: float | None = None) -> None:
        """Starts a specific configured server by name (async)."""
        server = self._servers.get(name)
        if not server:
            raise MCPConfigurationError(f"Server '{name}' is not registered.")
        if not server.config.enabled:
            return
        effective_timeout = timeout if timeout is not None else server.config.timeout_seconds
        await server.start(timeout=effective_timeout)

    async def stop_server_async(self, name: str, timeout: float = 3.0) -> None:
        """Stops a specific server process (async)."""
        server = self._servers.get(name)
        if server:
            await server.stop(timeout=timeout)

    async def restart_server_async(self, name: str, timeout: float | None = None) -> None:
        """Restarts a server process and re-establishes stdio connection (async)."""
        server = self._servers.get(name)
        effective_timeout = timeout if timeout is not None else (server.config.timeout_seconds if server else 30.0)
        await self.stop_server_async(name)
        await self.start_server_async(name, timeout=effective_timeout)

    async def start_all_async(self, timeout: float = 10.0) -> None:
        """Starts all registered and enabled servers concurrently (async)."""
        tasks = []
        for server in self._servers.values():
            if server.config.enabled:
                tasks.append(server.start(timeout=timeout))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all_async(self, timeout: float = 3.0) -> None:
        """Stops all running server processes cleanly (async)."""
        tasks = [server.stop(timeout=timeout) for server in self._servers.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def call_tool_async(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> MCPToolResult:
        """Routes a tool call to the specified server over stdio (async)."""
        server = self._servers.get(server_name)
        if not server:
            raise MCPConfigurationError(f"Server '{server_name}' is not registered.")

        if not server.config.is_tool_allowed(tool_name):
            raise MCPSecurityError(
                f"Tool '{tool_name}' is not allowed on MCP server '{server_name}' by security policy."
            )

        if server.status != MCPServerStatus.CONNECTED:
            if server.config.enabled and not server.process.is_alive:
                await server.start()
            else:
                raise MCPConnectionError(f"Server '{server_name}' is not connected (status: {server.status.value}).")

        if tool_name not in server.tools:
            await server.refresh_tools()
            if tool_name not in server.tools:
                raise MCPToolNotFoundError(f"Tool '{tool_name}' not found on server '{server_name}'.")

        return await server.client.call_tool(tool_name, arguments, timeout=timeout)

    async def ping_all_async(self, timeout: float = 5.0) -> dict[str, bool]:
        """Pings all connected servers and returns their responsiveness status (async)."""
        results: dict[str, bool] = {}
        for name, srv in self._servers.items():
            if srv.status == MCPServerStatus.CONNECTED:
                results[name] = await srv.client.ping(timeout=timeout)
            else:
                results[name] = False
        return results

    # ── Synchronous Lifecycle Methods (Callable from anywhere) ────────────────

    def start_server(self, name: str, timeout: float | None = None) -> None:
        """Starts a specific configured server by name (synchronous)."""
        server = self._servers.get(name)
        effective_timeout = timeout if timeout is not None else (server.config.timeout_seconds if server else 30.0)
        self.run_sync(self.start_server_async(name, timeout=effective_timeout), timeout=effective_timeout + 5.0)

    def stop_server(self, name: str, timeout: float = 3.0) -> None:
        """Stops a specific server process (synchronous)."""
        self.run_sync(self.stop_server_async(name, timeout=timeout), timeout=timeout + 2.0)

    def restart_server(self, name: str, timeout: float | None = None) -> None:
        """Restarts a server process and re-establishes stdio connection (synchronous)."""
        server = self._servers.get(name)
        effective_timeout = timeout if timeout is not None else (server.config.timeout_seconds if server else 30.0)
        self.run_sync(self.restart_server_async(name, timeout=effective_timeout), timeout=effective_timeout + 6.0)

    def start_all(self, timeout: float = 10.0) -> None:
        """Starts all registered and enabled servers concurrently (synchronous)."""
        self.run_sync(self.start_all_async(timeout=timeout), timeout=timeout + 3.0)

    def stop_all(self, timeout: float = 3.0) -> None:
        """Stops all running server processes cleanly (synchronous)."""
        self.run_sync(self.stop_all_async(timeout=timeout), timeout=timeout + 2.0)

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> MCPToolResult:
        """Routes a tool call to the specified server (synchronous)."""
        sync_timeout = (timeout + 2.0) if timeout is not None else None
        return self.run_sync(
            self.call_tool_async(server_name, tool_name, arguments, timeout=timeout),
            timeout=sync_timeout,
        )

    def ping_all(self, timeout: float = 5.0) -> dict[str, bool]:
        """Pings all connected servers (synchronous)."""
        return self.run_sync(self.ping_all_async(timeout=timeout), timeout=timeout + 1.0)

    def get_tool_definitions(self, server_name: str | None = None) -> list[MCPToolDefinition]:
        """Returns all currently discovered tools across all (or a specific) server."""
        if server_name:
            srv = self._servers.get(server_name)
            return list(srv.tools.values()) if srv else []

        all_tools: list[MCPToolDefinition] = []
        for srv in self._servers.values():
            all_tools.extend(srv.tools.values())
        return all_tools

    def shutdown(self, timeout: float = 3.0) -> None:
        """Terminates all server processes and stops the background event loop."""
        try:
            if self._loop.is_running():
                self.run_sync(self.stop_all_async(timeout=timeout), timeout=timeout + 1.0)
        except Exception:
            pass
        finally:
            if self._own_loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=2.0)

    def __del__(self) -> None:
        self.shutdown()
