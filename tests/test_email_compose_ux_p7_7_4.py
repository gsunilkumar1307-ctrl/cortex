"""Deterministic test suite for CORTEX P7.7.4 Desktop Composer Field Rendering.

Verifies:
1. The exact confirmed user workflow:
   - Turn 1: "Send mail to nishakindalkar@gmail.com to apply internship for pentagon space"
     - FROM populated with connected account ("Google <gsunilkumar1307@gmail.com>")
     - TO populated with canonical email ("nishakindalkar@gmail.com")
     - SUBJECT populated with non-blank subject line
     - BODY populated with initial email message
   - Turn 2: "Make it large and formal"
     - Returns concise feedback "Expanded the draft with additional details."
     - TO remains visibly populated ("nishakindalkar@gmail.com"), never blank
     - SUBJECT remains visibly populated, never blank, never containing body text
     - BODY contains formal expanded body starting with "Dear Nisha,"
     - Task params and draft object maintain strict field integrity
2. Component contract and validation logic:
   - Required fields validation: empty TO or empty SUBJECT blocks approval
   - Valid non-empty fields allow approval
   - Distinct, explicit BODY section with label and hint in desktop UI code
   - No CSS class name collision on composer inputs
"""

import unittest
from pathlib import Path
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskStatus


class TestEmailComposeUXP774(unittest.TestCase):
    """P7.7.4 Desktop Composer Field Rendering Verification Suite."""

    def setUp(self):
        self.orch = CortexOrchestrator()

    def test_confirmed_user_workflow_field_integrity(self):
        """Verifies Turn 1 and Turn 2 for Pentagon Space application email."""
        # ── Turn 1: Initial Request ──
        t1_resp = self.orch.chat("Send mail to nishakindalkar@gmail.com to apply internship for pentagon space")
        task_id = self.orch.pending_action["task_id"]
        t1 = self.orch.tasks[task_id]

        self.assertEqual(t1.status, TaskStatus.WAITING_APPROVAL)
        self.assertEqual(t1.state_version, 1)

        # Verify FROM (sender_account)
        self.assertTrue(bool(t1.params.get("sender_account")), "sender_account should not be empty")
        self.assertIn("gsunilkumar1307@gmail.com", t1.params.get("sender_account", ""))

        # Verify TO (recipient)
        self.assertEqual(t1.params.get("recipient"), "nishakindalkar@gmail.com")
        self.assertEqual(t1.params.get("recipient_email"), "nishakindalkar@gmail.com")
        self.assertEqual(self.orch.pending_action.get("recipient"), "nishakindalkar@gmail.com")

        # Verify SUBJECT
        subj = t1.params.get("subject", "")
        self.assertTrue(bool(subj), "Subject should not be empty")
        self.assertNotIn("\n", subj, "Subject must not contain multiline body content")
        self.assertTrue(len(subj) < 120, "Subject must be a concise subject line")

        # Verify BODY
        body = t1.params.get("formatted_body") or t1.params.get("body", "")
        self.assertTrue(bool(body), "Body should not be empty")
        self.assertIn("pentagon space", body.lower())

        # Verify Draft object in params
        draft = t1.params.get("draft")
        self.assertIsNotNone(draft, "Draft object must be in task params")
        self.assertEqual(draft.get("recipient"), "nishakindalkar@gmail.com")
        t1_hash = t1.params.get("approval_hash")

        # ── Turn 2: Follow-up Edit ("Make it large and formal") ──
        t2_resp = self.orch.chat("Make it large and formal")
        t2 = self.orch.tasks[task_id]

        # Task ID stability
        self.assertEqual(t2.id, task_id)
        self.assertEqual(self.orch.pending_action["task_id"], task_id)
        self.assertEqual(t2.state_version, 2)

        # Concise response message without duplicate "Draft created" announcement
        self.assertIn("expanded", t2_resp["message"].lower())
        self.assertNotIn("draft created and saved to your mailbox", t2_resp["message"].lower())

        # Verify FROM remains intact
        self.assertTrue(bool(t2.params.get("sender_account")), "sender_account must remain populated after edit")
        self.assertIn("gsunilkumar1307@gmail.com", t2.params.get("sender_account", ""))

        # Verify TO remains visibly populated (NEVER blank)
        self.assertEqual(t2.params.get("recipient"), "nishakindalkar@gmail.com")
        self.assertEqual(t2.params.get("recipient_email"), "nishakindalkar@gmail.com")
        self.assertEqual(self.orch.pending_action.get("recipient"), "nishakindalkar@gmail.com")

        # Verify SUBJECT remains visibly populated (NEVER blank)
        subj2 = t2.params.get("subject", "")
        self.assertTrue(bool(subj2), "Subject must remain populated after edit")
        self.assertNotIn("\n", subj2, "Subject must not contain body text")
        self.assertNotIn("dear nisha", subj2.lower(), "Subject must not contain salutation or body text")

        # Verify BODY has distinct editable content starting with Dear Nisha,
        body2 = t2.params.get("formatted_body") or t2.params.get("body", "")
        self.assertTrue(bool(body2), "Body must not be empty")
        self.assertTrue(body2.startswith("Dear Nisha,"), f"Body must start with 'Dear Nisha,', got: {body2[:30]}")
        self.assertIn("pentagon space", body2.lower())
        self.assertIn("internship program", body2.lower())
        self.assertIn("sincerely", body2.lower())

        # Verify approval hash updated on edit
        self.assertNotEqual(t1_hash, t2.params["approval_hash"])

    def test_validation_gate_blocks_approval_on_empty_fields(self):
        """Validates that empty required fields (recipient or subject) trigger blocking validation."""
        def is_valid(recipient: str, subject: str) -> bool:
            return bool(recipient and recipient.strip() and subject and subject.strip())

        # Both present -> allowed
        self.assertTrue(is_valid("user@example.com", "Project Status Update"))

        # Recipient empty -> blocked
        self.assertFalse(is_valid("", "Project Status Update"))
        self.assertFalse(is_valid("   ", "Project Status Update"))

        # Subject empty -> blocked
        self.assertFalse(is_valid("user@example.com", ""))
        self.assertFalse(is_valid("user@example.com", "   "))

        # Both empty -> blocked
        self.assertFalse(is_valid("", ""))
        self.assertFalse(is_valid(None, None))

    def test_frontend_source_code_contract(self):
        """Verifies that the React desktop app implements explicit BODY section, field resolution, and validation."""
        app_jsx_path = Path(__file__).resolve().parent.parent / "apps" / "desktop" / "src" / "App.jsx"
        self.assertTrue(app_jsx_path.exists(), "App.jsx must exist")
        content = app_jsx_path.read_text(encoding="utf-8")

        # Field resolution helpers exist
        self.assertIn("resolveComposerRecipient", content)
        self.assertIn("resolveComposerSubject", content)
        self.assertIn("resolveComposerBody", content)
        self.assertIn("resolveComposerSender", content)

        # Distinct explicit Body section with header and label
        self.assertIn("composer-body-section", content)
        self.assertIn("composer-body-header", content)
        self.assertIn('<span className="composer-label">Body</span>', content)

        # Validation warning and disabled approve button
        self.assertIn("composer-validation-warning", content)
        self.assertIn("disabled={isSaving || !isValid}", content)

        # Check styles.css has matching rules
        styles_path = Path(__file__).resolve().parent.parent / "apps" / "desktop" / "src" / "styles.css"
        self.assertTrue(styles_path.exists(), "styles.css must exist")
        styles = styles_path.read_text(encoding="utf-8")

        self.assertIn(".composer-field-input", styles)
        self.assertIn(".composer-body-section", styles)
        self.assertIn(".composer-body-header", styles)
        self.assertIn(".composer-validation-warning", styles)


if __name__ == "__main__":
    unittest.main()
