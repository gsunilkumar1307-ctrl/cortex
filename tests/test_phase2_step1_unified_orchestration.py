"""Phase 2, Step 1: Unified Core Task Orchestration & Multi-Task Scoped State Regression Suite.

Tests cover:
1. Canonical task lifecycle transitions: REQUEST_RECEIVED -> PLANNING -> EXECUTING -> OBSERVING -> VERIFYING -> COMPLETED
2. Multi-turn clarification with slot filling and context retention
3. Two independent tasks active simultaneously with contextual matching
4. Ambiguous input across multiple pending tasks prompts clarification without guessing
5. Unrelated turn executed independently while preserving all pending tasks
6. Isolated task cancellation affecting only target task, leaving other tasks intact
7. Task persistence across simulated restart via TaskStore rehydration
8. Compound sequence (_chat_sequence) routing through ExecutionEngine with step.command propagation
9. Strict verification semantics preventing false COMPLETED status on failure/unverified
10. Single-use approval token invalidation upon parameter modification
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.agent.execution_engine import ExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceActionResult, DeviceAutomation
from backend.core.contracts import (
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
    canonical_status,
)
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.tools.registry import ToolRegistry


class TestPhase2Step1UnifiedOrchestration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "test_memory.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.task_store = TaskStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )

        # Mock mail backend to prevent real client calls
        self.mock_mail = MagicMock()
        self.mock_mail.draft_mail.return_value = {
            "ok": True,
            "message": "Draft created in Apple Mail.",
            "data": {"draft_id": "draft_mock_1"},
        }
        self.mock_mail.send_mail.return_value = {
            "ok": True,
            "message": "Email sent successfully.",
            "data": {"message_id": "msg_mock_1"},
        }
        self.mock_mail.delete_draft.return_value = {"ok": True}
        self.device._mail = self.mock_mail
        self.device._get_mail = MagicMock(return_value=self.mock_mail)

    def test_01_canonical_lifecycle_transitions(self) -> None:
        """Test 1: Verify canonical lifecycle status transitions and audit trail events."""
        # Check canonical status mapping
        self.assertEqual(canonical_status(TaskStatus.REQUEST_RECEIVED), TaskStatus.UNDERSTANDING)
        self.assertEqual(canonical_status("received"), TaskStatus.UNDERSTANDING)
        self.assertEqual(canonical_status(TaskStatus.WAITING_FOR_USER_INPUT), TaskStatus.AWAITING_CLARIFICATION)
        self.assertEqual(canonical_status("waiting_for_user_input"), TaskStatus.AWAITING_CLARIFICATION)

        task = Task(
            intent="Open Notes",
            command=TaskCommand.OPEN_APP,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            params={"appName": "Notes"},
            status=TaskStatus.REQUEST_RECEIVED,
        )
        self.assertEqual(task.status, TaskStatus.REQUEST_RECEIVED)
        task.add_event("received", "Request received.")

        # Planning
        task.status = TaskStatus.PLANNING
        task.add_event("planned", "Generated single-step execution plan.")

        step = PlanStep(
            id="step_1",
            action="Open Notes",
            tool="desktop_tool",
            command=TaskCommand.OPEN_APP,
            inputs={"appName": "Notes"},
        )
        plan = Plan(goal="Open Notes", steps=[step], task_id=task.id)
        task.plan = plan

        engine = self.orch.execution_engine
        res = engine.execute_plan(task)

        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(res.status, TaskStatus.COMPLETED)

        event_types = [e.type if hasattr(e, "type") else e["type"] for e in task.audit_trail]
        self.assertIn("received", event_types)
        self.assertIn("planned", event_types)
        self.assertIn("executing", event_types)
        self.assertIn("observed", event_types)
        self.assertIn("step_completed", event_types)
        self.assertIn("completed", event_types)

    def test_02_multi_turn_clarification_with_slot_filling(self) -> None:
        """Test 2: Multi-turn clarification retains context and fills missing slots."""
        # Turn 1: Partial command with recipient but missing body
        r1 = self.orch.chat("send mail to bob@example.com")
        self.assertIn("task", r1)
        task1 = r1["task"]
        self.assertIn(task1["status"], (TaskStatus.WAITING_INPUT.value, TaskStatus.NEED_INFO.value, TaskStatus.AWAITING_CLARIFICATION.value))
        self.assertIn("bob@example.com", r1["message"])
        self.assertEqual(self.orch.pending_action.get("step"), "waiting_for_body")

        # Turn 2: Provide body
        r2 = self.orch.chat("Please review the architecture blueprint attached.")
        task2 = r2["task"]
        self.assertEqual(task2["params"]["recipient_email"], "bob@example.com")
        self.assertIn("architecture blueprint", task2["params"]["body"].lower())
        self.assertEqual(task2["status"], TaskStatus.WAITING_APPROVAL.value)

    def test_03_two_independent_active_tasks_simultaneous(self) -> None:
        """Test 3: Two independent active tasks exist simultaneously and match contextually."""
        # Seed Task A (Email for Bob)
        task_a = Task(
            intent="send email to bob@example.com",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={"recipient": "bob@example.com", "subject": "Project Status", "body": "Hello Bob"},
        )
        task_a.status = TaskStatus.WAITING_APPROVAL
        self.orch.tasks[task_a.id] = task_a
        self.orch._pending_tasks[task_a.id] = {
            "type": "email_draft",
            "task_id": task_a.id,
            "task": task_a.to_dict(),
            "recipient": "bob@example.com",
            "step": "confirm_send",
            "command": "send_mail",
        }

        # Seed Task B (WhatsApp for Alice)
        task_b = Task(
            intent="send whatsapp to Alice",
            command=TaskCommand.SEND_WHATSAPP,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={"recipient": "Alice", "contact": "Alice", "body": "Hey Alice"},
        )
        task_b.status = TaskStatus.WAITING_APPROVAL
        self.orch.tasks[task_b.id] = task_b
        self.orch._pending_tasks[task_b.id] = {
            "type": "whatsapp_draft",
            "task_id": task_b.id,
            "task": task_b.to_dict(),
            "recipient": "Alice",
            "step": "confirm_send",
            "command": "send_whatsapp",
        }

        self.assertEqual(len(self.orch._pending_tasks), 2)

        # Contextual resolution for Bob
        target_id_bob, pending_bob, is_ambig = self.orch._resolve_target_pending_task("Send the email to Bob")
        self.assertFalse(is_ambig)
        self.assertEqual(target_id_bob, task_a.id)

        # Contextual resolution for Alice
        target_id_alice, pending_alice, is_ambig2 = self.orch._resolve_target_pending_task("Send the WhatsApp message to Alice")
        self.assertFalse(is_ambig2)
        self.assertEqual(target_id_alice, task_b.id)

    def test_04_ambiguous_response_prompts_clarification_no_guessing(self) -> None:
        """Test 4: When multiple tasks are pending, ambiguous input asks user to clarify."""
        # Two pending tasks
        self.orch._pending_tasks["task_1"] = {
            "type": "email_draft",
            "task_id": "task_1",
            "recipient": "bob@example.com",
            "step": "confirm_send",
        }
        self.orch._pending_tasks["task_2"] = {
            "type": "whatsapp_draft",
            "task_id": "task_2",
            "recipient": "alice",
            "step": "confirm_send",
        }

        # Ambiguous input "Send it" or "Proceed"
        target_id, pending, is_ambiguous = self.orch._resolve_target_pending_task("Send it")
        self.assertTrue(is_ambiguous)
        self.assertIsNone(target_id)

        # In chat(), this triggers conversational clarification
        res = self.orch.chat("Send it")
        self.assertIn("multiple pending tasks active", res["message"].lower())
        self.assertIn("bob@example.com", res["message"])
        self.assertIn("alice", res["message"])

    def test_05_unrelated_query_executed_without_affecting_pending_tasks(self) -> None:
        """Test 5: An unrelated informational/math query executes without clearing pending tasks."""
        self.orch._pending_tasks["task_email"] = {
            "type": "email_draft",
            "task_id": "task_email",
            "recipient": "charlie@example.com",
            "step": "waiting_for_body",
        }
        self.assertEqual(len(self.orch._pending_tasks), 1)

        # Execute an unrelated calculation or question
        res = self.orch.chat("What is 15 * 8?")
        self.assertIn("task", res)
        # Pending task must still be completely intact
        self.assertIn("task_email", self.orch._pending_tasks)
        self.assertEqual(self.orch._pending_tasks["task_email"]["recipient"], "charlie@example.com")

    def test_06_isolated_task_cancellation(self) -> None:
        """Test 6: Cancelling one task leaves other active tasks intact."""
        task_1 = Task("email to Bob", TaskCommand.SEND_MAIL, RiskLevel.HIGH, True, params={"recipient": "Bob"})
        task_1.status = TaskStatus.WAITING_APPROVAL
        task_2 = Task("whatsapp to Alice", TaskCommand.SEND_WHATSAPP, RiskLevel.HIGH, True, params={"recipient": "Alice"})
        task_2.status = TaskStatus.WAITING_APPROVAL

        self.orch.tasks[task_1.id] = task_1
        self.orch.tasks[task_2.id] = task_2
        self.orch._pending_tasks[task_1.id] = {
            "type": "email_draft",
            "task_id": task_1.id,
            "task": task_1,
            "recipient": "Bob",
        }
        self.orch._pending_tasks[task_2.id] = {
            "type": "whatsapp_draft",
            "task_id": task_2.id,
            "task": task_2,
            "recipient": "Alice",
        }

        # Cancel Bob's task explicitly
        res = self.orch.chat("Cancel Bob's email")
        self.assertIn("cancel", res["message"].lower())
        self.assertNotIn(task_1.id, self.orch._pending_tasks)
        self.assertIn(task_2.id, self.orch._pending_tasks)
        self.assertEqual(self.orch.tasks[task_1.id].status, TaskStatus.CANCELED)

    def test_07_task_persistence_across_rehydration(self) -> None:
        """Test 7: Tasks persist across restarts and rehydrate into _pending_tasks."""
        # Create an active task in task_store
        persisted_task = Task(
            intent="draft mail to david@example.com",
            command=TaskCommand.DRAFT_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={"recipient": "david@example.com", "subject": "Review Request", "approval_hash": "hash_123"},
        )
        persisted_task.status = TaskStatus.WAITING_APPROVAL
        self.task_store.save_task(persisted_task)

        # Simulate fresh startup with a new orchestrator pointing to same task_store
        new_orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )

        self.assertIn(persisted_task.id, new_orch._pending_tasks)
        rehydrated = new_orch._pending_tasks[persisted_task.id]
        self.assertEqual(rehydrated["type"], "approval")
        self.assertEqual(rehydrated["recipient"], "david@example.com")
        self.assertEqual(rehydrated["approval_hash"], "hash_123")

    def test_08_chat_sequence_routes_through_execution_engine(self) -> None:
        """Test 8: Compound sequence execution routes through ExecutionEngine with step commands."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="VERIFIED\n", stderr="")

            res = self.orch.chat("Open Notes and type exactly: Hello from Phase 2.")
            task = res["task"]
            self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(res["message"], "Sequence completed.")

            # Audit trail must have step_completed events with explicit commands
            audit_trail = task.get("auditTrail", [])
            step_events = [e for e in audit_trail if e.get("type") == "step_completed"]
            self.assertEqual(len(step_events), 2)
            self.assertEqual(step_events[0]["data"]["command"], TaskCommand.OPEN_APP.value)
            self.assertEqual(step_events[1]["data"]["command"], TaskCommand.TYPE_TEXT.value)

    def test_09_verification_failure_prevents_false_completed(self) -> None:
        """Test 9: Verification failure or unverified result prevents COMPLETED status."""
        self.device.dry_run = False
        self.device.system = "darwin"
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            # Return UNVERIFIED outcome
            mock_subproc.return_value = MagicMock(returncode=0, stdout="UNVERIFIED: text not found\n", stderr="")

            res = self.orch.chat("Open Notes and type exactly: Text not appearing.")
            task = res["task"]

            self.assertNotEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(task["status"], TaskStatus.NEEDS_ATTENTION.value)
            self.assertIn("could not be verified", res["message"])

    def test_10_approval_gate_and_hash_invalidation(self) -> None:
        """Test 10: Single-use approval token invalidates upon parameter changes."""
        # Create draft requiring approval
        self.orch.chat("send mail to frank@example.com")
        r2 = self.orch.chat("Inform them that the meeting is scheduled for Friday at 3 PM.")
        task = r2["task"]
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        initial_hash = task["params"]["approval_hash"]
        self.assertTrue(bool(initial_hash))

        # Edit draft parameter (subject)
        r3 = self.orch.chat("Change subject to Rescheduled Meeting Notice")
        task3 = r3["task"]
        new_hash = task3["params"]["approval_hash"]
        self.assertTrue(bool(new_hash))
        self.assertNotEqual(initial_hash, new_hash)

        # Replaying initial hash must fail
        replay_res = self.orch.approve(task3["id"], approved=True, approval_hash=initial_hash)
        self.assertEqual(replay_res["status"], TaskStatus.WAITING_APPROVAL.value)

        # Approving with current valid hash succeeds
        approve_res = self.orch.approve(task3["id"], approved=True, approval_hash=new_hash)
        self.assertEqual(approve_res["status"], TaskStatus.COMPLETED.value)
