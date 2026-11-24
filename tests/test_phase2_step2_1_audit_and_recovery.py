"""
Regression tests for Phase 2 Step 2.1: Audit Evidence Correction and Recovery Safety.

Verifies:
1. Notes application name appears correctly in verification events (no empty quotes '').
2. Requested text is correctly associated with verification events.
3. Missing metadata is reported honestly without fabricating values or displaying empty quotes.
4. Recovery resolves as success ONLY after positive independent observation proves intended side effect.
5. Uncertain recovery remains UNVERIFIED and does not convert uncertain operations into success.
6. Cancelled tasks are never resumed or resolved as success during recovery.
7. End-to-end audit trail in ExecutionEngine produces structured metadata (appName, action, text, verified).
"""

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from backend.core.contracts import (
    AdapterExecutionStatus,
    AdapterObservation,
    AdapterRecoveryResult,
    AdapterResult,
    AuditEvent,
    ExecutionError,
    ExecutionResult,
    Observation,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
    VerificationResult,
)
from backend.adapters.base import ApplicationAdapterRegistry, AdapterToolWrapper
from backend.adapters.notes_adapter import NotesAdapter
from backend.agent.execution_engine import ExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.policy import PolicyEngine
from backend.tools.desktop_tool import DesktopTool
from backend.tools.registry import ToolRegistry


class TestPhase2Step21AuditEvidenceAndRecoverySafety(unittest.TestCase):
    def setUp(self) -> None:
        self.notes_adapter = NotesAdapter(dry_run=True)
        self.policy = PolicyEngine()
        self.tool_registry = ToolRegistry()
        self.adapter_registry = ApplicationAdapterRegistry()
        self.adapter_registry.register(self.notes_adapter)
        self.notes_wrapper = AdapterToolWrapper(self.notes_adapter)
        self.tool_registry.register_instance("notes_adapter", self.notes_wrapper)

        # Mock automation for DesktopTool
        self.mock_automation = MagicMock()
        self.mock_automation.dry_run = False
        self.mock_automation.is_app_running.return_value = True
        self.mock_automation.is_app_active.return_value = True
        self.desktop_tool = DesktopTool(self.mock_automation)
        self.tool_registry.register_instance("desktop_tool", self.desktop_tool)

        self.engine = ExecutionEngine(
            registry=self.tool_registry,
            policy_engine=self.policy,
        )

    # ── Test 1: DesktopTool Verification Populates Application Name ────────
    def test_01_desktop_tool_verify_open_app_populates_name(self) -> None:
        """1. DesktopTool.verify for open_app uses appName and avoids empty quotes ''."""
        # Top-level appName
        inputs = {"appName": "Notes", "command": "open_app"}
        obs = Observation(
            target="desktop:open_app",
            state_data={"command": "open_app", "app_running": True, "app_active": True},
        )
        res = ExecutionResult(step_id="s1", ok=True, message="Opened Notes")

        verif = self.desktop_tool.verify(inputs, obs, res)
        self.assertTrue(verif.verified)
        self.assertEqual(verif.evidence, "Verified application 'Notes' is running. In foreground.")
        self.assertNotIn("''", verif.evidence)

        # Nested appName under params
        inputs_nested = {"params": {"appName": "Notes"}, "command": "open_app"}
        verif_nested = self.desktop_tool.verify(inputs_nested, obs, res)
        self.assertTrue(verif_nested.verified)
        self.assertEqual(verif_nested.evidence, "Verified application 'Notes' is running. In foreground.")
        self.assertNotIn("''", verif_nested.evidence)

    # ── Test 2: DesktopTool Verification Populates Requested Text ──────────
    def test_02_desktop_tool_verify_type_text_populates_text_and_app(self) -> None:
        """2. DesktopTool.verify for type_text populates text and app name without empty quotes."""
        inputs = {"appName": "Notes", "text": "Hello from Cortex.", "command": "type_text"}
        obs = Observation(
            target="desktop:type_text",
            state_data={"command": "type_text", "text_verified": True, "appName": "Notes", "text": "Hello from Cortex."},
        )
        res = ExecutionResult(step_id="s2", ok=True, message="Typed text into Notes", data={"verified": True})

        verif = self.desktop_tool.verify(inputs, obs, res)
        self.assertTrue(verif.verified)
        self.assertEqual(verif.evidence, "Verified text 'Hello from Cortex.' successfully entered into 'Notes'.")
        self.assertNotIn("''", verif.evidence)

    # ── Test 3: Missing Metadata Reported Honestly Without Fabrications ────
    def test_03_missing_metadata_reported_honestly(self) -> None:
        """3. When appName or text is missing, verification evidence reports honest generic terms without empty quotes."""
        # Open app with no app name
        inputs_no_app = {"command": "open_app"}
        obs_no_app = Observation(
            target="desktop:open_app",
            state_data={"command": "open_app", "app_running": True, "app_active": True},
        )
        res_no_app = ExecutionResult(step_id="s3", ok=True, message="App launched")
        verif_no_app = self.desktop_tool.verify(inputs_no_app, obs_no_app, res_no_app)
        self.assertTrue(verif_no_app.verified)
        self.assertEqual(verif_no_app.evidence, "Verified target application is running. In foreground.")
        self.assertNotIn("''", verif_no_app.evidence)

        # Type text with no text provided
        inputs_no_text = {"appName": "Notes", "command": "type_text"}
        obs_no_text = Observation(
            target="desktop:type_text",
            state_data={"command": "type_text", "text_verified": True},
        )
        res_no_text = ExecutionResult(step_id="s4", ok=True, message="Dispatched typing", data={"verified": True})
        verif_no_text = self.desktop_tool.verify(inputs_no_text, obs_no_text, res_no_text)
        self.assertTrue(verif_no_text.verified)
        self.assertEqual(verif_no_text.evidence, "Verified text successfully entered into 'Notes'.")
        self.assertNotIn("''", verif_no_text.evidence)

        # Type text failure with missing text
        obs_fail = Observation(
            target="desktop:type_text",
            state_data={"command": "type_text", "text_verified": False, "unverified": True},
        )
        verif_fail = self.desktop_tool.verify(inputs_no_text, obs_fail, res_no_text)
        self.assertFalse(verif_fail.verified)
        self.assertEqual(verif_fail.evidence, "Text verification failed: could not confirm that requested text was entered into 'Notes'.")
        self.assertNotIn("''", verif_fail.evidence)

    # ── Test 4: NotesAdapter Verification Handles Empty / Populated Text ───
    def test_04_notes_adapter_verify_action_honest_evidence(self) -> None:
        """4. NotesAdapter.verify_action outputs accurate text without empty quotes."""
        adapter = NotesAdapter(dry_run=False)

        # Verified text
        obs = AdapterObservation(
            target="app:Notes",
            state_data={"app_running": True, "app_active": True, "text_verified": True},
        )
        verif = adapter.verify_action("type_text", {"text": "Meeting Summary"}, obs)
        self.assertTrue(verif.verified)
        self.assertEqual(verif.evidence, "Verified text 'Meeting Summary' successfully entered into Notes.")
        self.assertNotIn("''", verif.evidence)

        # Missing text
        verif_no_txt = adapter.verify_action("type_text", {}, obs)
        self.assertTrue(verif_no_txt.verified)
        self.assertEqual(verif_no_txt.evidence, "Verified text successfully entered into Notes.")
        self.assertNotIn("''", verif_no_txt.evidence)

        # Failed verification
        obs_unverif = AdapterObservation(
            target="app:Notes",
            state_data={"app_running": True, "app_active": True, "text_verified": False, "unverified": True},
        )
        verif_unverif = adapter.verify_action("type_text", {}, obs_unverif)
        self.assertFalse(verif_unverif.verified)
        self.assertEqual(verif_unverif.evidence, "Text verification failed: could not confirm that requested text was entered into Notes.")
        self.assertNotIn("''", verif_unverif.evidence)

    # ── Test 5: Recovery Resolves Success Only After Positive Observation ───
    def test_05_recovery_resolves_success_only_with_positive_observation(self) -> None:
        """5. Recovery safely resolves as success when independent observation confirms side effect."""
        adapter = NotesAdapter(dry_run=True)
        # Seed simulated store with note
        adapter._simulated_store["Existing Note"] = {"title": "Existing Note", "body": "Already typed content."}

        # Independent observation finds the text present
        rec = adapter.recover("type_text", {"title": "Existing Note", "text": "Already typed content."}, "Text already present in Notes")
        self.assertFalse(rec.can_retry)
        self.assertEqual(rec.strategy, "resolve_as_success")
        self.assertIn("already present", rec.message)

    # ── Test 6: Uncertain Recovery Remains UNVERIFIED / Escalated ──────────
    def test_06_uncertain_recovery_escalates_and_remains_unverified(self) -> None:
        """6. Recovery refuses to convert uncertain operations into success without positive observation."""
        adapter = NotesAdapter(dry_run=True)
        # Note does not contain requested text and unverified flag is present
        rec = adapter.recover(
            "type_text",
            {"text": "Unverified missing content", "unverified": True},
            "Text already present in Notes",
        )
        self.assertFalse(rec.can_retry)
        self.assertEqual(rec.strategy, "escalate")
        self.assertIn("Cannot resolve as success", rec.message)

    # ── Test 7: ExecutionEngine Recovery Safety Guard ──────────────────────
    def test_07_execution_engine_recovery_guard_prevents_false_success(self) -> None:
        """7. ExecutionEngine refuses resolve_as_success if observation state lacks positive proof."""
        mock_tool = MagicMock()
        mock_tool.execute.return_value = ExecutionResult(step_id="step_1", ok=False, message="Simulated error")
        # Observation provides NO positive proof (unverified = True)
        mock_tool.observe.return_value = Observation(
            target="test",
            state_data={"unverified": True, "already_present": False, "text_verified": False},
        )
        mock_tool.verify.return_value = VerificationResult(verified=False, evidence="Unverified state")
        # Tool recover claims resolve_as_success despite lack of evidence
        mock_tool.recover.return_value = {"strategy": "resolve_as_success", "message": "Blind claim"}

        self.tool_registry.register_instance("mock_tool", mock_tool)

        task = Task(intent="Test recovery safety", command=TaskCommand.UNKNOWN)
        plan = Plan(
            goal="Test recovery safety",
            steps=[PlanStep(id="s1", action="dangerous action", tool="mock_tool", inputs={})],
            task_id=task.id,
        )

        res = self.engine.execute_plan(task, plan)
        # Must NOT be completed! Must be UNVERIFIED
        self.assertEqual(task.status, TaskStatus.UNVERIFIED)
        self.assertEqual(res.status, TaskStatus.UNVERIFIED)
        self.assertIn("could not verify intended side effect", task.error)

        # Audit trail must have step_unverified, not step_completed
        event_types = [e.type for e in task.audit_trail]
        self.assertIn("step_unverified", event_types)
        self.assertNotIn("step_completed", event_types)

    # ── Test 8: Cancelled Task Is Never Resolved As Success in Recovery ────
    def test_08_cancelled_task_never_resolved_during_recovery(self) -> None:
        """8. If task status is CANCELLED, recovery never resolves it as success."""
        mock_tool = MagicMock()
        mock_tool.execute.return_value = ExecutionResult(step_id="step_1", ok=False, message="Error")
        mock_tool.observe.return_value = Observation(target="test", state_data={"text_verified": True, "already_present": True})
        mock_tool.verify.return_value = VerificationResult(verified=False, evidence="Failed")
        mock_tool.recover.return_value = {"strategy": "resolve_as_success", "message": "Would resolve"}

        self.tool_registry.register_instance("cancelling_tool", mock_tool)

        task = Task(intent="Test cancellation", command=TaskCommand.UNKNOWN)
        plan = Plan(
            goal="Test cancellation",
            steps=[PlanStep(id="s1", action="action", tool="cancelling_tool", inputs={})],
            task_id=task.id,
        )

        def cancel_on_progress(stage: str, msg: str) -> None:
            if stage == "recovering":
                task.status = TaskStatus.CANCELLED

        res = self.engine.execute_plan(task, plan, on_progress=cancel_on_progress)
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertEqual(res.status, TaskStatus.CANCELLED)

    # ── Test 9: End-to-End Audit Events Contain Structured Metadata ────────
    def test_09_end_to_end_audit_events_contain_structured_metadata(self) -> None:
        """9. ExecutionEngine records structured metadata (appName, action, text, verified) on step_verified."""
        task = Task(intent="Open Notes and type Hello", command=TaskCommand.UNKNOWN)
        plan = Plan(
            goal="Open Notes and type Hello",
            steps=[
                PlanStep(
                    id="s1",
                    action="Open Notes",
                    tool="desktop_tool",
                    inputs={"appName": "Notes", "command": TaskCommand.OPEN_APP},
                    command=TaskCommand.OPEN_APP,
                ),
                PlanStep(
                    id="s2",
                    action="Type Hello",
                    tool="desktop_tool",
                    inputs={"appName": "Notes", "text": "Hello from Cortex.", "command": TaskCommand.TYPE_TEXT},
                    command=TaskCommand.TYPE_TEXT,
                ),
            ],
            task_id=task.id,
        )

        res = self.engine.execute_plan(task, plan)
        self.assertEqual(task.status, TaskStatus.COMPLETED)

        verified_events = [e for e in task.audit_trail if e.type == "step_verified"]
        self.assertEqual(len(verified_events), 2)

        # Step 1: Open Notes
        ev1 = verified_events[0]
        self.assertIn("Notes", ev1.message)
        self.assertNotIn("''", ev1.message)
        self.assertEqual(ev1.data.get("appName"), "Notes")
        self.assertEqual(ev1.data.get("action"), "open_app")
        self.assertTrue(ev1.data.get("verified"))

        # Step 2: Type Hello
        ev2 = verified_events[1]
        self.assertIn("Hello from Cortex.", ev2.message)
        self.assertIn("Notes", ev2.message)
        self.assertNotIn("''", ev2.message)
        self.assertEqual(ev2.data.get("appName"), "Notes")
        self.assertEqual(ev2.data.get("action"), "type_text")
        self.assertEqual(ev2.data.get("text"), "Hello from Cortex.")
        self.assertTrue(ev2.data.get("verified"))


if __name__ == "__main__":
    unittest.main()
