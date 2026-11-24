"""
Test Suite for Cortex Agent — P7.6 Focused Mail Intelligence Remediation

Validates the three core defect fixes:
Defect A: Email body contamination (no 'Leave Request Draft:' or 'Note to Self:' headers)
Defect B: Conversational email-investigation context (following up on self.last_mail_results)
Defect C: Company / domain / subject search false negatives & intent preservation
"""

import unittest
from unittest.mock import MagicMock, patch
from backend.core.contracts import TaskCommand, TaskStatus
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailEngine
from backend.capabilities.mail_actions import MailAutomation, _term_matches


class TestEmailIntelligenceP76Remediation(unittest.TestCase):
    def setUp(self):
        self.orch = CortexOrchestrator()
        self.email_engine = EmailEngine()
        self.mail_auto = MailAutomation()

    # ── Defect A: Email Body Contamination ────────────────────────────────────

    def test_defect_a_professor_leave_draft_has_no_internal_labels(self):
        """Canonical draft body for leave request must not include 'Leave Request Draft:' label."""
        draft = self.email_engine.compose_email(
            raw_intent="Write to my professor requesting leave tomorrow",
            recipient_raw="Professor Sharma",
            content="requesting leave tomorrow",
            use_gemini=False,
        )
        self.assertNotIn("Leave Request Draft:", draft.body)
        self.assertTrue(
            draft.body.startswith("Dear Professor Sharma,") or draft.body.startswith("Hello"),
            f"Draft body should start with salutation, got: {draft.body[:50]}",
        )

    def test_defect_a_note_to_self_has_no_internal_labels(self):
        """Canonical draft body for note to self must not include 'Note to Self:' label."""
        draft = self.email_engine.compose_email(
            raw_intent="Send mail to myself saying remember to review PR",
            recipient_raw="myself",
            content="remember to review PR",
            use_gemini=False,
        )
        self.assertNotIn("Note to Self:", draft.body)
        self.assertIn("Remember to review PR", draft.body)

    # ── Defect C: Company / Domain / Subject Matching & Intent Preservation ──

    def test_defect_c_term_matches_domain_subtokens(self):
        """_term_matches must match company names in sender email domains."""
        self.assertTrue(_term_matches("pentagon", "campusconnect@pentagonspace.in"))
        self.assertTrue(_term_matches("pentagon space", "campusconnect@pentagonspace.in"))
        self.assertTrue(_term_matches("google", "alerts@google.com"))
        self.assertTrue(_term_matches("apple", "support@apple.com"))

    def test_defect_c_apple_sender_does_not_match_unrelated_newsletter_domain(self):
        """_term_matches must not match Apple in an unrelated newsletter sender email."""
        self.assertFalse(_term_matches("apple", "hi@mail.theresanaiforthat.com"))
        self.assertFalse(_term_matches("apple", "TAAFT"))

    def test_defect_c_search_mail_filters_apple_sender_vs_about(self):
        """Strict 'from Apple' must return 0 for TAAFT newsletter, but 'about Apple' matches."""
        taaft_email = {
            "id": "5119",
            "sender": "TAAFT",
            "sender_email": "hi@mail.theresanaiforthat.com",
            "subject": "🏠 Apple Trains Robots in Fake Homes",
            "date": "11/15/2026",
            "is_read": True,
            "snippet": "Apple Trains Robots in Fake Homes",
        }

        # 1. Search 'FROM Apple' -> snd_lower is 'apple'
        matches_from = self.mail_auto._matches_filters(
            taaft_email,
            q_lower="apple",
            snd_lower="apple",
            rec_lower="",
            sbj_lower="",
            acc_lower="",
            mbx_lower="",
            unread_only=False,
            dt_from=None,
            dt_to=None,
        )
        self.assertFalse(matches_from, "Newsletter mentioning Apple in subject must NOT match 'from Apple'")

        # 2. Search 'ABOUT Apple' -> snd_lower is empty, sbj_lower is 'apple'
        matches_about = self.mail_auto._matches_filters(
            taaft_email,
            q_lower="apple",
            snd_lower="",
            rec_lower="",
            sbj_lower="apple",
            acc_lower="",
            mbx_lower="",
            unread_only=False,
            dt_from=None,
            dt_to=None,
        )
        self.assertTrue(matches_about, "'About Apple' search MUST match email with Apple in subject")

    def test_defect_c_search_mail_matches_pentagon_space_sender_domain(self):
        """Pentagon Space email must match when searched by company/sender."""
        pentagon_email = {
            "id": "6319",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "is_read": True,
            "snippet": "Google Meet Link for Group Discussion - Pentagon Space",
        }

        # Search with snd_lower = 'pentagon space'
        matches = self.mail_auto._matches_filters(
            pentagon_email,
            q_lower="pentagon space",
            snd_lower="pentagon space",
            rec_lower="",
            sbj_lower="",
            acc_lower="",
            mbx_lower="",
            unread_only=False,
            dt_from=None,
            dt_to=None,
        )
        self.assertTrue(matches, "Pentagon Space email must match via sender domain pentagonspace.in")

    # ── Defect B: Conversational Email Investigation Context ─────────────────

    def test_defect_b_empty_last_mail_results_returns_helpful_guidance(self):
        """Asking email follow-up with no recent search results prompts to search first."""
        self.orch.last_mail_results = []
        res = self.orch.chat("What are they asking me to do?")
        self.assertIn("No recent email search results found in context", res["message"])

    def test_defect_b_investigation_what_are_they_asking(self):
        """Asking 'What are they asking me to do?' extracts actionable content from context."""
        self.orch.last_mail_results = [{
            "id": "6319",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "body": (
                "Hello everyone, please find the Google Meet link below. Kindly join on time.\n\n"
                "Date: 12-11-2026\nTime: 04:30 PM\nBatch No: 05\n"
                "Meet Link : https://meet.google.com/zwz-oxsx-uaf\n"
            ),
        }]
        res = self.orch.chat("What are they asking me to do?")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("https://meet.google.com/zwz-oxsx-uaf", res["message"])
        self.assertIn("Campus Connect", res["message"])

    def test_defect_b_investigation_when_is_the_deadline(self):
        """Asking 'When is the deadline?' extracts scheduled time from email context."""
        self.orch.last_mail_results = [{
            "id": "6319",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "body": "Date: 12-11-2026\nTime: 04:30 PM\nBatch No: 05\nMeet Link : https://meet.google.com/zwz-oxsx-uaf",
        }]
        res = self.orch.chat("When is the deadline?")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("12-11-2026", res["message"])
        self.assertIn("04:30 PM", res["message"])

    def test_defect_b_investigation_show_me_that_email(self):
        """Asking 'Show me that email' renders complete formatted headers and body."""
        self.orch.last_mail_results = [{
            "id": "6319",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "body": "Hello everyone, please join on time.",
        }]
        res = self.orch.chat("Show me that email")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("From: Campus Connect (campusconnect@pentagonspace.in)", res["message"])
        self.assertIn("Subject: Google Meet Link for Group Discussion - Pentagon Space", res["message"])
        self.assertIn("Hello everyone, please join on time.", res["message"])

    def test_defect_b_investigation_who_sent_it(self):
        """Asking 'Who sent it?' identifies the sender from context."""
        self.orch.last_mail_results = [{
            "id": "6319",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "body": "Hello everyone.",
        }]
        res = self.orch.chat("Who sent it?")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("Campus Connect", res["message"])
        self.assertIn("campusconnect@pentagonspace.in", res["message"])

    def test_defect_b_investigation_ordinal_resolution(self):
        """'Explain the second email' selects the second email in last_mail_results."""
        self.orch.last_mail_results = [
            {"id": "1", "sender": "First Sender", "subject": "First Subject", "body": "First content"},
            {"id": "2", "sender": "Second Sender", "subject": "Second Subject", "body": "Second content requesting action"},
        ]
        res = self.orch.chat("Explain the second email")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("Second Subject", res["message"])

    def test_defect_b_reply_asking_for_clarification_wires_to_last_mail(self):
        """'Reply asking for clarification' targets the last retrieved email in context."""
        self.orch.last_mail_results = [{
            "id": "6319",
            "account": "Google",
            "mailbox": "INBOX",
            "sender": "Campus Connect",
            "sender_email": "campusconnect@pentagonspace.in",
            "subject": "Google Meet Link for Group Discussion - Pentagon Space",
            "date": "11/12/2026",
            "body": "Hello everyone.",
        }]
        with patch.object(self.orch.mail_automation, "create_email_draft") as mock_draft:
            mock_draft.return_value = MagicMock(ok=True, data={"draft_id": "draft-123"})
            res = self.orch.chat("Reply asking for clarification")
            self.assertEqual(res["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
            self.assertIn("campusconnect@pentagonspace.in", res["message"])
            self.assertIn("Re: Google Meet Link for Group Discussion - Pentagon Space", res["message"])


if __name__ == "__main__":
    unittest.main()
