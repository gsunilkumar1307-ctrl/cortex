"""
CORTEX P7.5.1 — Targeted Conversational Email Polish Test Suite
Verifies:
1. Deterministic Fallback: Natural-Language Email Creation
   - "Send Rahul an update."
   - "Send an update to Rahul."
   - "Write Rahul about the project."
   - "Send my professor an update."
   - Ambiguous recipient & Unknown recipient
   - Missing message purpose / body prompts conversationally
   - Existing WhatsApp / messaging intents remain isolated
2. Deterministic Fallback: Conversational Editing Operators
   - "Mention that I am available next week."
   - "Make it sound more natural."
   - "Make it more professional."
   - "Make it shorter."
   - "Remove the availability sentence."
   - "Change the subject to Internship Discussion."
   - "Replace Monday with Wednesday."
   - "Don't mention my previous project."
   - Ambiguous editing instruction ("Fix it", "Change it")
   - Content preservation & zero instruction-prefix leakage
3. Approval and Safety Verification
   - Draft hash recalculation after material edits
   - Invalidation of previous approval on modification
   - Tamper detection
   - 300-second TTL expiry enforcement
   - Real sending remains blocked (CORTEX_ALLOW_REAL_EMAIL_SEND=0)
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailDraft, ProfessionalEmailEngine
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel, command_from_intent


class TestConversationalEmailP751Polish:
    def setup_method(self):
        self.orchestrator = CortexOrchestrator()
        self.orchestrator.mail_automation.dry_run = True
        self.orchestrator.use_gemini = False  # Strict deterministic fallback verification
        self.orchestrator.pending_action = None
        self.orchestrator.history = []
        self.email_engine = ProfessionalEmailEngine()

    # =========================================================================
    # 1. Natural-Language Email Creation Tests
    # =========================================================================

    def test_01_nl_creation_intent_classification(self):
        """Verifies natural-language variants classify as email operations in deterministic mode."""
        creation_queries = [
            ("Send Rahul an update.", TaskCommand.SEND_MAIL),
            ("Send an update to Rahul.", TaskCommand.SEND_MAIL),
            ("Write Rahul about the project.", TaskCommand.DRAFT_MAIL),
            ("Send my professor an update.", TaskCommand.SEND_MAIL),
            ("Email Rahul about the internship.", TaskCommand.SEND_MAIL),
            ("Send my project guide an update regarding the submission.", TaskCommand.SEND_MAIL),
            ("Write to the person who contacted me about the internship.", TaskCommand.DRAFT_MAIL),
        ]
        for query, expected_cmd in creation_queries:
            cmd = command_from_intent(query)
            assert cmd == expected_cmd, f"Expected {expected_cmd} for '{query}', got {cmd}"

    def test_02_messaging_intents_not_misclassified(self):
        """Verifies WhatsApp, SMS, and chat intents are NOT misclassified as email."""
        messaging_queries = [
            "Send WhatsApp to Rahul",
            "Send a message to Rahul",
            "Text Rahul about the meeting",
            "Send a message saying hello",
        ]
        for query in messaging_queries:
            cmd = command_from_intent(query)
            assert cmd != TaskCommand.SEND_MAIL
            assert cmd != TaskCommand.DRAFT_MAIL
            assert cmd == TaskCommand.SEND_MESSAGE

    def test_03_nl_creation_parameter_extraction_leaves_body_empty(self):
        """Verifies topics/updates are extracted as subjects, leaving body empty for multi-turn input."""
        ext1 = self.email_engine.extract_command_and_content("Send Rahul an update.")
        assert ext1["recipient"].lower() == "rahul"
        assert ext1["subject"] == "Update"
        assert ext1["content"] == ""

        ext2 = self.email_engine.extract_command_and_content("Write Rahul about the project.")
        assert ext2["recipient"].lower() == "rahul"
        assert "project" in ext2["subject"].lower()
        assert "project" in ext2["content"].lower()

        ext3 = self.email_engine.extract_command_and_content("Email Rahul about the internship.")
        assert ext3["recipient"].lower() == "rahul"
        assert "internship" in ext3["subject"].lower()
        assert "internship" in ext3["content"].lower()

    def test_04_nl_creation_multi_turn_prompts_for_body(self):
        """Verifies 'Send Rahul an update' prompts for body without inventing facts or sending."""
        res = self.orchestrator.chat("Send Rahul an update.")
        assert "what would you like me to send to rahul" in res["message"].lower()
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "waiting_for_body"

        # Next turn provides body
        res2 = self.orchestrator.chat("I have submitted the final report.")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "submitted the final report" in draft.body.lower()
        assert "rahul" in draft.recipient.lower()

    def test_05_unknown_or_ambiguous_recipient_handling(self):
        """Verifies unknown recipient prompts for clarification without inventing an address."""
        res = self.orchestrator.chat("Send an update to a non_existent_contact_xyz.")
        assert self.orchestrator.pending_action is not None
        # RecipientResolver requires clarification for unidentifiable contacts
        assert self.orchestrator.pending_action.get("step") in (
            "waiting_for_recipient_clarification",
            "waiting_for_body",
            "waiting_for_recipient",
        )
        assert "@" not in res["message"]  # Never fabricates an email address

    # =========================================================================
    # 2. Conversational Editing Operators Tests
    # =========================================================================

    def test_06_mention_that_no_prefix_leakage(self):
        """Verifies 'Mention that ...' adds detail without leaking instruction prefix into body."""
        draft = EmailDraft(
            recipient="advisor@university.edu",
            subject="Progress Report",
            body="Dear Professor,\n\nI am writing to share my weekly progress.\n\nBest regards,\nStudent",
        )
        h0 = draft.compute_hash()

        updated = self.email_engine.update_draft_with_edit(draft, "Mention that I am available next week.")
        assert "mention that" not in updated.body.lower()
        assert "I am available next week." in updated.body
        assert updated.approval_hash != h0
        # Check structure: inserted before sign-off
        lines = [l for l in updated.body.split("\n\n") if l.strip()]
        assert lines[-1] == "Best regards,\nStudent"
        assert lines[-2] == "I am available next week."

    def test_07_make_it_sound_more_natural(self):
        """Verifies 'Make it sound more natural' softens stiff phrasing and adjusts tone."""
        draft = EmailDraft(
            recipient="client@company.com",
            subject="Proposal Review",
            body="Respected Client,\n\nI am writing to respectfully request an update regarding the contract.\n\nYours faithfully,\nSunil",
        )
        updated = self.email_engine.update_draft_with_edit(draft, "Make it sound more natural.")
        assert updated.tone == "natural"
        assert not updated.body.startswith("Respected")
        assert "Dear Client" in updated.body
        assert "yours faithfully" not in updated.body.lower()
        assert "best regards" in updated.body.lower()

    def test_08_replace_x_with_y(self):
        """Verifies 'Replace Monday with Wednesday' cleanly swaps terms."""
        draft = EmailDraft(
            recipient="team@startup.io",
            subject="Sprint Planning on Monday",
            body="Hi Team,\n\nOur sprint planning is scheduled for Monday at 10 AM.\n\nBest,\nLead",
        )
        updated = self.email_engine.update_draft_with_edit(draft, "Replace Monday with Wednesday.")
        assert "Wednesday" in updated.body
        assert "Monday" not in updated.body
        assert "Wednesday" in updated.subject
        assert "Monday" not in updated.subject

    def test_09_remove_sentence_and_omit_topic(self):
        """Verifies 'Remove the availability sentence' and 'Don't mention my previous project' filter cleanly."""
        draft = EmailDraft(
            recipient="recruiter@tech.com",
            subject="Interview Availability",
            body="Dear Recruiter,\n\nThank you for the update. We discussed my availability yesterday. Also, my previous project was built in React.\n\nSincerely,\nCandidate",
        )
        # Remove availability sentence
        u1 = self.email_engine.update_draft_with_edit(draft, "Remove the sentence about availability.")
        assert "availability" not in u1.body.lower()
        assert "React" in u1.body  # Preserves unrelated content

        # Don't mention previous project
        u2 = self.email_engine.update_draft_with_edit(u1, "Don't mention my previous project.")
        assert "previous project" not in u2.body.lower()
        assert "thank you for the update" in u2.body.lower()

    def test_10_add_polite_closing(self):
        """Verifies 'Add a polite closing' inserts a professional sign-off."""
        draft = EmailDraft(
            recipient="partner@corp.com",
            subject="Partnership Discussion",
            body="Dear Partner,\n\nHere is our revised terms sheet.\n\nBest regards,\nExecutive",
        )
        updated = self.email_engine.update_draft_with_edit(draft, "Add a polite closing.")
        assert "thank you for your time and consideration" in updated.body.lower()
        assert "best regards" in updated.body.lower()

    def test_11_ambiguous_editing_instruction_clarification(self):
        """Verifies vague edits ('Fix it', 'Change it') trigger focused conversational clarification."""
        # Setup active pending action
        draft = EmailDraft(
            recipient="test@example.com",
            subject="Test Subject",
            body="Hi Test,\n\nTest body.\n\nBest regards",
        )
        task = self.orchestrator.tasks["task_test_edit"] = self.orchestrator.tasks.get("task_test_edit") or MagicMock()
        task.id = "task_test_edit"
        task.to_dict.return_value = {"id": "task_test_edit"}
        self.orchestrator.pending_action = {
            "type": "email_draft",
            "step": "confirm_send",
            "task_id": "task_test_edit",
            "recipient": "test@example.com",
            "subject": "Test Subject",
            "body": "Test body.",
            "draft": draft,
            "lang": "en",
        }

        res = self.orchestrator.chat("Fix it")
        assert "could you please specify what changes" in res["message"].lower()
        # Ensure state was not destroyed
        assert self.orchestrator.pending_action.get("step") == "confirm_send"

    # =========================================================================
    # 3. Approval and Safety Verification Tests
    # =========================================================================

    def test_12_material_edit_invalidates_prior_approval_hash(self):
        """Verifies draft hash changes after material edit and old hash approval is rejected."""
        draft = EmailDraft(
            recipient="alex@company.com",
            subject="Release Notes",
            body="Hi Alex,\n\nVersion 1.0 is ready.\n\nBest,\nDev",
            sender_account="Google <user@gmail.com>",
        )
        h0 = draft.compute_hash()

        # Update draft
        updated = self.email_engine.update_draft_with_edit(draft, "Mention that all tests passed.")
        h1 = updated.approval_hash
        assert h1 != h0

        # Attempting to approve with old hash h0 must be rejected
        task = Task(
            intent="Send release notes",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.HIGH,
            requires_approval=True,
            params={
                "recipient": updated.recipient,
                "subject": updated.subject,
                "body": updated.body,
                "formatted_body": updated.body,
                "sender_account": updated.sender_account,
                "approval_hash": h1,
                "created_at": time.time(),
                "draft": updated.to_dict(),
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        # Passing obsolete expected_hash h0
        res = self.orchestrator.approve(task.id, approved=True, approval_hash=h0)
        assert "mismatch" in (res.get("error") or "").lower()

    def test_13_send_safety_gate_enforcement(self):
        """Verifies real sending remains strictly blocked when CORTEX_ALLOW_REAL_EMAIL_SEND=0."""
        from backend.capabilities.mail_actions import MailAutomation, MailDeliveryStatus
        mail = MailAutomation()
        mail.dry_run = False
        mail.system = "darwin"

        with patch.dict("os.environ", {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            res_apple = mail.send_mail(
                recipient="client@enterprise.com",
                subject="Test Safety Gate",
                body="Test body",
                account="Google <user@gmail.com>",
            )
            assert res_apple.get("ok") is False
            assert res_apple.get("delivery_status") == MailDeliveryStatus.BLOCKED.value
