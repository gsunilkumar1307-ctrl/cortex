"""
Tests for Phase P7.5.3: Email Send Safety Gate Correction.

Verifies:
1. Mandatory safety gate: Real email transmission is permitted ONLY when
   os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1".
   All other values (unset, empty string, '0', 'false', 'False', 'no', 'off',
   'true', 'yes', etc.) evaluate to False (BLOCK).
2. All outbound execution routes enforce the gate immediately before dispatch:
   - MailAutomation.send_mail()
   - AppleMailProvider.send_message()
   - GmailProvider.send_message()
   - MailProviderManager.send_message()
   - DeviceActionHandler._send_mail()
   - Apple Mail MCP sending tools
3. Reply and Forward execution paths enforce the gate.
4. Cryptographic approval tokens: single-use, 300s TTL, SHA-256 payload integrity.
5. In the "1" case, authorization is granted at the gate and dispatches to
   mocked implementations (zero real outbound emails transmitted).
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import pytest

from backend.agent.email_engine import EmailDraft
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation
from backend.capabilities.mail_actions import MailAutomation, clear_mail_records
from backend.capabilities.safety import is_real_email_send_allowed
from backend.core.contracts import MailDeliveryStatus, TaskCommand, TaskStatus
from backend.integrations.email.apple_mail_provider import AppleMailProvider
from backend.integrations.email.gmail_provider import GmailProvider
from backend.integrations.email.manager import MailProviderManager
from backend.mcp.client import MCPClient
from backend.mcp.config import get_apple_mail_server_config
from backend.mcp.exceptions import MCPSecurityError
from backend.mcp.process import MCPProcess
from backend.persistence.task_store import TaskStore


class TestEmailSendSafetyGateP753(unittest.TestCase):
    """Authoritative test suite for P7.5.3 safety gate correction."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_p753.sqlite3")
        self.task_store = TaskStore(self.db_path)
        clear_mail_records(self.db_path)

    def tearDown(self) -> None:
        clear_mail_records(self.db_path)
        self.temp_dir.cleanup()

    # =========================================================================
    # 1. Centralized Gate Truth Table Verification
    # =========================================================================

    def test_01_centralized_gate_table_matrix(self) -> None:
        """Verifies is_real_email_send_allowed() against all required environment values."""
        blocked_values = [
            None,       # Unset
            "",         # Empty string
            "   ",      # Whitespace only
            "0",        # Zero
            "false",    # Lowercase false
            "False",    # Titlecase False
            "FALSE",    # Uppercase FALSE
            "no",       # No
            "off",      # Off
            "true",     # Truthy string 'true' (must NOT enable)
            "yes",      # Truthy string 'yes' (must NOT enable)
            "2",        # Arbitrary number
            "enabled",  # Word enabled
            "on",       # Word on
        ]

        for val in blocked_values:
            if val is None:
                with patch.dict(os.environ, {}, clear=True):
                    os.environ.pop("CORTEX_ALLOW_REAL_EMAIL_SEND", None)
                    self.assertFalse(
                        is_real_email_send_allowed(),
                        f"Expected unset CORTEX_ALLOW_REAL_EMAIL_SEND to evaluate to False, got True"
                    )
            else:
                with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": val}):
                    self.assertFalse(
                        is_real_email_send_allowed(),
                        f"Expected CORTEX_ALLOW_REAL_EMAIL_SEND={val!r} to evaluate to False, got True"
                    )

        # Only exact '1' or whitespace-padded '1' evaluates to True
        allowed_values = ["1", " 1 ", "1\n", "\t1\t"]
        for val in allowed_values:
            with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": val}):
                self.assertTrue(
                    is_real_email_send_allowed(),
                    f"Expected CORTEX_ALLOW_REAL_EMAIL_SEND={val!r} to evaluate to True, got False"
                )

    # =========================================================================
    # 2. MailAutomation.send_mail Outbound Gate Verification
    # =========================================================================

    def test_02_mail_automation_blocks_all_non_one_values_without_dispatch(self) -> None:
        """Verifies MailAutomation.send_mail() blocks transmission for every blocked value without calling dispatch."""
        mail = MailAutomation(dry_run=False)
        mail.system = "darwin"

        blocked_cases = [None, "", "0", "false", "False", "no", "off", "true", "yes"]

        for val in blocked_cases:
            env_override = {} if val is None else {"CORTEX_ALLOW_REAL_EMAIL_SEND": val}
            with patch.dict(os.environ, env_override, clear=(val is None)):
                if val is None:
                    os.environ.pop("CORTEX_ALLOW_REAL_EMAIL_SEND", None)

                with patch("subprocess.run") as mock_subproc, \
                     patch("urllib.request.urlopen") as mock_urlopen:

                    # 1. Test Apple Mail route
                    res_apple = mail.send_mail(
                        recipient="student@college.edu",
                        subject="Term Paper",
                        body="Attached draft.",
                        account="College Account",
                    )
                    self.assertFalse(res_apple.get("ok"))
                    self.assertEqual(res_apple.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
                    self.assertEqual(res_apple.get("error"), "SEND_BLOCKED_BY_POLICY")
                    mock_subproc.assert_not_called()

                    # 2. Test Gmail route
                    res_gmail = mail.send_mail(
                        recipient="partner@gmail.com",
                        subject="Project Update",
                        body="Status is good.",
                        account="Google <partner@gmail.com>",
                    )
                    self.assertFalse(res_gmail.get("ok"))
                    self.assertEqual(res_gmail.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
                    self.assertEqual(res_gmail.get("error"), "SEND_BLOCKED_BY_POLICY")
                    mock_urlopen.assert_not_called()

    # =========================================================================
    # 3. Direct Provider Helpers Enforcement
    # =========================================================================

    def test_03_direct_apple_mail_provider_send_message(self) -> None:
        """Verifies AppleMailProvider.send_message enforces gate on direct call."""
        provider = AppleMailProvider(dry_run=False)
        provider.system = "darwin"

        # Blocked case
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            with patch("subprocess.run") as mock_subproc:
                res = provider.send_message(
                    recipient="dean@university.edu",
                    subject="Research Grant",
                    body="Proposal details.",
                    account="Faculty",
                )
                self.assertFalse(res.get("ok"))
                self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
                self.assertEqual(res.get("error"), "SEND_BLOCKED_BY_POLICY")
                mock_subproc.assert_not_called()

        # Allowed case (mocked dispatch, no real email)
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "1"}):
            with patch("subprocess.run") as mock_subproc:
                mock_subproc.return_value = MagicMock(returncode=0)
                res = provider.send_message(
                    recipient="dean@university.edu",
                    subject="Research Grant",
                    body="Proposal details.",
                    account="Faculty",
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.DELIVERY_UNCONFIRMED.value)
                mock_subproc.assert_called_once()

    def test_04_direct_gmail_provider_send_message(self) -> None:
        """Verifies GmailProvider.send_message enforces gate on direct call."""
        provider = GmailProvider(sandbox=False)

        # Blocked case
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            with patch("urllib.request.urlopen") as mock_url:
                res = provider.send_message(
                    recipient="investor@gmail.com",
                    subject="Pitch Deck",
                    body="See attachment.",
                    account="My Gmail",
                )
                self.assertFalse(res.get("ok"))
                self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
                self.assertEqual(res.get("error"), "SEND_BLOCKED_BY_POLICY")
                mock_url.assert_not_called()

        # Allowed case (mocked dispatch, no real email)
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "1"}):
            with patch("urllib.request.urlopen") as mock_url, \
                 patch.object(provider, "is_authenticated", return_value=True):
                mock_resp = MagicMock()
                mock_resp.read.return_value = b'{"id": "gmail-mock-id-777"}'
                mock_url.return_value.__enter__.return_value = mock_resp

                res = provider.send_message(
                    recipient="investor@gmail.com",
                    subject="Pitch Deck",
                    body="See attachment.",
                    account="My Gmail",
                )
                self.assertTrue(res.get("ok"))
                self.assertEqual(res.get("message_id"), "gmail-mock-id-777")
                mock_url.assert_called_once()

    def test_05_direct_mail_provider_manager_send_message(self) -> None:
        """Verifies MailProviderManager.send_message enforces gate before delegating."""
        mgr = MailProviderManager(dry_run=False)

        # Blocked case
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            with patch.object(mgr.apple_mail, "send_message") as mock_apple_send:
                res = mgr.send_message(
                    recipient="client@agency.com",
                    subject="Invoice",
                    body="Details enclosed.",
                    account="Work",
                )
                self.assertFalse(res.get("ok"))
                self.assertEqual(res.get("delivery_status"), MailDeliveryStatus.BLOCKED.value)
                self.assertEqual(res.get("error"), "SEND_BLOCKED_BY_POLICY")
                mock_apple_send.assert_not_called()

        # Allowed case
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "1"}):
            with patch.object(mgr.apple_mail, "send_message") as mock_apple_send:
                mock_apple_send.return_value = {"ok": True, "message": "Dispatched to mock provider"}
                res = mgr.send_message(
                    recipient="client@agency.com",
                    subject="Invoice",
                    body="Details enclosed.",
                    account="Work",
                )
                self.assertTrue(res.get("ok"))
                mock_apple_send.assert_called_once()

    def test_06_direct_device_automation_send_mail(self) -> None:
        """Verifies DeviceAutomation._send_mail enforces gate and returns failure."""
        handler = DeviceAutomation()

        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            result = handler._send_mail(
                recipient="director@company.com",
                subject="Q3 Goals",
                body="Draft presentation.",
                account="Default",
            )
            self.assertFalse(result.ok)
            self.assertIn("blocked by safety policy", result.message.lower())
            self.assertEqual(result.data.get("error"), "SEND_BLOCKED_BY_POLICY")

    # =========================================================================
    # 4. Apple Mail MCP Send Tools Strictly Blocked
    # =========================================================================

    def test_07_mcp_apple_mail_sending_tools_strictly_blocked(self) -> None:
        """Verifies MCPClient strictly blocks all apple-mail sending tools."""
        cfg = get_apple_mail_server_config()
        proc = MCPProcess(cfg)
        client = MCPClient(proc)

        send_tools = ["send-email", "send-serial-email", "reply-to-message", "forward-message"]
        for tool_name in send_tools:
            self.assertFalse(cfg.is_tool_allowed(tool_name))
            with pytest.raises(MCPSecurityError) as ctx:
                asyncio.run(client.call_tool(tool_name, {"to": "audit@example.com"}))
            self.assertIn("not allowed", str(ctx.value).lower())

    # =========================================================================
    # 5. Reply & Forward Paths Gated by Policy
    # =========================================================================

    def test_08_reply_workflow_draft_and_send_gate_enforcement(self) -> None:
        """Verifies reply drafting succeeds with RFC threading headers, and approval send is blocked when CORTEX_ALLOW_REAL_EMAIL_SEND=0."""
        orc = CortexOrchestrator(task_store=self.task_store, use_gemini=False)

        # Mock incoming message in search results
        mock_msg = {
            "id": "msg-reply-101",
            "subject": "Interview Invitation",
            "sender": "Rahul <rahul@example.com>",
            "body": "Can you attend tomorrow?",
            "date": "2026-11-18",
            "account": "Google",
        }

        with patch.object(orc.mail_automation, "search_mail") as mock_search, \
             patch.object(orc.mail_automation, "get_message") as mock_get_msg, \
             patch.object(orc.mail_automation, "get_message_headers") as mock_headers:

            mock_search.return_value = {"ok": True, "emails": [mock_msg]}
            mock_get_msg.return_value = {"ok": True, "email": mock_msg}
            mock_headers.return_value = {
                "ok": True,
                "rfc_message_id": "<rahul-msg-101@example.com>",
                "headers": {"message-id": "<rahul-msg-101@example.com>"},
                "in_reply_to": "",
                "references": [],
            }

            # User issues reply instruction
            res = orc.chat("Reply to Rahul saying I will attend the session tomorrow at 2 PM.")
            self.assertIn("task", res)
            task_dict = res["task"]
            self.assertEqual(task_dict["status"], TaskStatus.WAITING_APPROVAL.value)
            self.assertEqual(task_dict["params"].get("in_reply_to"), "<rahul-msg-101@example.com>")
            task_id = task_dict["id"]

            # User confirms send via conversational command with CORTEX_ALLOW_REAL_EMAIL_SEND=0
            with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
                with patch("subprocess.run") as mock_subproc:
                    confirm_res = orc.chat("send")
                    task_res = confirm_res.get("task", {})
                    self.assertEqual(task_res.get("status"), TaskStatus.FAILED.value)
                    for call_arg in mock_subproc.call_args_list:
                        args = call_arg[0] if call_arg and len(call_arg) > 0 else []
                        script_text = " ".join(str(a) for a in args)
                        self.assertNotIn("make new outgoing message", script_text)
                        self.assertNotIn("send", script_text.split())
                    task_after = orc._get_task(task_id)
                    audit_msgs = [e.message for e in task_after.audit_trail]
                    self.assertTrue(any("blocked by safety policy" in m.lower() for m in audit_msgs))

    def test_09_forward_workflow_draft_and_send_gate_enforcement(self) -> None:
        """Verifies forward drafting succeeds with content and approval send is blocked when CORTEX_ALLOW_REAL_EMAIL_SEND=0."""
        orc = CortexOrchestrator(task_store=self.task_store, use_gemini=False)

        mock_msg = {
            "id": "msg-fwd-202",
            "subject": "Vendor Quote",
            "sender": "Rahul <rahul@example.com>",
            "body": "Here is the pricing breakdown for Q1.",
            "date": "2026-11-18",
            "account": "Google",
        }

        with patch.object(orc.mail_automation, "search_mail") as mock_search, \
             patch.object(orc.mail_automation, "get_message") as mock_get_msg, \
             patch.object(orc.mail_automation, "get_message_headers") as mock_headers:

            mock_search.return_value = {"ok": True, "emails": [mock_msg]}
            mock_get_msg.return_value = {"ok": True, "email": mock_msg}
            mock_headers.return_value = {
                "ok": True,
                "rfc_message_id": "<vendor-quote-202@vendor.com>",
                "headers": {"message-id": "<vendor-quote-202@vendor.com>"},
                "in_reply_to": "",
                "references": [],
            }

            res = orc.chat("Forward the email from Rahul to Sarah saying please review this quote.")
            self.assertIn("task", res)
            task_dict = res["task"]
            self.assertEqual(task_dict["status"], TaskStatus.WAITING_APPROVAL.value)

            task_id = task_dict["id"]

            with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
                with patch("subprocess.run") as mock_subproc:
                    confirm_res = orc.chat("send")
                    task_res = confirm_res.get("task", {})
                    self.assertEqual(task_res.get("status"), TaskStatus.FAILED.value)
                    for call_arg in mock_subproc.call_args_list:
                        args = call_arg[0] if call_arg and len(call_arg) > 0 else []
                        script_text = " ".join(str(a) for a in args)
                        self.assertNotIn("make new outgoing message", script_text)
                        self.assertNotIn("send", script_text.split())
                    task_after = orc._get_task(task_id)
                    audit_msgs = [e.message for e in task_after.audit_trail]
                    self.assertTrue(any("blocked by safety policy" in m.lower() for m in audit_msgs))

    # =========================================================================
    # 6. Approval Lifecycle Regression (Hash, Expiry, Single-Use)
    # =========================================================================

    def test_10_approval_lifecycle_hash_expiry_and_replay(self) -> None:
        """Verifies tamper detection, 300s expiration, and single-use replay protection."""
        orc = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        chat_res = orc.chat("Send Rahul a mail saying I am available next week.")
        self.assertIn("task", chat_res)
        task_dict = chat_res["task"]
        task_id = task_dict["id"]
        valid_hash = task_dict["params"]["approval_hash"]

        # 1. Tampered hash is rejected
        tampered_res = orc.approve(task_id, approved=True, approval_hash="0000000000000000000000000000000000000000000000000000000000000000")
        self.assertIn("mismatch", tampered_res.get("error", "").lower())

        # 2. Expired approval (> 300s) is rejected
        task = orc._get_task(task_id)
        task.params["created_at"] = time.time() - 305
        orc._persist_task(task)
        expired_res = orc.approve(task_id, approved=True, approval_hash=valid_hash)
        self.assertIn("expired", expired_res.get("error", "").lower())

        # Reset created_at to current time
        task.params["created_at"] = time.time()
        orc._persist_task(task)

        # 3. Single-use consumption & replay rejection
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            appr1 = orc.approve(task_id, approved=True, approval_hash=valid_hash)
            # First approval consumes the token
            self.assertTrue(task.params.get("approval_consumed"))

            # Replay attempt fails immediately
            appr2 = orc.approve(task_id, approved=True, approval_hash=valid_hash)
            self.assertIn("replay", appr2.get("error", "").lower())

    # =========================================================================
    # 7. Mocked Positive Authorization ("1" Case)
    # =========================================================================

    def test_11_positive_authorization_mocked_end_to_end_send(self) -> None:
        """Verifies CORTEX_ALLOW_REAL_EMAIL_SEND=1 grants authorization and dispatches to mock without sending real email."""
        orc = CortexOrchestrator(task_store=self.task_store, use_gemini=False)
        chat_res = orc.chat("Send Rahul a mail using my Apple Mail account saying I will attend the session tomorrow.")
        task_id = chat_res["task"]["id"]
        valid_hash = chat_res["task"]["params"]["approval_hash"]

        # Run in isolated environment where CORTEX_ALLOW_REAL_EMAIL_SEND == "1"
        # BUT with subprocess.run and verify_mail_sent mocked so no real email is transmitted!
        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "1"}):
            with patch("subprocess.run") as mock_subproc, \
                 patch("backend.capabilities.mail_actions.MailAutomation.verify_mail_sent") as mock_verify:

                mock_subproc.return_value = MagicMock(returncode=0, stdout="", stderr="")
                mock_verify.return_value = {
                    "verified": True,
                    "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value,
                    "status": MailDeliveryStatus.SENT_VERIFIED.value,
                    "details": {"message_id": "mock-sent-123"},
                }

                appr_res = orc.approve(task_id, approved=True, approval_hash=valid_hash)
                # Verify execution reached the mock dispatch
                self.assertEqual(appr_res["status"], TaskStatus.COMPLETED.value)
                self.assertTrue(mock_subproc.called)

    # =========================================================================
    # 8. Secret & Privacy Preservation in Safety Logging
    # =========================================================================

    def test_12_no_leakage_in_safety_logging(self) -> None:
        """Verifies blocked policy logs do not dump recipient addresses or email bodies."""
        mail = MailAutomation(dry_run=False)

        with patch.dict(os.environ, {"CORTEX_ALLOW_REAL_EMAIL_SEND": "0"}):
            with self.assertLogs("backend.capabilities.mail_actions", level=logging.WARNING) as cm:
                mail.send_mail(
                    recipient="secret_patient_99@confidential.hospital.org",
                    subject="Medical Diagnosis - Highly Confidential",
                    body="Patient diagnosed with private condition.",
                    account="Medical",
                )
                output = " ".join(cm.output)
                # Verify safety gate warning was logged
                self.assertIn("blocked by safety policy", output.lower())
                # Verify sensitive parameters were NOT leaked in log message
                self.assertNotIn("secret_patient_99", output)
                self.assertNotIn("private condition", output)
                self.assertNotIn("Highly Confidential", output)


if __name__ == "__main__":
    unittest.main()
