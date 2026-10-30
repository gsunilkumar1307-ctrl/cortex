import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.capabilities import DeviceAutomation
from backend.capabilities.device_actions import APP_ALIASES
from backend.core.contracts import TaskCommand, TaskStatus
from backend.persistence import EncryptedMemoryStore
from backend.agent import CortexOrchestrator


class DesktopOperatorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        self.memory = EncryptedMemoryStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(self.device, self.memory, use_gemini=False)

    def test_app_alias_resolution(self):
        """Verifies recognizable aliases map to canonical application names."""
        self.assertEqual(self.device.resolve_app_name("chrome"), "Google Chrome")
        self.assertEqual(self.device.resolve_app_name("google chrome"), "Google Chrome")
        self.assertEqual(self.device.resolve_app_name("vscode"), "Visual Studio Code")
        self.assertEqual(self.device.resolve_app_name("code"), "Visual Studio Code")
        self.assertEqual(self.device.resolve_app_name("calc"), "Calculator")
        self.assertEqual(self.device.resolve_app_name("calculator"), "Calculator")
        self.assertEqual(self.device.resolve_app_name("notes"), "Notes")
        self.assertEqual(self.device.resolve_app_name("safari"), "Safari")
        self.assertEqual(self.device.resolve_app_name("whatsapp"), "WhatsApp")

    def test_open_app_command_dispatch(self):
        """'open chrome' routes to OPEN_APP with canonical appName."""
        res = self.orch.chat("open chrome")
        task = res["task"]
        self.assertEqual(task["command"], TaskCommand.OPEN_APP.value)
        self.assertEqual(task["status"], TaskStatus.COMPLETED.value)

    def test_close_window_vs_quit_app_distinction(self):
        """Close window maps to CLOSE_WINDOW, whereas quit notes maps to CLOSE_APP."""
        res_win = self.orch.chat("close window")
        self.assertEqual(res_win["task"]["command"], TaskCommand.CLOSE_WINDOW.value)
        self.assertEqual(res_win["task"]["status"], TaskStatus.COMPLETED.value)

        res_quit = self.orch.chat("quit Notes")
        self.assertEqual(res_quit["task"]["command"], TaskCommand.CLOSE_APP.value)
        self.assertEqual(res_quit["task"]["status"], TaskStatus.COMPLETED.value)

    def test_inspect_application_state(self):
        """'inspect app Notes' inspects whether application is running and returns structured state."""
        res = self.device.execute(TaskCommand.INSPECT_APP, {"appName": "notes"})
        self.assertTrue(res.ok)
        self.assertEqual(res.data.get("appName"), "Notes")
        self.assertIn("isRunning", res.data)

    def test_create_document_and_move_file_in_sandbox(self):
        """Safely creates a markdown document and moves it within the permitted sandbox."""
        sandbox_dir = Path.home() / "Documents" / "Cortex_Operator_Test"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        doc_path = sandbox_dir / "report.md"
        target_path = sandbox_dir / "final_report.md"

        try:
            # Create document
            create_res = self.device.execute(TaskCommand.CREATE_DOCUMENT, {
                "path": str(doc_path),
                "title": "Quarterly Review",
                "content": "All milestones achieved on schedule.",
            })
            self.assertTrue(create_res.ok)
            self.assertTrue(doc_path.exists())
            self.assertIn("Quarterly Review", doc_path.read_text(encoding="utf-8"))

            # Move file
            move_res = self.device.execute(TaskCommand.MOVE_FILE, {
                "source": str(doc_path),
                "destination": str(target_path),
            })
            self.assertTrue(move_res.ok)
            self.assertFalse(doc_path.exists())
            self.assertTrue(target_path.exists())
            self.assertIn("Quarterly Review", target_path.read_text(encoding="utf-8"))
        finally:
            if doc_path.exists():
                doc_path.unlink()
            if target_path.exists():
                target_path.unlink()
            if sandbox_dir.exists():
                try:
                    sandbox_dir.rmdir()
                except Exception:
                    pass

    def test_sandbox_security_traversal_denied(self):
        """File operations attempting system traversal outside permitted sandbox are rejected."""
        res = self.device.execute(TaskCommand.MOVE_FILE, {
            "source": "/etc/passwd",
            "destination": "/tmp/stolen_passwd",
        })
        self.assertFalse(res.ok)
        self.assertIn("denied", res.message.lower())


if __name__ == "__main__":
    unittest.main()

