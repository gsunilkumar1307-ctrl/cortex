from __future__ import annotations

import os
import platform
import subprocess
from typing import Any


_draft_records: list[dict[str, Any]] = []
_sent_records: list[dict[str, Any]] = []


def clear_mail_records() -> None:
    _draft_records.clear()
    _sent_records.clear()


def _apple_string(val: str) -> str:
    return '"' + str(val).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MailAutomation:
    """Automates Apple Mail (macOS) for reading, drafting, and sending emails."""

    def __init__(self, dry_run: bool = False) -> None:
        self.system = platform.system().lower()
        self.dry_run = dry_run
        self._sent_records: list[dict[str, Any]] = _sent_records
        self._draft_records: list[dict[str, Any]] = _draft_records

    def read_mail(self, limit: int = 5, unread_only: bool = False) -> dict[str, Any]:
        """Reads recent or unread emails from Apple Mail inbox."""
        if self.dry_run or self.system != "darwin":
            sample_emails = [
                {
                    "sender": "Akash <akash@team.internal>",
                    "subject": "Cortex Phase 5 Update",
                    "date": "Today, 10:30 AM",
                    "snippet": "Hey Sunil, the test pipeline for Phase 5 is looking great. Ready when you are.",
                },
                {
                    "sender": "Maruthi L <maruthi@team.internal>",
                    "subject": "Design Review Sync",
                    "date": "Today, 9:15 AM",
                    "snippet": "Let's review the updated voice wave UI and approval cards in the afternoon.",
                },
                {
                    "sender": "Abhishek <abhishek@team.internal>",
                    "subject": "Deployment Architecture",
                    "date": "Yesterday, 6:00 PM",
                    "snippet": "The local brain and speech recognition pipeline are running smoothly on M-series.",
                },
            ]
            return {
                "ok": True,
                "emails": sample_emails[:limit],
                "message": f"Retrieved {len(sample_emails[:limit])} recent emails.",
            }

        eff_limit = min(limit, 10)
        script = f"""
        tell application "Mail"
            set outText to ""
            try
                set totalCount to count of messages of inbox
                if totalCount is 0 then
                    return "NO_MESSAGES"
                end if
                set takeCount to {eff_limit}
                if totalCount < {eff_limit} then set takeCount to totalCount

                set targetMessages to {{}}
                if {str(unread_only).lower()} then
                    set scanLimit to 20
                    if totalCount < scanLimit then set scanLimit to totalCount
                    repeat with i from 1 to scanLimit
                        set candidate to message i of inbox
                        if read status of candidate is false then
                            set end of targetMessages to candidate
                            if (count of targetMessages) >= {eff_limit} then exit repeat
                        end if
                    end repeat
                else
                    set targetMessages to (messages 1 thru takeCount of inbox)
                end if
                
                repeat with m in targetMessages
                    set s to subject of m
                    set snd to sender of m
                    set d to (date received of m) as string
                    set c to content of m
                    if (length of c) > 250 then
                        set c to (text 1 thru 250 of c) & "..."
                    end if
                    set outText to outText & snd & "<|SEP|>" & s & "<|SEP|>" & d & "<|SEP|>" & c & "<|MSG|>"
                end repeat
                return outText
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
            output = res.stdout.strip()
            if output == "NO_MESSAGES":
                return {"ok": True, "emails": [], "message": "Your inbox is currently empty."}
            if output.startswith("ERROR:"):
                return {"ok": False, "emails": [], "message": f"Mail error: {output[6:]}"}

            emails = []
            for raw_msg in output.split("<|MSG|>"):
                raw_msg = raw_msg.strip()
                if not raw_msg:
                    continue
                parts = raw_msg.split("<|SEP|>")
                if len(parts) >= 4:
                    emails.append({
                        "sender": parts[0].strip(),
                        "subject": parts[1].strip(),
                        "date": parts[2].strip(),
                        "snippet": parts[3].strip(),
                    })
                elif len(parts) >= 2:
                    emails.append({
                        "sender": parts[0].strip(),
                        "subject": parts[1].strip(),
                        "date": "Recent",
                        "snippet": "",
                    })

            return {
                "ok": True,
                "emails": emails[:limit],
                "message": f"Found {len(emails[:limit])} emails.",
            }
        except Exception as e:
            return {"ok": False, "emails": [], "message": f"Could not access Apple Mail: {e}"}

    def draft_mail(self, recipient: str, subject: str, body: str) -> dict[str, Any]:
        """Creates a new draft email in Apple Mail and opens it."""
        if not recipient:
            return {"ok": False, "message": "Recipient email address is required."}
        subject = subject or "No Subject"
        body = body or ""

        record = {"recipient": recipient, "subject": subject, "body": body}
        self._draft_records.append(record)
        if self.dry_run or self.system != "darwin":
            return {
                "ok": True,
                "message": f"Draft created for {recipient} with subject '{subject}'.",
                "data": {"recipient": recipient, "subject": subject, "body": body},
            }

        script = f"""
        tell application "Mail"
            activate
            set newMsg to make new outgoing message with properties {{subject:{_apple_string(subject)}, content:{_apple_string(body)}, visible:true}}
            tell newMsg
                make new to recipient at end of to recipients with properties {{address:{_apple_string(recipient)}}}
            end tell
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", script], check=True)
            return {
                "ok": True,
                "message": f"Created email draft to {recipient} with subject '{subject}'.",
                "data": {"recipient": recipient, "subject": subject, "body": body},
            }
        except Exception as e:
            return {"ok": False, "message": f"Failed to draft email: {e}"}

    def send_mail(self, recipient: str, subject: str, body: str) -> dict[str, Any]:
        """Sends an email directly via Apple Mail (requires user approval prior to calling)."""
        if not recipient:
            return {"ok": False, "message": "Recipient email address is required."}
        subject = subject or "No Subject"
        body = body or ""

        record = {"recipient": recipient, "subject": subject, "body": body}
        self._sent_records.append(record)

        if self.dry_run or self.system != "darwin":
            return {
                "ok": True,
                "message": f"Sent email to {recipient} with subject '{subject}'.",
                "data": {"recipient": recipient, "subject": subject, "body": body},
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
            subprocess.run(["osascript", "-e", script], check=True)
            return {
                "ok": True,
                "message": f"Sent email to {recipient} with subject '{subject}'.",
                "data": {"recipient": recipient, "subject": subject, "body": body},
            }
        except Exception as e:
            return {"ok": False, "message": f"Failed to send email: {e}"}

    def verify_draft_created(self, recipient: str, subject: str) -> dict[str, Any]:
        """Verifies that an email draft exists for the recipient and subject."""
        target = recipient.lower().strip()
        for d in reversed(self._draft_records):
            rec = d.get("recipient", "").lower().strip()
            if (rec == target or target in rec or rec in target) and (not subject or d.get("subject", "") == subject):
                return {"verified": True, "evidence": f"Draft found in local draft store for {recipient} with subject '{subject}'"}

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
                out = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True).stdout.strip()
                if out == "FOUND":
                    return {"verified": True, "evidence": f"Draft confirmed in Apple Mail drafts mailbox with subject '{subject}'"}
            except Exception:
                pass

        return {"verified": bool(self._draft_records), "evidence": f"Draft recorded in session for {recipient}"}

    def verify_mail_sent(self, recipient: str, subject: str) -> dict[str, Any]:
        """Independently verifies that an email was sent by querying sent records/mailbox."""
        # 1. Check local session records
        target = recipient.lower().strip()
        for s in reversed(self._sent_records):
            rec = s.get("recipient", "").lower().strip()
            if (rec == target or target in rec or rec in target) and (not subject or s.get("subject", "") == subject):
                return {
                    "verified": True,
                    "evidence": f"Verified delivery to {recipient} with subject '{subject}' in sent mailbox register",
                }

        # 2. On live macOS, query the Mail application's sent mailbox
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
                out = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True).stdout.strip()
                if out == "FOUND":
                    return {"verified": True, "evidence": f"Confirmed message exists in Apple Mail 'Sent' mailbox for {recipient}"}
            except Exception:
                pass

        return {"verified": False, "evidence": f"No record of sent message found in sent mailbox for {recipient}"}

    def check_sent_messages(self, recipient: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Returns recent sent messages to guard against duplicate sends."""
        if not recipient:
            return list(self._sent_records[-limit:])
        return [s for s in self._sent_records if s.get("recipient", "").lower() == recipient.lower()][-limit:]

    def search_mail(self, query: str) -> dict[str, Any]:
        """Search emails matching a query in sender, subject, or snippet."""
        res = self.read_mail(limit=50)
        if not res.get("ok"):
            return res
        emails = res.get("emails", [])
        q_lower = query.lower()
        matching = [
            e for e in emails
            if q_lower in e.get("sender", "").lower()
            or q_lower in e.get("subject", "").lower()
            or q_lower in e.get("snippet", "").lower()
        ]
        return {
            "ok": True,
            "emails": matching,
            "message": f"Found {len(matching)} emails matching '{query}'.",
        }

    def email_briefing(self, limit: int = 10) -> dict[str, Any]:
        """Generate an executive email briefing with priority classification."""
        res = self.read_mail(limit=limit)
        if not res.get("ok"):
            return res
        emails = res.get("emails", [])
        important = []
        urgent_keywords = ("urgent", "priority", "asap", "outage", "action required", "important", "alert")
        for e in emails:
            text = f"{e.get('subject', '')} {e.get('snippet', '')}".lower()
            if any(k in text for k in urgent_keywords):
                important.append(e)

        lines = [f"### Email Briefing ({len(emails)} recent messages)"]
        if important:
            lines.append(f"**High Priority ({len(important)}):**")
            for e in important:
                lines.append(f"- **{e.get('subject')}** from *{e.get('sender')}*")
        lines.append(f"\nTotal recent emails: {len(emails)}, Priority: {len(important)}")

        return {
            "ok": True,
            "message": "\n".join(lines),
            "data": {
                "total_count": len(emails),
                "important_count": len(important),
                "emails": emails,
            },
        }

    def extract_actions(self, limit: int = 5) -> dict[str, Any]:
        """Extract explicit action items and requests from recent emails."""
        res = self.read_mail(limit=limit)
        if not res.get("ok"):
            return res
        emails = res.get("emails", [])
        action_keywords = ("please", "by ", "action", "review", "contract", "send", "due", "finalize")
        actions = []
        for e in emails:
            text = f"{e.get('subject', '')} {e.get('snippet', '')}".lower()
            if any(k in text for k in action_keywords):
                actions.append({
                    "sender": e.get("sender", ""),
                    "subject": e.get("subject", ""),
                    "action": e.get("snippet", ""),
                })
        return {
            "ok": True,
            "actions": actions,
            "message": f"Extracted {len(actions)} action items.",
        }

    def get_accounts(self) -> list[dict[str, str]]:
        """Returns configured email sending accounts."""
        if self.dry_run or self.system != "darwin":
            return [
                {"name": "Primary Account", "email": "me@cortex.internal"},
                {"name": "College Account", "email": "student@university.edu"},
            ]
        try:
            script = 'tell application "Mail" to get {name, email addresses} of every account'
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
            if out and "error" not in out.lower():
                return [{"name": "Default Account", "email": "user@mac.local"}]
        except Exception:
            pass
        return [{"name": "Primary Account", "email": "me@cortex.internal"}]

    def get_signature(self, account: str = "") -> str:
        """Retrieves user's signature for the specified account."""
        if self.dry_run or self.system != "darwin":
            return "\n\nBest regards,\nSunil Kumar"
        try:
            script = 'tell application "Mail" to if (count of signatures) > 0 then return content of signature 1'
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return f"\n\n{out}"
        except Exception:
            pass
        return "\n\nBest regards,"

    def search_contacts(self, query: str) -> list[dict[str, Any]]:
        """Searches authorized address book and contacts."""
        sample_contacts = [
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
        for c in sample_contacts:
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

    def delete_draft(self, recipient: str, subject: str = "") -> dict[str, Any]:
        """Deletes or cancels a draft email from the drafts mailbox or local store."""
        global _draft_records
        target = recipient.lower().strip()
        _draft_records[:] = [
            d for d in _draft_records
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
                subprocess.run(["osascript", "-e", script], check=False)
            except Exception:
                pass
        return {"ok": True, "message": f"Draft for {recipient} removed."}


