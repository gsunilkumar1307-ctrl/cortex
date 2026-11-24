"""
P7.3 Integration and Safety Test Suite:
Intelligent Email Search, Unified Multi-Account Intelligence,
and Critical P0 Safety Corrections.
"""

from __future__ import annotations

import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from backend.core.contracts import TaskCommand, TaskStatus, command_from_intent, Task, RiskLevel
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailDraft, EmailEngine
from backend.persistence.task_store import TaskStore, MailDeliveryStatus
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records


class TestMailSearchAndAccounts(unittest.TestCase):
    def setUp(self) -> None:
        clear_mail_records()
        self.orchestrator = CortexOrchestrator()
        self.orchestrator.use_gemini = False
        self.task_store = getattr(self.orchestrator, "task_store", None)
        if self.task_store:
            with self.task_store._connect() as conn:
                conn.execute("DELETE FROM mail_send_attempts;")
                conn.execute("DELETE FROM approvals;")
                conn.execute("DELETE FROM audit_events;")
                conn.execute("DELETE FROM tasks WHERE id = 'task-approval-lifecycle';")
                conn.commit()

    def tearDown(self) -> None:
        clear_mail_records()
        if self.task_store:
            with self.task_store._connect() as conn:
                conn.execute("DELETE FROM mail_send_attempts;")
                conn.execute("DELETE FROM approvals;")
                conn.execute("DELETE FROM audit_events;")
                conn.execute("DELETE FROM tasks WHERE id = 'task-approval-lifecycle';")
                conn.commit()

    # ── 1. Intelligent Natural Language Search Parameter Parsing ──────────

    def test_01_search_query_parsing_sender(self) -> None:
        queries = [
            ("Do I have any mail from Apple?", "Apple"),
            ("Show me the latest email from Rahul Hulikatti.", "Rahul Hulikatti"),
            ("Did Google send me anything?", "Google"),
            ("Find emails from RVCE.", "RVCE"),
            ("Find the latest reply from my project guide.", "my project guide"),
        ]
        for prompt, expected_sender in queries:
            cmd = command_from_intent(prompt)
            self.assertEqual(cmd, TaskCommand.SEARCH_MAIL, f"Failed command classification for: {prompt}")
            params = self.orchestrator._extract_mail_search_params(prompt)
            self.assertEqual(params.get("sender"), expected_sender, f"Failed sender extraction for: {prompt}")

    def test_02_search_query_parsing_unread(self) -> None:
        prompt = "Show unread emails from Instagram."
        cmd = command_from_intent(prompt)
        self.assertEqual(cmd, TaskCommand.SEARCH_MAIL)
        params = self.orchestrator._extract_mail_search_params(prompt)
        self.assertEqual(params.get("sender"), "Instagram")
        self.assertTrue(params.get("unread_only"))

    def test_03_search_query_parsing_keywords_and_topics(self) -> None:
        p1 = "Find the latest email about my project."
        params1 = self.orchestrator._extract_mail_search_params(p1)
        self.assertEqual(params1.get("subject"), "my project")
        self.assertEqual(params1.get("limit"), 1)

        p2 = "Search all accounts for emails containing the word internship."
        params2 = self.orchestrator._extract_mail_search_params(p2)
        self.assertEqual(params2.get("query"), "internship")
        self.assertTrue(params2.get("all_accounts"))

        p3 = "Find the interview invitation I received last week."
        params3 = self.orchestrator._extract_mail_search_params(p3)
        self.assertIn("interview invitation", params3.get("query"))
        self.assertIsNotNone(params3.get("date_from"))

    def test_04_search_query_parsing_date_expressions(self) -> None:
        p1 = "Show me emails received between Monday and Friday."
        params1 = self.orchestrator._extract_mail_search_params(p1)
        self.assertIn("Monday to Friday", params1.get("date_expression", ""))

        p2 = "Find emails received today."
        params2 = self.orchestrator._extract_mail_search_params(p2)
        self.assertIsNotNone(params2.get("date_from"))
        self.assertIsNotNone(params2.get("date_to"))

        p3 = "Find emails from yesterday."
        params3 = self.orchestrator._extract_mail_search_params(p3)
        self.assertIsNotNone(params3.get("date_from"))
        self.assertIsNotNone(params3.get("date_to"))

    # ── 2. SEARCH_MAIL Execution in Orchestrator ──────────────────────────

    def test_05_search_mail_orchestrator_execution(self) -> None:
        sample_results = [
            {
                "account": "Google",
                "mailbox": "INBOX",
                "sender": "Apple <no_reply@email.apple.com>",
                "sender_email": "no_reply@email.apple.com",
                "subject": "Your Apple ID was used to sign in to iCloud",
                "date": "Today, 10:00 AM",
                "is_read": False,
                "snippet": "Your Apple ID was used to sign in to iCloud from a new browser.",
            }
        ]

        with patch.object(self.orchestrator.automation.mail, "search_mail", return_value={"ok": True, "emails": sample_results}):
            res = self.orchestrator.chat("Do I have any mail from Apple?")
            msg = res.get("message", "")
            task = res.get("task", {})

            self.assertEqual(task.get("command"), TaskCommand.SEARCH_MAIL.value)
            self.assertEqual(task.get("status"), TaskStatus.COMPLETED.value)
            self.assertIn("[Google: INBOX]", msg)
            self.assertIn("Apple", msg)
            self.assertIn("Apple ID was used", msg)
            self.assertIn("[UNREAD]", msg)

    def test_06_search_mail_empty_results_handling(self) -> None:
        with patch.object(self.orchestrator.automation.mail, "search_mail", return_value={"ok": True, "emails": []}):
            res = self.orchestrator.chat("Find emails from nonexistent_sender_12345.")
            msg = res.get("message", "")
            self.assertIn("No emails found", msg)

    # ── 3. Multi-Account Intelligence ─────────────────────────────────────

    def test_07_dynamic_account_discovery_no_mock_accounts(self) -> None:
        mail = self.orchestrator.automation.mail
        accounts = mail.get_accounts()
        self.assertIsInstance(accounts, list)
        self.assertTrue(len(accounts) >= 1)
        # Ensure hardcoded mock identity strings are eliminated
        for acc in accounts:
            self.assertNotEqual(acc.get("email"), "me@cortex.internal")
            self.assertNotEqual(acc.get("email"), "student@university.edu")

    def test_08_contextual_account_switching_in_draft_edit(self) -> None:
        draft = EmailDraft(
            recipient="rahul@example.com",
            subject="Project Sync",
            body="Hi Rahul,\n\nLet's meet tomorrow.\n\nBest regards,",
            sender_account="Google (gsunilkumar1307@gmail.com)",
        )
        initial_hash = draft.compute_hash()

        # Switch to work account
        updated = self.orchestrator.email_engine.update_draft_with_edit(draft, "Send this from my work account")
        self.assertEqual(updated.sender_account, "Work Account")
        # Cryptographic approval hash must be recomputed upon account alteration
        self.assertNotEqual(updated.approval_hash, initial_hash)
        self.assertEqual(updated.approval_hash, updated.compute_hash())

    def test_09_non_destructive_draft_refinement(self) -> None:
        draft = EmailDraft(
            recipient="rahul@example.com",
            subject="Project Sync",
            body="Hi Rahul,\n\nPlease find the project documentation attached.\n\nBest regards,\nSunil",
        )
        initial_body = draft.body

        # Conversational edit to add detail
        updated = self.orchestrator.email_engine.update_draft_with_edit(draft, "Also mention that the presentation is scheduled for 3 PM")
        self.assertIn("Hi Rahul", updated.body)
        self.assertIn("presentation is scheduled for 3 PM", updated.body)
        self.assertIn("Best regards,", updated.body)
        self.assertIn("project documentation attached", updated.body)

    # ── 4. P0 Critical Safety Hardening ───────────────────────────────────

    def test_10_sent_verification_timestamp_correlation(self) -> None:
        mail = self.orchestrator.automation.mail
        # Record a past message from 1 hour ago
        one_hour_ago = time.time() - 3600
        dispatch_time = time.time()

        def mock_verifier(recipient, subject, account="", limit=25, since_timestamp=None):
            # If verifier enforces since_timestamp, the old message cannot verify a dispatch from now
            if since_timestamp and since_timestamp > one_hour_ago:
                return {
                    "verified": False,
                    "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "evidence": "No message found sent after dispatch timestamp.",
                }
            return {
                "verified": True,
                "status": MailDeliveryStatus.SENT_VERIFIED.value,
                "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value,
                "evidence": "Matched message.",
            }

        mail._mock_sent_verifier = mock_verifier
        try:
            res = mail.verify_mail_sent(
                recipient="rahul@example.com",
                subject="Test Subject",
                since_timestamp=dispatch_time,
            )
            self.assertFalse(res["verified"])
            self.assertEqual(res["status"], MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)
        finally:
            mail._mock_sent_verifier = None

    def test_11_atomic_idempotency_reservation_concurrency(self) -> None:
        if not self.task_store:
            self.skipTest("TaskStore not configured")

        payload_hash = "sha256_mock_hash_concurrency_test_01"
        recipient = "rahul@example.com"
        subject = "Concurrent Dispatch Test"

        # Thread/Client 1 reserves
        r1, reason1, attempt1 = self.task_store.reserve_mail_send_attempt(
            task_id="task-01",
            payload_hash=payload_hash,
            recipient=recipient,
            subject=subject,
        )
        self.assertTrue(r1)
        self.assertEqual(attempt1.get("status"), MailDeliveryStatus.SEND_ATTEMPTED.value)

        # Thread/Client 2 attempts to reserve identical payload_hash concurrently
        r2, reason2, attempt2 = self.task_store.reserve_mail_send_attempt(
            task_id="task-02",
            payload_hash=payload_hash,
            recipient=recipient,
            subject=subject,
        )
        self.assertFalse(r2)
        self.assertIn("Duplicate send prevented", reason2)

    def test_12_blocked_state_auditable_reauthorization(self) -> None:
        if not self.task_store:
            self.skipTest("TaskStore not configured")

        payload_hash = "sha256_mock_hash_blocked_test_02"
        # First record a BLOCKED attempt
        self.task_store.record_mail_send_attempt(
            task_id="task-blocked",
            payload_hash=payload_hash,
            recipient="malicious@test.com",
            subject="Blocked Content",
            status=MailDeliveryStatus.BLOCKED.value,
        )

        # Confirm send attempt cannot be reserved while BLOCKED
        reserved, res_msg, _ = self.task_store.reserve_mail_send_attempt(
            task_id="task-retry",
            payload_hash=payload_hash,
            recipient="malicious@test.com",
            subject="Blocked Content",
        )
        self.assertFalse(reserved)
        self.assertIn("blocked", res_msg.lower())

        # Administrator / user reauthorizes
        ok, reauth_msg = self.task_store.reauthorize_mail_send_attempt(
            payload_hash=payload_hash,
            reason="Verified safe destination and explicit user confirmation.",
            authorized_by="security_admin",
        )
        self.assertTrue(ok)

        # Verify state transitioned to NOT_ATTEMPTED and audit event recorded
        attempt = self.task_store.get_mail_send_attempt_by_hash(payload_hash)
        self.assertEqual(attempt.get("status"), MailDeliveryStatus.NOT_ATTEMPTED.value)

        # Now reservation succeeds
        r3, _, _ = self.task_store.reserve_mail_send_attempt(
            task_id="task-reauthorized",
            payload_hash=payload_hash,
            recipient="malicious@test.com",
            subject="Blocked Content",
        )
        self.assertTrue(r3)

    def test_13_approval_lifecycle_expiration_and_replay_prevention(self) -> None:
        if not self.task_store:
            self.skipTest("TaskStore not configured")

        task_id = "task-approval-lifecycle"
        payload_hash = "sha256_approval_lifecycle_hash_03"

        dummy_task = Task(
            id=task_id,
            intent="Send approved project email",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            status=TaskStatus.WAITING_APPROVAL,
        )
        self.task_store.save_task(dummy_task)

        # Record approval with 1-second expiration
        self.task_store.record_approval(
            task_id=task_id,
            payload_hash=payload_hash,
            expires_in_seconds=1,
        )

        # Consume immediately (should succeed)
        ok1, msg1 = self.task_store.consume_approval(task_id, payload_hash)
        self.assertTrue(ok1, msg1)

        # Replay attempt (must fail)
        ok2, msg2 = self.task_store.consume_approval(task_id, payload_hash)
        self.assertFalse(ok2)
        self.assertIn("replay", msg2.lower())

        # Test expiration
        payload_hash_exp = "sha256_approval_exp_hash_04"
        self.task_store.record_approval(
            task_id=task_id,
            payload_hash=payload_hash_exp,
            expires_in_seconds=1,
        )
        time.sleep(1.2)
        ok3, msg3 = self.task_store.consume_approval(task_id, payload_hash_exp)
        self.assertFalse(ok3)
        self.assertIn("expired", msg3.lower())


if __name__ == "__main__":
    unittest.main()
