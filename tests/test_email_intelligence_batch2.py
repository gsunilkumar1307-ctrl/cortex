"""
tests/test_email_intelligence_batch2.py
======================================
Batch 2 Test Suite: Goal-Oriented Email Agent + Native Email Skill

Verifies the 7 core Batch 2 objectives:
1. Native SKILL.md runtime loading, discovery, and targeted prompt injection.
2. Task 1: Search interpretation & execution ("Find emails from Apple about my account").
3. Task 2: Full email body retrieval & summarization ("Summarize the latest email from IBM").
4. Task 3: Inbox intelligence & action item extraction ("Is there anything I need to respond to?").
5. Task 4: Autonomous drafting ("Write Rahul an email asking about internship opportunities").
6. Task 5: Self-identity resolution ("Write a mail to myself requesting leave tomorrow").
7. Task 6: Contextual reply ("Reply to this email thanking them and asking what happens next").
8. Task 7: Bounded recovery on search failure.
9. Quota/429 circuit breaker and deterministic fallback continuity.
10. Send-gate safety enforcement (CORTEX_ALLOW_REAL_EMAIL_SEND).
"""

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.agent.orchestrator import CortexOrchestrator
from backend.agent.skill_loader import SkillLoader
from backend.agent.email_engine import (
    ProfessionalEmailEngine,
    EmailDraft,
    convert_instruction_to_recipient_content,
)
from backend.capabilities.mail_actions import MailAutomation
from backend.capabilities.safety import is_real_email_send_allowed
from backend.core.contracts import RiskLevel, Task, TaskCommand, TaskStatus
from backend.tools.mail_tool import MailTool


class TestSkillLoaderAndRuntimeInjection(unittest.TestCase):
    """Verifies Section 1: SKILL.md discovery, parsing, and orchestrator injection."""

    def setUp(self):
        self.loader = SkillLoader()

    def test_skill_discovery_and_frontmatter(self):
        """SKILL.md must be discovered, parsed, and contain valid frontmatter."""
        skill = self.loader.get_skill("email-agent")
        self.assertIsNotNone(skill, "email-agent skill must be discovered")
        self.assertEqual(skill.name, "email-agent")
        self.assertEqual(skill.version, "1.0.0")
        self.assertIn("search", skill.triggers)
        self.assertIn("summarize", skill.triggers)
        self.assertIn("draft", skill.triggers)
        self.assertIn("reply", skill.triggers)
        self.assertIn("respond to", skill.triggers)
        self.assertTrue(len(skill.instructions) > 500, "SKILL.md instructions must be substantial")

    def test_is_email_task_classification(self):
        """SkillLoader accurately distinguishes email tasks from general tasks."""
        email_queries = [
            "Find emails from Apple about my account",
            "Summarize the latest email from IBM",
            "Is there anything I need to respond to?",
            "What emails need my attention?",
            "Write Rahul an email asking about internship opportunities",
            "Reply to this email thanking them and asking what happens next",
            "Check my unread emails",
            "Forward the email from Google to john@example.com",
        ]
        non_email_queries = [
            "What is the capital of France?",
            "Open Safari",
            "Calculate 45 * 12",
            "Take a screenshot",
            "Create a note titled Shopping List",
        ]

        for q in email_queries:
            self.assertTrue(self.loader.is_email_task(q), f"Query should be an email task: {q}")

        for q in non_email_queries:
            self.assertFalse(self.loader.is_email_task(q), f"Query should NOT be an email task: {q}")

    def test_prompt_extension_generation(self):
        """Prompt extension must be non-empty for email tasks and empty for non-email tasks."""
        ext_email = self.loader.get_prompt_extension_for_task("Summarize the latest email from IBM")
        self.assertIn("Cortex Email Agent Skill", ext_email)
        self.assertIn("bounded execution cycle", ext_email.lower())

        ext_general = self.loader.get_prompt_extension_for_task("What is the capital of France?")
        self.assertEqual(ext_general, "", "Non-email tasks must not receive email skill prompt extensions")

    def test_orchestrator_runtime_skill_tracking(self):
        """Orchestrator records loaded skills in task.metadata and self.active_skills."""
        orch = CortexOrchestrator(use_gemini=False)
        with patch.object(orch.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(ok=True, data={"emails": []}, message="Found 0 emails")
            res = orch.chat("Find emails from Apple about my account")
            self.assertTrue(orch.is_skill_active("email-agent"))
            self.assertIn("email-agent", res["task"].get("metadata", {}).get("loaded_skills", []))

        # Non-email task
        res_math = orch.chat("What is 10 + 15?")
        self.assertFalse(orch.is_skill_active("email-agent"))
        self.assertEqual(res_math["task"].get("metadata", {}).get("loaded_skills", []), [])


class TestTask1SearchInterpretation(unittest.TestCase):
    """Task 1: Search interpretation & execution ('Find emails from Apple about my account')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_search_parameter_extraction(self):
        """Interprets sender and topic cleanly without contamination."""
        query = "Find emails from Apple about my account"
        params = self.orch._extract_mail_search_params(query)
        self.assertEqual(params.get("sender"), "Apple")
        self.assertEqual(params.get("query"), "my account")

    def test_search_execution_and_presentation(self):
        """Executes search and formats grounded results."""
        mock_emails = [
            {
                "id": "app-101",
                "account": "iCloud",
                "mailbox": "INBOX",
                "sender": "Apple <no_reply@apple.com>",
                "subject": "Your Apple ID security code",
                "date": "Today, 10:15 AM",
                "is_read": False,
            }
        ]
        with patch.object(self.orch.automation, "execute") as mock_exec:
            mock_exec.return_value = MagicMock(
                ok=True,
                data={"emails": mock_emails, "coverage": {"status": "complete"}, "execution_engine": "mcp"},
                message="Found 1 matching email(s)",
            )
            res = self.orch.chat("Find emails from Apple about my account")
            self.assertEqual(res["task"]["status"], TaskStatus.COMPLETED.value)
            self.assertIn("Apple ID security code", res["message"])
            self.assertIn("[UNREAD]", res["message"])
            self.assertIn("iCloud: INBOX", res["message"])


class TestTask2FullEmailSummarization(unittest.TestCase):
    """Task 2: Full email body retrieval & summarization ('Summarize the latest email from IBM')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_routing_and_full_body_enrichment(self):
        """Identifies SUMMARIZE_MAIL, fetches full body via get_message, and summarizes."""
        mock_inbox_email = {
            "id": "ibm-msg-999",
            "sender": "IBM Cloud <support@ibm.com>",
            "subject": "Cloud Infrastructure Quarterly Maintenance",
            "date": "Yesterday, 3:00 PM",
            "snippet": "Short preview...",
        }
        full_rfc_body = (
            "Dear Customer,\n\n"
            "This is a formal notice regarding scheduled quarterly infrastructure maintenance.\n"
            "All services in us-east region will undergo 15 minutes of scheduled downtime.\n"
            "Please ensure backups are synchronized before midnight on Friday.\n\n"
            "Best regards,\nIBM Cloud Support Team"
        )

        with patch.object(self.orch.mail_automation, "search_mail") as mock_search, \
             patch.object(self.orch.mail_automation, "get_message") as mock_get_msg:
            mock_search.return_value = {"ok": True, "emails": [mock_inbox_email]}
            mock_get_msg.return_value = {
                "ok": True,
                "email": {
                    "id": "ibm-msg-999",
                    "sender": "IBM Cloud <support@ibm.com>",
                    "subject": "Cloud Infrastructure Quarterly Maintenance",
                    "body": full_rfc_body,
                },
            }

            res = self.orch.chat("Summarize the latest email from IBM")
            self.assertEqual(res["task"]["command"], TaskCommand.SUMMARIZE_MAIL.value)
            mock_get_msg.assert_called_with("ibm-msg-999")
            self.assertIn("scheduled quarterly infrastructure maintenance", res["message"])
            self.assertIn("IBM Cloud", res["message"])


class TestTask3InboxIntelligence(unittest.TestCase):
    """Task 3: Inbox intelligence & action item extraction ('Is there anything I need to respond to?')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.mail_actions = MailAutomation()

    def test_intent_routing_for_action_extraction(self):
        """'Is there anything I need to respond to?' routes to EXTRACT_ACTIONS."""
        analysis = self.orch._analyze_intent_fallback("Is there anything I need to respond to?")
        self.assertEqual(analysis["command"], TaskCommand.EXTRACT_ACTIONS)

        analysis2 = self.orch._analyze_intent_fallback("What emails need my attention?")
        self.assertEqual(analysis2["command"], TaskCommand.EXTRACT_ACTIONS)

    def test_inbox_intelligence_filtering_and_ranking(self):
        """Filters marketing emails, detects questions/deadlines, ranks urgency, and discloses scope."""
        sample_emails = [
            {
                "id": "promo-1",
                "sender": "Marketing Deals <offers@promo.store.com>",
                "subject": "50% off all shoes this weekend only!",
                "date": "Today, 9:00 AM",
                "body": "Unsubscribe here. Special sale on footwear. Don't miss out on savings!",
            },
            {
                "id": "urgent-prof",
                "sender": "Prof. Smith <prof.smith@university.edu>",
                "subject": "Research Project Submission",
                "date": "Today, 11:30 AM",
                "body": "Hi, could you please submit your final project report by 5 PM today? Are you on track?",
            },
            {
                "id": "recruiter-1",
                "sender": "HR Recruiter <recruiting@techcorp.io>",
                "subject": "Interview Scheduling",
                "date": "Yesterday, 2:00 PM",
                "body": "Hi, please confirm if you are available for a 30-minute technical interview tomorrow.",
            },
        ]

        with patch.object(self.mail_actions, "read_mail") as mock_read, \
             patch.object(self.mail_actions, "get_message") as mock_get_msg:
            mock_read.return_value = {"ok": True, "emails": sample_emails}
            mock_get_msg.side_effect = lambda msg_id: {
                "ok": True,
                "email": next((e for e in sample_emails if e["id"] == msg_id), {}),
            }

            report = self.mail_actions.extract_actions(limit=10)
            self.assertTrue(report["ok"])
            msg = report["message"]

            # Marketing noise discarded
            self.assertNotIn("50% off all shoes", msg)

            # High priority action item detected
            self.assertIn("Prof. Smith", msg)
            self.assertIn("[High Priority]", msg)
            self.assertIn("Contains an upcoming deadline", msg)

            # Recruiter interview detected
            self.assertIn("HR Recruiter", msg)

            # Scope disclosure present
            self.assertIn("Reviewed last 3 inbox messages", msg)


class TestTask4AutonomousDrafting(unittest.TestCase):
    """Task 4: Autonomous drafting ('Write Rahul an email asking about internship opportunities')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)
        self.orch.pending_action = None

    def test_autonomous_draft_generation(self):
        """Infers complete professional body and presents draft review card without sending."""
        query = "Write Rahul an email asking about internship opportunities"
        with patch.object(self.orch.recipient_resolver, "resolve") as mock_resolve, \
             patch.object(self.orch.automation, "execute") as mock_exec:
            from backend.agent.recipient_resolver import ResolutionResult, ResolvedRecipient
            mock_resolve.return_value = ResolutionResult(
                status="resolved",
                recipient=ResolvedRecipient(
                    name="Rahul",
                    email="rahul@example.com",
                    source="mock",
                    confidence=1.0,
                ),
            )
            mock_exec.return_value = MagicMock(ok=True, data={"draft_id": "draft-101"})

            res = self.orch.chat(query)
            task = res["task"]
            self.assertIn(task["status"], (TaskStatus.COMPLETED.value, TaskStatus.WAITING_APPROVAL.value))
            self.assertIn("rahul@example.com", res["message"])
            self.assertIn("Internship Opportunities", res["message"])
            # Draft body must be generated, not empty or generic
            draft_params = task.get("params", {})
            self.assertTrue(len(draft_params.get("body", "")) > 100)
            self.assertIn("internship", draft_params.get("body", "").lower())


class TestTask5SelfIdentityResolution(unittest.TestCase):
    """Task 5: Self-identity resolution ('Write a mail to myself requesting leave tomorrow')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_self_identity_with_connected_account(self):
        """Resolves connected account email as recipient and drafts leave request."""
        query = "Write a mail to myself requesting leave tomorrow"
        with patch.object(self.orch.mail_automation, "get_accounts") as mock_acc, \
             patch.object(self.orch.automation, "execute") as mock_exec:
            mock_acc.return_value = [
                {"name": "Personal", "email": "sunil@gmail.com", "enabled": True}
            ]
            mock_exec.return_value = MagicMock(ok=True, data={"draft_id": "draft-self-1"})

            res = self.orch.chat(query)
            task = res["task"]
            self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertIn("sunil@gmail.com", res["message"])
            self.assertIn("Leave Tomorrow", res["message"])

    def test_self_identity_zero_accounts_safe_halt(self):
        """When no accounts are connected, halts safely without crashing or hallucinating."""
        query = "Write a mail to myself requesting leave tomorrow"
        with patch.object(self.orch.mail_automation, "get_accounts") as mock_acc:
            mock_acc.return_value = []
            res = self.orch.chat(query)
            task = res["task"]
            self.assertEqual(task["status"], TaskStatus.NEED_INFO.value)
            self.assertIn("No connected email accounts", res["message"])


class TestTask6ContextualReply(unittest.TestCase):
    """Task 6: Contextual reply ('Reply to this email thanking them and asking what happens next')."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_contextual_reply_participle_body_conversion(self):
        """Instruction 'thanking them and asking what happens next' becomes professional text."""
        body, meta = convert_instruction_to_recipient_content("thanking them and asking what happens next")
        self.assertIn("Thank you very much for the update", body)
        self.assertIn("what happens next", body)

    def test_contextual_reply_e2e_workflow(self):
        """Picks up context from recent emails, threads headers, and presents draft card."""
        thread_msg = {
            "id": "thread-456",
            "account": "Work",
            "mailbox": "INBOX",
            "sender": "Alice Smith <alice.smith@techcorp.com>",
            "subject": "Interview Update: Stage 2 Complete",
            "date": "Today, 10:00 AM",
            "body": "Hi, the team enjoyed speaking with you. We will be in touch shortly.",
        }

        # Populate last_mail_results on orchestrator to simulate previous context
        self.orch.last_mail_results = [thread_msg]

        with patch.object(self.orch.mail_automation, "get_message") as mock_get_msg, \
             patch.object(self.orch.mail_automation, "get_message_headers") as mock_headers, \
             patch.object(self.orch.automation, "execute") as mock_exec:
            mock_get_msg.return_value = {"ok": True, "email": thread_msg}
            mock_headers.return_value = {
                "ok": True,
                "rfc_message_id": "<msg-stage2-456@techcorp.com>",
                "references": ["<msg-stage1-123@techcorp.com>"],
            }
            mock_exec.return_value = MagicMock(ok=True, data={"draft_id": "draft-reply-789"})

            res = self.orch.chat("Reply to this email thanking them and asking what happens next")
            task = res["task"]
            self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
            self.assertIn("Re: Interview Update: Stage 2 Complete", res["message"])
            self.assertIn("alice.smith@techcorp.com", res["message"])
            self.assertIn("Draft created and saved to your mailbox", res["message"])
            self.assertEqual(task["params"].get("draft_id"), "draft-reply-789")

            # Verify threading headers recorded
            self.assertEqual(task["params"].get("in_reply_to"), "<msg-stage2-456@techcorp.com>")


class TestTask7BoundedRecovery(unittest.TestCase):
    """Task 7: Bounded recovery on search failure."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_search_bounded_recovery_relax_criteria(self):
        """When strict subject search yields 0 results, retries with broad query."""
        initial_fail = MagicMock(ok=True, data={"emails": []}, message="No emails found")
        recovered_success = MagicMock(
            ok=True,
            data={
                "emails": [
                    {
                        "id": "rec-1",
                        "sender": "Support <support@service.com>",
                        "subject": "Your Account Notification",
                        "date": "Today",
                    }
                ]
            },
            message="Found 1 matching email(s)",
        )

        with patch.object(self.orch.automation, "execute", side_effect=[initial_fail, recovered_success]) as mock_exec:
            task = Task(
                intent="Find emails about service notification",
                command=TaskCommand.SEARCH_MAIL,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                params={"subject": "service notification"},
            )
            self.orch._execute(task)

            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertIn("Your Account Notification", task.result)
            event_types = [getattr(e, "event_type", getattr(e, "name", "")) for e in task.events]
            self.assertIn("search_recovery_attempt", event_types)
            self.assertIn("search_recovered", event_types)

    def test_search_bounded_recovery_fails_gracefully_no_hallucination(self):
        """If recovery also yields 0 results, truthfully reports zero results without fabricating."""
        fail_mock = MagicMock(ok=True, data={"emails": []}, message="No emails found")

        with patch.object(self.orch.automation, "execute", return_value=fail_mock):
            task = Task(
                intent="Find emails about non-existent topic",
                command=TaskCommand.SEARCH_MAIL,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                params={"subject": "non-existent topic xyz123"},
            )
            self.orch._execute(task)

            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertIn("No emails found", task.result)
            self.assertNotIn("found 1", task.result.lower())


class TestCircuitBreakerAndSafetyGate(unittest.TestCase):
    """Circuit breaker cooldown and safety gate verification."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_quota_429_triggers_cooldown(self):
        """429 ResourceExhausted exception activates 3-minute cooldown."""
        exc = Exception("429 ResourceExhausted: Quota exceeded for quota metric 'Generate Content API'")
        self.orch._handle_gemini_error(exc, context="test")
        self.assertFalse(self.orch._is_gemini_available())

    def test_send_safety_gate_strict_enforcement(self):
        """is_real_email_send_allowed() MUST return True ONLY for exact '1'."""
        unsafe_values = ["", "0", "false", "False", "no", "off", "true", "yes", "None"]
        for val in unsafe_values:
            with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": val}):
                self.assertFalse(
                    is_real_email_send_allowed(),
                    f"CORTEX_ALLOW_REAL_EMAIL_SEND='{val}' must be blocked",
                )

        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "1"}):
            self.assertTrue(is_real_email_send_allowed())


class TestSection10IntentUnderstanding(unittest.TestCase):
    """Section 10: Intent understanding across all 11+ natural language goal variations & Indic triggers."""

    def test_natural_language_goal_variations(self):
        from backend.core.contracts import command_from_intent
        goals = [
            "Is there anything I need to respond to?",
            "Do I have any pending replies?",
            "Is anyone waiting for me?",
            "Did anyone ask me a question?",
            "What emails require my attention?",
            "What should I take care of today?",
            "Did anyone send me any important requests?",
            "Are there any deadlines in my emails?",
            "Find emails where I need to take action.",
            "What am I supposed to follow up on?",
            "Have I missed any important emails?",
            "Anyone waiting for me?",
            "What emails need my attention?",
            "Did anyone ask me to do something?",
            "pending replies in my inbox",
            "emails requiring my attention",
            "deadlines in my inbox",
            "ನಾನು ಉತ್ತರಿಸಬೇಕಾದ ಇಮೇಲ್‌ಗಳು ಇವೆಯೇ",
            "क्या मुझे किसी ईमेल का जवाब देना है",
            "நான் பதிலளிக்க வேண்டிய மின்னஞ்சல்கள்",
            "నేను సమాధానం ఇవ్వాల్సిన ఇమెయిల్‌లు"
        ]
        for g in goals:
            cmd = command_from_intent(g)
            self.assertEqual(cmd, TaskCommand.EXTRACT_ACTIONS, f"Goal '{g}' failed to route to EXTRACT_ACTIONS: got {cmd}")


class TestSection10ContentAnalysis(unittest.TestCase):
    """Section 10: Email content analysis and grounded categorization."""

    def setUp(self):
        self.mail = MailAutomation()

    def test_content_scenarios_and_filtering(self):
        emails = [
            # 1. Direct question
            {"id": "q1", "sender": "Alice <alice@work.com>", "subject": "Design Question", "date": "Nov 18", "body": "Could you please explain the authentication flow?"},
            # 2. Document request
            {"id": "d1", "sender": "HR <hr@company.com>", "subject": "Onboarding Documents", "date": "Nov 18", "body": "Please submit your signed offer letter and passport copy."},
            # 3. Deadline
            {"id": "dl1", "sender": "Professor <prof@edu.org>", "subject": "Final Paper", "date": "Nov 19", "body": "Please submit your thesis by Nov 25 at 5 PM."},
            # 4. Confirmation
            {"id": "c1", "sender": "Team Lead <lead@tech.co>", "subject": "Offsite Attendance", "date": "Nov 17", "body": "Please confirm whether you will attend the team dinner."},
            # 5. Informational FYI (ignored from action items)
            {"id": "fyi1", "sender": "Ops <ops@tech.co>", "subject": "System Maintenance", "date": "Nov 17", "body": "FYI: Server maintenance is scheduled for Sunday. No action needed."},
            # 6. Marketing / promotion (ignored from action items)
            {"id": "m1", "sender": "Promotions <deals@shop.com>", "subject": "50% off all shoes!", "date": "Nov 16", "body": "Unsubscribe here. Best footwear sale on sneakers!"},
            # 7. Thread where user already replied (ignored from pending)
            {"id": "t_replied", "sender": "Bob <bob@co.org>", "subject": "Question about budget", "date": "Nov 15", "body": "Can you send the budget?", "already_replied": True},
            # 8. Pending thread
            {"id": "t_pending", "sender": "Carol <carol@partner.com>", "subject": "Contract Draft", "date": "Nov 16", "body": "Following up on the contract draft. Any update?"},
            # 9. Ambiguous email (low priority, no fabricated deadline)
            {"id": "ambig1", "sender": "Dave <dave@friends.com>", "subject": "Catching up", "date": "Nov 14", "body": "Hey, let us catch up sometime next month."},
        ]

        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}), \
             patch.object(self.mail, "get_accounts", return_value=[{"name": "Work", "email": "user@work.com"}]):
            res = self.mail.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            msg = res["message"]

            # Direct question detected
            self.assertIn("Design Question", msg)
            # Document request detected
            self.assertIn("Onboarding Documents", msg)
            # Deadline detected with exact date
            self.assertIn("Final Paper", msg)
            self.assertIn("Nov 25", msg)
            # Confirmation detected
            self.assertIn("Offsite Attendance", msg)
            # Informational & marketing filtered out
            self.assertNotIn("System Maintenance", msg)
            self.assertNotIn("50% off all shoes", msg)
            # Already replied thread excluded
            self.assertNotIn("Question about budget", msg)
            # Pending thread included
            self.assertIn("Contract Draft", msg)
            # Summary present
            self.assertIn("Summary:", msg)
            # Scope present
            self.assertIn("Reviewed last 9 inbox messages across 1 connected account(s)", msg)


class TestSection10EdgeCases(unittest.TestCase):
    """Section 10: Edge case handling."""

    def setUp(self):
        self.mail = MailAutomation()

    def test_empty_inbox(self):
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": []}), \
             patch.object(self.mail, "get_accounts", return_value=[{"name": "Personal", "email": "me@gmail.com"}]):
            res = self.mail.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["actions"]), 0)
            self.assertIn("couldn't identify any messages that clearly require a reply or action", res["message"])
            self.assertIn("Reviewed last 0 inbox messages", res["message"])

    def test_no_actionable_emails(self):
        emails = [
            {"id": "1", "sender": "News <news@site.com>", "subject": "Daily Digest", "body": "Today headlines..."},
            {"id": "2", "sender": "Store <store@mall.com>", "subject": "Receipt for purchase", "body": "Thank you for your order!"},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}), \
             patch.object(self.mail, "get_accounts", return_value=[{"name": "Work", "email": "user@work.com"}]):
            res = self.mail.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["actions"]), 0)
            self.assertIn("couldn't identify any messages that clearly require a reply or action", res["message"])
            self.assertIn("Reviewed last 2 inbox messages", res["message"])

    def test_multiple_accounts_scope(self):
        emails = [
            {"id": "1", "sender": "Prof <prof@uni.edu>", "subject": "Assignment", "body": "Could you please submit the assignment by Friday?"}
        ]
        accounts = [{"name": "Work", "email": "w@co.com"}, {"name": "Uni", "email": "u@uni.edu"}]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}), \
             patch.object(self.mail, "get_accounts", return_value=accounts):
            res = self.mail.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertIn("across 2 connected account(s)", res["message"])

    def test_missing_body_and_long_body(self):
        emails = [
            {"id": "1", "sender": "Bob <b@co.com>", "subject": "Action required on invoice", "snippet": "Please approve"},
            {"id": "2", "sender": "Alice <a@co.com>", "subject": "Question", "body": "Could you review this?" + (" A" * 5000)},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}), \
             patch.object(self.mail, "get_accounts", return_value=[{"name": "Work", "email": "w@co.com"}]):
            res = self.mail.extract_actions(limit=10)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["actions"]), 2)

    def test_duplicate_deduplication(self):
        emails = [
            {"id": "dup1", "sender": "Same <s@co.com>", "subject": "Reminder", "body": "Please confirm."},
            {"id": "dup1", "sender": "Same <s@co.com>", "subject": "Reminder", "body": "Please confirm."},
        ]
        with patch.object(self.mail, "read_mail", return_value={"ok": True, "emails": emails}):
            res = self.mail.extract_actions(limit=10)
            self.assertEqual(len(res["actions"]), 1)


class TestSection10FailureHandlingAndSafety(unittest.TestCase):
    """Section 10: Model failure handling, local fallback disclosure, and read-only safety."""

    def setUp(self):
        self.orch = CortexOrchestrator(use_gemini=False)

    def test_local_fallback_limitation_disclosure(self):
        sample_emails = [
            {"id": "1", "sender": "Prof. Smith <prof@uni.edu>", "subject": "Lab Report", "body": "Could you please submit the lab report by 5 PM today?"}
        ]
        with patch.object(self.orch.mail_automation, "read_mail", return_value={"ok": True, "emails": sample_emails}):
            task = Task(
                intent="Is there anything I need to respond to?",
                command=TaskCommand.EXTRACT_ACTIONS,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                params={"limit": 10}
            )
            self.orch._execute(task)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertIn("Prof. Smith", task.result)
            self.assertIn("I analyzed the accessible emails using local extraction because the AI provider was temporarily unavailable", task.result)

    def test_action_item_review_is_strictly_read_only(self):
        """Action item extraction must never trigger email sending or draft mutation."""
        sample_emails = [
            {"id": "1", "sender": "Boss <boss@corp.com>", "subject": "Urgent Review", "body": "Please review and send your feedback ASAP."}
        ]
        with patch.object(self.orch.mail_automation, "read_mail", return_value={"ok": True, "emails": sample_emails}), \
             patch.object(self.orch.mail_automation, "send_mail") as mock_send, \
             patch.object(self.orch.mail_automation, "draft_mail") as mock_draft:
            task = Task(
                intent="What should I take care of today?",
                command=TaskCommand.EXTRACT_ACTIONS,
                risk_level=RiskLevel.LOW,
                requires_approval=False,
                params={"limit": 10}
            )
            self.orch._execute(task)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            mock_send.assert_not_called()
            mock_draft.assert_not_called()


if __name__ == "__main__":
    unittest.main()
