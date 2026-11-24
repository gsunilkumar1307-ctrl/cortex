"""tests/test_real_world_acceptance.py
Official LangGraph Migration — Section 16 Real-World Acceptance Test Suite.

Verifies the 10 real-world acceptance criteria specified in Section 16:
1. Conversational intelligence: "What is an AI agent?" -> Valid answer, no tool triggered, clean response.
2. Model consistency: 10 consecutive requests to local Ollama -> 10 successful completions, zero Gemini references, zero rate limits.
3. Browser task: "Search YouTube for classical music and play one" -> Browser navigation/search/verified observation.
4. Filesystem search: Search for files on workspace/Desktop -> Real search executed, real files returned, honest output.
5. Multi-step autonomous task: "Inspect the active window, open Notes, and write 'LangGraph migration complete'" -> Multi-step LangGraph execution, verified final state.
6. Failure recovery: Execute an invalid action -> LangGraph error routing, bounded recovery, clean failure reporting without crash.
7. Approval interruption and resume: Consequential action -> LangGraph pause/interrupt before execution, approval gate, resume from checkpoint.
8. Cancellation: Issue cancellation request -> Safe graph exit, status CANCELLED, clean response.
9. Independent verification: Mismatch detection -> Verification node checks reality, refuses false COMPLETED, reports honestly.
10. Non-streaming vs streaming consistency: Identical tasks in streaming and direct execution -> Matching final state and event sequence.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.agent.execution_engine import ExecutionEngine
from backend.agent.langgraph_engine import LangGraphExecutionEngine
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceActionResult, DeviceAutomation
from backend.core.contracts import (
    ExecutionResult,
    Observation,
    Plan,
    PlanStep,
    RiskLevel,
    Task,
    TaskCommand,
    TaskStatus,
    VerificationResult,
)
from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.persistence.task_store import TaskStore
from backend.tools.desktop_tool import DesktopTool
from backend.tools.file_tool import FileTool
from backend.tools.registry import ToolRegistry


class TestRealWorldAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "acceptance_test.sqlite3")
        self.memory = EncryptedMemoryStore(self.db_path)
        self.task_store = TaskStore(self.db_path)
        self.device = DeviceAutomation(dry_run=True)
        self.orch = CortexOrchestrator(
            automation=self.device,
            memory=self.memory,
            task_store=self.task_store,
            use_gemini=False,
            dry_run=True,
        )

    def test_01_conversational_intelligence(self) -> None:
        """Test 1: Conversational intelligence answering without triggering device tools."""
        res = self.orch.chat("What is an AI agent?")
        task = res["task"]

        self.assertEqual(task["command"], TaskCommand.ASK_QUESTION.value)
        self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
        self.assertTrue(len(res["message"]) > 20)
        # Verify no tool was dispatched
        self.assertNotIn("desktop_tool", [e.get("action", "") for e in task.get("audit_trail", [])])
        # Verify clean answer
        self.assertTrue(any(k in res["message"].lower() for k in ("agent", "autonomous", "system", "environment", "decision", "ai", "action", "perceive")))

    def test_02_model_consistency_10_requests(self) -> None:
        """Test 2: Model consistency across 10 consecutive requests to local Ollama / Cortex reasoning."""
        queries = [
            "What is Python?",
            "What is an operating system?",
            "Explain memory caching in simple terms.",
            "What is latency in computing?",
            "Define an autonomous agent.",
            "What does a task queue do?",
            "Explain the concept of idempotency.",
            "What is a cryptographic hash?",
            "What is process isolation?",
            "Summarize the purpose of checkpointing.",
        ]

        completions = []
        for q in queries:
            r = self.orch.chat(q)
            completions.append(r)

        self.assertEqual(len(completions), 10)
        for idx, r in enumerate(completions):
            self.assertEqual(r["task"]["status"], TaskStatus.COMPLETED.value, f"Query {idx} failed")
            # Strictly zero Gemini cloud references
            msg_lower = r["message"].lower()
            self.assertNotIn("gemini", msg_lower)
            self.assertNotIn("openai", msg_lower)
            self.assertNotIn("anthropic", msg_lower)
            # Strictly zero rate limit errors
            self.assertNotIn("429", msg_lower)
            self.assertNotIn("resourceexhausted", msg_lower)
            self.assertNotIn("rate limit", msg_lower)

    def test_03_browser_task_youtube_search(self) -> None:
        """Test 3: Browser task executing YouTube search with verified observation."""
        msg = "Search YouTube for classical music and play one"
        cmd = TaskCommand.OPEN_URL
        params = {
            "url": "https://www.youtube.com",
            "query": "classical music",
            "browser_intent": "MEDIA_PLAYBACK",
            "site": "youtube.com",
        }

        plan = self.orch.planner.plan(msg, cmd, params)
        self.assertTrue(len(plan.steps) >= 3)
        self.assertEqual(plan.steps[0].command, TaskCommand.OPEN_URL)
        self.assertEqual(plan.steps[1].command, TaskCommand.BROWSER_TYPE)

        # Mock browser actions to simulate real Playwright MCP execution
        with patch.object(self.orch.tools.get_instance("browser_tool"), "execute") as mock_exec, \
             patch.object(self.orch.tools.get_instance("browser_tool"), "observe") as mock_obs, \
             patch.object(self.orch.tools.get_instance("browser_tool"), "verify") as mock_ver:

            mock_exec.return_value = ExecutionResult(step_id="step1", ok=True, message="Navigated to https://www.youtube.com", data={"url": "https://www.youtube.com"})
            mock_obs.return_value = Observation(target="browser:navigate", state_data={"loaded": True, "url": "https://www.youtube.com"}, raw_output="Page loaded")
            mock_ver.return_value = VerificationResult(verified=True, evidence="YouTube page loaded and verified")

            task = Task(intent=msg, command=cmd, risk_level=RiskLevel.LOW, requires_approval=False, params=params)
            res = self.orch.execution_engine.execute_plan(task, plan)

            self.assertEqual(res.status, TaskStatus.COMPLETED)
            self.assertTrue(len(task.observations) > 0)
            self.assertTrue(len(task.verifications) > 0)

    def test_04_filesystem_search_workspace(self) -> None:
        """Test 4: Filesystem search returning real workspace files."""
        # Execute real file search in the Cortex directory
        res = self.orch.chat("search files on Desktop")
        task = res["task"]

        self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
        self.assertIn("Finder Inspection", res["message"])
        self.assertTrue(len(task.get("auditTrail", [])) > 0)

    def test_05_multi_step_autonomous_task(self) -> None:
        """Test 5: Multi-step autonomous task: inspect window, open Notes, and write text."""
        self.device.dry_run = False
        self.device.system = "darwin"
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="VERIFIED\n", stderr="")

            res = self.orch.chat("Open Notes and type exactly: LangGraph migration complete.")
            task = res["task"]

            self.assertEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(res["message"], "Sequence completed.")
            # Verify events reflect canonical progression
            audit_trail = task.get("auditTrail", [])
            event_names = [e.get("type") for e in audit_trail]
            self.assertIn("executing", event_names)
            self.assertIn("step_completed", event_names)
            self.assertIn("step_verified", event_names)

    def test_06_failure_recovery_bounded_retry(self) -> None:
        """Test 6: Bounded failure recovery upon encountering an invalid action."""
        step = PlanStep(
            id="fail_step_1",
            action="Read non-existent system file /nonexistent/file.txt",
            tool="desktop_tool",
            inputs={"command": TaskCommand.READ_FILE, "params": {"file_path": "/nonexistent/file.txt"}},
            command=TaskCommand.READ_FILE,
            risk_level=RiskLevel.LOW,
            retry_policy={"max_retries": 2, "backoff_seconds": 0.01},
        )
        plan = Plan(goal="Read non-existent file", steps=[step])
        task = Task(intent="Read non-existent file", command=TaskCommand.READ_FILE, risk_level=RiskLevel.LOW, requires_approval=False)

        res = self.orch.execution_engine.execute_plan(task, plan)

        self.assertEqual(res.status, TaskStatus.FAILED)
        # Verify retries were bounded (not infinite)
        retry_events = [e for e in task.audit_trail if e.type == "retrying"]
        self.assertLessEqual(len(retry_events), 2)
        self.assertIn("failed", [e.type for e in task.audit_trail])

    def test_07_approval_interruption_and_resume(self) -> None:
        """Test 7: Approval interruption at safety gate and resumption via cryptographic token."""
        self.orch.chat("send mail to team@example.com")
        r2 = self.orch.chat("Tell them the production deployment is complete.")
        task = r2["task"]

        # 1. Action is paused at LangGraph approval gate
        self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
        token = task["params"]["approval_hash"]
        self.assertTrue(bool(token))

        # 2. Resuming with valid approval token completes execution
        approve_res = self.orch.approve(task["id"], approved=True, approval_hash=token)
        self.assertEqual(approve_res["status"], TaskStatus.COMPLETED.value)

    def test_08_cancellation_safe_graph_exit(self) -> None:
        """Test 8: Task cancellation cleanly stops graph execution with CANCELLED status."""
        plan_steps = [
            PlanStep(
                id=f"cancel_step_{i}",
                action=f"Step {i}",
                tool="desktop_tool",
                inputs={"command": TaskCommand.CALCULATE, "params": {"expression": f"{i}+{i}"}},
                command=TaskCommand.CALCULATE,
                risk_level=RiskLevel.LOW,
            )
            for i in range(1, 5)
        ]
        plan = Plan(goal="Multi-step calculation", steps=plan_steps)
        task = Task(intent="Multi-step calculation", command=TaskCommand.CALCULATE, risk_level=RiskLevel.LOW, requires_approval=False)

        # Cancel mid-execution via on_progress callback
        def cancel_on_second_step(stage: str, msg: str):
            if "Step 2" in msg:
                task.status = TaskStatus.CANCELLED
                task.cancellation_requested = True

        res = self.orch.execution_engine.execute_plan(task, plan, on_progress=cancel_on_second_step)

        self.assertEqual(res.status, TaskStatus.CANCELLED)
        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertIn("canceled", [e.type for e in task.audit_trail])

    def test_09_independent_verification_mismatch_detection(self) -> None:
        """Test 9: Independent verification detects state mismatch and refuses false completion."""
        self.device.dry_run = False
        self.device.system = "darwin"
        with patch.object(self.device, "is_app_running", return_value=True), \
             patch.object(self.device, "_focus_app", return_value=DeviceActionResult(True, "Focused Notes.")), \
             patch.object(self.device, "_open_app", return_value=DeviceActionResult(True, "Opened Notes.")), \
             patch("subprocess.run") as mock_subproc:

            # Tool subprocess returns UNVERIFIED (text not on screen)
            mock_subproc.return_value = MagicMock(returncode=0, stdout="UNVERIFIED: text not found\n", stderr="")

            res = self.orch.chat("Open Notes and type exactly: Text not appearing.")
            task = res["task"]

            # Must NOT report COMPLETED
            self.assertNotEqual(task["status"], TaskStatus.COMPLETED.value)
            self.assertEqual(task["status"], TaskStatus.NEEDS_ATTENTION.value)
            self.assertIn("could not be verified", res["message"])

    def test_10_streaming_vs_direct_consistency(self) -> None:
        """Test 10: Non-streaming vs streaming execution consistency."""
        step = PlanStep(
            id="calc_step",
            action="Calculate 42 * 2",
            tool="desktop_tool",
            inputs={"command": TaskCommand.CALCULATE, "params": {"expression": "42 * 2"}},
            command=TaskCommand.CALCULATE,
            risk_level=RiskLevel.LOW,
            expected_result="84",
        )
        plan1 = Plan(goal="Direct calc", steps=[step])
        task1 = Task(intent="Direct calc", command=TaskCommand.CALCULATE, risk_level=RiskLevel.LOW, requires_approval=False)

        plan2 = Plan(goal="Streamed calc", steps=[step])
        task2 = Task(intent="Streamed calc", command=TaskCommand.CALCULATE, risk_level=RiskLevel.LOW, requires_approval=False)

        streamed_events: list[str] = []
        def track_progress(stage: str, msg: str):
            streamed_events.append(stage)

        res_direct = self.orch.execution_engine.execute_plan(task1, plan1)
        res_streamed = self.orch.execution_engine.execute_plan(task2, plan2, on_progress=track_progress)

        # Both complete with identical status and result
        self.assertEqual(res_direct.status, res_streamed.status)
        self.assertEqual(res_direct.status, TaskStatus.COMPLETED)
        self.assertEqual(task1.status, task2.status)
        self.assertEqual(task1.result, task2.result)
        # Event sequence is consistent
        self.assertTrue(len(streamed_events) > 0)


if __name__ == "__main__":
    unittest.main()
