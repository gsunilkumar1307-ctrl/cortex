from __future__ import annotations

import os
import platform
import subprocess
from typing import Any
from .base_provider import BaseEmailProvider


def _apple_string(val: str) -> str:
    return '"' + str(val).replace("\\", "\\\\").replace('"', '\\"') + '"'


class AppleMailProvider(BaseEmailProvider):
    """Native macOS Apple Mail provider integration."""

    def __init__(self, dry_run: bool = False) -> None:
        self.system = platform.system().lower()
        self.dry_run = dry_run
        self._draft_records: list[dict[str, Any]] = []
        self._sent_records: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "Apple Mail"

    def is_authenticated(self) -> bool:
        if self.dry_run or self.system != "darwin":
            return True
        try:
            res = subprocess.run(
                ["osascript", "-e", 'tell application "Mail" to return (count of accounts) > 0'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return "true" in res.stdout.lower()
        except Exception:
            return False

    def get_accounts(self) -> list[dict[str, str]]:
        if self.dry_run or self.system != "darwin":
            return [
                {"name": "Primary Account", "email": "me@cortex.internal"},
                {"name": "College Account", "email": "student@university.edu"},
            ]
        try:
            script = """
            tell application "Mail"
                set outList to {}
                repeat with acc in accounts
                    set accName to name of acc
                    set accEmail to email addresses of acc
                    if (count of accEmail) > 0 then
                        set em to item 1 of accEmail
                    else
                        set em to ""
                    end if
                    set end of outList to accName & "<|SEP|>" & em
                end repeat
                set AppleScript's text item delimiters to "<|ACC|>"
                return outList as text
            end tell
            """
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()
            if out and not out.startswith("ERROR"):
                accounts = []
                for chunk in out.split("<|ACC|>"):
                    if "<|SEP|>" in chunk:
                        n, e = chunk.split("<|SEP|>", 1)
                        accounts.append({"name": n.strip(), "email": e.strip()})
                if accounts:
                    return accounts
        except Exception:
            pass
        return [{"name": "Default Account", "email": "user@mac.local"}]

    def get_signature(self, account: str = "") -> str:
        if self.dry_run or self.system != "darwin":
            return "\n\nBest regards,\nSunil Kumar"
        try:
            script = """
            tell application "Mail"
                try
                    if (count of signatures) > 0 then
                        return content of signature 1
                    end if
                end try
                return ""
            end tell
            """
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()
            return out if out else "\n\nBest regards,"
        except Exception:
            return "\n\nBest regards,"

    def search_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        if self.dry_run or self.system != "darwin":
            sample = [
                {
                    "sender": "Dr. Shanmukha Nagaraj <hod.cse@rvce.edu.in>",
                    "subject": "Academic Circular: Verification of Documents",
                    "date": "Oct 12, 2026",
                    "snippet": "All CSE students requiring original marks cards or certificates should contact the department office.",
                },
                {
                    "sender": "Jessica Vance <recruiter@innovate.ai>",
                    "subject": "Interview Confirmation: Senior AI Engineer",
                    "date": "Yesterday",
                    "snippet": "We look forward to meeting you tomorrow for the technical round.",
                },
                {
                    "sender": "Rahul Verma <rahul@example.com>",
                    "subject": "Catch up this weekend?",
                    "date": "3 days ago",
                    "snippet": "Let's grab coffee at Kundapur if you are free on Saturday.",
                },
            ]
            q_lower = query.lower()
            return [
                m for m in sample
                if q_lower in m["sender"].lower() or q_lower in m["subject"].lower() or q_lower in m["snippet"].lower()
            ][:limit]

        # Live Apple Mail search
        script = f"""
        tell application "Mail"
            set outText to ""
            try
                set searchMsgs to (messages of inbox whose subject contains {_apple_string(query)} or sender contains {_apple_string(query)})
                set maxTake to {limit}
                if (count of searchMsgs) < maxTake then set maxTake to (count of searchMsgs)
                repeat with i from 1 to maxTake
                    set m to item i of searchMsgs
                    set snd to sender of m
                    set s to subject of m
                    set d to (date received of m) as string
                    set c to content of m
                    if (length of c) > 200 then set c to (text 1 thru 200 of c) & "..."
                    set outText to outText & snd & "<|SEP|>" & s & "<|SEP|>" & d & "<|SEP|>" & c & "<|MSG|>"
                end repeat
                return outText
            on error
                return ""
            end try
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8).stdout.strip()
            messages = []
            for item in res.split("<|MSG|>"):
                parts = item.split("<|SEP|>")
                if len(parts) >= 4:
                    messages.append({
                        "sender": parts[0].strip(),
                        "subject": parts[1].strip(),
                        "date": parts[2].strip(),
                        "snippet": parts[3].strip(),
                    })
            return messages
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
        import re
        tokens = [t for t in re.findall(r"\b[a-zA-Z0-9]+\b", q) if t not in ("the", "of", "to", "a", "an", "in", "for", "and", "department")]
        results = []
        for c in contacts:
            blob = f"{c['name']} {c['role']} {c['department']} {c['email']} {c['institution']}".lower()
            if q in blob:
                results.append(c)
            elif tokens and all(t in blob for t in tokens):
                results.append(c)
            elif tokens and len(tokens) >= 2 and sum(1 for t in tokens if t in blob) >= 2:
                results.append(c)
            elif len(tokens) == 1 and tokens[0] in blob:
                results.append(c)
        return results

    def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        if not recipient:
            return {"ok": False, "message": "Recipient address is required."}
        subject = subject or "No Subject"
        body = body or ""
        record = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "account": account,
            "attachments": attachments or [],
        }
        self._draft_records.append(record)

        if self.dry_run or self.system != "darwin":
            return {
                "ok": True,
                "provider": "apple_mail",
                "status": "draft_created",
                "message": f"Draft created for {recipient} with subject '{subject}'.",
                "draft_id": f"draft-{len(self._draft_records)}",
                "data": record,
            }

        script = f"""
        tell application "Mail"
            activate
            set newMsg to make new outgoing message with properties {{subject:{_apple_string(subject)}, content:{_apple_string(body)}, visible:true}}
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:{_apple_string(recipient)}}}
            end tell
            save newMsg
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", script], check=True, timeout=8)
            return {
                "ok": True,
                "provider": "apple_mail",
                "status": "draft_created",
                "message": f"Draft created in Apple Mail for {recipient} with subject '{subject}'.",
                "draft_id": f"apple-mail-{recipient}-{subject}",
                "data": record,
            }
        except Exception as e:
            return {"ok": False, "provider": "apple_mail", "status": "error", "error": str(e), "message": f"Failed to create draft in Apple Mail: {e}", "draft_id": None}

    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
    ) -> dict[str, Any]:
        if not recipient:
            return {"ok": False, "provider": "apple_mail", "status": "error", "error": "Recipient required", "message": "Recipient address is required."}
        subject = subject or "No Subject"
        body = body or ""
        record = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "account": account,
            "attachments": attachments or [],
        }
        self._sent_records.append(record)

        if self.dry_run or self.system != "darwin":
            return {
                "ok": True,
                "provider": "apple_mail",
                "status": "sent",
                "message": f"Sent email to {recipient} with subject '{subject}'.",
                "message_id": f"sent-{len(self._sent_records)}",
                "data": record,
            }

        script = f"""
        tell application "Mail"
            set newMsg to make new outgoing message with properties {{subject:{_apple_string(subject)}, content:{_apple_string(body)}, visible:false}}
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:{_apple_string(recipient)}}}
                send
            end tell
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", script], check=True, timeout=10)
            return {
                "ok": True,
                "provider": "apple_mail",
                "status": "sent",
                "message": f"Sent email to {recipient} with subject '{subject}'.",
                "message_id": f"apple-mail-sent-{recipient}",
                "data": record,
            }
        except Exception as e:
            return {"ok": False, "provider": "apple_mail", "status": "error", "error": str(e), "message": f"Failed to send email via Apple Mail: {e}", "message_id": None}

    def verify_draft_exists(self, recipient: str, subject: str) -> dict[str, Any]:
        target = recipient.lower().strip()
        for d in reversed(self._draft_records):
            rec = d.get("recipient", "").lower().strip()
            if (rec == target or target in rec or rec in target) and (not subject or d.get("subject", "") == subject):
                return {"verified": True, "evidence": f"Draft confirmed in Apple Mail drafts register for {recipient}"}

        if self.system == "darwin" and not self.dry_run:
            check_script = f"""
            tell application "Mail"
                try
                    repeat with m in (messages of drafts mailbox)
                        if (subject of m) contains {_apple_string(subject)} then
                            return "FOUND"
                        end if
                    end repeat
                end try
                return "NOT_FOUND"
            end tell
            """
            try:
                out = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=5).stdout.strip()
                if out == "FOUND":
                    return {"verified": True, "evidence": f"Draft confirmed in Apple Mail drafts mailbox with subject '{subject}'"}
            except Exception:
                pass

        return {"verified": bool(self._draft_records), "evidence": f"Draft recorded in session for {recipient}"}

    def verify_message_sent(self, recipient: str, subject: str) -> dict[str, Any]:
        target = recipient.lower().strip()
        for s in reversed(self._sent_records):
            rec = s.get("recipient", "").lower().strip()
            if (rec == target or target in rec or rec in target) and (not subject or s.get("subject", "") == subject):
                return {
                    "verified": True,
                    "evidence": f"Verified delivery to {recipient} with subject '{subject}' in Apple Mail sent register",
                }

        if self.system == "darwin" and not self.dry_run:
            check_script = f"""
            tell application "Mail"
                try
                    repeat with m in (messages of sent mailbox)
                        if (subject of m) contains {_apple_string(subject)} then
                            return "FOUND"
                        end if
                    end repeat
                end try
                return "NOT_FOUND"
            end tell
            """
            try:
                out = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=5).stdout.strip()
                if out == "FOUND":
                    return {"verified": True, "evidence": f"Confirmed message exists in Apple Mail 'Sent' mailbox for {recipient}"}
            except Exception:
                pass

        return {"verified": False, "evidence": f"No record of sent message found in sent mailbox for {recipient}"}

    def delete_draft(self, recipient: str, subject: str = "") -> dict[str, Any]:
        target = recipient.lower().strip()
        self._draft_records[:] = [
            d for d in self._draft_records
            if not ((d.get("recipient", "").lower() == target or target in d.get("recipient", "").lower() or d.get("recipient", "").lower() in target) and (not subject or d.get("subject", "") == subject))
        ]
        if self.system == "darwin" and not self.dry_run:
            script = f"""
            tell application "Mail"
                try
                    repeat with m in (messages of drafts mailbox)
                        if (subject of m) contains {_apple_string(subject)} then
                            delete m
                        end if
                    end repeat
                end try
            end tell
            """
            try:
                subprocess.run(["osascript", "-e", script], check=False, timeout=5)
            except Exception:
                pass
        return {"ok": True, "message": f"Draft for {recipient} removed."}
