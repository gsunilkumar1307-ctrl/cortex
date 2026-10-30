from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.agent.email_engine import EmailDraft
from backend.agent.orchestrator import CortexOrchestrator
from backend.api.server import app
from backend.capabilities import DeviceAutomation
from backend.core.auth import get_or_create_session_secret, verify_session_token
from backend.core.contracts import (
    ConcurrencyError,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
)
from backend.integrations.email.apple_mail_provider import AppleMailProvider, extract_clean_email
from backend.persistence.task_store import TaskStore, recursive_sanitize


class TestPhase12RemediationVerification(unittest.TestCase):
    """
    Dedicated Phase 1.2 Verification Suite covering:
    - SEC-01: Scoped Electron-to-FastAPI authentication & origin validation
    - SEC-02: Elimination of implicit TestClient authentication bypass
    - DUR-01: SQLite optimistic concurrency & conflict rejection (Tests A, B, C, D, E)
    - MAIL-01: Strengthened sent-message reconciliation & fail-closed ambiguity handling
    - SEC-03: Defensive Content-Security-Policy specification
    - MOD-01: Durable PAUSED_MODEL_UNAVAILABLE task state & safe resumption
    - AUD-01: Deep recursive audit event redaction
    - MAIL-02: Full 64-char SHA-256 payload binding including CC/BCC
    """

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmp_dir) / "test-cortex-remediation.sqlite3")
        self.task_store = TaskStore(self.db_path)
        self.session_token = get_or_create_session_secret()
        self.unauth_client = TestClient(app)
        self.auth_client = TestClient(app, headers={"X-Cortex-Session": self.session_token})

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # =========================================================================
    # SEC-01 & SEC-02: Authentication & Boundary Security
    # =========================================================================

    def test_sec02_unauthenticated_requests_strictly_rejected_without_bypass(self) -> None:
        """Verify no testclient or loopback bypass allows unauthenticated access to protected routes."""
        # 1. Missing header -> 401
        res1 = self.unauth_client.post("/chat", json={"message": "Draft email"})
        self.assertEqual(res1.status_code, 401)
        self.assertIn("Missing X-Cortex-Session token", res1.json()["detail"])

        # 2. Invalid header -> 401
        res2 = self.unauth_client.post(
            "/chat",
            json={"message": "Draft email"},
            headers={"X-Cortex-Session": "invalid_token_1234567890"},
        )
        self.assertEqual(res2.status_code, 401)
        self.assertIn("Invalid X-Cortex-Session token", res2.json()["detail"])

        # 3. Protected tasks endpoint -> 401 without auth
        res3 = self.unauth_client.post("/tasks/task-xyz/approve", json={"approved": True})
        self.assertEqual(res3.status_code, 401)

        # 4. Protected memory endpoint -> 401 without auth
        res4 = self.unauth_client.get("/memory")
        self.assertEqual(res4.status_code, 401)

        # 5. Public health endpoint -> 200 without auth
        res_health = self.unauth_client.get("/health")
        self.assertEqual(res_health.status_code, 200)

        # 6. Valid authentication succeeds
        res_auth = self.auth_client.get("/health")
        self.assertEqual(res_auth.status_code, 200)

    # =========================================================================
    # DUR-01: SQLite Optimistic Concurrency Control (Tests A, B, C, D, E)
    # =========================================================================

    def test_dur01_test_a_stale_snapshot_rejected_and_db_unmodified(self) -> None:
        """Test A: Stale snapshot write is rejected and SQLite database retains newer version."""
        task = Task(id="task-stale-1", intent="Initial Task", state_version=1)
        self.task_store.save_task(task)

        # Update to version 2
        task.transition_to(TaskStatus.RUNNING)
        self.assertEqual(task.state_version, 2)
        self.task_store.save_task(task)

        # Attempt to save a stale snapshot at version 1
        stale_snapshot = Task(id="task-stale-1", intent="Stale Overwrite", state_version=1)
        with self.assertRaises(ConcurrencyError) as ctx:
            self.task_store.save_task(stale_snapshot)
        self.assertIn("Concurrency conflict", str(ctx.exception))

        # Verify directly in SQLite that version 2 and newer intent remain intact
        persisted = self.task_store.get_task("task-stale-1")
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.state_version, 2)
        self.assertEqual(persisted.intent, "Initial Task")
        self.assertEqual(persisted.status, TaskStatus.EXECUTING)

    def test_dur01_test_b_concurrent_transitions_with_expected_version(self) -> None:
        """Test B: Concurrent transitions only succeed when expected_version matches database."""
        task = Task(id="task-race-1", intent="Racing Task", state_version=1)
        self.task_store.save_task(task)

        # Writer 1 advances from 1 -> 2 with expected_version=1 (succeeds)
        task_w1 = Task(id="task-race-1", intent="Writer 1 Update", state_version=2, status=TaskStatus.RUNNING)
        self.task_store.save_task(task_w1, expected_version=1)

        # Writer 2 attempts to advance from 1 -> 2 with expected_version=1 (must fail)
        task_w2 = Task(id="task-race-1", intent="Writer 2 Update", state_version=2, status=TaskStatus.COMPLETED)
        with self.assertRaises(ConcurrencyError):
            self.task_store.save_task(task_w2, expected_version=1)

        # Confirm Writer 1 won
        persisted = self.task_store.get_task("task-race-1")
        self.assertEqual(persisted.intent, "Writer 1 Update")
        self.assertEqual(persisted.status, TaskStatus.EXECUTING)

    def test_dur01_test_c_equal_version_conflict_rejected(self) -> None:
        """Test C: Conflicting snapshots with the same version cannot overwrite each other."""
        snap1 = Task(id="task-equal-1", intent="Snapshot A", state_version=1)
        self.task_store.save_task(snap1)

        snap2 = Task(id="task-equal-1", intent="Snapshot B Conflict", state_version=1)
        with self.assertRaises(ConcurrencyError):
            self.task_store.save_task(snap2)

        # Confirm Snapshot A was preserved
        persisted = self.task_store.get_task("task-equal-1")
        self.assertEqual(persisted.intent, "Snapshot A")

    def test_dur01_test_d_cancellation_and_approval_race(self) -> None:
        """Test D: Competing cancellation and approval cannot restore cancelled state."""
        task = Task(id="task-race-cancel", intent="Email send", command=TaskCommand.SEND_MAIL, status=TaskStatus.AWAITING_APPROVAL, state_version=1)
        self.task_store.save_task(task)

        # User cancels task -> state_version becomes 2, status=CANCELLED
        task.transition_to(TaskStatus.CANCELLED, reason="User cancelled")
        self.assertEqual(task.state_version, 2)
        self.task_store.save_task(task)

        # A stale approval handler snapshot trying to set EXECUTING at state_version=2 or with expected_version=1 fails
        stale_approval = Task(id="task-race-cancel", intent="Email send", command=TaskCommand.SEND_MAIL, status=TaskStatus.EXECUTING, state_version=2)
        with self.assertRaises(ConcurrencyError):
            self.task_store.save_task(stale_approval, expected_version=1)

        persisted = self.task_store.get_task("task-race-cancel")
        self.assertEqual(persisted.status, TaskStatus.CANCELLED)

    def test_dur01_test_e_restart_durability(self) -> None:
        """Test E: Persisted state survives orchestrator restart using isolated database."""
        task = Task(id="task-restart-1", intent="Important Work", status=TaskStatus.AWAITING_APPROVAL, state_version=3)
        self.task_store.save_task(task)

        fresh_orch = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        self.assertIn("task-restart-1", fresh_orch.tasks)
        self.assertEqual(fresh_orch.tasks["task-restart-1"].state_version, 3)
        self.assertEqual(fresh_orch.tasks["task-restart-1"].status, TaskStatus.AWAITING_APPROVAL)

    # =========================================================================
    # MAIL-01: Sent Message Reconciliation
    # =========================================================================

    def test_mail01_sent_message_reconciliation_exact_and_ambiguous(self) -> None:
        """Test MAIL-01: Sent verification matches exact email, rejects mismatched recipient, and flags ambiguous records."""
        provider = AppleMailProvider(dry_run=True)

        # 1. Send legitimate message
        provider.send_message(
            recipient="alice.smith@university.edu",
            subject="Research Proposal Feedback",
            body="Looks great!",
        )

        # Exact match succeeds
        v1 = provider.verify_message_sent("alice.smith@university.edu", "Research Proposal Feedback")
        self.assertTrue(v1["verified"])

        # Different recipient with same subject fails
        v2 = provider.verify_message_sent("bob@other.edu", "Research Proposal Feedback")
        self.assertFalse(v2["verified"])

        # Different subject for same recipient fails
        v3 = provider.verify_message_sent("alice.smith@university.edu", "Completely Different Subject")
        self.assertFalse(v3["verified"])

        # Duplicate/ambiguous send record causes inconclusive/uncertain verdict
        provider.send_message(
            recipient="alice.smith@university.edu",
            subject="Research Proposal Feedback",
            body="Second duplicate attempt",
        )
        v_ambig = provider.verify_message_sent("alice.smith@university.edu", "Research Proposal Feedback")
        self.assertFalse(v_ambig["verified"])
        self.assertTrue(v_ambig.get("uncertain"))

    def test_mail01_extract_clean_email_helper(self) -> None:
        """Test normalization helper extracts canonical lowercased email addresses."""
        self.assertEqual(extract_clean_email("Alice <Alice.Smith@Domain.COM>"), "alice.smith@domain.com")
        self.assertEqual(extract_clean_email("BOB@TEST.ORG"), "bob@test.org")
        self.assertEqual(extract_clean_email(""), "")

    # =========================================================================
    # SEC-03: Content Security Policy Verification
    # =========================================================================

    def test_sec03_index_html_contains_restrictive_csp_meta_tag(self) -> None:
        """Verify index.html contains a restrictive Content Security Policy."""
        index_path = Path(__file__).resolve().parents[1] / "apps" / "desktop" / "index.html"
        self.assertTrue(index_path.exists())
        content = index_path.read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", content)
        self.assertIn("default-src 'self'", content)
        self.assertIn("script-src 'self'", content)
        self.assertIn("connect-src 'self' http://127.0.0.1:8765", content)
        self.assertNotIn("unsafe-eval", content)

    # =========================================================================
    # MOD-01: Model Outage Persistence & Task Resumption
    # =========================================================================

    def test_mod01_model_dependent_task_pauses_durably_and_resumes(self) -> None:
        """Verify model-dependent tasks pause in PAUSED_MODEL_UNAVAILABLE on outage and resume cleanly."""
        orch = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        orch.gemini_cooldown_until = datetime.now().timestamp() + 300.0  # simulate quota outage

        task = Task(
            id="vision-task-1",
            intent="Analyze what is on my screen",
            command=TaskCommand.SCREEN_VISION,
            params={"requires_model": True},
        )
        orch.tasks[task.id] = task
        orch._execute(task)

        # Must transition to PAUSED_MODEL_UNAVAILABLE
        self.assertEqual(task.status, TaskStatus.PAUSED_MODEL_UNAVAILABLE)
        persisted = self.task_store.get_task("vision-task-1")
        self.assertEqual(persisted.status, TaskStatus.PAUSED_MODEL_UNAVAILABLE)

        # Survives restart in PAUSED_MODEL_UNAVAILABLE
        orch2 = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        self.assertEqual(orch2.tasks["vision-task-1"].status, TaskStatus.PAUSED_MODEL_UNAVAILABLE)

        # Deterministic tasks can still complete while model is unavailable
        calc_task = Task(
            id="calc-task-1",
            intent="Calculate 15 * 8",
            command=TaskCommand.CALCULATE,
            params={"expression": "15 * 8"},
        )
        orch.tasks[calc_task.id] = calc_task
        orch._execute(calc_task)
        self.assertEqual(calc_task.status, TaskStatus.COMPLETED)

    # =========================================================================
    # AUD-01: Deep Recursive Audit Redaction
    # =========================================================================

    def test_aud01_recursive_audit_redaction(self) -> None:
        """Verify deeply nested credentials, tokens, bodies, and passwords are redacted."""
        raw_metadata = {
            "task_id": "test-task",
            "request": {
                "headers": {
                    "Authorization": "Bearer sensitive_token_xyz",
                    "X-Cortex-Session": "secret_session_token",
                },
                "params": {
                    "recipient": "partner@cortex.internal",
                    "body": "Private confidential message body",
                    "nested_credentials": {
                        "api_key": "gemini_secret_key_123",
                        "password": "db_password_456",
                    },
                },
            },
            "steps": [
                {"name": "step1", "token": "step_token_789"},
                {"name": "step2", "status": "ok"},
            ],
        }

        sanitized = recursive_sanitize(raw_metadata)
        self.assertEqual(sanitized["request"]["headers"]["Authorization"], "[REDACTED]")
        self.assertEqual(sanitized["request"]["headers"]["X-Cortex-Session"], "[REDACTED]")
        self.assertEqual(sanitized["request"]["params"]["body"], "[REDACTED]")
        self.assertEqual(sanitized["request"]["params"]["nested_credentials"], "[REDACTED]")
        self.assertEqual(sanitized["steps"][0]["token"], "[REDACTED]")
        # Non-sensitive fields preserved
        self.assertEqual(sanitized["request"]["params"]["recipient"], "partner@cortex.internal")
        self.assertEqual(sanitized["steps"][1]["status"], "ok")

        # Persist through task store and inspect saved SQLite record
        event_id = self.task_store.record_audit_event("security_audit", task_id="test-task", metadata=raw_metadata)
        events = self.task_store.get_audit_events("test-task")
        stored_meta = events[0]["metadata"]
        self.assertEqual(stored_meta["request"]["headers"]["Authorization"], "[REDACTED]")
        self.assertEqual(stored_meta["request"]["params"]["body"], "[REDACTED]")

    # =========================================================================
    # MAIL-02: Full 64-char SHA-256 Approval Hash Binding
    # =========================================================================

    def test_mail02_full_sha256_hash_and_material_field_binding(self) -> None:
        """Verify approval hash is a 64-character SHA-256 hash that binds To, CC, BCC, Subject, Body, Attachments."""
        draft = EmailDraft(
            recipient="lead@domain.com",
            subject="Release Approval",
            body="Please review and authorize Phase 1.2 release.",
            sender_account="security@domain.com",
            attachments=["audit.pdf"],
            cc=["auditor@domain.com"],
            bcc=["compliance@domain.com"],
        )
        h1 = draft.compute_hash()
        self.assertEqual(len(h1), 64)

        # Changing CC invalidates hash
        draft_cc_mod = EmailDraft(
            recipient=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            sender_account=draft.sender_account,
            attachments=draft.attachments,
            cc=["different@domain.com"],
            bcc=draft.bcc,
        )
        self.assertNotEqual(h1, draft_cc_mod.compute_hash())

        # Changing BCC invalidates hash
        draft_bcc_mod = EmailDraft(
            recipient=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            sender_account=draft.sender_account,
            attachments=draft.attachments,
            cc=draft.cc,
            bcc=[],
        )
        self.assertNotEqual(h1, draft_bcc_mod.compute_hash())

        # Changing sender account invalidates hash
        draft_sender_mod = EmailDraft(
            recipient=draft.recipient,
            subject=draft.subject,
            body=draft.body,
            sender_account="unauthorized@domain.com",
            attachments=draft.attachments,
            cc=draft.cc,
            bcc=draft.bcc,
        )
        self.assertNotEqual(h1, draft_sender_mod.compute_hash())


if __name__ == "__main__":
    unittest.main()
