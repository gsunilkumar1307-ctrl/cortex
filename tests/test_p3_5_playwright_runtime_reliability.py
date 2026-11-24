"""
Tests for Phase P3.5: Playwright MCP Runtime Reliability & Process Lifecycle.

Verifies:
1. Process cleanup on initialization failure (no zombie processes).
2. Robust recovery from initialization timeouts without entering 'Server connection closed' failure loop.
3. Multiple connect() calls do not spawn concurrent reader tasks.
4. PATH environment sanitization preserves standard tool locations (/usr/local/bin, etc.).
5. Useful diagnostic errors identify the failure stage without leaking secrets.
6. No silent fallback to Safari when Playwright MCP is unavailable.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from backend.core.contracts import RiskLevel, Task, TaskCommand, TaskStatus
from backend.mcp.client import MCPClient
from backend.mcp.config import MCPServerConfig, sanitize_environment
from backend.mcp.exceptions import MCPConnectionError, MCPTimeoutError, MCPProcessError
from backend.mcp.manager import MCPServerManager, _ManagedServer
from backend.mcp.models import MCPServerStatus
from backend.mcp.process import MCPProcess
from backend.agent.orchestrator import CortexOrchestrator


class TestPlaywrightRuntimeReliability(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(dry_run=True, use_gemini=False)

    def test_p3_5_01_path_sanitization_includes_essential_bins(self) -> None:
        """Verifies that sanitize_environment guarantees standard tool paths (/usr/local/bin, etc.)."""
        # Simulate sparse environment as seen in macOS GUI / Electron launches
        with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}, clear=True):
            clean_env = sanitize_environment()
            path_dirs = clean_env.get("PATH", "").split(":")
            self.assertIn("/usr/local/bin", path_dirs)
            self.assertIn("/usr/bin", path_dirs)
            self.assertIn("/bin", path_dirs)
            self.assertIn(str(Path.home() / ".local" / "bin"), path_dirs)

    def test_p3_5_02_server_start_failure_cleans_up_process(self) -> None:
        """Verifies that if initialization times out or fails, the child process is terminated immediately."""
        mgr = MCPServerManager()
        cfg = MCPServerConfig(
            name="test_timeout_server",
            command="sleep",
            args=["5"],
            default_risk_level=RiskLevel.LOW,
            timeout_seconds=0.5,
        )
        mgr.register_server(cfg)
        server = mgr._servers["test_timeout_server"]

        try:
            with self.assertRaises(MCPProcessError):
                mgr.start_server("test_timeout_server", timeout=0.2)

            # Process must NOT be left running
            self.assertFalse(server.process.is_alive)
            self.assertEqual(server.status, MCPServerStatus.ERROR)
        finally:
            mgr.stop_all()

    def test_p3_5_03_retry_recovers_cleanly_without_connection_closed_loop(self) -> None:
        """Verifies that retrying start_server after a failure starts a clean fresh attempt."""
        mgr = MCPServerManager()
        cfg = MCPServerConfig(
            name="test_retry_server",
            command="sleep",
            args=["5"],
            default_risk_level=RiskLevel.LOW,
            timeout_seconds=0.5,
        )
        mgr.register_server(cfg)

        try:
            # First attempt fails with timeout
            with self.assertRaises(MCPProcessError) as ctx1:
                mgr.start_server("test_retry_server", timeout=0.2)
            self.assertIn("timed out", str(ctx1.exception).lower())

            # Second attempt must cleanly retry and NOT raise "Server connection closed"
            with self.assertRaises(MCPProcessError) as ctx2:
                mgr.start_server("test_retry_server", timeout=0.2)
            self.assertNotIn("Server connection closed", str(ctx2.exception))
            self.assertIn("timed out", str(ctx2.exception).lower())
        finally:
            mgr.stop_all()

    def test_p3_5_04_client_connect_cancels_previous_reader_task(self) -> None:
        """Verifies that calling connect() multiple times does not spawn duplicate reader tasks."""
        mock_proc = MagicMock(spec=MCPProcess)
        mock_proc.is_alive = True
        mock_proc.process = MagicMock()
        mock_proc.config = MCPServerConfig(name="test", command="echo", default_risk_level=RiskLevel.LOW)

        client = MCPClient(mock_proc)
        loop = asyncio.new_event_loop()
        try:
            async def run_test():
                # Mock initialize to succeed
                with patch.object(client, "initialize", new_callable=AsyncMock):
                    with patch.object(client, "_read_stdout_loop", new_callable=AsyncMock) as mock_loop:
                        await client.connect(timeout=1.0)
                        first_task = client._reader_task
                        self.assertIsNotNone(first_task)

                        await client.connect(timeout=1.0)
                        second_task = client._reader_task
                        self.assertIsNotNone(second_task)
                        # Previous task should have been cancelled/replaced
                        self.assertTrue(first_task.done() or first_task.cancelled())

            loop.run_until_complete(run_test())
        finally:
            loop.close()

    def test_p3_5_05_diagnostic_error_on_service_unavailability(self) -> None:
        """Verifies that when Playwright MCP is unavailable, a diagnostic error is returned without secrets."""
        task = Task(intent="Open Flipkart and search for a hub for MacBook", command=TaskCommand.OPEN_URL)
        task.params = {"url": "https://www.flipkart.com", "browser_intent": "WEBSITE_SEARCH"}

        # Simulate MCP manager having an errored playwright server
        mock_server = MagicMock()
        mock_server.config.enabled = True
        mock_server.status = MCPServerStatus.ERROR
        mock_server.process.get_last_stderr.return_value = "Command not found: npx"

        self.orchestrator.mcp_manager._servers["playwright"] = mock_server

        with patch.object(self.orchestrator, "ensure_mcp_tools"):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Playwright MCP browser automation service is currently unavailable", task.result)
        self.assertIn("server stderr: Command not found: npx", task.result)
        # Ensure Safari is never invoked
        self.assertNotIn("Safari", task.result)

    def test_p3_5_06_no_safari_fallback_on_playwright_failure(self) -> None:
        """Verifies that failure in Playwright MCP does not trigger legacy Safari open."""
        task = Task(intent="Open Amazon", command=TaskCommand.OPEN_URL)
        task.params = {"url": "https://www.amazon.in", "browser_intent": "OPEN_WEBSITE"}

        with patch.object(self.orchestrator, "ensure_mcp_tools"):
            with patch("subprocess.run") as mock_subproc:
                self.orchestrator._execute_playwright_browser(task)
                # Verify subprocess.run was NEVER called with Safari
                for call in mock_subproc.call_args_list:
                    args = call[0][0] if call[0] else []
                    self.assertNotIn("Safari", args)


if __name__ == "__main__":
    unittest.main()
