import pytest
from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailDraft, ProfessionalEmailEngine
from backend.agent.recipient_resolver import RecipientResolver
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records, _draft_records, _sent_records
from backend.core.contracts import TaskCommand, TaskStatus, RiskLevel


@pytest.fixture(autouse=True)
def cleanup():
    clear_mail_records()
    yield
    clear_mail_records()


class TestRecipientResolution:
    def test_resolve_named_contact(self):
        resolver = RecipientResolver(mail_automation=MailAutomation(dry_run=True))
        res = resolver.resolve("Rahul", full_message="Draft an email to Rahul about the project.")
        assert res.status == "resolved"
        assert res.recipient is not None
        assert "rahul@example.com" in res.recipient.email.lower()

    def test_resolve_project_guide_role(self):
        resolver = RecipientResolver(mail_automation=MailAutomation(dry_run=True))
        res = resolver.resolve("my project guide", full_message="Write an email to my project guide.")
        assert res.status == "resolved"
        assert res.recipient is not None
        assert "prof.smith@university.edu" in res.recipient.email.lower()
        assert "guide" in res.recipient.role.lower() or "professor" in res.recipient.role.lower()

    def test_resolve_direct_email_address(self):
        resolver = RecipientResolver(mail_automation=MailAutomation(dry_run=True))
        res = resolver.resolve("test.recipient@domain.org", full_message="Create an email to test.recipient@domain.org")
        assert res.status == "resolved"
        assert res.recipient is not None
        assert res.recipient.email == "test.recipient@domain.org"

    def test_ambiguous_recipient_requires_clarification(self):
        resolver = RecipientResolver()
        # HOD matches both RVCE and BMSCE in known directory
        res = resolver.resolve("HOD", full_message="Send an email to HOD")
        assert res.status in ("multiple_candidates", "need_clarification")
        assert res.clarification_prompt != ""
        assert res.recipient is None

    def test_never_invents_unknown_recipient_email(self):
        resolver = RecipientResolver(mail_automation=MailAutomation(dry_run=True))
        res = resolver.resolve("Unknown Stranger Nonexistent", full_message="Draft email to Unknown Stranger Nonexistent")
        assert res.status == "need_clarification"
        assert res.recipient is None
        assert "couldn't confidently identify" in res.clarification_prompt.lower() or "clarify" in res.clarification_prompt.lower() or "share the email" in res.clarification_prompt.lower()


class TestExecutionConstraintSeparation:
    def test_do_not_send_stripped_from_content(self):
        engine = ProfessionalEmailEngine()
        res = engine.extract_command_and_content("Draft an email to rahul@example.com saying the project is ready. Do not send it.")
        assert "do not send" not in res["content"].lower()
        assert "project is ready" in res["content"].lower()

    def test_keep_as_draft_stripped_from_content(self):
        engine = ProfessionalEmailEngine()
        res = engine.extract_command_and_content("Draft an email to rahul@example.com saying meeting is scheduled at 2 PM. Keep it as a draft.")
        assert "keep it as a draft" not in res["content"].lower()
        assert "keep as draft" not in res["content"].lower()
        assert "meeting is scheduled" in res["content"].lower()

    def test_gmail_directive_detected_and_account_set(self):
        engine = ProfessionalEmailEngine()
        res = engine.extract_command_and_content("Draft an email in Gmail to rahul@example.com about the project.")
        assert "gmail" in res["account"].lower()
        assert res["recipient"] == "rahul@example.com"


class TestAppleMailDraftAndRevisionWorkflow:
    def test_apple_mail_draft_creation_and_revisions(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        
        # 1. Draft email
        step1 = orc.chat("Draft an email in Apple Mail to Rahul saying our project presentation is scheduled for 10 AM. Keep it as a draft.")
        assert "rahul@example.com" in step1["task"]["params"]["recipient_email"]
        assert orc.pending_action is not None
        assert orc.pending_action["step"] == "confirm_send"
        initial_hash = orc.pending_action["draft"].approval_hash
        
        # Verify Apple Mail draft stored
        verif = orc.automation.mail.verify_draft_created("rahul@example.com", orc.pending_action["subject"])
        assert verif["verified"] is True
        initial_draft_count = len([d for d in _draft_records if d.get("provider") == "apple_mail"])
        assert initial_draft_count == 1

        # 2. Revision: "Change the meeting time to 3 PM."
        step2 = orc.chat("Change the meeting time to 3 PM.")
        assert orc.pending_action is not None
        assert "3 PM" in orc.pending_action["draft"].body
        # Check no duplicate drafts accumulated in records
        apple_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
        assert len(apple_drafts) == 1
        assert "3 PM" in apple_drafts[0]["body"]

        # 3. Revision: "Use a more professional tone."
        step3 = orc.chat("Use a more professional tone.")
        assert orc.pending_action["draft"].tone == "professional"
        assert "Dear" in orc.pending_action["draft"].body or "Sincerely" in orc.pending_action["draft"].body
        apple_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
        assert len(apple_drafts) == 1

        # 4. Revision: "Make it shorter."
        step4 = orc.chat("Make it shorter.")
        assert orc.pending_action["draft"].tone in ("concise", "formal_concise")
        apple_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
        assert len(apple_drafts) == 1

        # 5. Revision: "Add this paragraph: Please bring your project report copies."
        step5 = orc.chat("Add this paragraph: Please bring your project report copies.")
        assert "Please bring your project report copies" in orc.pending_action["draft"].body
        apple_drafts = [d for d in _draft_records if d.get("provider") == "apple_mail"]
        assert len(apple_drafts) == 1

        # 6. Inspection: "Show me the revised draft"
        step6 = orc.chat("Show me the revised draft")
        assert "Please bring your project report copies" in step6["message"]
        # Ensure inspection does NOT replace body
        assert "show me" not in orc.pending_action["draft"].body.lower()

        # 7. Confirm draft was NEVER sent
        assert len(_sent_records) == 0


class TestGmailDraftAndRevisionWorkflow:
    def test_gmail_draft_creation_and_revisions(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        
        # 1. Draft email in Gmail
        step1 = orc.chat("Draft an email in Gmail to Rahul about the project saying let's review Phase 3 deliverables.")
        assert "rahul@example.com" in step1["task"]["params"]["recipient_email"]
        assert orc.pending_action is not None
        assert orc.pending_action["step"] == "confirm_send"
        assert "gmail" in orc.pending_action["sender_account"].lower()
        
        # Verify Gmail draft created
        gmail_drafts = orc.automation.mail.manager.gmail._sandbox_drafts
        assert len(gmail_drafts) == 1
        initial_gmail_id = gmail_drafts[0]["id"]

        # 2. Revision: "Make it shorter."
        step2 = orc.chat("Make it shorter.")
        assert len(gmail_drafts) == 1
        assert gmail_drafts[0]["id"] == initial_gmail_id

        # 3. Revision: "Use a more professional tone."
        step3 = orc.chat("Use a more professional tone.")
        assert len(gmail_drafts) == 1
        assert gmail_drafts[0]["id"] == initial_gmail_id

        # 4. Revision: "Change the meeting time to 3 PM."
        step4 = orc.chat("Change the meeting time to 3 PM.")
        assert len(gmail_drafts) == 1
        assert "3 PM" in gmail_drafts[0]["body"]

        # 5. Confirm draft was NEVER sent
        assert len(orc.automation.mail.manager.gmail._sandbox_sent) == 0


class TestSafetyAndExplicitApprovalGate:
    def test_vague_approval_rejected(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        step1 = orc.chat("Draft an email to Rahul saying the presentation is tomorrow. Keep it as a draft.")
        assert orc.pending_action is not None
        initial_body = orc.pending_action["draft"].body

        # Vague confirmation like "looks good"
        step2 = orc.chat("looks good")
        assert "explicit authorization" in step2["message"].lower() or "approve" in step2["message"].lower()
        # Draft was NOT sent
        assert len(_sent_records) == 0
        # Draft body was NOT overwritten with "looks good"
        assert orc.pending_action["draft"].body == initial_body
        assert orc.pending_action["step"] == "confirm_send"

    def test_modified_content_invalidates_approval(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        step1 = orc.chat("Send an email to Rahul saying final review is today.")
        task_id = step1["task"]["id"]
        task = orc.tasks[task_id]
        original_hash = task.params["approval_hash"]

        # User modifies draft parameters behind the scenes
        task.params["body"] = "Tampered body content!"
        task.params["formatted_body"] = "Tampered body content!"

        # Attempt to approve with original token
        res = orc.approve(task_id, approved=True, approval_hash=original_hash)
        assert res["status"] == TaskStatus.WAITING_APPROVAL.value
        assert "modified" in res["error"].lower() or "invalidated" in res["error"].lower()
        assert len(_sent_records) == 0

    def test_cancellation_cleans_draft_and_aborts(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        step1 = orc.chat("Draft an email to Rahul saying the meeting is cancelled.")
        task_id = step1["task"]["id"]
        
        # User cancels
        step2 = orc.chat("Cancel this email.")
        assert orc.pending_action is None
        assert orc.tasks[task_id].status in (TaskStatus.CANCELED, TaskStatus.CANCELLED)
        assert len(_sent_records) == 0

    def test_replay_and_duplicate_send_prevented(self):
        orc = CortexOrchestrator(use_gemini=False)
        orc.automation.dry_run = True
        step1 = orc.chat("Send an email to Rahul saying the slides are ready.")
        task_id = step1["task"]["id"]
        task = orc.tasks[task_id]
        auth_hash = task.params["approval_hash"]

        # First approval succeeds
        appr1 = orc.approve(task_id, approved=True, approval_hash=auth_hash)
        assert appr1["status"] == TaskStatus.COMPLETED.value
        assert len(_sent_records) == 1

        # Second approval attempt on the exact same task is rejected as replay
        appr2 = orc.approve(task_id, approved=True, approval_hash=auth_hash)
        assert "already" in appr2["error"].lower() or "replay" in appr2["error"].lower()
        # Message was NOT sent twice!
        assert len(_sent_records) == 1
