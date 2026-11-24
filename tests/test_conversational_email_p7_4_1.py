"""
CORTEX P7.4.1 — Conversational Email Remediation Test Suite
Verifies all 5 blockers and defense-in-depth remediations:
1. Reply/Forward approval hash reconstruction in approve()
2. Sending-account resolution policy (domain match suggests with is_ambiguous=True)
3. RFC 2822 Message-ID validation & extraction (preventing <numeric_id> in MCP create-draft)
4. Dative natural-language instruction normalization ("Send him a mail asking...")
5. Standardized 300-second approval expiration window
6. Send-safety gate enforcement across all providers (including Gmail)
"""

import os
import re
import time
import pytest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import (
    ProfessionalEmailEngine,
    EmailDraft,
    convert_instruction_to_recipient_content,
)
from backend.capabilities.mail_actions import MailAutomation, MailDeliveryStatus
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel


class TestConversationalEmailP741Remediation:
    def setup_method(self):
        self.orchestrator = CortexOrchestrator()
        self.orchestrator.mail_automation.dry_run = True
        self.email_engine = ProfessionalEmailEngine()

    # -------------------------------------------------------------------------
    # 1. P0 Blocker 1: Reply / Forward Approval Hash Reconstruction
    # -------------------------------------------------------------------------
    def test_01_reply_draft_approval_hash_reconstruction(self):
        """Verifies reply drafts with in_reply_to and references compute matching hashes in approve()."""
        draft = EmailDraft(
            recipient="advisor@university.edu",
            subject="Re: Thesis Defense Scheduling",
            body="Dear Professor,\n\nI confirm that Friday at 2 PM works well for me.",
            sender_account="Google <gsunilkumar1307@gmail.com>",
            in_reply_to="<thesis-init-12345@university.edu>",
            references=["<thesis-init-12345@university.edu>"],
        )
        approval_hash = draft.compute_hash()

        task = Task(
            intent="Reply to Professor confirming Friday",
            command=TaskCommand.REPLY_MAIL,
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "recipient_email": draft.recipient,
                "subject": draft.subject,
                "body": "I confirm that Friday at 2 PM works well for me.",
                "formatted_body": draft.body,
                "sender_account": draft.sender_account,
                "account": draft.sender_account,
                "approval_hash": approval_hash,
                "in_reply_to": draft.in_reply_to,
                "references": draft.references,
                "created_at": time.time(),
                "draft": draft.to_dict(),
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        # Approval with valid hash must succeed
        res = self.orchestrator.approve(task.id, approved=True, approval_hash=approval_hash)
        assert res.get("status") != TaskStatus.FAILED.value
        assert "Approval invalidated" not in (res.get("error") or "")

    def test_02_forward_draft_approval_hash_reconstruction(self):
        """Verifies forward drafts with threading headers approve without hash mismatch."""
        draft = EmailDraft(
            recipient="teammate@startup.io",
            subject="Fwd: Product Roadmap Update",
            body="FYI, please see below.\n\n---------- Forwarded message ---------\nFrom: boss@corp.com",
            sender_account="Work <me@startup.io>",
            in_reply_to="<corp-msg-999@corp.com>",
            references=["<corp-msg-999@corp.com>"],
        )
        approval_hash = draft.compute_hash()

        task = Task(
            intent="Forward roadmap to teammate",
            command=TaskCommand.FORWARD_MAIL,
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "recipient_email": draft.recipient,
                "subject": draft.subject,
                "body": "FYI, please see below.",
                "formatted_body": draft.body,
                "sender_account": draft.sender_account,
                "account": draft.sender_account,
                "approval_hash": approval_hash,
                "in_reply_to": draft.in_reply_to,
                "references": draft.references,
                "created_at": time.time(),
                "draft": draft.to_dict(),
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        res = self.orchestrator.approve(task.id, approved=True, approval_hash=approval_hash)
        assert res.get("status") != TaskStatus.FAILED.value
        assert "Approval invalidated" not in (res.get("error") or "")

    def test_03_tampered_draft_rejected_in_approve(self):
        """Verifies modifying draft body invalidates approval."""
        draft = EmailDraft(
            recipient="client@enterprise.org",
            subject="Re: Contract Terms",
            body="We accept the 10% discount.",
            sender_account="Google",
            in_reply_to="<contract-1@enterprise.org>",
            references=["<contract-1@enterprise.org>"],
        )
        original_hash = draft.compute_hash()

        task = Task(
            intent="Reply to contract",
            command=TaskCommand.REPLY_MAIL,
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "subject": draft.subject,
                "body": "Tampered body: We accept 50% discount.",
                "formatted_body": "Tampered body: We accept 50% discount.",
                "sender_account": draft.sender_account,
                "approval_hash": original_hash,
                "in_reply_to": draft.in_reply_to,
                "references": draft.references,
                "created_at": time.time(),
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        res = self.orchestrator.approve(task.id, approved=True, approval_hash=original_hash)
        assert "Approval invalidated: draft content was modified" in (res.get("error") or "")
        assert res.get("status") == TaskStatus.WAITING_APPROVAL.value

    # -------------------------------------------------------------------------
    # 2. P0 Blocker 2: Sending-Account Selection Policy
    # -------------------------------------------------------------------------
    def test_04_domain_match_suggests_without_silent_autoselection(self):
        """Verifies recipient domain matching does NOT silently auto-select when multiple accounts exist."""
        multi_accounts = [
            {"name": "Personal", "email": "me@personal.com"},
            {"name": "Work", "email": "me@enterprise.org"},
        ]

        with patch.object(self.orchestrator.mail_automation, "get_accounts", return_value=multi_accounts):
            acc, is_amb, prompt = self.orchestrator._resolve_sending_account(
                recipient="colleague@enterprise.org",
            )
            # MUST NOT silently select
            assert acc == ""
            assert is_amb is True
            # MUST suggest matching account inside clarification prompt
            assert "enterprise.org" in prompt
            assert "Work" in prompt
            assert "Would you like to send this from" in prompt or "would you like to send this from" in prompt

    def test_05_explicit_and_thread_account_selection_remains_direct(self):
        """Verifies explicit user choice or thread context directly selects the account."""
        multi_accounts = [
            {"name": "Personal", "email": "me@personal.com"},
            {"name": "Work", "email": "me@enterprise.org"},
        ]

        with patch.object(self.orchestrator.mail_automation, "get_accounts", return_value=multi_accounts):
            # Explicit user choice
            acc1, is_amb1, _ = self.orchestrator._resolve_sending_account(
                requested_account="Work",
                recipient="colleague@enterprise.org",
            )
            assert "Work" in acc1
            assert is_amb1 is False

            # Thread context
            acc2, is_amb2, _ = self.orchestrator._resolve_sending_account(
                thread_account="Personal",
                recipient="friend@other.com",
            )
            assert "Personal" in acc2
            assert is_amb2 is False

    # -------------------------------------------------------------------------
    # 3. P1 Blocker 3: RFC 2822 Message-ID Compliance & Validation
    # -------------------------------------------------------------------------
    def test_06_rfc2822_message_id_schema_validation(self):
        """Verifies RFC 2822 regex strictly rejects local numeric IDs and malformed IDs."""
        rfc_pattern = re.compile(r"^<[^<>\s@]+@[^<>\s@]+>$")

        # Valid RFC 2822 IDs
        assert rfc_pattern.match("<valid.id-123@domain.com>") is not None
        assert rfc_pattern.match("<CAGx_9-abc@mail.gmail.com>") is not None
        assert rfc_pattern.match("<9f36e35d@google.com>") is not None

        # Invalid IDs (must be rejected)
        assert rfc_pattern.match("<8502>") is None
        assert rfc_pattern.match("8502") is None
        assert rfc_pattern.match("<invalid>") is None
        assert rfc_pattern.match("") is None
        assert rfc_pattern.match("<user@domain with spaces.com>") is None

    def test_07_compose_reply_never_fabricates_numeric_message_id(self):
        """Verifies compose_reply does not set in_reply_to or references to numeric ID."""
        thread_context = {
            "id": 8502,
            "sender": "Hiring Team <jobs@company.com>",
            "sender_email": "jobs@company.com",
            "subject": "Interview Invitation",
            "body": "Are you available for an interview?",
            "account": "Google",
        }
        draft = self.email_engine.compose_reply(
            thread_context=thread_context,
            reply_instruction="I will be available Monday morning.",
        )
        # Cannot be numeric <8502>
        assert draft.in_reply_to != "<8502>"
        assert "<8502>" not in draft.references

        # When real RFC 2822 Message-ID is provided:
        thread_context_rfc = {
            "id": 8502,
            "rfc_message_id": "<real-rfc-msgid@company.com>",
            "sender": "Hiring Team <jobs@company.com>",
            "subject": "Interview Invitation",
            "body": "Are you available for an interview?",
            "account": "Google",
        }
        draft_rfc = self.email_engine.compose_reply(
            thread_context=thread_context_rfc,
            reply_instruction="I will be available Monday morning.",
        )
        assert draft_rfc.in_reply_to == "<real-rfc-msgid@company.com>"
        assert "<real-rfc-msgid@company.com>" in draft_rfc.references

    def test_08_create_draft_filters_invalid_threading_headers_for_mcp(self):
        """Verifies draft_mail strips malformed IDs so Apple Mail MCP does not reject schema."""
        mock_mgr = MagicMock()
        mock_res = MagicMock()
        mock_res.is_error = False
        mock_mgr.call_tool.return_value = mock_res
        mock_mgr._servers = {"apple-mail": True}

        mail = MailAutomation(mcp_manager=mock_mgr)
        mail.dry_run = False
        mail.system = "darwin"

        # Pass invalid numeric in_reply_to
        mail.draft_mail(
            recipient="test@example.com",
            subject="Test Thread",
            body="Test body",
            in_reply_to="<8502>",
            references=["<8502>", "<valid-ref@example.com>"],
        )

        call_args = mock_mgr.call_tool.call_args[0][2]
        # inReplyTo must not have been passed as <8502>
        assert "inReplyTo" not in call_args
        # references must only contain the valid RFC 2822 ID
        assert call_args.get("references") == ["<valid-ref@example.com>"]

    # -------------------------------------------------------------------------
    # 4. P1 Blocker 4: Dative Conversational Instruction Normalization
    # -------------------------------------------------------------------------
    def test_09_dative_instruction_normalization(self):
        """Verifies dative phrases strip pronouns and meta-intents cleanly into professional prose."""
        cases = [
            (
                "Send him a mail asking about the application status.",
                "I am writing to inquire regarding the application status. Could you please provide an update on this?",
            ),
            (
                "Send him a mail asking when the interview is scheduled.",
                "Could you please let me know when the interview is scheduled?",
            ),
            (
                "Can you draft him an email asking about the project status?",
                "I am writing to inquire regarding the project status. Could you please provide an update on this?",
            ),
            (
                "Ask Rahul about the internship.",
                "I am writing to inquire regarding the internship. Could you please provide an update on this?",
            ),
            (
                "Ask him when the interview is scheduled.",
                "Could you please let me know when the interview is scheduled?",
            ),
            (
                "Tell her that I'll attend.",
                "I would like to let you know that I'll attend.",
            ),
            (
                "Let them know I am interested.",
                "I wanted to let you know that I am interested.",
            ),
        ]

        for prompt, expected in cases:
            res, _ = convert_instruction_to_recipient_content(prompt)
            assert res == expected, f"Failed on prompt: '{prompt}' -> got: '{res}'"

    # -------------------------------------------------------------------------
    # 5. P1 Blocker 5: Standardized 300-Second Approval Window
    # -------------------------------------------------------------------------
    def test_10_standardized_300s_approval_expiry(self):
        """Verifies approve() rejects tasks older than 300 seconds (5 minutes)."""
        draft = EmailDraft(
            recipient="test@example.com",
            subject="Meeting",
            body="Hi there",
            sender_account="Google",
        )
        task = Task(
            intent="Send meeting mail",
            command=TaskCommand.SEND_MAIL,
            risk_level=RiskLevel.MEDIUM,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "subject": draft.subject,
                "body": draft.body,
                "sender_account": draft.sender_account,
                "approval_hash": draft.compute_hash(),
                "created_at": time.time() - 350,  # 350s ago (> 300s)
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        res = self.orchestrator.approve(task.id, approved=True, approval_hash=draft.compute_hash())
        assert res.get("status") == TaskStatus.WAITING_APPROVAL.value
        assert "Approval expired" in (res.get("error") or "")

    def test_11_fresh_task_within_300s_approved(self):
        """Verifies approve() accepts tasks requested within 300 seconds."""
        draft = EmailDraft(
            recipient="test@example.com",
            subject="Meeting",
            body="Hi there",
            sender_account="Google",
        )
        task = Task(
            intent="Draft meeting mail",
            command=TaskCommand.DRAFT_MAIL,
            risk_level=RiskLevel.LOW,
            requires_approval=True,
            params={
                "recipient": draft.recipient,
                "subject": draft.subject,
                "body": draft.body,
                "sender_account": draft.sender_account,
                "approval_hash": draft.compute_hash(),
                "created_at": time.time() - 60,  # 60s ago (< 300s)
            },
        )
        task.status = TaskStatus.WAITING_APPROVAL
        self.orchestrator.tasks[task.id] = task

        res = self.orchestrator.approve(task.id, approved=True, approval_hash=draft.compute_hash())
        assert "Approval expired" not in (res.get("error") or "")
        assert res.get("status") == TaskStatus.COMPLETED.value

    # -------------------------------------------------------------------------
    # 6. P2 Defense-in-Depth: Send Safety Gate Across All Providers
    # -------------------------------------------------------------------------
    def test_12_send_safety_gate_blocks_all_providers_when_unset(self):
        """Verifies MailAutomation.send_mail enforces CORTEX_ALLOW_REAL_EMAIL_SEND before Gmail or Apple Mail."""
        mail = MailAutomation()
        mail.dry_run = False
        mail.system = "darwin"

        with patch.dict(os.environ, {}, clear=True):
            # Ensure CORTEX_ALLOW_REAL_EMAIL_SEND is unset
            os.environ.pop("CORTEX_ALLOW_REAL_EMAIL_SEND", None)

            # 1. Attempt sending with Gmail account
            res_gmail = mail.send_mail(
                recipient="test@example.com",
                subject="Test Gmail",
                body="Test body",
                account="Google <test@gmail.com>",
            )
            assert res_gmail.get("ok") is False
            assert res_gmail.get("delivery_status") == MailDeliveryStatus.BLOCKED.value

            # 2. Attempt sending with Apple Mail account
            res_apple = mail.send_mail(
                recipient="test@example.com",
                subject="Test Apple Mail",
                body="Test body",
                account="Personal <me@icloud.com>",
            )
            assert res_apple.get("ok") is False
            assert res_apple.get("delivery_status") == MailDeliveryStatus.BLOCKED.value
