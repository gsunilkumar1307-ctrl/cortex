from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from collections import deque
from typing import Callable, Any

from .config import sanitize_environment, validate_server_config
from .exceptions import MCPProcessError, MCPTimeoutError
from .models import MCPServerConfig, MCPServerStatus


class MCPProcess:
    """
    Supervises a single local MCP server subprocess over stdio.
    Enforces non-shell execution, environment sanitization, stderr monitoring,
    graceful termination, and restart throttling.
    """

    def __init__(self, config: MCPServerConfig, on_exit: Callable[[int | None], None] | None = None) -> None:
        self.config = config
        self.on_exit = on_exit
        self.process: asyncio.subprocess.Process | None = None
        self.status: MCPServerStatus = MCPServerStatus.STOPPED
        self.stderr_lines: deque[str] = deque(maxlen=100)
        self._stderr_task: asyncio.Task[None] | None = None
        self._wait_task: asyncio.Task[None] | None = None
        self._restart_timestamps: list[float] = []
        self.__lock: asyncio.Lock | None = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self.__lock is None:
            self.__lock = asyncio.Lock()
        return self.__lock

    @property
    def is_alive(self) -> bool:
        """Returns True if the underlying process is currently running."""
        return self.process is not None and self.process.returncode is None

    @property
    def returncode(self) -> int | None:
        return self.process.returncode if self.process else None

    async def start(self) -> None:
        """Spawns the MCP server child process using non-shell exec."""
        async with self._lock:
            if self.is_alive:
                return

            validate_server_config(self.config)
            sanitized_env = sanitize_environment(self.config.env)

            self.status = MCPServerStatus.STARTING
            try:
                # We strictly use create_subprocess_exec (NEVER create_subprocess_shell)
                # to prevent shell injection vulnerabilities.
                # Use a 16MB stream buffer limit so large MCP responses (e.g. Playwright snapshots) do not trigger LimitOverrunError
                self.process = await asyncio.create_subprocess_exec(
                    self.config.command,
                    *self.config.args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    limit=16 * 1024 * 1024,
                    env=sanitized_env,
                    cwd=self.config.cwd,
                    start_new_session=True,  # Isolate in its own process group
                )
                self.status = MCPServerStatus.CONNECTED
                self._stderr_task = asyncio.create_task(self._read_stderr_loop())
                self._wait_task = asyncio.create_task(self._monitor_exit_loop())
            except Exception as e:
                self.status = MCPServerStatus.ERROR
                raise MCPProcessError(f"Failed to spawn MCP server '{self.config.name}': {e}") from e

    async def _read_stderr_loop(self) -> None:
        """Reads and stores child process stderr output for diagnostics."""
        if not self.process or not self.process.stderr:
            return
        try:
            while not self.process.stderr.at_eof():
                line = await self.process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    self.stderr_lines.append(decoded)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _monitor_exit_loop(self) -> None:
        """Watches for unexpected child process termination."""
        if not self.process:
            return
        try:
            await self.process.wait()
            rc = self.process.returncode
            if self.status != MCPServerStatus.STOPPED:
                self.status = MCPServerStatus.DISCONNECTED
            if self.on_exit and callable(self.on_exit):
                self.on_exit(rc)
        except asyncio.CancelledError:
            pass

    def can_restart(self) -> bool:
        """Evaluates restart throttling circuit breaker."""
        now = time.time()
        # Filter out timestamps older than the restart window
        window_start = now - self.config.restart_window_seconds
        self._restart_timestamps = [t for t in self._restart_timestamps if t >= window_start]
        return len(self._restart_timestamps) < self.config.max_restarts

    def record_restart(self) -> None:
        """Records a restart event for throttling evaluation."""
        self._restart_timestamps.append(time.time())

    async def stop(self, timeout: float = 3.0) -> None:
        """Gracefully terminates the child process and frees stdio resources."""
        async with self._lock:
            self.status = MCPServerStatus.STOPPED

            if self._stderr_task and not self._stderr_task.done():
                self._stderr_task.cancel()
            if self._wait_task and not self._wait_task.done():
                self._wait_task.cancel()

            if not self.process:
                return

            if self.process.returncode is None:
                # 1. Try graceful SIGTERM
                try:
                    # Terminate entire process group
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    try:
                        self.process.terminate()
                    except ProcessLookupError:
                        pass

                # 2. Await clean exit within timeout
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    # 3. Escalate to SIGKILL if still running
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        try:
                            self.process.kill()
                        except ProcessLookupError:
                            pass
                    try:
                        await asyncio.wait_for(self.process.wait(), timeout=1.0)
                    except Exception:
                        pass

            # Close standard streams
            if self.process.stdin:
                try:
                    self.process.stdin.close()
                except Exception:
                    pass

            self.process = None

    def get_last_stderr(self, lines: int = 10) -> str:
        """Returns the most recent stderr output lines from the server process."""
        recent = list(self.stderr_lines)[-lines:]
        return "\n".join(recent)
