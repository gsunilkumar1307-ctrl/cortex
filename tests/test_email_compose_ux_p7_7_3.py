"""Deterministic regression test suite for CORTEX P7.7.3 Live Email Editing Regression & Composer State Integrity Remediation.

Covers:
1. Scenario A: Self leave application with 10 sequential conversational edits.
   - Single task ID maintained across turns.
   - Sequential state_version increments from 1 to 11.
   - Recipient (TO) and subject are canonical, valid, and never blank or corrupted ('myself for' eliminated).
   - Initial turn gives creation notice; conversational edits give concise feedback without duplicate notices.
2. Scenario B: Pentagon Space internship workflow.
   - Initial: "Send mail to nishakindalkar@gmail.com to apply for internship at Pentagon Space."
   - Edit 1: "Make it large." (Correctly recognized as expansion, dynamically addresses Pentagon Space and Nisha, no generic VTU leakage).
   - Edit 2: "Tell her to apply for internship within a week." (Correctly recognized as directive/deadline, formats polite directive into body).
   - No duplicate draft-ready announcements across edit turns.
   - TO and SUBJECT fields remain fully populated and valid throughout.
3. Cryptographic hash integrity and security gate compliance.
"""

import unittest
from backend.agent.email_engine import EmailEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus


class TestEmailComposeUXP773(unittest.TestCase):
    """P7.7.3 Live Email Editing Regression & State Integrity Tests."""

    def setUp(self):
        self.engine = EmailEngine()
        self.orch = CortexOrchestrator()

    def test_scenario_a_self_leave_10_turn_integrity(self):
        """Verifies Scenario A 10-turn lifecycle with non-blank fields and strict versioning."""
        # Turn 1: Initial Draft
        resp1 = self.orch.chat("send mail to myself for requesting a leave permission")
        self.assertIn("task_id", self.orch.pending_action)
        task_id = self.orch.pending_action["task_id"]
        t1 = self.orch.tasks[task_id]

        self.assertEqual(t1.status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(t1.state_version, 1)
        # Recipient must be canonical email, never 'myself for'
        self.assertEqual(t1.params.get("recipient"), "gsunilkumar1307@gmail.com")
        self.assertEqual(t1.params.get("recipient_email"), "gsunilkumar1307@gmail.com")
        self.assertIn("leave", t1.params.get("subject", "").lower())
        self.assertIsNotNone(t1.params.get("draft"))
        self.assertEqual(t1.params["draft"].get("recipient"), "gsunilkumar1307@gmail.com")

        # Initial turn has the full creation announcement
        self.assertIn("Draft created and saved to your mailbox", resp1["message"])

        steps = [
            ("make it more formal and friendly tone", 2, "formal and friendly"),
            ("recipient name is sunil", 3, "Sunil"),
            ("make it short", 4, "short"),
            ("make the leave permission for 1 week", 5, "1 week"),
            ("change leave duration to two days", 6, "two days"),
            ("recipient name is Dhulappa", 7, "Dhulappa"),
            ("make it larger", 8, "Expanded"),
            ("format it as a proper leave letter", 9, "Leave Application"),
            ("change the topic to applying for a VTU internship", 10, "VTU"),
        ]

        for prompt, expected_version, expected_feedback_fragment in steps:
            resp = self.orch.chat(prompt)
            task = self.orch.tasks[task_id]

            # Task ID stability
            self.assertEqual(self.orch.pending_action["task_id"], task_id)
            self.assertEqual(task.id, task_id)

            # State version incrementation
            self.assertEqual(task.state_version, expected_version)

            # Concise feedback without duplicate creation notices
            self.assertNotIn("Draft created and saved to your mailbox", resp["message"])
            self.assertIn(expected_feedback_fragment.lower(), resp["message"].lower())

            # TO, SUBJECT, BODY, DRAFT are NEVER empty or blank
            self.assertEqual(task.params.get("recipient"), "gsunilkumar1307@gmail.com")
            self.assertEqual(task.params.get("recipient_email"), "gsunilkumar1307@gmail.com")
            self.assertTrue(bool(task.params.get("subject")), f"Subject empty on '{prompt}'")
            self.assertTrue(bool(task.params.get("formatted_body")), f"Body empty on '{prompt}'")
            self.assertIsNotNone(task.params.get("draft"))

        # Final state check on Turn 10
        final_task = self.orch.tasks[task_id]
        self.assertEqual(final_task.params["subject"], "Application for VTU Internship")
        self.assertTrue(final_task.params["formatted_body"].startswith("Dear Dhulappa,"))
        self.assertIn("internship", final_task.params["formatted_body"].lower())

    def test_scenario_b_pentagon_space_internship_workflow(self):
        """Verifies Scenario B: initial draft -> 'Make it large.' -> directive with deadline."""
        # Turn 1: Initial Draft
        resp1 = self.orch.chat("Send mail to nishakindalkar@gmail.com to apply for internship at Pentagon Space.")
        self.assertIn("task_id", self.orch.pending_action)
        task_id = self.orch.pending_action["task_id"]
        t1 = self.orch.tasks[task_id]

        self.assertEqual(t1.status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(t1.state_version, 1)
        self.assertEqual(t1.params["recipient"], "nishakindalkar@gmail.com")
        self.assertEqual(t1.params["recipient_email"], "nishakindalkar@gmail.com")
        self.assertIn("internship", t1.params["subject"].lower())
        self.assertIn("Draft created and saved to your mailbox", resp1["message"])

        # Turn 2: "Make it large."
        resp2 = self.orch.chat("Make it large.")
        t2 = self.orch.tasks[task_id]

        # Must NOT be an unrecognized edit or re-announcement
        self.assertNotIn("couldn't identify the specific change", resp2["message"].lower())
        self.assertNotIn("Draft created and saved to your mailbox", resp2["message"])
        self.assertIn("expanded", resp2["message"].lower())

        # Version must increment
        self.assertEqual(t2.state_version, 2)
        self.assertEqual(t2.id, task_id)

        # Fields must remain intact
        self.assertEqual(t2.params["recipient"], "nishakindalkar@gmail.com")
        self.assertEqual(t2.params["recipient_email"], "nishakindalkar@gmail.com")
        self.assertTrue(bool(t2.params["subject"]))
        self.assertIsNotNone(t2.params.get("draft"))

        # Body must address Nisha and specify Pentagon Space, NOT VTU!
        body2 = t2.params["formatted_body"]
        self.assertTrue(body2.startswith("Dear Nisha,"), f"Expected salutation to start with 'Dear Nisha,', got:\n{body2[:40]}")
        self.assertIn("Pentagon Space", body2)
        self.assertNotIn("VTU", body2)

        # Turn 3: "Tell her to apply for internship within a week."
        resp3 = self.orch.chat("Tell her to apply for internship within a week.")
        t3 = self.orch.tasks[task_id]

        # Must NOT be an unrecognized edit or re-announcement
        self.assertNotIn("couldn't identify the specific change", resp3["message"].lower())
        self.assertNotIn("Draft created and saved to your mailbox", resp3["message"])
        self.assertIn("instruction", resp3["message"].lower())

        # Version must increment
        self.assertEqual(t3.state_version, 3)
        self.assertEqual(t3.id, task_id)

        # Fields must remain intact
        self.assertEqual(t3.params["recipient"], "nishakindalkar@gmail.com")
        self.assertEqual(t3.params["recipient_email"], "nishakindalkar@gmail.com")
        self.assertTrue(bool(t3.params["subject"]))

        # Body must include the polite directive
        body3 = t3.params["formatted_body"]
        self.assertIn("Please ensure to apply for internship within a week.", body3)
        self.assertIn("Pentagon Space", body3)
        self.assertTrue(body3.startswith("Dear Nisha,"))
        self.assertIn("Sincerely,", body3)

    def test_security_hash_recalculated_on_each_edit(self):
        """Verifies that each conversational edit generates a new, distinct cryptographic approval hash."""
        self.orch.chat("Send mail to nishakindalkar@gmail.com to apply for internship at Pentagon Space.")
        task_id = self.orch.pending_action["task_id"]
        h1 = self.orch.tasks[task_id].params["approval_hash"]

        self.orch.chat("Make it large.")
        h2 = self.orch.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(h1, h2)

        self.orch.chat("Tell her to apply for internship within a week.")
        h3 = self.orch.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(h2, h3)


if __name__ == "__main__":
    unittest.main()
