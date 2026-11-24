from __future__ import annotations

import unittest
from unittest.mock import patch
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, TaskStatus
from backend.capabilities.mail_actions import clear_mail_records


class TestTask6AppleMail(unittest.TestCase):
    def setUp(self) -> None:
        clear_mail_records()
        self.orchestrator = CortexOrchestrator()
        if hasattr(self.orchestrator, "task_store") and self.orchestrator.task_store:
            with self.orchestrator.task_store._connect() as conn:
                conn.execute("DELETE FROM mail_send_attempts")
                conn.commit()

    def tearDown(self) -> None:
        clear_mail_records()
        if hasattr(self.orchestrator, "task_store") and self.orchestrator.task_store:
            with self.orchestrator.task_store._connect() as conn:
                conn.execute("DELETE FROM mail_send_attempts")
                conn.commit()

    def test_01_draft_mail_resolution_and_content(self) -> None:
        """Requirement 1, 3, 4, 5, 6:
        Resolves Rahul, creates draft, verifies existence, reports draft created but not sent.
        """
        prompt = "Draft an email to Rahul about tomorrow's project meeting. Do not send it."
        res = self.orchestrator.chat(prompt)

        msg = res.get("message", "")
        self.assertIn("rahul@example.com", msg)
        self.assertIn("not been sent", msg.lower())

        task = res.get("task", {})
        self.assertEqual(task.get("status"), TaskStatus.COMPLETED.value)
        self.assertEqual(task.get("command"), TaskCommand.DRAFT_MAIL.value)

        pending = self.orchestrator.pending_action
        self.assertIsNotNone(pending)
        self.assertEqual(pending.get("step"), "confirm_send")

        draft = pending.get("draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.recipient, "rahul@example.com")
        self.assertTrue(len(draft.subject) > 0)
        self.assertIn("meeting", draft.body.lower())
        self.assertNotIn("do not send", draft.body.lower())

    def test_02_multiple_candidates_clarification(self) -> None:
        """Requirement 2:
        If multiple plausible recipients exist, ask one focused clarification question.
        """
        orc = CortexOrchestrator()

        def mock_search_contacts(query: str):
            return [
                {"name": "Rahul Verma", "email": "rahul@example.com", "role": "friend", "department": "", "institution": ""},
                {"name": "Rahul Sharma", "email": "rahul.sharma@example.com", "role": "colleague", "department": "Engineering", "institution": "TechCorp"},
            ]

        orc.automation.mail.search_contacts = mock_search_contacts
        r1 = orc.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")

        # Must ask clarification
        msg1 = r1.get("message", "")
        self.assertIn("multiple candidates", msg1.lower())
        self.assertIn("Rahul Verma", msg1)
        self.assertIn("Rahul Sharma", msg1)
        self.assertEqual(orc.pending_action.get("step"), "waiting_for_recipient_disambiguation")

        # User chooses candidate 1
        r2 = orc.chat("1")
        msg2 = r2.get("message", "")
        self.assertIn("rahul@example.com", msg2)
        self.assertIn("Update regarding Tomorrow's Meeting", msg2)
        self.assertEqual(orc.pending_action.get("step"), "confirm_send")

    def test_03_followup_make_it_shorter_and_more_formal(self) -> None:
        """Requirement 7:
        Follow-up: 'Make it shorter and more formal' adjusts tone and greeting while preserving recipient and subject.
        """
        self.orchestrator.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")
        res = self.orchestrator.chat("Make it shorter and more formal")

        draft = self.orchestrator.pending_action.get("draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.recipient, "rahul@example.com")
        self.assertIn("meeting", draft.subject.lower())
        self.assertIn("Dear Rahul", draft.body)
        self.assertIn("Sincerely", draft.body)
        self.assertIn("meeting", draft.body.lower())

    def test_04_followup_change_subject(self) -> None:
        """Requirement 7:
        Follow-up: 'Change the subject to: Project Sync Tomorrow' updates subject and preserves recipient and body.
        """
        self.orchestrator.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")
        self.orchestrator.chat("Make it shorter and more formal")
        res = self.orchestrator.chat("Change the subject to: Project Sync Tomorrow")

        draft = self.orchestrator.pending_action.get("draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft.recipient, "rahul@example.com")
        self.assertEqual(draft.subject, "Project Sync Tomorrow")
        self.assertIn("Sincerely", draft.body)

    def test_05_followup_cancel_draft(self) -> None:
        """Requirement 7 & 9:
        Follow-up: 'Cancel this draft' removes the draft, invalidates approval hash, and clears pending action.
        """
        self.orchestrator.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")
        res = self.orchestrator.chat("Cancel this draft")

        msg = res.get("message", "")
        self.assertTrue("cancel" in msg.lower() or "action_cancelled" in msg.lower() or "cancelled" in msg.lower())
        self.assertIsNone(self.orchestrator.pending_action)

        # Verify task is canceled and approval_hash is cleared
        task = res.get("task", {})
        self.assertEqual(task.get("status"), TaskStatus.CANCELED.value)
        self.assertIsNone(task.get("params", {}).get("approval_hash"))

    @patch("backend.capabilities.mail_actions.MailAutomation.send_mail")
    @patch("backend.capabilities.mail_actions.MailAutomation.verify_mail_sent")
    def test_06_send_it_approval_consumption_and_replay_protection(self, mock_verify, mock_send) -> None:
        """Requirement 8 & 10:
        'Send it' executes approval, consumes approval hash once, delivers safely without external spam, and rejects replay.
        """
        mock_send.return_value = {"ok": True, "delivery_status": "SENT_VERIFIED", "message": "Email sent to rahul@example.com."}
        mock_verify.return_value = {"verified": True, "status": "SENT_VERIFIED", "delivery_status": "SENT_VERIFIED", "evidence": "Found in Sent mailbox"}

        self.orchestrator.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")
        send_res = self.orchestrator.chat("Send it")

        msg = send_res.get("message", "")
        self.assertIn("sent", msg.lower())
        self.assertIn("rahul", msg.lower())

        task = send_res.get("task", {})
        self.assertEqual(task.get("status"), TaskStatus.COMPLETED.value)
        self.assertIsNone(task.get("error"))

        # Pending action is cleared
        self.assertIsNone(self.orchestrator.pending_action)

        # Single-use approval hash consumption: attempting to approve again must be rejected as a replay
        replay_res = self.orchestrator.approve(task["id"], approved=True)
        self.assertIn("replayed", replay_res.get("error", "").lower())


if __name__ == "__main__":
    unittest.main()

