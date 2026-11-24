"""
tests/test_email_intelligence_batch2_2.py
========================================
Batch 2.2 Remediation Test Suite:
1. Email Reliability & Cooldown Independence:
   - "Which emails require my attention?"
   - "Do I have any upcoming deadlines?"
   - "Any mails from Pentagon?"
   - Operates reliably during Gemini cooldown with honest disclosure.
2. Search Integrity & Mailbox Scope:
   - Correct query extraction (no arbitrary single-token "an" extracted).
   - Clean default mailbox scope (Trash/Spam/Drafts excluded unless explicitly requested).
   - Clear attribution of account and mailbox.
3. Draft Integrity & Factual Consistency:
   - Does not invent dates ("tomorrow"), roles ("Professor"), or reasons ("personal commitments").
   - Exactly one clean professional sign-off, zero duplicate closings.
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import ProfessionalEmailEngine, EmailDraft
from backend.capabilities.mail_actions import MailAutomation
from backend.core.contracts import TaskCommand, TaskStatus


class TestCooldownAndModelIndependence(unittest.TestCase):
    """Verifies that supported email operations complete deterministically during Gemini cooldown."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=True)
        # Simulate active rate-limit / quota cooldown on Gemini
        self.orch.gemini_cooldown_until = time.time() + 300.0

    def test_which_emails_require_attention_succeeds_during_cooldown(self):
        """'Which emails require my attention?' must NOT raise a Gemini cooldown error."""
        sample_emails = [
            {
                "id": "work-1",
                "sender": "Lead Dev <lead@dev.com>",
                "subject": "PR Review Required",
                "date": "Today, 10:00 AM",
                "body": "Hi Sunil, could you please review the PR by EOD?",
            }
        ]
        with patch.object(self.orch.mail_automation, "read_mail") as mock_read, \
             patch.object(self.orch.mail_automation, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": sample_emails}
            mock_get_msg.return_value = {"ok": True, "email": sample_emails[0]}

            res = self.orch.chat("Which emails require my attention?")
            self.assertEqual(res["task"]["command"], TaskCommand.EXTRACT_ACTIONS.value)
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            msg = res["message"]
            self.assertNotIn("Google Gemini reasoning model is currently cooling down", msg)
            self.assertIn("Lead Dev", msg)
            self.assertIn("local extraction", msg)

    def test_upcoming_deadlines_succeeds_during_cooldown(self):
        """'Do I have any upcoming deadlines?' must NOT raise a Gemini cooldown error."""
        with patch.object(self.orch.mail_automation, "read_mail") as mock_read, \
             patch.object(self.orch.mail_automation, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": []}
            mock_get_msg.return_value = {"ok": True, "email": {}}

            res = self.orch.chat("Do I have any upcoming deadlines?")
            self.assertEqual(res["task"]["command"], TaskCommand.EXTRACT_ACTIONS.value)
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertNotIn("Google Gemini reasoning model is currently cooling down", res["message"])
            self.assertIn("couldn't identify any messages that clearly require a reply or action", res["message"])

    def test_sender_search_succeeds_during_cooldown(self):
        """'Any mails from Pentagon?' must route to SEARCH_MAIL and succeed during cooldown."""
        with patch.object(self.orch.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(
                ok=True,
                data={"emails": [], "coverage": {"status": "complete"}},
                message="No emails found matching 'Pentagon' across connected accounts.",
            )

            res = self.orch.chat("Any mails from Pentagon?")
            self.assertEqual(res["task"]["command"], TaskCommand.SEARCH_MAIL.value)
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertNotIn("Google Gemini reasoning model is currently cooling down", res["message"])
            self.assertEqual(res["task"]["params"]["sender"], "Pentagon")

    def test_company_search_succeeds_during_cooldown(self):
        """'Any mail from Apple?' must route to SEARCH_MAIL and succeed during cooldown."""
        with patch.object(self.orch.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(
                ok=True,
                data={"emails": [], "coverage": {"status": "complete"}},
                message="No emails found matching 'Apple' across connected accounts.",
            )

            res = self.orch.chat("Any mail from Apple?")
            self.assertEqual(res["task"]["command"], TaskCommand.SEARCH_MAIL.value)
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertNotIn("Google Gemini reasoning model is currently cooling down", res["message"])
            self.assertEqual(res["task"]["params"]["sender"], "Apple")


class TestSearchIntegrityAndMailboxScope(unittest.TestCase):
    """Verifies search parameter extraction, default mailbox scoping, and Trash/Spam isolation."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.mail_actions = MailAutomation(dry_run=True)

    def test_search_param_extraction_pentagon(self):
        """'Emails from Pentagon' extracts Pentagon as sender and query."""
        params = self.orch._extract_mail_search_params("Emails from Pentagon")
        self.assertEqual(params["sender"], "Pentagon")
        self.assertEqual(params["query"], "Pentagon")
        self.assertEqual(params["mailbox"], "")

    def test_search_param_extraction_apple(self):
        """'Any mail from Apple?' extracts Apple as sender and query."""
        params = self.orch._extract_mail_search_params("Any mail from Apple?")
        self.assertEqual(params["sender"], "Apple")
        self.assertEqual(params["query"], "Apple")

    def test_search_param_extraction_internship(self):
        """'Find emails about internship' extracts internship as query and subject."""
        params = self.orch._extract_mail_search_params("Find emails about internship")
        self.assertEqual(params["query"], "internship")
        self.assertEqual(params["subject"], "internship")

    def test_an_is_not_extracted_from_unrelated_instruction(self):
        """'Ask about a known email containing an actual request' must NOT extract 'an'."""
        params = self.orch._extract_mail_search_params("Ask about a known email containing an actual request")
        self.assertNotEqual(params["query"], "an")
        self.assertNotEqual(params["subject"], "an")
        self.assertEqual(params["query"], "actual request")

    def test_trash_not_included_in_default_search_scope(self):
        """Normal search must exclude emails from Trash, Deleted Messages, Spam, and Junk."""
        sample_emails = [
            {
                "id": "trash-1",
                "account": "Gmail",
                "mailbox": "[Gmail]/Trash",
                "sender": "Recruiter <jobs@corp.com>",
                "subject": "Interview Request",
                "body": "Here is an actual request.",
                "date": "Today, 11:00 AM",
            },
            {
                "id": "inbox-1",
                "account": "Gmail",
                "mailbox": "INBOX",
                "sender": "Client <client@work.com>",
                "subject": "Project Proposal",
                "body": "Here is an actual request for review.",
                "date": "Today, 10:00 AM",
            },
            {
                "id": "spam-1",
                "account": "Gmail",
                "mailbox": "[Gmail]/Spam",
                "sender": "Spammer <spam@scam.com>",
                "subject": "Claim Prize",
                "body": "An actual request.",
                "date": "Today, 9:00 AM",
            },
        ]

        with patch.object(self.mail_actions, "read_mail") as mock_read:
            mock_read.return_value = {"ok": True, "emails": sample_emails}

            # Normal search with no mailbox specified
            res = self.mail_actions.search_mail(query="actual request")
            self.assertTrue(res["ok"])
            ret_emails = res["emails"]

            # Must contain the INBOX email
            inbox_ids = [e["id"] for e in ret_emails]
            self.assertIn("inbox-1", inbox_ids)

            # Must NOT contain the Trash or Spam emails
            self.assertNotIn("trash-1", inbox_ids)
            self.assertNotIn("spam-1", inbox_ids)

    def test_explicit_trash_search_supported(self):
        """When user explicitly asks for Trash, it must be searched."""
        params = self.orch._extract_mail_search_params("Emails from Google in trash")
        self.assertEqual(params["sender"], "Google")
        self.assertEqual(params["mailbox"], "Trash")

        params2 = self.orch._extract_mail_search_params("Find deleted emails from IBM")
        self.assertEqual(params2["sender"], "IBM")
        self.assertEqual(params2["mailbox"], "Trash")

    def test_explicit_spam_search_supported(self):
        """When user explicitly asks for Spam/Junk, it must set mailbox='Junk'."""
        params = self.orch._extract_mail_search_params("Check spam for confirmation")
        self.assertEqual(params["mailbox"], "Junk")

    def test_search_results_identify_account_and_mailbox(self):
        """Formatted search results must display the account and mailbox attribution."""
        sample_emails = [
            {
                "id": "inbox-apple",
                "account": "Personal",
                "mailbox": "INBOX",
                "sender": "Apple <no_reply@email.apple.com>",
                "subject": "Your Apple Invoice",
                "date": "Nov 18, 2026",
                "is_read": True,
            }
        ]
        with patch.object(self.orch.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(
                ok=True,
                data={"emails": sample_emails, "coverage": {"status": "complete"}},
                message="Found 1 matching email(s)",
            )

            res = self.orch.chat("Any mail from Apple?")
            self.assertIn("[Personal: INBOX]", res["message"])
            self.assertIn("Apple <no_reply@email.apple.com>", res["message"])

    def test_duplicate_drafts_excluded_from_normal_search(self):
        """Draft messages must not pollute normal search results."""
        sample_emails = [
            {
                "id": "draft-1",
                "account": "Gmail",
                "mailbox": "[Gmail]/Drafts",
                "is_draft": True,
                "sender": "Me <sunil@example.com>",
                "subject": "Draft regarding internship",
                "body": "Internship draft",
                "date": "Today, 11:30 AM",
            },
            {
                "id": "inbox-real",
                "account": "Gmail",
                "mailbox": "INBOX",
                "is_draft": False,
                "sender": "Prof. Rao <rao@univ.edu>",
                "subject": "Internship opportunities",
                "body": "Available opportunities",
                "date": "Today, 10:00 AM",
            },
        ]
        with patch.object(self.mail_actions, "read_mail") as mock_read:
            mock_read.return_value = {"ok": True, "emails": sample_emails}

            res = self.mail_actions.search_mail(query="internship")
            ret_ids = [e["id"] for e in res["emails"]]
            self.assertIn("inbox-real", ret_ids)
            self.assertNotIn("draft-1", ret_ids)


class TestDraftIntegrityAndFactualConsistency(unittest.TestCase):
    """Verifies that contextual drafting uses only known facts and does not invent dates or roles."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.engine = ProfessionalEmailEngine()

    def test_leave_request_draft_does_not_invent_dates_roles_or_commitments(self):
        """Drafting leave without dates or roles must NOT invent 'tomorrow', 'Professor', or 'commitments'."""
        query = "A letter for requesting leave"
        draft = self.engine.compose_email(
            raw_intent="send mail to myself",
            recipient_raw="myself",
            content=query,
            use_gemini=False,
        )

        body = draft.body
        # Must NOT assume leave is tomorrow
        self.assertNotIn("tomorrow", body.lower())
        self.assertIn("leave of absence", body.lower())

        # Must NOT assume recipient is a professor
        self.assertNotIn("Dear Professor", body)
        self.assertIn("Dear [Recipient / Manager],", body)

        # Must NOT assume coursework / lab work
        self.assertNotIn("coursework", body.lower())
        self.assertNotIn("lab work", body.lower())

        # Must NOT invent 'prior personal commitments'
        self.assertNotIn("prior personal commitments", body.lower())

        # Must have exactly one closing
        self.assertIn("Sincerely,\nSunil Kumar", body)
        self.assertNotIn("Best regards", body)

    def test_multi_turn_self_leave_request_workflow(self):
        """Simulates User: 'Send mail to myself' -> 'A letter for requesting leave'."""
        with patch.object(self.orch.mail_automation, "get_accounts") as mock_acc, \
             patch.object(self.orch.automation, "execute") as mock_exec:
            mock_acc.return_value = [{"name": "Personal", "email": "sunil@example.com", "default": True}]
            mock_exec.return_value = MagicMock(ok=True)

            r1 = self.orch.chat("Send mail to myself")
            self.assertEqual(r1["task"]["status"], TaskStatus.NEED_INFO.value)
            self.assertIn("What would you like me to send to myself?", r1["message"])

            r2 = self.orch.chat("A letter for requesting leave")
            self.assertEqual(r2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
            msg = r2["message"]

            # Must NOT prepend nested 'Hello,' before the draft
            self.assertNotIn("Hello,\n\nLeave Request Draft:", msg)

            # Must NOT assume 'tomorrow'
            self.assertNotIn("tomorrow", msg.lower())

            # Must NOT assume 'Dear Professor'
            self.assertNotIn("Dear Professor", msg)

            # Must NOT have duplicate sign-offs (e.g. 'Sincerely, Sunil Kumar' followed by 'Best regards')
            self.assertNotIn("Sincerely,\nSunil Kumar\n\nBest regards", msg)
            self.assertNotIn("Sunil Kumar\n\nBest regards", msg)

    def test_explicit_professor_leave_with_date_preserved(self):
        """When user explicitly says 'Write to my professor requesting leave tomorrow', context is respected."""
        with patch.object(self.orch.recipient_resolver, "resolve") as mock_resolve:
            from backend.agent.recipient_resolver import ResolutionResult, ResolvedRecipient
            mock_resolve.return_value = ResolutionResult(
                status="resolved",
                recipient=ResolvedRecipient(
                    name="Prof. Sharma",
                    email="prof.sharma@university.edu",
                    role="professor",
                    source="mock",
                    confidence=1.0,
                )
            )

            draft = self.engine.compose_email(
                raw_intent="Write to my professor requesting leave tomorrow",
                recipient_raw="prof.sharma@university.edu",
                content="Requesting leave tomorrow",
                use_gemini=False,
            )

            # In this case, professor and tomorrow were explicitly specified
            self.assertTrue("Dear Prof" in draft.body or "Dear Professor" in draft.body)
            self.assertIn("tomorrow", draft.body.lower())
            # Must still have a clean single sign-off
            self.assertNotIn("Sincerely\n\nBest regards", draft.body)


if __name__ == "__main__":
    unittest.main()
