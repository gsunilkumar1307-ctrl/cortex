"""
CORTEX — LIVE EMAIL INTELLIGENCE & NATURAL-LANGUAGE REMEDIATION (BATCH 1.2) TEST SUITE

Covers the 8 live desktop test scenarios (Tests A through H) and edge cases:
- Test A: Self recipient ("Draft a mail to myself.")
- Test B: Self recipient with purpose ("Send mail to myself to apply for VTU internships within a week.")
- Test C: Recipient name resolution ("Draft a mail to Sunil Kumar.")
- Test D: Missing recipient ("Send hello buddy.")
- Test E: Simple email content ("Write a short email to Rahul saying hello buddy.")
- Test F: Context contamination ("Hey Cortex. Draft a mail to myself.")
- Test G: Summarization during rate limit ("Summarize the latest email from IBM.")
- Test H: Response-needed analysis during rate limit ("What emails need responses?")
- Natural variations of self-identity: "Send mail to me", "Send it to my own Gmail", "Write an email to my own account".
- Send safety gate verification: Zero outbound transmissions, draft approval required.
"""

import os
import pytest
from unittest.mock import MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.recipient_resolver import RecipientResolver
from backend.agent.email_engine import EmailEngine
from backend.capabilities.safety import is_real_email_send_allowed
from backend.core.contracts import TaskCommand, TaskStatus


class TestEmailIntelligenceBatch1_2:

    @pytest.fixture(autouse=True)
    def ensure_safety_gate_disabled(self, monkeypatch):
        """Ensure real email sending remains strictly disabled across all tests."""
        monkeypatch.delenv("CORTEX_ALLOW_REAL_EMAIL_SEND", raising=False)
        assert is_real_email_send_allowed() is False

    # =========================================================================
    # Test A: Self recipient without body
    # =========================================================================

    def test_a_draft_mail_to_myself_asks_for_content(self):
        """Test A: 'Draft a mail to myself.' -> Recognizes self-recipient and asks for content."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Draft a mail to myself.")
        assert res["task"]["status"] == TaskStatus.NEED_INFO.value
        # Must ask what the email should say or contain
        assert any(w in res["message"].lower() for w in ("what would you like", "say", "send to myself"))
        # Must NOT create a draft card yet
        assert "Options:" not in res["message"]
        # Pending action must be waiting for body
        assert orc.pending_action is not None
        assert orc.pending_action.get("step") == "waiting_for_body"

    # =========================================================================
    # Test B: Self recipient with purpose and timeframe
    # =========================================================================

    def test_b_send_mail_to_myself_vtu_internships(self):
        """Test B: 'Send mail to myself to apply for VTU internships within a week.'
        -> Resolves self, separates purpose & timeframe, drafts meaningful email, does not send."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Send mail to myself to apply for VTU internships within a week.")
        task = res["task"]
        msg = res["message"]

        # Status must be WAITING_APPROVAL (approval card displayed)
        assert task["status"] == TaskStatus.WAITING_APPROVAL.value
        # Recipient must be user's verified email account
        assert "gsunilkumar1307@gmail.com" in msg
        # Must NOT address user as 'Google'
        assert "Hey Google" not in msg
        assert "Dear Google" not in msg
        # Subject must reflect VTU internships
        assert "VTU Internship" in msg or "VTU" in msg
        # Body must outline application goal and timeframe
        assert "internship" in msg.lower()
        assert "week" in msg.lower()
        # Explicit approval must be required
        assert "explicit approval" in msg.lower() or "approve:" in msg.lower()

    # =========================================================================
    # Test C: Recipient name resolution (Sunil Kumar)
    # =========================================================================

    def test_c_draft_mail_to_sunil_kumar(self):
        """Test C: 'Draft a mail to Sunil Kumar.'
        -> Resolves against user's actual account without hallucinating external email address."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Draft a mail to Sunil Kumar.")
        task = res["task"]
        msg = res["message"]

        assert task["status"] == TaskStatus.NEED_INFO.value
        # Recognizes Sunil Kumar and asks what the email should contain
        assert "Sunil Kumar" in msg
        assert any(w in msg.lower() for w in ("what would you like", "say", "send to"))

    # =========================================================================
    # Test D: Missing recipient handling
    # =========================================================================

    def test_d_send_hello_buddy_asks_for_recipient(self):
        """Test D: 'Send hello buddy.'
        -> Asks who the recipient is. Does NOT arbitrarily select Google or draft without recipient."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Send hello buddy.")
        task = res["task"]
        msg = res["message"]

        assert task["status"] == TaskStatus.NEED_INFO.value
        # Must ask for recipient
        assert "who would you like" in msg.lower()
        # Must NOT draft to Google
        assert "Hey Google" not in msg
        assert "Sendhello Buddy" not in msg
        # Pending action stores the intended body
        assert orc.pending_action is not None
        assert orc.pending_action.get("step") == "waiting_for_recipient"
        assert "hello buddy" in orc.pending_action.get("body", "").lower()

    # =========================================================================
    # Test E: Simple email content without context contamination
    # =========================================================================

    def test_e_write_short_email_to_rahul_saying_hello_buddy(self):
        """Test E: 'Write a short email to Rahul saying hello buddy.'
        -> Resolves Rahul, creates concise natural email, no assistant contamination."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Write a short email to Rahul saying hello buddy.")
        task = res["task"]
        msg = res["message"]

        assert task["status"] in (TaskStatus.COMPLETED.value, TaskStatus.WAITING_APPROVAL.value)
        # Recipient is resolved Rahul
        assert "rahul@example.com" in msg or "Rahul" in msg
        # No assistant wake-word or 'Hey Google'
        assert "Hey Google" not in msg
        assert "Sendhello" not in msg
        # Email has not been sent
        assert "not been sent" in msg.lower() or "approval" in msg.lower()

    # =========================================================================
    # Test F: Assistant wake-word context contamination prevention
    # =========================================================================

    def test_f_hey_cortex_draft_mail_to_myself(self):
        """Test F: 'Hey Cortex. Draft a mail to myself.'
        -> 'Hey Cortex' is treated as assistant addressing, not draft content."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.get_accounts = lambda: [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

        res = orc.chat("Hey Cortex. Draft a mail to myself.")
        task = res["task"]
        msg = res["message"]

        assert task["status"] == TaskStatus.NEED_INFO.value
        # 'Hey Cortex' must not appear as recipient or content
        assert "Hey Cortex" not in msg
        assert any(w in msg.lower() for w in ("what would you like", "say", "send to"))

    # =========================================================================
    # Test G: Email summarization with model unavailable (rate limit)
    # =========================================================================

    def test_g_summarize_ibm_email_during_rate_limit(self):
        """Test G: 'Summarize the latest email from IBM.' with model unavailable
        -> Retrieves email, reads actual content, provides local extractive summary and limitation disclosure."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.search_mail = MagicMock(return_value={
            "ok": True,
            "emails": [{
                "id": "ibm_msg_101",
                "sender": "IBM SkillsBuild <user@skillsbuild.org>",
                "subject": "Internship and Career Pathways at IBM",
                "date": "18 Nov 2026 10:00:00 +0000",
                "snippet": "Exciting internship opportunities are open now for engineering students.",
            }]
        })
        orc.mail_automation.get_message = MagicMock(return_value={
            "ok": True,
            "email": {
                "id": "ibm_msg_101",
                "body": "Dear Sunil Kumar, Applications for IBM summer internships are now open. Build your experience with hands-on projects and mentorship."
            }
        })

        res = orc.chat("Summarize the latest email from IBM.")
        task = res["task"]
        msg = res["message"]

        assert task["status"] == TaskStatus.COMPLETED.value
        assert "IBM" in msg
        assert "internship" in msg.lower()
        # Must disclose local fallback
        assert "Local extractive summary" in msg or "local" in msg.lower()
        # Must NOT crash or return generic cooling-down error
        assert "cooling down" not in msg.lower()

    # =========================================================================
    # Test H: Response-needed analysis with model unavailable (rate limit)
    # =========================================================================

    def test_h_what_emails_need_responses_during_rate_limit(self):
        """Test H: 'What emails need responses?' with model unavailable
        -> Inspects inbox, categorizes actionable items, provides disclosure, no generic cooling down error."""
        orc = CortexOrchestrator(use_gemini=False)
        orc.mail_automation.dry_run = True
        orc.mail_automation.read_mail = MagicMock(return_value={
            "ok": True,
            "emails": [
                {
                    "id": "msg_01",
                    "sender": "Prof. Smith <prof.smith@university.edu>",
                    "subject": "Assignment Submission Due Tomorrow",
                    "date": "Today, 9:00 AM",
                    "body": "Could you please confirm whether your project presentation slides are ready by 5 PM today?",
                },
                {
                    "id": "msg_02",
                    "sender": "Newsletter <news@dailyupdates.com>",
                    "subject": "Daily Tech Digest",
                    "date": "Today, 8:00 AM",
                    "body": "Here are today's top tech headlines.",
                }
            ]
        })
        orc.mail_automation.get_message = MagicMock(return_value={"ok": False})

        res = orc.chat("What emails need responses?")
        task = res["task"]
        msg = res["message"]

        assert task["command"] == TaskCommand.EXTRACT_ACTIONS.value
        assert task["status"] == TaskStatus.COMPLETED.value
        # Identifies actionable email from Prof. Smith
        assert "Prof. Smith" in msg or "Assignment Submission" in msg
        # Ignores newsletter noise
        assert "Daily Tech Digest" not in msg
        # Includes local analysis disclosure
        assert "Local inbox inspection" in msg or "Scope:" in msg
        # Must NOT return generic cooling down error
        assert "cooling down" not in msg.lower()

    # =========================================================================
    # Natural-language variations of self-identity
    # =========================================================================

    def test_self_identity_variations(self):
        """Verifies natural language variations resolve to self identity without guessing."""
        resolver = RecipientResolver()
        mock_automation = MagicMock()
        mock_automation.get_accounts.return_value = [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]
        resolver.mail_automation = mock_automation

        queries = [
            "myself",
            "me",
            "my email",
            "my own email",
            "Send mail to me",
            "Email myself about internships",
            "Send it to my own Gmail",
            "Write an email to my own account",
            "Draft a mail to Sunil Kumar",
        ]

        for q in queries:
            res = resolver.resolve(q)
            assert res.status == "resolved", f"Failed to resolve self query: {q}"
            assert res.recipient.email == "gsunilkumar1307@gmail.com", f"Wrong email for: {q}"
            assert res.recipient.role == "self", f"Wrong role for: {q}"
            assert res.recipient.name == "Sunil Kumar", f"Name should be Sunil Kumar, not provider label for: {q}"

    # =========================================================================
    # Safety Gate: Zero real email transmission
    # =========================================================================

    def test_safety_gate_strictly_prevents_real_send(self):
        """Verifies real email sending is strictly gated by CORTEX_ALLOW_REAL_EMAIL_SEND."""
        # By default unset -> blocked
        assert is_real_email_send_allowed() is False

        # Truthy string '0' must NOT enable sending
        os.environ["CORTEX_ALLOW_REAL_EMAIL_SEND"] = "0"
        assert is_real_email_send_allowed() is False

        # 'false' must NOT enable sending
        os.environ["CORTEX_ALLOW_REAL_EMAIL_SEND"] = "false"
        assert is_real_email_send_allowed() is False

        # Only explicit '1' enables sending
        os.environ["CORTEX_ALLOW_REAL_EMAIL_SEND"] = "1"
        assert is_real_email_send_allowed() is True

        # Reset back to unset
        del os.environ["CORTEX_ALLOW_REAL_EMAIL_SEND"]
        assert is_real_email_send_allowed() is False
