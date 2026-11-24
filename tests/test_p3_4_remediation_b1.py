"""
Regression Tests for Blocker B1 Remediation: Removal of Synthetic Search Results.

Verifies:
1. Live browser output is retained and rendered truthfully without fabrication.
2. Empty browser output produces an honest "no matching search results" report, NOT fake records.
3. Unknown websites do not receive fabricated records.
4. Search results remain isolated between tasks (no stale result pollution).
5. Flipkart, GitHub, AWS, and Wikipedia queries do not return pre-written fake prices,
   fake laptop listings, hardcoded star counts, or canned paragraphs.
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


class TestBlockerB1Remediation(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(dry_run=True, use_gemini=False)

    def test_b1_01_real_browser_search_results_retained(self) -> None:
        """Verifies that actual search results extracted from Playwright MCP are rendered in task.result."""
        task = Task(
            intent="Search Flipkart for ASUS laptop",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://www.flipkart.com",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "ASUS laptop",
            "site": "flipkart",
            "site_name": "Flipkart",
        }

        real_items = [
            {"title": "ASUS TUF Gaming A15", "url": "https://www.flipkart.com/asus-tuf-a15"},
            {"title": "ASUS Zenbook 14 OLED", "url": "https://www.flipkart.com/asus-zenbook-14"},
        ]
        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Search submitted.",
            data={
                "url": "https://www.flipkart.com/search?q=ASUS+laptop",
                "title": "ASUS Laptop - Buy ASUS Laptop Online at Best Prices In India | Flipkart.com",
                "search_results": real_items,
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        # Verify genuine titles are present
        self.assertIn("ASUS TUF Gaming A15", task.result)
        self.assertIn("ASUS Zenbook 14 OLED", task.result)
        # Verify markdown links are present
        self.assertIn("[ASUS TUF Gaming A15](https://www.flipkart.com/asus-tuf-a15)", task.result)
        # Verify NO fake prices or fake models (from old hardcoded list)
        self.assertNotIn("HP 15s", task.result)
        self.assertNotIn("₹41,990", task.result)
        self.assertNotIn("Lenovo IdeaPad Slim 3", task.result)
        self.assertNotIn("Acer Aspire 7", task.result)
        # Verify session state retains real items
        self.assertEqual(self.orchestrator.last_browser_results, real_items)

    def test_b1_02_empty_browser_results_honestly_reported(self) -> None:
        """Verifies that zero results from browser output produce an honest report, NOT synthetic data."""
        task = Task(
            intent="Search Flipkart for xyznonexistentproduct123",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://www.flipkart.com",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "xyznonexistentproduct123",
            "site": "flipkart",
            "site_name": "Flipkart",
        }

        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Search submitted.",
            data={
                "url": "https://www.flipkart.com/search?q=xyznonexistentproduct123",
                "title": "Flipkart.com",
                "search_results": [],
                "snapshot": "- heading \"No results found\"",
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("no matching search results were found", task.result)
        # Must not inject synthetic laptop list!
        self.assertNotIn("HP 15s", task.result)
        self.assertNotIn("₹41,990", task.result)
        self.assertEqual(self.orchestrator.last_browser_results, [])

    def test_b1_03_unknown_website_receives_no_fabricated_records(self) -> None:
        """Verifies that unfamiliar websites are handled with dynamic output without mock records."""
        task = Task(
            intent="Search DuckDuckGo for quantum mechanics",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://duckduckgo.com",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "quantum mechanics",
            "site": "duckduckgo",
            "site_name": "Duckduckgo",
        }

        ddg_items = [
            {"title": "Quantum Mechanics - Stanford Encyclopedia", "url": "https://plato.stanford.edu/entries/qm/"},
            {"title": "Introduction to Quantum Mechanics", "url": "https://en.wikipedia.org/wiki/Introduction_to_quantum_mechanics"},
        ]
        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Search completed.",
            data={
                "url": "https://duckduckgo.com/?q=quantum+mechanics",
                "title": "quantum mechanics at DuckDuckGo",
                "search_results": ddg_items,
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Quantum Mechanics - Stanford Encyclopedia", task.result)
        self.assertIn("https://plato.stanford.edu/entries/qm/", task.result)
        self.assertEqual(self.orchestrator.last_browser_results, ddg_items)

    def test_b1_04_github_search_no_fabricated_stars_or_release(self) -> None:
        """Verifies GitHub queries display real page results rather than hardcoded 73,500+ stars or v1.50.1."""
        task = Task(
            intent="Search GitHub for playwright mcp",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://github.com",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "playwright mcp",
            "site": "github",
            "site_name": "GitHub",
        }

        real_gh_items = [
            {"title": "modelcontextprotocol/servers", "url": "https://github.com/modelcontextprotocol/servers"},
            {"title": "microsoft/playwright", "url": "https://github.com/microsoft/playwright"},
        ]
        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="GitHub search completed.",
            data={
                "url": "https://github.com/search?q=playwright+mcp",
                "title": "Search · playwright mcp · GitHub",
                "search_results": real_gh_items,
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("modelcontextprotocol/servers", task.result)
        self.assertNotIn("73,500+ stars", task.result)
        self.assertNotIn("v1.50.1", task.result)

    def test_b1_05_wikipedia_search_no_canned_quantum_paragraph(self) -> None:
        """Verifies Wikipedia searches render actual page results rather than canned text."""
        task = Task(
            intent="Search Wikipedia for quantum computing and explain it",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://www.wikipedia.org",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "quantum computing",
            "site": "wikipedia",
            "site_name": "Wikipedia",
        }

        wiki_items = [
            {"title": "Quantum computing", "url": "https://en.wikipedia.org/wiki/Quantum_computing"},
            {"title": "Timeline of quantum computing", "url": "https://en.wikipedia.org/wiki/Timeline_of_quantum_computing"},
        ]
        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Wikipedia page retrieved.",
            data={
                "url": "https://en.wikipedia.org/wiki/Quantum_computing",
                "title": "Quantum computing - Wikipedia",
                "search_results": wiki_items,
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Quantum computing", task.result)
        self.assertNotIn("Quantum computing is a rapidly-emerging technology that harnesses the laws", task.result)

    def test_b1_06_search_results_isolated_between_tasks(self) -> None:
        """Verifies opening a website with no search clears previous search results to avoid stale data leakage."""
        self.orchestrator.last_browser_results = [
            {"title": "Old Laptop", "url": "https://example.com/old"}
        ]

        task = Task(
            intent="Open Amazon",
            command=TaskCommand.OPEN_URL,
        )
        task.params = {
            "url": "https://www.amazon.in",
            "browser_intent": "OPEN_WEBSITE",
            "site": "amazon",
            "site_name": "Amazon",
        }

        mock_res = _make_mock_exec_res(
            status=TaskStatus.COMPLETED,
            summary="Amazon home loaded.",
            data={
                "url": "https://www.amazon.in",
                "title": "Online Shopping site in India: Shop Online for Mobiles, Books, Watches & more",
            },
        )

        with patch.object(self.orchestrator.execution_engine, "execute_plan", return_value=mock_res):
            self.orchestrator._execute_playwright_browser(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        # Results must be cleared on bare website open
        self.assertEqual(self.orchestrator.last_browser_results, [])


if __name__ == "__main__":
    unittest.main()
