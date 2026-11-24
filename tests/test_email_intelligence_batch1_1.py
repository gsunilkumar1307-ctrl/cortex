"""
CORTEX — EMAIL INTELLIGENCE REMEDIATION (BATCH 1.1) TEST SUITE
Verifies targeted remediations for the three findings in CORTEX_EMAIL_INTELLIGENCE_BATCH1_INDEPENDENT_AUDIT.md:

Finding 3.1: Deterministic Summarization Routing
- "Summarize the latest email from IBM."
- "Summarize my latest email."
- "Give me a summary of the latest email from Google."
- "Summarize the latest message I received."
- Correctly classifies as SUMMARIZE_MAIL.
- Correctly extracts sender/query and limit=1.
- Executes full body retrieval via get_message() and returns descriptive summary without Gemini.
- Preserves ordinary search classification.

Finding 3.2: Self-Identity Zero-Account Fallthrough
- Explicitly handles resolution.status == "source_unavailable".
- Never falls through to treating "myself", "me", or self-reference phrases as literal email addresses.
- Halts in NEED_INFO and requests information to continue.
- Never drafts or sends to "myself" or "me".

Finding 3.3: "Send It to Me" Self-Reference
- "Send it to me."
- "Send an email to me."
- "Email me."
- "Send this to myself."
- "Write a mail to my own email address."
- Normalizes these phrasings to self-identity resolution path.
- Resolves to actual connected account identity for single account.
- Triggers disambiguation prompt for multiple accounts.
- Never resolves "me" through unrelated contact matching.
- Ambiguous/unresolved identity never reaches send dispatch.
"""

import pytest
from unittest.mock import MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import RecipientResolver
from backend.agent.email_engine import ProfessionalEmailEngine
from backend.core.contracts import TaskCommand, TaskStatus


class TestEmailIntelligenceBatch1_1:

    # =========================================================================
    # Finding 3.1: Deterministic Summarization Routing
    # =========================================================================

    def test_01_summarization_command_classification(self):
        """Verifies natural summarization requests route to SUMMARIZE_MAIL under deterministic fallback."""
        orc = CortexOrchestrator(use_gemini=False)

        queries = [
            ("Summarize the latest email from IBM.", "IBM", 1),
            ("Summarize my latest email.", "", 1),
            ("Give me a summary of the latest email from Google.", "Google", 1),
            ("Summarize the latest message I received.", "", 1),
        ]

        for query, expected_sender, expected_limit in queries:
            analysis = orc._analyze_intent(query)
            assert analysis["command"] == TaskCommand.SUMMARIZE_MAIL, f"Failed routing for: {query}"
            params = analysis["params"]
            if expected_sender:
                assert params.get("sender") == expected_sender, f"Wrong sender for {query}: {params.get('sender')}"
            assert params.get("limit") == expected_limit, f"Wrong limit for {query}: {params.get('limit')}"

    def test_02_summarization_execution_with_gemini_unavailable(self):
        """Verifies SUMMARIZE_MAIL enriches email with full body and produces a descriptive preview."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "user@example.com"}]

        orc.mail_automation.search_mail = MagicMock(return_value={
            "ok": True,
            "emails": [{
                "id": "ibm_msg_999",
                "sender": "recruiting@ibm.com",
                "subject": "Interview Invitation",
                "date": "18 Nov 2026 12:00:00 +0000",
                "snippet": "Short preview...",
            }]
        })
        orc.mail_automation.get_message = MagicMock(return_value={
            "ok": True,
            "email": {
                "id": "ibm_msg_999",
                "body": "Dear Sunil, We are pleased to invite you for an interview at IBM tomorrow at 3 PM. Please confirm your availability."
            }
        })

        res = orc.chat("Summarize the latest email from IBM.")
        assert res["task"]["command"] == TaskCommand.SUMMARIZE_MAIL.value
        assert res["task"]["status"] == TaskStatus.COMPLETED.value
        assert "recruiting@ibm.com" in res["task"]["result"]
        assert "Interview Invitation" in res["task"]["result"]
        assert "interview at IBM tomorrow" in res["task"]["result"]
        assert orc.mail_automation.get_message.called

    def test_03_ordinary_email_search_preserved(self):
        """Verifies ordinary search requests remain SEARCH_MAIL and are not broken by summarization regex."""
        orc = CortexOrchestrator(use_gemini=False)

        searches = [
            "Search for emails from Apple.",
            "Find emails about internships.",
            "Find emails I received last week.",
            "Find unread emails.",
            "Show me the latest email from Google.",
        ]

        for s in searches:
            analysis = orc._analyze_intent(s)
            assert analysis["command"] == TaskCommand.SEARCH_MAIL, f"Wrong command for: {s}"

    # =========================================================================
    # Finding 3.2: Self-Identity Zero-Account Fallthrough
    # =========================================================================

    def test_04_zero_account_self_identity_safely_halts(self):
        """Verifies that with zero connected accounts, self-references halt in NEED_INFO without drafting."""
        test_phrasings = [
            "Send it to me saying hello",
            "Send this to myself with body hello",
            "Send an email to me saying hello",
            "Email me saying hello",
            "Write a mail to my own email address saying hello",
        ]

        for phrase in test_phrasings:
            orc = CortexOrchestrator(use_gemini=False)
            orc.mail_automation.dry_run = True
            orc.mail_automation.get_accounts = lambda: []

            res = orc.chat(phrase)
            assert res["task"]["status"] == TaskStatus.NEED_INFO.value, f"Did not halt in need_info for: {phrase}"
            assert "No connected email accounts found" in res["message"], f"Did not explain zero accounts for: {phrase}"

            # Verify no draft to "myself" or "me" was prepared
            pending = orc.pending_action
            assert pending is not None
            assert pending.get("step") == "waiting_for_recipient"
            draft = pending.get("draft")
            if draft:
                assert draft.recipient not in ("myself", "me", "my email", "my own email", "self")

    def test_05_zero_account_resolver_status_and_prompt(self):
        """Verifies RecipientResolver returns source_unavailable with actionable prompt when no accounts exist."""
        auto = MagicMock()
        auto.get_accounts.return_value = []
        resolver = RecipientResolver(mail_automation=auto)

        for phrase in ["myself", "me", "my email", "my own email address", "Send it to me", "Send this to myself"]:
            res = resolver.resolve(phrase)
            assert res.status == "source_unavailable", f"Expected source_unavailable for {phrase}, got {res.status}"
            assert res.recipient is None
            assert "No connected email accounts found" in res.clarification_prompt
            assert "enter your email address" in res.clarification_prompt

    # =========================================================================
    # Finding 3.3: "Send It to Me" Self-Reference & Disambiguation
    # =========================================================================

    def test_06_single_account_self_identity_resolves_and_drafts(self):
        """Verifies single-account setup resolves all self phrasings to connected account and creates draft."""
        test_phrasings = [
            "Send it to me saying hello",
            "Send this to myself with body hello",
            "Email me saying hello",
            "Send an email to me saying hello",
            "Write a mail to my own email address saying hello",
        ]

        for phrase in test_phrasings:
            orc = CortexOrchestrator(use_gemini=False)
            orc.mail_automation.dry_run = True
            orc.mail_automation.get_accounts = lambda: [{"name": "Personal", "email": "user@example.com"}]

            res = orc.chat(phrase)
            assert res["task"]["status"] in (TaskStatus.WAITING_APPROVAL.value, TaskStatus.COMPLETED.value)
            pending = orc.pending_action
            assert pending is not None
            assert pending.get("step") == "confirm_send"
            draft = pending.get("draft")
            assert draft is not None
            assert draft.recipient == "user@example.com"

    def test_07_multi_account_self_identity_prompts_disambiguation(self):
        """Verifies multiple connected accounts prompt for disambiguation without guessing."""
        test_phrasings = [
            "Send it to me saying hello",
            "Send this to myself with body hello",
            "Email me saying hello",
        ]

        for phrase in test_phrasings:
            orc = CortexOrchestrator(use_gemini=False)
            orc.mail_automation.dry_run = True
            orc.mail_automation.get_accounts = lambda: [
                {"name": "Personal", "email": "user@personal.com"},
                {"name": "Work", "email": "user@work.com"},
            ]

            res = orc.chat(phrase)
            assert res["task"]["status"] == TaskStatus.NEED_INFO.value
            pending = orc.pending_action
            assert pending is not None
            assert pending.get("step") == "waiting_for_recipient_disambiguation"
            assert "multiple connected email accounts" in res["message"].lower()
            assert "user@personal.com" in res["message"]
            assert "user@work.com" in res["message"]

    def test_08_self_identity_never_matches_unrelated_contacts(self):
        """Verifies self-reference words never match similarly-named contacts in address book."""
        auto = MagicMock()
        auto.get_accounts.return_value = [{"name": "Primary", "email": "self@primary.com"}]

        resolver = RecipientResolver(mail_automation=auto)
        # Mock address book with contacts containing "me"
        resolver._contacts = [
            MagicMock(name="Melanie", email="melanie@company.com"),
            MagicMock(name="Jerome", email="jerome@company.com"),
        ]

        for self_phrase in ["me", "myself", "Send it to me", "Send this to myself"]:
            res = resolver.resolve(self_phrase)
            assert res.status == "resolved"
            assert res.recipient is not None
            assert res.recipient.email == "self@primary.com"
            assert res.recipient.role == "self"
            assert "melanie" not in res.recipient.email
            assert "jerome" not in res.recipient.email

    def test_09_unresolved_identity_never_reaches_send_dispatch(self):
        """Verifies that unresolved or ambiguous identity halts in NEED_INFO and never enters confirm_send."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: []

        res = orc.chat("Send it to me saying important update")
        assert res["task"]["status"] == TaskStatus.NEED_INFO.value
        assert orc.pending_action is not None
        assert orc.pending_action.get("step") != "confirm_send"
        assert orc.pending_action.get("step") == "waiting_for_recipient"

    def test_10_ordinary_draft_creation_remains_functional(self):
        """Verifies that autonomous draft creation for standard requests is completely preserved."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "user@example.com"}]

        res = orc.chat("Draft an email to Rahul asking about internship opportunities.")
        assert orc.pending_action is not None
        assert orc.pending_action.get("step") == "confirm_send"
        draft = orc.pending_action.get("draft")
        assert draft is not None
        assert "internship opportunities" in draft.body.lower()
        assert "rahul" in draft.recipient.lower()
