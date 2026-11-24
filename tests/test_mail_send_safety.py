from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.email_engine import EmailDraft, EmailEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.policy import PolicyEngine
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records
from backend.core.contracts import MailDeliveryStatus, TaskStatus
from backend.mcp.client import MCPClient
from backend.mcp.config import get_apple_mail_server_config
from backend.mcp.manager import MCPServerManager
from backend.mcp.process import MCPProcess
from backend.mcp.exceptions import MCPSecurityError
from backend.persistence.task_store import TaskStore


class TestMailSendSafety(unittest.TestCase):
    """
    Comprehensive test suite for Phase P7.2:
    Apple Mail Send-Safety Hardening & Delivery Verification.
    """

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_safety.sqlite3")
        self.task_store = TaskStore(self.db_path)
        clear_mail_records(self.db_path)

    def tearDown(self) -> None:
        clear_mail_records(self.db_path)
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. SYNTHETIC-SEND REMOVAL TESTS
    # =========================================================================

    def test_synthetic_send_domains_never_report_success(self) -> None:
        """Verify test domains do not trigger fabricated send success."""
        mail = MailAutomation()
        test_recipients = [
            "test@example.com",
            "user@test.com",
            "admin@cortex.internal",
            "physician@hospital.org",
        ]
        for recipient in test_recipients:
            res = mail.send_mail(
                recipient=recipient,
                subject="Test Subject",
                body="Test Body",
            )
            # In Phase P7.2, real sending is strictly blocked by policy.
            # It must return truthful BLOCKED status, never synthetic ok=True.
            self.assertFalse(res.get("ok", True))
            self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
            self.assertIn("blocked by safety policy", res.get("message", "").lower())

    def test_pytest_env_never_triggers_synthetic_send(self) -> None:
        """Verify PYTEST_CURRENT_TEST in env does not cause fabricated success."""
        mail = MailAutomation()
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_synthetic_send"}):
            res = mail.send_mail(
                recipient="realuser@gmail.com",
                subject="Real Subject",
                body="Real Body",
            )
            self.assertFalse(res.get("ok", True))
            self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)

    def test_draft_deletion_never_reports_delivery(self) -> None:
        """Verify deleting a draft never reports successful delivery."""
        mail = MailAutomation()
        del_res = mail.delete_draft("test@example.com", "Test Subject")
        self.assertNotIn("sent", del_res.get("message", "").lower())
        self.assertNotEqual(del_res.get("status"), MailDeliveryStatus.SENT_VERIFIED.value)

    def test_verify_mail_sent_does_not_rely_on_in_memory_records(self) -> None:
        """Verify verify_mail_sent never treats in-memory records as proof of delivery."""
        mail = MailAutomation()
        # Even if someone populated in-memory _sent_records:
        mail._sent_records.append({
            "recipient": "test@example.com",
            "subject": "In Memory Only",
            "time": "2026-06-17T12:00:00",
        })
        with patch("subprocess.run") as mock_run:
            # Mock AppleScript returning no messages found
            mock_run.return_value = MagicMock(returncode=0, stdout="NOT_FOUND\n", stderr="")
            check = mail.verify_mail_sent("test@example.com", "In Memory Only")
            self.assertFalse(check["verified"])
            self.assertEqual(check["delivery_status"], MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)

    # =========================================================================
    # 2. PERSISTENT IDEMPOTENCY & DUPLICATE PREVENTION TESTS
    # =========================================================================

    def test_task_store_mail_send_attempts_schema_and_persistence(self) -> None:
        """Verify TaskStore schema migration 3 creates mail_send_attempts table and persists records."""
        attempt_id = self.task_store.record_mail_send_attempt(
            task_id="task-123",
            payload_hash="hash-abc-001",
            recipient="alice@example.com",
            subject="Status Report",
            status=MailDeliveryStatus.SEND_ATTEMPTED.value,
        )
        self.assertTrue(len(attempt_id) > 0)

        record = self.task_store.get_mail_send_attempt_by_hash("hash-abc-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["payloadHash"], "hash-abc-001")
        self.assertEqual(record["status"], MailDeliveryStatus.SEND_ATTEMPTED.value)
        self.assertEqual(record["attemptCount"], 1)

    def test_duplicate_send_prevention_across_restarts(self) -> None:
        """Verify duplicate payload_hash is blocked even after recreating TaskStore (simulating restart)."""
        payload_hash = "unique-hash-payload-999"
        self.task_store.record_mail_send_attempt(
            task_id="task-old",
            payload_hash=payload_hash,
            recipient="bob@example.com",
            subject="Quarterly Review",
            status=MailDeliveryStatus.SENT_VERIFIED.value,
        )

        # Simulate fresh process restart with same database
        restarted_store = TaskStore(self.db_path)
        is_dup, reason, existing = restarted_store.check_mail_send_duplicate(payload_hash)
        self.assertTrue(is_dup)
        self.assertIn("duplicate send prevented", reason.lower())
        self.assertIn("sent and verified", reason.lower())
        self.assertIsNotNone(existing)
        self.assertEqual(existing["status"], MailDeliveryStatus.SENT_VERIFIED.value)

    def test_duplicate_send_blocked_for_all_non_repeatable_states(self) -> None:
        """Verify duplicate send is blocked for BLOCKED, SEND_ATTEMPTED, and DELIVERY_UNCONFIRMED."""
        test_states = [
            (MailDeliveryStatus.BLOCKED.value, "previously blocked by safety policy"),
            (MailDeliveryStatus.SEND_ATTEMPTED.value, "in-flight or unconfirmed"),
            (MailDeliveryStatus.DELIVERY_UNCONFIRMED.value, "in-flight or unconfirmed"),
        ]
        for state, expected_sub in test_states:
            p_hash = f"hash-for-state-{state}"
            self.task_store.record_mail_send_attempt(
                task_id=f"task-{state}",
                payload_hash=p_hash,
                recipient="charlie@example.com",
                subject="Meeting",
                status=state,
            )
            is_dup, reason, _ = self.task_store.check_mail_send_duplicate(p_hash)
            self.assertTrue(is_dup)
            self.assertIn(expected_sub, reason.lower())

    # =========================================================================
    # 3. CRYPTOGRAPHIC APPROVAL INTEGRITY TESTS
    # =========================================================================

    def test_approval_hash_covers_all_fields_and_attachments(self) -> None:
        """Verify draft canonicalization produces deterministic SHA-256 over all fields including attachments."""
        # Create temp attachment
        att_path = os.path.join(self.temp_dir.name, "invoice.pdf")
        with open(att_path, "wb") as f:
            f.write(b"PDF-1.4 sample invoice content")

        draft = EmailDraft(
            recipient="dave@example.com",
            subject="Invoice #101",
            body="Please see attached invoice.",
            cc=["finance@example.com"],
            bcc=["audit@example.com"],
            attachments=[att_path],
            sender_account="me@example.com",
        )
        hash_1 = draft.compute_hash()
        self.assertEqual(len(hash_1), 64)

        # Same data -> identical hash
        draft_same = EmailDraft(
            recipient="dave@example.com",
            subject="Invoice #101",
            body="Please see attached invoice.",
            cc=["finance@example.com"],
            bcc=["audit@example.com"],
            attachments=[att_path],
            sender_account="me@example.com",
        )
        self.assertEqual(draft_same.compute_hash(), hash_1)

    def test_approval_invalidated_when_content_or_recipient_modified(self) -> None:
        """Verify changing recipient, subject, body, or attachment invalidates approval hash."""
        att_path = os.path.join(self.temp_dir.name, "doc.txt")
        with open(att_path, "wb") as f:
            f.write(b"Version 1")

        base_draft = EmailDraft(
            recipient="eve@example.com",
            subject="Important Update",
            body="Original message body",
            attachments=[att_path],
        )
        original_hash = base_draft.compute_hash()

        # Recipient modified
        mod_rec = EmailDraft(recipient="mallory@example.com", subject="Important Update", body="Original message body", attachments=[att_path])
        self.assertNotEqual(mod_rec.compute_hash(), original_hash)

        # Subject modified
        mod_subj = EmailDraft(recipient="eve@example.com", subject="Different Subject", body="Original message body", attachments=[att_path])
        self.assertNotEqual(mod_subj.compute_hash(), original_hash)

        # Body modified
        mod_body = EmailDraft(recipient="eve@example.com", subject="Important Update", body="Tampered body", attachments=[att_path])
        self.assertNotEqual(mod_body.compute_hash(), original_hash)

        # Attachment file modified on disk
        with open(att_path, "wb") as f:
            f.write(b"Version 2 - Tampered Content")
        mod_att = EmailDraft(recipient="eve@example.com", subject="Important Update", body="Original message body", attachments=[att_path])
        self.assertNotEqual(mod_att.compute_hash(), original_hash)

    def test_single_use_approval_consumption_and_replay_rejection(self) -> None:
        """Verify approval is consumed once and replay is rejected."""
        orchestrator = CortexOrchestrator(task_store=self.task_store)
        orchestrator.chat("Draft an email to Rahul about tomorrow's project meeting. Do not send it.")
        pending = orchestrator.pending_action
        self.assertIsNotNone(pending)
        task_id = pending["task_id"]

        with patch("backend.capabilities.mail_actions.MailAutomation.send_mail") as mock_send, \
             patch("backend.capabilities.mail_actions.MailAutomation.verify_mail_sent") as mock_verify:
            mock_send.return_value = {"ok": True, "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value, "message": "Email sent to rahul@example.com."}
            mock_verify.return_value = {"verified": True, "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value, "status": MailDeliveryStatus.SENT_VERIFIED.value}

            res1 = orchestrator.chat("Send it")
            self.assertIn("sent", res1.get("message", "").lower())

            # Attempt replay on same task_id
            res2 = orchestrator.approve(task_id, approved=True)
            self.assertIn("replay", res2.get("error", "").lower())

    # =========================================================================
    # 4. SENT MAILBOX BOUNDED VERIFICATION TESTS
    # =========================================================================

    def test_bounded_sent_verification_single_match(self) -> None:
        """Verify exactly one match in Sent mailbox produces SENT_VERIFIED."""
        mail = MailAutomation()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="FOUND|id-99|2026-06-17 14:30:00|frank@example.com|Project Status\n",
                stderr="",
            )
            res = mail.verify_mail_sent("frank@example.com", "Project Status", limit=25)
            self.assertTrue(res["verified"])
            self.assertEqual(res["delivery_status"], MailDeliveryStatus.SENT_VERIFIED.value)
            self.assertEqual(res["details"]["message_id"], "id-99")

    def test_bounded_sent_verification_ambiguous_matches(self) -> None:
        """Verify multiple matches in Sent mailbox produces DELIVERY_UNCONFIRMED (ambiguous)."""
        mail = MailAutomation()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="AMBIGUOUS\n",
                stderr="",
            )
            res = mail.verify_mail_sent("frank@example.com", "Project Status", limit=25)
            self.assertFalse(res["verified"])
            self.assertEqual(res["delivery_status"], MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)
            self.assertIn("ambiguous", res["evidence"].lower())

    def test_bounded_sent_verification_not_found(self) -> None:
        """Verify zero matches in Sent mailbox produces DELIVERY_UNCONFIRMED."""
        mail = MailAutomation()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="NOT_FOUND\n",
                stderr="",
            )
            res = mail.verify_mail_sent("frank@example.com", "Nonexistent Subject", limit=25)
            self.assertFalse(res["verified"])
            self.assertEqual(res["delivery_status"], MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)

    def test_bounded_sent_verification_applescript_timeout_or_error(self) -> None:
        """Verify AppleScript error or timeout produces DELIVERY_UNCONFIRMED, never false success."""
        mail = MailAutomation()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["osascript"], timeout=8)
            res = mail.verify_mail_sent("frank@example.com", "Subject")
            self.assertFalse(res["verified"])
            self.assertEqual(res["delivery_status"], MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)
            self.assertIn("timed out", res["evidence"].lower())

    # =========================================================================
    # 5. BACKEND SEND RESTRICTIONS TESTS (MCP & CAPABILITIES)
    # =========================================================================

    def test_mcp_client_blocks_apple_mail_send_tools(self) -> None:
        """Verify MCPClient strictly blocks all sending tools on apple-mail server."""
        cfg = get_apple_mail_server_config()
        proc = MCPProcess(cfg)
        client = MCPClient(proc)

        prohibited_tools = ["send-email", "send-serial-email", "reply-to-message", "forward-message"]
        for tool_name in prohibited_tools:
            with pytest.raises(MCPSecurityError) as cm:
                asyncio.run(client.call_tool(tool_name, {"to": "test@example.com"}))
            self.assertIn("not allowed", str(cm.value).lower())

    def test_mcp_server_manager_blocks_apple_mail_send_tools(self) -> None:
        """Verify MCPServerManager blocks sending tools on apple-mail."""
        manager = MCPServerManager()
        cfg = get_apple_mail_server_config()
        manager.register_server(cfg)

        prohibited_tools = ["send-email", "send-serial-email", "reply-to-message", "forward-message"]
        for tool_name in prohibited_tools:
            with pytest.raises(MCPSecurityError) as cm:
                manager.run_sync(manager.call_tool_async("apple-mail", tool_name, {"to": "test@example.com"}))
            self.assertIn("not allowed", str(cm.value).lower())
        manager.stop_all()


if __name__ == "__main__":
    unittest.main()
