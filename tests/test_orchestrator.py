import tempfile
import unittest
import unittest.mock
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation
from cortex_memory import EncryptedMemoryStore
from orchestrator import CortexOrchestrator


class OrchestratorTests(unittest.TestCase):
    def make_orchestrator(self, use_gemini=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(tmp.name) / "memory.sqlite3"))
        return CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=use_gemini)

    def test_safe_action_executes_without_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("open calculator")
        self.assertEqual(response["task"]["status"], "completed")
        self.assertFalse(response["task"]["requiresApproval"])

    def test_sensitive_action_waits_for_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("restart my computer")
        task = response["task"]
        self.assertEqual(task["status"], "waiting_approval")
        self.assertTrue(task["requiresApproval"])

        approved = orchestrator.approve(task["id"], True)
        self.assertEqual(approved["status"], "completed")

    def test_close_app_executes_without_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("close Calculator")
        self.assertEqual(response["task"]["command"], "close_app")
        self.assertEqual(response["task"]["params"], {"appName": "Calculator"})
        self.assertEqual(response["task"]["status"], "completed")
        self.assertFalse(response["task"]["requiresApproval"])

    def test_focus_app_executes_without_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("switch to Notes")
        self.assertEqual(response["task"]["command"], "focus_app")
        self.assertEqual(response["task"]["params"], {"appName": "Notes"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_type_text_into_app(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("type hello world in Notes")
        self.assertEqual(response["task"]["command"], "type_text")
        self.assertEqual(response["task"]["params"], {"text": "hello world", "appName": "Notes"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_press_shortcut_in_app(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("press command s in Notes")
        self.assertEqual(response["task"]["command"], "keystroke")
        self.assertEqual(response["task"]["params"], {"shortcut": "command s", "appName": "Notes"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_choose_menu_item_in_app(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("choose New from File menu in Notes")
        self.assertEqual(response["task"]["command"], "menu_item")
        self.assertEqual(response["task"]["params"], {"item": "New", "menu": "File", "appName": "Notes"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_calculate_executes_without_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("calculate 9 times 8")
        self.assertEqual(response["task"]["command"], "calculate")
        self.assertEqual(response["task"]["params"], {"expression": "9 times 8"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_write_note_executes_without_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("write note called Groceries saying buy milk")
        self.assertEqual(response["task"]["command"], "write_note")
        self.assertEqual(response["task"]["params"], {"title": "Groceries", "body": "buy milk"})
        self.assertEqual(response["task"]["status"], "completed")

    def test_send_message_requires_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("send message to Sam saying hello")
        self.assertEqual(response["task"]["command"], "send_message")
        self.assertEqual(response["task"]["params"], {"recipient": "Sam", "body": "hello"})
        self.assertEqual(response["task"]["status"], "waiting_approval")
        self.assertTrue(response["task"]["requiresApproval"])

    def test_cancel_pending_action(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("restart my computer")
        canceled = orchestrator.cancel(response["task"]["id"])
        self.assertEqual(canceled["status"], "canceled")

    def test_open_then_close_sequence(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("open Calculator then close Calculator")
        task = response["task"]
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["result"], "Sequence completed.")
        self.assertEqual(task["params"], {"sequence": ["open Calculator", "close Calculator"]})

    def test_sequence_pauses_for_sensitive_action(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("open Calculator then restart my computer")
        task = response["task"]
        self.assertEqual(task["status"], "waiting_approval")
        self.assertTrue(task["requiresApproval"])

    def test_ask_question_fallback(self):
        orchestrator = self.make_orchestrator()
        # Ensure we test fallback parsing for questions
        response = orchestrator.chat("who is Jarvis?")
        self.assertEqual(response["task"]["command"], "ask_question")
        self.assertEqual(response["task"]["status"], "completed")

    def test_ask_question_gemini(self):
        import unittest.mock
        import os
        
        # We need to mock GenerativeModel and configure in google.generativeai
        with unittest.mock.patch("google.generativeai.GenerativeModel") as mock_model_class, \
             unittest.mock.patch("google.generativeai.configure") as mock_configure:
            
            mock_model = mock_model_class.return_value
            mock_response = unittest.mock.MagicMock()
            mock_response.text = '{"command": "ask_question", "params": {}, "risk_level": "low", "requires_approval": false, "block_reason": null, "answer": "I am Cortex, a safety-first AI assistant."}'
            mock_model.generate_content.return_value = mock_response

            # Force HAS_GENAI to be True for testing
            import orchestrator
            old_has_genai = orchestrator.HAS_GENAI
            orchestrator.HAS_GENAI = True
            
            old_key = os.environ.get("GEMINI_API_KEY")
            os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
            try:
                orch = self.make_orchestrator(use_gemini=True)
                self.assertTrue(orch.use_gemini)
                response = orch.chat("who are you?")
                self.assertEqual(response["task"]["command"], "ask_question")
                self.assertEqual(response["task"]["status"], "completed")
                self.assertEqual(response["message"], "I am Cortex, a safety-first AI assistant.")
            finally:
                orchestrator.HAS_GENAI = old_has_genai
                if old_key is not None:
                    os.environ["GEMINI_API_KEY"] = old_key
                else:
                    os.environ.pop("GEMINI_API_KEY", None)

    def test_web_search_fallback(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("search the web for weather today")
        self.assertEqual(response["task"]["command"], "web_search")

    @unittest.mock.patch("orchestrator.search_web")
    def test_web_search_gemini(self, mock_search):
        import unittest.mock
        import os
        
        mock_search.return_value = [{"title": "Weather", "href": "http://weather", "body": "Sunny today in Chennai."}]
        
        with unittest.mock.patch("google.generativeai.GenerativeModel") as mock_model_class, \
             unittest.mock.patch("google.generativeai.configure") as mock_configure:
            
            mock_model = mock_model_class.return_value
            mock_response_1 = unittest.mock.MagicMock()
            mock_response_1.text = '{"command": "web_search", "params": {"query": "weather today"}, "risk_level": "low", "requires_approval": false, "block_reason": null, "answer": null}'
            
            mock_response_2 = unittest.mock.MagicMock()
            mock_response_2.text = "Cortex: Today the weather is sunny in Chennai."
            
            mock_model.generate_content.side_effect = [mock_response_1, mock_response_2]

            import orchestrator
            old_has_genai = orchestrator.HAS_GENAI
            orchestrator.HAS_GENAI = True
            
            old_key = os.environ.get("GEMINI_API_KEY")
            os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
            try:
                orch = self.make_orchestrator(use_gemini=True)
                self.assertTrue(orch.use_gemini)
                response = orch.chat("what's the weather today?")
                self.assertEqual(response["task"]["command"], "web_search")
                self.assertEqual(response["task"]["status"], "completed")
                self.assertEqual(response["message"], "Cortex: Today the weather is sunny in Chennai.")
            finally:
                orchestrator.HAS_GENAI = old_has_genai
                if old_key is not None:
                    os.environ["GEMINI_API_KEY"] = old_key
                else:
                    os.environ.pop("GEMINI_API_KEY", None)


if __name__ == "__main__":
    unittest.main()
