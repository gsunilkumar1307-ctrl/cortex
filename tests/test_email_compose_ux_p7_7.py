"""
Test Suite for Cortex Agent — P7.7 Mail Compose, Review & Approval UX
Phase: P7.7 Email Composition Experience & Approval UX

Validates:
1. Direct draft editing via structured editor updates recipient, subject, body, CC, BCC, and attachments.
2. Direct editing updates orchestrator.pending_action and task.params without competing states.
3. Cryptographic approval invalidation: prior approval hash is rejected; fresh hash succeeds.
4. Direct edit + Approve cycle (auto-save and approve with recalculated hash).
5. Conversational editing updates the canonical task params and updates approval hash.
6. Cancellation clears pending action, invalidates hash, and marks task canceled.
7. Security policy: sensitive attachment blocking during draft edit.
8. Replay protection: approval cannot be consumed twice.
"""

import unittest
from backend.core.contracts import TaskCommand, TaskStatus
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailDraft


class TestEmailComposeUXP77(unittest.TestCase):
    def setUp(self):
        self.orch = CortexOrchestrator()

    def test_direct_draft_editing_updates_all_fields_and_recomputes_hash(self):
        """Editing recipient, subject, body, CC, BCC, sender_account updates task.params and recomputes hash."""
        resp = self.orch.chat("send email to rahul@example.com saying please share the project deck")
        task_id = resp["task"]["id"]
        task = self.orch.tasks[task_id]
        initial_hash = task.params["approval_hash"]

        # User edits all fields directly in the composer card
        res = self.orch.edit_pending_draft(
            task_id=task_id,
            recipient="rahul.internships@university.edu",
            subject="Updated: Inquiry Regarding Summer Internship",
            body="Dear Rahul,\n\nI am writing to inquire about upcoming summer internship opportunities.\n\nBest regards,\nSunil",
            sender_account="sunil.student@university.edu",
            cc=["careers@university.edu", "mentor@example.com"],
            bcc=["archive@university.edu"],
            attachments=["resume_sunil.pdf"],
        )

        self.assertTrue(res["ok"])
        self.assertEqual(task.params["recipient"], "rahul.internships@university.edu")
        self.assertEqual(task.params["recipient_email"], "rahul.internships@university.edu")
        self.assertEqual(task.params["subject"], "Updated: Inquiry Regarding Summer Internship")
        self.assertIn("summer internship opportunities", task.params["body"])
        self.assertEqual(task.params["sender_account"], "sunil.student@university.edu")
        self.assertEqual(task.params["cc"], ["careers@university.edu", "mentor@example.com"])
        self.assertEqual(task.params["bcc"], ["archive@university.edu"])
        self.assertEqual(task.params["attachments"], ["resume_sunil.pdf"])

        # Hash must be updated and match the exact EmailDraft.compute_hash()
        new_hash = task.params["approval_hash"]
        self.assertNotEqual(initial_hash, new_hash)

        expected_hash = EmailDraft(
            recipient="rahul.internships@university.edu",
            subject="Updated: Inquiry Regarding Summer Internship",
            body=task.params["body"],
            sender_account="sunil.student@university.edu",
            attachments=["resume_sunil.pdf"],
            cc=["careers@university.edu", "mentor@example.com"],
            bcc=["archive@university.edu"],
        ).compute_hash()
        self.assertEqual(new_hash, expected_hash)

    def test_direct_draft_editing_syncs_pending_action(self):
        """Structured edit must sync self.orch.pending_action so no split-brain state exists."""
        resp = self.orch.chat("send email to priya@tech.co saying let's connect tomorrow")
        task_id = resp["task"]["id"]

        self.assertIsNotNone(self.orch.pending_action)
        self.assertEqual(self.orch.pending_action.get("task_id"), task_id)

        # Edit recipient and body
        self.orch.edit_pending_draft(
            task_id=task_id,
            recipient="priya.lead@tech.co",
            subject="Discussion on Tech Collaboration",
            body="Hi Priya,\n\nLet's connect tomorrow at 3 PM to discuss the collaboration.\n\nRegards,\nSunil",
            cc=["team@tech.co"],
        )

        pending = self.orch.pending_action
        self.assertEqual(pending["recipient"], "priya.lead@tech.co")
        self.assertEqual(pending["recipient_email"], "priya.lead@tech.co")
        self.assertEqual(pending["subject"], "Discussion on Tech Collaboration")
        self.assertIn("3 PM", pending["body"])
        self.assertEqual(pending["cc"], ["team@tech.co"])

    def test_prior_approval_hash_invalidation_after_edit(self):
        """Attempting to approve using the old hash after editing must be rejected."""
        resp = self.orch.chat("Send Rahul a mail asking about internship opportunities.")
        task_id = self.orch.pending_action["task_id"]
        old_hash = self.orch.tasks[task_id].params["approval_hash"]

        # Edit draft content
        self.orch.edit_pending_draft(
            task_id=task_id,
            subject="Revised Subject - Internship Inquiry",
            body="Dear Rahul,\n\nHere is my revised application note.\n\nSincerely,\nSunil",
        )

        # Try to approve with stale old_hash
        reject_res = self.orch.approve(task_id, approved=True, approval_hash=old_hash)
        self.assertIn("error", reject_res)
        error_msg = reject_res["error"].lower()
        self.assertTrue(
            "invalidated" in error_msg or "mismatch" in error_msg or "hash" in error_msg
        )

    def test_fresh_approval_hash_succeeds_after_direct_edit(self):
        """Approving with the freshly recalculated hash after editing succeeds in authorization."""
        resp = self.orch.chat("send email to test@domain.com saying meeting confirmed")
        task_id = resp["task"]["id"]

        # Edit draft
        edit_res = self.orch.edit_pending_draft(
            task_id=task_id,
            subject="Meeting Confirmed for 2 PM",
            body="The meeting is confirmed for 2 PM in Conference Room A.",
        )
        self.assertTrue(edit_res["ok"])
        fresh_hash = edit_res["task"]["params"]["approval_hash"]

        # Approve with fresh hash - authorization succeeds and consumes approval
        approve_res = self.orch.approve(task_id, approved=True, approval_hash=fresh_hash)
        self.assertNotIn("mismatch", (approve_res.get("error") or "").lower())
        self.assertNotIn("invalidated", (approve_res.get("error") or "").lower())
        # Execution confirms authorization passed and approval was consumed
        self.assertTrue(approve_res.get("params", {}).get("approval_consumed") or approve_res.get("status") in ("executing", "completed", "failed"))

    def test_cancellation_cleans_pending_action_and_task(self):
        """Canceling an email draft clears pending_action and marks task canceled."""
        resp = self.orch.chat("draft email to finance@domain.com saying invoice question")
        task_id = resp["task"]["id"]

        self.assertIsNotNone(self.orch.pending_action)

        cancel_res = self.orch.cancel(task_id)
        self.assertIn(cancel_res["status"], (TaskStatus.CANCELED.value, TaskStatus.CANCELED, "canceled", "cancelled"))
        self.assertIsNone(self.orch.pending_action)

    def test_conversational_editing_updates_canonical_params(self):
        """Conversational edit commands update the canonical draft params and re-bind hash."""
        resp = self.orch.chat("Send Rahul a mail asking about internship opportunities.")
        task_id = self.orch.pending_action["task_id"]
        initial_hash = self.orch.tasks[task_id].params["approval_hash"]

        # User converses: 'Make it more professional.'
        revised_resp = self.orch.chat("Make it more professional.")
        revised_task = self.orch.tasks[task_id]

        self.assertEqual(revised_task.id, task_id)
        revised_hash = revised_task.params.get("approval_hash")
        self.assertIsNotNone(revised_hash)
        self.assertNotEqual(initial_hash, revised_hash)

        # The body should be updated to formal tone
        self.assertTrue(
            "Dear" in revised_task.params.get("body", "") or
            "Sincerely" in revised_task.params.get("body", "") or
            "internship" in revised_task.params.get("body", "").lower()
        )

    def test_sensitive_attachment_security_guard(self):
        """Draft editor blocks attaching sensitive credentials or keys."""
        resp = self.orch.chat("send email to friend@test.com saying check this file")
        task_id = resp["task"]["id"]

        edit_res = self.orch.edit_pending_draft(
            task_id=task_id,
            attachments=[".env", "id_rsa"],
        )
        self.assertFalse(edit_res["ok"])
        self.assertIn("blocked", edit_res["error"].lower())

    def test_replay_protection_on_approved_email(self):
        """An approval cannot be consumed twice."""
        resp = self.orch.chat("send email to test2@domain.com saying hello")
        task_id = resp["task"]["id"]
        auth_hash = resp["task"]["params"]["approval_hash"]

        # First approval authorizes action and consumes token
        first_res = self.orch.approve(task_id, approved=True, approval_hash=auth_hash)
        self.assertTrue(first_res.get("params", {}).get("approval_consumed") or first_res.get("status") in ("executing", "completed", "failed"))

        # Replay attempt
        second_res = self.orch.approve(task_id, approved=True, approval_hash=auth_hash)
        self.assertTrue(
            "error" in second_res and (
                "replay" in second_res["error"].lower() or
                "already" in second_res["error"].lower() or
                "cannot approve" in second_res["error"].lower()
            )
        )


if __name__ == "__main__":
    unittest.main()
