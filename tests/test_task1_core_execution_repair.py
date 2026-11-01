"""Tests for Task 1: Core Execution Path Repair.

Verifies:
1. Cancellation priority over in-place editing for pending email drafts.
2. Word-boundary checks preventing 'dr' from matching 'draft'.
3. 'Make it shorter and more formal' handling for active drafts and conversational context.
4. Clean search query extraction without conversational framing or trailing summary meta-instructions.
5. Removal of generic foundation-model boilerplate from ordinary knowledge questions.
6. Specific, verified action execution feedback replacing bare 'Done.' responses.
7. Indic / code-switched email parsing without character truncation.
8. WhatsApp meta-instruction stripping and unverified contact safety warnings.
"""

from __future__ import annotations

import unittest
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, TaskStatus
from backend.capabilities.whatsapp_actions import compose_whatsapp_message, format_whatsapp_approval_card
from backend.core.contracts import WhatsAppDraft


class TestTask1CoreExecutionRepair(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(use_gemini=False)

    def test_cancellation_priority_over_editing(self) -> None:
        """1. 'Cancel the email draft and do not send anything' must cancel immediately."""
        self.orchestrator.chat("Draft an email to dr.sharma@hospital.org saying the surgery schedule has been updated to next week")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action["type"], "email_draft")

        res = self.orchestrator.chat("Cancel the email draft and do not send anything")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertIn("Cancel", res["message"])
        self.assertNotIn("Hi dr.sharma@hospital.org", res["message"])

    def test_word_boundary_keyword_matching(self) -> None:
        """2. 'dr' keyword must not match 'draft' as a substring."""
        self.orchestrator.chat("Draft an email to dr.sharma@hospital.org saying review required")
        # 'Cancel this draft' has 'draft', which has 'dr', but must not be treated as an edit
        res = self.orchestrator.chat("Cancel this draft")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertIn("Cancel", res["message"])

    def test_make_it_shorter_and_more_formal_on_active_draft(self) -> None:
        """3A. 'Make it shorter and more formal' on active draft applies both shortening and formal tone."""
        self.orchestrator.chat(
            "Draft an email to dr.sharma@hospital.org saying The surgery schedule has been updated to next week. "
            "Please review the updated schedule at your earliest convenience."
        )
        self.assertIsNotNone(self.orchestrator.pending_action)
        orig_body = self.orchestrator.pending_action["draft"].body

        res = self.orchestrator.chat("Make it shorter and more formal")
        self.assertIsNotNone(self.orchestrator.pending_action)
        updated_draft = self.orchestrator.pending_action["draft"]

        self.assertIn("Dear", updated_draft.body)
        self.assertIn("Sincerely", updated_draft.body)
        self.assertNotEqual(orig_body, updated_draft.body)

    def test_make_it_shorter_and_more_formal_on_conversational_answer(self) -> None:
        """3B. 'Make it shorter and more formal' modifies the previous conversational answer without web search."""
        res1 = self.orchestrator.chat("What is quantum computing?")
        self.assertTrue(len(res1["message"]) > 20)

        res2 = self.orchestrator.chat("Make it shorter and more formal")
        # Must not search DuckDuckGo for Formalizer
        self.assertNotIn("Formalizer", res2["message"])
        self.assertNotIn("AI Humanizer", res2["message"])
        self.assertIn("formal terms", res2["message"].lower())

    def test_search_query_stripping(self) -> None:
        """4. Strips leading conversational framing and trailing meta-instructions from web search queries."""
        p1 = self.orchestrator._extract_params(
            TaskCommand.WEB_SEARCH,
            "Search the web for latest AI news and summarize the findings"
        )
        self.assertEqual(p1["query"], "latest AI news")

        p2 = self.orchestrator._extract_params(
            TaskCommand.WEB_SEARCH,
            "Can you please search for quantum computing and give me a summary"
        )
        self.assertEqual(p2["query"], "quantum computing")

        p3 = self.orchestrator._extract_params(
            TaskCommand.WEB_SEARCH,
            "Open Safari and search for latest update in AI and summarize it"
        )
        self.assertEqual(p3["query"], "latest update in AI")
        self.assertEqual(p3["browser"], "Safari")

    def test_ordinary_knowledge_no_foundation_model_boilerplate(self) -> None:
        """5. General non-AI queries must not have 'foundation models' boilerplate stamped onto them."""
        results = [{
            "title": "Why is the sky blue?",
            "body": "The sky is blue because gases in Earth's atmosphere scatter blue sunlight in all directions.",
            "href": "https://example.com/sky"
        }]
        summary = self.orchestrator._summarize_search("Why is the sky blue?", results)
        self.assertNotIn("foundation models", summary)
        self.assertIn("sky is blue", summary)

    def test_finder_intent_and_param_extraction(self) -> None:
        """6. Finder requests are classified as OPEN_APP with specific action execution."""
        from backend.core.contracts import command_from_intent
        cmd1 = command_from_intent("Show Documents in Finder")
        self.assertEqual(cmd1, TaskCommand.OPEN_APP)

        p1 = self.orchestrator._extract_params(cmd1, "Show Documents in Finder")
        self.assertEqual(p1["appName"], "Finder")
        self.assertEqual(p1.get("folder"), "Documents")

        cmd2 = command_from_intent("Open Finder")
        self.assertEqual(cmd2, TaskCommand.OPEN_APP)

    def test_no_bare_done_responses(self) -> None:
        """7. Desktop actions return verified, descriptive messages, never bare 'Done.'."""
        # Using dry_run automation
        self.orchestrator.automation.dry_run = True
        res = self.orchestrator.chat("Open Safari")
        self.assertNotEqual(res["message"].strip(), "Done.")
        self.assertIn("Safari", res["message"])

    def test_kannada_email_command_parsing(self) -> None:
        """8. Kannada email command must extract clean recipient without body truncation bug ('ಇ')."""
        p1 = self.orchestrator._extract_params(TaskCommand.SEND_MAIL, "ಮನೋಜ್‌ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸು")
        self.assertEqual(p1["body"], "")
        self.assertIn("ಮನೋಜ್", p1["recipient"])

        p2 = self.orchestrator._extract_params(TaskCommand.SEND_MAIL, "ಕನ್ನಡದಲ್ಲಿ ಇಮೇಲ್ ಕಳುಹಿಸು")
        self.assertEqual(p2["recipient"], "")
        self.assertEqual(p2["body"], "")

    def test_whatsapp_quote_stripping_do_not_send(self) -> None:
        """9. Quoted instructions in WhatsApp must strip 'Do not send it'."""
        msg = compose_whatsapp_message(
            '"I will be 15 minutes late. Do not send it."',
            recipient_name="Rahul"
        )
        self.assertNotIn("Do not send it", msg)
        self.assertIn("15 minutes late", msg)

    def test_whatsapp_unverified_recipient_warning(self) -> None:
        """10. Unverified recipient warning appears clearly on the WhatsApp approval card."""
        draft = WhatsAppDraft(
            recipient="+919999999999",
            phone="+919999999999",
            body="Hello.",
            contact_source="user_provided_unverified",
        )
        card = format_whatsapp_approval_card(draft, lang_code="en")
        self.assertIn("Unverified Recipient Identity", card)


if __name__ == "__main__":
    unittest.main()

