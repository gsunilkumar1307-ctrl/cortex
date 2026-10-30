import tempfile
import unittest
from pathlib import Path

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.core.contracts import Task, TaskCommand, TaskStatus, RiskLevel
from backend.persistence import EncryptedMemoryStore


class TestRapidConversationalIntelligence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=True), self.memory, use_gemini=False)

    def test_01_explain_big_bang_theory(self):
        """Scenario 1: 'Explain the Big Bang theory.' -> Relevant knowledge answer."""
        res = self.orch.chat("Explain the Big Bang theory.")
        self.assertEqual(res["task"]["status"], "completed")
        self.assertTrue(
            "cosmological model" in res["message"].lower() or "universe" in res["message"].lower(),
            f"Expected cosmology knowledge, got: {res['message']}",
        )
        self.assertNotIn("cbs", res["message"].lower())

    def test_02_explain_quantum_computing(self):
        """Scenario 2: 'Explain quantum computing.' -> Relevant technical answer."""
        res = self.orch.chat("Explain quantum computing.")
        self.assertEqual(res["task"]["status"], "completed")
        self.assertTrue(
            "quantum" in res["message"].lower() and ("qubits" in res["message"].lower() or "superposition" in res["message"].lower() or "comput" in res["message"].lower()),
            f"Expected technical explanation, got: {res['message']}",
        )

    def test_03_bruce_lee(self):
        """Scenario 3: 'Bruce Lee.' -> Relevant biographical information, not unrelated content."""
        res = self.orch.chat("Bruce Lee.")
        self.assertEqual(res["task"]["status"], "completed")
        self.assertTrue(
            "martial artist" in res["message"].lower() or "jeet kune do" in res["message"].lower() or "bruce lee" in res["message"].lower(),
            f"Expected Bruce Lee info, got: {res['message']}",
        )

    def test_04_what_can_cortex_do(self):
        """Scenario 4: 'What can Cortex do?' -> Actual capability status."""
        res = self.orch.chat("What can Cortex do?")
        self.assertEqual(res["task"]["status"], "completed")
        self.assertIn("SUPPORTED_AND_READY", res["message"])
        self.assertIn("PARTIALLY_IMPLEMENTED", res["message"])
        self.assertIn("Conversational Intelligence", res["message"])
        self.assertIn("Apple Mail Automation", res["message"])

    def test_05_06_07_email_workflow_shorten_cancel(self):
        """Scenarios 5, 6, 7:
        5: 'Draft an email to Rahul explaining I cannot attend tomorrow's meeting. Do not send it.'
        6: 'Make it shorter.' -> Correctly modifies the previous draft.
        7: 'Cancel that email.' -> Cancels the pending operation.
        """
        # Step 5: Draft email
        r1 = self.orch.chat("Draft an email to Rahul explaining I cannot attend tomorrow's meeting. Do not send it.")
        self.assertEqual(r1["task"]["status"], "completed")
        self.assertEqual(r1["task"]["params"]["recipient"], "Rahul")
        self.assertIn("Unable to Attend Tomorrow's Meeting", r1["task"]["params"]["subject"])
        self.assertIn("Draft created", r1["message"])

        # Step 6: Make it shorter
        r2 = self.orch.chat("Make it shorter.")
        self.assertEqual(r2["task"]["status"], "waiting_approval")
        self.assertIn("cannot attend tomorrow's meeting", r2["message"].lower())
        self.assertIn("rahul", r2["message"].lower())

        # Step 7: Cancel that email
        r3 = self.orch.chat("Cancel that email.")
        self.assertEqual(r3["task"]["status"], "canceled")
        self.assertIn("cancel", r3["message"].lower())

    def test_08_kannada_question(self):
        """Scenario 8: Kannada question -> Kannada response."""
        res = self.orch.chat("ಕರ್ನಾಟಕದ ರಾಜಧಾನಿ ಯಾವುದು?")
        self.assertIn("ಬೆಂಗಳೂರು", res["message"])

    def test_09_hindi_question(self):
        """Scenario 9: Hindi question -> Hindi response."""
        res = self.orch.chat("भारत की राजधानी क्या है?")
        self.assertIn("नई दिल्ली", res["message"])

    def test_10_kannada_english_mixed(self):
        """Scenario 10: Kannada-English mixed message -> Correct language understanding."""
        res = self.orch.chat("Karnataka capital yāvudu?")
        self.assertTrue("Bengaluru" in res["message"] or "ಬೆಂಗಳೂರು" in res["message"])

    def test_11_explain_in_simpler_words_follow_up(self):
        """Scenario 11: 'Explain that in simpler words.' -> Correct follow-up context."""
        self.orch.chat("Explain quantum computing.")
        res = self.orch.chat("Explain that in simpler words.")
        self.assertEqual(res["task"]["status"], "completed")
        self.assertTrue(
            "light switch" in res["message"].lower() or "qubits" in res["message"].lower(),
            f"Expected ELI5 simpler explanation, got: {res['message']}",
        )

    def test_12_task_interruption_and_switch(self):
        """Scenario 12: 'Stop. Help me with Python instead.' -> Pause previous task and switch."""
        self.orch.chat("Draft an email to Rahul saying hello")
        self.assertIsNotNone(self.orch.pending_action)

        res = self.orch.chat("Stop. Help me with Python instead.")
        self.assertIn("Paused the previous task", res["message"])
        self.assertIn("Python", res["message"])
        self.assertEqual(len(self.orch.paused_tasks), 1)

        # Verify resumption
        r_resume = self.orch.chat("Resume the previous task")
        self.assertIn("Resumed your previous task", r_resume["message"])
        self.assertIsNotNone(self.orch.pending_action)

    def test_13_ai_provider_unavailable(self):
        """Scenario 13: AI provider unavailable -> Honest failure, no invented answer."""
        t_model = Task(intent="Generate model text", command=TaskCommand.UNKNOWN, risk_level=RiskLevel.LOW, requires_approval=False, params={"requires_model": True})
        self.orch._execute(t_model)
        self.assertEqual(t_model.status, TaskStatus.PAUSED_MODEL_UNAVAILABLE)
        self.assertIn("Cloud model provider unavailable", t_model.error)

    def test_14_integration_unavailable(self):
        """Scenario 14: Integration unavailable -> Honest capability explanation."""
        res = self.orch.chat("Tell me in Spanish")
        self.assertIn("not currently configured", res["message"])

    def test_15_consequential_action_approval(self):
        """Scenario 15: Consequential action -> Approval required."""
        res = self.orch.chat("send email to test@domain.com saying Hello")
        self.assertEqual(res["task"]["status"], "waiting_approval")
        self.assertTrue(res["task"]["requiresApproval"])

    def test_16_failed_execution_no_false_success(self):
        """Scenario 16: Failed execution -> No false success message."""
        t_fail = Task(intent="Bad command", command=TaskCommand.OPEN_APP, risk_level=RiskLevel.LOW, requires_approval=False, params={"appName": "NonExistentApp123456"})
        self.orch.automation.dry_run = False
        self.orch._execute(t_fail)
        self.assertEqual(t_fail.status, TaskStatus.FAILED)
        self.assertNotEqual(t_fail.result, "Done.")


if __name__ == "__main__":
    unittest.main()

