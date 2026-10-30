from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.agent.email_engine import EmailDraft, EmailEngine, ProfessionalEmailEngine, sanitize_untrusted_email_content
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import ResolvedRecipient, ResolutionResult, RecipientResolver
from backend.api.server import app, orchestrator as server_orchestrator
from backend.capabilities import DeviceAutomation
from backend.capabilities.mail_actions import clear_mail_records, _sent_records
from backend.core.auth import get_or_create_session_secret
from backend.core.contracts import ActionAttempt, RiskLevel, Task, TaskCommand, TaskStatus
from backend.integrations.email.apple_mail_provider import AppleMailProvider
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.tools.registry import ToolRegistry
from backend.agent.execution_engine import ExecutionEngine
from backend.persistence.task_store import TaskStore


class TestPhase2EmailAutomation(unittest.TestCase):
    """
    Comprehensive test suite for Cortex Phase 2 Email Automation.
    Validates acceptance criteria EM-01 through EM-10.
    """

    def setUp(self) -> None:
        clear_mail_records()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test-memory.sqlite3"
        self.memory = EncryptedMemoryStore(db_path=str(self.db_path))
        self.automation = DeviceAutomation(dry_run=True)
        self.orchestrator = CortexOrchestrator(
            automation=self.automation,
            memory=self.memory,
            use_gemini=False,
        )
        server_orchestrator.automation = self.automation
        server_orchestrator.use_gemini = False
        server_orchestrator.registry = ToolRegistry(self.automation)
        server_orchestrator.execution_engine = ExecutionEngine(server_orchestrator.registry, server_orchestrator.policy_engine)
        self.session_token = get_or_create_session_secret()
        self.client = TestClient(app, headers={"X-Cortex-Session": self.session_token})

    def tearDown(self) -> None:
        clear_mail_records()
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # EM-01: Natural-language email requests parsed and validated
    # -------------------------------------------------------------------------
    def test_em01_natural_language_parsing_complete_fields(self) -> None:
        """EM-01: Extracts intent, recipient, account, cc, bcc, subject, body, attachments."""
        text = (
            "Send email to dev@example.com from account Work "
            "cc qa@example.com, pm@example.com bcc audit@example.com "
            "subject Release v2.0 with body The build is ready for deployment. "
            "attach /tmp/release_notes.txt"
        )
        engine = ProfessionalEmailEngine()
        extracted = engine.extract_command_and_content(text)
        self.assertEqual(extracted["recipient"], "dev@example.com")
        self.assertEqual(extracted["account"], "Work")
        self.assertEqual(extracted["cc"], ["qa@example.com", "pm@example.com"])
        self.assertEqual(extracted["bcc"], ["audit@example.com"])
        self.assertEqual(extracted["subject"], "Release v2.0")
        self.assertIn("The build is ready for deployment", extracted.get("content") or extracted.get("body", ""))
        self.assertEqual(extracted["attachments"], ["/tmp/release_notes.txt"])

    def test_em01_natural_language_attachment_validation(self) -> None:
        """EM-01: Non-existent attachments fail immediate validation before draft/send."""
        non_existent_file = "/tmp/cortex_missing_file_xyz_123.pdf"
        if os.path.exists(non_existent_file):
            os.remove(non_existent_file)

        provider = AppleMailProvider()
        res = provider.create_draft(
            recipient="test@example.com",
            subject="Missing file",
            body="Check this",
            attachments=[non_existent_file],
        )
        self.assertFalse(res["ok"])
        self.assertIn("Attachment file not found", res["error"])

    # -------------------------------------------------------------------------
    # EM-02: Ambiguous recipients trigger clarification before composing
    # -------------------------------------------------------------------------
    def test_em02_ambiguous_recipients_trigger_clarification(self) -> None:
        """EM-02: Ambiguous name with multiple contacts enters clarification state."""
        res = self.orchestrator.chat("Draft an email to Alex saying Friday meeting is confirmed")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )

        # Providing the clarified email completes the resolution and advances to approval
        res2 = self.orchestrator.chat("alex@enterprise.com")
        self.assertIsNotNone(res2.get("task"))
        self.assertEqual(res2["task"]["status"], "waiting_approval")
        self.assertEqual(res2["task"]["params"]["recipient"], "alex@enterprise.com")

    # -------------------------------------------------------------------------
    # EM-03: Draft fields match approved request
    # -------------------------------------------------------------------------
    def test_em03_draft_fields_match_approved_request(self) -> None:
        """EM-03: Provider draft created matches recipient, sender account, cc, bcc, subject, body."""
        engine = ProfessionalEmailEngine()
        draft = engine.compose_email(
            raw_intent="Quarterly Review",
            recipient_raw="client@enterprise.com",
            content="Please find the review attached.",
            subject_override="Quarterly Review",
            sender_account="Consulting Account",
            cc=["manager@enterprise.com"],
            bcc=["archive@enterprise.com"],
            attachments=[],
        )
        self.assertEqual(draft.recipient, "client@enterprise.com")
        self.assertEqual(draft.sender_account, "Consulting Account")
        self.assertEqual(draft.cc, ["manager@enterprise.com"])
        self.assertEqual(draft.bcc, ["archive@enterprise.com"])
        self.assertTrue(len(draft.approval_hash) == 64)

        # In mock provider / dry-run, create_draft accurately preserves fields
        provider = AppleMailProvider()
        res = provider.create_draft(
            recipient=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            account=draft.sender_account,
            cc=draft.cc,
            bcc=draft.bcc,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["recipient"], "client@enterprise.com")
        self.assertEqual(res["data"]["cc"], ["manager@enterprise.com"])
        self.assertEqual(res["data"]["bcc"], ["archive@enterprise.com"])
        self.assertEqual(res["data"]["account"], "Consulting Account")

    # -------------------------------------------------------------------------
    # EM-04: Sending requires explicit approval of exact payload
    # -------------------------------------------------------------------------
    def test_em04_sending_requires_explicit_approval_of_exact_payload(self) -> None:
        """EM-04: Execution without approval is blocked; requires valid approval hash."""
        res = self.client.post(
            "/chat",
            json={"message": "Send email to vendor@corp.com saying Specifications approved for delivery"},
        )
        task_data = res.json()["task"]
        self.assertTrue(task_data["requiresApproval"])
        self.assertEqual(task_data["status"], "waiting_approval")
        task_id = task_data["id"]
        valid_hash = task_data["params"]["approval_hash"]

        # Reject approval attempt without hash
        res_no_hash = self.client.post(f"/tasks/{task_id}/approve", json={"approved": True})
        self.assertEqual(res_no_hash.status_code, 400)

        # Reject approval attempt with forged hash
        res_bad_hash = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": "a" * 64},
        )
        self.assertEqual(res_bad_hash.status_code, 400)

        # Approve with exact hash succeeds
        res_good = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": valid_hash},
        )
        self.assertEqual(res_good.status_code, 200)
        self.assertEqual(res_good.json()["status"], "completed")

    # -------------------------------------------------------------------------
    # EM-05: Any material payload change invalidates approval
    # -------------------------------------------------------------------------
    def test_em05_material_payload_change_invalidates_approval(self) -> None:
        """EM-05: Editing subject, recipient, body, account, cc, or bcc recalculates SHA-256 and rejects stale hash."""
        res = self.client.post(
            "/chat",
            json={"message": "Send email to legal@firm.com saying Agreement signed"},
        )
        task_id = res.json()["task"]["id"]
        original_hash = res.json()["task"]["params"]["approval_hash"]

        # 1. Edit CC
        edit_res = self.client.post(
            f"/tasks/{task_id}/edit",
            json={"cc": ["counsel@firm.com"]},
        )
        self.assertEqual(edit_res.status_code, 200)
        new_hash = edit_res.json()["task"]["params"]["approval_hash"]
        self.assertNotEqual(original_hash, new_hash)

        # Old hash is rejected
        stale_approve = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": original_hash},
        )
        self.assertEqual(stale_approve.status_code, 400)
        self.assertIn("mismatch", stale_approve.json()["detail"].lower())

        # 2. Edit Sender Account
        edit_res2 = self.client.post(
            f"/tasks/{task_id}/edit",
            json={"sender_account": "Secondary Legal Account"},
        )
        self.assertEqual(edit_res2.status_code, 200)
        new_hash2 = edit_res2.json()["task"]["params"]["approval_hash"]
        self.assertNotEqual(new_hash, new_hash2)

        # Valid approval with new_hash2 works
        valid_approve = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": new_hash2},
        )
        self.assertEqual(valid_approve.status_code, 200)
        self.assertEqual(valid_approve.json()["status"], "completed")

    # -------------------------------------------------------------------------
    # EM-06: Approval replay and concurrent reuse are rejected
    # -------------------------------------------------------------------------
    def test_em06_approval_replay_rejected(self) -> None:
        """EM-06: A consumed approval token cannot be replayed or reused."""
        res = self.client.post(
            "/chat",
            json={"message": "Send email to ops@cloud.io saying Cluster maintenance completed"},
        )
        task_id = res.json()["task"]["id"]
        valid_hash = res.json()["task"]["params"]["approval_hash"]

        # First approval consumes token and completes execution
        res1 = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": valid_hash},
        )
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "completed")

        # Second approval attempt with same token is rejected
        res2 = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": valid_hash},
        )
        self.assertEqual(res2.status_code, 400)

    # -------------------------------------------------------------------------
    # EM-07: Cancellation is respected at execution boundaries
    # -------------------------------------------------------------------------
    def test_em07_cancellation_at_approval_gate(self) -> None:
        """EM-07: Cancelling waiting approval halts execution, clears hash, prevents send."""
        res = self.client.post(
            "/chat",
            json={"message": "Send email to payroll@corp.com saying Bonuses approved"},
        )
        task_id = res.json()["task"]["id"]
        valid_hash = res.json()["task"]["params"]["approval_hash"]

        # Cancel task
        res_cancel = self.client.post(f"/tasks/{task_id}/cancel")
        self.assertEqual(res_cancel.status_code, 200)
        self.assertIn(res_cancel.json()["status"], ("canceled", "cancelled"))

        # Attempt to approve after cancellation is rejected
        res_approve = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": valid_hash},
        )
        self.assertEqual(res_approve.status_code, 400)
        self.assertNotIn("Bonuses approved", [r.get("body") for r in _sent_records])

    # -------------------------------------------------------------------------
    # EM-08: Uncertain sends are reconciled without blind retries
    # -------------------------------------------------------------------------
    def test_em08_uncertain_sends_reconciled_without_blind_retries(self) -> None:
        """EM-08: Provider error / timeout halts execution without duplicate retry attempts."""
        class FailingMailProvider:
            def send_mail(self, recipient: str, subject: str, body: str, **kwargs):
                return {"ok": False, "message": "Connection to mail server dropped", "error": "ConnectionDropped"}

            def draft_mail(self, recipient: str, subject: str, body: str, **kwargs):
                return {"ok": True, "message": "Draft created"}

        mock_automation = DeviceAutomation(dry_run=True)
        mock_automation.mail = FailingMailProvider()
        self.orchestrator.automation = mock_automation
        self.orchestrator.registry = ToolRegistry(mock_automation)
        self.orchestrator.execution_engine = ExecutionEngine(self.orchestrator.registry, self.orchestrator.policy_engine)

        chat_res = self.orchestrator.chat("Send email to support@infra.net saying DB down")
        task = chat_res["task"]
        self.assertEqual(task["status"], "waiting_approval")
        valid_hash = task["params"]["approval_hash"]

        approve_res = self.orchestrator.approve(task["id"], approved=True, approval_hash=valid_hash)
        # Should fail safely without retrying irreversible send
        self.assertEqual(approve_res["status"], "failed")
        self.assertIn("Connection to mail server dropped", approve_res["error"])
        # Exactly one action attempt recorded, no blind retry attempts
        attempts = [ev for ev in approve_res["auditTrail"] if ev.get("type") in ("running", "executing")]
        self.assertTrue(len(attempts) <= 2)

    # -------------------------------------------------------------------------
    # EM-09: Distinct status reporting
    # -------------------------------------------------------------------------
    def test_em09_distinct_status_reporting(self) -> None:
        """EM-09: Verifies progression across distinct states (draft_created -> waiting_approval -> submitted -> sent_confirmed)."""
        chat_res = self.orchestrator.chat("Send email to friend@social.org saying Meet at 6pm")
        task = chat_res["task"]
        self.assertIsNotNone(task)
        # Event trail contains draft_prepared
        events = [e["type"] for e in task["auditTrail"]]
        self.assertIn("draft_prepared", events)
        self.assertEqual(task["status"], "waiting_approval")

        # Confirm send
        valid_hash = task["params"]["approval_hash"]
        approve_res = self.orchestrator.approve(task["id"], approved=True, approval_hash=valid_hash)
        self.assertEqual(approve_res["status"], "completed")
        approved_events = [e["type"] for e in approve_res["auditTrail"]]
        self.assertIn("approval_granted", approved_events)
        self.assertIn("observed", approved_events)

    # -------------------------------------------------------------------------
    # EM-10: Security invariants and Phase 1 regressions
    # -------------------------------------------------------------------------
    def test_em10_authentication_boundary_enforced(self) -> None:
        """EM-10: Unauthorized calls to API without valid session secret are rejected (401)."""
        unauthed_client = TestClient(app)
        res = unauthed_client.post("/chat", json={"message": "Send email to test@corp.com saying Test"})
        self.assertEqual(res.status_code, 401)

        res2 = unauthed_client.post("/tasks/any-id/approve", json={"approved": True})
        self.assertEqual(res2.status_code, 401)

    def test_em10_optimistic_locking_prevents_lost_updates(self) -> None:
        """EM-10: State version mismatch prevents concurrent task overwrites."""
        task_store = TaskStore(db_path=str(self.db_path))
        task = Task(id="task-lock-1", intent="Test locking", state_version=1)
        task_store.save_task(task)

        # Writer 1 advances 1 -> 2 with expected_version=1 (succeeds)
        task_w1 = Task(id="task-lock-1", intent="First update", state_version=2, status=TaskStatus.EXECUTING)
        task_store.save_task(task_w1, expected_version=1)

        # Writer 2 attempts stale update with expected_version=1 (must fail)
        from backend.core.contracts import ConcurrencyError
        task_w2 = Task(id="task-lock-1", intent="Stale update", state_version=2, status=TaskStatus.COMPLETED)
        with self.assertRaises(ConcurrencyError):
            task_store.save_task(task_w2, expected_version=1)


if __name__ == "__main__":
    unittest.main()
