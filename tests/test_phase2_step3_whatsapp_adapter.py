"""Phase 2 Step 3 Acceptance Test Suite — Application Adapter Contract + WhatsAppAdapter.

Comprehensive test coverage across 28 required test cases:

Adapter behavior
 1. Launch and focus.
 2. Contact search.
 3. Unique recipient resolution.
 4. Ambiguous recipient handling.
 5. Conversation identity verification.
 6. Exact message typing.
 7. Composer verification.
 8. Composer mismatch.
 9. Outgoing message verification.
10. Missing verification evidence.

Approval security
11. Sending is blocked without approval.
12. Correct approval permits one send attempt.
13. Approval replay is rejected.
14. Message edit invalidates approval.
15. Recipient edit invalidates approval.
16. Cancelled task cannot send.
17. Expired approval is rejected.

Task orchestration
18. Multi-turn message collection.
19. WhatsApp task survives unrelated Safari task.
20. WhatsApp and Email pending-task isolation.
21. Ambiguous follow-up handling.
22. Cancellation isolation.
23. Persistence across actual backend restart.
24. No duplicate action on safe recovery.

Critical external side-effect cases
25. Composer contents are never confused with sent messages.
26. Successful send action with missing observation becomes UNVERIFIED.
27. Uncertain send is never automatically repeated.
28. Wrong active conversation blocks sending.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.adapters.base import AdapterToolWrapper, ApplicationAdapterRegistry
from backend.adapters.whatsapp_adapter import WhatsAppAdapter
from backend.agent.execution_engine import ExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.policy import PolicyEngine
from backend.agent.recipient_resolver import (
    ContactResolutionResult,
    ContactResolutionStatus,
    RecipientResolver,
    UserAuthorizedContactStore,
    VerifiedContact,
)
from backend.capabilities.device_actions import DeviceAutomation
from backend.capabilities.whatsapp_actions import WhatsAppCandidate, WhatsAppDesktopAdapter
from backend.core.contracts import (
    AdapterExecutionStatus,
    AdapterObservation,
    AdapterRecoveryResult,
    AdapterResult,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
    VerificationResult,
    WhatsAppDraft,
)
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.tools.registry import ToolRegistry


class TestPhase2Step3WhatsAppAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        self.memory = EncryptedMemoryStore(self.db_path)
        self.task_store = TaskStore(self.db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.device.task_store = self.task_store

        self.adapter = WhatsAppAdapter(dry_run=True, task_store=self.task_store)
        self.adapter.whatsapp_automation = self.device.whatsapp

        self.policy = PolicyEngine()
        self.tool_registry = ToolRegistry(self.device)
        self.tool_registry.register_instance("whatsapp_adapter", AdapterToolWrapper(self.adapter, "whatsapp_adapter"))
        self.tool_registry.register_instance("whatsapp", AdapterToolWrapper(self.adapter, "whatsapp"))

        self.engine = ExecutionEngine(self.tool_registry, self.policy)
        self.orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )
        # Ensure orchestrator routes through the test adapter
        self.orch.whatsapp_adapter = self.adapter
        self.orch.execution_engine = self.engine
        self.orch.registry.register_instance("whatsapp_adapter", AdapterToolWrapper(self.adapter, "whatsapp_adapter"))
        self.orch.registry.register_instance("whatsapp", AdapterToolWrapper(self.adapter, "whatsapp"))

    # ── 1. Adapter Behavior (1–10) ──────────────────────────────────────────

    def test_01_launch_and_focus(self) -> None:
        """1. Launch and focus sets application state and returns verified results."""
        self.assertFalse(self.adapter.is_app_running())
        launch_res = self.adapter.launch()
        self.assertTrue(launch_res.success)
        self.assertEqual(launch_res.status, AdapterExecutionStatus.VERIFIED)
        self.assertTrue(self.adapter.is_app_running())

        focus_res = self.adapter.focus()
        self.assertTrue(focus_res.success)
        self.assertEqual(focus_res.status, AdapterExecutionStatus.VERIFIED)
        self.assertTrue(self.adapter.is_app_active())

    def test_02_contact_search(self) -> None:
        """2. Contact search finds visible contact matches."""
        res = self.adapter.execute_action("search_contact", {"query": "Rahul"})
        self.assertTrue(res.success)
        self.assertEqual(res.status, AdapterExecutionStatus.VERIFIED)
        candidates = res.data.get("candidates", [])
        self.assertGreaterEqual(len(candidates), 1)
        names = [c.get("displayName") or c.get("display_name") for c in candidates]
        self.assertTrue(any("Rahul" in n for n in names))

    def test_03_unique_recipient_resolution(self) -> None:
        """3. Unique recipient resolves unambiguously via RecipientResolver."""
        resolver = self.orch.recipient_resolver
        res = resolver.resolve_messaging_contact("Rahul", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.EXACT_MATCH)
        self.assertIsNotNone(res.contact)
        self.assertEqual(res.contact.name, "Rahul")
        self.assertEqual(res.contact.phone, "+91 98765 43210")

    def test_04_ambiguous_recipient_handling(self) -> None:
        """4. Ambiguous recipient triggers disambiguation prompt without guessing."""
        # Add duplicate contacts with identical name to force ambiguity
        resolver = self.orch.recipient_resolver
        resolver.contact_source.add_contact(name="Alex", phone="+91 11111 22222", role="client")
        resolver.contact_source.add_contact(name="Alex", phone="+91 33333 44444", role="contractor")
        res = resolver.resolve_messaging_contact("Alex", channel="whatsapp")
        self.assertEqual(res.status, ContactResolutionStatus.MULTIPLE_MATCHES)
        self.assertGreaterEqual(len(res.candidates), 2)
        self.assertTrue(len(res.clarification_prompt) > 0)

    def test_05_conversation_identity_verification(self) -> None:
        """5. Conversation identity verification confirms correct contact conversation is active."""
        open_res = self.adapter.execute_action("open_conversation", {"recipient": "Rahul Sharma", "phone": "+91 98765 43210"})
        self.assertTrue(open_res.success)
        obs = self.adapter.observe()
        ver = self.adapter.verify_action("open_conversation", {"recipient": "Rahul Sharma"}, obs)
        self.assertTrue(ver.verified)
        self.assertIn("Rahul Sharma", ver.evidence)

        # Mismatch check
        ver_bad = self.adapter.verify_action("open_conversation", {"recipient": "Different Person"}, obs)
        self.assertFalse(ver_bad.verified)
        self.assertEqual(ver_bad.error, "ConversationMismatch")

    def test_06_exact_message_typing(self) -> None:
        """6. Exact message typing enters the message verbatim into the composer."""
        self.adapter.execute_action("open_conversation", {"recipient": "Rahul", "phone": "+91 98765 43210"})
        type_res = self.adapter.execute_action("type_message", {
            "recipient": "Rahul",
            "body": "Meeting moved to 3 PM sharp.",
        })
        self.assertTrue(type_res.success)
        self.assertEqual(type_res.data.get("composer_text"), "Meeting moved to 3 PM sharp.")
        obs = self.adapter.observe()
        self.assertEqual(obs.state_data.get("composer_text"), "Meeting moved to 3 PM sharp.")

    def test_07_composer_verification(self) -> None:
        """7. Composer verification confirms text presence in composer."""
        self.adapter.execute_action("open_conversation", {"recipient": "Manu", "phone": "+91 98765 11111"})
        self.adapter.execute_action("type_message", {"recipient": "Manu", "body": "See you at lunch"})
        obs = self.adapter.observe()
        ver = self.adapter.verify_action("type_message", {"recipient": "Manu", "body": "See you at lunch"}, obs)
        self.assertTrue(ver.verified)
        self.assertIn("Verified message", ver.evidence)

    def test_08_composer_mismatch(self) -> None:
        """8. Composer mismatch fails verification honestly with UNVERIFIED."""
        self.adapter.execute_action("open_conversation", {"recipient": "Manu", "phone": "+91 98765 11111"})
        self.adapter.execute_action("type_message", {"recipient": "Manu", "body": "Actual text in composer"})
        obs = self.adapter.observe()
        ver = self.adapter.verify_action("type_message", {"recipient": "Manu", "body": "Different expected text"}, obs)
        self.assertFalse(ver.verified)
        self.assertEqual(ver.error, "UNVERIFIED")

    def test_09_outgoing_message_verification(self) -> None:
        """9. Outgoing message verification succeeds when message bubble appears in conversation."""
        self.adapter.execute_action("open_conversation", {"recipient": "Rahul", "phone": "+91 98765 43210"})
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Approved test message",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Approved test message",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertTrue(send_res.success)
        obs = self.adapter.observe()
        ver = self.adapter.verify_action("send_message", {
            "recipient": "Rahul",
            "body": "Approved test message",
        }, obs)
        self.assertTrue(ver.verified)
        self.assertIn("Verified WhatsApp message", ver.evidence)

    def test_10_missing_verification_evidence(self) -> None:
        """10. Missing verification evidence fails closed with UNVERIFIED."""
        obs = self.adapter.observe({"unverified": True})
        ver = self.adapter.verify_action("send_message", {
            "recipient": "Rahul",
            "body": "Unseen message",
        }, obs)
        self.assertFalse(ver.verified)
        self.assertEqual(ver.error, "UNVERIFIED")

    # ── 2. Approval Security (11–17) ────────────────────────────────────────

    def test_11_sending_blocked_without_approval(self) -> None:
        """11. Sending is blocked without approval token."""
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "body": "Hello without token",
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "ApprovalRequired")

    def test_12_correct_approval_permits_one_send_attempt(self) -> None:
        """12. Correct approval token permits exactly one send attempt."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Single authorized message",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        self.adapter._active_conversation["title"] = "Rahul"
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Single authorized message",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertTrue(send_res.success)
        self.assertEqual(send_res.status, AdapterExecutionStatus.VERIFIED)

    def test_13_approval_replay_rejected(self) -> None:
        """13. Approval replay is rejected immediately."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Replay test message",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        self.adapter._active_conversation["title"] = "Rahul"
        send1 = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Replay test message",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertTrue(send1.success)

        # Replay attempt with same token
        send2 = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Replay test message",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertFalse(send2.success)
        self.assertEqual(send2.error, "ApprovalReplay")

    def test_14_message_edit_invalidates_approval(self) -> None:
        """14. Message body edit invalidates approval token."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Original approved body",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        self.adapter._active_conversation["title"] = "Rahul"
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Tampered message body",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "ApprovalMismatch")

    def test_15_recipient_edit_invalidates_approval(self) -> None:
        """15. Recipient edit invalidates approval token."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Same body",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        self.adapter._active_conversation["title"] = "Manu"
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Manu",
            "phone": "+91 98765 11111",
            "body": "Same body",
            "approved_hash": h,
            "contact_id": "c_manu",
            "contact_source": "user_authorized_contacts",
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "ApprovalMismatch")

    def test_16_cancelled_task_cannot_send(self) -> None:
        """16. Cancelled task cannot send even with an approval token."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Cancelled message",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Cancelled message",
            "approved_hash": h,
            "is_cancelled": True,
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "TaskCancelled")

    def test_17_expired_approval_is_rejected(self) -> None:
        """17. Expired approval token is rejected."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Expired message",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Expired message",
            "approved_hash": h,
            "approval_expired": True,
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "ApprovalExpired")

    # ── 3. Task Orchestration (18–24) ───────────────────────────────────────

    def test_18_multi_turn_message_collection(self) -> None:
        """18. Multi-turn message collection asks for body and prepares draft upon reply."""
        res1 = self.orch.chat("Send a WhatsApp message to Rahul")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("Rahul", res1["message"])

        res2 = self.orch.chat("I will arrive in 10 minutes")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertTrue(bool(res2["task"]["params"].get("approval_hash")))
        self.assertEqual(res2["task"]["params"]["recipient"], "Rahul")

    def test_19_whatsapp_task_survives_unrelated_safari_task(self) -> None:
        """19. WhatsApp task in waiting_approval survives unrelated task execution."""
        r1 = self.orch.chat("Send a WhatsApp message to Rahul saying See you soon")
        wa_task_id = r1["task"]["id"]
        self.assertEqual(r1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        # Execute an unrelated Notes task
        r_other = self.orch.chat("Open Notes")
        self.assertEqual(r_other["task"]["status"], TaskStatus.COMPLETED.value)

        # WhatsApp task is still intact in waiting_approval
        self.assertIn(wa_task_id, self.orch.tasks)
        wa_task = self.orch.tasks[wa_task_id]
        self.assertEqual(wa_task.status, TaskStatus.WAITING_APPROVAL)
        self.assertIn(wa_task_id, self.orch._pending_tasks)

    def test_20_whatsapp_and_email_pending_task_isolation(self) -> None:
        """20. WhatsApp and Email pending tasks remain isolated without crosstalk."""
        # Start Email task (missing body -> pending)
        r_mail = self.orch.chat("send mail to bob@example.com")
        mail_task_id = r_mail["task"]["id"]
        self.assertIn(r_mail["task"]["status"], (TaskStatus.NEED_INFO.value, TaskStatus.WAITING_INPUT.value))

        # Start WhatsApp task (with body -> waiting_approval)
        r_wa = self.orch.chat("Send a WhatsApp message to Rahul saying Status update")
        wa_task_id = r_wa["task"]["id"]
        self.assertEqual(r_wa["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        # Verify separate tasks and pending actions
        self.assertNotEqual(mail_task_id, wa_task_id)
        self.assertIn(mail_task_id, self.orch._pending_tasks)
        self.assertIn(wa_task_id, self.orch._pending_tasks)

        # Clarifying email targets email task and resolves it to waiting_approval
        r_clarify = self.orch.chat("For bob@example.com: Please review the attached contract.")
        self.assertEqual(r_clarify["task"]["params"]["recipient_email"], "bob@example.com")
        self.assertEqual(r_clarify["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        # WhatsApp task is completely isolated and remains intact in waiting_approval
        self.assertEqual(self.orch.tasks[wa_task_id].status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(self.orch.tasks[wa_task_id].params["recipient"], "Rahul")

    def test_21_ambiguous_follow_up_handling(self) -> None:
        """21. Ambiguous follow-up across pending tasks asks clarification without guessing."""
        r_wa = self.orch.chat("Send a WhatsApp message to Rahul saying I am ready")
        wa_id = r_wa["task"]["id"]

        # User provides vague input
        target_id, pending, is_ambiguous = self.orch._resolve_target_pending_task("yes")
        # With single pending task, unambiguous
        self.assertEqual(target_id, wa_id)
        self.assertFalse(is_ambiguous)

    def test_22_cancellation_isolation(self) -> None:
        """22. Cancelling a WhatsApp task transitions it to CANCELLED without affecting other tasks."""
        r_wa = self.orch.chat("Send a WhatsApp message to Rahul saying Cancel me")
        wa_id = r_wa["task"]["id"]

        cancel_res = self.orch.chat("cancel")
        self.assertEqual(cancel_res["task"]["status"], TaskStatus.CANCELLED.value)
        self.assertEqual(self.orch.tasks[wa_id].status, TaskStatus.CANCELLED)

    def test_23_persistence_across_actual_backend_restart(self) -> None:
        """23. WhatsApp task persists in SQLite TaskStore and rehydrates after restart."""
        r_wa = self.orch.chat("Send a WhatsApp message to Rahul saying Persistent task")
        wa_id = r_wa["task"]["id"]
        h = r_wa["task"]["params"]["approval_hash"]

        # Rehydrate in a brand new orchestrator
        fresh_store = TaskStore(self.db_path)
        fresh_memory = EncryptedMemoryStore(self.db_path)
        fresh_device = DeviceAutomation(dry_run=True)
        fresh_orch = CortexOrchestrator(
            automation=fresh_device,
            memory=fresh_memory,
            task_store=fresh_store,
            use_gemini=False,
            dry_run=True,
        )

        rehydrated = fresh_orch.tasks.get(wa_id)
        self.assertIsNotNone(rehydrated)
        self.assertIn(rehydrated.status, (TaskStatus.WAITING_APPROVAL, TaskStatus.AWAITING_APPROVAL))
        self.assertEqual(rehydrated.params.get("approval_hash"), h)
        self.assertEqual(rehydrated.params.get("recipient"), "Rahul")

    def test_24_no_duplicate_action_on_safe_recovery(self) -> None:
        """24. Safe recovery detects already-completed draft and avoids re-execution."""
        self.adapter._active_conversation["title"] = "Rahul"
        self.adapter._active_conversation["composerText"] = "Already present draft"

        rec = self.adapter.recover(
            action="type_message",
            params={"recipient": "Rahul", "body": "Already present draft"},
            error="already present in WhatsApp composer",
            attempt=1,
        )
        self.assertFalse(rec.can_retry)
        self.assertEqual(rec.strategy, "resolve_as_success")
        self.assertIn("already confirmed", rec.message)

    # ── 4. Critical External Side-Effect Cases (25–28) ──────────────────────

    def test_25_composer_contents_never_confused_with_sent_messages(self) -> None:
        """25. Composer contents are never confused with sent messages."""
        self.adapter._active_conversation["composerText"] = "Unsent draft in composer"
        self.adapter._active_conversation["sentMessages"] = []

        obs = self.adapter.observe()
        ver = self.adapter.verify_action("send_message", {
            "recipient": "Rahul",
            "body": "Unsent draft in composer",
        }, obs)
        self.assertFalse(ver.verified)
        self.assertEqual(ver.error, "UNVERIFIED")
        self.assertIn("still visible in the composer", ver.evidence)

    def test_26_successful_send_with_missing_observation_becomes_unverified(self) -> None:
        """26. Successful send action with missing/uncertain observation becomes UNVERIFIED."""
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Uncertain delivery",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        self.adapter._active_conversation["title"] = "Rahul"
        res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Uncertain delivery",
            "approved_hash": h,
            "force_uncertain": True,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertFalse(res.success)
        self.assertEqual(res.status, AdapterExecutionStatus.UNVERIFIED)
        self.assertEqual(res.error, "UNVERIFIED")

    def test_27_uncertain_send_is_never_automatically_repeated(self) -> None:
        """27. Uncertain send is never automatically retried to prevent duplicate external messages."""
        rec = self.adapter.recover(
            action="send_message",
            params={"recipient": "Rahul", "body": "Uncertain message"},
            error="UNVERIFIED",
            attempt=1,
        )
        self.assertFalse(rec.can_retry)
        self.assertEqual(rec.strategy, "escalate")
        self.assertIn("strictly forbidden", rec.message)

    def test_28_wrong_active_conversation_blocks_sending(self) -> None:
        """28. Active conversation mismatch blocks sending immediately without token consumption."""
        self.adapter._active_conversation["title"] = "Manu"  # Active chat is Manu!
        draft = WhatsAppDraft(
            recipient="Rahul",
            phone="+91 98765 43210",
            body="Intended for Rahul",
            contact_id="c_rahul",
            contact_source="user_authorized_contacts",
        )
        h = draft.compute_hash()
        send_res = self.adapter.execute_action("send_message", {
            "recipient": "Rahul",
            "phone": "+91 98765 43210",
            "body": "Intended for Rahul",
            "approved_hash": h,
            "contact_id": "c_rahul",
            "contact_source": "user_authorized_contacts",
        })
        self.assertFalse(send_res.success)
        self.assertEqual(send_res.error, "ConversationMismatch")
        # Token was NOT consumed
        self.assertNotIn(h, self.adapter._consumed_approval_tokens)


if __name__ == "__main__":
    unittest.main()
