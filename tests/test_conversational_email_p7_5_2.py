"""
CORTEX P7.5.2 — Final Natural-Language Email Routing Correction Test Suite
Verifies:
1. Deterministic Fallback: NL Email Creation with Dative & Prepositional Inversion:
   - "Send Rahul a mail asking about internship opportunities."
   - "Send Rahul a mail about internship opportunities."
   - "Send Rahul an email asking about the project."
   - "Send Rahul a mail regarding my application."
   - "Write Rahul a mail asking about the internship."
   - "Send an email to Rahul asking about internship opportunities."
2. Messaging Isolation:
   - WhatsApp and SMS commands remain strictly TaskCommand.SEND_MESSAGE.
3. Multi-turn Clarification & Conversation:
   - Topic extraction into subject without swallowing topic into body.
   - Missing body prompts conversationally for content.
   - Ambiguous / descriptive recipients prompt for clarification.
4. Gemini Provider Resilience & Fallback:
   - Gemini unavailable / disabled.
   - Gemini HTTP 429 / Quota Exhaustion circuit breaker.
   - Strict deterministic fallback execution with zero silent provider switching.
5. Safety Gates:
   - Dynamic SHA-256 hash recalculation and invalidation of prior approvals.
   - Replay protection.
   - Global send block enforcement (CORTEX_ALLOW_REAL_EMAIL_SEND=0).
"""

import time
import os
import pytest
from unittest.mock import patch, MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import EmailDraft, ProfessionalEmailEngine
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel, command_from_intent
from backend.capabilities.mail_actions import MailAutomation, MailDeliveryStatus


class TestConversationalEmailP752:
    def setup_method(self):
        self.orchestrator = CortexOrchestrator()
        self.orchestrator.mail_automation.dry_run = True
        self.orchestrator.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]
        self.orchestrator.use_gemini = False  # Pure deterministic fallback verification
        self.orchestrator.pending_action = None
        self.orchestrator.history = []
        self.email_engine = ProfessionalEmailEngine()

    # =========================================================================
    # 1. Natural-Language Intent Classification
    # =========================================================================

    def test_01_target_failing_query_and_variations_classification(self):
        """Verifies 'Send Rahul a mail asking...' and variations route correctly."""
        queries = [
            ("Send Rahul a mail asking about internship opportunities.", TaskCommand.SEND_MAIL),
            ("Send Rahul a mail about internship opportunities.", TaskCommand.SEND_MAIL),
            ("Send Rahul an email asking about the project.", TaskCommand.SEND_MAIL),
            ("Send Rahul a mail regarding my application.", TaskCommand.SEND_MAIL),
            ("Write Rahul a mail asking about the internship.", TaskCommand.DRAFT_MAIL),
            ("Send an email to Rahul asking about internship opportunities.", TaskCommand.SEND_MAIL),
            ("Send Rahul a mail.", TaskCommand.SEND_MAIL),
            ("Send Rahul an email.", TaskCommand.SEND_MAIL),
            ("Draft Rahul an email regarding the schedule.", TaskCommand.DRAFT_MAIL),
        ]
        for query, expected_cmd in queries:
            cmd = command_from_intent(query)
            assert cmd == expected_cmd, f"Query '{query}' classified as {cmd}, expected {expected_cmd}"

    def test_02_messaging_isolation(self):
        """Verifies WhatsApp and SMS commands never route to email creation."""
        messaging_queries = [
            ("Send Rahul a message on WhatsApp about the internship.", TaskCommand.SEND_MESSAGE),
            ("Send an SMS to Rahul about the internship.", TaskCommand.SEND_MESSAGE),
            ("Send a WhatsApp message to Rahul asking about the project.", TaskCommand.SEND_MESSAGE),
            ("Text Rahul about the internship.", TaskCommand.SEND_MESSAGE),
            ("WhatsApp Rahul saying the meeting is delayed.", TaskCommand.SEND_MESSAGE),
        ]
        for query, expected_cmd in messaging_queries:
            cmd = command_from_intent(query)
            assert cmd == expected_cmd, f"Messaging query '{query}' misclassified as {cmd}"

    # =========================================================================
    # 2. Parameter Extraction & Multi-turn Execution
    # =========================================================================

    def test_03_parameter_extraction_infers_content_from_intent(self):
        """Verifies parameter extraction isolates recipient & subject, and infers contextual body from intent."""
        extracted = self.email_engine.extract_command_and_content("Send Rahul a mail asking about internship opportunities.")
        assert extracted["recipient"] == "Rahul"
        assert "Internship Opportunities" in extracted["subject"]
        assert "internship opportunities" in extracted["content"].lower()

        extracted2 = self.email_engine.extract_command_and_content("Send Rahul an email asking about the project.")
        assert extracted2["recipient"] == "Rahul"
        assert "The Project" in extracted2["subject"]
        assert "project" in extracted2["content"].lower()

        extracted3 = self.email_engine.extract_command_and_content("Send Rahul a mail regarding my application.")
        assert extracted3["recipient"] == "Rahul"
        assert "My Application" in extracted3["subject"]
        assert "application" in extracted3["content"].lower()

    def test_04_autonomous_intent_drafting_and_conversational_revision(self):
        """Verifies autonomous draft generation for 'Send Rahul a mail asking about internship opportunities.' and conversational editing."""
        res = self.orchestrator.chat("Send Rahul a mail asking about internship opportunities.")
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "internship opportunities" in draft.body.lower()
        assert "Internship Opportunities" in draft.subject
        assert "rahul" in draft.recipient.lower()

        # Conversational edit: User refines the draft
        res2 = self.orchestrator.chat("Make it more casual and mention summer 2027.")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft2 = self.orchestrator.pending_action.get("draft")
        assert draft2 is not None

    def test_05_ambiguous_and_descriptive_recipient_handling(self):
        """Verifies descriptive or unresolvable recipients prompt for clarification without inventing addresses."""
        res = self.orchestrator.chat("Send my professor a mail asking about the final exam.")
        assert "clarify" in res["message"].lower() or "professor" in res["message"].lower()
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") in ("waiting_for_recipient_clarification", "waiting_for_body")

    def test_06_conversational_editing_without_prefix_leakage(self):
        """Verifies conversational editing on the draft strips meta-instruction prefixes."""
        self.orchestrator.chat("Send Rahul a mail asking about internship opportunities.")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"

        # Turn 2: Conversational edit
        res3 = self.orchestrator.chat("Mention that I have strong Python and machine learning skills.")
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "mention that" not in draft.body.lower()
        assert "python and machine learning" in draft.body.lower()
        assert self.orchestrator.pending_action.get("step") == "confirm_send"

    def test_07_approval_hash_invalidation_and_replay_protection(self):
        """Verifies material edits recalculate approval hash and reject obsolete/replayed approvals."""
        self.orchestrator.chat("Send Rahul a mail asking about internship opportunities.")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"

        task_id = self.orchestrator.pending_action["task_id"]
        task = self.orchestrator.tasks[task_id]
        initial_hash = task.params.get("approval_hash")
        assert initial_hash is not None

        # Material edit: make it formal
        self.orchestrator.chat("Make it more professional.")
        new_hash = task.params.get("approval_hash")
        assert new_hash != initial_hash, "Hash must change after material edit"

        # Attempt approval with obsolete hash
        app_res = self.orchestrator.approve(task_id, approved=True, approval_hash=initial_hash)
        assert "mismatch" in (app_res.get("error") or "").lower() or app_res.get("status") == TaskStatus.WAITING_APPROVAL.value

        # Legitimate approval with new hash
        app_res2 = self.orchestrator.approve(task_id, approved=True, approval_hash=new_hash)
        assert "mismatch" not in (app_res2.get("error") or "").lower()
        assert app_res2.get("status") in (TaskStatus.COMPLETED.value, TaskStatus.EXECUTING.value, TaskStatus.FAILED.value)

        # Replay attempt
        replay_res = self.orchestrator.approve(task_id, approved=True, approval_hash=new_hash)
        assert "replayed" in (replay_res.get("error") or "").lower()

    # =========================================================================
    # 3. Gemini Provider Resilience & HTTP 429 Fallback
    # =========================================================================

    def test_08_gemini_unavailable_triggers_deterministic_fallback(self):
        """Verifies when Gemini is unavailable or disabled, system operates via deterministic fallback."""
        self.orchestrator.use_gemini = False
        self.orchestrator.pending_action = None
        self.orchestrator.tasks.clear()
        assert self.orchestrator._is_gemini_available() is False

        # Should execute purely deterministically without raising exceptions
        res = self.orchestrator.chat("Send Rahul a mail about internship opportunities.")
        assert res is not None
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "internship opportunities" in draft.body.lower()

    def test_09_gemini_http_429_circuit_breaker_and_graceful_fallback(self):
        """Verifies HTTP 429 quota exhaustion activates circuit breaker and redirects to fallback."""
        self.orchestrator.use_gemini = True
        self.orchestrator.pending_action = None
        self.orchestrator.tasks.clear()

        # Simulate Google API HTTP 429 error
        err_msg = "429 ResourceExhausted: Quota exceeded for metric: generativelanguage.googleapis.com, limit: 15"
        self.orchestrator._handle_gemini_error(Exception(err_msg), context="chat")

        assert self.orchestrator.gemini_cooldown_until > time.time()
        assert self.orchestrator._is_gemini_available() is False

        # Process message during cooldown — executes via fallback without network call
        res = self.orchestrator.chat("Send Rahul an email asking about the project.")
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        assert "rahul" in self.orchestrator.pending_action.get("recipient", "").lower()
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "project" in draft.body.lower()

    def test_10_no_silent_provider_switching(self):
        """Verifies system never switches to unauthorized third-party LLM providers on failure."""
        orc = CortexOrchestrator(use_gemini=False)
        assert not hasattr(orc, "openai_client") or orc.__dict__.get("openai_client") is None
        assert not hasattr(orc, "anthropic_client") or orc.__dict__.get("anthropic_client") is None
        # Confirms model name is preserved
        assert orc.gemini_model in ("gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.5-flash", None)

    # =========================================================================
    # 4. Outbound Send Safety Gate Enforcement
    # =========================================================================

    def test_11_send_safety_gate_blocks_outbound_delivery(self):
        """Verifies CORTEX_ALLOW_REAL_EMAIL_SEND=0 strictly blocks real transmission."""
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            mail_auto = MailAutomation(dry_run=False)
            res = mail_auto.send_mail(
                recipient="rahul@example.com",
                subject="Regarding: Internship Opportunities",
                body="Hello Rahul, are there open positions?",
                account="Primary Account",
            )
            assert res.get("ok") is False
            assert res.get("delivery_status") == MailDeliveryStatus.BLOCKED.value
