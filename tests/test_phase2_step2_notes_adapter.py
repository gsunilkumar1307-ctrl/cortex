"""Phase 2 Step 2 Acceptance Test Suite — Application Adapter Contract + NotesAdapter.

Comprehensive test coverage across:
1. Notes launch and focus.
2. Exact text typing.
3. Successful content verification.
4. Verification failure (honest failure reporting, status never COMPLETED).
5. Duplicate typing prevention (idempotency).
6. Retry and recovery behavior.
7. Task cancellation.
8. Task persistence and resumption.
9. Approval and lifecycle compatibility.
10. Legacy Notes workflow compatibility.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.adapters.base import AdapterToolWrapper, ApplicationAdapterRegistry
from backend.adapters.notes_adapter import NotesAdapter
from backend.agent.execution_engine import ExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.policy import PolicyEngine
from backend.capabilities.device_actions import DeviceActionResult, DeviceAutomation
from backend.core.contracts import (
    AdapterExecutionStatus,
    AdapterResult,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
)
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.tools.registry import ToolRegistry


class TestPhase2Step2NotesAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.task_store = TaskStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.adapter = NotesAdapter(dry_run=True)
        self.policy = PolicyEngine()
        self.registry = ToolRegistry(automation=self.device)
        self.engine = ExecutionEngine(registry=self.registry, policy_engine=self.policy)
        self.orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )

    # ── Test 1: Notes Launch and Focus ─────────────────────────────────────
    def test_01_notes_launch_and_focus(self) -> None:
        """1. Verify launch() and focus() conform to AdapterResult contract."""
        launch_res = self.adapter.launch()
        self.assertTrue(launch_res.success)
        self.assertEqual(launch_res.status, AdapterExecutionStatus.VERIFIED)
        self.assertEqual(launch_res.action, "launch")
        self.assertTrue(launch_res.data.get("running"))

        focus_res = self.adapter.focus()
        self.assertTrue(focus_res.success)
        self.assertEqual(focus_res.status, AdapterExecutionStatus.VERIFIED)
        self.assertEqual(focus_res.action, "focus")
        self.assertTrue(focus_res.data.get("active"))

    # ── Test 2: Exact Text Typing ──────────────────────────────────────────
    def test_02_exact_text_typing(self) -> None:
        """2. Verify execute_action('type_text') enters clean text without meta phrasing."""
        res = self.adapter.execute_action("type_text", {"text": "exactly: Hello from Cortex Adapter."})
        self.assertTrue(res.success)
        self.assertEqual(res.status, AdapterExecutionStatus.VERIFIED)
        self.assertEqual(res.data.get("text"), "Hello from Cortex Adapter.")
        self.assertEqual(res.data.get("appName"), "Notes")
        self.assertFalse(res.data.get("already_present"))

    # ── Test 3: Successful Content Verification ────────────────────────────
    def test_03_successful_content_verification(self) -> None:
        """3. Content observation independently verifies typed text."""
        # Type into adapter
        self.adapter.execute_action("type_text", {"text": "Verify me in Notes."})
        # Observe
        obs = self.adapter.observe({"text": "Verify me in Notes."})
        self.assertTrue(obs.state_data.get("text_verified"))

        # Verify
        ver = self.adapter.verify_action("type_text", {"text": "Verify me in Notes."}, obs)
        self.assertTrue(ver.verified)
        self.assertGreaterEqual(ver.confidence, 0.9)
        self.assertIn("Verify me in Notes.", ver.evidence)

    # ── Test 4: Verification Failure (Honest Failure Reporting) ────────────
    def test_04_verification_failure_reports_unverified(self) -> None:
        """4. When text is not found in the note, verification fails with UNVERIFIED."""
        adapter = NotesAdapter(dry_run=False)
        adapter.system = "darwin"

        # Mock observation where text is unverified
        with patch.object(adapter, "is_app_running", return_value=True), \
             patch.object(adapter, "focus", return_value=AdapterResult(success=True, status=AdapterExecutionStatus.VERIFIED, action="focus")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="UNVERIFIED\n",
                stderr="",
            )

            res = adapter.execute_action("type_text", {"text": "Missing content."})
            self.assertFalse(res.success)
            self.assertEqual(res.status, AdapterExecutionStatus.UNVERIFIED)
            self.assertTrue(res.data.get("unverified"))

            obs = adapter.observe({"text": "Missing content."})
            obs.state_data["text_verified"] = False
            obs.state_data["unverified"] = True

            ver = adapter.verify_action("type_text", {"text": "Missing content."}, obs)
            self.assertFalse(ver.verified)
            self.assertEqual(ver.error, "UNVERIFIED")
            self.assertIn("Text verification failed", ver.evidence)

    # ── Test 5: Duplicate Typing Prevention (Idempotency) ──────────────────
    def test_05_duplicate_typing_prevention(self) -> None:
        """5. Re-executing typing when text already present prevents duplicate typing."""
        adapter = NotesAdapter(dry_run=False)
        adapter.system = "darwin"

        with patch.object(adapter, "is_app_running", return_value=True), \
             patch.object(adapter, "focus", return_value=AdapterResult(success=True, status=AdapterExecutionStatus.VERIFIED, action="focus")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="ALREADY_PRESENT\n",
                stderr="",
            )

            res = adapter.execute_action("type_text", {"text": "Existing content."})
            self.assertTrue(res.success)
            self.assertEqual(res.status, AdapterExecutionStatus.VERIFIED)
            self.assertTrue(res.data.get("already_present"))
            self.assertIn("Duplicate typing prevented", res.message)

    # ── Test 6: Retry and Recovery Behavior ────────────────────────────────
    def test_06_retry_and_recovery_behavior(self) -> None:
        """6. Transient errors trigger bounded retry; already present resolves as success."""
        # Already present recovery
        rec1 = self.adapter.recover("type_text", {"text": "Existing"}, "already present in Notes")
        self.assertFalse(rec1.can_retry)
        self.assertEqual(rec1.strategy, "resolve_as_success")
        self.assertIn("duplicate typing safely prevented", rec1.message)

        # Focus recovery on attempt 1
        rec2 = self.adapter.recover("type_text", {"text": "Test"}, "Notes window not available", attempt=1)
        self.assertTrue(rec2.can_retry)
        self.assertEqual(rec2.strategy, "retry")

        # Escalate on attempt 2
        rec3 = self.adapter.recover("type_text", {"text": "Test"}, "Notes window not available", attempt=2)
        self.assertFalse(rec3.can_retry)
        self.assertEqual(rec3.strategy, "escalate")

    # ── Test 7: Task Cancellation ──────────────────────────────────────────
    def test_07_task_cancellation_during_execution(self) -> None:
        """7. A task cancelled midway through execution does not execute remaining steps."""
        task = Task(intent="Open Notes and type Hello", command=TaskCommand.UNKNOWN)
        plan = Plan(
            goal="Open Notes and type Hello",
            steps=[
                PlanStep(id="s1", action="Launch", tool="notes_adapter", inputs={"action": "launch"}),
                PlanStep(id="s2", action="Type", tool="notes_adapter", inputs={"action": "type_text", "text": "Hello"}),
            ],
            task_id=task.id,
        )
        task.plan = plan

        # Simulate cancellation before step 2
        def on_progress(state: str, msg: str) -> None:
            if "Step 2" in msg:
                task.status = TaskStatus.CANCELLED

        res = self.engine.execute_plan(task, plan, on_progress=on_progress)
        self.assertEqual(res.status, TaskStatus.CANCELLED)
        # Step 2 was not executed
        step_2 = plan.steps[1]
        self.assertNotEqual(step_2.status, "completed")

    # ── Test 8: Task Persistence and Resumption ────────────────────────────
    def test_08_task_persistence_and_resumption(self) -> None:
        """8. Notes tasks persist to TaskStore and rehydrate accurately across restart."""
        task = Task(
            intent="Write note titled Project Plan saying Review Q4 roadmap",
            command=TaskCommand.WRITE_NOTE,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            params={"title": "Project Plan", "body": "Review Q4 roadmap"},
        )
        task.status = TaskStatus.AWAITING_CLARIFICATION
        self.task_store.save_task(task)

        # Fresh orchestrator
        fresh_orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )
        self.assertIn(task.id, fresh_orch.tasks)
        rehydrated = fresh_orch.tasks[task.id]
        self.assertEqual(rehydrated.params["title"], "Project Plan")
        self.assertEqual(rehydrated.params["body"], "Review Q4 roadmap")

    # ── Test 9: Approval and Lifecycle Compatibility ───────────────────────
    def test_09_approval_and_lifecycle_compatibility(self) -> None:
        """9. Notes execution follows canonical lifecycle: EXECUTING -> OBSERVING -> VERIFYING -> COMPLETED."""
        task = Task(intent="Create note", command=TaskCommand.WRITE_NOTE, params={"title": "Demo", "body": "Notes"})
        plan = Plan(
            goal="Create note",
            steps=[
                PlanStep(
                    id="s1",
                    action="Create Note Demo",
                    tool="notes_adapter",
                    inputs={"action": "create_note", "title": "Demo", "body": "Notes"},
                )
            ],
            task_id=task.id,
        )
        task.plan = plan

        lifecycle_events = []
        def track_progress(state: str, msg: str) -> None:
            lifecycle_events.append(state)

        final_res = self.engine.execute_plan(task, plan, on_progress=track_progress)
        self.assertEqual(final_res.status, TaskStatus.COMPLETED)
        self.assertIn("executing", lifecycle_events)
        self.assertIn("observing", lifecycle_events)
        self.assertIn("verifying", lifecycle_events)

        event_types = [e.type if hasattr(e, "type") else e.get("type", "") for e in task.audit_trail]
        self.assertIn("executing", event_types)
        self.assertIn("observed", event_types)
        self.assertIn("step_verified", event_types)
        self.assertIn("completed", event_types)

    # ── Test 10: Legacy Notes Workflow Compatibility ───────────────────────
    def test_10_legacy_notes_workflow_compatibility(self) -> None:
        """10. Existing conversational chat APIs for Notes remain fully operational via adapter."""
        # 1. Create note
        res1 = self.orch.chat("Create a note titled Architecture Plan with the following content: Implement NotesAdapter.")
        self.assertEqual(res1["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res1["task"]["params"]["title"], "Architecture Plan")

        # 2. Append point
        res2 = self.orch.chat("Add this point: Integrate with ExecutionEngine.")
        self.assertEqual(res2["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res2["task"]["params"]["action"], "append_note")

        # 3. Shorten title
        res3 = self.orch.chat("Make the title shorter")
        self.assertEqual(res3["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res3["task"]["params"]["action"], "shorten_title")

        # 4. Open note
        res4 = self.orch.chat("Open that note")
        self.assertEqual(res4["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res4["task"]["params"]["action"], "open_note")


if __name__ == "__main__":
    unittest.main()
