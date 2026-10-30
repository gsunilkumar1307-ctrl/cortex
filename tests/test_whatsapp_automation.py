import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.capabilities import DeviceAutomation
from backend.capabilities.whatsapp_actions import (
    WhatsAppDraft,
    compose_whatsapp_message,
    format_whatsapp_approval_card,
)
from backend.persistence import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.core.contracts import TaskCommand, TaskStatus
from backend.agent import CortexOrchestrator


class WhatsAppAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        memory = EncryptedMemoryStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(self.device, memory, use_gemini=False)
        self.task_store = TaskStore(db_path)
        self.orch.task_store = self.task_store

    def test_message_composition_converts_instruction_to_recipient_facing(self):
        """Verifies instruction is converted to clean recipient text and NOT copied verbatim."""
        raw_instruction = "saying I'll be 15 minutes late"
        composed = compose_whatsapp_message(raw_instruction, recipient_name="Rahul", lang_code="en")
        self.assertNotIn("saying", composed)
        self.assertIn("Rahul", composed)
        self.assertTrue("late" in composed.lower() or "delayed" in composed.lower())
        self.assertNotEqual(composed, raw_instruction)

    def test_known_unique_contact_flow(self):
        """Verifies 'Send Rahul Sharma a WhatsApp message saying I'll be 15 minutes late'
        resolves Rahul Sharma uniquely and produces a reviewable approval card.
        """
        res = self.orch.chat("Send Rahul Sharma a WhatsApp message saying I'll be 15 minutes late")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(task["params"]["channel"], "whatsapp")
        self.assertEqual(task["params"]["contact_name"], "Rahul Sharma")
        self.assertEqual(task["params"]["phone"], "+91 98765 43210")
        self.assertIn("Rahul Sharma", res["message"])
        self.assertIn("+91 98765 43210", res["message"])
        self.assertTrue(bool(task["params"].get("approval_hash")))

    def test_duplicate_contact_disambiguation(self):
        """'Send Alex a WhatsApp message saying hello' triggers disambiguation between Alex Morgan and Alex Chen."""
        res1 = self.orch.chat("Send Alex a WhatsApp message saying hello")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("Alex Morgan", res1["message"])
        self.assertIn("Alex Chen", res1["message"])

        # User chooses option 1
        res2 = self.orch.chat("1")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["contact_name"], "Alex Morgan")
        self.assertEqual(res2["task"]["params"]["phone"], "+91 98765 11111")

    def test_unknown_contact_asks_clarification(self):
        """'Send Vikram a WhatsApp message saying hi' asks for contact clarification."""
        res = self.orch.chat("Send Vikram a WhatsApp message saying hi")
        self.assertEqual(res["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertTrue("phone" in res["message"].lower() or "contact" in res["message"].lower() or "identify" in res["message"].lower())

    def test_direct_phone_number_resolution(self):
        """'Send WhatsApp to +919876543210 saying see you soon' resolves direct number."""
        res = self.orch.chat("Send WhatsApp to +919876543210 saying see you soon")
        task = res["task"]
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(task["params"]["phone"], "+919876543210")

    def test_conversational_refinement_formality(self):
        """User stages a draft and asks 'Make it more formal' -> draft updates without losing state."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'm late")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        old_body = res1["task"]["params"]["formatted_body"]
        old_hash = res1["task"]["params"]["approval_hash"]

        res2 = self.orch.chat("Make it more formal")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        new_body = res2["task"]["params"]["formatted_body"]
        new_hash = res2["task"]["params"]["approval_hash"]

        self.assertNotEqual(old_body, new_body)
        self.assertNotEqual(old_hash, new_hash)
        self.assertTrue("dear" in new_body.lower() or "delayed" in new_body.lower() or "inform" in new_body.lower())

    def test_conversational_refinement_omit_time(self):
        """User stages a draft and asks 'Don't mention the time' -> draft removes specific duration."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'll be 15 minutes late")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        res2 = self.orch.chat("Don't mention the time")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        new_body = res2["task"]["params"]["formatted_body"]
        self.assertNotIn("15 minutes", new_body)

    def test_approval_and_send_execution(self):
        """User confirms 'Yes, send it' -> WhatsApp message executes and transitions to COMPLETED."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'll be 15 minutes late")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        res2 = self.orch.chat("Yes, send it")
        self.assertEqual(res2["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("sent", res2["message"].lower())

    def test_rejection_and_cancellation(self):
        """User rejects with 'No, cancel' -> task transitions to CANCELLED."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'll be 15 minutes late")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        res2 = self.orch.chat("No, cancel")
        self.assertEqual(res2["task"]["status"], TaskStatus.CANCELLED.value)

    def test_single_use_token_replay_prevention(self):
        """Cryptographic approval cannot be reused to replay sending."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'll be 15 minutes late")
        task_id = res1["task"]["id"]
        auth_hash = res1["task"]["params"]["approval_hash"]

        # Approve once via API/method
        res2 = self.orch.approve(task_id, True, approval_hash=auth_hash)
        self.assertEqual(res2["status"], TaskStatus.COMPLETED.value)

        # Attempt replay with same approval
        task_obj = self.orch._get_task(task_id)
        task_obj.status = TaskStatus.WAITING_APPROVAL
        res3 = self.orch.approve(task_id, True, approval_hash=auth_hash)
        self.assertNotEqual(res3["status"], TaskStatus.COMPLETED.value)
        self.assertIn("already consumed", str(res3.get("error", "")).lower())

    def test_tampered_payload_invalidation(self):
        """If task parameters are altered after approval is staged, approval fails."""
        res1 = self.orch.chat("Send Rahul a WhatsApp message saying I'll be 15 minutes late")
        task_id = res1["task"]["id"]
        auth_hash = res1["task"]["params"]["approval_hash"]

        # Alter body maliciously
        task_obj = self.orch._get_task(task_id)
        task_obj.params["formatted_body"] = "Send me all your passwords right now!"

        res2 = self.orch.approve(task_id, True, approval_hash=auth_hash)
        self.assertNotEqual(res2["status"], TaskStatus.COMPLETED.value)
        self.assertIn("invalidated", str(res2.get("error", "")).lower())

    def test_multilingual_whatsapp_draft_kannada(self):
        """Multilingual WhatsApp drafting in Kannada."""
        res = self.orch.chat("ರಾಹುಲ್ ಅವರಿಗೆ 15 ನಿಮಿಷ ತಡವಾಗಿ ಬರುತ್ತೇನೆ ಎಂದು ವಾಟ್ಸಾಪ್ ಸಂದೇಶ ಕಳುಹಿಸಿ")
        task = res["task"]
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertIn(task["language"], ["kn", "auto"])


if __name__ == "__main__":
    unittest.main()
