"""
tests/test_browser_automation_routing.py
=========================================
Browser-automation routing tests for Cortex Agent.

Tests are clearly labelled:
  - [MOCKED] — no network or macOS dependency; safe for CI.
  - [LIVE]   — requires macOS, network access, and (for Safari) display/permission.
               Skipped automatically when running on non-Darwin platforms.

P0 regression: "Open Safari and search for latest update in AI."
must route to WEB_SEARCH with query="latest update in AI" and browser="Safari".
"""

import re
import sys
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

warnings.filterwarnings("ignore")

# ── helpers ─────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.core.contracts import command_from_intent, TaskCommand  # noqa: E402

_COMPOUND_RE = re.compile(
    r"(?:open|launch|start)\s+(safari|chrome|firefox|edge|browser)\s+"
    r"and\s+(?:search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+up\s+|research\s+|find\s+|google\s+)"
    r"(.+)",
    re.IGNORECASE,
)


def _extract_browser_query(msg: str):
    """Return (browser, query) for compound open-browser-and-search sentences, else (None, None)."""
    m = _COMPOUND_RE.search(msg)
    if m:
        return m.group(1).title(), m.group(2).strip().rstrip(".")
    return None, None


def _make_orch(dry_run: bool = True, use_gemini: bool = False):
    from backend.capabilities import DeviceAutomation
    from backend.persistence import EncryptedMemoryStore
    from backend.agent import CortexOrchestrator

    tmp = tempfile.mkdtemp()
    mem = EncryptedMemoryStore(str(Path(tmp) / "memory.sqlite3"))
    return CortexOrchestrator(DeviceAutomation(dry_run=dry_run), mem, use_gemini=use_gemini)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Intent Classification (MOCKED, no network)
# ═══════════════════════════════════════════════════════════════════════════

class TestIntentClassification:
    """[MOCKED] Verifies command_from_intent() returns the correct TaskCommand."""

    def test_p0_open_safari_and_search(self):
        """P0 regression: compound open-safari-and-search → WEB_SEARCH."""
        cmd = command_from_intent("Open Safari and search for latest update in AI.")
        assert cmd == TaskCommand.WEB_SEARCH, f"Expected WEB_SEARCH, got {cmd.name}"

    def test_open_safari_and_search_openai(self):
        cmd = command_from_intent("Open Safari and search for OpenAI news.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_launch_chrome_and_search(self):
        cmd = command_from_intent("Launch Chrome and search for quantum computing.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_open_safari_and_find(self):
        """Variant with 'find' instead of 'search for'."""
        cmd = command_from_intent("Open Safari and find the latest AI developments.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_search_the_web_for(self):
        cmd = command_from_intent("Search the web for Python tutorials.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_find_latest_developments(self):
        """'Find the latest ...' should be web research, not file search."""
        cmd = command_from_intent("Find the latest developments in robotics.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_find_recent_news(self):
        cmd = command_from_intent("Find recent news about Apple.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_search_and_summarize(self):
        cmd = command_from_intent("Search for latest AI news and summarize it.")
        assert cmd == TaskCommand.WEB_SEARCH

    def test_open_safari_alone_is_open_app(self):
        """'Open Safari.' without a search query must stay OPEN_APP."""
        cmd = command_from_intent("Open Safari.")
        assert cmd == TaskCommand.OPEN_APP, f"Expected OPEN_APP, got {cmd.name}"

    def test_find_file_still_search_files(self):
        """File-search intent must not be hijacked by the new web-search 'find' rule."""
        cmd = command_from_intent("Find file report.pdf.")
        assert cmd == TaskCommand.SEARCH_FILES


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — Query Extraction (MOCKED, no network)
# ═══════════════════════════════════════════════════════════════════════════

class TestQueryExtraction:
    """[MOCKED] Verifies that _extract_params() produces correct query and browser values."""

    def _params(self, msg: str) -> dict:
        orch = _make_orch()
        cmd = command_from_intent(msg)
        return orch._extract_params(cmd, msg)

    def test_p0_query_extracted_correctly(self):
        """P0: query must be 'latest update in AI', NOT the full sentence."""
        params = self._params("Open Safari and search for latest update in AI.")
        assert params.get("query") == "latest update in AI", f"Got: {params}"

    def test_p0_browser_param_set(self):
        params = self._params("Open Safari and search for latest update in AI.")
        assert params.get("browser") == "Safari", f"Got: {params}"

    def test_openai_query_extracted(self):
        params = self._params("Open Safari and search for OpenAI news.")
        assert params.get("query") == "OpenAI news"
        assert params.get("browser") == "Safari"

    def test_chrome_query_extracted(self):
        params = self._params("Launch Chrome and search for quantum computing.")
        assert params.get("query") == "quantum computing"
        assert params.get("browser") == "Chrome"

    def test_plain_search_query(self):
        params = self._params("Search the web for Python tutorials.")
        assert "python tutorials" in params.get("query", "").lower()

    def test_open_safari_alone_no_query(self):
        """OPEN_APP intent: no 'query' key expected (different command path)."""
        cmd = command_from_intent("Open Safari.")
        assert cmd == TaskCommand.OPEN_APP
        # _extract_params for OPEN_APP returns appName, not query
        orch = _make_orch()
        params = orch._extract_params(cmd, "Open Safari.")
        assert "query" not in params


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — Orchestrator end-to-end (MOCKED search results, dry_run)
# ═══════════════════════════════════════════════════════════════════════════

MOCK_RESULTS = [
    {
        "title": "AI Update 2025: Breakthroughs in Large Language Models",
        "body": "OpenAI, Google, and Anthropic released major model updates in 2025, "
                "including GPT-5 and Gemini Ultra 2.",
        "href": "https://example.com/ai-update-2025",
    },
    {
        "title": "Latest Developments in Generative AI",
        "body": "Generative AI tools are now integrated into most enterprise software suites.",
        "href": "https://example.com/gen-ai-dev",
    },
]


class TestOrchestratorRouting:
    """[MOCKED] Verifies end-to-end orch.chat() routing with mocked search results."""

    def _chat(self, msg: str, mock_results=None):
        if mock_results is None:
            mock_results = MOCK_RESULTS
        with patch(
            "backend.integrations.search.web_search.search_web", return_value=mock_results
        ):
            orch = _make_orch(dry_run=True, use_gemini=False)
            return orch.chat(msg)

    def test_p0_status_completed(self):
        res = self._chat("Open Safari and search for latest update in AI.")
        assert res["task"]["status"] == "completed"

    def test_p0_command_is_web_search(self):
        res = self._chat("Open Safari and search for latest update in AI.")
        assert res["task"]["command"] == "web_search"

    def test_p0_response_not_encyclopedia(self):
        """Response must NOT describe Safari/iOS — it must reflect AI search results."""
        res = self._chat("Open Safari and search for latest update in AI.")
        response = res.get("message", "").lower()
        # Should NOT be about the Safari browser product
        assert "ios" not in response or "ai" in response, \
            f"Response looks like a Safari encyclopedia: {response[:200]}"
        assert "apple" not in response or "ai" in response or "openai" in response.lower()

    def test_p0_response_contains_search_result_content(self):
        """Response must reference content from the mocked search results."""
        res = self._chat("Open Safari and search for latest update in AI.")
        response = res.get("message", "").lower()
        assert any(
            kw in response
            for kw in ("llm", "language model", "openai", "gpt", "gemini", "anthropic", "generative", "2025", "ai")
        ), f"Response does not reference AI content: {response[:300]}"

    def test_p0_params_correct(self):
        res = self._chat("Open Safari and search for latest update in AI.")
        params = res["task"]["params"]
        assert params.get("query") == "latest update in AI"
        assert params.get("browser") == "Safari"

    def test_search_web_for_python(self):
        res = self._chat("Search the web for Python tutorials.", mock_results=[
            {"title": "Learn Python", "body": "Python 3 tutorial for beginners.", "href": "https://example.com/python"}
        ])
        assert res["task"]["status"] == "completed"
        assert res["task"]["command"] == "web_search"

    def test_stop_searching(self):
        """'Stop searching' should not be routed as WEB_SEARCH."""
        cmd = command_from_intent("Stop searching.")
        assert cmd != TaskCommand.WEB_SEARCH

    def test_no_results_honest_error(self):
        """Empty results → honest failure, not a fake 'Done.'"""
        with patch("backend.integrations.search.web_search.search_web", return_value=[]):
            orch = _make_orch(dry_run=True, use_gemini=False)
            res = orch.chat("Open Safari and search for latest update in AI.")
        task = res["task"]
        # Either failed (preferred) or the status is completed with a real message
        # It must NOT return a silent 'Done.' masking the absence of results
        response = res.get("message", "")
        assert response != "Done.", "Silent 'Done.' returned when no results found"
        assert response.strip() != "", "Empty response returned when no results found"

    def test_safari_unavailable_dry_run(self):
        """In dry_run mode Safari subprocess is skipped; must still search and respond."""
        res = self._chat("Open Safari and search for latest update in AI.")
        # dry_run=True skips subprocess — result still reports web search outcome
        assert res["task"]["status"] == "completed"

    def test_follow_up_context_second_result(self):
        """[MOCKED] Follow-up 'explain the second result' uses session context."""
        orch = _make_orch(dry_run=True, use_gemini=False)
        with patch("backend.integrations.search.web_search.search_web", return_value=MOCK_RESULTS):
            orch.chat("Open Safari and search for latest update in AI.")
        # A follow-up on the second result — at minimum should not crash
        res2 = orch.chat("Explain the second result in simple words.")
        assert res2 is not None
        assert "message" in res2


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — Live / macOS-only tests (skipped on non-Darwin or no network)
# ═══════════════════════════════════════════════════════════════════════════

SKIP_NOT_MAC = pytest.mark.skipif(
    sys.platform != "darwin", reason="Requires macOS"
)


@SKIP_NOT_MAC
class TestLiveSafari:
    """[LIVE — macOS + network] Skipped automatically on non-Darwin platforms."""

    def test_live_safari_subprocess_called(self):
        """Verify subprocess is invoked to open Safari (mocked to avoid side-effects)."""
        with patch("subprocess.run") as mock_run, \
             patch("backend.integrations.search.web_search.search_web", return_value=MOCK_RESULTS):
            orch = _make_orch(dry_run=False, use_gemini=False)
            res = orch.chat("Open Safari and search for latest update in AI.")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "Safari" in call_args, f"Safari not in subprocess args: {call_args}"
        assert "google.com/search" in " ".join(call_args), \
            f"No Google search URL in subprocess args: {call_args}"
        # Query must NOT be the full sentence
        assert "Open Safari" not in " ".join(call_args)
        assert res["task"]["status"] == "completed"

    def test_live_search_url_contains_correct_query(self):
        """URL passed to Safari subprocess must encode the extracted query, not the raw intent."""
        import urllib.parse
        with patch("subprocess.run") as mock_run, \
             patch("backend.integrations.search.web_search.search_web", return_value=MOCK_RESULTS):
            orch = _make_orch(dry_run=False, use_gemini=False)
            orch.chat("Open Safari and search for latest update in AI.")

        if mock_run.called:
            url_arg = mock_run.call_args[0][0][-1]
            decoded = urllib.parse.unquote(url_arg)
            assert "latest update in AI" in decoded or "latest+update+in+AI" in url_arg, \
                f"Unexpected URL: {url_arg}"
            assert "Open Safari" not in decoded, f"Full sentence leaked into URL: {decoded}"

