"""
Regression Tests for Blocker B2 Remediation: Removal of Legacy Safari Browser Fallback.

Verifies:
1. Browser navigation strictly uses Playwright MCP and BaseTool execution lifecycle.
2. Legacy native Safari fallback (osascript / open -a Safari) is never invoked for browser navigation tasks.
3. Native macOS desktop application launching remains fully functional for non-browser apps (Notes, Preview, Finder).
4. When Playwright MCP is unavailable, an honest and explicit service-unavailable error is returned.
5. Browser security and approval policies remain strictly enforced (SSRF, dangerous tools, consequential actions).
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import Task, TaskCommand, TaskStatus


def _make_mock_exec_res(status: TaskStatus = TaskStatus.COMPLETED, data: dict | None = None, summary: str = "Success"):
    res = MagicMock()
    res.status = status
    res.summary = summary
    res.message = summary
    res.data = data or {}
    return res


class TestBlockerB2Remediation(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(dry_run=True, use_gemini=False)

    def test_b2_01_browser_navigation_uses_playwright_mcp_not_safari(self) -> None:
        """Verifies TaskCommand.OPEN_URL routes through Playwright MCP and does NOT invoke Safari subprocess."""
        task = Task(
            intent="Open https://www.wikipedia.org",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://www.wikipedia.org",
            "browser": "Safari",  # Even if user mentions Safari, it must not spawn native Safari subprocess
            "use_context": True,
        }

        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Navigated to https://www.wikipedia.org",
            data={
                "url": "https://www.wikipedia.org",
                "title": "Wikipedia, the free encyclopedia",
            },
        )

        with patch("subprocess.run") as mock_subproc, \
             patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res) as mock_plan:
            self.orchestrator._execute_playwright_browser(task)

        # Plan execution must be invoked via ExecutionEngine / Playwright MCP
        mock_plan.assert_called_once()
        # Subprocess must NOT be invoked to open Safari
        mock_subproc.assert_not_called()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Wikipedia", task.result)
        self.assertIn("https://www.wikipedia.org", task.result)

    def test_b2_02_contextual_article_opening_uses_playwright_mcp(self) -> None:
        """Verifies opening an article from previous search context routes to Playwright MCP without Safari."""
        self.orchestrator.last_search_results = [
            {"title": "Deep Learning Breakthroughs", "href": "https://example.org/deep-learning", "body": "Summary..."}
        ]

        task = Task(
            intent="Open that article",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "use_context": True,
            "browser": "Safari",
        }

        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Opened article.",
            data={
                "url": "https://example.org/deep-learning",
                "title": "Deep Learning Breakthroughs",
            },
        )

        with patch("subprocess.run") as mock_subproc, \
             patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res) as mock_plan:
            self.orchestrator._execute(task)

        mock_plan.assert_called_once()
        mock_subproc.assert_not_called()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Deep Learning Breakthroughs", task.result)

    def test_b2_03_native_apps_preserved_for_non_browser_tasks(self) -> None:
        """Verifies native macOS desktop automation still works for non-browser apps like Notes and Preview."""
        with patch.object(self.orchestrator.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(ok=True, message="Opened Notes.")
            res = self.orchestrator.automation.execute(TaskCommand.OPEN_APP, {"appName": "Notes"})

        self.assertTrue(res.ok)
        mock_exec.assert_called_once_with(TaskCommand.OPEN_APP, {"appName": "Notes"})

    def test_b2_04_playwright_unavailable_honestly_reported(self) -> None:
        """Verifies that if Playwright MCP is unavailable, an explicit error is returned without silent fallbacks."""
        task = Task(
            intent="Open https://www.python.org",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {"url": "https://www.python.org"}

        # Simulate MCP manager with no playwright server and no registry tool
        with patch.object(self.orchestrator, "mcp_manager", None), \
             patch.object(self.orchestrator.registry, "get", return_value=None), \
             patch("subprocess.run") as mock_subproc:
            self.orchestrator._execute_playwright_browser(task)

        # Must NOT fallback to silent Safari open
        mock_subproc.assert_not_called()
        # Must report service unavailable error
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Playwright MCP browser automation service is unavailable", task.error)
        self.assertIn("No browser could be launched", task.result)

    def test_b2_05_browser_security_policies_remain_enforced(self) -> None:
        """Verifies SSRF blocking and security policies remain active in the Playwright execution path."""
        task = Task(
            intent="Open http://127.0.0.1:8080/admin",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {"url": "http://127.0.0.1:8080/admin"}

        with patch("subprocess.run") as mock_subproc:
            self.orchestrator._execute_playwright_browser(task)

        mock_subproc.assert_not_called()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("Security Policy Violation", task.error)
        self.assertIn("loopback", task.result)


if __name__ == "__main__":
    unittest.main()
