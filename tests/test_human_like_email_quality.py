"""
Cortex Agent — Human-Like Email Draft Quality Regression Suite
Validates:
1. Recipient-name handling: Never convert email usernames into human names;
   use verified contact names or neutral greeting "Hello,".
2. Subject line accuracy: Accurately reflects purpose; no unsolicited extension requests.
3. Body composition: Polished grammar, date normalization, clear salutation and sign-off.
4. Two-turn Acceptance Case:
   Turn 1: 'send mail to gsunilkumar1307@gmail.com'
   Turn 2: 'project presentation deadline is on 5 november'
   Expected:
   Recipient: gsunilkumar1307@gmail.com
   Subject: Project Presentation Deadline
   Body:
   Hello,

   The project presentation deadline is November 5.

   Best regards
5. Ambiguity handling: Bare intents prompt for clarification before draft finalization.
6. Approval & Security: Material changes invalidate approval hash; explicit approval required.
"""

import unittest
from unittest.mock import patch, MagicMock

from backend.agent.email_engine import (
    ProfessionalEmailEngine,
    EmailDraft,
    is_ambiguous_email_intent,
    polish_email_body_text,
)
from backend.agent.recipient_resolver import RecipientResolver
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus, TaskCommand


class TestHumanLikeEmailQuality(unittest.TestCase):
    def setUp(self):
        self.engine = ProfessionalEmailEngine()
        self.resolver = RecipientResolver()

    # -------------------------------------------------------------------------
    # 1. Recipient-Name Handling & Non-Inference
    # -------------------------------------------------------------------------
    def test_username_non_inference_greeting(self):
        """Never convert an email username such as 'gsunilkumar1307' into a presumed human name."""
        res = self.resolver.resolve("gsunilkumar1307@gmail.com")
        self.assertEqual(res.status, "resolved")
        self.assertEqual(res.recipient.email, "gsunilkumar1307@gmail.com")
        self.assertNotIn("Gsunilkumar", res.recipient.name)

        rec_ctx = self.engine.infer_recipient_context("gsunilkumar1307@gmail.com", "deadline update")
        self.assertFalse(rec_ctx.has_verified_name)
        self.assertEqual(rec_ctx.name, "")

        draft = self.engine.compose_email(
            raw_intent="send email to gsunilkumar1307@gmail.com saying update",
            recipient_raw="gsunilkumar1307@gmail.com",
            content="the project is progressing as scheduled",
        )
        self.assertNotIn("Gsunilkumar", draft.body)
        self.assertNotIn("Gsunilkumar1307", draft.body)
        self.assertTrue(draft.body.startswith("Hello,"))

    def test_verified_contact_name_preserved(self):
        """Resolve a greeting name only from a reliable contact record."""
        res = self.resolver.resolve("Dr. Shanmukha Nagaraj")
        self.assertEqual(res.status, "resolved")
        self.assertIn("Shanmukha", res.recipient.name)

        rec_ctx = self.engine.infer_recipient_context(
            f"{res.recipient.name} <{res.recipient.email}>",
            "meeting inquiry",
        )
        self.assertTrue(rec_ctx.has_verified_name)
        self.assertIn("Shanmukha", rec_ctx.name)

    def test_explicit_display_name_greeting(self):
        """Explicit display name in RFC format generates personalized greeting."""
        rec_ctx = self.engine.infer_recipient_context(
            "Sunil Kumar <gsunilkumar1307@gmail.com>",
            "project update",
        )
        self.assertTrue(rec_ctx.has_verified_name)
        self.assertEqual(rec_ctx.name, "Sunil Kumar")

        draft = self.engine.compose_email(
            raw_intent="update for Sunil",
            recipient_raw="Sunil Kumar <gsunilkumar1307@gmail.com>",
            content="we finished the tasks",
        )
        self.assertIn("Sunil Kumar", draft.body)

    # -------------------------------------------------------------------------
    # 2. Subject Line Matching Actual Intent
    # -------------------------------------------------------------------------
    def test_informational_deadline_does_not_request_extension(self):
        """Do not generate subjects such as 'Assignment Deadline Extension Request' unless explicitly requested."""
        rec_ctx = self.engine.infer_recipient_context("prof@rvce.edu.in", "deadline info")
        rec_ctx.role = "professor"

        # Informational statement about deadline
        subject_info = self.engine.generate_subject("project presentation deadline is on 5 november", rec_ctx)
        self.assertEqual(subject_info, "Project Presentation Deadline")
        self.assertNotIn("Extension", subject_info)

        # Informational submission
        subject_sub = self.engine.generate_subject("submission deadline is tomorrow", rec_ctx)
        self.assertEqual(subject_sub, "Submission Deadline")
        self.assertNotIn("Extension", subject_sub)

    def test_explicit_extension_request_subject_and_body(self):
        """Explicit request for extension generates extension subject and respectful body."""
        rec_ctx = self.engine.infer_recipient_context("prof@rvce.edu.in", "need extension")
        rec_ctx.role = "professor"

        subject = self.engine.generate_subject("requesting an extension on the assignment deadline", rec_ctx)
        self.assertIn("Extension Request", subject)

        draft = self.engine.compose_email(
            raw_intent="ask professor for deadline extension",
            recipient_raw="prof@rvce.edu.in",
            content="need an extension of one day for the assignment",
        )
        self.assertIn("respectfully request an extension", draft.body)

    # -------------------------------------------------------------------------
    # 3. Body Polishing & Date Formatting
    # -------------------------------------------------------------------------
    def test_polish_email_body_text_dates_and_grammar(self):
        """Date phrases and capitalization are cleanly polished."""
        raw1 = "project presentation deadline is on 5 november"
        polished1 = polish_email_body_text(raw1)
        self.assertEqual(polished1, "The project presentation deadline is November 5.")

        raw2 = "meeting is on 15th december at office"
        polished2 = polish_email_body_text(raw2)
        self.assertEqual(polished2, "The meeting is December 15 at office.")

        raw3 = "i will arrive in delhi on 12 october"
        polished3 = polish_email_body_text(raw3)
        self.assertEqual(polished3, "I will arrive in delhi on October 12.")

    # -------------------------------------------------------------------------
    # 4. Ambiguity Clarification
    # -------------------------------------------------------------------------
    def test_ambiguity_detection(self):
        """Single vague words are flagged as ambiguous."""
        self.assertTrue(is_ambiguous_email_intent("deadline"))
        self.assertTrue(is_ambiguous_email_intent("urgent"))
        self.assertTrue(is_ambiguous_email_intent("meeting"))
        self.assertTrue(is_ambiguous_email_intent("check this"))
        self.assertFalse(is_ambiguous_email_intent("project presentation deadline is on 5 november"))
        self.assertFalse(is_ambiguous_email_intent("i will be late due to traffic"))

    def test_orchestrator_prompts_clarification_for_ambiguous_body(self):
        """Orchestrator enters NEED_INFO and prompts for clarification when body is ambiguous."""
        orc = CortexOrchestrator()
        orc.chat("send mail to gsunilkumar1307@gmail.com")
        r2 = orc.chat("deadline")

        self.assertIn("clarify what specific message", r2["message"])
        self.assertEqual(r2["task"]["status"], TaskStatus.NEED_INFO.value)

    # -------------------------------------------------------------------------
    # 5. Two-Turn Acceptance Case
    # -------------------------------------------------------------------------
    def test_acceptance_case_two_turn_workflow(self):
        """
        Acceptance test case:
        Turn 1: send mail to gsunilkumar1307@gmail.com
        Turn 2: project presentation deadline is on 5 november
        Expected output:
        Recipient: gsunilkumar1307@gmail.com
        Subject: Project Presentation Deadline
        Body:
        Hello,

        The project presentation deadline is November 5.

        Best regards
        """
        orc = CortexOrchestrator()

        # Turn 1
        r1 = orc.chat("send mail to gsunilkumar1307@gmail.com")
        self.assertIn("gsunilkumar1307@gmail.com", r1["message"])
        self.assertEqual(r1["task"]["status"], TaskStatus.NEED_INFO.value)

        # Turn 2
        r2 = orc.chat("project presentation deadline is on 5 november")
        task = r2["task"]
        params = task.get("params", {})

        # 1. Recipient
        self.assertEqual(params.get("recipient_email"), "gsunilkumar1307@gmail.com")

        # 2. Subject
        self.assertEqual(params.get("subject"), "Project Presentation Deadline")

        # 3. Body
        expected_body = "Hello,\n\nThe project presentation deadline is November 5.\n\nBest regards"
        self.assertEqual(params.get("formatted_body"), expected_body)

        # 4. Status & Approval
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertTrue(task.get("requiresApproval", task.get("requires_approval")))
        self.assertTrue(len(params.get("approval_hash", "")) == 64)

    # -------------------------------------------------------------------------
    # 6. Approval Invalidation & Security
    # -------------------------------------------------------------------------
    def test_draft_edit_invalidates_approval_hash(self):
        """Material change to draft body or subject recomputes a fresh SHA-256 hash."""
        draft = self.engine.compose_email(
            raw_intent="send mail to gsunilkumar1307@gmail.com",
            recipient_raw="gsunilkumar1307@gmail.com",
            content="project presentation deadline is on 5 november",
        )
        initial_hash = draft.approval_hash
        self.assertEqual(len(initial_hash), 64)

        # Modify draft body
        updated_draft = self.engine.update_draft_with_edit(draft, "change deadline to November 10")
        self.assertNotEqual(updated_draft.approval_hash, initial_hash)
        self.assertEqual(len(updated_draft.approval_hash), 64)


if __name__ == "__main__":
    unittest.main()
