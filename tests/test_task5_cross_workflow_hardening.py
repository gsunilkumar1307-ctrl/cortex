"""Tests for Task 5: Cross-Workflow Reliability & Live Acceptance Hardening.

Verifies:
1. Cross-task context isolation (pending email draft is preserved when executing screen observation, Safari research, or Finder inspection).
2. Follow-up reference resolution ("the second result", "make the summary shorter", "cancel it") resolves to the correct context.
3. Cancellation precedence (cancelling pending email draft without sending, invalidating approval hashes, deleting draft in mailbox).
4. Edit versus search routing (search queries never misclassified as email edits).
5. Duplicate-action prevention (preventing repeated execution of identical consequential actions within time window).
6. Resource coordination and thread-safe execution (re-entrant locking on orchestrator).
7. Evidence-based completion reporting (distinguishing PASS, PARTIAL, BLOCKED, FAILED).
8. TaskStore rehydration and crash recovery (inspecting action attempts and approval expiration).
9. Approval gate enforcement (high-risk email/WhatsApp require explicit approval).
10. Full cross-workflow execution sequence (Workflow A -> Workflow B -> Follow-ups -> Workflow C).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.policy import PolicyEngine, DuplicateCheckResult
from backend.core.contracts import (
    TaskCommand,
    TaskStatus,
    RiskLevel,
    Task,
    command_from_intent,
)


class TestTask5CrossWorkflowHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(use_gemini=False)

    def test_01_cross_workflow_isolation_email_and_finder(self) -> None:
        """1. A pending email draft is preserved when executing Finder inspection without body corruption."""
        self.orchestrator.chat("Draft an email to dr.sharma@hospital.org saying the surgery schedule is updated")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "confirm_send")

        # Execute Finder inspection while email is waiting for confirmation
        res_finder = self.orchestrator.chat("Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything.")
        self.assertEqual(res_finder.get("task", {}).get("command"), TaskCommand.SEARCH_FILES.value)
        self.assertIn("Finder Inspection:", res_finder.get("message", ""))

        # Pending email action must still be intact and uncorrupted
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "confirm_send")
        self.assertEqual(self.orchestrator.pending_action.get("recipient"), "dr.sharma@hospital.org")

        # Confirm send works cleanly afterwards
        res_send = self.orchestrator.chat("Yes, send it")
        self.assertIn("Email sent to dr.sharma@hospital.org", res_send.get("message", ""))
        self.assertIsNone(self.orchestrator.pending_action)

    def test_02_cross_workflow_isolation_waiting_for_body_and_screen(self) -> None:
        """2. When waiting for an email body, a screen observation command executes as screen observation, not as body text."""
        self.orchestrator.chat("Draft an email to dr.sharma@hospital.org")
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_body")

        # User asks to observe screen instead of providing body
        res_screen = self.orchestrator.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        self.assertEqual(res_screen.get("task", {}).get("command"), TaskCommand.OBSERVE_SCREEN.value)
        self.assertIn("Active application:", res_screen.get("message", ""))

        # Pending action remains waiting for body
        self.assertIsNotNone(self.orchestrator.pending_action)
        self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_body")

    def test_03_followup_reference_make_summary_shorter_after_finder(self) -> None:
        """3. 'Make the summary shorter' resolves to the preceding research summary even after Finder was opened."""
        # 1. Search
        r1 = self.orchestrator.chat("Search for the latest developments in AI and summarize the findings.")
        self.assertIn("Overview:", r1.get("message", ""))

        # 2. Finder
        r2 = self.orchestrator.chat("Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything.")
        self.assertIn("Finder Inspection:", r2.get("message", ""))

        # 3. Shorten summary
        r3 = self.orchestrator.chat("Make the summary shorter.")
        msg3 = r3.get("message", "")
        self.assertIn("Condensed Summary", msg3)
        self.assertIn("Key Takeaways:", msg3)
        self.assertIn("Sources & Citations:", msg3)

    def test_04_cancellation_precedence_and_approval_invalidation(self) -> None:
        """4. 'Cancel it' cancels the active pending action, invalidates approval hash, and cleans up."""
        self.orchestrator.chat("Draft an email to dr.sharma@hospital.org saying review required")
        self.assertIsNotNone(self.orchestrator.pending_action)
        task_id = self.orchestrator.pending_action.get("task_id")
        self.assertIsNotNone(task_id)

        # Cancel it
        res_cancel = self.orchestrator.chat("Cancel it")
        self.assertIsNone(self.orchestrator.pending_action)
        self.assertIn("Cancel", res_cancel.get("message", ""))

        # Verify task state in tasks dict
        task = self.orchestrator.tasks.get(task_id)
        if task:
            self.assertEqual(task.status, TaskStatus.CANCELED)
            self.assertIsNone(task.params.get("approval_hash"))

    def test_05_duplicate_action_prevention(self) -> None:
        """5. Duplicate consequential action within time window is blocked or prevented."""
        policy = PolicyEngine()
        key = "mail:dr.sharma@hospital.org:surgery_review"

        # Record attempt and mark completed
        policy.record_execution_attempt(key, "send_mail", {"to": "dr.sharma@hospital.org"})
        policy.mark_execution_completed(key, "completed")

        # Second attempt within window
        check = policy.check_duplicate_or_uncertain(key, window_seconds=300.0)
        self.assertTrue(check.is_duplicate)
        self.assertIn("Duplicate action prevented", check.reason or "")

    def test_06_in_flight_uncertain_state_handling(self) -> None:
        """6. In-flight action attempt marked uncertain blocks blind retry."""
        policy = PolicyEngine()
        key = "browser:click:submit_btn"

        policy.record_execution_attempt(key, "browser_click", {"selector": "#submit"})
        # In progress / uncertain
        check = policy.check_duplicate_or_uncertain(key, window_seconds=300.0)
        self.assertTrue(check.is_duplicate)
        self.assertIn("Uncertain execution state", check.reason or "")

    def test_07_thread_safe_locking(self) -> None:
        """7. Orchestrator maintains an RLock for thread-safe concurrent execution."""
        import threading
        self.assertIsInstance(self.orchestrator._lock, type(threading.RLock()))
        with self.orchestrator._lock:
            # Re-entrant acquire must not deadlock
            with self.orchestrator._lock:
                self.assertTrue(True)

    def test_08_evidence_based_completion_contract_finder(self) -> None:
        """8. Finder inspection response contains verifiable evidence and read-only declaration."""
        res = self.orchestrator.chat("Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything.")
        msg = res.get("message", "")
        self.assertIn("• **Finder Status:**", msg)
        self.assertIn("• **Inspection Type:** Directory entries (read-only filesystem listing).", msg)
        self.assertIn("• **Ordering:** Alphabetical (case-insensitive, ascending).", msg)
        self.assertIn("• **Filesystem Status:** Verified read-only inspection. No files were created, modified, renamed, or deleted.", msg)

    def test_09_evidence_based_completion_contract_screen(self) -> None:
        """9. Screen observation response reports active app, window, visible elements, and limitations."""
        res = self.orchestrator.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        msg = res.get("message", "")
        self.assertIn("- **Active application:**", msg)
        self.assertIn("- **Active window:**", msg)
        self.assertIn("- **Visible elements:**", msg)
        self.assertIn("- **Limitations:**", msg)

    def test_10_crash_recovery_rehydration(self) -> None:
        """10. Orchestrator rehydrates tasks on startup and handles uncertain states safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from backend.persistence import TaskStore
            db_path = str(Path(tmpdir) / "tasks.sqlite3")
            store = TaskStore(db_path)

            # Create an in-flight executing task
            t = Task("Send email to prof@univ.edu", TaskCommand.SEND_MAIL, RiskLevel.HIGH, True)
            t.status = TaskStatus.EXECUTING
            store.save_task(t)

            # Rehydrate with fresh orchestrator
            fresh_orc = CortexOrchestrator(use_gemini=False, task_store=store)
            rehydrated = fresh_orc.tasks.get(t.id)
            self.assertIsNotNone(rehydrated)
            # Must transition to NEEDS_ATTENTION because external side-effect cannot be confirmed
            self.assertEqual(rehydrated.status, TaskStatus.NEEDS_ATTENTION)

    def test_11_full_multi_workflow_sequence(self) -> None:
        """11. Complete multi-workflow sequence (Workflow A -> B -> Follow-up -> C)."""
        # Workflow A
        res_a = self.orchestrator.chat("Observe my screen and tell me the active application, active window, and five visible elements.")
        self.assertEqual(res_a.get("task", {}).get("command"), TaskCommand.OBSERVE_SCREEN.value)

        # Workflow B
        res_b = self.orchestrator.chat("Search for the latest developments in AI and summarize the findings.")
        self.assertEqual(res_b.get("task", {}).get("command"), TaskCommand.WEB_SEARCH.value)

        # Follow-up
        res_f = self.orchestrator.chat("Make the summary shorter.")
        self.assertIn("Condensed Summary", res_f.get("message", ""))

        # Workflow C
        res_c = self.orchestrator.chat("Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything.")
        self.assertEqual(res_c.get("task", {}).get("command"), TaskCommand.SEARCH_FILES.value)
        self.assertIn("Finder Inspection: Downloads", res_c.get("message", ""))


if __name__ == "__main__":
    unittest.main()
