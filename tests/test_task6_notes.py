import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.core.contracts import TaskCommand, TaskStatus
from backend.persistence import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore


class Task6AppleNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        memory = EncryptedMemoryStore(db_path)
        # Use dry_run=False on macOS darwin to verify live Apple Notes capability,
        # with fallback to simulated store on non-darwin
        is_darwin = sys.platform == "darwin"
        self.device = DeviceAutomation(dry_run=not is_darwin)
        self.orch = CortexOrchestrator(self.device, memory, use_gemini=False)
        self.task_store = TaskStore(db_path)
        self.orch.task_store = self.task_store

        # Clean up any preexisting test notes
        if is_darwin:
            import subprocess
            for t in ("Test Project Meeting", "Project Meeting", "Meeting"):
                subprocess.run(
                    ["osascript", "-e", f'tell application "Notes" to delete (every note whose name is "{t}")'],
                    capture_output=True,
                )

    def tearDown(self):
        if sys.platform == "darwin":
            import subprocess
            for t in ("Test Project Meeting", "Project Meeting", "Meeting"):
                subprocess.run(
                    ["osascript", "-e", f'tell application "Notes" to delete (every note whose name is "{t}")'],
                    capture_output=True,
                )

    def test_01_create_note_strips_conversational_wrappers(self):
        """1. Extract the actual title and content accurately.
        2. Strip conversational wrappers ('with the following content:', etc.)
        3. Create the note and verify title and text.
        """
        res = self.orch.chat(
            "Create a note titled Project Meeting with the following content: Review Q3 milestones and allocate team resources."
        )
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(task["command"], TaskCommand.WRITE_NOTE.value)

        # Title and body correctly isolated
        self.assertEqual(task["params"]["title"], "Project Meeting")
        body = task["params"]["body"]
        self.assertNotIn("with the following content", body.lower())
        self.assertNotIn("the following content", body.lower())
        self.assertIn("Review Q3 milestones and allocate team resources", body)

        # Verification in store
        v = self.device.verify_note("Project Meeting")
        self.assertTrue(v.get("verified"))
        self.assertIn("Review Q3 milestones", v.get("body", ""))

    def test_02_follow_up_make_title_shorter(self):
        """5a. 'Make the title shorter' -> Rename the note appropriately."""
        res1 = self.orch.chat(
            "Create a note titled Project Meeting with the following content: Review Q3 milestones."
        )
        self.assertEqual(res1["task"]["status"], TaskStatus.COMPLETED.value)

        res2 = self.orch.chat("Make the title shorter")
        self.assertEqual(res2["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res2["task"]["params"]["action"], "shorten_title")
        self.assertIn("Meeting", res2["message"])

        # Check updated note exists under shortened name
        v = self.device.verify_note("Meeting")
        self.assertTrue(v.get("verified"))

    def test_03_follow_up_add_point_to_existing_note(self):
        """5b. 'Add this point: Action item for Rahul' -> Append to the existing note, not create a new one."""
        self.orch.chat(
            "Create a note titled Project Meeting with the following content: Initial discussion."
        )

        res = self.orch.chat("Add this point: Action item for Rahul")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res["task"]["params"]["action"], "append_note")
        self.assertIn("Action item for Rahul", res["message"])

        # Verify content contains both initial text and appended point
        v = self.device.verify_note("Project Meeting")
        self.assertTrue(v.get("verified"))
        self.assertIn("Initial discussion", v.get("body", ""))
        self.assertIn("Action item for Rahul", v.get("body", ""))

    def test_04_follow_up_open_note(self):
        """5c. 'Open that note' -> Open/bring the note to the front."""
        self.orch.chat(
            "Create a note titled Project Meeting with the following content: Discussion notes."
        )

        res = self.orch.chat("Open that note")
        self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res["task"]["params"]["action"], "open_note")
        self.assertIn("Project Meeting", res["message"])

    def test_05_duplicate_prevention(self):
        """6. Subsequent operations must target the note already created, not create new duplicate notes."""
        self.orch.chat(
            "Create a note titled Project Meeting with the following content: Discussion notes."
        )
        # Append two points in succession
        self.orch.chat("Add this point: Point one")
        self.orch.chat("Add this point: Point two")

        if sys.platform == "darwin":
            import subprocess
            out = subprocess.run(
                ["osascript", "-e", 'tell application "Notes" to count (every note whose name is "Project Meeting")'],
                capture_output=True,
                text=True,
            )
            count = int(out.stdout.strip())
            # Exactly one note with this name must exist
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()

