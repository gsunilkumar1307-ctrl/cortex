import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import sys
import urllib.request
import io

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.capabilities import DeviceAutomation
from backend.persistence import EncryptedMemoryStore
from backend.agent import CortexOrchestrator, EmailDraft
from backend.integrations.email.gmail_provider import GmailProvider
from backend.api.server import app
from fastapi.testclient import TestClient


class TestMasterDirectiveApprovalGate(unittest.TestCase):
    """Verifies Milestone 4 server-side approval gate and draft editing integrity."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(self.tmp.name) / "memory.sqlite3"))
        self.orch = CortexOrchestrator(DeviceAutomation(dry_run=True), memory, use_gemini=False)

    def test_draft_creation_stages_cryptographic_hash(self):
        resp = self.orch.chat("send email to test@domain.com saying Hello")
        task_id = resp["task"]["id"]
        task = self.orch.tasks[task_id]

        self.assertEqual(task.status, "waiting_approval")
        self.assertTrue(task.requires_approval)
        self.assertTrue(bool(task.params.get("approval_hash")))

        initial_hash = task.params["approval_hash"]

        # Manual computation must match
        expected_hash = EmailDraft(
            recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
            subject=task.params.get("subject", ""),
            body=task.params.get("formatted_body") or task.params.get("body", ""),
            sender_account=task.params.get("sender_account", ""),
            attachments=task.params.get("attachments", []),
        ).compute_hash()
        self.assertEqual(initial_hash, expected_hash)

    def test_edit_pending_draft_updates_fields_and_invalidates_hash(self):
        resp = self.orch.chat("send email to alice@domain.com saying Initial draft")
        task_id = resp["task"]["id"]
        task = self.orch.tasks[task_id]

        initial_hash = task.params["approval_hash"]

        # Perform structured edit
        updated = self.orch.edit_pending_draft(
            task_id=task_id,
            recipient="bob@domain.com",
            subject="Updated Subject",
            body="Completely new body text",
            sender_account="me@work.com",
            attachments=["invoice.pdf"],
        )

        self.assertTrue(updated["ok"])
        self.assertEqual(task.params["recipient"], "bob@domain.com")
        self.assertEqual(task.params["subject"], "Updated Subject")
        self.assertEqual(task.params["body"], "Completely new body text")
        self.assertEqual(task.params["attachments"], ["invoice.pdf"])
        self.assertEqual(task.params["sender_account"], "me@work.com")

        # Hash must have changed to bind to the new content
        new_hash = task.params["approval_hash"]
        self.assertNotEqual(initial_hash, new_hash)
        expected_hash = EmailDraft(
            recipient=task.params["recipient"],
            subject=task.params["subject"],
            body=task.params["body"],
            sender_account=task.params["sender_account"],
            attachments=task.params["attachments"],
        ).compute_hash()
        self.assertEqual(new_hash, expected_hash)

    def test_rejection_of_tampered_approval_hash(self):
        resp = self.orch.chat("send email to charlie@domain.com saying Hello")
        task_id = resp["task"]["id"]
        task = self.orch.tasks[task_id]

        # Silently tamper with the draft body without updating approval_hash
        task.params["formatted_body"] = "MALICIOUS INJECTED CONTENT"
        task.params["body"] = "MALICIOUS INJECTED CONTENT"

        # Attempting to approve must trigger hash verification failure
        res = self.orch.approve(task_id, True)

        self.assertEqual(res["status"], "waiting_approval")
        self.assertIn("Approval invalidated", res["error"])
        # Verify audit trail recorded the invalidation
        event_types = [e["type"] for e in res["auditTrail"]]
        self.assertIn("approval_invalidated", event_types)

    def test_sending_without_approval_is_blocked(self):
        resp = self.orch.chat("send email to dave@domain.com saying Test")
        task_id = resp["task"]["id"]

        # Reject approval
        res = self.orch.approve(task_id, False)
        self.assertEqual(res["status"], "canceled")
        self.assertIn("rejected", res["result"].lower())


class TestGmailProviderExtensions(unittest.TestCase):
    """Verifies Gmail OAuth helpers, thread fetching, and token handling."""

    def setUp(self):
        self.provider = GmailProvider(
            client_id="test-client-id.apps.googleusercontent.com",
            client_secret="test-client-secret",
            access_token="mock-token-123",
        )

    def test_authorization_url_generation(self):
        url = self.provider.get_authorization_url(
            redirect_uri="http://127.0.0.1:8765/email/auth/callback",
            state="custom-state-123",
        )
        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth", url)
        self.assertIn("client_id=test-client-id.apps.googleusercontent.com", url)
        self.assertIn("state=custom-state-123", url)
        self.assertIn("gmail.compose", url)
        self.assertIn("gmail.send", url)

    def test_missing_credentials_raises_error(self):
        p = GmailProvider(client_id="", client_secret="")
        p.client_id = ""  # override any env var
        with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}):
            with self.assertRaises(ValueError):
                p.get_authorization_url(redirect_uri="http://127.0.0.1:8765")

    @patch("urllib.request.urlopen")
    def test_exchange_code_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = self.provider.exchange_code(
            code="auth-code-xyz",
            redirect_uri="http://127.0.0.1:8765/email/auth/callback",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["access_token"], "new-access-token")
        self.assertEqual(self.provider.access_token, "new-access-token")

    def test_disconnect_removes_token(self):
        self.provider.access_token = "some-token"
        self.provider.refresh_token = "some-refresh"
        res = self.provider.disconnect()
        self.assertTrue(res["ok"])
        self.assertIsNone(self.provider.access_token)
        self.assertIsNone(self.provider.refresh_token)

    @patch("urllib.request.urlopen")
    def test_get_thread_retrieval(self, mock_urlopen):
        mock_thread_data = {
            "id": "thread-123",
            "messages": [
                {
                    "id": "msg-1",
                    "snippet": "Can we meet tomorrow?",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Prof. Smith <smith@univ.edu>"},
                            {"name": "Subject", "value": "Meeting tomorrow"},
                            {"name": "Date", "value": "2026-10-20"},
                        ],
                    },
                }
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_thread_data).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        thread = self.provider.get_thread("thread-123")
        self.assertTrue(thread["ok"])
        self.assertEqual(thread["thread_id"], "thread-123")
        self.assertEqual(len(thread["messages"]), 1)
        self.assertEqual(thread["messages"][0]["sender"], "Prof. Smith <smith@univ.edu>")


class TestServerEndpoints(unittest.TestCase):
    """Verifies FastAPI endpoints for task draft editing, accounts, and auth."""

    def setUp(self):
        self.client = TestClient(app)

    def test_get_email_accounts_endpoint(self):
        res = self.client.get("/email/accounts")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("accounts", data)

    def test_post_edit_task_draft(self):
        # Create a task via /chat endpoint
        chat_res = self.client.post("/chat", json={"message": "send email to test@domain.com saying Hello"})
        self.assertEqual(chat_res.status_code, 200)
        task = chat_res.json()["task"]
        task_id = task["id"]
        self.assertEqual(task["status"], "waiting_approval")

        # Call edit draft endpoint
        edit_payload = {
            "recipient": "new-recipient@domain.com",
            "subject": "Edited Subject Line",
            "body": "Edited message body text",
            "attachments": ["report.pdf"],
        }
        edit_res = self.client.post(f"/tasks/{task_id}/edit", json=edit_payload)
        self.assertEqual(edit_res.status_code, 200)

        updated_resp = edit_res.json()
        self.assertTrue(updated_resp["ok"])
        updated_task = updated_resp["task"]
        self.assertEqual(updated_task["params"]["recipient"], "new-recipient@domain.com")
        self.assertEqual(updated_task["params"]["subject"], "Edited Subject Line")
        self.assertEqual(updated_task["params"]["body"], "Edited message body text")
        self.assertEqual(updated_task["params"]["attachments"], ["report.pdf"])

    def test_post_edit_nonexistent_task(self):
        res = self.client.post(
            "/tasks/nonexistent-id-xyz/edit",
            json={"recipient": "a@b.com", "subject": "S", "body": "B"},
        )
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
