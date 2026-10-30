"""
Regression and verification tests for the critical bug:
'CORTEX TYPES USER INSTRUCTIONS INSTEAD OF COMPOSING EMAILS'

Validates:
1. Scenario 1: Informational email drafting without raw meta-instructions.
2. Scenario 2: Polite extension request without invented reasons and without raw instruction leaks.
3. Scenario 3: Explicit generic desktop typing request executes TYPE_TEXT.
4. Scenario 4: Multi-turn drafting and structured editing without keystroke typing.
5. Scenario 5: Draft modification invalidates previous approval hash.
6. Single-turn direct email command creates draft without typing.
7. Diagnostic logging records capability selection and redacts sensitive metadata.
"""

import unittest
from unittest.mock import patch, MagicMock

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, TaskStatus, command_from_intent


class TestInstructionTypingBugRegression(unittest.TestCase):
    def setUp(self):
        self.orchestrator = CortexOrchestrator(use_gemini=False)
        # Mock automation mail actions so live Apple Mail is not invoked during test
        self.orchestrator.automation._get_mail = MagicMock()
        self.mock_mail = MagicMock()
        self.mock_mail.draft_mail.return_value = {
            "ok": True,
            "message": "Draft created in Apple Mail.",
            "data": {"draft_id": "mock_draft_123"},
        }
        self.mock_mail.create_email_draft.return_value = {
            "ok": True,
            "message": "Draft created in Apple Mail.",
            "data": {"draft_id": "mock_draft_123"},
        }
        self.mock_mail.send_mail.return_value = {
            "ok": True,
            "message": "Email sent successfully.",
            "data": {"message_id": "mock_msg_456"},
        }
        self.orchestrator.automation._mail = self.mock_mail

    def test_scenario_1_informational_email(self):
        """Scenario 1:
        User: 'send mail to gsunilkumar1307@gmail.com'
        User: 'Inform them that the project presentation deadline is on 5 November.'
        Expected:
        - Subject: 'Project Presentation Deadline'
        - Body: 'Hello,\n\nThe project presentation deadline is November 5.\n\nBest regards'
        - Not 'Typed text.' and not generic text typing.
        """
        with patch.object(self.orchestrator.automation, "_type_text") as mock_type:
            # Turn 1
            t1 = self.orchestrator.chat("send mail to gsunilkumar1307@gmail.com")
            self.assertIn("gsunilkumar1307@gmail.com", t1["message"])
            self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_body")

            # Turn 2
            t2 = self.orchestrator.chat("Inform them that the project presentation deadline is on 5 November.")
            task = t2["task"]

            # Must NOT call desktop typing
            mock_type.assert_not_called()

            # Must NOT respond with "Typed text."
            self.assertNotIn("Typed text.", t2["message"])

            # Must have structured email drafting command
            self.assertEqual(task["command"], TaskCommand.SEND_MAIL.value)
            self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)

            # Check subject and body
            self.assertEqual(task["params"]["subject"], "Project Presentation Deadline")
            formatted_body = task["params"]["formatted_body"]
            self.assertIn("The project presentation deadline is November 5.", formatted_body)
            self.assertIn("Hello,", formatted_body)
            self.assertIn("Best regards", formatted_body)

            # Raw instruction wrapper must NOT appear in body
            self.assertNotIn("Inform them that", formatted_body)

    def test_scenario_2_polite_extension_request(self):
        """Scenario 2:
        User: 'send mail to gsunilkumar1307@gmail.com'
        User: 'Write a polite email asking whether the project presentation deadline can be extended by two days. Do not invent a reason.'
        Expected:
        - Subject: 'Project Presentation Deadline Extension Request'
        - Body contains: 'Could the project presentation deadline please be extended by two days?'
        - Zero invented excuses (e.g. no fabricated illness, busy week, or reasons)
        - Raw instruction 'Write a polite email asking whether...' does NOT appear verbatim
        - Capability used is draft_mail, not type_text
        - Response is an approval request card, not 'Typed text.'
        """
        with patch.object(self.orchestrator.automation, "_type_text") as mock_type:
            # Turn 1
            t1 = self.orchestrator.chat("send mail to gsunilkumar1307@gmail.com")
            self.assertEqual(self.orchestrator.pending_action.get("step"), "waiting_for_body")

            # Turn 2
            t2 = self.orchestrator.chat("Write a polite email asking whether the project presentation deadline can be extended by two days. Do not invent a reason.")
            task = t2["task"]

            # Must NOT call desktop keystroke typing
            mock_type.assert_not_called()

            # Must NOT respond with "Typed text."
            self.assertNotIn("Typed text.", t2["message"])
            self.assertIn("Draft created", t2["message"])
            self.assertIn("Should I send it?", t2["message"])

            # Must be waiting for approval
            self.assertEqual(task["status"], TaskStatus.WAITING_APPROVAL.value)
            self.assertEqual(task["command"], TaskCommand.SEND_MAIL.value)

            # Subject check
            self.assertEqual(task["params"]["subject"], "Project Presentation Deadline Extension Request")

            # Body composition checks
            formatted_body = task["params"]["formatted_body"]
            self.assertIn("Could the project presentation deadline please be extended by two days?", formatted_body)
            self.assertIn("Hello,", formatted_body)
            self.assertIn("Best regards", formatted_body)

            # Must NOT contain raw instructions or meta-constraints
            self.assertNotIn("Write a polite email", formatted_body)
            self.assertNotIn("Do not invent a reason", formatted_body)
            self.assertNotIn("asking whether", formatted_body)

            # Must NOT invent excuses
            self.assertNotIn("traffic", formatted_body.lower())
            self.assertNotIn("illness", formatted_body.lower())
            self.assertNotIn("committed to submitting high-quality work", formatted_body.lower())

    def test_scenario_3_generic_text_typing(self):
        """Scenario 3:
        User: 'Type exactly this text into the current document: Hello, team.'
        Expected:
        - Routes to TaskCommand.TYPE_TEXT
        - Generic desktop typing capability is executed
        - Is NOT converted into an email draft
        """
        cmd = command_from_intent("Type exactly this text into the current document: Hello, team.")
        self.assertEqual(cmd, TaskCommand.TYPE_TEXT)

        with patch.object(self.orchestrator.automation, "_type_text") as mock_type:
            mock_type.return_value = MagicMock(ok=True, message="Typed text.")
            t = self.orchestrator.chat("Type exactly this text into the current document: Hello, team.")
            mock_type.assert_called_once()
            self.assertEqual(t["task"]["command"], TaskCommand.TYPE_TEXT.value)

    def test_scenario_4_multi_turn_drafting_and_editing(self):
        """Scenario 4:
        User drafts an email and then edits it across multiple conversational turns.
        Edits must be applied to the structured draft and never typed as keystrokes.
        """
        with patch.object(self.orchestrator.automation, "_type_text") as mock_type:
            # Turn 1: create draft
            self.orchestrator.chat("send mail to gsunilkumar1307@gmail.com")
            t2 = self.orchestrator.chat("Write a polite email asking whether the project presentation deadline can be extended by two days. Do not invent a reason.")
            initial_body = t2["task"]["params"]["formatted_body"]

            # Turn 3: edit draft
            t3 = self.orchestrator.chat("Make it very formal and change subject to Urgent: Deadline Extension Inquiry")
            task3 = t3["task"]

            mock_type.assert_not_called()
            self.assertEqual(task3["params"]["subject"].lower(), "urgent: deadline extension inquiry")
            self.assertEqual(task3["status"], TaskStatus.WAITING_APPROVAL.value)

    def test_scenario_5_draft_edit_invalidates_approval_hash(self):
        """Scenario 5:
        Draft modification must invalidate previous approval hash.
        """
        self.orchestrator.chat("send mail to gsunilkumar1307@gmail.com")
        t2 = self.orchestrator.chat("Write a polite email asking whether the project presentation deadline can be extended by two days. Do not invent a reason.")
        initial_hash = t2["task"]["params"]["approval_hash"]
        self.assertTrue(bool(initial_hash))

        t3 = self.orchestrator.chat("Change subject to Updated Project Deadline Request")
        new_hash = t3["task"]["params"]["approval_hash"]
        self.assertTrue(bool(new_hash))

        # Hashes must differ
        self.assertNotEqual(initial_hash, new_hash)
        self.assertEqual(t3["task"]["status"], TaskStatus.WAITING_APPROVAL.value)

    def test_single_turn_direct_instruction(self):
        """Single turn direct command:
        'Write a polite email to gsunilkumar1307@gmail.com asking whether the project presentation deadline can be extended by two days. Do not invent a reason.'
        """
        with patch.object(self.orchestrator.automation, "_type_text") as mock_type:
            t = self.orchestrator.chat("Write a polite email to gsunilkumar1307@gmail.com asking whether the project presentation deadline can be extended by two days. Do not invent a reason.")
            mock_type.assert_not_called()
            task = t["task"]
            self.assertEqual(task["command"], TaskCommand.DRAFT_MAIL.value)
            self.assertEqual(task["params"]["recipient"], "gsunilkumar1307@gmail.com")
            self.assertEqual(task["params"]["subject"], "Project Presentation Deadline Extension Request")
            self.assertIn("Could the project presentation deadline please be extended by two days?", task["params"]["formatted_body"])

    def test_diagnostic_logging_redaction(self):
        """Diagnostic logging must record selected capability with sensitive fields redacted."""
        from backend.core.contracts import Task
        task = Task(
            intent="Draft an email",
            command=TaskCommand.DRAFT_MAIL,
            params={
                "recipient": "test@example.com",
                "subject": "Test Subject",
                "body": "Sensitive body content that must be redacted",
                "formatted_body": "Sensitive formatted body",
            },
        )
        self.orchestrator._execute(task)

        # Find capability_selected event
        cap_events = [e for e in task.audit_trail if getattr(e, "event_type", "") == "capability_selected" or getattr(e, "name", "") == "capability_selected"]
        self.assertTrue(len(cap_events) > 0, "capability_selected event must be recorded")

        event = cap_events[0]
        meta = getattr(event, "data", {}).get("metadata", {})
        self.assertEqual(meta.get("body"), "[REDACTED]")
        self.assertEqual(meta.get("formatted_body"), "[REDACTED]")
        self.assertEqual(meta.get("recipient"), "test@example.com")


if __name__ == "__main__":
    unittest.main()
