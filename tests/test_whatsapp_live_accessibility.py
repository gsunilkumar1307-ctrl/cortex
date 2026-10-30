from __future__ import annotations

import concurrent.futures
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import (
    RecipientResolver,
    UserAuthorizedContactStore,
)
from backend.capabilities import DeviceAutomation
from backend.capabilities.whatsapp_actions import (
    WhatsAppCandidate,
    WhatsAppConversationObservation,
    WhatsAppDesktopAdapter,
    WhatsAppObservationStatus,
    WhatsAppSendAttempt,
    WhatsAppUIState,
)
from backend.core.contracts import (
    ContactResolutionStatus,
    TaskStatus,
)
from backend.persistence import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore


class WhatsAppLiveAccessibilityTests(unittest.TestCase):
    """Phase 7 Mock-Verified Regression Suite for Live WhatsApp Accessibility Logic.
    NOTE: These automated tests use mocked adapter states to verify branching,
    fail-closed security boundaries, and error recovery deterministically.
    They verify logic only; live GUI behavior is validated via the manual test guide.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(pathlib.Path(self.tmp.name) / "test_memory.sqlite3")
        self.memory = EncryptedMemoryStore(self.db_path)
        self.task_store = TaskStore(self.db_path)

        self.device = DeviceAutomation(dry_run=True)
        self.adapter = WhatsAppDesktopAdapter(mock_mode=True)
        self.device.whatsapp.adapter = self.adapter
        self.device.whatsapp.task_store = self.task_store

        self.contact_store = UserAuthorizedContactStore(
            contacts=[
                {"id": "c_rahul_sharma", "name": "Rahul Sharma", "phone": "+91 98765 43210", "role": "colleague"},
            ],
            memory_store=self.memory,
        )

        self.resolver = RecipientResolver(
            mail_automation=self.device.mail,
            memory_store=self.memory,
            contact_source=self.contact_store,
            whatsapp_adapter=self.adapter,
        )

        self.orch = CortexOrchestrator(self.device, self.memory, use_gemini=False)
        self.orch.recipient_resolver = self.resolver
        self.orch.task_store = self.task_store
        self.orch.automation.whatsapp.task_store = self.task_store

    # 1. Accessibility permission denied
    def test_01_accessibility_permission_denied(self) -> None:
        self.adapter._mock_permission_denied = True
        res = self.resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertIn("permission denied", res.clarification_prompt.lower())

    # 2. Actual empty search results
    def test_02_actual_empty_search_results_fails_closed(self) -> None:
        self.adapter._mock_candidates = []
        res = self.resolver.resolve_messaging_contact("Nonexistent Person", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.NO_MATCH)
        self.assertIn("No contact found", res.clarification_prompt)
        self.assertIsNone(res.contact)

    # 3. Valid observed candidates
    def test_03_valid_observed_candidates(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Engg", phone_number=None, evidence_label="visible_ui_live")
        ]
        res = self.resolver.resolve_messaging_contact("Rahul Engg", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.EXACT_MATCH)
        self.assertIsNotNone(res.contact)
        self.assertEqual(res.contact.name, "Rahul Engg")
        self.assertEqual(res.contact.metadata.get("evidence_label"), "visible_ui_name_only")

    # 4. Partial and duplicate candidates
    def test_04_partial_and_duplicate_candidates(self) -> None:
        # Partial match -> suggestion only, never auto-selected
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Sharma", phone_number="+91 98765 43210")
        ]
        res_partial = self.resolver.resolve_messaging_contact("Rahul Engg", channel="whatsapp")
        self.assertEqual(res_partial.status, ContactResolutionStatus.NO_MATCH)
        self.assertEqual(len(res_partial.suggestions), 1)

        # Duplicate/multiple matches -> disambiguation
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul College", phone_number="+91 98765 11111"),
            WhatsAppCandidate(display_name="Rahul Office", phone_number="+91 98765 22222"),
        ]
        res_multi = self.resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res_multi.status, ContactResolutionStatus.MULTIPLE_MATCHES)
        self.assertEqual(len(res_multi.candidates), 2)
        self.assertIn("Multiple visible WhatsApp candidates", res_multi.clarification_prompt)

    # 5. Missing phone number
    def test_05_missing_phone_number_marked_unverified(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Ananya Rao", phone_number=None)
        ]
        res = self.resolver.resolve_messaging_contact("Ananya Rao", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.EXACT_MATCH)
        self.assertFalse(res.contact.is_verified)
        self.assertFalse(res.contact.metadata.get("phone_verified"))
        self.assertEqual(res.contact.phone, "")

    # 6. Unexpected dialogs
    def test_06_unexpected_dialogs_blocks_operation(self) -> None:
        self.adapter._mock_modal_dialog = True
        res = self.resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertIn("modal dialog", res.clarification_prompt.lower())

    # 7. Stale accessibility observations
    def test_07_stale_accessibility_observations_rejected(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Sharma", phone_number="+91 98765 43210")
        ]
        chat_res = self.orch.chat("Send WhatsApp message to Rahul Sharma saying Stale Test")
        task_id = chat_res["task"]["id"]
        task = self.orch.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.WAITING_APPROVAL)
        h = task.params.get("approval_hash")

        # Now mark observation stale immediately before approve()
        self.adapter._mock_observation_stale = True
        approve_res = self.orch.approve(task_id, approved=True, approval_hash=h)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("stale", task.error.lower())

    # 8. Changed active conversation before send
    def test_08_changed_active_conversation_aborts_send(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Sharma", phone_number="+91 98765 43210")
        ]
        chat_res = self.orch.chat("Send WhatsApp message to Rahul Sharma saying Conversation Shift")
        task_id = chat_res["task"]["id"]
        task = self.orch.tasks[task_id]
        self.assertEqual(task.status, TaskStatus.WAITING_APPROVAL)
        h = task.params.get("approval_hash")

        # Now change active conversation to unintended contact
        self.adapter._mock_conversation = {
            "title": "Unintended Contact",
            "isOpen": True,
            "composerText": "Test",
        }
        approve_res = self.orch.approve(task_id, approved=True, approval_hash=h)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("changed", task.error.lower())

    # 9. Malformed accessibility output
    def test_09_malformed_accessibility_output_fails_closed(self) -> None:
        self.adapter._mock_candidates = []
        # Simulate selector missing or unreadable UI
        self.adapter._mock_selector_missing = True
        res = self.resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertIn("unreadable", res.clarification_prompt.lower())

    # 10. Unsupported UI hierarchy
    def test_10_unsupported_ui_hierarchy_handled(self) -> None:
        self.adapter._mock_unsupported_hierarchy = True
        res = self.resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.SOURCE_UNAVAILABLE)
        self.assertIn("hierarchy", res.clarification_prompt.lower())

    # 11. Synthetic records not overriding live results
    def test_11_synthetic_records_never_override_empty_live_results(self) -> None:
        # Synthetic demo contact "Rahul Sharma" exists in self.contact_store
        # BUT visible WhatsApp UI returns 0 results for "Rahul Sharma"
        self.adapter._mock_candidates = []
        res = self.resolver.resolve_messaging_contact("Rahul Sharma", channel="whatsapp")
        # Must fail closed: NO_MATCH, never fall back to synthetic store
        self.assertEqual(res.status, ContactResolutionStatus.NO_MATCH)
        self.assertIsNone(res.contact)

    # 12. Application restart with an unresolved attempt
    def test_12_restart_with_unresolved_attempt_reconciles_safely(self) -> None:
        # Create an attempt in SQLite before simulated crash
        attempt = WhatsAppSendAttempt(
            task_id="task_crash_01",
            recipient="Priya Patel",
            phone="+919876567890",
            body="Important update",
            payload_hash="hash_01",
            status="submitted",
        )
        self.task_store.record_whatsapp_send_attempt(attempt)

        # Simulate application restart: instantiate a fresh WhatsAppAutomation
        fresh_automation = DeviceAutomation(dry_run=True).whatsapp
        fresh_automation.task_store = self.task_store

        # Reconcile attempts on startup
        reconciled = fresh_automation.reconcile_unresolved_attempts()
        self.assertEqual(len(reconciled), 1)

        # Check attempt state in SQLite: marked outcome_unknown, never auto-retried
        stored = self.task_store.get_whatsapp_send_attempt(attempt.attempt_id)
        self.assertEqual(stored["status"], "outcome_unknown")
        self.assertEqual(stored["observedOutcome"], "crash_or_restart_detected")
        self.assertIn("restart detected", stored["errorMessage"].lower())

    # 13. Duplicate concurrent requests protected by orchestrator lock
    def test_13_duplicate_concurrent_requests_serialized(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Sharma", phone_number="+91 98765 43210")
        ]
        self.adapter._mock_conversation = {"title": "Rahul Sharma", "isOpen": True, "composerText": ""}
        chat_res = self.orch.chat("Send WhatsApp message to Rahul Sharma saying Race Test")
        task_id = chat_res["task"]["id"]
        task = self.orch.tasks[task_id]
        h = task.params.get("approval_hash")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(self.orch.approve, task_id, True, h)
            f2 = executor.submit(self.orch.approve, task_id, True, h)
            for f in concurrent.futures.as_completed([f1, f2]):
                results.append(f.result())

        # Exactly 1 success, 1 replay rejection
        statuses = [r.get("status") for r in results]
        self.assertIn(TaskStatus.COMPLETED.value, statuses)
        events = [getattr(e, "type", getattr(e, "name", str(e))) for e in task.events]
        self.assertIn("approval_replay_rejected", events)

    # 14. Draft-only bypass attempts rejected
    def test_14_draft_only_bypass_attempts_rejected(self) -> None:
        self.adapter._mock_candidates = [
            WhatsAppCandidate(display_name="Rahul Sharma", phone_number="+91 98765 43210")
        ]
        chat_res = self.orch.chat("Draft a WhatsApp message to Rahul Sharma saying Draft Only Bypass Test")
        task_id = chat_res["task"]["id"]
        task = self.orch.tasks[task_id]
        self.assertTrue(task.params.get("draft_only"))
        h = task.params.get("approval_hash")

        # Direct approval call must be rejected
        res = self.orch.approve(task_id, approved=True, approval_hash=h)
        self.assertEqual(res.get("status"), TaskStatus.FAILED.value)
        self.assertIn("draft-only", res.get("error", "").lower())
        self.assertEqual(len(self.device.whatsapp.sent_messages), 0)


if __name__ == "__main__":
    unittest.main()
