from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.core.contracts import (
    Task,
    TaskStatus,
    TaskCommand,
    RiskLevel,
    LanguageCode,
    ActionAttempt,
    ActionAttemptStatus,
    canonical_status,
    TERMINAL_STATUSES,
    IllegalStateTransitionError,
    ConcurrencyError,
)
from backend.persistence.task_store import TaskStore, MigrationError
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.core.auth import get_or_create_session_secret, verify_session_token
from backend.agent.orchestrator import CortexOrchestrator
from backend.api.server import app


class TestPhase1ExecutionFoundation(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = str(Path(self.temp_dir) / "test-cortex.sqlite3")
        self.task_store = TaskStore(self.db_path)
        self.client = TestClient(app)
        self.session_token = get_or_create_session_secret()

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # =========================================================================
    # Workstream A — Canonical Task State Machine (ACC-002, ACC-003, ACC-005)
    # =========================================================================

    def test_canonical_state_allowed_transitions(self) -> None:
        task = Task(intent="Send email", command=TaskCommand.SEND_MAIL)
        self.assertEqual(task.status, TaskStatus.PROPOSED)
        self.assertEqual(task.state_version, 1)

        # Proposed / Planned -> Awaiting Approval
        task.transition_to(TaskStatus.AWAITING_APPROVAL, reason="Prepared email draft")
        self.assertEqual(task.status, TaskStatus.AWAITING_APPROVAL)
        self.assertEqual(task.state_version, 2)

        # Awaiting Approval -> Executing
        task.transition_to(TaskStatus.EXECUTING, reason="User approved")
        self.assertEqual(task.status, TaskStatus.EXECUTING)
        self.assertEqual(task.state_version, 3)

        # Executing -> Verifying
        task.transition_to(TaskStatus.VERIFYING, reason="Waiting for mailbox evidence")
        self.assertEqual(task.status, TaskStatus.VERIFYING)
        self.assertEqual(task.state_version, 4)

        # Verifying -> Completed
        task.transition_to(TaskStatus.COMPLETED, reason="Mail delivery confirmed")
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.state_version, 5)

    def test_disallowed_transitions_fail_cleanly(self) -> None:
        task = Task(intent="Check news", command=TaskCommand.WEB_SEARCH)
        task.status = TaskStatus.QUEUED

        # Queued directly to Executing is disallowed (must go through understanding/planned)
        with self.assertRaises(IllegalStateTransitionError):
            task.transition_to(TaskStatus.EXECUTING)

        # Terminal state cannot transition to anything
        task.status = TaskStatus.COMPLETED
        with self.assertRaises(IllegalStateTransitionError):
            task.transition_to(TaskStatus.EXECUTING)

        with self.assertRaises(IllegalStateTransitionError):
            task.transition_to(TaskStatus.PLANNED)

    def test_optimistic_concurrency_guard(self) -> None:
        task = Task(intent="Open Calendar", command=TaskCommand.OPEN_APP)
        task.status = TaskStatus.PLANNED
        self.assertEqual(task.state_version, 1)

        # Passing correct version succeeds
        task.transition_to(TaskStatus.EXECUTING, expected_version=1)
        self.assertEqual(task.state_version, 2)

        # Passing stale version fails
        with self.assertRaises(ConcurrencyError):
            task.transition_to(TaskStatus.COMPLETED, expected_version=1)

    def test_cancellation_semantics(self) -> None:
        task = Task(intent="Send note", command=TaskCommand.SEND_MESSAGE)
        task.status = TaskStatus.AWAITING_APPROVAL
        self.assertFalse(task.cancellation_requested)

        task.request_cancellation(reason="User said cancel")
        self.assertTrue(task.cancellation_requested)
        self.assertEqual(task.status, TaskStatus.CANCELLED)

        # Once cancelled, terminal lock prevents further actions
        with self.assertRaises(IllegalStateTransitionError):
            task.transition_to(TaskStatus.EXECUTING)

    # =========================================================================
    # Workstream B — Relational SQLite Persistence & Migrations (ACC-004)
    # =========================================================================

    def test_fresh_database_initialization_and_schema_migrations(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("SELECT version FROM schema_migrations;")
            versions = [r[0] for r in cur.fetchall()]
            self.assertIn(1, versions)

            # Check that all tables exist
            tables = [
                "tasks",
                "task_steps",
                "approvals",
                "action_attempts",
                "audit_events",
                "artifacts",
            ]
            for t in tables:
                cur = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?;", (t,)
                )
                self.assertIsNotNone(cur.fetchone(), f"Table {t} missing from schema")

    def test_migration_preserves_legacy_memories_table(self) -> None:
        # Create legacy database with memories
        legacy_db = Path(self.temp_dir) / "legacy.sqlite3"
        legacy_store = EncryptedMemoryStore(str(legacy_db))
        legacy_store.put("pref_1", "preference", {"theme": "dark", "lang": "kn"})

        # Initialize TaskStore on the existing legacy database
        ts = TaskStore(str(legacy_db))

        # Verify legacy memories still decrypt cleanly
        decrypted = legacy_store.get("pref_1")
        self.assertIsNotNone(decrypted)
        self.assertEqual(decrypted.get("theme"), "dark")
        self.assertEqual(decrypted.get("lang"), "kn")

        # Verify relational tables are also operational
        with sqlite3.connect(str(legacy_db)) as conn:
            cur = conn.execute("SELECT version FROM schema_migrations;")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_database_backup(self) -> None:
        backup_file = Path(self.temp_dir) / "backup_test.sqlite3"
        dest = self.task_store.backup(backup_file)
        self.assertTrue(dest.exists())
        self.assertGreater(dest.stat().st_size, 0)

    # =========================================================================
    # Workstream C — Startup Rehydration and Crash Recovery (ACC-001, ACC-013)
    # =========================================================================

    def test_restart_with_task_awaiting_clarification(self) -> None:
        task = Task(
            id="clarify-task-1",
            intent="Send email to Bob",
            command=TaskCommand.SEND_MAIL,
            status=TaskStatus.AWAITING_CLARIFICATION,
            params={"clarification": "Multiple candidates found for Bob"},
        )
        self.task_store.save_task(task)

        # Initialize fresh orchestrator pointing to the same database
        orch = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        self.assertIn("clarify-task-1", orch.tasks)
        rehydrated = orch.tasks["clarify-task-1"]
        self.assertEqual(rehydrated.status, TaskStatus.AWAITING_CLARIFICATION)
        self.assertIsNotNone(orch.pending_action)
        self.assertEqual(orch.pending_action.get("type"), "clarification")

    def test_restart_with_task_awaiting_approval_and_expiry(self) -> None:
        # 1. Valid approval within 15 minutes
        fresh_task = Task(
            id="fresh-task-1",
            intent="Send email to Alex",
            command=TaskCommand.SEND_MAIL,
            status=TaskStatus.AWAITING_APPROVAL,
            params={"approval_hash": "hash_123", "recipient": "alex@test.com"},
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.task_store.save_task(fresh_task)

        orch = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        self.assertIn("fresh-task-1", orch.tasks)
        self.assertEqual(orch.tasks["fresh-task-1"].status, TaskStatus.AWAITING_APPROVAL)

        # 2. Expired approval (> 15 minutes ago)
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        stale_task = Task(
            id="stale-task-1",
            intent="Send email to Alex",
            command=TaskCommand.SEND_MAIL,
            status=TaskStatus.AWAITING_APPROVAL,
            params={"approval_hash": "hash_old", "recipient": "alex@test.com"},
            created_at=expired_time,
        )
        self.task_store.save_task(stale_task)

        orch2 = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        self.assertIn("stale-task-1", orch2.tasks)
        # Should transition to NEEDS_ATTENTION rather than silently accepting stale approval
        self.assertEqual(orch2.tasks["stale-task-1"].status, TaskStatus.NEEDS_ATTENTION)

    def test_crash_recovery_uncertain_send_not_blindly_retried(self) -> None:
        # Simulate an interrupted task that was EXECUTING when backend terminated
        interrupted_task = Task(
            id="interrupted-task-1",
            intent="Send quarterly update to team",
            command=TaskCommand.SEND_MAIL,
            status=TaskStatus.EXECUTING,
            params={"recipient": "team@cortex.internal", "subject": "Quarterly Update"},
        )
        self.task_store.save_task(interrupted_task)

        # Record pre-execution action attempt
        attempt = ActionAttempt(
            task_id=interrupted_task.id,
            action_type="send_email",
            payload_hash="payload_abc",
            status=ActionAttemptStatus.INITIATED,
        )
        self.task_store.record_action_attempt(attempt)

        # On reboot, orchestrator checks outcome evidence
        orch = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        rehydrated = orch.tasks.get("interrupted-task-1")
        self.assertIsNotNone(rehydrated)
        # If Sent mailbox cannot confirm delivery, task MUST enter NEEDS_ATTENTION, NEVER blind re-send
        self.assertEqual(rehydrated.status, TaskStatus.NEEDS_ATTENTION)

    # =========================================================================
    # Workstream D — Electron-FastAPI Security Boundary (ACC-023)
    # =========================================================================

    def test_unauthorized_api_requests_rejected_with_401(self) -> None:
        # Enable strict authentication mode
        os.environ["CORTEX_STRICT_AUTH"] = "1"
        try:
            # 1. Missing header -> 401
            resp = self.client.post("/chat", json={"message": "Hello"})
            self.assertEqual(resp.status_code, 401)
            self.assertIn("Unauthorized", resp.json()["detail"])

            # 2. Invalid header -> 401
            resp2 = self.client.post(
                "/chat",
                json={"message": "Hello"},
                headers={"X-Cortex-Session": "invalid_wrong_token_1234567890"},
            )
            self.assertEqual(resp2.status_code, 401)

            # 3. Valid header -> 200
            resp3 = self.client.post(
                "/chat",
                json={"message": "Hello"},
                headers={"X-Cortex-Session": self.session_token},
            )
            self.assertEqual(resp3.status_code, 200)

            # 4. Public endpoint (/health) is accessible without token
            health_resp = self.client.get("/health")
            self.assertEqual(health_resp.status_code, 200)
        finally:
            os.environ.pop("CORTEX_STRICT_AUTH", None)

    # =========================================================================
    # Workstream E — Approval Invariants & Expiry (ACC-006, ACC-007, ACC-008, ACC-009)
    # =========================================================================

    def test_approval_consumption_and_replay_protection(self) -> None:
        task_id = "approval-test-1"
        self.task_store.save_task(Task(id=task_id, intent="Test approval", command=TaskCommand.SEND_MAIL))
        payload_hash = "hash_valid_xyz"
        self.task_store.record_approval(task_id, payload_hash, expires_in_seconds=900)

        # First consumption succeeds
        ok, msg = self.task_store.consume_approval(task_id, payload_hash)
        self.assertTrue(ok)
        self.assertEqual(msg, "Approval consumed successfully.")

        # Second consumption (replay) fails
        ok2, msg2 = self.task_store.consume_approval(task_id, payload_hash)
        self.assertFalse(ok2)
        self.assertIn("replay", msg2.lower())

    def test_approval_15_minute_expiration(self) -> None:
        task_id = "approval-exp-1"
        self.task_store.save_task(Task(id=task_id, intent="Test approval expiry", command=TaskCommand.SEND_MAIL))
        payload_hash = "hash_expired_xyz"
        # Register approval with negative expiry (already expired)
        self.task_store.record_approval(task_id, payload_hash, expires_in_seconds=-10)

        ok, msg = self.task_store.consume_approval(task_id, payload_hash)
        self.assertFalse(ok)
        self.assertIn("expired", msg.lower())

    # =========================================================================
    # Workstream G — Structured Audit Events (No Secret Leaks)
    # =========================================================================

    def test_structured_audit_events_and_redaction(self) -> None:
        event_id = self.task_store.record_audit_event(
            event_type="auth_and_approval",
            task_id="audit-task-1",
            metadata={
                "action": "send_email",
                "recipient": "partner@cortex.internal",
                "secret": "super_secret_token_12345",
                "api_key": "gemini_key_abc",
                "full_body": "Confidential email body text",
            },
        )
        self.assertIsNotNone(event_id)

        events = self.task_store.get_audit_events(task_id="audit-task-1")
        self.assertEqual(len(events), 1)
        meta = events[0]["metadata"]
        # Verify sensitive fields are strictly redacted
        self.assertEqual(meta["secret"], "[REDACTED]")
        self.assertEqual(meta["api_key"], "[REDACTED]")
        self.assertEqual(meta["full_body"], "[REDACTED]")
        self.assertEqual(meta["recipient"], "partner@cortex.internal")


if __name__ == "__main__":
    unittest.main()
