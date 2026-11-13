"""
P0 Model, Conversation, and Intent Reliability Tests.
Validates:
- Consistent model initialization across orchestrator and vision modules
- Capability inquiries vs execution vs research routing
- Questions asking for execution evidence / session verified capabilities
- History roles, duplicate prevention, and truncation
- Clarification context contamination prevention
- Gemini rate-limit / quota cooldown, recovery, and honest fallback responses
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.screen_vision_intelligence import MultimodalVisualIntelligenceEngine
from backend.core.contracts import TaskCommand, TaskStatus, is_self_capability_query


class TestP0ModelAndIntentReliability(unittest.TestCase):
    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.orch.clear_history()

    def test_model_initialization_defaults_consistent(self):
        """Authoritative model configuration defaults to gemini-3.5-flash across all modules."""
        self.assertEqual(self.orch.model_name, "gemini-3.5-flash")
        screen_vision = MultimodalVisualIntelligenceEngine()
        self.assertEqual(screen_vision.model_name, "gemini-3.5-flash")

    def test_greeting_routing(self):
        """Greetings route to ASK_QUESTION and return conversational status."""
        res = self.orch.chat("Hey Cortex, how are you?")
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "").lower()
        self.assertTrue("doing fantastic" in msg or "how are you" in msg)

    def test_five_specific_things_no_web_search(self):
        """'What are five specific things you can help me do on this Mac?' must NOT invoke search_web."""
        query = "What are five specific things you can help me do on this Mac?"
        self.assertTrue(is_self_capability_query(query))
        with patch("backend.agent.orchestrator.search_web") as mock_search:
            res = self.orch.chat(query)
            mock_search.assert_not_called()
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "")
        self.assertIn("five specific things", msg.lower())
        self.assertIn("Safari", msg)
        self.assertIn("Apple Mail", msg)

    def test_session_verified_capabilities_uses_execution_evidence(self):
        """Questions asking what has been actually verified must use session execution evidence."""
        query = "Without opening anything, which capabilities have you actually verified in this session?"
        self.assertTrue(is_self_capability_query(query))
        with patch("backend.agent.orchestrator.search_web") as mock_search:
            res = self.orch.chat(query)
            mock_search.assert_not_called()
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "")
        self.assertIn("execution evidence in this session", msg.lower())
        self.assertIn("without opening or launching external applications", msg.lower())
        self.assertIn("Empirically Verified in this Session", msg)
        self.assertIn("Conversational Intelligence", msg)
        self.assertIn("Registered Capabilities (Unexecuted in this Session)", msg)
        self.assertIn("Safari Web Research", msg)

    def test_research_query_routes_to_research(self):
        """'What are the latest developments in AI? Give me source links.' must NOT be treated as capability inquiry."""
        query = "What are the latest developments in AI? Give me source links."
        self.assertFalse(is_self_capability_query(query))

    def test_clarification_not_contaminated_by_questions(self):
        """Pending email draft is not contaminated when user asks an unrelated question."""
        self.orch.pending_action = {
            "type": "email_draft",
            "step": "waiting_for_body",
            "recipient": "rahul@example.com",
            "command": TaskCommand.DRAFT_MAIL,
            "subject": "Project Update",
        }
        # User asks a conceptual question while draft is waiting for body
        unrelated_q = "Explain the difference between mutable and immutable Python objects."
        self.assertTrue(self.orch._is_unrelated_turn(unrelated_q, step="waiting_for_body"))

    def test_history_duplicate_prevention(self):
        """Adjacent identical conversational turns must not be inserted as duplicates into history."""
        self.orch.history = []
        msg = "What is Python?"
        resp = "Python is a high-level programming language."
        # First insertion
        self.orch.history.append({"role": "user", "parts": [msg]})
        self.orch.history.append({"role": "model", "parts": [resp]})
        initial_len = len(self.orch.history)
        self.assertEqual(initial_len, 2)

        # Trigger chat with identical turn simulation through _answer_general_question
        with patch.object(self.orch, "_answer_general_question", return_value=resp):
            res = self.orch.chat(msg)
            # Length should remain 2 because duplicate insertion was guarded
            self.assertEqual(len(self.orch.history), 2)

    def test_rate_limit_cooldown_and_honest_fallback(self):
        """When Gemini returns 429/quota error, circuit breaker activates and returns honest fallback without web search."""
        orch = CortexOrchestrator(use_gemini=True)
        # Simulate rate-limit error
        err = Exception("ResourceExhausted: 429 Quota exceeded for quota metric 'Queries'")
        orch._handle_gemini_error(err, context="test")
        self.assertFalse(orch._is_gemini_available())
        self.assertGreater(orch.gemini_cooldown_until, time.time())

        # General conceptual query during cooldown must NOT query DuckDuckGo
        with patch("backend.agent.orchestrator.search_web") as mock_search:
            res = orch.chat("Explain the difference between mutable and immutable Python objects.")
            mock_search.assert_not_called()
            self.assertIn("API rate limits", res.get("message", ""))

        # Verify automatic recovery after cooldown expiry
        orch.gemini_cooldown_until = time.time() - 1.0
        self.assertTrue(orch._is_gemini_available())


if __name__ == "__main__":
    unittest.main()
