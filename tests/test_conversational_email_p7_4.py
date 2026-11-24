"""
Tests for Phase P7.4: Conversational Email Intelligence.
Verifies:
1. Thread intelligence & reply/forward draft preparation.
2. Contextual sending-account selection.
3. Indirect conversational instruction normalization.
4. Email draft and task-state rehydration after process restarts.
5. Send-safety enforcement and dry-run guarantees.
"""

from __future__ import annotations

import os
import time
import pytest
from unittest.mock import MagicMock, patch

from backend.core.contracts import Task, TaskCommand, TaskStatus, command_from_intent
from backend.agent.email_engine import (
    EmailEngine,
    EmailDraft,
    normalize_recipient_pronouns,
    convert_instruction_to_recipient_content,
    compose_reply,
    compose_forward,
)
from backend.capabilities.mail_actions import (
    MailAutomation,
    get_message,
    get_thread,
    get_message_headers,
    get_accounts,
)
from backend.agent.orchestrator import CortexOrchestrator
from backend.persistence.task_store import TaskStore


class TestConversationalEmailP74:
    @pytest.fixture(autouse=True)
    def setup_env(self, tmp_path):
        os.environ["CORTEX_TEST_MODE"] = "1"
        os.environ.pop("CORTEX_ALLOW_REAL_EMAIL_SEND", None)
        self.db_path = str(tmp_path / "test_tasks_p7_4.db")
        self.task_store = TaskStore(db_path=self.db_path)
        self.orchestrator = CortexOrchestrator(task_store=self.task_store, dry_run=True)
        yield
        os.environ.pop("CORTEX_TEST_MODE", None)

    # -------------------------------------------------------------------------
    # 1. Intent Classification
    # -------------------------------------------------------------------------
    def test_01_reply_and_forward_intent_classification(self):
        # Reply intents
        assert command_from_intent("reply to Rahul saying I will be there at 5pm") == TaskCommand.REPLY_MAIL
        assert command_from_intent("reply to the Google interview email") == TaskCommand.REPLY_MAIL
        assert command_from_intent("write a reply saying thank you") == TaskCommand.REPLY_MAIL

        # Forward intents
        assert command_from_intent("forward this email to Sarah") == TaskCommand.FORWARD_MAIL
        assert command_from_intent("forward the project report to team@company.com") == TaskCommand.FORWARD_MAIL

        # Informational queries must route to SEARCH_MAIL
        assert command_from_intent("what did Rahul say in his last email") == TaskCommand.SEARCH_MAIL
        assert command_from_intent("did Apple reply to my inquiry") == TaskCommand.SEARCH_MAIL

    # -------------------------------------------------------------------------
    # 2. Indirect Instruction Normalization
    # -------------------------------------------------------------------------
    def test_02_indirect_instruction_normalization(self):
        # "Ask him about..."
        res1, _ = convert_instruction_to_recipient_content("Ask him about the internship opportunity")
        assert "I am writing to inquire regarding the internship opportunity" in res1
        assert "him" not in res1.lower().split()

        # "Tell her that..."
        res2, _ = convert_instruction_to_recipient_content("tell her that I will submit the report tomorrow")
        assert "I will submit the report tomorrow" in res2
        assert "tell her" not in res2.lower()

        # "Let them know that..."
        res3, _ = convert_instruction_to_recipient_content("let them know that we received the files")
        assert "we received the files" in res3.lower()

        # "Ask Rahul when..."
        res4, _ = convert_instruction_to_recipient_content("ask Rahul when the project kickoff meeting starts")
        assert "kickoff meeting starts" in res4
        assert "ask rahul" not in res4.lower()

        # Pronoun mapping
        pronoun_mapped = normalize_recipient_pronouns("his proposal is accepted and her team can begin")
        assert "your proposal" in pronoun_mapped
        assert "your team" in pronoun_mapped

    # -------------------------------------------------------------------------
    # 3. Thread Intelligence & Reply/Forward Composition
    # -------------------------------------------------------------------------
    def test_03_compose_reply_formatting_and_headers(self):
        original = {
            "id": "<msg-001@example.com>",
            "sender": "Rahul Hulikatti <rahul@example.com>",
            "subject": "Project Sprint Planning",
            "date": "Tue, 17 Jun 2026 10:00:00 +0000",
            "body": "Can you join the sprint planning call tomorrow at 10 AM?",
            "account": "Google",
            "references": ["<parent-000@example.com>"],
        }

        draft = compose_reply(
            original_message=original,
            reply_instruction="tell him I will join at 10 AM",
            sender_account="Google",
        )

        # Subject prefixing
        assert draft.subject == "Re: Project Sprint Planning"
        # Reply again doesn't duplicate "Re: Re:"
        original["subject"] = "Re: Project Sprint Planning"
        draft2 = compose_reply(original_message=original, reply_instruction="Sounds good")
        assert draft2.subject == "Re: Project Sprint Planning"

        # Recipient resolution
        assert "rahul@example.com" in draft.recipient

        # Thread headers
        assert draft.in_reply_to == "<msg-001@example.com>"
        assert "<parent-000@example.com>" in draft.references
        assert "<msg-001@example.com>" in draft.references

        # Quotation block
        assert "On Tue, 17 Jun 2026 10:00:00 +0000, Rahul Hulikatti <rahul@example.com> wrote:" in draft.body
        assert "> Can you join the sprint planning call tomorrow at 10 AM?" in draft.body
        assert "I will join at 10 AM" in draft.body

    def test_04_compose_forward_formatting_and_headers(self):
        original = {
            "id": "<msg-002@example.com>",
            "sender": "Professor Davis <davis@university.edu>",
            "recipient": "gsunilkumar1307@gmail.com",
            "subject": "Lab Schedule Update",
            "date": "Mon, 16 Jun 2026 14:00:00 +0000",
            "body": "The lab will be closed on Friday for equipment maintenance.",
            "references": ["<lab-root@university.edu>"],
        }

        draft = compose_forward(
            original_message=original,
            target_recipient="labpartner@university.edu",
            user_note="FYI regarding Friday",
            sender_account="Google",
        )

        assert draft.subject == "Fwd: Lab Schedule Update"
        assert draft.recipient == "labpartner@university.edu"
        assert "FYI regarding Friday" in draft.body
        assert "---------- Forwarded message ---------" in draft.body
        assert "From: Professor Davis <davis@university.edu>" in draft.body
        assert "Subject: Lab Schedule Update" in draft.body
        assert "The lab will be closed on Friday" in draft.body
        assert "<lab-root@university.edu>" in draft.references

    # -------------------------------------------------------------------------
    # 4. MCP Threading Tools Delegation & Fallback
    # -------------------------------------------------------------------------
    def test_05_mcp_threading_tools_delegation(self):
        mock_mcp = MagicMock()
        mock_mcp._servers = {"apple-mail": True}
        mock_result = MagicMock()
        mock_result.is_error = False
        mock_result.content = [{"type": "text", "text": '{"id": "msg-99", "subject": "Thread Subject"}'}]
        mock_mcp.call_tool.return_value = mock_result

        auto = MailAutomation(mcp_manager=mock_mcp, dry_run=False)

        # get_message
        res = auto.get_message("msg-99", mcp_manager=mock_mcp)
        assert res.get("ok") is True
        mock_mcp.call_tool.assert_called_with("apple-mail", "get-message", {"id": "msg-99"}, timeout=15.0)

        # get_thread
        mock_result.content = [{"type": "text", "text": '[{"id": "msg-99"}, {"id": "msg-100"}]'}]
        thread_res = auto.get_thread("msg-99", mcp_manager=mock_mcp)
        assert thread_res.get("ok") is True

        # get_message_headers
        mock_result.content = [{"type": "text", "text": '{"Message-ID": "<msg-99>", "In-Reply-To": "<msg-98>"}'}]
        hdr_res = auto.get_message_headers("msg-99", mcp_manager=mock_mcp)
        assert hdr_res.get("ok") is True

    # -------------------------------------------------------------------------
    # 5. Contextual Sending-Account Selection
    # -------------------------------------------------------------------------
    def test_06_contextual_sending_account_selection(self):
        multi_accounts = [
            {"name": "Personal", "email": "me@personal.com"},
            {"name": "Work", "email": "me@enterprise.org"},
        ]

        with patch.object(self.orchestrator.mail_automation, "get_accounts", return_value=multi_accounts):
            # Priority 1: User explicitly specifies account
            acc1, is_amb1, _ = self.orchestrator._resolve_sending_account(
                requested_account="Work",
                recipient="client@enterprise.org",
            )
            assert "Work" in acc1
            assert is_amb1 is False

            # Priority 2: In-reply-to thread context
            acc2, is_amb2, _ = self.orchestrator._resolve_sending_account(
                thread_account="Personal",
                recipient="friend@gmail.com",
            )
            assert "Personal" in acc2
            assert is_amb2 is False

            # Priority 3: Recipient domain affiliation (Supporting evidence only — asks user with suggestion)
            acc3, is_amb3, prompt3 = self.orchestrator._resolve_sending_account(
                recipient="colleague@enterprise.org",
            )
            assert acc3 == ""
            assert is_amb3 is True
            assert "Work" in prompt3 or "enterprise.org" in prompt3

            # Priority 5: Ambiguous recipient domain with multiple accounts -> clarification
            acc4, is_amb4, prompt4 = self.orchestrator._resolve_sending_account(
                recipient="someone@gmail.com",
            )
            assert acc4 == ""
            assert is_amb4 is True
            assert "multiple email accounts" in prompt4

        # Priority 4: Single account default
        single_account = [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]
        with patch.object(self.orchestrator.mail_automation, "get_accounts", return_value=single_account):
            acc_single, is_amb_s, _ = self.orchestrator._resolve_sending_account(
                recipient="someone@gmail.com",
            )
            assert "Google" in acc_single
            assert is_amb_s is False

    # -------------------------------------------------------------------------
    # 6. Task Rehydration & Process Restart Recovery
    # -------------------------------------------------------------------------
    def test_07_draft_rehydration_after_process_restart(self):
        draft = EmailDraft(
            recipient="advisor@university.edu",
            subject="Thesis Meeting Request",
            body="Dear Professor, I would like to schedule our weekly thesis review.",
            sender_account="Google",
            in_reply_to="<thesis-init@university.edu>",
            references=["<thesis-init@university.edu>"],
        )

        task_id = "test-rehydrate-p74-task"
        task = Task(
            id=task_id,
            intent="draft an email to professor",
            command=TaskCommand.DRAFT_MAIL,
            status=TaskStatus.WAITING_APPROVAL,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "recipient_email": draft.recipient,
                "subject": draft.subject,
                "body": draft.body,
                "formatted_body": draft.body,
                "sender_account": draft.sender_account,
                "in_reply_to": draft.in_reply_to,
                "references": draft.references,
                "draft": draft.to_dict(),
                "created_at": time.time(),
            },
        )
        task.approval_hash = draft.compute_hash()
        self.task_store.save_task(task)

        # Simulate clean restart by creating a new CortexOrchestrator instance pointing to same TaskStore
        new_orchestrator = CortexOrchestrator(task_store=self.task_store, dry_run=True)

        assert new_orchestrator.pending_action is not None
        assert new_orchestrator.pending_action.get("type") == "email_draft"
        assert new_orchestrator.pending_action.get("step") == "confirm_send"
        assert isinstance(new_orchestrator.pending_action.get("draft"), EmailDraft)

        rehydrated_draft = new_orchestrator.pending_action["draft"]
        assert rehydrated_draft.recipient == "advisor@university.edu"
        assert rehydrated_draft.subject == "Thesis Meeting Request"
        assert rehydrated_draft.in_reply_to == "<thesis-init@university.edu>"

        # Conversational refinement works on rehydrated task
        refine_resp = new_orchestrator.chat("Make it shorter and more formal.")
        assert refine_resp is not None
        assert new_orchestrator.pending_action is not None
        current_draft = new_orchestrator.pending_action["draft"]
        assert current_draft.tone == "formal_concise"

        # Further refinement: change subject
        subj_resp = new_orchestrator.chat("Change subject to: Thesis Progress Review")
        assert subj_resp is not None
        assert current_draft.subject == "Thesis Progress Review"

    def test_08_rehydration_payload_tampering_and_expiration(self):
        # A: Tampered payload
        tampered_draft = EmailDraft(
            recipient="target@corp.com",
            subject="Legitimate Subject",
            body="Original body",
            sender_account="Google",
        )
        task_tampered = Task(
            id="tampered-task-id",
            intent="draft mail",
            command=TaskCommand.DRAFT_MAIL,
            status=TaskStatus.WAITING_APPROVAL,
            requires_approval=True,
            params={
                "recipient": tampered_draft.recipient,
                "subject": tampered_draft.subject,
                "body": "Modified unauthorized body!",
                "formatted_body": "Modified unauthorized body!",
                "sender_account": tampered_draft.sender_account,
                "created_at": time.time(),
                "approval_hash": tampered_draft.compute_hash(),
            },
        )
        task_tampered.approval_hash = tampered_draft.compute_hash()
        self.task_store.save_task(task_tampered)

        orch_tampered = CortexOrchestrator(task_store=self.task_store, dry_run=True)
        # Rehydration marks tampered task as NEEDS_ATTENTION, so pending_action is not active
        assert orch_tampered.pending_action is None or orch_tampered.tasks["tampered-task-id"].status == TaskStatus.NEEDS_ATTENTION

        # B: Expired draft (>300 seconds)
        expired_draft = EmailDraft(
            recipient="target2@corp.com",
            subject="Expired Subject",
            body="Old body",
            sender_account="Google",
        )
        task_expired = Task(
            id="expired-task-id",
            intent="draft mail",
            command=TaskCommand.DRAFT_MAIL,
            status=TaskStatus.WAITING_APPROVAL,
            requires_approval=True,
            params={
                "recipient": expired_draft.recipient,
                "subject": expired_draft.subject,
                "body": expired_draft.body,
                "formatted_body": expired_draft.body,
                "sender_account": expired_draft.sender_account,
                "created_at": time.time() - 350,  # 350 seconds ago
                "approval_hash": expired_draft.compute_hash(),
            },
        )
        task_expired.approval_hash = expired_draft.compute_hash()
        self.task_store.save_task(task_expired)

        orch_expired = CortexOrchestrator(task_store=self.task_store, dry_run=True)
        # Rehydration marks expired task as NEEDS_ATTENTION
        assert orch_expired.tasks["expired-task-id"].status == TaskStatus.NEEDS_ATTENTION

    # -------------------------------------------------------------------------
    # 7. Send Safety Hard Block & Dry Run
    # -------------------------------------------------------------------------
    def test_09_send_safety_enforcement(self):
        # Verify CORTEX_ALLOW_REAL_EMAIL_SEND is unset
        assert os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND") is None

        # Verify disallowed tools remain in client / config blocklist
        from backend.mcp.config import BLOCKED_APPLE_MAIL_TOOLS, get_apple_mail_server_config
        assert "send-email" in BLOCKED_APPLE_MAIL_TOOLS
        assert "reply-to-message" in BLOCKED_APPLE_MAIL_TOOLS
        assert "forward-message" in BLOCKED_APPLE_MAIL_TOOLS
        assert "send-serial-email" in BLOCKED_APPLE_MAIL_TOOLS

        cfg = get_apple_mail_server_config()
        assert cfg.is_tool_allowed("send-email") is False
        assert cfg.is_tool_allowed("reply-to-message") is False
        assert cfg.is_tool_allowed("forward-message") is False

        # Simulated execution in dry-run mode returns safe confirmation
        draft = EmailDraft(
            recipient="test@example.com",
            subject="Dry Run Test",
            body="Testing dry run safety",
            sender_account="Google",
        )
        task = Task(
            id="dry-run-task",
            intent="send dry run email",
            command=TaskCommand.SEND_MAIL,
            status=TaskStatus.WAITING_APPROVAL,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "recipient_email": draft.recipient,
                "subject": draft.subject,
                "body": draft.body,
                "formatted_body": draft.body,
                "sender_account": draft.sender_account,
                "approval_hash": draft.compute_hash(),
            },
        )
        task.approval_hash = draft.compute_hash()
        self.task_store.save_task(task)
        self.orchestrator.tasks["dry-run-task"] = task

        self.orchestrator.pending_action = {
            "type": "email_draft",
            "step": "confirm_send",
            "task_id": "dry-run-task",
            "draft_id": "draft-dry-run",
            "recipient": draft.recipient,
            "recipient_email": draft.recipient,
            "subject": draft.subject,
            "body": draft.body,
            "formatted_body": draft.body,
            "sender_account": draft.sender_account,
            "draft": draft,
            "approval_hash": draft.compute_hash(),
            "created_at": time.time(),
        }

        resp = self.orchestrator.chat("yes, send it")
        msg = resp.get("message", "") if isinstance(resp, dict) else str(resp)
        assert any(kw in msg.lower() for kw in ("sent", "safeguard", "dry-run", "simulated", "confirmed", "delivery"))
