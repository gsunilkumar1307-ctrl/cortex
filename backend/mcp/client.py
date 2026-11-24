from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from .exceptions import (
    MCPConnectionError,
    MCPError,
    MCPProtocolError,
    MCPSecurityError,
    MCPTimeoutError,
)
from .models import MCPToolDefinition, MCPToolResult
from .process import MCPProcess


class MCPClient:
    """
    Asynchronous JSON-RPC 2.0 stdio client implementing the Model Context Protocol (MCP).
    Handles line-delimited message framing, request/response tracking, handshakes,
    tool discovery, tool invocation, and connection drops.
    """

    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, process: MCPProcess, on_tools_changed: Callable[[], None] | None = None) -> None:
        self.process = process
        self.on_tools_changed = on_tools_changed
        self._request_counter = 0
        self._pending_requests: dict[int | str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self.__write_lock: asyncio.Lock | None = None
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self.is_initialized = False

    @property
    def _write_lock(self) -> asyncio.Lock:
        if self.__write_lock is None:
            self.__write_lock = asyncio.Lock()
        return self.__write_lock

    async def connect(self, timeout: float = 10.0) -> None:
        """Starts the process (if not running) and begins the stdio read loop."""
        # Cancel any previous reader task to prevent concurrent reads on the same stream
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

        self._pending_requests.clear()
        self.is_initialized = False

        if not self.process.is_alive:
            await self.process.start()

        self._reader_task = asyncio.create_task(self._read_stdout_loop())
        try:
            await self.initialize(timeout=timeout)
        except Exception:
            # If initialization fails, clean up the reader task and reset
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except (asyncio.CancelledError, Exception):
                    pass
                self._reader_task = None
            self._fail_all_pending("Initialization failed.")
            raise

    async def initialize(self, timeout: float = 10.0) -> dict[str, Any]:
        """Executes the standard MCP initialization handshake."""
        init_params = {
            "protocolVersion": self.PROTOCOL_VERSION,
            "capabilities": {
                "roots": {"listChanged": False},
                "sampling": {},
            },
            "clientInfo": {
                "name": "cortex-agent",
                "version": "0.2.0",
            },
        }

        try:
            result = await self.send_request("initialize", init_params, timeout=timeout)
            self.server_info = result.get("serverInfo", {})
            self.server_capabilities = result.get("capabilities", {})
            self.is_initialized = True

            # Send required initialized confirmation notification
            await self.send_notification("notifications/initialized")
            return result
        except Exception as e:
            self.is_initialized = False
            raise MCPConnectionError(f"MCP initialization failed for '{self.process.config.name}': {e}") from e

    async def ping(self, timeout: float = 5.0) -> bool:
        """Sends an MCP ping request to check server responsiveness."""
        if not self.process.is_alive:
            return False
        try:
            await self.send_request("ping", {}, timeout=timeout)
            return True
        except Exception:
            return False

    async def list_tools(self, timeout: float = 10.0) -> list[MCPToolDefinition]:
        """Discovers available tools from the server via tools/list."""
        resp = await self.send_request("tools/list", {}, timeout=timeout)
        raw_tools = resp.get("tools", [])
        if not isinstance(raw_tools, list):
            raise MCPProtocolError(f"Expected list of tools, got {type(raw_tools)}")

        definitions: list[MCPToolDefinition] = []
        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            name = t.get("name", "")
            if not name:
                continue

            # Respect server tool allowlist / blocklist policies
            if not self.process.config.is_tool_allowed(name):
                continue

            desc = t.get("description", "")
            schema = t.get("inputSchema", {})
            risk = self.process.config.default_risk_level
            if self.process.config.name == "apple-mail":
                if name.startswith(("list", "get", "search", "health", "doctor")):
                    try:
                        from backend.core.contracts import RiskLevel
                    except ImportError:
                        from core.contracts import RiskLevel
                    risk = RiskLevel.LOW

            definitions.append(
                MCPToolDefinition(
                    name=name,
                    server_name=self.process.config.name,
                    description=desc,
                    input_schema=schema,
                    risk_level=risk,
                    requires_approval=self.process.config.requires_approval,
                    irreversible=self.process.config.irreversible,
                )
            )
        return definitions

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout: float | None = None,
    ) -> MCPToolResult:
        """Executes a tool on the server via tools/call."""
        if not self.process.config.is_tool_allowed(name):
            raise MCPSecurityError(
                f"Tool '{name}' is not allowed on MCP server '{self.process.config.name}' by security policy."
            )

        effective_timeout = timeout or self.process.config.timeout_seconds
        params = {
            "name": name,
            "arguments": arguments,
        }

        try:
            resp = await self.send_request("tools/call", params, timeout=effective_timeout)
            is_error = bool(resp.get("isError", False))
            content = resp.get("content", [])
            return MCPToolResult(content=content, is_error=is_error, raw_response=resp)
        except Exception as e:
            if isinstance(e, (MCPTimeoutError, MCPConnectionError, MCPSecurityError)):
                raise
            raise MCPError(f"Tool call '{name}' failed on server '{self.process.config.name}': {e}") from e

    async def send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Sends a JSON-RPC 2.0 request and awaits the matching response."""
        if not self.process.is_alive or not self.process.process or not self.process.process.stdin:
            raise MCPConnectionError(f"Server '{self.process.config.name}' is not running.")

        self._request_counter += 1
        req_id = self._request_counter

        msg = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            data = (json.dumps(msg) + "\n").encode("utf-8")
            async with self._write_lock:
                self.process.process.stdin.write(data)
                await self.process.process.stdin.drain()

            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as e:
            # Send cancellation notification to inform server
            asyncio.create_task(self._send_cancellation(req_id))
            raise MCPTimeoutError(
                f"Request {method} (id={req_id}) to '{self.process.config.name}' timed out after {timeout}s"
            ) from e
        finally:
            self._pending_requests.pop(req_id, None)

    async def _send_cancellation(self, req_id: int | str) -> None:
        """Sends a notifications/cancelled notice for an abandoned request."""
        try:
            await self.send_notification("notifications/cancelled", {"requestId": req_id, "reason": "Client timeout"})
        except Exception:
            pass

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Sends a JSON-RPC 2.0 notification (no response expected)."""
        if not self.process.is_alive or not self.process.process or not self.process.process.stdin:
            return

        msg: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            msg["params"] = params

        data = (json.dumps(msg) + "\n").encode("utf-8")
        async with self._write_lock:
            self.process.process.stdin.write(data)
            await self.process.process.stdin.drain()

    async def _read_stdout_loop(self) -> None:
        """Continuously reads line-delimited JSON-RPC messages from server stdout."""
        if not self.process.process or not self.process.process.stdout:
            return

        stdout = self.process.process.stdout
        try:
            while not stdout.at_eof():
                line = await stdout.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue

                try:
                    payload = json.loads(decoded)
                    self._handle_incoming_message(payload)
                except json.JSONDecodeError:
                    # Ignore malformed non-JSON lines (e.g. occasional logger output from child)
                    continue
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            # If the stdout loop ends, resolve all pending requests with error
            self._fail_all_pending("Server connection closed.")

    def _handle_incoming_message(self, msg: dict[str, Any]) -> None:
        """Routes parsed JSON-RPC message to appropriate handler."""
        # 1. Response to a pending request
        if "id" in msg and ("result" in msg or "error" in msg):
            req_id = msg["id"]
            future = self._pending_requests.get(req_id)
            if future and not future.done():
                if "error" in msg:
                    err = msg["error"]
                    err_msg = err.get("message", "Unknown error") if isinstance(err, dict) else str(err)
                    future.set_exception(MCPError(err_msg))
                else:
                    future.set_result(msg.get("result", {}))
            return

        # 2. Server-initiated requests (e.g. roots/list, ping)
        if "method" in msg and "id" in msg:
            req_id = msg["id"]
            method = msg.get("method", "")
            asyncio.create_task(self._handle_server_request(req_id, method, msg.get("params", {})))
            return

        # 3. Server notifications
        if "method" in msg and "id" not in msg:
            method = msg.get("method", "")
            if method == "notifications/tools/list_changed":
                if self.on_tools_changed and callable(self.on_tools_changed):
                    self.on_tools_changed()
            return

    async def _handle_server_request(self, req_id: Any, method: str, params: dict[str, Any]) -> None:
        """Handles server-initiated requests such as roots/list or ping."""
        if method == "roots/list":
            roots = []
            if self.process.config.args:
                for arg in self.process.config.args:
                    arg_str = str(arg)
                    if not arg_str.startswith("-") and not arg_str.startswith("@"):
                        try:
                            p = Path(arg_str).expanduser().resolve()
                            if p.exists() and p.is_dir():
                                roots.append({"uri": f"file://{p}", "name": p.name or "workspace"})
                        except Exception:
                            pass
            if not roots:
                roots = [{"uri": f"file://{Path.home() / 'Documents' / 'CortexWorkspace'}", "name": "workspace"}]
            await self._send_raw_response(req_id, result={"roots": roots})
        elif method == "ping":
            await self._send_raw_response(req_id, result={})
        else:
            await self._send_raw_response(
                req_id,
                error={"code": -32601, "message": f"Method '{method}' not supported by client."},
            )

    async def _send_raw_response(
        self,
        req_id: Any,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Sends a JSON-RPC response back to the server."""
        if not self.process.is_alive or not self.process.process or not self.process.process.stdin:
            return
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
        if error is not None:
            payload["error"] = error
        else:
            payload["result"] = result or {}
        data = (json.dumps(payload) + "\n").encode("utf-8")
        try:
            async with self._write_lock:
                self.process.process.stdin.write(data)
                await self.process.process.stdin.drain()
        except Exception:
            pass

    def _fail_all_pending(self, reason: str) -> None:
        """Fails all in-flight requests when connection is terminated."""
        for req_id, future in list(self._pending_requests.items()):
            if not future.done():
                future.set_exception(MCPConnectionError(f"{reason} (id={req_id})"))
        self._pending_requests.clear()

    async def disconnect(self) -> None:
        """Terminates client reader loop and pending requests."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        self._fail_all_pending("Client disconnected.")
        self.is_initialized = False
