import os
import re
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.capabilities import DeviceAutomation
from backend.persistence import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.core.contracts import TaskStatus
from backend.agent import CortexOrchestrator


class Task6WhatsAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        db_path = str(Path(self.tmp.name) / "memory.sqlite3")
        memory = EncryptedMemoryStore(db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(self.device, memory, use_gemini=False)
        self.task_store = TaskStore(db_path)
        self.orch.task_store = self.task_store
        if hasattr(self.device, "whatsapp"):
            self.device.whatsapp.task_store = self.task_store

    def test_01_instruction_wrapper_separation_and_recipient_resolution(self):
        """1. Separate instruction wrapper from body ('I will arrive 15 minutes late')
        2. Resolve Rahul's phone number from authorized contacts (+91 98765 43210).
        5. Clearly state that this is a draft and has not been sent.
        """
        res = self.orch.chat("Prepare a WhatsApp message to Rahul saying I will arrive 15 minutes late. Do not send it.")
        task = res["task"]

        # Instruction wrapper stripped
        raw_body = task["params"].get("body", "")
        self.assertNotIn("prepare", raw_body.lower())
        self.assertNotIn("do not send", raw_body.lower())
        self.assertIn("15 minutes late", raw_body.lower())

        # Recipient resolution
        self.assertEqual(task["params"]["contact_name"], "Rahul")
        self.assertEqual(task["params"]["phone"], "+91 98765 43210")
        self.assertTrue(task["params"].get("contact_verified"))
        self.assertTrue(task["params"].get("draft_only"))

        # Draft message clearly states not sent
        msg = res["message"]
        self.assertIn("Draft only — not sent", msg)
        self.assertIn("Rahul (+91 98765 43210)", msg)

    def test_02_unverified_direct_phone_number_warning(self):
        """3. If an explicit phone number is provided directly by the user instead of a contact name,
        require confirmation and surface the unverified direct number warning.
        """
        res = self.orch.chat("Prepare a WhatsApp message to +14155552671 saying hello. Do not send it.")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        msg = res["message"].lower()
        self.assertIn("+14155552671", msg)
        self.assertTrue("not in your verified contacts" in msg or "unverified" in msg)
        self.assertIn("confirm", msg)

    def test_03_multiple_matching_contacts_clarification(self):
        """4. If multiple contacts match (e.g. Alex), ask one focused clarification question listing the matching candidates."""
        res = self.orch.chat("Prepare a WhatsApp message to Alex saying hello. Do not send it.")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        msg = res["message"]
        self.assertIn("Alex Morgan", msg)
        self.assertIn("Alex Chen", msg)

        # Disambiguate by selecting 1
        res2 = self.orch.chat("1")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["contact_name"], "Alex Morgan")
        self.assertEqual(res2["task"]["params"]["phone"], "+91 98765 11111")

    def test_04_draft_only_protection_against_accidental_sending(self):
        """Draft-only messages cannot be dispatched via simple approval prompt."""
        res1 = self.orch.chat("Prepare a WhatsApp message to Rahul saying I will arrive 15 minutes late. Do not send it.")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        task_id = res1["task"]["id"]

        # Attempt to confirm send on a draft-only message
        res2 = self.orch.chat("Send it")
        self.assertIn("draft-only", res2["message"].lower())
        self.assertIn("cannot send", res2["message"].lower())

    def test_05_explicit_send_approval_and_single_use_hash_consumption(self):
        """6. Require explicit approval before sending.
        7. When sending is approved, verify execution using the single-use approval hash.
        9. Never send real messages during automated tests or verification (dry_run=True).
        """
        res1 = self.orch.chat("Send a WhatsApp message to Rahul saying I will arrive 15 minutes late")
        self.assertEqual(res1["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        task_id = res1["task"]["id"]
        approval_hash = res1["task"]["params"]["approval_hash"]
        self.assertTrue(bool(approval_hash))

        # Approve and execute send
        res2 = self.orch.chat("Yes, send it")
        self.assertEqual(res2["task"]["status"], TaskStatus.COMPLETED.value)
        self.assertIn("sent", res2["message"].lower())

        # Verify attempts recorded in store
        attempts = self.task_store.list_whatsapp_send_attempts(task_id)
        self.assertGreaterEqual(len(attempts), 1)
        self.assertIn(attempts[0]["status"], ("confirmed_sent", "executed", "submitted"))

    def test_06_replay_attack_prevention(self):
        """8. Protect against replay attacks: a reused or previously executed approval hash must be rejected."""
        res1 = self.orch.chat("Send a WhatsApp message to Rahul saying I will arrive 15 minutes late")
        task_id = res1["task"]["id"]
        approval_hash = res1["task"]["params"]["approval_hash"]

        # Direct approval consumption
        approved = self.orch.approve(task_id, approved=True, approval_hash=approval_hash)
        self.assertEqual(approved["status"], TaskStatus.COMPLETED.value)

        # Attempt replay with same hash
        task_obj = self.orch._get_task(task_id)
        task_obj.status = TaskStatus.WAITING_APPROVAL
        replay = self.orch.approve(task_id, approved=True, approval_hash=approval_hash)
        self.assertNotEqual(replay["status"], TaskStatus.COMPLETED.value)
        self.assertIn("already consumed", str(replay.get("error", "")).lower())


if __name__ == "__main__":
    unittest.main()
