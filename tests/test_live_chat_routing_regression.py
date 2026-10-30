"""
test_live_chat_routing_regression.py — Stage 3: Live Chat Routing & Multi-turn Regression Tests

Validates:
1. An email request with an ambiguous recipient triggers clarification.
2. A subsequent Kannada greeting is correctly recognized and answered in Kannada, without repeating the clarification prompt.
3. A subsequent romanized Hindi question is correctly answered in Hindi, without repeating the clarification prompt.
4. A legitimate recipient answer resumes the pending draft and creates an approval card.
5. Cancellation of a pending email task works at any point in the flow.
6. Approval gate is preserved (sending is not performed without explicit user approval).
"""
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from backend.agent.orchestrator import CortexOrchestrator
import tempfile
from backend.core.contracts import TaskStatus, TaskCommand, LanguageCode
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore


class TestLiveChatRoutingRegression(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp_dir.name) / "test-reg.sqlite3"
        self.memory = EncryptedMemoryStore(db_path=str(db_path))
        self.task_store = TaskStore(db_path=str(db_path))
        self.orchestrator = CortexOrchestrator(use_gemini=False, memory=self.memory, task_store=self.task_store)
        # Mock automation execute to avoid real OS/AppleScript calls
        self.orchestrator.automation.execute = MagicMock(return_value=MagicMock(ok=True, message="Draft created"))

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_ambiguous_email_with_multilingual_interleaving_and_resume(self):
        """
        Scenario:
        1. User asks to draft email to ambiguous recipient 'Alex'.
        2. User sends Kannada greeting.
        3. User sends romanized Hindi question.
        4. User provides legitimate recipient email.
        5. User cancels the draft.
        """
        # Turn 1: Ambiguous recipient email request
        r1 = self.orchestrator.chat("Draft an email to Alex about rescheduling our project meeting to Friday at 3 PM")
        self.assertIn("identify", r1["message"].lower())
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_recipient_clarification")

        # Turn 2: Kannada greeting
        r2 = self.orchestrator.chat("ನಮಸ್ಕಾರ, ನೀವು ಹೇಗಿದ್ದೀರಿ?")
        # Must respond in Kannada and not repeat the email clarification
        self.assertNotIn("Alex's email", r2["message"])
        self.assertTrue(any(c in r2["message"] for c in ("ಕಾರ್ಟೆಕ್ಸ್", "ಚೆನ್ನಾಗಿದ್ದೇನೆ", "ನಮಸ್ಕಾರ", "ಸಹಾಯಕ")))
        self.assertEqual(r2.get("task", {}).get("language"), "kn")
        # Pending action must still be safely preserved in background
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_recipient_clarification")

        # Turn 3: Romanized Hindi question
        r3 = self.orchestrator.chat("Hindi me batao Cortex kya hai")
        # Must not repeat the email clarification
        self.assertNotIn("Alex's email", r3["message"])
        self.assertEqual(r3.get("task", {}).get("language"), "hi")
        # Pending action must still be preserved
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_recipient_clarification")

        # Turn 4: Legitimate answer to recipient clarification
        r4 = self.orchestrator.chat("alex@example.com")
        # Must resume draft creation and produce approval card
        self.assertIn("alex@example.com", r4["message"])
        self.assertIn("Draft", r4["message"])
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "confirm_send")

        # Turn 5: User cancels
        r5 = self.orchestrator.chat("cancel that")
        self.assertIn("Cancel", r5["message"])
        self.assertIsNone(self.orchestrator.pending_action)

    def test_direct_cancellation_during_recipient_clarification(self):
        """User can cancel directly when asked for recipient clarification."""
        r1 = self.orchestrator.chat("Draft an email to Alex about the budget")
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_recipient_clarification")

        # Cancel
        r2 = self.orchestrator.chat("cancel that")
        self.assertIn("Cancel", r2["message"])
        self.assertIsNone(self.orchestrator.pending_action)

    def test_ordinary_chat_does_not_break_without_pending_action(self):
        """Verify normal chat turns work cleanly."""
        r1 = self.orchestrator.chat("Hello!")
        self.assertTrue(len(r1["message"]) > 0)
        self.assertIsNone(self.orchestrator.pending_action)

        r2 = self.orchestrator.chat("ನಮಸ್ಕಾರ")
        self.assertEqual(r2.get("task", {}).get("language"), "kn")


if __name__ == "__main__":
    unittest.main()
