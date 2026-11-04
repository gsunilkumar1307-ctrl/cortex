import unittest
from unittest.mock import patch
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, command_from_intent, is_self_capability_query


class TestCapabilityRouting(unittest.TestCase):
    def setUp(self):
        self.orchestrator = CortexOrchestrator(use_gemini=False)

    def test_reported_defect_reproduced_and_fixed(self):
        """
        User asks: 'What can you help me with? Give me five specific things you can actually do on this Mac.'
        Must NOT trigger web search (DuckDuckGo), must return 5 real verified capabilities,
        system status tiers, and safety boundaries.
        """
        query = "What can you help me with? Give me five specific things you can actually do on this Mac."
        
        # 1. Routing contract check
        self.assertTrue(is_self_capability_query(query))
        self.assertEqual(command_from_intent(query), TaskCommand.ASK_QUESTION)

        # 2. Execution check with mock to assert search_web is NEVER invoked
        with patch("backend.agent.orchestrator.search_web") as mock_search:
            res = self.orchestrator.chat(query)
            mock_search.assert_not_called()

        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "")
        self.assertIn("five specific things", msg.lower())
        self.assertIn("safari", msg.lower())
        self.assertIn("screen observation", msg.lower())
        self.assertIn("apple mail", msg.lower())
        self.assertIn("finder", msg.lower())
        self.assertIn("apple notes", msg.lower())
        
        # Confirm no web search artifacts
        self.assertNotIn("macrumors", msg.lower())
        self.assertNotIn("snippet only", msg.lower())
        self.assertNotIn("cortex ai overview:", msg.lower())

    def test_screen_reading_inquiry_vs_command(self):
        """
        'Can you read my screen?' -> capability inquiry (ASK_QUESTION), no action.
        'Observe my screen and tell me the active application, active window, and five visible elements.' -> action (OBSERVE_SCREEN).
        """
        inquiry = "Can you read my screen?"
        self.assertTrue(is_self_capability_query(inquiry))
        self.assertEqual(command_from_intent(inquiry), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(inquiry)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        self.assertIn("accessibility", res.get("message", "").lower())
        self.assertIn("screen recording", res.get("message", "").lower())

        action = "Observe my screen and tell me the active application, active window, and five visible elements."
        self.assertFalse(is_self_capability_query(action))
        self.assertEqual(command_from_intent(action), TaskCommand.OBSERVE_SCREEN)

    def test_email_draft_inquiry_vs_command(self):
        """
        'Can you create an email draft?' -> capability inquiry (ASK_QUESTION).
        'Draft an email to Rahul about tomorrow project meeting. Do not send it.' -> action (DRAFT_MAIL).
        """
        inquiry = "Can you create an email draft?"
        self.assertTrue(is_self_capability_query(inquiry))
        self.assertEqual(command_from_intent(inquiry), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(inquiry)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        self.assertIn("apple mail", res.get("message", "").lower())
        self.assertIn("approval", res.get("message", "").lower())

        action = "Draft an email to Rahul about tomorrow project meeting. Do not send it."
        self.assertFalse(is_self_capability_query(action))
        self.assertEqual(command_from_intent(action), TaskCommand.DRAFT_MAIL)

    def test_safari_inquiry_vs_command(self):
        """
        'Are you able to use Safari?' -> capability inquiry (ASK_QUESTION).
        'Open Safari, search for latest AI developments' -> action (WEB_SEARCH).
        """
        inquiry = "Are you able to use Safari?"
        self.assertTrue(is_self_capability_query(inquiry))
        self.assertEqual(command_from_intent(inquiry), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(inquiry)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        self.assertIn("safari", res.get("message", "").lower())

        action = "Open Safari, search for latest AI developments"
        self.assertFalse(is_self_capability_query(action))
        self.assertEqual(command_from_intent(action), TaskCommand.WEB_SEARCH)

    def test_which_apps_can_you_control(self):
        query = "Which apps can you control?"
        self.assertTrue(is_self_capability_query(query))
        self.assertEqual(command_from_intent(query), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(query)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "").lower()
        self.assertIn("safari", msg)
        self.assertIn("apple mail", msg)
        self.assertIn("finder", msg)
        self.assertIn("apple notes", msg)

    def test_what_are_your_current_limitations(self):
        query = "What are your current limitations?"
        self.assertTrue(is_self_capability_query(query))
        self.assertEqual(command_from_intent(query), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(query)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "").lower()
        self.assertIn("safety", msg)
        self.assertIn("permissions", msg)

    def test_legitimate_web_research_not_blocked(self):
        """
        Legitimate web research queries must NOT be misclassified as self-capability questions.
        """
        q1 = "Search the web for the latest Cortex alternatives"
        self.assertFalse(is_self_capability_query(q1))
        self.assertEqual(command_from_intent(q1), TaskCommand.WEB_SEARCH)

        q2 = "Find recent articles about macOS automation tools"
        self.assertFalse(is_self_capability_query(q2))
        self.assertEqual(command_from_intent(q2), TaskCommand.WEB_SEARCH)

    def test_external_general_questions_not_blocked(self):
        """
        Questions about external AI models must not trigger Cortex self-capability responses.
        """
        q = "What are the capabilities of GPT-4?"
        self.assertFalse(is_self_capability_query(q))
        self.assertEqual(command_from_intent(q), TaskCommand.ASK_QUESTION)

    def test_followup_preservation(self):
        """
        'Make the summary shorter' and 'Open the second result' must continue to work normally.
        """
        q_shorten = "Make the summary shorter"
        self.assertFalse(is_self_capability_query(q_shorten))
        self.assertNotEqual(command_from_intent(q_shorten), TaskCommand.WEB_SEARCH)

        q_open = "Open the second result"
        self.assertFalse(is_self_capability_query(q_open))
        self.assertEqual(command_from_intent(q_open), TaskCommand.OPEN_URL)

        # Verify chat execution shortens summary without triggering web search
        overview = (
            "### Cortex AI Overview: Latest AI Developments\n\n"
            "Recent reporting highlights significant progress.\n\n"
            "**Key Developments & Insights:**\n"
            "• **AlphaFold 3**: Deep structures predicted.\n\n"
            "**Sources & Citations:**\n"
            "1. [AlphaFold 3](https://deepmind.google/technologies/alphafold/)"
        )
        self.orchestrator.history.append({"role": "user", "parts": ["Search for latest AI developments"]})
        self.orchestrator.history.append({"role": "model", "parts": [overview]})

        with patch("backend.agent.orchestrator.search_web") as mock_search:
            res = self.orchestrator.chat("Make the summary shorter.")
            mock_search.assert_not_called()
            self.assertIn("Condensed Summary", res.get("message", ""))

    def test_kannada_capability_inquiry(self):
        query = "ನೀವೇನು ಮಾಡಬಲ್ಲಿರಿ?"
        self.assertTrue(is_self_capability_query(query))
        self.assertEqual(command_from_intent(query), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(query)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "")
        self.assertIn("ಕಾರ್ಟೆಕ್ಸ್", msg)
        self.assertIn("ಸಫಾರಿ", msg)

    def test_hindi_capability_inquiry(self):
        query = "आप क्या कर सकते हैं?"
        self.assertTrue(is_self_capability_query(query))
        self.assertEqual(command_from_intent(query), TaskCommand.ASK_QUESTION)
        res = self.orchestrator.chat(query)
        self.assertEqual(res.get("task", {}).get("command"), TaskCommand.ASK_QUESTION)
        msg = res.get("message", "")
        self.assertTrue("Cortex" in msg or "कॉर्टेक्स" in msg)
        self.assertIn("सफारी", msg)


if __name__ == "__main__":
    unittest.main()
