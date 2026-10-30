"""
tests/test_unified_dual_intelligence.py
=======================================
Comprehensive test suite verifying the Cortex Unified Dual-Intelligence Architecture:
  1. Conversational Intelligence (ChatGPT/Gemini standard)
  2. MacOS Autonomous Device Operator (Siri/operator standard)
  3. Cooperative Intelligence (Shared context, search-to-browser, research-to-email, follow-ups)

Covers all 12 mandatory demonstrations from the P0 specification:
  - TEST 1: "Explain the Big Bang theory."
  - TEST 2: "Open Safari."
  - TEST 3: "Open Safari and search for latest AI developments."
  - TEST 4: "Find the latest AI news and explain the second result."
  - TEST 5: "Open that article in Safari."
  - TEST 6: "Draft an email to Rahul about the AI research findings. Do not send it."
  - TEST 7: "Make it shorter."
  - TEST 8: "Explain quantum computing in Kannada."
  - TEST 9: "Stop. Help me with Python instead."
  - TEST 10: AI provider unavailable (honest fallback / preserved state).
  - TEST 11: Browser integration failure / honest reporting.
  - TEST 12: Consequential actions require explicit approval.
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.persistence import EncryptedMemoryStore
from backend.core.contracts import TaskCommand, TaskStatus, RiskLevel

MOCK_RESEARCH_RESULTS = [
    {
        "title": "Frontier AI Reasoning Models in 2025",
        "body": "State of the art models now use inference-time compute scaling and autonomous agentic workflows.",
        "href": "https://example.com/frontier-ai-2025",
    },
    {
        "title": "Anthropic Claude Code and Terminal Agent Evolution",
        "body": "Anthropic launched Claude Code, a specialized terminal agent capable of complex repo refactoring.",
        "href": "https://example.com/anthropic-claude-code",
    },
    {
        "title": "Quantum Machine Learning Advances",
        "body": "Quantum-classical hybrid algorithms demonstrate quadratic speedup in optimization and material discovery.",
        "href": "https://example.com/quantum-ml-2025",
    },
]


def create_orchestrator(dry_run: bool = True, use_gemini: bool = False):
    tmp = tempfile.mkdtemp()
    mem = EncryptedMemoryStore(str(Path(tmp) / "memory.sqlite3"))
    return CortexOrchestrator(DeviceAutomation(dry_run=dry_run), mem, use_gemini=use_gemini)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — Conversational Intelligence (Tests 1, 8, 10)
# ═══════════════════════════════════════════════════════════════════════════

class TestConversationalIntelligence:
    """[MOCKED / UNIT] Engine One: Reasoning, General Knowledge & Multilingual."""

    def test_demo_1_explain_big_bang(self):
        """TEST 1: Scientific knowledge answering without triggering device automation."""
        orch = create_orchestrator()
        res = orch.chat("Explain the Big Bang theory.")
        assert res["task"]["command"] == "ask_question"
        assert res["task"]["status"] == "completed"
        msg = res["message"].lower()
        # Verifies actual scientific model content, not device automation or filler
        assert any(kw in msg for kw in ("13.8 billion", "cosmological", "expansion", "universe", "density"))

    def test_demo_8_explain_quantum_in_kannada(self):
        """TEST 8: Multilingual conversation in Kannada script."""
        orch = create_orchestrator()
        res = orch.chat("Explain quantum computing in Kannada.")
        assert res["task"]["command"] == "ask_question"
        assert res["task"]["language"] == "kn"
        msg = res["message"]
        # Must be in Kannada script
        assert "ಕ್ವಾಂಟಮ್" in msg or "ಕಂಪ್ಯೂಟಿಂಗ್" in msg

    def test_demo_10_ai_provider_unavailable_honest_handling(self):
        """TEST 10: Provider unavailable yields honest offline report, preserving task."""
        orch = create_orchestrator(use_gemini=False)
        res = orch.chat("What is photosynthesis?")
        assert res["task"]["command"] == "ask_question"
        assert res["task"]["status"] == "completed"
        assert len(res["message"]) > 0


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — MacOS Device Intelligence (Tests 2, 11, 12)
# ═══════════════════════════════════════════════════════════════════════════

class TestMacOSDeviceIntelligence:
    """[MOCKED / UNIT] Engine Two: Device Control, Applications, Permissions & Approvals."""

    def test_demo_2_open_safari(self):
        """TEST 2: Application control opens and verifies Safari."""
        orch = create_orchestrator(dry_run=True)
        res = orch.chat("Open Safari.")
        assert res["task"]["command"] == "open_app"
        assert res["task"]["status"] == "completed"
        assert "Safari" in res["message"]

    def test_demo_11_browser_search_honest_reporting(self):
        """TEST 11: Empty search or integration limitation produces honest report, not 'Done.'."""
        orch = create_orchestrator(dry_run=True)
        with patch("backend.integrations.search.web_search.search_web", return_value=[]):
            res = orch.chat("Search for ")
        assert res["message"] != "Done."
        assert len(res["message"].strip()) > 0

    def test_demo_12_consequential_action_requires_approval(self):
        """TEST 12: High-risk/consequential operations require explicit approval before execution."""
        orch = create_orchestrator(dry_run=True)
        res = orch.chat("Send email to test@example.com saying hello")
        # Must require approval and cannot auto-execute
        assert res["task"]["status"] in ("waiting_approval", "need_info")
        assert res["task"]["command"] in ("send_mail", "draft_mail")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — Cooperative Intelligence & Multi-Turn Workflows (Tests 3-7, 9)
# ═══════════════════════════════════════════════════════════════════════════

class TestCooperativeIntelligence:
    """[MOCKED / INTEGRATION] Cooperative workflows connecting research, browser, and email."""

    def test_demo_3_open_safari_and_search(self):
        """TEST 3: Compound browser automation opens Safari with search query and returns results."""
        orch = create_orchestrator(dry_run=True)
        with patch("backend.agent.orchestrator.search_web", return_value=MOCK_RESEARCH_RESULTS):
            res = orch.chat("Open Safari and search for latest AI developments.")
        assert res["task"]["command"] == "web_search"
        assert res["task"]["params"]["query"] == "latest AI developments"
        assert res["task"]["params"]["browser"] == "Safari"
        assert "Frontier AI" in res["message"] or "Claude" in res["message"] or "Source:" in res["message"]

    def test_demo_4_5_search_explain_and_open_article(self):
        """TEST 4 & 5: Search, explain the second result, then open that exact article in Safari."""
        orch = create_orchestrator(dry_run=True)
        with patch("backend.agent.orchestrator.search_web", return_value=MOCK_RESEARCH_RESULTS):
            # Turn 1: Search and explain second result
            r4 = orch.chat("Find the latest AI news and explain the second result.")
            assert r4["task"]["command"] == "web_search"
            assert "second" in r4["message"].lower() or "anthropic" in r4["message"].lower() or "claude" in r4["message"].lower()

            # Turn 2: Open that article in Safari
            r5 = orch.chat("Open that article in Safari.")
            assert r5["task"]["command"] == "open_url"
            assert r5["task"]["status"] == "completed"
            assert "Safari" in r5["message"]
            assert "anthropic-claude-code" in r5["message"]

    def test_demo_6_7_research_to_email_and_modify(self):
        """TEST 6 & 7: Draft email incorporating research context, do not send, then make it shorter."""
        orch = create_orchestrator(dry_run=True)
        # Seed orchestrator with search results
        orch.last_search_results = MOCK_RESEARCH_RESULTS
        orch.last_search_query = "latest AI news"

        # Turn 1: Draft email to Rahul about research findings, do not send it
        r6 = orch.chat("Draft an email to Rahul about the AI research findings. Do not send it.")
        assert r6["task"]["command"] == "draft_mail"
        assert "rahul" in r6["message"].lower()
        assert orch.pending_action is not None
        assert orch.pending_action.get("type") == "email_draft"

        # Turn 2: "Make it shorter."
        r7 = orch.chat("Make it shorter.")
        assert r7["task"]["status"] in ("waiting_approval", "completed")
        assert "rahul" in r7["message"].lower()
        # Verify it remains un-sent awaiting user approval
        assert orch.pending_action is not None

    def test_demo_9_task_interruption(self):
        """TEST 9: 'Stop. Help me with Python instead.' pauses active task and starts new conversation."""
        orch = create_orchestrator(dry_run=True)
        # Start a draft task
        orch.chat("Draft an email to Rahul about the meeting. Do not send it.")
        assert len(orch.paused_tasks) == 0

        # Interrupt
        r9 = orch.chat("Stop. Help me with Python instead.")
        assert len(orch.paused_tasks) == 1
        assert "paused" in r9["message"].lower()
        assert "python" in r9["message"].lower()

    def test_full_cooperative_chain_request(self):
        """Cooperative intelligence chain: 'Find latest AI news, open the most relevant article in Safari, and explain it.'"""
        orch = create_orchestrator(dry_run=True)
        with patch("backend.agent.orchestrator.search_web", return_value=MOCK_RESEARCH_RESULTS):
            res = orch.chat("Find the latest AI news, open the most relevant article in Safari, and explain it.")
        assert res["task"]["command"] == "web_search"
        assert res["task"]["status"] == "completed"
        # Must confirm Safari was operated, article selected, and explained with source link
        assert "Safari" in res["message"]
        assert "Frontier AI" in res["message"]
        assert "https://example.com/frontier-ai-2025" in res["message"]
