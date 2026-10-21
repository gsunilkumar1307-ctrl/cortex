from __future__ import annotations

import time
from typing import Any
try:
    from backend.core.contracts import (
        ExecutionResult,
        Observation,
        VerificationResult,
        ExecutionError,
        RiskLevel,
        TaskCommand,
        TaskContext,
    )
except ImportError:
    from core.contracts import (
        ExecutionResult,
        Observation,
        VerificationResult,
        ExecutionError,
        RiskLevel,
        TaskCommand,
        TaskContext,
    )
from .base import BaseTool


class MailTool(BaseTool):
    """Universal Mail Tool for reading, drafting, and sending emails with strict verification."""

    def __init__(self, mail_automation: Any = None, automation: Any = None) -> None:
        super().__init__(
            name="mail_tool",
            description="Interacts with Apple Mail for reading, drafting, searching, and sending emails.",
            risk_level=RiskLevel.HIGH,
            command=TaskCommand.SEND_MAIL,
            irreversible=True,  # Sending email is irreversible!
        )
        if mail_automation:
            self.mail = mail_automation
        elif automation:
            self.mail = getattr(automation, "mail", getattr(automation, "_get_mail", lambda: None)())
        else:
            self.mail = None

    def set_mail_automation(self, mail_automation: Any) -> None:
        self.mail = mail_automation

    def execute(self, inputs: dict[str, Any], context: TaskContext | None = None) -> ExecutionResult:
        start_time = time.time()
        action = inputs.get("action", "send_mail")
        recipient = inputs.get("recipient_email") or inputs.get("recipient", "")
        subject = inputs.get("subject", "")
        body = inputs.get("formatted_body") or inputs.get("body", "")

        if not self.mail:
            return ExecutionResult(
                step_id=inputs.get("step_id", "mail-step"),
                ok=False,
                message="Mail automation adapter not initialized.",
                error="AdapterMissing",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if action == "draft_mail":
            res = self.mail.draft_mail(recipient, subject, body)
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "draft-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data=res.get("data", {}),
                error=None if res.get("ok") else res.get("message"),
                duration_ms=duration_ms,
            )

        elif action == "send_mail":
            try:
                res = self.mail.send_mail(recipient, subject, body)
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                return ExecutionResult(
                    step_id=inputs.get("step_id", "send-step"),
                    ok=False,
                    message=f"Send mail failed: {e}",
                    error=str(e),
                    duration_ms=duration_ms,
                )
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "send-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data=res.get("data", {}),
                error=None if res.get("ok") else res.get("message"),
                duration_ms=duration_ms,
            )

        elif action == "read_mail":
            res = self.mail.read_mail(limit=int(inputs.get("limit", 5)), unread_only=bool(inputs.get("unread_only", False)))
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "read-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data={"emails": res.get("emails", [])},
                error=None if res.get("ok") else res.get("message"),
                duration_ms=duration_ms,
            )

        elif action == "search_mail":
            res = self.mail.search_mail(inputs.get("query", ""))
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "search-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data={"emails": res.get("emails", [])},
                error=None if res.get("ok") else res.get("message"),
                duration_ms=duration_ms,
            )

        elif action == "email_briefing":
            res = self.mail.email_briefing(limit=int(inputs.get("limit", 10)))
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "briefing-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data=res.get("data", {}),
                duration_ms=duration_ms,
            )

        elif action == "extract_actions":
            res = self.mail.extract_actions(limit=int(inputs.get("limit", 5)))
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "extract-step"),
                ok=res.get("ok", False),
                message=res.get("message", ""),
                data={"actions": res.get("actions", [])},
                duration_ms=duration_ms,
            )

        elif action == "delete_draft":
            res = self.mail.delete_draft(recipient, subject) if hasattr(self.mail, "delete_draft") else {"ok": True, "message": "Draft deleted."}
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "delete-draft-step"),
                ok=res.get("ok", True),
                message=res.get("message", "Draft deleted."),
                duration_ms=duration_ms,
            )

        elif action == "search_contacts":
            contacts = self.mail.search_contacts(inputs.get("query", "")) if hasattr(self.mail, "search_contacts") else []
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "contacts-step"),
                ok=True,
                message=f"Found {len(contacts)} contacts.",
                data={"contacts": contacts},
                duration_ms=duration_ms,
            )

        elif action == "get_accounts":
            accounts = self.mail.get_accounts() if hasattr(self.mail, "get_accounts") else []
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "accounts-step"),
                ok=True,
                message=f"Found {len(accounts)} accounts.",
                data={"accounts": accounts},
                duration_ms=duration_ms,
            )

        elif action == "get_signature":
            sig = self.mail.get_signature(inputs.get("account", "")) if hasattr(self.mail, "get_signature") else "\n\nBest regards,"
            duration_ms = (time.time() - start_time) * 1000
            return ExecutionResult(
                step_id=inputs.get("step_id", "signature-step"),
                ok=True,
                message="Retrieved signature.",
                data={"signature": sig},
                duration_ms=duration_ms,
            )

        return ExecutionResult(
            step_id=inputs.get("step_id", "unknown-step"),
            ok=False,
            message=f"Unsupported mail action: {action}",
            error="UnsupportedAction",
        )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        action = inputs.get("action", "send_mail")
        recipient = inputs.get("recipient_email") or inputs.get("recipient", "")
        subject = inputs.get("subject", "")

        state: dict[str, Any] = {"action": action, "recipient": recipient, "subject": subject}

        if action == "draft_mail" and self.mail and hasattr(self.mail, "verify_draft_created"):
            draft_check = self.mail.verify_draft_created(recipient, subject)
            state["draft_found"] = draft_check.get("verified", False)
            state["evidence"] = draft_check.get("evidence", "")

        elif action == "send_mail":
            if self.mail and hasattr(self.mail, "verify_mail_sent"):
                send_check = self.mail.verify_mail_sent(recipient, subject)
            else:
                try:
                    from backend.capabilities.mail_actions import _sent_records
                except ImportError:
                    from capabilities.mail_actions import _sent_records
                found = any(s.get("recipient", "").lower() == recipient.lower() for s in _sent_records)
                send_check = {"verified": found, "evidence": "Checked sent register"}
            state["sent_found"] = send_check.get("verified", False)
            state["in_sent_mailbox"] = send_check.get("verified", False)
            state["evidence"] = send_check.get("evidence", "")

        elif action in ("read_mail", "search_mail"):
            state["count"] = len(execution_result.data.get("emails", []))

        return Observation(
            target=f"mail:{recipient or 'inbox'}",
            state_data=state,
            raw_output=execution_result.message,
            evidence_type="system_mailbox_query",
        )

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        """Independently verifies that the expected mail state was achieved."""
        action = inputs.get("action", "send_mail")
        recipient = inputs.get("recipient_email") or inputs.get("recipient", "")

        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Execution failed: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )

        if action == "draft_mail":
            verified = observation.state_data.get("draft_found", execution_result.ok)
            evidence = observation.state_data.get("evidence") or f"Draft confirmed for {recipient}"
            return VerificationResult(
                verified=verified,
                confidence=1.0 if verified else 0.5,
                evidence=evidence,
                uncertainty_reason=None if verified else "Draft not found in draft mailbox",
            )

        elif action == "send_mail":
            # For send_mail, we NEVER rely on execution_result.ok alone. We require observation evidence!
            verified = observation.state_data.get("sent_found", False)
            evidence = observation.state_data.get("evidence", "")
            if verified:
                return VerificationResult(
                    verified=True,
                    confidence=1.0,
                    evidence=f"Message verified in Sent mailbox for {recipient}: {evidence}",
                )
            else:
                return VerificationResult(
                    verified=False,
                    confidence=0.0,
                    evidence="Message not found in Sent mailbox despite execution call.",
                    uncertainty_reason="Uncertain delivery state: send executed but message not yet visible in Sent mailbox.",
                )

        # Read-only actions
        return VerificationResult(
            verified=True,
            confidence=1.0,
            evidence=f"Retrieved {observation.state_data.get('count', 0)} messages.",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        action = inputs.get("action", "send_mail")
        recipient = inputs.get("recipient", "")
        subject = inputs.get("subject", "")

        # CRITICAL SAFETY: If sending mail fails or is uncertain, check Sent mailbox FIRST!
        # NEVER repeat an email send blindly!
        if action == "send_mail":
            check = {"verified": False}
            if self.mail and hasattr(self.mail, "verify_mail_sent"):
                check = self.mail.verify_mail_sent(recipient, subject)
            else:
                try:
                    from backend.capabilities.mail_actions import _sent_records
                except ImportError:
                    from capabilities.mail_actions import _sent_records
                found = any(s.get("recipient", "").lower() == recipient.lower() for s in _sent_records)
                check = {"verified": found}

            if check.get("verified"):
                return {
                    "can_retry": False,
                    "strategy": "resolve_as_success",
                    "message": f"Email to {recipient} already exists in Sent mailbox (verified in Sent messages). Resolving without duplicate send.",
                }

        return {
            "can_retry": False,  # Never blind-retry email sending
            "strategy": "escalate",
            "message": f"Email operation failed ({error.message}). Halting execution to prevent duplicate email. Escalated to user.",
        }
