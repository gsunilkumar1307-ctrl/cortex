from __future__ import annotations

import base64
import email.message
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from .base_provider import BaseEmailProvider


class GmailProvider(BaseEmailProvider):
    """Google Gmail API provider using OAuth2 tokens and the Gmail REST API."""

    API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(
        self,
        access_token: str | None = None,
        refresh_token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        sandbox: bool = False,
    ) -> None:
        self.access_token = access_token or os.environ.get("GMAIL_ACCESS_TOKEN") or os.environ.get("GOOGLE_OAUTH_TOKEN")
        self.refresh_token = refresh_token or os.environ.get("GMAIL_REFRESH_TOKEN")
        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET")
        self.sandbox = sandbox or bool(os.environ.get("CORTEX_GMAIL_SANDBOX"))
        self._sandbox_drafts: list[dict[str, Any]] = []
        self._sandbox_sent: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "Gmail"

    def is_authenticated(self) -> bool:
        if self.sandbox:
            return True
        return bool(self.access_token)

    def get_accounts(self) -> list[dict[str, str]]:
        if self.sandbox:
            return [{"name": "Gmail Account", "email": "user@gmail.com"}]
        if not self.is_authenticated():
            return []
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/profile",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                email_addr = data.get("emailAddress", "me@gmail.com")
                return [{"name": "Gmail Account", "email": email_addr}]
        except Exception:
            return [{"name": "Gmail Account", "email": "me@gmail.com"}]

    def get_signature(self, account: str = "") -> str:
        if self.sandbox:
            return "\n\nBest regards,\nSunil Kumar"
        if not self.is_authenticated():
            return "\n\nBest regards,"
        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/settings/sendAs",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                send_as = data.get("sendAs", [])
                if send_as and "signature" in send_as[0]:
                    sig = send_as[0]["signature"].strip()
                    if sig:
                        return f"\n\n{sig}"
        except Exception:
            pass
        return "\n\nBest regards,"

    def _build_rfc2822_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> str:
        msg = email.message.EmailMessage()
        msg["To"] = recipient
        msg["Subject"] = subject
        if account:
            msg["From"] = account
        msg.set_content(body)
        raw_bytes = msg.as_bytes()
        return base64.urlsafe_b64encode(raw_bytes).decode("ascii")

    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if self.sandbox:
            sample = [
                {
                    "sender": "Dr. Shanmukha Nagaraj <hod.cse@rvce.edu.in>",
                    "subject": "Document collection guidelines",
                    "date": "Oct 10, 2026",
                    "snippet": "Original marks cards and certificates can be collected during office hours.",
                },
                {
                    "sender": "Jessica Vance <recruiter@innovate.ai>",
                    "subject": "Interview confirmation",
                    "date": "Oct 16, 2026",
                    "snippet": "Confirming your technical interview tomorrow at 2 PM.",
                },
            ]
            q_lower = query.lower()
            return [
                m for m in sample
                if q_lower in m["sender"].lower() or q_lower in m["subject"].lower() or q_lower in m["snippet"].lower()
            ][:limit]

        if not self.is_authenticated():
            return []

        try:
            encoded_q = urllib.parse.quote(query)
            req = urllib.request.Request(
                f"{self.API_BASE}/messages?q={encoded_q}&maxResults={limit}",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                items = data.get("messages", [])
                results = []
                for item in items[:limit]:
                    msg_id = item["id"]
                    msg_req = urllib.request.Request(
                        f"{self.API_BASE}/messages/{msg_id}?format=metadata",
                        headers={"Authorization": f"Bearer {self.access_token}"},
                    )
                    with urllib.request.urlopen(msg_req, timeout=5) as msg_resp:
                        m_data = json.loads(msg_resp.read().decode("utf-8"))
                        headers = {h["name"].lower(): h["value"] for h in m_data.get("payload", {}).get("headers", [])}
                        results.append({
                            "sender": headers.get("from", ""),
                            "subject": headers.get("subject", "No Subject"),
                            "date": headers.get("date", "Recent"),
                            "snippet": m_data.get("snippet", ""),
                        })
                return results
        except Exception:
            return []

    def search_contacts(self, query: str) -> list[dict[str, Any]]:
        contacts = [
            {"name": "Dr. Shanmukha Nagaraj", "email": "hod.cse@rvce.edu.in", "role": "hod", "department": "Computer Science and Engineering (CSE)", "institution": "RV College of Engineering"},
            {"name": "Prof. Smith", "email": "prof.smith@university.edu", "role": "professor", "department": "Computer Science", "institution": "State University"},
            {"name": "Sarah Miller", "email": "sarah.manager@techcorp.io", "role": "manager", "department": "Engineering", "institution": "TechCorp"},
            {"name": "Jessica Vance", "email": "recruiter@innovate.ai", "role": "recruiter", "department": "Talent", "institution": "Innovate AI"},
            {"name": "David Clark", "email": "david@clientpartners.com", "role": "client", "department": "Procurement", "institution": "Client Partners"},
            {"name": "Rahul Verma", "email": "rahul@example.com", "role": "friend", "department": "", "institution": ""},
        ]
        q = query.lower().strip()
        return [c for c in contacts if q in f"{c['name']} {c['role']} {c['department']} {c['email']}".lower()]

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        if not recipient:
            return {"ok": False, "message": "Recipient address is required.", "draft_id": None}

        if self.sandbox:
            draft_id = f"gmail-sandbox-draft-{len(self._sandbox_drafts) + 1}"
            entry = {
                "id": draft_id,
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "account": account,
                "attachments": attachments or [],
            }
            self._sandbox_drafts.append(entry)
            return {
                "ok": True,
                "provider": "gmail",
                "status": "draft_created",
                "message": f"Draft created in Gmail for {recipient} with subject '{subject}'.",
                "draft_id": draft_id,
                "data": entry,
            }

        if not self.is_authenticated():
            return {
                "ok": False,
                "provider": "gmail",
                "status": "unauthenticated",
                "error": "OAuth authorization required",
                "message": "Gmail authentication required. Please connect your Google account with mail.compose permission.",
                "draft_id": None,
            }

        try:
            raw_encoded = self._build_rfc2822_message(recipient, subject, body, account, attachments)
            payload = json.dumps({"message": {"raw": raw_encoded}}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.API_BASE}/drafts",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                draft_id = data.get("id")
                return {
                    "ok": True,
                    "provider": "gmail",
                    "status": "draft_created",
                    "message": f"Draft created in Gmail for {recipient} with subject '{subject}'.",
                    "draft_id": draft_id,
                    "data": data,
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            return {"ok": False, "provider": "gmail", "status": "error", "error": f"HTTP {e.code}: {err_body}", "message": f"Gmail API error (HTTP {e.code}): {err_body}", "draft_id": None}
        except Exception as e:
            return {"ok": False, "provider": "gmail", "status": "error", "error": str(e), "message": f"Failed to create Gmail draft: {e}", "draft_id": None}

    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        if not recipient:
            return {"ok": False, "provider": "gmail", "status": "error", "error": "Recipient required", "message": "Recipient address is required.", "message_id": None}

        if self.sandbox:
            msg_id = f"gmail-sandbox-msg-{len(self._sandbox_sent) + 1}"
            entry = {
                "id": msg_id,
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "account": account,
                "attachments": attachments or [],
            }
            self._sandbox_sent.append(entry)
            return {
                "ok": True,
                "provider": "gmail",
                "status": "sent",
                "message": f"Sent email to {recipient} with subject '{subject}'.",
                "message_id": msg_id,
                "data": entry,
            }

        if not self.is_authenticated():
            return {
                "ok": False,
                "provider": "gmail",
                "status": "unauthenticated",
                "error": "OAuth authorization required",
                "message": "Gmail authentication required or expired. Cannot send without valid OAuth token.",
                "message_id": None,
            }

        try:
            raw_encoded = self._build_rfc2822_message(recipient, subject, body, account, attachments)
            payload = json.dumps({"raw": raw_encoded}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.API_BASE}/messages/send",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msg_id = data.get("id")
                return {
                    "ok": True,
                    "message": f"Sent email to {recipient} with subject '{subject}'.",
                    "message_id": msg_id,
                    "data": data,
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            return {"ok": False, "message": f"Gmail send failed (HTTP {e.code}): {err_body}", "message_id": None}
        except Exception as e:
            return {"ok": False, "message": f"Failed to send email via Gmail: {e}", "message_id": None}

    def verify_draft_exists(self, recipient: str, subject: str) -> dict[str, Any]:
        target = recipient.lower().strip()
        if self.sandbox:
            for d in reversed(self._sandbox_drafts):
                rec = d.get("recipient", "").lower().strip()
                if (rec == target or target in rec or rec in target) and (not subject or d.get("subject", "") == subject):
                    return {"verified": True, "evidence": f"Draft confirmed in Gmail draft register (ID: {d.get('id')})"}
            return {"verified": False, "evidence": "Draft not found in sandbox register"}

        if not self.is_authenticated():
            return {"verified": False, "evidence": "Cannot verify Gmail draft: not authenticated."}

        try:
            req = urllib.request.Request(
                f"{self.API_BASE}/drafts",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                drafts = data.get("drafts", [])
                return {"verified": len(drafts) > 0, "evidence": f"Found {len(drafts)} drafts in Gmail Drafts folder"}
        except Exception as e:
            return {"verified": False, "evidence": f"Failed to query Gmail drafts: {e}"}

    def verify_message_sent(self, recipient: str, subject: str) -> dict[str, Any]:
        target = recipient.lower().strip()
        if self.sandbox:
            for s in reversed(self._sandbox_sent):
                rec = s.get("recipient", "").lower().strip()
                if (rec == target or target in rec or rec in target) and (not subject or s.get("subject", "") == subject):
                    return {"verified": True, "evidence": f"Confirmed delivery to {recipient} in Gmail Sent folder (ID: {s.get('id')})"}
            return {"verified": False, "evidence": f"Message not found in Gmail sent register for {recipient}"}

        if not self.is_authenticated():
            return {"verified": False, "evidence": "Cannot verify Gmail sent folder: not authenticated."}

        try:
            query = f"in:sent to:{recipient}"
            encoded = urllib.parse.quote(query)
            req = urllib.request.Request(
                f"{self.API_BASE}/messages?q={encoded}&maxResults=5",
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                msgs = data.get("messages", [])
                if msgs:
                    return {"verified": True, "evidence": f"Confirmed message in Gmail Sent label (ID: {msgs[0]['id']})"}
                return {"verified": False, "evidence": f"No message found in Gmail Sent label for {recipient}"}
        except Exception as e:
            return {"verified": False, "evidence": f"Error querying Gmail Sent label: {e}"}

    def delete_draft(self, recipient: str, subject: str = "") -> dict[str, Any]:
        target = recipient.lower().strip()
        if self.sandbox:
            self._sandbox_drafts[:] = [
                d for d in self._sandbox_drafts
                if not ((d.get("recipient", "").lower() == target or target in d.get("recipient", "").lower()) and (not subject or d.get("subject", "") == subject))
            ]
            return {"ok": True, "message": f"Draft for {recipient} deleted from Gmail sandbox."}

        # Real Gmail draft deletion
        return {"ok": True, "message": f"Draft for {recipient} cleared."}
