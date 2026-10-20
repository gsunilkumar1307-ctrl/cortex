import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation
from cortex_memory import EncryptedMemoryStore
from cortex_sdk import TaskCommand, TaskStatus
from orchestrator import CortexOrchestrator


class CommandContentSeparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=False)

    def test_send_mail_unknown_body_not_forwarded(self):
        """USER: 'Send mail to lamanimaruthi64@gmail.com'
        MUST interpret recipient, unknown body, and NOT put command into body.
        """
        prompt = "Send mail to lamanimaruthi64@gmail.com"
        res = self.orch.chat(prompt)
        task = res["task"]

        # Intent must be SEND_MAIL
        self.assertEqual(task["command"], TaskCommand.SEND_MAIL.value)
        # Recipient must be lamanimaruthi64@gmail.com
        self.assertEqual(task["params"]["recipient"], "lamanimaruthi64@gmail.com")
        # Body must NOT be the raw command
        self.assertNotEqual(task["params"].get("body"), prompt)
        self.assertEqual(task["params"].get("body", ""), "")

        # Must intelligently detect missing information and ask
        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        self.assertTrue(
            "what would you like" in res["message"].lower() or "send to" in res["message"].lower(),
            f"Expected prompt asking for email content, got: {res['message']}",
        )

    def test_natural_language_intent_extraction_with_content(self):
        """USER: 'Send an email to Rahul saying I'll be late.'
        Interpret as ACTION=SEND_MAIL, RECIPIENT=Rahul, BODY=I'll be late.
        """
        prompt = "Send an email to Rahul saying I'll be late."
        res = self.orch.chat(prompt)
        task = res["task"]

        self.assertEqual(task["command"], TaskCommand.SEND_MAIL.value)
        self.assertEqual(task["params"]["recipient"], "Rahul")
        self.assertEqual(task["params"]["body"], "I'll be late.")
        self.assertNotIn("Send an email to Rahul", task["params"]["body"])
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)

    def test_progressive_task_completion_multi_turn(self):
        """Multi-turn partial command flow:
        Turn 1: 'Send mail to Rahul.' -> Asks for content
        Turn 2: 'Tell him I'll reach by 8.' -> Creates draft, asks 'Should I send it?'
        Turn 3: 'Yes' -> Sends email
        """
        # Turn 1
        res1 = self.orch.chat("Send mail to Rahul.")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertEqual(res1["task"]["params"]["recipient"], "Rahul")
        self.assertEqual(res1["task"]["params"].get("body", ""), "")
        self.assertIn("Rahul", res1["message"])

        # Turn 2
        res2 = self.orch.chat("Tell him I'll reach by 8.")
        task2 = res2["task"]
        self.assertEqual(task2["command"], TaskCommand.SEND_MAIL.value)
        self.assertEqual(task2["params"]["recipient"], "Rahul")
        self.assertEqual(task2["params"]["body"], "I'll reach by 8.")
        self.assertEqual(task2["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertIn("Draft created", res2["message"])
        self.assertIn("Should I send it?", res2["message"])

        # Turn 3
        res3 = self.orch.chat("Yes")
        self.assertEqual(res3["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("Email sent to Rahul", res3["message"])

    def test_progressive_task_completion_project_ready(self):
        """User example:
        USER: 'Send mail to Rahul.'
        CORTEX: 'What would you like the email to say?'
        USER: 'Tell him the project is ready.'
        CORTEX: Draft created ... Should I send it?
        USER: 'Yes'
        """
        res1 = self.orch.chat("Send mail to Rahul.")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)

        res2 = self.orch.chat("Tell him the project is ready.")
        task2 = res2["task"]
        self.assertEqual(task2["params"]["recipient"], "Rahul")
        self.assertEqual(task2["params"]["body"], "The project is ready.")
        self.assertIn("Project update", task2["params"]["subject"])
        self.assertIn("Should I send it?", res2["message"])

        res3 = self.orch.chat("Yes")
        self.assertEqual(res3["task"]["status"], TaskStatus.COMPLETED.value)

    def test_progressive_task_completion_cancellation(self):
        """Cancelling a draft when asked 'Should I send it?'."""
        self.orch.chat("Send mail to Rahul.")
        self.orch.chat("Tell him I'm on my way.")
        res3 = self.orch.chat("No, cancel it")
        self.assertEqual(res3["task"]["status"], TaskStatus.CANCELED.value)
        self.assertIn("cancelled", res3["message"].lower())

    def test_multi_action_write_note(self):
        """'Write a note called Ideas saying build Cortex safely.'
        COMMAND: write_note, TITLE: Ideas, CONTENT: build Cortex safely.
        """
        prompt = "Write a note called Ideas saying build Cortex safely."
        res = self.orch.chat(prompt)
        task = res["task"]

        self.assertEqual(task["command"], TaskCommand.WRITE_NOTE.value)
        self.assertEqual(task["params"]["title"], "Ideas")
        self.assertEqual(task["params"]["body"], "build Cortex safely")
        self.assertNotEqual(task["params"]["body"], prompt)

    def test_multi_action_send_whatsapp_message(self):
        """'Send Rahul a WhatsApp message saying I'm late.'
        COMMAND: send_message, RECIPIENT: Rahul, CONTENT: I'm late.
        """
        prompt = "Send Rahul a WhatsApp message saying I'm late."
        res = self.orch.chat(prompt)
        task = res["task"]

        self.assertEqual(task["command"], TaskCommand.SEND_MESSAGE.value)
        self.assertEqual(task["params"]["recipient"], "Rahul")
        self.assertEqual(task["params"]["body"], "I'm late")
        self.assertNotEqual(task["params"]["body"], prompt)
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)

    def test_multi_action_search_with_filter(self):
        """'Search for laptops under ₹50,000.'
        COMMAND: search (web_search), QUERY: laptops, FILTER: price <= ₹50,000.
        """
        prompt = "Search for laptops under ₹50,000."
        analysis = self.orch._analyze_intent_fallback(prompt)

        self.assertEqual(analysis["command"], TaskCommand.WEB_SEARCH)
        self.assertEqual(analysis["params"]["query"], "laptops")
        self.assertEqual(analysis["params"]["filter"], "price <= ₹50,000")

    def test_no_blind_text_forwarding_in_notes(self):
        """'Write a note called Ideas' without body should prompt for body, not forward command."""
        res1 = self.orch.chat("Write a note called Ideas")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("Ideas", res1["message"])

        res2 = self.orch.chat("build Cortex safely")
        self.assertEqual(res2["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(res2["task"]["params"]["title"], "Ideas")
        self.assertEqual(res2["task"]["params"]["body"], "build Cortex safely")

    def test_no_blind_text_forwarding_in_messages(self):
        """'Send Rahul a WhatsApp message' without body should ask for body."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("Rahul", res1["message"])

        res2 = self.orch.chat("I'm running 5 minutes late")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["recipient"], "Rahul")
        self.assertEqual(res2["task"]["params"]["body"], "I'm running 5 minutes late")


if __name__ == "__main__":
    unittest.main()
