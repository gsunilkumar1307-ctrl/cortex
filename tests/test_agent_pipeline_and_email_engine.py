"""
Comprehensive tests for Cortex Core Agent Execution Pipeline and Professional Email Engine.
Validates:
1. Pipeline Requirements A through Z:
   A: Basic question
   B: Safe command
   C: Multi-step task
   D: Email generation
   E: Different recipient roles
   F: Different relationship contexts
   G: Different tones
   H: Professional vs casual request
   I: Missing recipient context
   J: Ambiguous recipient
   K: Command/content separation
   L: Approval required
   M: Approval accepted
   N: Approval rejected
   O: Edit then approve
   P: Tool failure
   Q: Observation failure
   R: Verification failure
   S: Recovery
   T: Retry limit
   U: Timeout
   V: Cancellation
   W: Duplicate protection
   X: External service unavailable
   Y: Unexpected UI state
   Z: Email send verification

2. Golden Email Test Matrix:
   - Professor
   - Manager
   - Recruiter
   - Client
   - Colleague
   - Unknown recipient
   - Formal request
   - Neutral request
   - Friendly professional request
   - Very concise request
   - Follow-up email
   - Reply to thread
   - Edited draft
   - Cancelled draft
   - Failed send
   - Uncertain send result
   - Duplicate-send protection
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))
sys.path.insert(0, str(ROOT / "automation-engine"))
sys.path.insert(0, str(ROOT / "memory-service"))
sys.path.insert(0, str(ROOT / "cloud-brain" / "app"))

from cortex_automation import DeviceAutomation
from cortex_automation.mail_actions import _draft_records, _sent_records, clear_mail_records
from cortex_memory import EncryptedMemoryStore
from cortex_sdk.contracts import (
    ApprovalRequest,
    ExecutionError,
    ExecutionResult,
    FinalResult,
    Observation,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskContext,
    TaskStatus,
    VerificationResult,
)
from email_engine import ProfessionalEmailEngine
from execution_engine import ExecutionEngine
from orchestrator import CortexOrchestrator
from policy import PolicyEngine
from tools.base import BaseTool
from tools.mail_tool import MailTool
from tools.registry import ToolRegistry


class TestAgentPipelineAndEmailEngine(unittest.TestCase):
    def setUp(self):
        clear_mail_records()
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.automation = DeviceAutomation(dry_run=True)
        self.orchestrator = CortexOrchestrator(self.automation, self.memory, use_gemini=False)

    def tearDown(self):
        clear_mail_records()
        self.tmp.cleanup()

    # =========================================================================
    # PART 1: REQUIREMENTS A THROUGH Z
    # =========================================================================

    def test_requirement_a_basic_question(self):
        """A. Basic question: answered directly, no approval required, completed."""
        resp = self.orchestrator.chat("What is AI?")
        self.assertIn("message", resp)
        self.assertTrue(len(resp["message"]) > 0)
        # Should not require approval for simple knowledge query
        if resp.get("task"):
            self.assertFalse(resp["task"].get("requiresApproval", False))

    def test_requirement_b_safe_command(self):
        """B. Safe command: executes automatically without approval and verifies."""
        resp = self.orchestrator.chat("open calculator")
        task = resp.get("task")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "completed")
        self.assertFalse(task["requiresApproval"])

    def test_requirement_c_multi_step_task(self):
        """C. Multi-step task: decomposes and executes sequential plan steps."""
        plan_steps = [
            PlanStep(id="s1", action="Open Notes", tool="desktop_tool", inputs={"command": "open_app", "appName": "Notes"}),
            PlanStep(id="s2", action="Type notes", tool="desktop_tool", inputs={"command": "type_text", "text": "Meeting notes"}),
        ]
        plan = Plan(id="p1", task_id="t1", goal="Take meeting notes", steps=plan_steps)
        task = Task(id="t1", command="take notes", plan=plan)

        exec_engine = ExecutionEngine(self.orchestrator.tools, self.orchestrator.policy)
        result = exec_engine.execute_plan(task)

        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertEqual(len(task.observations), 2)
        self.assertEqual(len(task.verifications), 2)
        for v in task.verifications:
            self.assertTrue(v.verified)

    def test_requirement_d_email_generation(self):
        """D. Email generation: produces structured draft with no generic filler."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            recipient="prof.smith@university.edu",
            command="Email my professor asking for one more day to submit the assignment",
            relationship_type="professor",
        )
        self.assertIn("assignment", draft.body.lower())
        self.assertNotIn("hope this email finds you well", draft.body.lower())
        self.assertNotIn("kindly do the needful", draft.body.lower())
        self.assertTrue(draft.quality_report.approved)
        self.assertTrue(draft.quality_report.scores["no_generic_filler"] >= 8)

    def test_requirement_e_different_recipient_roles(self):
        """E. Different recipient roles: professor, manager, recruiter, client, colleague."""
        engine = ProfessionalEmailEngine()

        # Professor
        prof_draft = engine.generate_email_draft("prof@mit.edu", "Request extension for thesis submission", relationship_type="professor")
        self.assertIn("respectful", prof_draft.tone)
        self.assertTrue("extension" in prof_draft.subject.lower() or "thesis" in prof_draft.subject.lower())

        # Manager
        mgr_draft = engine.generate_email_draft("boss@tech.com", "I will be late because of traffic", relationship_type="manager")
        self.assertIn("concise", mgr_draft.tone)
        self.assertIn("traffic", mgr_draft.body.lower())

        # Recruiter
        rec_draft = engine.generate_email_draft("hr@corp.com", "Ask whether interview is confirmed for tomorrow", relationship_type="recruiter")
        self.assertIn("interview", rec_draft.body.lower())
        self.assertIn("confirmed", rec_draft.body.lower())

        # Client
        client_draft = engine.generate_email_draft("client@acme.com", "Tell client we completed the requested changes", relationship_type="client")
        self.assertIn("changes", client_draft.body.lower())

        # Colleague
        colleague_draft = engine.generate_email_draft("arjun@team.internal", "Finished the report and you can review it", relationship_type="colleague")
        self.assertIn("report", colleague_draft.body.lower())

    def test_requirement_f_different_relationship_contexts(self):
        """F. Different relationship contexts: friend vs vendor vs academic."""
        engine = ProfessionalEmailEngine()

        friend = engine.generate_email_draft("alex@gmail.com", "Catch up this weekend for coffee", relationship_type="friend")
        self.assertIn("coffee", friend.body.lower())
        self.assertEqual(friend.tone, "casual_warm")

        vendor = engine.generate_email_draft("supplies@vendor.com", "Inquire about invoice status", relationship_type="vendor")
        self.assertEqual(vendor.tone, "professional_direct")

    def test_requirement_g_different_tones(self):
        """G. Different tones: formal vs concise vs urgent."""
        engine = ProfessionalEmailEngine()

        formal = engine.generate_email_draft("director@org.org", "Submit annual evaluation", user_tone_override="formal")
        self.assertEqual(formal.tone, "formal")

        concise = engine.generate_email_draft("team@org.org", "Server maintenance scheduled for 10 PM", user_tone_override="concise")
        self.assertEqual(concise.tone, "concise")

    def test_requirement_h_professional_vs_casual_request(self):
        """H. Professional vs casual request produces distinct greeting and structure."""
        engine = ProfessionalEmailEngine()
        prof_res = engine.generate_email_draft("dr.lee@lab.org", "Submit research update", user_tone_override="formal")
        cas_res = engine.generate_email_draft("buddy@domain.com", "Submit research update", user_tone_override="casual")

        self.assertNotEqual(prof_res.body, cas_res.body)
        self.assertIn("Dr.", prof_res.body)

    def test_requirement_i_missing_recipient_context(self):
        """I. Missing recipient context uses neutral polite style without inventing roles."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft("contact123@example.com", "Request information regarding the scheduled webinar")
        self.assertEqual(draft.relationship_inferred, "unknown")
        self.assertNotIn("Professor", draft.body)
        self.assertNotIn("Manager", draft.body)
        self.assertIn("webinar", draft.body.lower())

    def test_requirement_j_ambiguous_recipient(self):
        """J. Ambiguous recipient: asks for clarification or email address."""
        resp = self.orchestrator.chat("Send an email to someone")
        # Should ask who or what recipient
        self.assertTrue(
            "specify" in resp["message"].lower()
            or "who" in resp["message"].lower()
            or "recipient" in resp["message"].lower()
            or "email" in resp["message"].lower()
        )

    def test_requirement_k_command_content_separation(self):
        """K. Command/content separation: user command is NOT mechanically copied to body or subject."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "rahul@example.com",
            "Send an email to Rahul saying I will reach Kundapur on October 9.",
            recipient_name="Rahul",
        )
        self.assertFalse(draft.subject.lower().startswith("send an email to"))
        self.assertNotIn("Send an email to Rahul", draft.body)
        self.assertIn("Kundapur", draft.body)
        self.assertIn("October 9", draft.body)

    def test_requirement_l_approval_required(self):
        """L. Approval required: Email drafting stops in waiting_approval before any send."""
        resp = self.orchestrator.chat("Send an email to sarah@domain.com saying the project is ready for review")
        task = resp.get("task")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "waiting_approval")
        self.assertTrue(task["requiresApproval"])
        # Ensure no email was sent yet
        self.assertEqual(len(_sent_records), 0)

    def test_requirement_m_approval_accepted(self):
        """M. Approval accepted: approving the task sends email and verifies in Sent."""
        resp = self.orchestrator.chat("Send an email to sarah@domain.com saying the project is ready for review")
        task_id = resp["task"]["id"]

        approved = self.orchestrator.approve(task_id, True)
        self.assertEqual(approved["status"], "completed")
        self.assertEqual(len(_sent_records), 1)
        self.assertEqual(_sent_records[0]["recipient"], "sarah@domain.com")

    def test_requirement_n_approval_rejected(self):
        """N. Approval rejected: rejecting cancels the task and sends nothing."""
        resp = self.orchestrator.chat("Send an email to client@domain.com saying we need more time")
        task_id = resp["task"]["id"]

        rejected = self.orchestrator.approve(task_id, False)
        self.assertEqual(rejected["status"], "canceled")
        self.assertEqual(len(_sent_records), 0)

    def test_requirement_o_edit_then_approve(self):
        """O. Edit then approve: follow-up modifies draft, re-verifies, and waits for approval."""
        resp1 = self.orchestrator.chat("Send an email to boss@company.com saying I will be late due to traffic")
        task_id = resp1["task"]["id"]
        original_body = resp1["task"]["params"]["body"]

        # User requests edit
        resp2 = self.orchestrator.chat("make it shorter")
        task2 = resp2["task"]
        self.assertEqual(task2["id"], task_id)
        self.assertEqual(task2["status"], "waiting_approval")
        self.assertNotEqual(task2["params"]["body"], original_body)
        self.assertTrue(len(task2["params"]["body"]) < len(original_body) or "traffic" in task2["params"]["body"].lower())

        # Now approve
        approved = self.orchestrator.approve(task_id, True)
        self.assertEqual(approved["status"], "completed")
        self.assertEqual(len(_sent_records), 1)

    def test_requirement_p_tool_failure(self):
        """P. Tool failure: handles error gracefully, marks status failed with clear message."""
        class FailingTool(BaseTool):
            def execute(self, inputs, context=None):
                return ExecutionResult(step_id="s1", ok=False, message="Hardware device unreachable", error="DeviceError")
            def observe(self, inputs, exec_result):
                return Observation(target="device", state_data={"connected": False})
            def verify(self, inputs, observation, exec_result):
                return VerificationResult(verified=False, evidence="Device offline")
            def recover(self, inputs, error, attempt):
                return {"can_retry": False, "strategy": "abort", "message": "Device offline permanently"}

        registry = ToolRegistry()
        registry.register_instance("fail_tool", FailingTool(name="fail_tool", description="fails", risk_level=RiskLevel.LOW))
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Ping device", tool="fail_tool", inputs={})
        task = Task(id="t_fail", command="ping", plan=Plan(id="p_fail", task_id="t_fail", goal="ping", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("Device offline", result.summary)

    def test_requirement_q_observation_failure(self):
        """Q. Observation failure: missing expected state leads to verification failure."""
        class UnobservableTool(BaseTool):
            def execute(self, inputs, context=None):
                return ExecutionResult(step_id="s1", ok=True, message="Sent command to motor")
            def observe(self, inputs, exec_result):
                # Sensor failed to respond
                return Observation(target="motor", state_data={}, raw_output="sensor timeout")
            def verify(self, inputs, observation, exec_result):
                if not observation.state_data.get("position_confirmed"):
                    return VerificationResult(verified=False, evidence="Sensor timeout: motor position unverified")
                return VerificationResult(verified=True)
            def recover(self, inputs, error, attempt):
                return {"can_retry": False, "strategy": "stop_safely", "message": "Motor state unverified, stopping."}

        registry = ToolRegistry()
        registry.register_instance("motor_tool", UnobservableTool(name="motor_tool", description="motor", risk_level=RiskLevel.MEDIUM))
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Move motor", tool="motor_tool", inputs={})
        task = Task(id="t_motor", command="move motor", plan=Plan(id="p_motor", task_id="t_motor", goal="move", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("unverified", result.summary.lower())

    def test_requirement_r_verification_failure(self):
        """R. Verification failure: never claims success when verification check returns false."""
        class FalseClaimTool(BaseTool):
            def execute(self, inputs, context=None):
                return ExecutionResult(step_id="s1", ok=True, message="Success reported by API")
            def observe(self, inputs, exec_result):
                return Observation(target="api", state_data={"db_record_found": False})
            def verify(self, inputs, observation, exec_result):
                # Independent database verification failed
                return VerificationResult(verified=False, evidence="Record not found in database")
            def recover(self, inputs, error, attempt):
                return {"can_retry": False, "strategy": "fail", "message": "Verification failed: not in DB"}

        registry = ToolRegistry()
        registry.register_instance("claim_tool", FalseClaimTool(name="claim_tool", description="claim", risk_level=RiskLevel.LOW))
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Write data", tool="claim_tool", inputs={})
        task = Task(id="t_db", command="write data", plan=Plan(id="p_db", task_id="t_db", goal="write", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertFalse(any(v.verified for v in task.verifications))

    def test_requirement_s_recovery_via_state_check(self):
        """S. Recovery: transient error resolved by checking actual state."""
        class FlakyNetworkTool(BaseTool):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.calls = 0

            def execute(self, inputs, context=None):
                self.calls += 1
                # Timeout occurred after remote submission
                return ExecutionResult(step_id="s1", ok=False, message="HTTP 504 Gateway Timeout", error="Timeout")

            def observe(self, inputs, exec_result):
                # Inspecting the remote resource reveals the submission was indeed saved!
                return Observation(target="remote", state_data={"transaction_recorded": True})

            def verify(self, inputs, observation, exec_result):
                if observation.state_data.get("transaction_recorded"):
                    return VerificationResult(verified=True, evidence="Transaction confirmed and succeeded in backend ledger")
                return VerificationResult(verified=False, evidence="Transaction not found")

            def recover(self, inputs, error, attempt):
                # Check if it was recorded
                return {"can_retry": False, "strategy": "resolve_as_success", "message": "Observed state confirms transaction succeeded."}

        registry = ToolRegistry()
        tool = FlakyNetworkTool(name="flaky_tool", description="flaky", risk_level=RiskLevel.HIGH)
        registry.register_instance("flaky_tool", tool)
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Submit payment record", tool="flaky_tool", inputs={})
        task = Task(id="t_rec", command="submit", plan=Plan(id="p_rec", task_id="t_rec", goal="submit", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertIn("succeeded", result.summary.lower())

    def test_requirement_t_retry_limit(self):
        """T. Retry limit: stops after configured retry limit without infinite loops."""
        attempts = []

        class RetryTool(BaseTool):
            def execute(self, inputs, context=None):
                attempts.append(len(attempts) + 1)
                return ExecutionResult(step_id="s1", ok=False, message="Transient 503")
            def observe(self, inputs, exec_res):
                return Observation(target="service", state_data={})
            def verify(self, inputs, obs, exec_res):
                return VerificationResult(verified=False, evidence="503 Service Unavailable")
            def recover(self, inputs, err, attempt):
                return {"can_retry": attempt < 2, "strategy": "retry" if attempt < 2 else "abort", "message": "Exceeded retry limit"}

        registry = ToolRegistry()
        registry.register_instance("retry_tool", RetryTool(name="retry_tool", description="test", risk_level=RiskLevel.LOW))
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Poll service", tool="retry_tool", inputs={}, retry_policy={"max_retries": 2, "backoff_seconds": 0.01})
        task = Task(id="t_retry", command="poll", plan=Plan(id="p_retry", task_id="t_retry", goal="poll", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertLessEqual(len(attempts), 3)

    def test_requirement_u_timeout(self):
        """U. Timeout: times out safely without repeating irreversible actions."""
        policy = PolicyEngine()
        is_irrev = policy.is_irreversible("send_email")
        self.assertTrue(is_irrev)

        # Irreversible actions should not be marked retryable blindly
        err = ExecutionError(code="Timeout", message="Socket timeout", recoverable=not is_irrev)
        self.assertFalse(err.recoverable)

    def test_requirement_v_cancellation(self):
        """V. Cancellation: cancelling task stops execution and preserves state."""
        resp = self.orchestrator.chat("Send an email to test@domain.com saying hello")
        task_id = resp["task"]["id"]

        cancelled = self.orchestrator.cancel_task(task_id, reason="User changed mind")
        self.assertEqual(cancelled["status"], "canceled")
        self.assertEqual(len(_sent_records), 0)

    def test_requirement_w_duplicate_protection(self):
        """W. Duplicate protection: idempotency key prevents duplicate execution."""
        policy = PolicyEngine()
        key1 = policy.get_idempotency_key("send_email", {"recipient": "a@b.com", "subject": "Test"})
        key2 = policy.get_idempotency_key("send_email", {"recipient": "a@b.com", "subject": "Test"})
        self.assertEqual(key1, key2)

        policy.mark_execution_started(key1)
        check = policy.check_duplicate_or_uncertain(key1)
        self.assertFalse(check["can_proceed"])
        self.assertEqual(check["status"], "in_flight")

        policy.mark_execution_completed(key1, "completed")
        check_after = policy.check_duplicate_or_uncertain(key1)
        self.assertFalse(check_after["can_proceed"])
        self.assertEqual(check_after["status"], "already_completed")

    def test_requirement_x_external_service_unavailable(self):
        """X. External service unavailable: captured and reported clearly."""
        class OfflineServiceTool(BaseTool):
            def execute(self, inputs, context=None):
                return ExecutionResult(step_id="s1", ok=False, message="Mail server connection refused (offline)", error="ConnectionRefused")
            def observe(self, inputs, exec_result):
                return Observation(target="network", state_data={"reachable": False})
            def verify(self, inputs, observation, exec_result):
                return VerificationResult(verified=False, evidence="Service offline")
            def recover(self, inputs, error, attempt):
                return {"can_retry": False, "strategy": "abort", "message": "Email server offline"}

        registry = ToolRegistry()
        registry.register_instance("offline_tool", OfflineServiceTool(name="offline_tool", description="test", risk_level=RiskLevel.HIGH))
        exec_engine = ExecutionEngine(registry, PolicyEngine())

        step = PlanStep(id="s1", action="Connect", tool="offline_tool", inputs={})
        task = Task(id="t_off", command="connect", plan=Plan(id="p_off", task_id="t_off", goal="connect", steps=[step]))

        result = exec_engine.execute_plan(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("offline", result.summary.lower())

    def test_requirement_y_unexpected_ui_state(self):
        """Y. Unexpected UI state handled safely."""
        tool = self.orchestrator.tools.get_instance("desktop_tool")
        # In dry run, closing non-existent app or focusing missing window returns safe outcome
        res = tool.execute({"command": "focus_app", "appName": "NonExistentApp12345"})
        self.assertTrue(res.ok)  # Mock returns gracefully

    def test_requirement_z_email_send_verification(self):
        """Z. Email send verification: independently checks Sent mailbox records."""
        mail_tool = MailTool(automation=self.automation)
        # Execute send
        exec_res = mail_tool.execute({
            "command": "send_mail",
            "recipient": "verified_user@domain.com",
            "subject": "Delivery Check",
            "body": "Checking delivery verification",
        })
        self.assertTrue(exec_res.ok)

        # Observe
        obs = mail_tool.observe({"recipient": "verified_user@domain.com", "subject": "Delivery Check"}, exec_res)
        self.assertTrue(obs.state_data.get("in_sent_mailbox"))

        # Verify
        ver = mail_tool.verify({"recipient": "verified_user@domain.com", "subject": "Delivery Check"}, obs, exec_res)
        self.assertTrue(ver.verified)
        self.assertIn("verified in Sent mailbox", ver.evidence)

    # =========================================================================
    # PART 2: GOLDEN EMAIL TEST MATRIX
    # =========================================================================

    def test_golden_matrix_professor(self):
        """Professor: respectful, academic, concise request."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "prof.hansen@university.edu",
            "Email my professor asking for one more day to submit the assignment",
            recipient_name="Professor Hansen",
            relationship_type="professor",
        )
        self.assertEqual(draft.relationship_inferred, "professor")
        self.assertIn("Professor Hansen", draft.body)
        self.assertIn("extension", draft.body.lower())
        self.assertNotIn("cheers", draft.body.lower())
        self.assertNotIn("hey prof", draft.body.lower())

    def test_golden_matrix_manager(self):
        """Manager: concise, professional, direct, informative."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "sarah.manager@techcorp.io",
            "Mail my manager that I will be late because of traffic",
            recipient_name="Sarah",
            relationship_type="manager",
        )
        self.assertEqual(draft.relationship_inferred, "manager")
        self.assertIn("traffic", draft.body.lower())
        self.assertTrue("traffic" in draft.subject.lower() or "late" in draft.subject.lower())
        self.assertTrue(len(draft.body.split()) < 100)  # Concise

    def test_golden_matrix_recruiter(self):
        """Recruiter: polished, courteous, professional, clear inquiry."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "recruiter@innovate.ai",
            "Email the recruiter and ask whether my interview is confirmed",
            recipient_name="Jessica",
            relationship_type="recruiter",
        )
        self.assertEqual(draft.relationship_inferred, "recruiter")
        self.assertIn("interview", draft.body.lower())
        self.assertIn("confirmed", draft.body.lower())

    def test_golden_matrix_client(self):
        """Client: professional, confident, precise, outcome-focused."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "david@clientpartners.com",
            "Tell the client we have completed the requested changes",
            recipient_name="David",
            relationship_type="client",
        )
        self.assertEqual(draft.relationship_inferred, "client")
        self.assertIn("completed", draft.body.lower())
        self.assertIn("changes", draft.body.lower())

    def test_golden_matrix_colleague(self):
        """Colleague: professional but natural, collaborative."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "arjun@corp.internal",
            "Tell Arjun I finished the report and he can review it",
            recipient_name="Arjun",
            relationship_type="colleague",
        )
        self.assertEqual(draft.relationship_inferred, "colleague")
        self.assertIn("report", draft.body.lower())
        self.assertIn("review", draft.body.lower())

    def test_golden_matrix_unknown_recipient(self):
        """Unknown recipient: neutral, polite, professional, no invented relationship."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "inquiries@conference2026.org",
            "Send an email to this person asking for the meeting details",
        )
        self.assertEqual(draft.relationship_inferred, "unknown")
        self.assertNotIn("Professor", draft.body)
        self.assertNotIn("Manager", draft.body)
        self.assertIn("meeting", draft.body.lower())

    def test_golden_matrix_formal_request(self):
        """Formal request explicitly requested by user."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "board@enterprise.org",
            "Send formal notification of audit completion",
            user_tone_override="formal",
        )
        self.assertEqual(draft.tone, "formal")
        self.assertIn("Sincerely", draft.body)

    def test_golden_matrix_neutral_request(self):
        """Neutral request without strong bias."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "helpdesk@cloud.com",
            "Inquire about account access provisioning",
        )
        self.assertIn("account", draft.body.lower())

    def test_golden_matrix_friendly_professional_request(self):
        """Friendly professional request."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "priya@partner.org",
            "Congratulate Priya on the product release",
            recipient_name="Priya",
            relationship_type="colleague",
            user_tone_override="warm_professional",
        )
        self.assertIn("congratulations", draft.body.lower())

    def test_golden_matrix_very_concise_request(self):
        """Very concise request."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "ops@infra.net",
            "Notify ops team server deployment completed successfully",
            user_tone_override="very concise",
        )
        word_count = len(draft.body.split())
        self.assertLessEqual(word_count, 65)

    def test_golden_matrix_follow_up_email(self):
        """Follow-up email context."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "vendor@logistics.com",
            "Following up on the shipment tracking number from yesterday",
            recipient_name="Vendor Support",
        )
        self.assertTrue("following up" in draft.body.lower() or "follow-up" in draft.subject.lower())

    def test_golden_matrix_reply_to_thread(self):
        """Reply to thread maintains context and Re: prefix."""
        engine = ProfessionalEmailEngine()
        thread_ctx = {
            "subject": "Q3 Budget Review",
            "last_message": "Can you provide the final expense figures by 4 PM?",
        }
        draft = engine.generate_email_draft(
            "finance@corp.com",
            "The final expense figures are attached and within budget",
            thread_context=thread_ctx,
        )
        self.assertTrue(draft.subject.startswith("Re: Q3 Budget Review"))
        self.assertIn("expense", draft.body.lower())

    def test_golden_matrix_edited_draft(self):
        """Edited draft updates body and preserves recipient."""
        engine = ProfessionalEmailEngine()
        draft = engine.generate_email_draft(
            "lead@team.internal",
            "Draft update on sprint velocity",
        )
        edited = engine.update_draft_with_edit(draft, "make it more concise")
        self.assertEqual(edited.recipient, draft.recipient)
        self.assertTrue(edited.quality_report.approved)

    def test_golden_matrix_cancelled_draft(self):
        """Cancelled draft workflow via orchestrator."""
        resp = self.orchestrator.chat("Send an email to mark@domain.com saying we cancel the order")
        task_id = resp["task"]["id"]
        self.assertEqual(resp["task"]["status"], "waiting_approval")

        cancel_resp = self.orchestrator.cancel_task(task_id, reason="Customer called to keep order")
        self.assertEqual(cancel_resp["status"], "canceled")
        self.assertEqual(len(_sent_records), 0)

    def test_golden_matrix_failed_send(self):
        """Failed send: MailTool failure reports failure and does not claim success."""
        with patch.object(self.automation.mail, "send_mail", side_effect=RuntimeError("SMTP connection timed out")):
            mail_tool = MailTool(automation=self.automation)
            res = mail_tool.execute({
                "command": "send_mail",
                "recipient": "fail@test.com",
                "subject": "Fail Test",
                "body": "Body",
            })
            self.assertFalse(res.ok)
            self.assertIn("timed out", res.message)

    def test_golden_matrix_uncertain_send_result_recovery(self):
        """Uncertain send result triggers check_sent_messages rather than blindly repeating."""
        mail_tool = MailTool(automation=self.automation)
        # Simulate record existing in sent
        _sent_records.append({
            "recipient": "uncertain@test.com",
            "subject": "Uncertain Test",
            "body": "Body",
            "timestamp": time.time(),
        })

        # Recovery checks sent status
        rec = mail_tool.recover(
            {"recipient": "uncertain@test.com", "subject": "Uncertain Test"},
            ExecutionError(code="Timeout", message="Request timed out"),
            attempt=1,
        )
        self.assertEqual(rec["strategy"], "resolve_as_success")
        self.assertIn("verified in Sent messages", rec["message"])

    def test_golden_matrix_duplicate_send_protection(self):
        """Duplicate send protection prevents double-sending identical email."""
        resp = self.orchestrator.chat("Send an email to duplicate@test.com saying hello world")
        task_id = resp["task"]["id"]

        # Approve once
        app1 = self.orchestrator.approve(task_id, True)
        self.assertEqual(app1["status"], "completed")
        self.assertEqual(len(_sent_records), 1)

        # Attempt to execute again with same key
        policy = self.orchestrator.policy
        key = policy.get_idempotency_key("send_mail", {
            "action": "send_mail",
            "recipient": "duplicate@test.com",
            "subject": resp["task"]["params"]["subject"],
            "body": resp["task"]["params"].get("body", ""),
        })
        check = policy.check_duplicate_or_uncertain(key)
        self.assertFalse(check["can_proceed"])
        self.assertEqual(check["status"], "already_completed")


if __name__ == "__main__":
    unittest.main()
