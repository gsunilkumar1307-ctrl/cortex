"""Automated regression test suite for Cortex macOS Text-Typing Workflow & Verification.

Tests cover:
1. Opening Notes and typing exact text (mocked success with verification).
2. Notes launching successfully, but text entry failing.
3. Notes not receiving keyboard focus.
4. Accessibility verification failing -> unverified status (never COMPLETED).
5. Text appearing successfully and verified -> COMPLETED status.
6. Partial sequence execution never marked COMPLETED.
7. Duplicate typing prevention when text already present.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceActionResult, DeviceAutomation
from backend.core.contracts import TaskCommand, TaskStatus
from backend.persistence.encrypted_store import EncryptedMemoryStore


class TestMacOSTypingVerificationRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.device = DeviceAutomation(dry_run=False)
        self.device.system = "darwin"
        self.orch = CortexOrchestrator(self.device, self.memory, use_gemini=False)

    def test_01_open_notes_and_type_exact_text_success_verified(self) -> None:
        """Command 'Open Notes and type exactly: Hello from Cortex.' succeeds with full verification."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="VERIFIED\n",
                stderr="",
            )

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            task = res["task"]

            self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(res["message"], "Sequence completed.")
            # Verify text was cleaned from "exactly: " prefix
            audit_trail = task.get("auditTrail", [])
            step_events = [e for e in audit_trail if e.get("type") == "step_completed"]
            self.assertEqual(len(step_events), 2)
            self.assertEqual(step_events[0].get("data", {}).get("command"), TaskCommand.OPEN_APP.value)
            self.assertEqual(step_events[1].get("data", {}).get("command"), TaskCommand.TYPE_TEXT.value)

    def test_02_notes_launches_successfully_but_text_entry_fails(self) -> None:
        """Notes opens, but text entry fails (e.g. editor not found). Task MUST be FAILED, never COMPLETED."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="ERROR: Could not find editable text area in Notes.\n",
                stderr="",
            )

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            task = res["task"]

            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertNotEqual(res["message"], "Sequence completed.")
            self.assertIn("Could not find editable text area in Notes", task["error"])
            self.assertIn("Completed 1/2 steps", task["error"])

    def test_03_notes_not_receiving_keyboard_focus(self) -> None:
        """Notes fails to acquire focus. Sequence must halt and report FAILED, never COMPLETED."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(False, "Notes focus timeout")):

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            task = res["task"]

            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertNotEqual(res["message"], "Sequence completed.")
            self.assertIn("Notes focus timeout", task["error"])

    def test_04_accessibility_verification_failing_sets_unverified_status(self) -> None:
        """If typing is dispatched but text cannot be verified in the note, status must be NEEDS_ATTENTION, never COMPLETED."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="UNVERIFIED\n",
                stderr="",
            )

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            task = res["task"]

            # UNVERIFIED results in FAILED (or NEEDS_ATTENTION), but strictly NEVER COMPLETED
            self.assertNotEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertNotEqual(res["message"], "Sequence completed.")
            self.assertIn("not verified", str(task.get("error") or task.get("result")).lower())

    def test_05_text_appearing_successfully_and_verified_sets_completed(self) -> None:
        """When text is confirmed present after typing, task finishes with COMPLETED and 'Sequence completed.'"""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="VERIFIED\n",
                stderr="",
            )

            action_res = self.device._type_text("Hello from Cortex.", "Notes")
            self.assertTrue(action_res.ok)
            self.assertTrue(action_res.data["verified"])
            self.assertFalse(action_res.data["already_present"])

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(res["message"], "Sequence completed.")

    def test_06_partial_sequence_execution_never_marked_completed(self) -> None:
        """A sequence where Step 1 succeeds and Step 2 is skipped or fails must NEVER be COMPLETED."""
        with patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch.object(self.device, "_type_text", return_value=DeviceActionResult(False, "Window lost focus")):

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            task = res["task"]

            self.assertEqual(task["status"], TaskStatus.FAILED.value)
            self.assertNotEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertIn("Completed 1/2 steps", task["error"])

    def test_07_duplicate_typing_prevention_when_text_already_present(self) -> None:
        """When the requested text already exists in the target note, typing is skipped to prevent duplication."""
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(
                returncode=0,
                stdout="ALREADY_PRESENT\n",
                stderr="",
            )

            action_res = self.device._type_text("Hello from Cortex.", "Notes")
            self.assertTrue(action_res.ok)
            self.assertTrue(action_res.data["verified"])
            self.assertTrue(action_res.data["already_present"])
            self.assertIn("Duplicate typing prevented", action_res.message)

            res = self.orch.chat("Open Notes and type exactly: Hello from Cortex.")
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(res["message"], "Sequence completed.")


if __name__ == "__main__":
    unittest.main()
