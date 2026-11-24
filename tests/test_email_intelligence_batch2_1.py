"""
tests/test_email_intelligence_batch2_1.py
========================================
Batch 2.1 Test Suite: Email Intelligence Accuracy Remediation

Validates the remediation of false-positive actionable email classifications:
1. False-Positive Suite: Eliminates promotional campaigns, marketing broadcasts,
   newsletters with rhetorical questions, and event dates mistakenly flagged as user deadlines.
2. Genuine Action Suite: Preserves genuine user obligations, document requests,
   application deadlines, interview inquiries, and attendance confirmations.
3. Integrity & Anti-Fabrication Suite: Strictly evidence-grounded recommendations,
   no fabricated deadlines, no fabricated status updates, clean zero-action reporting.
4. Orchestrator Integration: Full chat turn verification for "Is there anything I need to respond to?".
"""

import unittest
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.mail_actions import MailAutomation
from backend.core.contracts import TaskCommand, TaskStatus


class TestFalsePositiveElimination(unittest.TestCase):
    """Verifies that promotional, marketing, and non-actionable broadcast emails are excluded."""

    def setUp(self):
        self.mail_actions = MailAutomation(dry_run=True)

    def test_tradingview_black_friday_filtered(self):
        """TradingView Black Friday promotional email must NOT be classified as actionable."""
        sample_email = {
            "id": "tv-bf-1",
            "sender": "TradingView <noreply@tradingview.com>",
            "subject": "Black Friday is coming — mark your calendar",
            "date": "Nov 18, 2026",
            "body": (
                "Get ready for the biggest sale of the year. "
                "Black Friday is on November 27. "
                "Mark your calendar and don't miss out on savings! "
                "Unsubscribe here. All rights reserved."
            ),
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["actions"]), 0)
            self.assertIn("couldn't identify any messages that clearly require a reply or action", res["message"])
            self.assertNotIn("TradingView", res["message"])

    def test_mark_your_calendar_winter_release_filtered(self):
        """'Mark your calendar for our winter release' must NOT be classified as actionable."""
        sample_email = {
            "id": "promo-winter",
            "sender": "Acme Cloud <updates@acme.io>",
            "subject": "Mark your calendar for our winter release",
            "date": "Nov 17, 2026",
            "body": "We are thrilled to announce our upcoming winter release event on Dec 15. View in browser. Unsubscribe.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_dont_miss_upcoming_sale_filtered(self):
        """'Don't miss our upcoming sale' must NOT be classified as actionable."""
        sample_email = {
            "id": "promo-sale",
            "sender": "Fashion Weekly <deals@fashion.com>",
            "subject": "Don't miss our upcoming sale",
            "date": "Nov 16, 2026",
            "body": "Huge discounts across all categories. Sale begins this Friday. Unsubscribe from promotional emails.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_promotional_urgent_filtered(self):
        """Promotional email containing 'urgent' in marketing context must NOT be classified as actionable."""
        sample_email = {
            "id": "promo-urgent",
            "sender": "Online Retailer <marketing@retailer.com>",
            "subject": "Urgent: Black Friday deals ending soon",
            "date": "Nov 15, 2026",
            "body": "Don't miss out on special discounts up to 70% off. Sale ends midnight! Opt-out of marketing emails.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_promotional_dates_not_treated_as_user_deadlines(self):
        """Sale dates mentioned in promotional copy must not be extracted as user deadlines."""
        sample_email = {
            "id": "promo-dates",
            "sender": "Tech Store <deals@techdeals.com>",
            "subject": "Black Friday Week Specials",
            "date": "Nov 18, 2026",
            "body": "Sale runs Nov 20 to Nov 27. Mark your calendar for exclusive discounts. Unsubscribe.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_newsletter_rhetorical_question_filtered(self):
        """Newsletter containing a rhetorical question must NOT trigger reply_required."""
        sample_email = {
            "id": "news-rhetorical",
            "sender": "AI Weekly <newsletter@aiweekly.com>",
            "subject": "Weekly Digest #142",
            "date": "Nov 17, 2026",
            "body": (
                "Could quantum computing change AI? In this issue we explore the latest benchmarks "
                "and interview leading researchers. Read our full roundup online. Unsubscribe."
            ),
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_automated_announcement_without_obligation_filtered(self):
        """Product update announcement without user obligation must NOT be actionable."""
        sample_email = {
            "id": "saas-update",
            "sender": "Product Team <announcements@saas.com>",
            "subject": "Product update: New dashboard features",
            "date": "Nov 16, 2026",
            "body": (
                "We have launched new customizable widgets on your dashboard. "
                "Check out what's new. Update your notification preferences or unsubscribe."
            ),
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)

    def test_marketing_followup_filtered(self):
        """Marketing email checking in on promotional offers must NOT be treated as actionable."""
        sample_email = {
            "id": "promo-followup",
            "sender": "Sales Team <sales@saastool.io>",
            "subject": "Following up on our summer discount",
            "date": "Nov 14, 2026",
            "body": (
                "Just following up on our summer discount offer to see if you would like to upgrade your team plan. "
                "Check our plans and explore our pricing. Unsubscribe here."
            ),
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 0)


class TestGenuineActionPreservation(unittest.TestCase):
    """Verifies that genuine questions, deadlines, document requests, and follow-ups are preserved."""

    def setUp(self):
        self.mail_actions = MailAutomation(dry_run=True)

    def test_direct_question_preserved(self):
        """Direct question from a colleague must be detected as reply_required."""
        sample_email = {
            "id": "direct-q-1",
            "sender": "Alice Engineer <alice@company.com>",
            "subject": "Question on authentication flow",
            "date": "Nov 19, 2026, 10:15 AM",
            "body": "Hi Sunil, could you please explain the authentication flow used in the login module? Thanks!",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertEqual(act["category"], "reply_required")
            self.assertEqual(act["urgency"], "Medium")
            self.assertIn("direct question", act["reason"].lower())
            self.assertIn("reply", act["suggested_action"].lower())

    def test_resume_request_preserved(self):
        """Request for resume with a deadline must be detected and grounded in evidence."""
        sample_email = {
            "id": "recruiter-resume",
            "sender": "Bob Recruiter <bob@staffing.com>",
            "subject": "Software Engineer Opening",
            "date": "Nov 18, 2026, 2:30 PM",
            "body": "Hi Sunil, we were impressed by your profile. Could you send me your resume by Friday? Best, Bob.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertIn("resume", act["reason"].lower())
            self.assertIn("resume", act["suggested_action"].lower())
            self.assertIsNotNone(act["deadline"])
            self.assertEqual(act["urgency"], "High")

    def test_document_submission_preserved(self):
        """Request for signed offer letter and passport copy must recommend document submission."""
        sample_email = {
            "id": "hr-docs",
            "sender": "HR Onboarding <hr@enterprise.com>",
            "subject": "Onboarding requirements",
            "date": "Nov 18, 2026",
            "body": "Dear Sunil, please submit your signed offer letter and passport copy so we can process your badge.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertIn("offer letter", act["reason"].lower())
            self.assertIn("submit", act["suggested_action"].lower())

    def test_genuine_application_deadline_preserved(self):
        """Application deadline must trigger High urgency and deadline_sensitive category."""
        sample_email = {
            "id": "grad-deadline",
            "sender": "University Admissions <admissions@gradschool.edu>",
            "subject": "Fall Application Status",
            "date": "Nov 17, 2026",
            "body": "Dear Applicant, please submit your internship application before November 27 to be considered for early review.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertEqual(act["urgency"], "High")
            self.assertEqual(act["category"], "deadline_sensitive")
            self.assertIn("November 27", act["deadline"])

    def test_genuine_followup_status_preserved(self):
        """Genuine follow-up inquiring about application progress must be detected as followup_required."""
        sample_email = {
            "id": "job-followup",
            "sender": "Hiring Team <jobs@startup.io>",
            "subject": "Application Status",
            "date": "Nov 19, 2026",
            "body": "Hi Sunil, checking in on the status of your internship application. Have you had a chance to complete the assessment?",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertEqual(act["category"], "followup_required")
            self.assertIn("status", act["reason"].lower())

    def test_university_tuition_action_preserved(self):
        """Tuition payment notice with due date must trigger High priority with approaching deadline."""
        sample_email = {
            "id": "bursar-tuition",
            "sender": "Bursar Office <bursar@university.edu>",
            "subject": "Tuition Payment Reminder",
            "date": "Nov 16, 2026",
            "body": "Notice: Your semester tuition payment is due by Nov 30. Please log into the student portal to pay.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertEqual(act["urgency"], "High")
            self.assertIn("Nov 30", act["deadline"])
            self.assertIn("payment", act["reason"].lower())

    def test_confirmation_request_preserved(self):
        """Request to confirm event attendance must be detected with appropriate action recommendation."""
        sample_email = {
            "id": "team-dinner",
            "sender": "Team Lead <lead@company.com>",
            "subject": "Team Dinner Next Week",
            "date": "Nov 19, 2026",
            "body": "Hi everyone, please confirm whether you will attend the team dinner on Thursday so we can finalize reservations.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertIn("confirm", act["suggested_action"].lower())
            self.assertIn("attend", act["suggested_action"].lower())

    def test_pending_thread_response_preserved(self):
        """Request for agreement confirmation on contract terms must be actionable."""
        sample_email = {
            "id": "partner-terms",
            "sender": "Contract Partner <partner@biz.com>",
            "subject": "Revised Partnership Terms",
            "date": "Nov 18, 2026",
            "body": "Hi Sunil, attached is the revised agreement. Please let us know if these terms are acceptable so we can proceed.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertEqual(act["category"], "reply_required")


class TestIntegrityAndAntiFabrication(unittest.TestCase):
    """Verifies that recommendations and deadlines are strictly grounded in email evidence."""

    def setUp(self):
        self.mail_actions = MailAutomation(dry_run=True)

    def test_no_deadline_fabricated_when_none_exists(self):
        """When an email requests review without a date, deadline must be None."""
        sample_email = {
            "id": "review-no-date",
            "sender": "Colleague John <john@work.io>",
            "subject": "Code Review Request",
            "date": "Nov 19, 2026",
            "body": "Hi Sunil, could you please review the new pull request when you get a chance?",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertIsNone(act["deadline"], "Deadline must be None when no deadline was stated")
            self.assertNotIn("deadline", act["reason"].lower())

    def test_no_status_update_fabricated_for_resume_request(self):
        """A resume request must NOT recommend 'Acknowledge the follow-up and provide a status update'."""
        sample_email = {
            "id": "resume-req",
            "sender": "Jessica Recruiter <recruiter@innovate.ai>",
            "subject": "Application Follow-up",
            "date": "Nov 19, 2026",
            "body": "Hi Sunil, could you please send over your resume? We'd like to schedule an interview.",
        }
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": [sample_email]}
            mock_get_msg.return_value = {"ok": True, "email": sample_email}

            res = self.mail_actions.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)
            act = res["actions"][0]
            self.assertNotEqual(act["suggested_action"], "Acknowledge the follow-up and provide a status update.")
            self.assertIn("resume", act["suggested_action"].lower())

    def test_all_promotional_yields_clean_empty_reporting(self):
        """When all emails in inbox are promotional, the message must gracefully state zero actionable items."""
        sample_emails = [
            {
                "id": "promo-1",
                "sender": "TradingView <noreply@tradingview.com>",
                "subject": "Black Friday is coming — mark your calendar",
                "date": "Nov 18, 2026",
                "body": "Biggest sale of the year on Nov 27. Unsubscribe.",
            },
            {
                "id": "promo-2",
                "sender": "Retail Deals <deals@retail.com>",
                "subject": "Don't miss our holiday discounts",
                "date": "Nov 17, 2026",
                "body": "50% off everything this weekend. Opt-out here.",
            },
            {
                "id": "promo-3",
                "sender": "Tech Newsletter <newsletter@tech.com>",
                "subject": "Weekly Digest #89",
                "date": "Nov 16, 2026",
                "body": "What's new in cloud computing? Unsubscribe from updates.",
            },
        ]
        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": sample_emails}
            mock_get_msg.side_effect = lambda msg_id: {
                "ok": True,
                "email": next((e for e in sample_emails if e["id"] == msg_id), {}),
            }

            res = self.mail_actions.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["actions"]), 0)
            self.assertIn("I checked the emails available to me. I couldn't identify any messages that clearly require a reply or action.", res["message"])
            self.assertIn("Reviewed last 3 inbox messages", res["message"])


class TestOrchestratorIntegrationBatch2_1(unittest.TestCase):
    """Verifies orchestrator natural language handling for 'Is there anything I need to respond to?'."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_mixed_inbox_excludes_tradingview_and_includes_genuine_task(self):
        """Orchestrator end-to-end chat returns genuine task and completely excludes TradingView."""
        sample_emails = [
            {
                "id": "tv-bf",
                "sender": "TradingView <noreply@tradingview.com>",
                "subject": "Black Friday is coming — mark your calendar",
                "date": "Nov 18, 2026",
                "body": "Get ready for the biggest sale of the year on Nov 27. Unsubscribe.",
            },
            {
                "id": "prof-smith",
                "sender": "Prof. Smith <prof.smith@university.edu>",
                "subject": "Project Progress Review",
                "date": "Nov 19, 2026, 9:00 AM",
                "body": "Hi Sunil, could you please explain the authentication flow in your prototype by Friday?",
            },
        ]
        with patch.object(self.orch.mail_automation, "read_mail") as mock_read, \
             patch.object(self.orch.mail_automation, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": sample_emails}
            mock_get_msg.side_effect = lambda msg_id: {
                "ok": True,
                "email": next((e for e in sample_emails if e["id"] == msg_id), {}),
            }

            res = self.orch.chat("Is there anything I need to respond to?")
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            msg = res["message"]

            # Must NOT contain TradingView or marketing recommendations
            self.assertNotIn("TradingView", msg)
            self.assertNotIn("Acknowledge the follow-up and provide a status update", msg)

            # Must contain Prof. Smith action item
            self.assertIn("Prof. Smith", msg)
            self.assertIn("Project Progress Review", msg)
            self.assertIn("High priority", msg)

    def test_all_promotional_inbox_returns_clean_response(self):
        """Orchestrator chat returns zero-action message when only marketing emails exist."""
        sample_emails = [
            {
                "id": "promo-tv",
                "sender": "TradingView <noreply@tradingview.com>",
                "subject": "Black Friday is coming — mark your calendar",
                "date": "Nov 18, 2026",
                "body": "Get ready for Black Friday discounts. Unsubscribe.",
            },
        ]
        with patch.object(self.orch.mail_automation, "read_mail") as mock_read, \
             patch.object(self.orch.mail_automation, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": sample_emails}
            mock_get_msg.side_effect = lambda msg_id: {
                "ok": True,
                "email": next((e for e in sample_emails if e["id"] == msg_id), {}),
            }

            res = self.orch.chat("Is there anything I need to respond to?")
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertIn("couldn't identify any messages that clearly require a reply or action", res["message"])
            self.assertNotIn("TradingView", res["message"])


if __name__ == "__main__":
    unittest.main()
