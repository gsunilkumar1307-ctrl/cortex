"""Final Completion Sprint Test Suite for Cortex Mail Automation.

Verifies end-to-end reliability for project submission:
1. Scenario 1 (Failure A): User supplies text, then says 'send mail to myself'.
   - Context is retained from dialogue history.
   - Self identity resolved to gsunilkumar1307@gmail.com.
   - Approval card created without asking 'What would you like me to send to myself?'.
2. Scenario 2 (Failures B, C, E): College leave permission to attend a tech summit.
   - Clean, preposition-free subject: 'Request for Leave Permission to Attend Technology Summit'.
   - Academic tone & student request to attend summit.
   - 'Expand and formalize it' elaborates on academic learning and lecture catch-up,
     strictly omitting corporate deliverables/handover bottlenecks.
3. Scenario 3 (Failure F): Natural-language draft inspection & direct edits.
   - 'Check the recipient.' -> returns canonical recipient.
   - 'Check the subject.' -> returns clean subject.
   - 'Read the entire body.' -> returns full body without mutating draft.
   - 'Change the subject to ...' -> updates subject.
   - 'Replace the body with ...' -> updates body.
   - 'Send mail to myself' -> updates recipient to user's address.
4. Scenario 4: Real mailbox operations:
   - Account verification (Google <gsunilkumar1307@gmail.com>).
   - Real email reading & search capabilities.
"""

import unittest
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailEngine, RecipientContext
from backend.capabilities.mail_actions import MailAutomation
from backend.core.contracts import TaskStatus


class TestMailAutomationFinalSprint(unittest.TestCase):
    """End-to-End Final Sprint Verification Suite."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.orch.pending_action = None
        self.orch.tasks.clear()
        self.ee = EmailEngine()

    def test_scenario_1_self_send_context_retention(self):
        """User supplies an email body, then asks to send to myself."""
        # Turn 1: User types message body
        r1 = self.orch.chat("I would like to draft a formal request for 2 days leave due to a family emergency.")
        self.assertIsNotNone(r1.get("message"))

        # Turn 2: User says 'send mail to myself'
        r2 = self.orch.chat("send mail to myself")
        task_id = self.orch.pending_action.get("task_id") if self.orch.pending_action else None
        self.assertIsNotNone(task_id, "Pending action must exist after 'send mail to myself'")
        task = self.orch.tasks[task_id]

        self.assertIn(task.status, (TaskStatus.AWAITING_APPROVAL, TaskStatus.WAITING_APPROVAL))
        self.assertIn("gsunilkumar1307@gmail.com", task.params.get("recipient", ""))
        body = task.params.get("body", "")
        self.assertTrue(bool(body), "Draft body must not be empty")
        self.assertTrue(
            "emergency" in body.lower() or "leave" in body.lower(),
            f"Original intent context was lost: {body}"
        )
        self.assertNotIn("what would you like me to send to myself", r2.get("message", "").lower())

    def test_scenario_2_college_summit_leave_and_expansion(self):
        """College leave to attend technology summit generates academic tone and clean expansion."""
        # Step A: Subject Generation
        subj = self.ee.generate_subject(
            "Draft a leave permission email to my college to attend a technology summit.",
            RecipientContext(name="college", role="institution")
        )
        self.assertEqual(subj, "Request for Leave Permission to Attend Technology Summit")
        self.assertFalse(subj.endswith("From"), f"Invalid trailing preposition in subject: {subj}")

        # Step B: Turn 1
        r1 = self.orch.chat("Draft a leave permission email to my college to attend a technology summit.")
        # Step C: Turn 2 disambiguate recipient
        r2 = self.orch.chat("college@vtu.ac.in")

        task_id = self.orch.pending_action["task_id"]
        t2 = self.orch.tasks[task_id]
        self.assertEqual(t2.status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(t2.params.get("recipient"), "college@vtu.ac.in")
        self.assertIn("Technology Summit", t2.params.get("subject", ""))

        # Step D: Turn 3 'Expand and formalize it'
        r3 = self.orch.chat("Expand and formalize it.")
        t3 = self.orch.tasks[task_id]
        body3 = t3.params.get("formatted_body") or t3.params.get("body", "")

        # Strict Verification: No corporate drift
        self.assertNotIn("handover", body3.lower(), "Corporate handover phrase found in academic leave!")
        self.assertNotIn("bottlenecks", body3.lower(), "Corporate bottleneck phrase found in academic leave!")
        self.assertNotIn("team members", body3.lower(), "Corporate team deliverables found in academic leave!")
        self.assertTrue(
            "summit" in body3.lower() or "technology summit" in body3.lower(),
            f"Technology summit context missing: {body3}"
        )
        self.assertTrue(
            "coursework" in body3.lower() or "lectures" in body3.lower() or "academic" in body3.lower(),
            f"Academic learning context missing: {body3}"
        )

    def test_scenario_3_inspection_and_direct_replacements(self):
        """Inspection commands return accurate facts without draft mutation; direct edits modify draft."""
        self.orch.chat("Send mail to nishakindalkar@gmail.com to apply internship for pentagon space")
        task_id = self.orch.pending_action["task_id"]
        t1 = self.orch.tasks[task_id]
        hash_before = t1.params.get("approval_hash")

        # 1. Inspection: Check recipient
        r_rec = self.orch.chat("Check the recipient.")
        self.assertIn("nishakindalkar@gmail.com", r_rec.get("message", ""))
        self.assertEqual(t1.params.get("approval_hash"), hash_before, "Inspection must not alter hash")

        # 2. Inspection: Check subject
        r_sub = self.orch.chat("Check the subject.")
        self.assertIn("Inquiry regarding Internship Opportunities", r_sub.get("message", ""))

        # 3. Inspection: Read body
        r_bod = self.orch.chat("Read the entire body.")
        self.assertIn("pentagon space", r_bod.get("message", "").lower())

        # 4. Direct edit: Change subject
        r_sub_chg = self.orch.chat("Change the subject to Official Internship Application – Sunil Kumar")
        t_after_sub = self.orch.tasks[task_id]
        self.assertEqual(t_after_sub.params.get("subject"), "Official Internship Application – Sunil Kumar")

        # 5. Direct edit: Replace body
        new_text = "Dear Hiring Team,\n\nI am writing to formally submit my internship application.\n\nSincerely,\nSunil Kumar"
        self.orch.chat(f"Replace the body with {new_text}")
        t_after_bod = self.orch.tasks[task_id]
        self.assertEqual(t_after_bod.params.get("body"), new_text)

        # 6. Recipient edit: Send to myself
        self.orch.chat("Send mail to myself")
        t_after_self = self.orch.tasks[task_id]
        self.assertEqual(t_after_self.params.get("recipient"), "gsunilkumar1307@gmail.com")

    def test_scenario_4_real_mailbox_connectivity(self):
        """Connected mailbox accounts and reading capabilities are responsive and accurate."""
        ma = MailAutomation()
        accounts = ma.get_accounts()
        self.assertTrue(len(accounts) >= 1, "At least one connected mailbox account must be present")
        self.assertEqual(accounts[0].get("name"), "Google")
        self.assertEqual(accounts[0].get("email"), "gsunilkumar1307@gmail.com")

        # Read emails
        res = ma.read_mail(limit=3)
        self.assertTrue(res.get("ok"), f"read_mail failed: {res.get('message')}")
        self.assertTrue(len(res.get("emails", [])) > 0, "Connected mailbox should return emails")


if __name__ == "__main__":
    unittest.main()
