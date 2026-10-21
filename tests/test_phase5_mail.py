import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation, classify_command
from cortex_memory import EncryptedMemoryStore
from cortex_sdk import RiskLevel, TaskCommand
from orchestrator import CortexOrchestrator


class Phase5MailTests(unittest.TestCase):
    def make_orchestrator(self, use_gemini=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(tmp.name) / "memory.sqlite3"))
        return CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=use_gemini)

    def test_read_mail_command(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("check my emails")
        task = response["task"]
        self.assertEqual(task["command"], "read_mail")
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["requiresApproval"])
        self.assertIn("emails", task["auditTrail"][-1]["data"])

    def test_summarize_mail_command_fallback(self):
        orchestrator = self.make_orchestrator(use_gemini=False)
        response = orchestrator.chat("summarize my emails")
        task = response["task"]
        self.assertEqual(task["command"], "summarize_mail")
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["requiresApproval"])
        self.assertIn("recent emails", response["message"])

    def test_summarize_mail_gemini(self):
        with patch("google.generativeai.GenerativeModel") as mock_model_class, \
             patch("google.generativeai.configure") as _:
            mock_model = mock_model_class.return_value
            # Step 1: intent classifier returns summarize_mail
            mock_intent = MagicMock()
            mock_intent.text = '{"command": "summarize_mail", "params": {"limit": 5, "unread_only": false}, "risk_level": "low", "requires_approval": false, "block_reason": null, "answer": null}'
            # Step 2: email summarizer returns warm summary
            mock_summary = MagicMock()
            mock_summary.text = "You have 3 new emails. Akash says the Phase 5 tests look great, and Maruthi wants to sync this afternoon on the UI."
            mock_model.generate_content.side_effect = [mock_intent, mock_summary]

            import orchestrator
            old_has_genai = orchestrator.HAS_GENAI
            orchestrator.HAS_GENAI = True
            old_key = os.environ.get("GEMINI_API_KEY")
            os.environ["GEMINI_API_KEY"] = "fake-key"
            try:
                orch = self.make_orchestrator(use_gemini=True)
                response = orch.chat("summarize my inbox")
                self.assertEqual(response["task"]["command"], "summarize_mail")
                self.assertEqual(response["task"]["status"], "completed")
                self.assertIn("Akash", response["message"])
            finally:
                orchestrator.HAS_GENAI = old_has_genai
                if old_key is not None:
                    os.environ["GEMINI_API_KEY"] = old_key
                else:
                    os.environ.pop("GEMINI_API_KEY", None)

    def test_draft_mail_command(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("draft email to akash@team.internal subject Project Update body All systems operational")
        task = response["task"]
        self.assertEqual(task["command"], "draft_mail")
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["requiresApproval"])
        self.assertEqual(task["params"]["recipient"], "akash@team.internal")
        self.assertEqual(task["params"]["subject"], "Project Update")
        self.assertEqual(task["params"]["body"], "All systems operational")

    def test_send_mail_requires_approval(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("send email to maruthi@team.internal subject Design Review body UI looks great")
        task = response["task"]
        self.assertEqual(task["command"], "send_mail")
        self.assertEqual(task["status"], "waiting_approval")
        self.assertTrue(task["requiresApproval"])
        self.assertEqual(task["riskLevel"], "high")

    def test_send_mail_approved_executes(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("send email to abhishek@team.internal subject Deploy saying Pipeline is ready")
        task_id = response["task"]["id"]
        self.assertEqual(response["task"]["status"], "waiting_approval")

        approved = orchestrator.approve(task_id, True)
        self.assertEqual(approved["status"], "completed")
        self.assertIn("Sent email to abhishek@team.internal", approved["result"])

    def test_send_mail_rejected_cancels(self):
        orchestrator = self.make_orchestrator()
        response = orchestrator.chat("send email to test@example.com subject Test saying hello")
        task_id = response["task"]["id"]
        self.assertEqual(response["task"]["status"], "waiting_approval")

        rejected = orchestrator.approve(task_id, False)
        self.assertEqual(rejected["status"], "canceled")
        self.assertEqual(rejected["result"], "Approval rejected. No action was taken.")

    def test_mail_safety_classification(self):
        risk_read, approval_read, _ = classify_command(TaskCommand.READ_MAIL, "check email")
        self.assertEqual(risk_read, RiskLevel.LOW)
        self.assertFalse(approval_read)

        risk_draft, approval_draft, _ = classify_command(TaskCommand.DRAFT_MAIL, "draft email")
        self.assertEqual(risk_draft, RiskLevel.LOW)
        self.assertFalse(approval_draft)

        risk_send, approval_send, _ = classify_command(TaskCommand.SEND_MAIL, "send email to bob")
        self.assertEqual(risk_send, RiskLevel.HIGH)
        self.assertTrue(approval_send)


if __name__ == "__main__":
    unittest.main()
