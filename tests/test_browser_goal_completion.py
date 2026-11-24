import unittest
from unittest.mock import MagicMock, patch
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel, ExecutionResult

class TestBrowserGoalCompletion(unittest.TestCase):
    def setUp(self):
        self.orch = CortexOrchestrator()

    # ── A. Natural-Language URL Extraction ─────────────────────────
    def test_url_extraction_tradingview_explanation(self):
        """Verify prompt with trailing explanation goal separates URL cleanly."""
        params = self.orch._extract_open_url_params("Open TradingView and explain what it does.")
        self.assertEqual(params["url"], "https://www.tradingview.com")
        self.assertEqual(params.get("info_goal"), "explain what it does")
        self.assertNotIn("explain", params["url"])
        self.assertNotIn(" ", params["url"])

    def test_url_extraction_claude_summary(self):
        """Verify Claude prompt separates URL and feature summary goal."""
        params = self.orch._extract_open_url_params("Visit a Claude website and summarize its main features.")
        self.assertEqual(params["url"], "https://www.claude.ai")
        self.assertEqual(params.get("info_goal"), "summarize its main features")
        self.assertNotIn("summarize", params["url"])

    def test_url_extraction_explicit_url_with_clause(self):
        """Verify explicit URL followed by informational clause preserves clean URL."""
        params = self.orch._extract_open_url_params("Open https://example.com and explain its purpose")
        self.assertEqual(params["url"], "https://example.com")
        self.assertEqual(params.get("info_goal"), "explain its purpose")

    def test_url_extraction_multi_word_brand(self):
        """Verify multi-word brand like Barnes & Noble is preserved without corruption."""
        params = self.orch._extract_open_url_params("Open Barnes & Noble")
        self.assertEqual(params["url"], "https://www.barnesandnoble.com")
        self.assertEqual(params["target"], "Barnes & Noble")

    # ── B. Information Synthesis ────────────────────────────────────
    def test_information_synthesis_grounding(self):
        """Verify grounded synthesis generates content-backed answer and includes verified URL."""
        mock_snapshot = (
            "[ref=e1] heading 'TradingView - Track All Markets'\n"
            "[ref=e2] link 'Supercharts - Advanced Financial Charting'\n"
            "[ref=e3] link 'Screeners for Stocks, Crypto, Forex'\n"
            "[ref=e4] text 'Market quotes and social ideas for traders'"
        )
        summary = self.orch._generate_grounded_browser_summary(
            title="TradingView",
            url="https://www.tradingview.com",
            snapshot_text=mock_snapshot,
            intent="Open TradingView and explain what it does."
        )
        self.assertIn("TradingView", summary)
        self.assertIn("https://www.tradingview.com", summary)
        self.assertTrue("charting" in summary.lower() or "markets" in summary.lower() or "trading" in summary.lower())
        self.assertIn("Verified destination: https://www.tradingview.com", summary)

    def test_claude_feature_summary_synthesis(self):
        """Verify Claude synthesis generates feature points and includes verified URL."""
        mock_snapshot = (
            "[ref=e1] heading 'Claude by Anthropic'\n"
            "[ref=e2] text 'Next-generation AI assistant for coding, reasoning, and analysis'\n"
            "[ref=e3] link 'Claude 3.5 Sonnet Models'"
        )
        summary = self.orch._generate_grounded_browser_summary(
            title="Claude",
            url="https://www.claude.ai",
            snapshot_text=mock_snapshot,
            intent="Visit a Claude website and summarize its main features."
        )
        self.assertIn("Claude", summary)
        self.assertIn("https://www.claude.ai", summary)
        self.assertTrue("reasoning" in summary.lower() or "coding" in summary.lower() or "features" in summary.lower())

    # ── C. Search and Goal Preservation ─────────────────────────────
    def test_search_goal_preservation_github_langgraph(self):
        """Verify searching GitHub preserves search target and query."""
        params = self.orch._extract_open_url_params("Open GitHub and find the LangGraph repository.")
        self.assertEqual(params["url"], "https://github.com")
        self.assertEqual(params.get("browser_intent"), "WEBSITE_SEARCH")
        self.assertEqual(params.get("query"), "LangGraph")
        self.assertEqual(params.get("site"), "GitHub")

    def test_github_plan_generates_search_actions(self):
        """Verify planner schedules typing into search box and capturing results."""
        params = {
            "url": "https://github.com",
            "browser_intent": "WEBSITE_SEARCH",
            "query": "LangGraph",
            "site": "GitHub",
            "search_target": "search"
        }
        plan = self.orch.planner.plan("Open GitHub and find the LangGraph repository.", TaskCommand.OPEN_URL, params, None)
        self.assertGreaterEqual(len(plan.steps), 3)
        tools = [s.tool for s in plan.steps]
        # Must include open, type/fill, snapshot
        self.assertTrue(any("open" in t or "navigate" in t for t in tools))
        self.assertTrue(any("type" in t or "fill" in t for t in tools))
        self.assertTrue(any("snapshot" in t or "scrape" in t for t in tools))

    # ── D. Sequence Result Preservation ─────────────────────────────
    def test_sequence_result_preservation_no_bare_completed_string(self):
        """Verify compound browser sequence preserves URL and inspection evidence instead of 'Sequence completed.'"""
        commands = [
            "Open https://www.claude.ai",
            "inspect it",
            "verify its URL"
        ]
        res = self.orch._chat_sequence("Open a claude page, inspect it, and verify its URL.", commands, "chat")
        msg = res["message"]
        # Must NEVER be the bare uninformative string
        self.assertNotEqual(msg.strip(), "Sequence completed.")
        # Must contain actual verification evidence
        self.assertTrue("claude.ai" in msg or "URL verified" in msg or "inspected" in msg or "navigated" in msg.lower())

    # ── E. Completion Correctness ───────────────────────────────────
    def test_navigation_only_fails_on_missing_snapshot_content(self):
        """Verify that when informational synthesis is requested but no snapshot is available, task fails."""
        task = Task(
            intent="Open TradingView and explain what it does.",
            command=TaskCommand.OPEN_URL,
            params={"url": "https://www.tradingview.com", "info_goal": "explain what it does"}
        )
        mock_final_res = MagicMock(
            status=TaskStatus.COMPLETED,
            data={"url": "https://www.tradingview.com", "title": "TradingView", "snapshot": ""},
            summary="Loaded page."
        )
        with patch.object(self.orch.execution_engine, "execute_plan", return_value=mock_final_res):
            self.orch._execute(task)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("Failed to retrieve rendered page content", task.error)

if __name__ == "__main__":
    unittest.main()
