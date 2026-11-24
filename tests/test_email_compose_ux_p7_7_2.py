"""Deterministic regression test suite for CORTEX P7.7.2 Single Composer Lifecycle & Duplicate Card Remediation.

Verifies:
1. Exact sequence of 10 conversational modifications to a single email draft task:
   - Initial: "send mail to myself for requesting a leave permission"
   - Edit 1: "make it more formal and friendly"
   - Edit 2: "make it short"
   - Edit 3: "recipient name is sunil"
   - Edit 4: "request leave for one week and add date"
   - Edit 5: "change leave duration to one week"
   - Edit 6: "change leave duration to two days"
   - Edit 7: "recipient name is dhulappa"
   - Edit 8: "make it larger"
   - Edit 9: "format it as a proper leave letter"
   - Edit 10: "change the topic to applying for a vtu internship"
2. Single Composer Task Identity: Exactly ONE task ID is preserved across all 10 edits.
3. Notification Differentiation: Initial draft presents the approval card/notice, while subsequent
   edits return concise natural feedback without duplicate approval card walls.
4. TO & SUBJECT Population: Neither recipient nor subject are ever blank or unpopulated.
5. Topic Shift: "Change the topic to applying for a VTU internship" properly updates subject to
   "Application for VTU Internship", replaces body with formal internship application, preserves
   the recipient salutation name ("Dear Dhulappa,"), and retains recipient email.
6. Expanded & Letter Formats: "Make it larger" expands the body, "Format it as a proper leave letter"
   formats formal leave structure.
7. Cryptographic approval hash recomputation and replay protection.
"""

import unittest
from backend.agent.email_engine import EmailEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus


class TestEmailComposeUXP772(unittest.TestCase):
    """P7.7.2 Single Composer Lifecycle & UX Remediation Tests."""

    def setUp(self):
        self.engine = EmailEngine()
        self.orch = CortexOrchestrator()

    def test_10_turn_single_composer_lifecycle(self):
        """Verifies the complete 10-turn conversational editing sequence on a single persistent task."""
        # Turn 1: Initial Draft
        resp1 = self.orch.chat("send mail to myself for requesting a leave permission")
        self.assertIn("task_id", self.orch.pending_action)
        initial_task_id = self.orch.pending_action["task_id"]
        t1 = self.orch.tasks[initial_task_id]

        self.assertEqual(t1.status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(t1.state_version, 1)
        self.assertTrue(t1.params.get("recipient"))
        self.assertTrue(t1.params.get("subject"))
        # Initial turn has the full approval card presentation
        self.assertIn("Draft created and saved to your mailbox", resp1["message"])
        self.assertIn("Options:", resp1["message"])

        # Edit 1: "Make it more formal and friendly"
        resp2 = self.orch.chat("make it more formal and friendly")
        t2 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t2.state_version, 2)
        self.assertNotIn("Draft created and saved to your mailbox", resp2["message"])
        self.assertNotIn("Options:", resp2["message"])
        self.assertIn("formal and friendly", resp2["message"].lower())
        self.assertIn("hope this email finds you well", t2.params["formatted_body"].lower())

        # Edit 2: "Make it short"
        resp3 = self.orch.chat("make it short")
        t3 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t3.state_version, 3)
        self.assertNotIn("Draft created and saved to your mailbox", resp3["message"])
        self.assertNotIn("Options:", resp3["message"])
        self.assertIn("short", resp3["message"].lower())

        # Edit 3: "Recipient name is Sunil"
        resp4 = self.orch.chat("recipient name is sunil")
        t4 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t4.state_version, 4)
        self.assertNotIn("Draft created and saved to your mailbox", resp4["message"])
        self.assertNotIn("Options:", resp4["message"])
        self.assertIn("Sunil", resp4["message"])
        self.assertTrue(t4.params["formatted_body"].startswith("Dear Sunil,"))

        # Edit 4: "Request leave for one week and add date"
        resp5 = self.orch.chat("request leave for one week and add date")
        t5 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t5.state_version, 5)
        self.assertNotIn("Draft created and saved to your mailbox", resp5["message"])
        self.assertNotIn("Options:", resp5["message"])
        self.assertIn("one week", t5.params["formatted_body"].lower())
        self.assertIn("starting from monday", t5.params["formatted_body"].lower())

        # Edit 5: "Change leave duration to one week"
        resp6 = self.orch.chat("change leave duration to one week")
        t6 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t6.state_version, 6)
        self.assertNotIn("Draft created and saved to your mailbox", resp6["message"])
        self.assertNotIn("Options:", resp6["message"])
        self.assertIn("one week", t6.params["formatted_body"].lower())

        # Edit 6: "Change leave duration to two days"
        resp7 = self.orch.chat("change leave duration to two days")
        t7 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t7.state_version, 7)
        self.assertNotIn("Draft created and saved to your mailbox", resp7["message"])
        self.assertNotIn("Options:", resp7["message"])
        self.assertIn("two days", t7.params["formatted_body"].lower())
        self.assertIn("two days", resp7["message"].lower())

        # Edit 7: "Recipient name is Dhulappa"
        resp8 = self.orch.chat("recipient name is dhulappa")
        t8 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t8.state_version, 8)
        self.assertNotIn("Draft created and saved to your mailbox", resp8["message"])
        self.assertNotIn("Options:", resp8["message"])
        self.assertIn("Dhulappa", resp8["message"])
        self.assertTrue(t8.params["formatted_body"].startswith("Dear Dhulappa,"))
        self.assertTrue(t8.params.get("recipient_email"))

        # Edit 8: "Make it larger"
        len_before = len(t8.params["formatted_body"])
        resp9 = self.orch.chat("make it larger")
        t9 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t9.state_version, 9)
        self.assertNotIn("Draft created and saved to your mailbox", resp9["message"])
        self.assertNotIn("Options:", resp9["message"])
        self.assertIn("expanded", resp9["message"].lower())
        self.assertGreater(len(t9.params["formatted_body"]), len_before)
        self.assertTrue(t9.params["formatted_body"].startswith("Dear Dhulappa,"))

        # Edit 9: "Format it as a proper leave letter"
        resp10 = self.orch.chat("format it as a proper leave letter")
        t10 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t10.state_version, 10)
        self.assertNotIn("Draft created and saved to your mailbox", resp10["message"])
        self.assertNotIn("Options:", resp10["message"])
        self.assertIn("leave application", t10.params["subject"].lower())
        self.assertTrue(t10.params["formatted_body"].startswith("Dear Dhulappa,"))

        # Edit 10: "Change the topic to applying for a VTU internship"
        resp11 = self.orch.chat("change the topic to applying for a vtu internship")
        t11 = self.orch.tasks[initial_task_id]
        self.assertEqual(self.orch.pending_action["task_id"], initial_task_id)
        self.assertEqual(t11.state_version, 11)
        self.assertNotIn("Draft created and saved to your mailbox", resp11["message"])
        self.assertNotIn("Options:", resp11["message"])
        self.assertIn("vtu", resp11["message"].lower())
        self.assertEqual(t11.params["subject"], "Application for VTU Internship")
        self.assertTrue(t11.params["formatted_body"].startswith("Dear Dhulappa,"))
        self.assertIn("internship", t11.params["formatted_body"].lower())
        self.assertNotIn("leave of absence", t11.params["formatted_body"].lower())
        self.assertEqual(t11.params["recipient_email"], "gsunilkumar1307@gmail.com")

        # Verify task ID never changed
        self.assertEqual(t11.id, initial_task_id)
        self.assertEqual(t11.state_version, 11)

    def test_composer_fields_never_blank(self):
        """Validates that TO (recipient) and SUBJECT fields are never empty across edits."""
        self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]

        test_edits = [
            "make it formal and friendly",
            "make it short",
            "recipient name is sunil",
            "request leave for one week and add date",
            "change leave duration to two days",
            "recipient name is dhulappa",
            "make it larger",
            "format it as a proper leave letter",
            "change the topic to applying for a vtu internship",
        ]

        for edit in test_edits:
            self.orch.chat(edit)
            task = self.orch.tasks[task_id]
            self.assertTrue(bool(task.params.get("recipient")), f"Recipient empty after edit: {edit}")
            self.assertTrue(bool(task.params.get("recipient_email")), f"Recipient email empty after edit: {edit}")
            self.assertTrue(bool(task.params.get("subject")), f"Subject empty after edit: {edit}")
            self.assertTrue(bool(task.params.get("body")), f"Body empty after edit: {edit}")

    def test_unrecognized_edit_concise_response_without_card_dump(self):
        """Unrecognized edit returns a concise message without dumping the approval card options wall."""
        self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]
        old_body = self.orch.tasks[task_id].params["body"]

        resp = self.orch.chat("quantum algorithmic teleportation hyperdrive")
        self.assertNotIn("EMAIL ACTION APPROVAL REQUIRED", resp["message"])
        self.assertIn("couldn't identify the specific change", resp["message"].lower())
        # Body remains uncorrupted
        self.assertEqual(self.orch.tasks[task_id].params["body"], old_body)

    def test_direct_draft_edit_and_stale_hash_protection(self):
        """Direct edit via UI composer updates draft and invalidates older approval hashes."""
        self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]
        h1 = self.orch.tasks[task_id].params["approval_hash"]

        # Direct edit simulating user typing in composer fields
        edit_res = self.orch.edit_pending_draft(
            task_id=task_id,
            subject="Directly Edited Subject",
            body="Dear Dhulappa,\n\nDirectly updated content.\n\nSincerely,\nSunil",
        )
        self.assertTrue(edit_res.get("ok"))
        h2 = self.orch.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(h1, h2)

        # Stale approval rejection
        stale_res = self.orch.approve(task_id, approved=True, approval_hash=h1)
        self.assertIn("error", stale_res)
        self.assertTrue("mismatch" in stale_res["error"].lower() or "invalidated" in stale_res["error"].lower())


if __name__ == "__main__":
    unittest.main()
