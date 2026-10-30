from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import (
    RecipientResolver,
    UserAuthorizedContactStore,
)
from backend.capabilities import DeviceAutomation
from backend.capabilities.whatsapp_actions import (
    WhatsAppDraft,
    compose_whatsapp_message,
)
from backend.core.contracts import (
    ContactResolutionStatus,
    TaskCommand,
    TaskStatus,
    VerifiedContact,
)
from backend.persistence import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore


class VerifiedWhatsAppContactResolutionTests(unittest.TestCase):
    """Deterministic, fail-closed regression test suite for WhatsApp contact resolution.
    Covers WA-CONTACT-01 through WA-CONTACT-14.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(pathlib.Path(self.tmp.name) / "test_memory.sqlite3")
        self.memory = EncryptedMemoryStore(self.db_path)
        self.task_store = TaskStore(self.db_path)
        self.device = DeviceAutomation(dry_run=True)

        # Standard authorized contact store
        self.contact_store = UserAuthorizedContactStore(
            contacts=[
                {"id": "c_rahul_sharma", "name": "Rahul Sharma", "phone": "+91 98765 43210", "role": "colleague"},
                {"id": "c_priya", "name": "Priya Patel", "phone": "+91 98765 67890", "role": "team lead"},
                {"id": "c_ananya", "name": "Ananya Rao", "phone": "+91 98765 54321", "role": "researcher"},
                {"id": "c_alex_mor", "name": "Alex Morgan", "phone": "+91 98765 11111", "role": "designer"},
            ],
            memory_store=self.memory,
        )
        self.resolver = RecipientResolver(
            mail_automation=self.device.mail,
            memory_store=self.memory,
            contact_source=self.contact_store,
        )
        self.orch = CortexOrchestrator(self.device, self.memory, use_gemini=False)
        self.orch.recipient_resolver = self.resolver
        self.orch.task_store = self.task_store

    def test_wa_contact_01_exact_saved_contact_resolves_actual_number(self) -> None:
        """WA-CONTACT-01: Exact saved contact resolves to the source record's actual number."""
        res = self.orch.chat("Send WhatsApp to Priya Patel saying meeting at 3")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(task["params"]["contact_name"], "Priya Patel")
        self.assertEqual(task["params"]["phone"], "+91 98765 67890")
        self.assertTrue(task["params"]["contact_verified"])
        self.assertEqual(task["params"]["contact_source"], "user_authorized_contacts")
        self.assertEqual(task["params"]["contact_id"], "c_priya")
        self.assertIn("Priya Patel", res["message"])
        self.assertIn("+91 98765 67890", res["message"])

    def test_wa_contact_02_rahul_engg_absent_returns_no_match(self) -> None:
        """WA-CONTACT-02: 'Rahul Engg' absent from the contact source returns NO_MATCH."""
        resolution = self.resolver.resolve_messaging_contact("Rahul Engg", channel="whatsapp")
        self.assertEqual(resolution.status, ContactResolutionStatus.NO_MATCH)
        self.assertIsNone(resolution.contact)
        self.assertIn("No contact found for 'Rahul Engg'", resolution.clarification_prompt)

        res = self.orch.chat("Send WhatsApp to Rahul Engg saying are you free?")
        self.assertEqual(res["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("No contact found for 'Rahul Engg'", res["message"])

    def test_wa_contact_03_unrelated_rahul_sharma_never_selected_fallback(self) -> None:
        """WA-CONTACT-03: An unrelated 'Rahul Sharma' is never selected as a fallback for 'Rahul Engg'."""
        res = self.orch.chat("Send WhatsApp to Rahul Engg saying project update")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        self.assertNotEqual(task["params"].get("contact_name"), "Rahul Sharma")
        self.assertNotEqual(task["params"].get("phone"), "+91 98765 43210")
        self.assertNotIn("Rahul Sharma", res["message"])
        self.assertNotIn("draft_prepared", [e.get("name") for e in task.get("audit_trail", [])])

    def test_wa_contact_04_system_never_invents_phone_number(self) -> None:
        """WA-CONTACT-04: The system never invents a phone number for an unsaved name."""
        res = self.orch.chat("Send WhatsApp to Vikram Malhotra saying hello")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        self.assertFalse(bool(task["params"].get("phone")))
        self.assertFalse(bool(task["params"].get("approval_hash")))
        self.assertIn("No contact found for 'Vikram Malhotra'", res["message"])

    def test_wa_contact_05_duplicate_exact_names_trigger_multiple_matches(self) -> None:
        """WA-CONTACT-05: Duplicate exact names trigger MULTIPLE_MATCHES and interactive disambiguation."""
        self.contact_store.add_contact("Alex Chen", "+91 98765 22222", role="engineer", id="c_alex_eng")
        self.contact_store.add_contact("Alex Chen", "+91 98765 33333", role="architect", id="c_alex_arch")

        res1 = self.orch.chat("Send WhatsApp to Alex Chen saying review design")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("Multiple verified contacts found matching 'Alex Chen'", res1["message"])
        self.assertIn("engineer", res1["message"])
        self.assertIn("architect", res1["message"])

        # User chooses the second contact
        res2 = self.orch.chat("2")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["contact_name"], "Alex Chen")
        self.assertEqual(res2["task"]["params"]["phone"], "+91 98765 33333")
        self.assertEqual(res2["task"]["params"]["contact_id"], "c_alex_arch")

    def test_wa_contact_06_partial_fuzzy_matches_are_suggestions_only(self) -> None:
        """WA-CONTACT-06: Partial and fuzzy matches are suggestions only, never automatic selections."""
        # Querying "Alex" when store has "Alex Morgan" and "Alex Chen"
        self.contact_store.add_contact("Alex Chen", "+91 98765 22222", role="engineer")

        res1 = self.orch.chat("Send WhatsApp to Alex saying hi")
        # Must NOT automatically pick one as exact match
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn("unverified suggestions", res1["message"].lower())
        self.assertIn("Alex Morgan", res1["message"])
        self.assertIn("Alex Chen", res1["message"])

        # User explicitly chooses suggestion 1
        res2 = self.orch.chat("1")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["contact_name"], "Alex Morgan")
        self.assertEqual(res2["task"]["params"]["phone"], "+91 98765 11111")

    def test_wa_contact_07_transliteration_multilingual_cannot_bypass_exact_match(self) -> None:
        """WA-CONTACT-07: Transliteration and multilingual similarity cannot bypass exact-match policy."""
        # Contact store only has English "Rahul Sharma"
        res = self.orch.chat("Send WhatsApp to ರಾಹುಲ್ saying namaskara")
        task = res["task"]

        # Must fail closed to NEED_INFO, not silently resolve to Rahul Sharma
        self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
        self.assertNotEqual(task["params"].get("contact_name"), "Rahul Sharma")
        self.assertNotIn("Rahul Sharma", res["message"])

    def test_wa_contact_08_unavailable_or_stale_source_prevents_sending(self) -> None:
        """WA-CONTACT-08: An unavailable or stale contact source prevents sending."""
        # Test source unavailable fails closed
        self.contact_store.set_available(False)
        res1 = self.orch.chat("Send WhatsApp to Priya Patel saying check this")
        self.assertEqual(res1["task"]["status"], TaskStatus.FAILED.value)
        self.assertIn("unavailable", res1["message"].lower())

        # Restore availability but make stale
        self.contact_store.set_available(True)
        self.contact_store.set_stale(True)
        res2 = self.orch.chat("Send WhatsApp to Priya Patel saying check this")
        self.assertEqual(res2["task"]["status"], TaskStatus.FAILED.value)
        self.assertIn("stale", res2["message"].lower())

        # Ensure approve() also checks staleness fail-closed
        self.contact_store.set_stale(False)
        res3 = self.orch.chat("Send WhatsApp to Priya Patel saying check this")
        task_id = res3["task"]["id"]
        auth_hash = res3["task"]["params"]["approval_hash"]
        self.assertEqual(res3["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

        self.contact_store.set_stale(True)
        app_res = self.orch.approve(task_id, approved=True, approval_hash=auth_hash)
        self.assertEqual(app_res["status"], TaskStatus.FAILED.value)
        self.assertIn("stale", app_res.get("error", "").lower())

    def test_wa_contact_09_changing_selected_recipient_invalidates_approval(self) -> None:
        """WA-CONTACT-09: Changing the selected recipient invalidates the previous approval."""
        res = self.orch.chat("Send WhatsApp to Priya Patel saying hello")
        task_id = res["task"]["id"]
        auth_hash = res["task"]["params"]["approval_hash"]

        # Maliciously mutate the recipient phone
        task_obj = self.orch._get_task(task_id)
        task_obj.params["phone"] = "+91 99999 99999"

        app_res = self.orch.approve(task_id, approved=True, approval_hash=auth_hash)
        self.assertNotEqual(app_res["status"], TaskStatus.COMPLETED.value)
        self.assertEqual(app_res["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertIn("invalidated", str(app_res.get("error", "")).lower())

    def test_wa_contact_10_send_adapter_receives_approved_destination(self) -> None:
        """WA-CONTACT-10: The final send adapter receives exactly the destination that was approved."""
        res1 = self.orch.chat("Send WhatsApp to Priya Patel saying dinner tonight")
        task_id = res1["task"]["id"]
        auth_hash = res1["task"]["params"]["approval_hash"]

        app_res = self.orch.approve(task_id, approved=True, approval_hash=auth_hash)
        self.assertEqual(app_res["status"], TaskStatus.COMPLETED.value)

        # Inspect sent records in automation adapter
        sent = self.device.whatsapp.sent_messages
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["recipient"], "Priya Patel")
        self.assertEqual(sent[0]["phone"], "+919876567890")
        self.assertEqual(sent[0]["approved_hash"], auth_hash)

    def test_wa_contact_11_cached_context_restart_cannot_restore_unverified_recipient(self) -> None:
        """WA-CONTACT-11: Cached task context and application restart cannot restore an unverified recipient."""
        res1 = self.orch.chat("Send WhatsApp to Priya Patel saying see you")
        task_id = res1["task"]["id"]
        auth_hash = res1["task"]["params"]["approval_hash"]

        # Create new orchestrator rehydrating from memory
        new_device = DeviceAutomation(dry_run=True)
        new_orch = CortexOrchestrator(new_device, self.memory, use_gemini=False)
        new_store = UserAuthorizedContactStore(
            contacts=[],  # Empty contacts list on new instance!
            memory_store=self.memory,
        )
        new_orch.recipient_resolver = RecipientResolver(
            mail_automation=new_device.mail,
            memory_store=self.memory,
            contact_source=new_store,
        )
        new_orch.task_store = self.task_store

        # Contact is absent from new contact source -> approve must fail
        app_res = new_orch.approve(task_id, approved=True, approval_hash=auth_hash)
        # Hash recomputation or recipient lookup fails
        task_after = new_orch._get_task(task_id)
        self.assertNotEqual(task_after.status, TaskStatus.COMPLETED)

    def test_wa_contact_12_approval_card_uses_verified_structured_data(self) -> None:
        """WA-CONTACT-12: The approval card uses verified structured recipient data, not an LLM-generated name."""
        res = self.orch.chat("Send WhatsApp to Rahul Sharma saying meeting confirmed")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(task["params"]["contact_name"], "Rahul Sharma")
        self.assertEqual(task["params"]["phone"], "+91 98765 43210")
        self.assertEqual(task["params"]["contact_source"], "user_authorized_contacts")
        self.assertIn("Rahul Sharma (+91 98765 43210)", res["message"])
        self.assertTrue(bool(task["params"].get("approval_hash")))

    def test_wa_contact_13_user_provided_phone_requires_explicit_confirmation(self) -> None:
        """WA-CONTACT-13: A user-provided phone number is used only after displaying it and obtaining explicit confirmation."""
        unverified_num = "+919123456789"
        res1 = self.orch.chat(f"Send WhatsApp to {unverified_num} saying quick test")
        self.assertEqual(res1["task"]["status"], TaskStatus.NEED_INFO.value)
        self.assertIn(unverified_num, res1["message"])
        self.assertIn("not in your verified contacts", res1["message"])

        # User confirms
        res2 = self.orch.chat("yes")
        self.assertEqual(res2["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(res2["task"]["params"]["phone"], unverified_num)
        self.assertFalse(res2["task"]["params"]["contact_verified"])
        self.assertEqual(res2["task"]["params"]["contact_source"], "user_provided_unverified")

    def test_wa_contact_14_existing_email_and_whatsapp_regressions_covered(self) -> None:
        """WA-CONTACT-14: Existing email approval and WhatsApp message-body extraction regressions remain covered."""
        # 1. WhatsApp body conversion does not copy "saying"
        body = compose_whatsapp_message("saying I'll be 15 minutes late", recipient_name="Priya")
        self.assertNotIn("saying", body)
        self.assertIn("Priya", body)
        self.assertTrue("late" in body.lower() or "delayed" in body.lower())

        # 2. Email drafting still works correctly
        mail_res = self.orch.chat("Send an email to principal@rvce.edu.in saying request for lab access")
        self.assertEqual(mail_res["task"]["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertIn("principal@rvce.edu.in", mail_res["task"]["params"]["recipient"])


if __name__ == "__main__":
    unittest.main()

