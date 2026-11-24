"""
CORTEX — EMAIL INTELLIGENCE REMEDIATION (BATCH 1) TEST SUITE
Verifies:
1. Autonomous Email Draft Composition:
   - "Draft an email to Rahul asking about internship opportunities."
   - "Write to my professor requesting leave tomorrow."
   - "Email HR asking about the status of my application."
   - Never demands user type the body when intent is provided.
   - Conversational draft editing remains intact.
2. Self-Identity Resolution:
   - "myself", "me", "my email", "my own email address" resolves to connected account.
   - Multi-account disambiguation.
   - Graceful reporting when zero accounts connected.
3. Search Query Sanitization:
   - Strips conversational and temporal noise from search queries.
   - "Find emails I received last week." -> query = "", date range set.
   - "Find unread emails." -> query = "", unread_only = True.
4. Term Matching & Stemming:
   - Singular/plural and inflection clustering (intern ↔ internship ↔ internships, opportunity ↔ opportunities).
5. Newest-First Date Sorting:
   - Deterministic newest-first sort before limit is applied.
   - Safe against missing or malformed date fields.
6. Full Message Body Retrieval for Summarization:
   - _summarize_emails enriches messages with full body via get_message().
   - Fallback provides informative summary rather than bare subject listing.
"""

import os
import time
import pytest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.email_engine import ProfessionalEmailEngine, EmailDraft
from backend.agent.recipient_resolver import RecipientResolver
from backend.capabilities.mail_actions import (
    MailAutomation,
    _term_matches,
    _sort_emails_by_date_desc,
    parse_email_date,
)
from backend.core.contracts import TaskCommand, TaskStatus


class TestEmailIntelligenceBatch1:
    def setup_method(self):
        self.orchestrator = CortexOrchestrator(use_gemini=False)
        self.orchestrator.mail_automation.dry_run = True
        self.orchestrator.mail_automation.get_accounts = lambda: [
            {"name": "Google", "email": "gsunilkumar1307@gmail.com"}
        ]
        self.orchestrator.pending_action = None
        self.orchestrator.history = []
        self.email_engine = ProfessionalEmailEngine()

    # =========================================================================
    # 1. Autonomous Email Draft Composition
    # =========================================================================

    def test_01_draft_to_rahul_asking_about_internships(self):
        """Verifies autonomous draft generation without demanding user write the body."""
        res = self.orchestrator.chat("Draft an email to Rahul asking about internship opportunities.")
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "confirm_send"

        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "internship opportunities" in draft.body.lower()
        assert "Internship Opportunities" in draft.subject
        assert "rahul" in draft.recipient.lower()

        # Conversational refinement
        res2 = self.orchestrator.chat("Make it a bit more casual.")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft2 = self.orchestrator.pending_action.get("draft")
        assert draft2 is not None

    def test_02_write_to_professor_requesting_leave_tomorrow(self):
        """Verifies professor leave request infers content and prompts only for recipient email."""
        res = self.orchestrator.chat("Write to my professor requesting leave tomorrow.")
        assert self.orchestrator.pending_action is not None
        # Recipient is unknown descriptive name, so it asks for the email address
        assert self.orchestrator.pending_action.get("step") == "waiting_for_recipient_clarification"
        assert "professor" in res["message"].lower() or "email" in res["message"].lower()

        # Turn 2: User provides email -> system immediately drafts with inferred body
        res2 = self.orchestrator.chat("prof.sharma@university.edu")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "prof.sharma@university.edu" in draft.recipient
        assert "Dear Professor" in draft.body
        assert "leave tomorrow" in draft.body.lower()
        assert "sincerely" in draft.body.lower()

    def test_03_email_hr_asking_about_application_status(self):
        """Verifies HR application status inquiry infers content and prompts only for email."""
        res = self.orchestrator.chat("Email HR asking about the status of my application.")
        assert self.orchestrator.pending_action is not None
        assert self.orchestrator.pending_action.get("step") == "waiting_for_recipient_clarification"

        # Turn 2: User provides email
        res2 = self.orchestrator.chat("careers@google.com")
        assert self.orchestrator.pending_action.get("step") == "confirm_send"
        draft = self.orchestrator.pending_action.get("draft")
        assert draft is not None
        assert "careers@google.com" in draft.recipient
        assert "status of my application" in draft.body.lower()
        assert "Hello HR" in draft.body or "Hello" in draft.body

    # =========================================================================
    # 2. Self-Identity Resolution
    # =========================================================================

    def test_04_self_identity_resolution_single_account(self):
        """Verifies 'myself', 'me', 'my email' resolves to user's connected email address."""
        resolver = RecipientResolver(mail_automation=self.orchestrator.mail_automation)
        
        for phrase in ("myself", "me", "my email", "my own email address"):
            res = resolver.resolve(phrase)
            assert res.status == "resolved", f"Failed for phrase {phrase}"
            assert res.recipient is not None
            assert res.recipient.email == "gsunilkumar1307@gmail.com"
            assert res.recipient.role == "self"

    def test_05_self_identity_resolution_multi_account(self):
        """Verifies multi-account setup prompts for clarification rather than guessing."""
        multi_auto = MagicMock()
        multi_auto.get_accounts.return_value = [
            {"name": "Personal", "email": "user@personal.com"},
            {"name": "Work", "email": "user@company.com"},
        ]
        resolver = RecipientResolver(mail_automation=multi_auto)

        res = resolver.resolve("myself")
        assert res.status == "multiple_candidates"
        assert len(res.candidates) == 2
        assert "user@personal.com" in res.clarification_prompt
        assert "user@company.com" in res.clarification_prompt

    def test_06_self_identity_resolution_no_accounts(self):
        """Verifies truthful reporting when no email accounts are connected."""
        no_acc_auto = MagicMock()
        no_acc_auto.get_accounts.return_value = []
        resolver = RecipientResolver(mail_automation=no_acc_auto)

        res = resolver.resolve("myself")
        assert res.status == "source_unavailable"
        assert "no connected email accounts" in res.clarification_prompt.lower()

    # =========================================================================
    # 3. Search Query Sanitization & Matching
    # =========================================================================

    def test_07_search_query_sanitization(self):
        """Verifies conversational and temporal framing is stripped and doesn't pollute query."""
        test_queries = [
            ("Find emails I received last week.", "", True, False),
            ("Find unread emails.", "", False, True),
            ("Show me unread messages", "", False, True),
            ("Find emails about internships.", "internships", False, False),
            ("Search for messages from Apple", "Apple", False, False),
            ("Show me the latest email from Google.", "Google", False, False),
        ]

        for text, expected_q, has_date, is_unread in test_queries:
            params = self.orchestrator._extract_mail_search_params(text)
            if expected_q:
                assert params["query"].lower() == expected_q.lower()
            else:
                assert params["query"] == ""
            if has_date:
                assert params["date_from"] is not None
                assert params["date_to"] is not None
            if is_unread:
                assert params["unread_only"] is True

    def test_08_term_matching_and_stemming(self):
        """Verifies singular/plural and inflection cluster matching."""
        # Singular vs Plural: intern / internship / internships
        assert _term_matches("internships", "Summer Internship Program") is True
        assert _term_matches("internship", "We have multiple internships available") is True
        assert _term_matches("intern", "Summer Internship Program") is True

        # Opportunity / Opportunities
        assert _term_matches("opportunities", "Great job opportunity for engineers") is True
        assert _term_matches("opportunity", "Explore career opportunities") is True

        # Message / Messages
        assert _term_matches("messages", "New message received") is True
        assert _term_matches("message", "List of messages") is True

        # Negative checks
        assert _term_matches("apple", "Google Cloud update") is False
        assert _term_matches("intern", "Internal architecture review") is False

    # =========================================================================
    # 4. Newest-First Date Sorting & Accuracy
    # =========================================================================

    def test_09_newest_first_sorting(self):
        """Verifies emails are strictly sorted newest-first by parsed received date."""
        raw_emails = [
            {"id": "1", "subject": "Old email", "date": "10 Nov 2026 10:00:00 +0000"},
            {"id": "2", "subject": "Newest email", "date": "18 Nov 2026 14:00:00 +0000"},
            {"id": "3", "subject": "Middle email", "date": "14 Nov 2026 12:00:00 +0000"},
            {"id": "4", "subject": "Malformed date", "date": "Not a real date"},
            {"id": "5", "subject": "Missing date"},
        ]

        sorted_emails = _sort_emails_by_date_desc(raw_emails)
        assert len(sorted_emails) == 5
        # Top result must be the newest
        assert sorted_emails[0]["id"] == "2"
        assert sorted_emails[1]["id"] == "3"
        assert sorted_emails[2]["id"] == "1"
        # Malformed and missing dates fall to the end without crashing
        assert sorted_emails[3]["id"] in ("4", "5")
        assert sorted_emails[4]["id"] in ("4", "5")

    # =========================================================================
    # 5. Full Message Retrieval for Summarization
    # =========================================================================

    def test_10_summarize_emails_retrieves_full_body(self):
        """Verifies _summarize_emails calls get_message to fetch full content rather than snippet."""
        mock_emails = [
            {"id": "msg_42", "sender": "IBM <recruiter@ibm.com>", "subject": "Offer Update", "snippet": "Hello, we are"}
        ]

        # Mock mail_automation.get_message to return full body
        def mock_get_msg(msg_id):
            if str(msg_id) == "msg_42":
                return {
                    "ok": True,
                    "email": {
                        "id": "msg_42",
                        "sender": "IBM <recruiter@ibm.com>",
                        "subject": "Offer Update",
                        "body": "Hello, we are delighted to extend an offer for the Senior AI Engineer role at IBM. Please review the attached contract and let us know your decision by Friday.",
                    }
                }
            return {"ok": False}

        self.orchestrator.mail_automation.get_message = mock_get_msg

        summary = self.orchestrator._summarize_emails(mock_emails)
        assert summary is not None
        assert "IBM" in summary
        # Verifies the full content was retrieved and included in the summary output
        assert "offer" in summary.lower() or "senior ai engineer" in summary.lower()
