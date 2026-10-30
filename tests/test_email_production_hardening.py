from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.agent.email_engine import EmailDraft, ProfessionalEmailEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import RecipientResolver, ResolvedRecipient
from backend.api.server import app
from backend.core.auth import get_or_create_session_secret
from backend.capabilities import DeviceAutomation
from backend.capabilities.mail_actions import (
    MailAutomation,
    _apple_string,
    _sent_records,
    _draft_records,
    clear_mail_records,
)
from backend.core.contracts import (
    LanguageCode,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
)
from backend.integrations.email.apple_mail_provider import AppleMailProvider
from backend.persistence.encrypted_store import EncryptedMemoryStore


class TestEmailProductionHardening(unittest.TestCase):
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
        self.client = TestClient(app, headers={"X-Cortex-Session": get_or_create_session_secret()})

    def tearDown(self) -> None:
        clear_mail_records()
        self.tmp_dir.cleanup()

    # ── Test 1: Ambiguous recipient requests clarification ────────────────────
    def test_01_ambiguous_recipient_requests_clarification(self) -> None:
        resp = self.orchestrator.chat("Draft an email to Alex saying the meeting is moved to Friday")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )
        msg_lower = resp["message"].lower()
        self.assertTrue(
            any(k in msg_lower for k in ("identify", "clarify", "email address", "alex")),
            f"Expected clarification prompt, got: {resp['message']}",
        )

    # ── Test 2: Unrelated Kannada, Hindi, and English questions preserve draft ─
    @patch("backend.agent.orchestrator.search_web", return_value=[{"title": "Cortex Info", "body": "Cortex is an AI companion.", "href": "https://cortex.internal"}])
    def test_02_unrelated_questions_in_kannada_hindi_english_preserve_pending_draft(self, mock_search: MagicMock) -> None:
        # Step 1: Start email with ambiguous recipient
        self.orchestrator.chat("Draft an email to Alex saying meeting rescheduled")
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )

        # Step 2: Kannada greeting
        resp_kn = self.orchestrator.chat("ನಮಸ್ಕಾರ, ನೀವು ಹೇಗಿದ್ದೀರಿ?")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )
        self.assertTrue(
            any(w in resp_kn["message"] for w in ("ನಮಸ್ಕಾರ", "ಚೆನ್ನಾಗಿದ್ದೇನೆ", "ಹೇಗೆ")),
            f"Expected Kannada response, got: {resp_kn['message']}",
        )

        # Step 3: Hindi question
        resp_hi = self.orchestrator.chat("Hindi me batao Cortex kya hai")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )

        # Step 4: English general question
        resp_en = self.orchestrator.chat("What is photosynthesis?")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )

    # ── Test 3: Valid recipient resumes the correct pending task ──────────────
    def test_03_valid_recipient_resumes_correct_pending_task(self) -> None:
        self.orchestrator.chat("Draft an email to Alex saying meeting rescheduled to 3 PM")
        resp = self.orchestrator.chat("alex.smith@example.com")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "confirm_send")
        draft = self.orchestrator.pending_action.get("draft")
        self.assertIsNotNone(draft)
        self.assertIn("alex.smith@example.com", draft.recipient)
        self.assertIn("3 PM", draft.body)

    # ── Test 4: Duplicate names require disambiguation ────────────────────────
    def test_04_duplicate_names_require_disambiguation(self) -> None:
        resolver = RecipientResolver()
        resolver.KNOWN_DIRECTORY = [
            {
                "name": "Dr. John Smith",
                "email": "john.cardio@hospital.org",
                "role": "doctor",
                "department": "Cardiology",
                "institution": "Hospital A",
                "keywords": ["john", "smith"],
            },
            {
                "name": "Dr. John Smith",
                "email": "john.neuro@hospital.org",
                "role": "doctor",
                "department": "Neurology",
                "institution": "Hospital B",
                "keywords": ["john", "smith"],
            },
        ]
        orch = CortexOrchestrator(
            memory=self.memory,
            use_gemini=False,
        )
        orch.recipient_resolver = resolver
        resp = orch.chat("Send email to Dr. John Smith saying rounds are delayed")
        self.assertIsNotNone(orch.pending_action)
        self.assertEqual(
            orch.pending_action.get("step"),
            "waiting_for_recipient_disambiguation",
        )
        self.assertIn("multiple", resp["message"].lower())

    # ── Test 5: Cancellation during recipient clarification ───────────────────
    def test_05_cancellation_during_recipient_clarification(self) -> None:
        self.orchestrator.chat("Draft an email to Alex saying meeting rescheduled")
        self.assertIsNotNone(self.orchestrator.pending_action)
        resp = self.orchestrator.chat("cancel")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertIn(resp["task"]["status"], ("canceled", "cancelled"))
        self.assertEqual(resp["message"], "Cancelled.")

    # ── Test 6: Cancellation after draft creation or while awaiting approval ──
    def test_06_cancellation_after_draft_creation_or_awaiting_approval(self) -> None:
        self.orchestrator.chat("Send email to sunil@internal.io saying task finished")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "confirm_send")
        task_id = self.orchestrator.pending_action["task_id"]

        resp = self.orchestrator.chat("cancel draft")
        self.assertIsNone(self.orchestrator.pending_action)
        task = self.orchestrator.tasks[task_id]
        self.assertIn(task.status, (TaskStatus.CANCELED, TaskStatus.CANCELLED))
        self.assertIsNone(task.params.get("approval_hash"))

    # ── Test 7: Cancellation never triggers web search or LLM fallback ────────
    @patch("backend.agent.orchestrator.search_web")
    def test_07_cancellation_never_triggers_web_search_or_llm_fallback(self, mock_search: MagicMock) -> None:
        self.orchestrator.pending_action = None
        resp = self.orchestrator.chat("cancel")
        mock_search.assert_not_called()
        self.assertEqual(resp["message"], "Cancelled.")

        # Test localized Kannada cancellation
        resp_kn = self.orchestrator.chat("ರದ್ದುಮಾಡು")
        mock_search.assert_not_called()
        self.assertEqual(resp_kn["message"], "ರದ್ದುಗೊಳಿಸಲಾಗಿದೆ.")

    # ── Test 8: Ordinary conversation works after cancellation ────────────────
    def test_08_ordinary_conversation_works_after_cancellation(self) -> None:
        self.orchestrator.chat("Send email to Alex saying please review")
        self.orchestrator.chat("cancel")
        self.assertIsNone(self.orchestrator.pending_action)

        resp = self.orchestrator.chat("Hello Cortex")
        self.assertNotIn("clarify", resp["message"].lower())
        self.assertNotIn("recipient", resp["message"].lower())

    # ── Test 9: Draft edits invalidate previous approval ──────────────────────
    def test_09_draft_edits_invalidate_previous_approval(self) -> None:
        self.orchestrator.chat("Send email to team@cortex.internal saying build succeeded")
        task_id = self.orchestrator.pending_action["task_id"]
        old_hash = self.orchestrator.tasks[task_id].params["approval_hash"]

        # Edit the draft
        self.orchestrator.chat("make it formal and add regards from engineering")
        new_hash = self.orchestrator.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(old_hash, new_hash)

        # Attempting to approve with old hash is rejected
        res = self.orchestrator.approve(task_id, approved=True, approval_hash=old_hash)
        self.assertEqual(res["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertIn("mismatch", res.get("error", "").lower())

    # ── Test 10: Recipient/account/content changes invalidate previous approval ─
    def test_10_recipient_account_content_changes_invalidate_previous_approval(self) -> None:
        self.orchestrator.chat("Send email to dev@cortex.internal saying ready to ship")
        task_id = self.orchestrator.pending_action["task_id"]
        initial_hash = self.orchestrator.tasks[task_id].params["approval_hash"]

        # Programmatic edit
        self.orchestrator.edit_pending_draft(
            task_id=task_id,
            recipient="security@cortex.internal",
        )
        updated_hash = self.orchestrator.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(initial_hash, updated_hash)

        # Old hash must be rejected
        res = self.orchestrator.approve(task_id, approved=True, approval_hash=initial_hash)
        self.assertEqual(res["status"], TaskStatus.WAITING_APPROVAL.value)

    # ── Test 11: Sending without approval is rejected by backend ──────────────
    def test_11_sending_without_approval_rejected_by_backend(self) -> None:
        task = Task(
            intent="Send email to ceo@company.com saying secret payload",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={"recipient": "ceo@company.com", "subject": "Notice", "body": "Secret"},
        )
        self.orchestrator._execute(task)
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertIn("approval", task.error.lower())
        self.assertEqual(len(_sent_records), 0)

    # ── Test 12: Replayed approval is rejected ────────────────────────────────
    def test_12_replayed_approval_is_rejected(self) -> None:
        self.orchestrator.chat("Send email to tester@test.io saying first run")
        task_id = self.orchestrator.pending_action["task_id"]

        # First approval succeeds
        res1 = self.orchestrator.approve(task_id, approved=True)
        self.assertEqual(res1["status"], "completed")
        self.assertEqual(len(_sent_records), 1)

        # Replayed approval
        res2 = self.orchestrator.approve(task_id, approved=True)
        self.assertIn("replay", res2.get("error", "").lower())
        self.assertEqual(len(_sent_records), 1)

    # ── Test 13: Cancelled tasks cannot subsequently be approved or executed ──
    def test_13_cancelled_tasks_cannot_subsequently_be_approved_or_executed(self) -> None:
        self.orchestrator.chat("Send email to reviewer@acm.org saying paper draft")
        task_id = self.orchestrator.pending_action["task_id"]

        self.orchestrator.cancel(task_id)
        self.assertEqual(self.orchestrator.tasks[task_id].status, TaskStatus.CANCELED)

        # Attempt to approve cancelled task
        res = self.orchestrator.approve(task_id, approved=True)
        self.assertEqual(res["status"], TaskStatus.CANCELED.value)
        self.assertIn("canceled", res.get("error", "").lower())
        self.assertEqual(len(_sent_records), 0)

    # ── Test 14: Apple Mail unavailable or permission denied results in honest failure ─
    @patch("subprocess.run")
    def test_14_apple_mail_unavailable_or_permission_denied_results_in_honest_failure(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["osascript"],
            stderr="Mail got an error: Application isn't running. (-600)",
        )
        automation = MailAutomation(dry_run=False)
        automation.system = "darwin"

        res = automation.send_mail("test@example.com", "Subj", "Body")
        self.assertFalse(res["ok"])
        self.assertIn("Failed to send email", res["message"])
        self.assertIn("Application isn't running", res["message"])

    # ── Test 15: Failed AppleScript execution never creates false sent record ──
    @patch("subprocess.run")
    def test_15_failed_applescript_execution_never_creates_false_sent_record(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=["osascript"],
            stderr="Mail got an error: Not authorized to send Apple events to Mail. (-1743)",
        )
        automation = MailAutomation(dry_run=False)
        automation.system = "darwin"

        res = automation.send_mail("victim@example.com", "Important", "Body")
        self.assertFalse(res["ok"])
        self.assertEqual(len(automation._sent_records), 0)

        # Independent verification must report False
        verify = automation.verify_mail_sent("victim@example.com", "Important")
        self.assertFalse(verify["verified"])

    # ── Test 16: Unicode and malformed email content handled safely ───────────
    def test_16_unicode_and_malformed_email_content_handled_safely(self) -> None:
        # Malformed content with null byte, carriage returns, quotes, backslashes, emojis, and Indic text
        malformed = 'Null byte: \x00, Quotes: "hello", Backslash: \\, CR: \r\n, Kannada: ನಮಸ್ಕಾರ, Hindi: नमस्ते, Emojis: 🚀✨'
        escaped = _apple_string(malformed)
        self.assertNotIn("\x00", escaped)
        self.assertNotIn("\r", escaped)
        self.assertTrue(escaped.startswith('"'))
        self.assertTrue(escaped.endswith('"'))
        self.assertIn('\\"', escaped)
        self.assertIn("\\\\", escaped)

    # ── Test 17: Email-account endpoint failures are structured and predictable ─
    @patch("backend.integrations.email.manager.MailProviderManager.list_accounts")
    def test_17_email_account_endpoint_failures_are_structured_and_predictable(
        self, mock_list: MagicMock
    ) -> None:
        mock_list.side_effect = RuntimeError("Apple Mail daemon unreachable")
        resp = self.client.get("/email/accounts")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["accounts"], [])
        self.assertIn("Apple Mail daemon unreachable", data["error"])

    # ── Test 18: Memory/history initialization and endpoint behavior ──────────
    def test_18_memory_history_initialization_and_endpoint_behavior(self) -> None:
        # Create uninitialized store
        raw_db_path = Path(self.tmp_dir.name) / "fresh-memory.sqlite3"
        store = EncryptedMemoryStore(db_path=str(raw_db_path))
        # Clear table to simulate missing schema
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("DROP TABLE IF EXISTS memories")

        # Operations must auto-initialize rather than raising OperationalError
        store.put("user_pref", "preference", {"theme": "dark"})
        retrieved = store.get("user_pref")
        self.assertEqual(retrieved, {"theme": "dark"})
        items = store.list()
        self.assertEqual(len(items), 1)

        # Test API endpoint
        resp = self.client.get("/memory")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("items", resp.json())


if __name__ == "__main__":
    unittest.main()
