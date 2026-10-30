from __future__ import annotations

import concurrent.futures
import platform
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.agent.email_engine import EmailDraft
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import RecipientResolver
from backend.api.server import app, orchestrator as server_orchestrator
from backend.capabilities import DeviceAutomation
from backend.capabilities.mail_actions import clear_mail_records, _sent_records
from backend.core.contracts import RiskLevel, Task, TaskCommand, TaskStatus
from backend.integrations.email.apple_mail_provider import AppleMailProvider
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.tools.registry import ToolRegistry
from backend.agent.execution_engine import ExecutionEngine
from backend.core.auth import get_or_create_session_secret


class TestStageFLiveIntegrationValidation(unittest.TestCase):
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
        server_orchestrator.registry = ToolRegistry(self.automation)
        server_orchestrator.execution_engine = ExecutionEngine(server_orchestrator.registry, server_orchestrator.policy_engine)
        self.client = TestClient(app, headers={"X-Cortex-Session": get_or_create_session_secret()})

    def tearDown(self) -> None:
        clear_mail_records()
        self.tmp_dir.cleanup()

    # =========================================================================
    # Phase 2 — Cancellation End-to-End Across All Lifecycle States
    # =========================================================================

    def test_cancellation_during_recipient_clarification_typed_and_ui(self) -> None:
        # Typed cancellation
        self.orchestrator.chat("Draft an email to Alex saying Friday meeting is confirmed")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_clarification",
        )
        res_typed = self.orchestrator.chat("cancel")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertEqual(res_typed["message"], "Cancelled.")

        # UI cancellation via API POST /tasks/{id}/cancel
        res_chat = self.client.post("/chat", json={"message": "Draft email to Charlie saying hello"})
        task_id = res_chat.json()["task"]["id"]
        res_cancel = self.client.post(f"/tasks/{task_id}/cancel")
        self.assertEqual(res_cancel.status_code, 200)
        self.assertEqual(res_cancel.json()["status"], "canceled")

    def test_cancellation_during_recipient_disambiguation(self) -> None:
        resolver = RecipientResolver()
        resolver.KNOWN_DIRECTORY = [
            {"name": "Alex Miller", "email": "alex.m@cortex.internal", "role": "dev"},
            {"name": "Alex Morgan", "email": "alex.morgan@cortex.internal", "role": "design"},
        ]
        self.orchestrator.recipient_resolver = resolver
        self.orchestrator.chat("Send email to Alex saying design approved")
        self.assertEqual(
            self.orchestrator.pending_action.get("step"),
            "waiting_for_recipient_disambiguation",
        )

        # User cancels instead of selecting candidate
        res = self.orchestrator.chat("No, cancel that")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertEqual(res["message"], "Cancelled.")

    def test_cancellation_does_not_affect_unrelated_tasks(self) -> None:
        # Create Task A
        task_a = Task(
            intent="Task A",
            command=TaskCommand.CALCULATE,
            params={"expression": "10 * 5"},
            status=TaskStatus.COMPLETED,
            result="50",
        )
        self.orchestrator.tasks[task_a.id] = task_a

        # Create Task B (Email pending)
        self.orchestrator.chat("Send email to client@corp.com saying proposal ready")
        task_b_id = self.orchestrator.pending_action["task_id"]

        # Cancel Task B
        self.orchestrator.chat("cancel")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.tasks[task_b_id].status, TaskStatus.CANCELED)

        # Task A must remain completely unaffected
        self.assertEqual(self.orchestrator.tasks[task_a.id].status, TaskStatus.COMPLETED)
        self.assertEqual(self.orchestrator.tasks[task_a.id].result, "50")

    @patch("backend.agent.orchestrator.search_web")
    def test_cancellation_never_triggers_search_or_llm_fallback(self, mock_search: MagicMock) -> None:
        self.orchestrator.pending_action = None
        for cancel_cmd in ("cancel", "abort it", "discard", "nevermind", "ರದ್ದು", "रद्द करो"):
            res = self.orchestrator.chat(cancel_cmd)
            mock_search.assert_not_called()
            self.assertTrue(any(w in res["message"] for w in ("Cancelled", "ರದ್ದು", "रद्द")))

    def test_subsequent_question_works_normally_after_cancellation(self) -> None:
        self.orchestrator.chat("Draft email to Sam saying project delayed")
        self.orchestrator.chat("cancel")
        self.assertIsNone(self.orchestrator.pending_action)

        res = self.orchestrator.chat("What is the capital of France?")
        self.assertNotIn("Sam", res["message"])
        self.assertNotIn("email", res["message"].lower())
        self.assertIn("Paris", res["message"])

    # =========================================================================
    # Phase 3 — Approval Security & Tamper Resistance
    # =========================================================================

    def test_approval_missing_hash_rejected_by_api(self) -> None:
        res = self.client.post("/chat", json={"message": "Send email to security@corp.com saying audit pass"})
        task_id = res.json()["task"]["id"]

        # Client attempts approval without supplying approval_hash
        res_approve = self.client.post(f"/tasks/{task_id}/approve", json={"approved": True})
        self.assertEqual(res_approve.status_code, 400)
        self.assertIn("Missing approval hash", res_approve.json()["detail"])

    def test_approval_incorrect_hash_rejected_by_api(self) -> None:
        res = self.client.post("/chat", json={"message": "Send email to security@corp.com saying audit pass"})
        task_id = res.json()["task"]["id"]

        # Client supplies a forged/incorrect hash
        res_approve = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": "forged_sha256_hash_12345"},
        )
        self.assertEqual(res_approve.status_code, 400)
        self.assertIn("mismatch", res_approve.json()["detail"].lower())

    def test_content_modification_invalidates_prior_hash(self) -> None:
        res = self.client.post("/chat", json={"message": "Send email to audit@cortex.internal saying Report clean"})
        task_id = res.json()["task"]["id"]
        original_hash = res.json()["task"]["params"]["approval_hash"]

        # Edit body content
        res_edit = self.client.post(f"/tasks/{task_id}/edit", json={"body": "Report critical: 5 defects found"})
        self.assertEqual(res_edit.status_code, 200)
        new_hash = res_edit.json()["task"]["params"]["approval_hash"]
        self.assertNotEqual(original_hash, new_hash)

        # Attempting approval with old hash is rejected
        res_approve_old = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": original_hash},
        )
        self.assertEqual(res_approve_old.status_code, 400)
        self.assertIn("mismatch", res_approve_old.json()["detail"].lower())

        # Approving with current valid hash succeeds
        res_approve_new = self.client.post(
            f"/tasks/{task_id}/approve",
            json={"approved": True, "approval_hash": new_hash},
        )
        self.assertEqual(res_approve_new.status_code, 200)
        self.assertEqual(res_approve_new.json()["status"], "completed")

    def test_concurrent_approval_requests_are_race_safe(self) -> None:
        # Create a task waiting for approval in server_orchestrator
        res = self.client.post("/chat", json={"message": "Send email to race@test.io saying Testing concurrency"})
        task_id = res.json()["task"]["id"]
        valid_hash = res.json()["task"]["params"]["approval_hash"]

        results = []

        def submit_approval():
            return self.client.post(
                f"/tasks/{task_id}/approve",
                json={"approved": True, "approval_hash": valid_hash},
            )

        # Launch 5 concurrent approval requests at the exact same moment
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(submit_approval) for _ in range(5)]
            for f in concurrent.futures.as_completed(futures):
                results.append(f.result())

        status_codes = [r.status_code for r in results]
        # Exactly one request must succeed (200), and all other concurrent attempts must be rejected (400)
        self.assertEqual(status_codes.count(200), 1, f"Expected exactly 1 success, got: {status_codes}")
        self.assertEqual(status_codes.count(400), 4, f"Expected 4 rejections, got: {status_codes}")

    def test_direct_execution_without_approval_is_blocked(self) -> None:
        task = Task(
            intent="Send email to vip@domain.com saying unapproved send",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={"recipient": "vip@domain.com", "subject": "Notice", "body": "Payload"},
        )
        self.orchestrator._execute(task)
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertIn("approval", task.error.lower())
        self.assertEqual(len(_sent_records), 0)

    # =========================================================================
    # Phase 4 — Live macOS Mail Provider Behavior
    # =========================================================================

    def test_apple_mail_provider_query_and_distinction(self) -> None:
        if platform.system().lower() != "darwin":
            self.skipTest("macOS specific test")

        provider = AppleMailProvider(dry_run=False)
        is_auth = provider.is_authenticated()
        accounts = provider.get_accounts()

        # Check honest status
        self.assertIsInstance(is_auth, bool)
        self.assertIsInstance(accounts, list)
        if accounts:
            self.assertIn("email", accounts[0])
            self.assertIn("name", accounts[0])

        # Test distinct states:
        # 1. Draft records != Sent records
        self.assertEqual(len(provider._draft_records), 0)
        self.assertEqual(len(provider._sent_records), 0)

        # 2. Independent verification of non-existent message returns False
        verify_res = provider.verify_message_sent("nobody_12345@cortex.internal", "Nonexistent Subject")
        self.assertFalse(verify_res.get("verified", False))

    # =========================================================================
    # Phase 5 — Multilingual & Conversational Resiliency
    # =========================================================================

    @patch("backend.agent.orchestrator.search_web", return_value=[{"title": "Info", "body": "Content", "href": "url"}])
    def test_multilingual_interleaving_native_scripts_and_transliterations(self, mock_search: MagicMock) -> None:
        # Start email
        self.orchestrator.chat("Draft an email to Alex saying meeting confirmed")
        self.assertIsNotNone(self.orchestrator.pending_action)

        # Kannada native script question
        r_kn = self.orchestrator.chat("ನಮಸ್ಕಾರ, ನೀವು ಹೇಗಿದ್ದೀರಿ?")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertTrue(any(w in r_kn["message"] for w in ("ನಮಸ್ಕಾರ", "ಚೆನ್ನಾಗಿದ್ದೇನೆ", "ಹೇಗೆ")))

        # Hindi romanized transliteration question
        r_hi = self.orchestrator.chat("Hindi me batao Cortex kya hai")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertNotIn("Alex's email", r_hi["message"])

        # Localized Hindi cancellation
        r_cancel = self.orchestrator.chat("रद्द करो")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertIn("रद्द", r_cancel["message"])


if __name__ == "__main__":
    unittest.main()
