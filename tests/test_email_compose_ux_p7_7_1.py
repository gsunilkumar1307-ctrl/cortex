"""Deterministic regression test suite for CORTEX P7.7.1 Conversational Draft Editing.

Verifies:
1. Exact 5-step conversational sequence from live desktop audit:
   - Initial draft: "send mail to myself for requesting a leave permission"
   - Edit 1: "make it more formal and friendly tone"
   - Edit 2: "recipient name is sunil"
   - Edit 3: "make it short"
   - Edit 4: "make the leave permission for 1 week"
2. Order-independence: All permutations of the 4 edits produce clean drafts.
3. Universal placeholder elimination: No '[Recipient / Manager]' remains.
4. No instruction text leakage: Prompts are never appended into the email body.
5. Multi-turn orchestrator chat state synchronization and state_version bumping.
6. Honest handling of unrecognized edits without draft corruption.
7. Cryptographic approval hash recalculation and stale hash replay prevention.
"""

import unittest
import itertools
from unittest.mock import MagicMock

from backend.agent.email_engine import EmailEngine, EmailDraft
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus


class TestEmailComposeUXP771(unittest.TestCase):
    """P7.7.1 Conversational Draft Editing Reliability Tests."""

    def setUp(self):
        self.engine = EmailEngine()
        self.orch = CortexOrchestrator()

    def test_exact_5_step_sequence_direct(self):
        """Validates the exact 5-step sequence directly on EmailEngine."""
        # Step 1: Initial draft
        draft = self.engine.generate_email_draft(
            recipient="gsunilkumar1307@gmail.com",
            command="send_mail",
            content="send mail to myself for requesting a leave permission",
            relationship_type="self",
        )
        self.assertIn("leave", draft.body.lower())
        self.assertIn("gsunilkumar1307@gmail.com", draft.recipient)

        # Step 2: "make it more formal and friendly tone"
        draft2 = self.engine.update_draft_with_edit(draft, "make it more formal and friendly tone")
        self.assertIn("hope this email finds you well", draft2.body.lower())
        self.assertIn("understanding and consideration", draft2.body.lower())

        # Step 3: "recipient name is sunil"
        draft3 = self.engine.update_draft_with_edit(draft2, "recipient name is sunil")
        self.assertTrue(draft3.body.startswith("Dear Sunil,"))
        self.assertNotIn("[Recipient", draft3.body)
        self.assertNotIn("[Manager", draft3.body)

        # Step 4: "make it short"
        draft4 = self.engine.update_draft_with_edit(draft3, "make it short")
        self.assertTrue(draft4.body.startswith("Dear Sunil,"))
        self.assertIn("respectfully request leave of absence", draft4.body)
        self.assertNotIn("[Recipient", draft4.body)

        # Step 5: "make the leave permission for 1 week"
        draft5 = self.engine.update_draft_with_edit(draft4, "make the leave permission for 1 week")
        
        # Final Assertions:
        # 1. Addressed to Sunil
        self.assertTrue(draft5.body.startswith("Dear Sunil,"), f"Expected 'Dear Sunil,', got: {draft5.body[:30]}")
        # 2. Contains 1 week duration
        self.assertIn("for 1 week", draft5.body)
        # 3. Concise and structured
        lines = [l.strip() for l in draft5.body.split("\n\n") if l.strip()]
        self.assertGreaterEqual(len(lines), 3)
        # 4. Zero placeholders
        self.assertNotIn("[Recipient / Manager]", draft5.body)
        self.assertNotIn("[Recipient]", draft5.body)
        self.assertNotIn("[Manager]", draft5.body)
        # 5. Zero instruction text leakage
        self.assertNotIn("make it short", draft5.body)
        self.assertNotIn("recipient name is sunil", draft5.body)
        self.assertNotIn("make the leave permission for 1 week", draft5.body)
        self.assertNotIn("make it more formal and friendly tone", draft5.body)
        # 6. Valid sign-off
        self.assertIn("Sincerely,\nSunil Kumar", draft5.body)

    def test_permutations_of_conversational_edits(self):
        """Verifies that all 24 orderings of the 4 edits produce a clean, valid draft."""
        edits = [
            "make it more formal and friendly tone",
            "recipient name is sunil",
            "make it short",
            "make the leave permission for 1 week",
        ]

        for perm in itertools.permutations(edits):
            draft = self.engine.generate_email_draft(
                recipient="gsunilkumar1307@gmail.com",
                command="send_mail",
                content="send mail to myself for requesting a leave permission",
                relationship_type="self",
            )
            for edit in perm:
                draft = self.engine.update_draft_with_edit(draft, edit)

            self.assertIn("Dear Sunil,", draft.body, f"Dear Sunil missing for perm: {perm}")
            self.assertIn("1 week", draft.body, f"1 week missing for perm: {perm}")
            self.assertNotIn("[Recipient", draft.body, f"Placeholder remaining for perm: {perm}")
            self.assertNotIn("make it short", draft.body.lower(), f"Instruction leaked for perm: {perm}")
            self.assertIn("sunil kumar", draft.body.lower(), f"Signoff missing for perm: {perm}")

    def test_orchestrator_multi_turn_chat_sequence(self):
        """Verifies full conversational flow through CortexOrchestrator.chat()."""
        # Turn 1
        resp1 = self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]
        task1 = self.orch.tasks[task_id]
        self.assertEqual(task1.status, TaskStatus.WAITING_APPROVAL)
        h1 = task1.params["approval_hash"]
        v1 = task1.state_version

        # Turn 2
        resp2 = self.orch.chat("make it more formal and friendly tone")
        task2 = self.orch.tasks[task_id]
        h2 = task2.params["approval_hash"]
        v2 = task2.state_version
        self.assertNotEqual(h1, h2, "Hash must update on formal & friendly edit")
        self.assertGreater(v2, v1, "State version must increment")

        # Turn 3
        resp3 = self.orch.chat("recipient name is sunil")
        task3 = self.orch.tasks[task_id]
        h3 = task3.params["approval_hash"]
        self.assertIn("Dear Sunil,", task3.params["formatted_body"])
        self.assertNotIn("[Recipient", task3.params["formatted_body"])
        self.assertNotEqual(h2, h3, "Hash must update on recipient name edit")

        # Turn 4
        resp4 = self.orch.chat("make it short")
        task4 = self.orch.tasks[task_id]
        h4 = task4.params["approval_hash"]
        self.assertIn("Dear Sunil,", task4.params["formatted_body"])
        self.assertNotIn("[Recipient", task4.params["formatted_body"])

        # Turn 5
        resp5 = self.orch.chat("make the leave permission for 1 week")
        task5 = self.orch.tasks[task_id]
        h5 = task5.params["approval_hash"]
        final_body = task5.params["formatted_body"]

        self.assertIn("Dear Sunil,", final_body)
        self.assertIn("1 week", final_body)
        self.assertNotIn("[Recipient", final_body)
        self.assertNotIn("make it short", final_body)
        self.assertNotIn("recipient name is sunil", final_body)
        self.assertNotIn("make the leave permission for 1 week", final_body)

        # Pending action synchronization
        self.assertEqual(self.orch.pending_action["body"], task5.params["body"])
        self.assertEqual(self.orch.pending_action["draft"].approval_hash, h5)

    def test_unrecognized_edit_honesty_and_no_corruption(self):
        """Verifies unrecognized edits do not pollute body and return honest feedback."""
        resp1 = self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]
        before_body = self.orch.tasks[task_id].params["formatted_body"]
        before_hash = self.orch.tasks[task_id].params["approval_hash"]
        before_version = self.orch.tasks[task_id].state_version

        # Send an unrecognized edit
        resp2 = self.orch.chat("gibberish instruction xyz 999")
        msg = resp2["message"] if isinstance(resp2, dict) else resp2

        # 1. Body must remain 100% identical and uncorrupted
        after_body = self.orch.tasks[task_id].params["formatted_body"]
        self.assertEqual(before_body, after_body)
        self.assertNotIn("gibberish", after_body)

        # 2. Hash and version preserved
        self.assertEqual(before_hash, self.orch.tasks[task_id].params["approval_hash"])
        self.assertEqual(before_version, self.orch.tasks[task_id].state_version)

        # 3. Honest feedback given to user
        self.assertTrue(
            "couldn't identify" in msg.lower() or "unchanged" in msg.lower(),
            f"Expected honest explanation, got: {msg}"
        )

    def test_stale_hash_rejection_after_conversational_edit(self):
        """Verifies that an approval payload containing an older hash is rejected."""
        resp1 = self.orch.chat("send mail to myself for requesting a leave permission")
        task_id = self.orch.pending_action["task_id"]
        initial_hash = self.orch.tasks[task_id].params["approval_hash"]

        # Perform conversational edit
        self.orch.chat("make the leave permission for 1 week")
        fresh_hash = self.orch.tasks[task_id].params["approval_hash"]
        self.assertNotEqual(initial_hash, fresh_hash)

        # Attempt to approve with stale hash
        stale_res = self.orch.approve(task_id, approved=True, approval_hash=initial_hash)
        self.assertIn("mismatch", (stale_res.get("error") or stale_res.get("message") or "").lower())

    def test_recipient_name_variations(self):
        """Tests diverse phrasing of recipient name directives."""
        base_draft = self.engine.generate_email_draft(
            recipient="test@example.com",
            command="send_mail",
            content="send mail to myself for requesting a leave permission",
            relationship_type="self",
        )

        variations = [
            ("recipient name is dr. ramesh", "Dear Dr. Ramesh,"),
            ("recipient is prof. sharma", "Dear Prof. Sharma,"),
            ("address recipient as priya", "Dear Priya,"),
            ("address him as mr. john", "Dear Mr. John,"),
            ("name is anita", "Dear Anita,"),
            ("dear mohan", "Dear Mohan,"),
        ]

        for phrase, expected_sal in variations:
            d = self.engine.update_draft_with_edit(base_draft, phrase)
            self.assertTrue(d.body.startswith(expected_sal), f"Failed on '{phrase}': expected {expected_sal}, got {d.body[:30]}")
            self.assertNotIn("[Recipient", d.body)

    def test_leave_duration_variations(self):
        """Tests diverse phrasing of leave durations."""
        base_draft = self.engine.generate_email_draft(
            recipient="test@example.com",
            command="send_mail",
            content="send mail to myself for requesting a leave permission",
            relationship_type="self",
        )

        variations = [
            ("make the leave permission for 2 weeks", "for 2 weeks"),
            ("leave for 3 days", "for 3 days"),
            ("leave duration is one month", "for one month"),
            ("for 5 days", "for 5 days"),
            ("make it for 10 days", "for 10 days"),
        ]

        for phrase, expected_substr in variations:
            d = self.engine.update_draft_with_edit(base_draft, phrase)
            self.assertIn(expected_substr, d.body, f"Failed on '{phrase}': expected {expected_substr} in body")

    def test_explicit_paragraph_addition(self):
        """Tests that explicit additions (add: ...) work without instruction leakage."""
        base_draft = self.engine.generate_email_draft(
            recipient="test@example.com",
            command="send_mail",
            content="send mail to myself for requesting a leave permission",
            relationship_type="self",
        )
        d = self.engine.update_draft_with_edit(base_draft, "add paragraph: I have handed over urgent tickets to Rajesh.")
        self.assertIn("I have handed over urgent tickets to Rajesh.", d.body)
        self.assertIn("Sincerely,\nSunil Kumar", d.body)


if __name__ == "__main__":
    unittest.main()
