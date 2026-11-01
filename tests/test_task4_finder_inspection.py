"""Tests for Task 4: Verified Finder Inspection.

Verifies:
1. Correct Downloads path resolution using actual home directory.
2. Directory containing more than five entries (displays first 5).
3. Directory containing fewer than five entries (honest count, no fabrication).
4. Empty directory (honest reporting of 0 files).
5. Missing directory handling.
6. Permission denied handling.
7. Non-ASCII and multilingual filenames.
8. Stable, explicitly defined ordering (case-insensitive alphabetical).
9. Finder activation failure handled separately from filesystem listing.
10. Honest distinction between filesystem entries and UI-visible items.
11. Strict read-only behavior (no files created, modified, renamed, or deleted).
12. Path traversal security protection.
13. Kannada and Hindi multilingual/code-switched Finder queries.
14. Live macOS Finder acceptance.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation
from backend.core.contracts import TaskCommand, TaskStatus, command_from_intent


class TestTask4FinderInspection(unittest.TestCase):
    def setUp(self) -> None:
        self.orchestrator = CortexOrchestrator(use_gemini=False)
        self.automation = DeviceAutomation()

    def test_01_downloads_path_resolution(self) -> None:
        """1. Correct Downloads path resolution using Path.home()."""
        res = self.automation._search_files(directory="Downloads", limit=5)
        expected_dir = str(Path.home() / "Downloads")
        self.assertEqual(res.data.get("directory"), expected_dir)

        # Case-insensitive resolution
        res_lower = self.automation._search_files(directory="downloads", limit=5)
        self.assertEqual(res_lower.data.get("directory"), expected_dir)

        res_tilde = self.automation._search_files(directory="~/Downloads", limit=5)
        self.assertEqual(res_tilde.data.get("directory"), expected_dir)

    def test_02_directory_containing_more_than_five_entries(self) -> None:
        """2. Directory containing >5 entries displays exactly first 5 and reports total."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            filenames = [f"file_{i:02d}.txt" for i in range(1, 9)]  # 8 files
            for f in filenames:
                (tmppath / f).write_text(f"content {f}", encoding="utf-8")

            res = self.automation._search_files(directory=str(tmppath), limit=5)
            self.assertTrue(res.ok)
            self.assertEqual(res.data["displayed_count"], 5)
            self.assertEqual(res.data["count"], 8)
            self.assertEqual(len(res.data["names"]), 5)
            self.assertEqual(res.data["names"], filenames[:5])
            self.assertIn("First 5 of 8", res.message)
            self.assertIn("file_01.txt", res.message)
            self.assertIn("file_05.txt", res.message)
            self.assertNotIn("file_06.txt", res.message)

    def test_03_directory_containing_fewer_than_five_entries(self) -> None:
        """3. Directory with <5 entries displays only available files without fabricating entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "alpha.txt").write_text("a", encoding="utf-8")
            (tmppath / "beta.pdf").write_text("b", encoding="utf-8")

            res = self.automation._search_files(directory=str(tmppath), limit=5)
            self.assertTrue(res.ok)
            self.assertEqual(res.data["displayed_count"], 2)
            self.assertEqual(res.data["count"], 2)
            self.assertEqual(res.data["names"], ["alpha.txt", "beta.pdf"])
            self.assertIn("First 2 entries", res.message)
            self.assertIn("1. `alpha.txt`", res.message)
            self.assertIn("2. `beta.pdf`", res.message)
            self.assertNotIn("3.", res.message)

    def test_04_empty_directory(self) -> None:
        """4. Empty directory reports 0 files and honest empty state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            res = self.automation._search_files(directory=str(tmpdir), limit=5)
            self.assertTrue(res.ok)
            self.assertEqual(res.data["displayed_count"], 0)
            self.assertEqual(res.data["count"], 0)
            self.assertEqual(res.data["names"], [])
            self.assertIn("0 entries found (directory is empty)", res.message)
            self.assertIn("contains no visible files", res.message)

    def test_05_missing_directory(self) -> None:
        """5. Missing directory is handled with an honest, specific error."""
        non_existent = Path(tempfile.gettempdir()) / "non_existent_cortex_folder_xyz123"
        res = self.automation._search_files(directory=str(non_existent), limit=5)
        self.assertFalse(res.ok)
        self.assertEqual(res.data.get("error"), "DirectoryNotFound")
        self.assertIn("Directory not found", res.message)

    def test_06_permission_denied(self) -> None:
        """6. Permission denied is reported honestly without crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("os.scandir", side_effect=PermissionError("Permission denied")):
                res = self.automation._search_files(directory=str(tmpdir), limit=5)
                self.assertFalse(res.ok)
                self.assertEqual(res.data.get("error"), "PermissionDenied")
                self.assertIn("Permission denied", res.message)

    def test_07_non_ascii_and_multilingual_filenames(self) -> None:
        """7. Non-ASCII and multilingual filenames are listed accurately."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            files = ["ದಾಖಲೆ_2026.pdf", "ವಿವರಣೆ.txt", "रिपोर्ट_final.docx", "résumé.pdf", "alpha.txt"]
            for f in files:
                (tmppath / f).write_text("data", encoding="utf-8")

            res = self.automation._search_files(directory=str(tmppath), limit=5)
            self.assertTrue(res.ok)
            self.assertEqual(res.data["displayed_count"], 5)
            for f in files:
                self.assertIn(f, res.data["names"])
                self.assertIn(f, res.message)

    def test_08_stable_explicitly_defined_ordering(self) -> None:
        """8. Ordering is strictly deterministic (case-insensitive alphabetical) and stated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            names = ["z_file.txt", "A_file.txt", "b_file.txt", "1_number.txt", "M_middle.txt"]
            for n in names:
                (tmppath / n).write_text("x", encoding="utf-8")

            res = self.automation._search_files(directory=str(tmppath), limit=5)
            self.assertTrue(res.ok)
            expected_order = sorted(names, key=str.lower)
            self.assertEqual(res.data["names"], expected_order)
            self.assertIn("Alphabetical (case-insensitive, ascending)", res.message)
            self.assertEqual(res.data["ordering"], "Alphabetical (case-insensitive, ascending)")

    def test_09_finder_activation_failure_handled_separately(self) -> None:
        """9. Finder activation failure does not block read-only filesystem listing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "sample.txt").write_text("hello", encoding="utf-8")

            with patch("subprocess.run") as mock_run:
                # Simulate osascript failing
                mock_run.return_value = MagicMock(returncode=1, stderr="Finder not running")
                res = self.automation._search_files(directory=str(tmppath), limit=5, open_finder=True)
                self.assertTrue(res.ok)
                self.assertFalse(res.data["finder_navigated"])
                self.assertIn("Navigation failed or unavailable", res.message)
                self.assertIn("sample.txt", res.message)

    def test_10_distinction_between_filesystem_and_ui_visible(self) -> None:
        """10. Distinguishes between filesystem directory entries and UI-visible items."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "item1.txt").write_text("1", encoding="utf-8")

            res = self.automation._search_files(directory=str(tmpdir), limit=5)
            self.assertIn("• **Inspection Type:** Directory entries (read-only filesystem listing)", res.message)
            self.assertIn("• **Finder Window Verification:**", res.message)

    def test_11_no_filesystem_modifications(self) -> None:
        """11. Inspection makes zero filesystem modifications."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "original.txt").write_text("unchanged", encoding="utf-8")

            mtime_before = (tmppath / "original.txt").stat().st_mtime
            entries_before = sorted(os.listdir(tmpdir))

            res = self.automation._search_files(directory=str(tmpdir), limit=5, open_finder=False)
            self.assertTrue(res.ok)

            mtime_after = (tmppath / "original.txt").stat().st_mtime
            entries_after = sorted(os.listdir(tmpdir))

            self.assertEqual(entries_before, entries_after)
            self.assertEqual(mtime_before, mtime_after)
            self.assertTrue(res.data["read_only"])
            self.assertIn("Verified read-only inspection", res.message)

    def test_12_path_traversal_blocked(self) -> None:
        """12. Path traversal (e.g. '../..') and blocked system files are rejected."""
        res = self.automation._search_files(directory="../../etc", limit=5)
        self.assertFalse(res.ok)
        self.assertEqual(res.data.get("error"), "AccessBlocked")
        self.assertIn("Access blocked", res.message)

    def test_13_kannada_and_indic_finder_queries(self) -> None:
        """13. Kannada and Hindi Finder / Downloads inspection commands route correctly."""
        kn_cmd = command_from_intent("ಫೈಂಡರ್ ತೆರೆದು ಡೌನ್‌ಲೋಡ್ಸ್‌ನಲ್ಲಿ ಮೊದಲ ಐದು ಫೈಲ್‌ಗಳನ್ನು ತೋರಿಸು")
        self.assertEqual(kn_cmd, TaskCommand.SEARCH_FILES)

        hi_cmd = command_from_intent("Finder खोलें और Downloads में पहली पाँच फाइलें दिखाएं")
        self.assertEqual(hi_cmd, TaskCommand.SEARCH_FILES)

    def test_14_live_macos_acceptance(self) -> None:
        """14. Live acceptance of the exact user prompt on macOS."""
        user_prompt = "Open Finder, navigate to Downloads and show me the first five visible filenames. Do not modify anything."
        res = self.orchestrator.chat(user_prompt)

        task = res.get("task", {})
        self.assertEqual(task.get("command"), TaskCommand.SEARCH_FILES.value)
        self.assertEqual(task.get("status"), TaskStatus.COMPLETED.value)

        msg = res.get("message", "")
        self.assertIn("### Finder Inspection: Downloads", msg)
        self.assertIn("Alphabetical (case-insensitive, ascending)", msg)
        self.assertIn("Verified read-only inspection", msg)
        self.assertIn("Items displayed:", msg)

        # Check that reported items actually exist in ~/Downloads
        downloads_dir = Path.home() / "Downloads"
        if downloads_dir.exists():
            existing = [p.name for p in downloads_dir.iterdir() if not p.name.startswith(".")]
            existing.sort(key=str.lower)
            for top_name in existing[:5]:
                self.assertIn(top_name, msg)


if __name__ == "__main__":
    unittest.main()
