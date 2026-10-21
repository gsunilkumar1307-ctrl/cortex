import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation
from cortex_memory import EncryptedMemoryStore
from cortex_sdk import TaskCommand
from orchestrator import CortexOrchestrator


class Phase4BrowserAndVisionTests(unittest.TestCase):
    def make_orchestrator(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(tmp.name) / "memory.sqlite3"))
        return CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=False)

    def test_open_url_command(self):
        orchestrator = self.make_orchestrator()
        with patch.object(orchestrator.automation, "_browser_open_url", return_value=MagicMock(ok=True, message="Opened URL", data={"url": "https://example.com"})):
            response = orchestrator.chat("open url https://example.com")
            self.assertEqual(response["task"]["command"], "open_url")
            self.assertEqual(response["task"]["params"]["url"], "https://example.com")
            self.assertEqual(response["task"]["status"], "completed")

    def test_screen_vision_command(self):
        orchestrator = self.make_orchestrator()
        with patch.object(orchestrator.automation, "_screen_vision", return_value=MagicMock(ok=True, message="I see a desktop with code open", data={})):
            response = orchestrator.chat("what is on my screen right now?")
            self.assertEqual(response["task"]["command"], "screen_vision")
            self.assertEqual(response["task"]["status"], "completed")

    def test_browser_scrape_command(self):
        orchestrator = self.make_orchestrator()
        with patch.object(orchestrator.automation, "_browser_scrape", return_value=MagicMock(ok=True, message="Page content", data={})):
            response = orchestrator.chat("scrape web https://example.com")
            self.assertEqual(response["task"]["command"], "browser_scrape")
            self.assertEqual(response["task"]["params"]["url"], "https://example.com")
            self.assertEqual(response["task"]["status"], "completed")

    def test_browser_click_requires_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("click on web button#submit")
        self.assertEqual(response["task"]["command"], "browser_click")
        self.assertEqual(response["task"]["status"], "waiting_approval")
        self.assertTrue(response["task"]["requiresApproval"])

    def test_browser_type_requires_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("type in browser search query")
        self.assertEqual(response["task"]["command"], "browser_type")
        self.assertEqual(response["task"]["status"], "waiting_approval")
        self.assertTrue(response["task"]["requiresApproval"])


if __name__ == "__main__":
    unittest.main()
