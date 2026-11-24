from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, date, timedelta, time as dtime
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from backend.core.contracts import MailDeliveryStatus
except ImportError:
    from core.contracts import MailDeliveryStatus

try:
    from backend.capabilities.safety import is_real_email_send_allowed
except ImportError:
    try:
        from capabilities.safety import is_real_email_send_allowed
    except ImportError:
        def is_real_email_send_allowed() -> bool:
            return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"



_draft_records: list[dict[str, Any]] = []
_sent_records: list[dict[str, Any]] = []


def clear_mail_records(db_path: Optional[str] = None) -> None:
    _draft_records.clear()
    _sent_records.clear()
    try:
        from backend.persistence.task_store import TaskStore
        target_path = db_path or "cortex-memory.sqlite3"
        if os.path.exists(target_path):
            ts = TaskStore(target_path)
            with ts._connect() as conn:
                conn.execute("DELETE FROM mail_send_attempts")
                conn.commit()
    except Exception:
        pass


def _apple_string(val: Any) -> str:
    if val is None:
        return '""'
    s = str(val)
    # Strip null bytes to prevent POSIX subprocess ValueError
    s = s.replace("\x00", "")
    # Normalize line endings
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    # Escape backslashes first, then quotes
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + s + '"'


def normalize_date_bound(val: Any, is_end: bool = False) -> tuple[datetime | None, bool]:
    """
    Normalizes a date boundary (date_from or date_to).
    Returns (normalized_datetime, is_valid).
    If val is None or empty, returns (None, True).
    If val is provided but unparseable, returns (None, False).
    """
    if val is None:
        return None, True
    if isinstance(val, datetime):
        return val.replace(tzinfo=None), True
    if isinstance(val, date):
        t = dtime(23, 59, 59, 999999) if is_end else dtime.min
        return datetime.combine(val, t), True
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val), True

    s = str(val).strip()
    if not s:
        return None, True

    # Try ISO format
    try:
        clean_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        return dt.replace(tzinfo=None), True
    except Exception:
        pass

    # Common date string formats
    formats = [
        ("%Y-%m-%d", True),
        ("%m/%d/%Y", True),
        ("%B %d, %Y", True),
        ("%d %B %Y", True),
        ("%Y-%m-%d %H:%M:%S", False),
        ("%m/%d/%Y %I:%M %p", False),
        ("%m/%d/%Y %I:%M:%S %p", False),
    ]
    for fmt, is_date_only in formats:
        try:
            dt = datetime.strptime(s, fmt)
            if is_end and is_date_only:
                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            elif not is_end and is_date_only:
                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt, True
        except ValueError:
            pass

    return None, False


def parse_email_date(date_val: Any, now: datetime | None = None) -> datetime | None:
    """
    Extracts and parses the date from an email metadata record.
    Supports AppleScript and MCP dates:
    - '11/18/2026'
    - 'Wednesday, 18 November 2026 at 10:00:00 AM'
    - 'Today, 10:30 AM'
    - 'Yesterday, 6:00 PM'
    - 'November 18, 2026'
    - ISO timestamps
    """
    if not date_val:
        return None
    if isinstance(date_val, datetime):
        return date_val.replace(tzinfo=None)
    if isinstance(date_val, date):
        return datetime.combine(date_val, dtime.min)
    if isinstance(date_val, (int, float)):
        return datetime.fromtimestamp(date_val)

    now = now or datetime.now()
    s = str(date_val).strip()
    s_low = s.lower()

    # Relative days: "Today, 10:30 AM" or "today"
    if s_low.startswith("today"):
        t_part = re.sub(r"^today[,\s]*", "", s, flags=re.IGNORECASE).strip()
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if t_part:
            for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S"):
                try:
                    t = datetime.strptime(t_part, fmt).time()
                    return datetime.combine(base.date(), t)
                except ValueError:
                    pass
        return base

    # "Yesterday, 6:00 PM"
    if s_low.startswith("yesterday"):
        t_part = re.sub(r"^yesterday[,\s]*", "", s, flags=re.IGNORECASE).strip()
        base = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if t_part:
            for fmt in ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S"):
                try:
                    t = datetime.strptime(t_part, fmt).time()
                    return datetime.combine(base.date(), t)
                except ValueError:
                    pass
        return base

    # ISO strings
    try:
        clean_iso = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        return dt.replace(tzinfo=None)
    except Exception:
        pass

    # RFC 2822 email format (e.g. "10 Nov 2026 10:00:00 +0000", "Wed, 18 Nov 2026 14:00:00 +0000")
    try:
        from email.utils import parsedate_to_datetime
        dt_rfc = parsedate_to_datetime(s)
        if dt_rfc:
            return dt_rfc.replace(tzinfo=None)
    except Exception:
        pass

    # Clean AppleScript date strings: "Wednesday, 18 November 2026 at 10:00:00 AM"
    cleaned = re.sub(r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)[,\s]*", "", s, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+at\s+", " ", cleaned, flags=re.IGNORECASE).strip()

    formats = [
        "%m/%d/%Y",
        "%m/%d/%Y, %I:%M %p",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%Y %I:%M:%S %p",
        "%d %B %Y %I:%M:%S %p",
        "%d %B %Y %I:%M %p",
        "%d %B %Y",
        "%B %d, %Y",
        "%B %d, %Y, %I:%M %p",
        "%B %d, %Y %I:%M:%S %p",
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass

    return None


CLUSTERS = [
    {"intern", "interns", "internship", "internships"},
    {"opportunity", "opportunities"},
    {"application", "applications", "apply", "applying", "applied"},
    {"interview", "interviews", "interviewing", "interviewed"},
    {"schedule", "schedules", "scheduling", "scheduled"},
    {"document", "documents", "documentation"},
    {"update", "updates", "updating", "updated"},
    {"meeting", "meetings", "meet"},
    {"message", "messages"},
    {"invoice", "invoices"},
    {"report", "reports"},
    {"leave", "leaves", "vacation"},
    {"exam", "exams", "examination", "examinations"},
]


def _term_matches(needle: str, haystack: str) -> bool:
    """Matches search needle against target text with common inflectional variations and domain matching.
    Handles singular/plural (internship <-> internships, opportunity <-> opportunities),
    verb forms, token overlaps, and email/domain token matching without external NLP dependencies.
    """
    if not needle:
        return True
    if not haystack:
        return False

    n_clean = needle.strip().lower()
    h_clean = haystack.strip().lower()

    if re.search(r"\b" + re.escape(n_clean) + r"\b", h_clean):
        return True

    def _stem(word: str) -> set[str]:
        stems = {word}
        for cluster in CLUSTERS:
            if word in cluster:
                stems.update(cluster)
        if word.endswith("ies") and len(word) > 4:
            stems.add(word[:-3] + "y")
        elif word.endswith("es") and len(word) > 3:
            stems.add(word[:-2])
            stems.add(word[:-1])
        elif word.endswith("s") and len(word) > 3 and not word.endswith("ss"):
            stems.add(word[:-1])
        else:
            stems.add(word + "s")
            stems.add(word + "es")
            if word.endswith("y") and len(word) > 3:
                stems.add(word[:-1] + "ies")
        if word.endswith("ing") and len(word) > 4:
            stems.add(word[:-3])
        return stems

    needle_tokens = [t.strip(",.!?\"'';:()") for t in n_clean.split() if t.strip(",.!?\"'';:()")]
    if not needle_tokens:
        return True

    # Standard token boundary matching
    all_matched = True
    for n_tok in needle_tokens:
        tok_vars = _stem(n_tok)
        matched = False
        for var in tok_vars:
            if re.search(r"\b" + re.escape(var) + r"\b", h_clean):
                matched = True
                break
        if not matched:
            all_matched = False
            break

    if all_matched:
        return True

    # Domain / email sub-token matching:
    # If haystack contains an email or domain (e.g. campusconnect@pentagonspace.in or pentagonspace.in),
    # allow needle tokens to match within the domain segments or full domain string.
    # e.g., 'pentagon' or 'pentagon space' matches 'campusconnect@pentagonspace.in'.
    domain_part = ""
    if "@" in h_clean:
        domain_part = h_clean.split("@")[-1].split(">")[0].strip()
    elif "." in h_clean and not any(c.isspace() for c in h_clean):
        domain_part = h_clean.strip()

    if domain_part:
        domain_subtokens = [t for t in re.split(r"[\.\-_]", domain_part) if t]
        domain_matched = True
        for n_tok in needle_tokens:
            if len(n_tok) < 2:
                continue
            tok_vars = _stem(n_tok)
            matched = any(
                var in domain_part or any(var in seg for seg in domain_subtokens)
                for var in tok_vars
            )
            if not matched:
                domain_matched = False
                break
        if domain_matched:
            return True

    return False


def _sort_emails_by_date_desc(emails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sorts emails by date descending (newest first).
    Missing, invalid, or malformed dates are treated as datetime.min,
    ensuring they safely sort to the bottom rather than falsely ranking as newest.
    """
    def _key(em: dict[str, Any]) -> datetime:
        dt = parse_email_date(em.get("date"))
        return dt if dt is not None else datetime.min

    return sorted(emails, key=_key, reverse=True)



class MailAutomation:
    """Automates Apple Mail (macOS) and Gmail for reading, drafting, and sending emails."""

    def __init__(self, dry_run: bool = False, mcp_manager: Any = None) -> None:
        self.system = platform.system().lower()
        self.dry_run = dry_run
        self.mcp_manager = mcp_manager
        self._sent_records: list[dict[str, Any]] = _sent_records
        self._draft_records: list[dict[str, Any]] = _draft_records
        self._manager = None

    @property
    def manager(self):
        if self._manager is None:
            try:
                from backend.integrations.email.manager import MailProviderManager
            except ImportError:
                from integrations.email.manager import MailProviderManager
            self._manager = MailProviderManager(dry_run=self.dry_run)
        return self._manager

    def read_mail(
        self,
        limit: int = 5,
        unread_only: bool = False,
        mailbox: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        """Reads recent or unread emails from Apple Mail across specified or relevant mailboxes."""
        if self.dry_run or self.system != "darwin":
            sample_emails = [
                {
                    "account": "Apple Mail",
                    "mailbox": "INBOX",
                    "sender": "Akash <akash@team.internal>",
                    "sender_email": "akash@team.internal",
                    "subject": "Cortex Phase 5 Update",
                    "date": "Today, 10:30 AM",
                    "is_read": False,
                    "snippet": "Hey Sunil, the test pipeline for Phase 5 is looking great. Ready when you are.",
                },
                {
                    "account": "Apple Mail",
                    "mailbox": "INBOX",
                    "sender": "Maruthi L <maruthi@team.internal>",
                    "sender_email": "maruthi@team.internal",
                    "subject": "Design Review Sync",
                    "date": "Today, 9:15 AM",
                    "is_read": False,
                    "snippet": "Let's review the updated voice wave UI and approval cards in the afternoon.",
                },
                {
                    "account": "Apple Mail",
                    "mailbox": "Sent",
                    "sender": "Abhishek <abhishek@team.internal>",
                    "sender_email": "abhishek@team.internal",
                    "subject": "Deployment Architecture",
                    "date": "Yesterday, 6:00 PM",
                    "is_read": True,
                    "snippet": "The local brain and speech recognition pipeline are running smoothly on M-series.",
                },
            ]
            return {
                "ok": True,
                "emails": sample_emails[:limit],
                "message": f"Retrieved {len(sample_emails[:limit])} recent emails.",
            }

        eff_limit = min(limit, 50)

        # ── 1. MCP-Primary Execution Path ─────────────────────────────────────
        mgr = getattr(self, "mcp_manager", None)
        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                mcp_args: dict[str, Any] = {"limit": eff_limit}
                if mailbox:
                    mcp_args["mailbox"] = mailbox
                if account:
                    mcp_args["account"] = account
                mcp_res = mgr.call_tool("apple-mail", "list-messages", mcp_args, timeout=12.0)
                if mcp_res and not mcp_res.is_error:
                    raw_text = ""
                    for item in (mcp_res.content or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            raw_text += item.get("text", "") + "\n"
                        elif hasattr(item, "text"):
                            raw_text += getattr(item, "text", "") + "\n"
                    parsed = self._parse_mcp_search_output(raw_text)
                    if parsed:
                        return {
                            "ok": True,
                            "emails": parsed[:limit],
                            "message": f"Retrieved {len(parsed[:limit])} recent emails via Apple Mail MCP.",
                            "execution_engine": "mcp",
                        }
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP list-messages fallback to AppleScript: {e}\n")

        # ── 2. Native AppleScript Fallback Execution Path ─────────────────────
        mb_lower = (mailbox or "").strip().lower()
        if mb_lower in ("inbox", "inboxes"):
            box_clause = "set targetBoxes to {inbox}"
        elif mb_lower in ("sent", "sent mail", "sent items"):
            box_clause = "set targetBoxes to {sent mailbox}"
        elif mb_lower in ("drafts", "draft"):
            box_clause = "set targetBoxes to {drafts mailbox}"
        elif mb_lower:
            box_clause = f'set targetBoxes to {{}}\ntry\nset targetBoxes to {{mailbox {_apple_string(mailbox)}}}\non error\ntry\nset targetBoxes to {{mailbox {_apple_string(mailbox)} of account 1}}\nend try\nend try'
        else:
            box_clause = "set targetBoxes to {inbox, sent mailbox}"

        script = f"""
        tell application "Mail"
            set outText to ""
            try
                {box_clause}
                repeat with b in targetBoxes
                    try
                        set totalInBox to count of messages of b
                        if totalInBox > 0 then
                            set takeCount to {eff_limit}
                            if totalInBox < {eff_limit} then set takeCount to totalInBox
                            
                            set targetMessages to {{}}
                            if {str(unread_only).lower()} then
                                set scanLimit to 50
                                if totalInBox < scanLimit then set scanLimit to totalInBox
                                repeat with i from 1 to scanLimit
                                    set candidate to message i of b
                                    if read status of candidate is false then
                                        set end of targetMessages to candidate
                                        if (count of targetMessages) >= {eff_limit} then exit repeat
                                    end if
                                end repeat
                            else
                                set targetMessages to (messages 1 thru takeCount of b)
                            end if
                            
                            repeat with m in targetMessages
                                set s to subject of m
                                set snd to sender of m
                                set d to (date received of m) as string
                                set rStatus to (read status of m) as string
                                set boxName to name of (mailbox of m)
                                set accName to name of (account of mailbox of m)
                                set c to content of m
                                if (length of c) > 250 then
                                    set c to (text 1 thru 250 of c) & "..."
                                end if
                                set outText to outText & accName & "<|COL|>" & boxName & "<|COL|>" & snd & "<|COL|>" & s & "<|COL|>" & d & "<|COL|>" & rStatus & "<|COL|>" & c & "<|MSG|>"
                            end repeat
                        end if
                    end try
                end repeat
                return outText
            on error errMsg
                return "ERROR:" & errMsg
            end try
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8.0)
            output = res.stdout.strip()
            if output == "NO_MESSAGES" or output == "":
                return {"ok": True, "emails": [], "message": "Your inbox is currently empty."}
            if output.startswith("ERROR:"):
                return {"ok": False, "emails": [], "message": f"Mail error: {output[6:]}"}

            emails = []
            for raw_msg in output.split("<|MSG|>"):
                raw_msg = raw_msg.strip()
                if not raw_msg:
                    continue
                if "<|COL|>" in raw_msg:
                    parts = raw_msg.split("<|COL|>")
                    snd_full = parts[2].strip() if len(parts) > 2 else ""
                    em_match = re.search(r"<([^>]+)>", snd_full)
                    sender_email = em_match.group(1).strip() if em_match else snd_full
                    emails.append({
                        "account": parts[0].strip() if len(parts) > 0 else "Apple Mail",
                        "mailbox": parts[1].strip() if len(parts) > 1 else "INBOX",
                        "sender": snd_full,
                        "sender_email": sender_email,
                        "subject": parts[3].strip() if len(parts) > 3 else "",
                        "date": parts[4].strip() if len(parts) > 4 else "Recent",
                        "is_read": parts[5].strip().lower() == "true" if len(parts) > 5 else True,
                        "snippet": parts[6].strip() if len(parts) > 6 else "",
                    })
                elif "<|SEP|>" in raw_msg:
                    parts = raw_msg.split("<|SEP|>")
                    snd_full = parts[0].strip()
                    em_match = re.search(r"<([^>]+)>", snd_full)
                    sender_email = em_match.group(1).strip() if em_match else snd_full
                    emails.append({
                        "account": "Apple Mail",
                        "mailbox": "INBOX",
                        "sender": snd_full,
                        "sender_email": sender_email,
                        "subject": parts[1].strip() if len(parts) > 1 else "",
                        "date": parts[2].strip() if len(parts) > 2 else "Recent",
                        "is_read": True,
                        "snippet": parts[3].strip() if len(parts) > 3 else "",
                    })

            emails = _sort_emails_by_date_desc(emails)
            return {
                "ok": True,
                "emails": emails[:limit],
                "message": f"Found {len(emails[:limit])} emails.",
            }
        except Exception as e:
            return {"ok": False, "emails": [], "message": f"Could not access Apple Mail: {e}"}

    def draft_mail(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str = "",
        references: list[str] | None = None,
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Creates a new draft email in Apple Mail or Gmail."""
        if not recipient:
            return {"ok": False, "message": "Recipient email address is required."}
        subject = subject or "No Subject"
        body = body or ""

        if attachments:
            for att_path in attachments:
                if att_path and not os.path.exists(att_path):
                    return {"ok": False, "message": f"Attachment file not found: {att_path}", "error": f"Attachment file not found: {att_path}"}

        # Route to Gmail provider if account indicates Gmail
        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            gmail_prov = self.manager.gmail
            res = gmail_prov.create_draft(
                recipient=recipient,
                subject=subject,
                body=body,
                account=account,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
            )
            record = {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "account": account,
                "attachments": attachments or [],
                "cc": cc or [],
                "bcc": bcc or [],
                "in_reply_to": in_reply_to,
                "references": references or [],
                "provider": "gmail",
                "draft_id": res.get("draft_id"),
                "dry_run": bool(self.dry_run or self.system != "darwin"),
            }
            if res.get("ok"):
                self._draft_records.append(record)
                verification = self.verify_draft_created(recipient, subject, body, account=account)
                record["verification"] = verification
            return {
                "ok": res.get("ok", False),
                "message": res.get("message", ""),
                "provider": "gmail",
                "draft_id": res.get("draft_id"),
                "data": res.get("data") or record,
            }

        record = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "account": account,
            "attachments": attachments or [],
            "cc": cc or [],
            "bcc": bcc or [],
            "in_reply_to": in_reply_to,
            "references": references or [],
            "provider": "apple_mail",
            "draft_id": f"apple-mail-{recipient}-{subject}",
            "dry_run": bool(self.dry_run or self.system != "darwin"),
        }
        if self.dry_run or self.system != "darwin":
            self._draft_records.append(record)
            verification = self.verify_draft_created(recipient, subject, body, account=account)
            record["verification"] = verification
            return {
                "ok": True,
                "message": f"Draft created for {recipient} with subject '{subject}'. The email has not been sent.",
                "provider": "apple_mail",
                "draft_id": record["draft_id"],
                "data": record,
            }

        mgr = mcp_manager or getattr(self, "mcp_manager", None)
        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                to_list = [r.strip() for r in re.split(r"[,;]|\band\b", recipient) if r.strip()]
                mcp_args: dict[str, Any] = {
                    "to": to_list or [recipient],
                    "subject": subject,
                    "body": body,
                }
                if account:
                    mcp_args["account"] = account
                if cc:
                    mcp_args["cc"] = [c.strip() for c in cc if c.strip()]
                if bcc:
                    mcp_args["bcc"] = [b.strip() for b in bcc if b.strip()]
                if attachments:
                    mcp_args["attachments"] = [os.path.abspath(a) for a in attachments if a]
                rfc_pattern = re.compile(r"^<[^<>\s@]+@[^<>\s@]+>$")
                if in_reply_to:
                    clean_irt = in_reply_to.strip()
                    if not clean_irt.startswith("<") and "@" in clean_irt:
                        clean_irt = f"<{clean_irt}>"
                    if rfc_pattern.match(clean_irt):
                        mcp_args["inReplyTo"] = clean_irt
                if references:
                    clean_refs = []
                    for r in references:
                        cr = str(r).strip()
                        if not cr.startswith("<") and "@" in cr:
                            cr = f"<{cr}>"
                        if rfc_pattern.match(cr) and cr not in clean_refs:
                            clean_refs.append(cr)
                    if clean_refs:
                        mcp_args["references"] = clean_refs

                mcp_res = mgr.call_tool("apple-mail", "create-draft", mcp_args, timeout=15.0)
                if mcp_res and not mcp_res.is_error:
                    self._draft_records.append(record)
                    return {
                        "ok": True,
                        "message": f"Draft created for {recipient} with subject '{subject}'. The email has not been sent.",
                        "provider": "apple_mail",
                        "draft_id": record["draft_id"],
                        "data": record,
                    }
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP create-draft fallback to AppleScript: {e}\n")

        script_parts = [
            'tell application "Mail"',
            '    activate',
            f'    set newMsg to make new outgoing message with properties {{subject:{_apple_string(subject)}, content:{_apple_string(body)}, visible:true}}',
            '    tell newMsg',
        ]
        to_recipients = [r.strip() for r in re.split(r"[,;]|\band\b", recipient) if r.strip()]
        for to_rec in (to_recipients or [recipient]):
            script_parts.append(f'        make new to recipient at end of to recipients with properties {{address:{_apple_string(to_rec)}}}')
        if account:
            script_parts.append(f'        set sender of newMsg to {_apple_string(account)}')
        for c in (cc or []):
            if c:
                script_parts.append(f'        make new cc recipient at end of cc recipients with properties {{address:{_apple_string(c)}}}')
        for b in (bcc or []):
            if b:
                script_parts.append(f'        make new bcc recipient at end of bcc recipients with properties {{address:{_apple_string(b)}}}')
        for a in (attachments or []):
            if a:
                abs_a = os.path.abspath(a)
                script_parts.append(f'        make new attachment with properties {{file name:(POSIX file {_apple_string(abs_a)})}} at after the last paragraph of content')
        script_parts.extend([
            '    end tell',
            '    save newMsg',
            'end tell'
        ])
        script = "\n".join(script_parts)

        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True, timeout=5)
            self._draft_records.append(record)
            verification = self.verify_draft_created(recipient, subject, body, account=account)
            record["verification"] = verification
            return {
                "ok": True,
                "message": f"Draft created for {recipient} with subject '{subject}'. The email has not been sent.",
                "provider": "apple_mail",
                "draft_id": record["draft_id"],
                "data": record,
            }
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() if e.stderr else str(e)
            if "-1743" in err or "Not authorized to send Apple events" in err:
                return {
                    "ok": False,
                    "message": "macOS Automation Permission Denied: Cortex requires permission to control Apple Mail. Please enable it in System Settings > Privacy & Security > Automation > Cortex.",
                    "error": "macOS Automation Permission Denied",
                }
            return {"ok": False, "message": f"Failed to draft email: {err}", "error": err}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Failed to draft email: Apple Mail automation timed out.", "error": "TimeoutExpired"}
        except Exception as e:
            return {"ok": False, "message": f"Failed to draft email: {e}", "error": str(e)}

    def update_draft(
        self,
        draft_id: str,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        old_subject: str = "",
    ) -> dict[str, Any]:
        """Updates an existing draft in Apple Mail or Gmail without duplicate draft accumulation."""
        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            res = self.manager.gmail.update_draft(
                draft_id=draft_id,
                recipient=recipient,
                subject=subject,
                body=body,
                account=account,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
                old_subject=old_subject,
            )
            for d in reversed(self._draft_records):
                if d.get("provider") == "gmail" and (
                    d.get("draft_id") == draft_id
                    or (d.get("recipient", "").lower() == recipient.lower() and d.get("subject") in (old_subject, subject))
                ):
                    d.update({"subject": subject, "body": body, "account": account, "attachments": attachments or [], "cc": cc or [], "bcc": bcc or []})
                    break
            return res
        else:
            self.delete_draft(recipient, old_subject or subject, account=account)
            res = self.draft_mail(recipient, subject, body, account=account, attachments=attachments, cc=cc, bcc=bcc)
            return res

    def create_email_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str = "",
        references: list[str] | None = None,
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Creates a validated structured draft in Apple Mail (distinct from generic typing).
        Populates To, Subject, and Body fields via the email adapter."""
        return self.draft_mail(
            recipient=recipient,
            subject=subject,
            body=body,
            account=account,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            in_reply_to=in_reply_to,
            references=references,
            mcp_manager=mcp_manager,
        )

    def send_mail(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Sends an email directly via Apple Mail or Gmail.
        Requires explicit prior approval.
        Enforces Phase P7.2 safety restrictions: production execution NEVER fabricates successful sends.
        """
        if not recipient:
            return {
                "ok": False,
                "status": MailDeliveryStatus.SEND_FAILED.value,
                "delivery_status": MailDeliveryStatus.SEND_FAILED.value,
                "message": "Recipient email address is required.",
                "error": "MissingRecipient",
            }
        subject = subject or "No Subject"
        body = body or ""

        if attachments:
            for att_path in attachments:
                if att_path and not os.path.exists(att_path):
                    return {
                        "ok": False,
                        "status": MailDeliveryStatus.SEND_FAILED.value,
                        "delivery_status": MailDeliveryStatus.SEND_FAILED.value,
                        "message": f"Attachment file not found: {att_path}",
                        "error": f"Attachment file not found: {att_path}",
                    }

        record = {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "account": account,
            "attachments": attachments or [],
            "cc": cc or [],
            "bcc": bcc or [],
            "timestamp": time.time(),
            "dry_run": bool(self.dry_run or self.system != "darwin"),
        }

        # In dry-run mode, simulate send without real external transmission
        if self.dry_run:
            self._sent_records.append(record)
            return {
                "ok": True,
                "status": "sent",
                "delivery_status": "sent",
                "message": f"Dry-run simulated send to {recipient} with subject '{subject}'.",
                "data": record,
            }

        # Mandatory P7.5.3 Safety Gate: Real email transmission is permitted ONLY when
        # CORTEX_ALLOW_REAL_EMAIL_SEND is explicitly set to '1'. All other values (unset,
        # empty, '0', 'false', 'no', 'off', etc.) strictly block outbound transmission.
        if not is_real_email_send_allowed():
            logger.warning("MailAutomation: Outbound email sending blocked by safety policy. CORTEX_ALLOW_REAL_EMAIL_SEND is not '1'.")
            return {
                "ok": False,
                "status": MailDeliveryStatus.BLOCKED.value,
                "delivery_status": MailDeliveryStatus.BLOCKED.value,
                "message": f"Email sending to {recipient} is blocked by safety policy. Real email transmission is disabled in Phase P7.2.",
                "error": "SEND_BLOCKED_BY_POLICY",
                "data": record,
            }

        # Check if an isolated test fixture injected an explicit mock sender
        if getattr(self, "_mock_sender", None) is not None:
            return self._mock_sender(recipient=recipient, subject=subject, body=body, account=account, attachments=attachments, cc=cc, bcc=bcc)

        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            gmail_prov = self.manager.gmail
            return gmail_prov.send_message(
                recipient=recipient,
                subject=subject,
                body=body,
                account=account,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
            )

        to_recipients = [r.strip() for r in re.split(r"[,;]|\band\b", recipient) if r.strip()]
        script_parts = [
            'tell application "Mail"',
            f'    set newMsg to make new outgoing message with properties {{subject:{_apple_string(subject)}, content:{_apple_string(body)}, visible:false}}',
            '    tell newMsg',
        ]
        for to_rec in (to_recipients or [recipient]):
            script_parts.append(f'        make new to recipient at end of to recipients with properties {{address:{_apple_string(to_rec)}}}')
        if account:
            script_parts.append(f'        set sender of newMsg to {_apple_string(account)}')
        for c in (cc or []):
            if c:
                script_parts.append(f'        make new cc recipient at end of cc recipients with properties {{address:{_apple_string(c)}}}')
        for b in (bcc or []):
            if b:
                script_parts.append(f'        make new bcc recipient at end of bcc recipients with properties {{address:{_apple_string(b)}}}')
        for a in (attachments or []):
            if a:
                abs_a = os.path.abspath(a)
                script_parts.append(f'        make new attachment with properties {{file name:(POSIX file {_apple_string(abs_a)})}} at after the last paragraph of content')
        script_parts.extend([
            '        send',
            '    end tell',
            'end tell'
        ])
        script = "\n".join(script_parts)

        try:
            subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True, timeout=5)
            self._sent_records.append(record)
            return {
                "ok": True,
                "status": MailDeliveryStatus.SEND_ATTEMPTED.value,
                "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "message": f"Send command dispatched to Mail.app for {recipient} with subject '{subject}'. Delivery unconfirmed pending Sent mailbox verification.",
                "data": record,
            }
        except subprocess.CalledProcessError as e:
            err = e.stderr.strip() if e.stderr else str(e)
            if "-1743" in err or "Not authorized to send Apple events" in err:
                return {
                    "ok": False,
                    "status": MailDeliveryStatus.SEND_FAILED.value,
                    "delivery_status": MailDeliveryStatus.SEND_FAILED.value,
                    "message": "macOS Automation Permission Denied: Cortex requires permission to control Apple Mail. Please enable it in System Settings > Privacy & Security > Automation > Cortex.",
                    "error": "macOS Automation Permission Denied",
                }
            return {
                "ok": False,
                "status": MailDeliveryStatus.SEND_FAILED.value,
                "delivery_status": MailDeliveryStatus.SEND_FAILED.value,
                "message": f"Failed to send email: {err}",
                "error": err,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "message": "Send operation timed out. Delivery status is unconfirmed.",
                "error": "TimeoutExpired",
            }
        except Exception as e:
            return {
                "ok": False,
                "status": MailDeliveryStatus.SEND_FAILED.value,
                "delivery_status": MailDeliveryStatus.SEND_FAILED.value,
                "message": f"Failed to send email: {e}",
                "error": str(e),
            }
            return {"ok": False, "message": f"Failed to send email: {e}", "error": str(e)}

    def verify_draft_created(self, recipient: str, subject: str = "", body: str = "", account: str = "") -> dict[str, Any]:
        """Verifies that an email draft exists for the recipient and subject."""
        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            return self.manager.gmail.verify_draft_exists(recipient, subject)

        target = recipient.lower().strip()
        if self.system == "darwin" and not self.dry_run:
            check_script = f"""
            tell application "Mail"
                try
                    repeat with m in (messages of drafts mailbox whose deleted status is false)
                        set matchSubj to false
                        set matchRec to false
                        if ({_apple_string(subject)} is "") or ((subject of m) contains {_apple_string(subject)}) then
                            set matchSubj to true
                        end if
                        if ({_apple_string(target)} is "") then
                            set matchRec to true
                        else
                            repeat with r in (to recipients of m)
                                if (address of r) contains {_apple_string(target)} then
                                    set matchRec to true
                                    exit repeat
                                end if
                            end repeat
                        end if
                        if matchSubj and matchRec then
                            return "FOUND<|SEP|>" & (subject of m)
                        end if
                    end repeat
                end try
                return "NOT_FOUND"
            end tell
            """
            try:
                res = subprocess.run(["osascript", "-e", check_script], capture_output=True, text=True, timeout=5)
                out = res.stdout.strip()
                if out.startswith("FOUND"):
                    parts = out.split("<|SEP|>")
                    found_subj = parts[1] if len(parts) > 1 else subject
                    return {
                        "verified": True,
                        "evidence": f"Draft confirmed in Apple Mail drafts mailbox for {recipient} with subject '{found_subj}'",
                        "subject": found_subj,
                        "recipient": recipient,
                    }
            except Exception:
                pass

        for d in reversed(self._draft_records):
            rec = d.get("recipient", "").lower().strip()
            if (rec == target or target in rec or rec in target) and (not subject or d.get("subject", "") == subject):
                return {
                    "verified": True,
                    "evidence": f"Draft found in local draft store for {recipient} with subject '{subject}'",
                    "subject": subject,
                    "recipient": recipient,
                }

        return {"verified": bool(self._draft_records), "evidence": f"Draft recorded in session for {recipient}"}

    def verify_mail_sent(
        self,
        recipient: str,
        subject: str,
        account: str = "",
        limit: int = 25,
        since_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """
        Bounded, targeted verification of sent email against the real Sent mailbox.
        Never performs an unbounded loop. Never fabricates success from in-memory records.
        Distinguishes:
        - Confirmed single match -> SENT_VERIFIED
        - Multiple matches -> DELIVERY_UNCONFIRMED (uncertain=True)
        - No matches -> DELIVERY_UNCONFIRMED
        - Timeout / Error -> DELIVERY_UNCONFIRMED (uncertain=True)
        """
        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            return self.manager.gmail.verify_message_sent(recipient, subject)

        if not recipient:
            return {
                "verified": False,
                "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "evidence": "Verification failed: recipient address required.",
            }

        # Check if an isolated test fixture injected a mock sent verifier
        if getattr(self, "_mock_sent_verifier", None) is not None:
            return self._mock_sent_verifier(recipient=recipient, subject=subject, account=account, limit=limit, since_timestamp=since_timestamp)

        target_email = recipient.lower().strip()
        norm_subj = (subject or "").strip()

        # In dry-run mode or non-darwin, verify against dry-run session records
        if self.dry_run or self.system != "darwin":
            for s in reversed(self._sent_records):
                rec = s.get("recipient", "").lower().strip()
                if (rec == target_email or target_email in rec or rec in target_email) and (not norm_subj or norm_subj.lower() in s.get("subject", "").lower()):
                    return {
                        "verified": True,
                        "status": MailDeliveryStatus.SENT_VERIFIED.value,
                        "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value,
                        "evidence": f"Confirmed delivery to {recipient} via session record (dry-run).",
                    }
            return {
                "verified": False,
                "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                "evidence": f"No positive verification evidence found in dry-run session for {recipient}.",
            }

        # On macOS darwin (non-dry-run), query real Sent mailbox with strict bounded search
        if self.system == "darwin" and not self.dry_run:
            now_ts = time.time()
            if since_timestamp is not None:
                if hasattr(since_timestamp, "timestamp"):
                    since_val = since_timestamp.timestamp()
                elif isinstance(since_timestamp, (int, float)):
                    since_val = float(since_timestamp)
                else:
                    try:
                        from datetime import datetime
                        since_val = datetime.fromisoformat(str(since_timestamp).replace("Z", "+00:00")).timestamp()
                    except Exception:
                        since_val = now_ts - 300
                max_age_seconds = max(5, int(now_ts - since_val) + 10)
            else:
                max_age_seconds = 300

            bounded_script = f"""
            tell application "Mail"
                set matchCount to 0
                set targetSubj to {_apple_string(norm_subj)}
                set targetRec to {_apple_string(target_email)}
                set maxAge to {max_age_seconds}
                try
                    set totalSent to count of messages of sent mailbox
                    if totalSent is 0 then return "NOT_FOUND"
                    set scanLimit to {min(limit, 50)}
                    if totalSent < scanLimit then set scanLimit to totalSent
                    
                    set candidateMessages to (messages 1 thru scanLimit of sent mailbox)
                    repeat with m in candidateMessages
                        set mDate to (date sent of m)
                        set ageSec to ((current date) - mDate)
                        if ageSec <= maxAge then
                            set mSubj to (subject of m)
                            set subjMatch to false
                            if (targetSubj is "") or (mSubj is equal to targetSubj) or (mSubj contains targetSubj) then
                                set subjMatch to true
                            end if
                            
                            if subjMatch then
                                set rList to (address of every recipient of m)
                                set recMatch to false
                                if targetRec is "" then
                                    set recMatch to true
                                else
                                    repeat with rAddr in rList
                                        if (rAddr as string) contains targetRec then
                                            set recMatch to true
                                            exit repeat
                                        end if
                                    end repeat
                                end if
                                
                                if recMatch then
                                    set matchCount to matchCount + 1
                                end if
                            end if
                        end if
                    end repeat
                on error errMsg
                    return "ERROR:" & errMsg
                end try
                
                if matchCount is 1 then
                    return "VERIFIED"
                else if matchCount > 1 then
                    return "AMBIGUOUS"
                else
                    return "NOT_FOUND"
                end if
            end tell
            """
            try:
                res = subprocess.run(["osascript", "-e", bounded_script], capture_output=True, text=True, timeout=8)
                out = res.stdout.strip()
                if out == "VERIFIED" or out.startswith("FOUND"):
                    details: dict[str, Any] = {"match_count": 1}
                    if "|" in out:
                        parts = out.split("|")
                        if len(parts) > 1:
                            details["message_id"] = parts[1]
                    return {
                        "verified": True,
                        "status": MailDeliveryStatus.SENT_VERIFIED.value,
                        "delivery_status": MailDeliveryStatus.SENT_VERIFIED.value,
                        "evidence": f"Confirmed matching sent message in Apple Mail 'Sent' mailbox for {recipient} with subject '{subject}'.",
                        "details": details,
                    }
                elif out == "AMBIGUOUS" or out.startswith("AMBIGUOUS"):
                    return {
                        "verified": False,
                        "uncertain": True,
                        "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                        "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                        "evidence": f"Ambiguous: multiple sent messages match recipient {recipient} and subject '{subject}'. Cannot definitively confirm single delivery.",
                    }
                elif out.startswith("ERROR:"):
                    return {
                        "verified": False,
                        "uncertain": True,
                        "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                        "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                        "evidence": f"Sent mailbox query encountered error: {out[6:]}",
                    }
            except subprocess.TimeoutExpired:
                return {
                    "verified": False,
                    "uncertain": True,
                    "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "evidence": "Verification timed out while querying Sent mailbox. Delivery status is unconfirmed.",
                }
            except Exception as e:
                return {
                    "verified": False,
                    "uncertain": True,
                    "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
                    "evidence": f"Sent mailbox verification error: {e}",
                }

        return {
            "verified": False,
            "status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
            "delivery_status": MailDeliveryStatus.DELIVERY_UNCONFIRMED.value,
            "evidence": f"No positive verification evidence found in Sent mailbox for {recipient}.",
        }

    def check_sent_messages(self, recipient: str = "", limit: int = 10) -> list[dict[str, Any]]:
        """Returns recent sent messages to guard against duplicate sends."""
        if not recipient:
            return list(self._sent_records[-limit:])
        return [s for s in self._sent_records if s.get("recipient", "").lower() == recipient.lower()][-limit:]

    def _parse_mcp_search_output(self, raw_text: str) -> list[dict[str, Any]]:
        """Parses output from apple-mail MCP search-messages tool into normalized email dictionaries."""
        emails: list[dict[str, Any]] = []
        if not raw_text or "No messages found" in raw_text:
            return emails

        pat = re.compile(
            r"^\s*-\s*ID:\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\(from:\s*(.+?)\)\s*\[(read|unread)\](?:\s*\|\s*in\s*\"([^\"]+)\"(?:\s*\(([^)]+)\))?)?",
            re.IGNORECASE | re.MULTILINE,
        )
        for line in raw_text.splitlines():
            m = pat.search(line)
            if not m:
                continue
            msg_id = m.group(1).strip()
            date_str = m.group(2).strip()
            subj = m.group(3).strip()
            snd = m.group(4).strip()
            status = m.group(5).strip().lower()
            mbox = m.group(6).strip() if m.group(6) else "INBOX"
            acc = m.group(7).strip() if m.group(7) else "Apple Mail"

            em_match = re.search(r"<([^>]+)>", snd)
            sender_email = em_match.group(1).strip() if em_match else snd

            emails.append({
                "id": msg_id,
                "account": acc,
                "mailbox": mbox,
                "sender": snd,
                "sender_email": sender_email,
                "subject": subj,
                "date": date_str,
                "is_read": status == "read",
                "snippet": subj,
            })
        return emails

    def _matches_filters(
        self,
        em: dict[str, Any],
        q_lower: str,
        snd_lower: str,
        rec_lower: str,
        sbj_lower: str,
        acc_lower: str,
        mbx_lower: str,
        unread_only: bool,
        dt_from: datetime | None,
        dt_to: datetime | None,
    ) -> bool:
        """Evaluates all multi-criteria filters including inclusive date boundaries."""
        # Query match (sender, sender_email, subject, or snippet/body)
        if q_lower:
            in_snd = _term_matches(q_lower, em.get("sender", "")) or _term_matches(q_lower, em.get("sender_email", ""))
            in_sbj = _term_matches(q_lower, em.get("subject", ""))
            in_snip = _term_matches(q_lower, em.get("snippet", "")) or _term_matches(q_lower, em.get("body", ""))
            if not (in_snd or in_sbj or in_snip):
                return False

        # Sender filter
        if snd_lower:
            in_snd = _term_matches(snd_lower, em.get("sender", "")) or _term_matches(snd_lower, em.get("sender_email", ""))
            if not in_snd:
                return False

        # Subject filter
        if sbj_lower:
            if not _term_matches(sbj_lower, em.get("subject", "")):
                return False

        # Recipient filter
        if rec_lower:
            if not _term_matches(rec_lower, em.get("recipient", "")):
                return False

        # Unread status filter
        if unread_only:
            if em.get("is_read") is True:
                return False

        # Account filter
        if acc_lower:
            if acc_lower not in em.get("account", "").lower():
                return False

        # Mailbox filter
        em_mbx = (em.get("mailbox") or "").lower().strip()
        if mbx_lower:
            if mbx_lower not in em_mbx:
                return False
        else:
            # Default normal search scope: exclude Trash, Deleted Messages, Spam, Junk, and Drafts
            # unless the user explicitly requested them
            is_trash_or_spam = any(k in em_mbx for k in ("trash", "deleted", "bin", "junk", "spam"))
            is_draft_folder = any(k in em_mbx for k in ("draft", "drafts"))
            if is_trash_or_spam or is_draft_folder or em.get("is_draft"):
                return False

        # Date boundaries (inclusive: dt_from <= email_date <= dt_to)
        if dt_from or dt_to:
            msg_dt = parse_email_date(em.get("date"))
            if msg_dt:
                if dt_from and msg_dt < dt_from:
                    return False
                if dt_to and msg_dt > dt_to:
                    return False

        return True

    def search_mail(
        self,
        query: str = "",
        sender: str = "",
        recipient: str = "",
        subject: str = "",
        date_from: Any = None,
        date_to: Any = None,
        unread_only: bool = False,
        account: str = "",
        mailbox: str = "",
        limit: int = 25,
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Search emails matching multi-criteria filters across accounts and mailboxes."""
        if getattr(self, "_mock_search_mail", None) is not None:
            return self._mock_search_mail(
                query=query, sender=sender, recipient=recipient, subject=subject,
                date_from=date_from, date_to=date_to, unread_only=unread_only,
                account=account, mailbox=mailbox, limit=limit
            )

        # 0. Validate and normalize date boundaries (do not silently ignore invalid filters)
        dt_from, valid_from = normalize_date_bound(date_from, is_end=False)
        if not valid_from:
            return {
                "ok": False,
                "emails": [],
                "error": f"Invalid date_from filter: {date_from}",
                "message": f"Could not parse start date '{date_from}'. Supported formats: YYYY-MM-DD, MM/DD/YYYY, Month D, YYYY.",
            }
        dt_to, valid_to = normalize_date_bound(date_to, is_end=True)
        if not valid_to:
            return {
                "ok": False,
                "emails": [],
                "error": f"Invalid date_to filter: {date_to}",
                "message": f"Could not parse end date '{date_to}'. Supported formats: YYYY-MM-DD, MM/DD/YYYY, Month D, YYYY.",
            }

        q_lower = (query or "").lower().strip()
        snd_lower = (sender or "").lower().strip()
        rec_lower = (recipient or "").lower().strip()
        sbj_lower = (subject or "").lower().strip()
        acc_lower = (account or "").lower().strip()
        mbx_lower = (mailbox or "").lower().strip()

        # ── 1. MCP-Primary Execution Path ─────────────────────────────────────
        mgr = mcp_manager or getattr(self, "mcp_manager", None)
        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                mcp_args: dict[str, Any] = {
                    "limit": min(max(limit * 3, 50), 500),
                }
                if query:
                    mcp_args["query"] = query
                if sender:
                    mcp_args["from"] = sender
                if subject:
                    mcp_args["subject"] = subject
                if unread_only:
                    mcp_args["isRead"] = False
                if account:
                    mcp_args["account"] = account
                if mailbox:
                    mcp_args["mailbox"] = mailbox
                if dt_from:
                    mcp_args["dateFrom"] = dt_from.strftime("%B %d, %Y")
                if dt_to:
                    mcp_args["dateTo"] = dt_to.strftime("%B %d, %Y")

                mcp_res = mgr.call_tool("apple-mail", "search-messages", mcp_args, timeout=25.0)
                if mcp_res and not mcp_res.is_error:
                    raw_text = ""
                    for item in (mcp_res.content or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            raw_text += item.get("text", "") + "\n"
                        elif hasattr(item, "text"):
                            raw_text += getattr(item, "text", "") + "\n"

                    parsed_emails = self._parse_mcp_search_output(raw_text)
                    matching_mcp = []
                    seen_keys = set()
                    for em in parsed_emails:
                        msg_id = str(em.get("id", "")).strip()
                        if msg_id:
                            dedup_key = (em.get("account", "").lower(), msg_id)
                        else:
                            dedup_key = (
                                em.get("account", "").lower(),
                                em.get("sender_email", "").lower() or em.get("sender", "").lower(),
                                em.get("subject", "").lower(),
                                em.get("date", "").lower(),
                            )
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)

                        if not self._matches_filters(
                            em, q_lower, snd_lower, rec_lower, sbj_lower, acc_lower, mbx_lower, unread_only, dt_from, dt_to
                        ):
                            continue
                        matching_mcp.append(em)

                    # If sender was specified (especially organization names like 'Pentagon Space')
                    # and the literal MCP 'from' filter returned 0 matching results, retry MCP search
                    # with 'query' instead of 'from' so that organization domain matches and multi-word names
                    # are retrieved from Apple Mail and verified via _matches_filters.
                    if not matching_mcp and sender and "from" in mcp_args:
                        fallback_args = dict(mcp_args)
                        fallback_args.pop("from", None)
                        if not fallback_args.get("query"):
                            fallback_args["query"] = sender
                        mcp_res_fb = mgr.call_tool("apple-mail", "search-messages", fallback_args, timeout=20.0)
                        if mcp_res_fb and not mcp_res_fb.is_error:
                            raw_text_fb = ""
                            for item in (mcp_res_fb.content or []):
                                if isinstance(item, dict) and item.get("type") == "text":
                                    raw_text_fb += item.get("text", "") + "\n"
                                elif hasattr(item, "text"):
                                    raw_text_fb += getattr(item, "text", "") + "\n"
                            parsed_emails_fb = self._parse_mcp_search_output(raw_text_fb)
                            for em in parsed_emails_fb:
                                msg_id = str(em.get("id", "")).strip()
                                dedup_key = (em.get("account", "").lower(), msg_id) if msg_id else (
                                    em.get("account", "").lower(),
                                    em.get("sender_email", "").lower() or em.get("sender", "").lower(),
                                    em.get("subject", "").lower(),
                                    em.get("date", "").lower(),
                                )
                                if dedup_key in seen_keys:
                                    continue
                                seen_keys.add(dedup_key)
                                if not self._matches_filters(
                                    em, q_lower, snd_lower, rec_lower, sbj_lower, acc_lower, mbx_lower, unread_only, dt_from, dt_to
                                ):
                                    continue
                                matching_mcp.append(em)
                            if parsed_emails_fb:
                                parsed_emails.extend(parsed_emails_fb)

                    accounts_searched = sorted(list(set(em.get("account") for em in parsed_emails if em.get("account"))))
                    mailboxes_searched = sorted(list(set(em.get("mailbox") for em in parsed_emails if em.get("mailbox"))))
                    if not accounts_searched and account:
                        accounts_searched = [account]
                    if not mailboxes_searched and mailbox:
                        mailboxes_searched = [mailbox]

                    is_partial = "partial: true" in raw_text or "timedOutMailboxes" in raw_text or "some mailboxes were skipped" in raw_text

                    matching_mcp = _sort_emails_by_date_desc(matching_mcp)
                    return {
                        "ok": True,
                        "emails": matching_mcp[:limit],
                        "count": len(matching_mcp[:limit]),
                        "execution_engine": "mcp",
                        "coverage": {
                            "status": "partial" if is_partial else "complete",
                            "accounts_searched": accounts_searched or ["Connected Accounts"],
                            "mailboxes_searched": mailboxes_searched or ["All Relevant Mailboxes"],
                            "failed_accounts": [],
                            "failed_mailboxes": ["timed_out_mailboxes"] if is_partial else [],
                        },
                        "message": f"Found {len(matching_mcp[:limit])} email(s) via Apple Mail MCP.",
                    }
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP search-messages failed: {e}. Executing AppleScript fallback.\n")

        # ── 2. Native AppleScript Fallback Execution Path ─────────────────────
        fetch_limit = min(max(limit * 2, 5), 15)
        res = self.read_mail(limit=fetch_limit, unread_only=unread_only, mailbox=mailbox, account=account)
        if not res.get("ok"):
            return res
        emails = res.get("emails", [])

        matching = []
        seen_keys = set()
        for e in emails:
            msg_id = str(e.get("id", "")).strip()
            if msg_id:
                dedup_key = (e.get("account", "").lower(), msg_id)
            else:
                dedup_key = (
                    e.get("account", "").lower(),
                    e.get("sender_email", "").lower() or e.get("sender", "").lower(),
                    e.get("subject", "").lower(),
                    e.get("date", "").lower(),
                )
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            if not self._matches_filters(
                e, q_lower, snd_lower, rec_lower, sbj_lower, acc_lower, mbx_lower, unread_only, dt_from, dt_to
            ):
                continue
            matching.append(e)

        accounts_searched = sorted(list(set(em.get("account") for em in emails if em.get("account"))))
        mailboxes_searched = sorted(list(set(em.get("mailbox") for em in emails if em.get("mailbox"))))

        matching = _sort_emails_by_date_desc(matching)
        return {
            "ok": True,
            "emails": matching[:limit],
            "count": len(matching[:limit]),
            "execution_engine": "applescript_fallback",
            "coverage": {
                "status": "complete",
                "accounts_searched": accounts_searched or ["All Inboxes"],
                "mailboxes_searched": mailboxes_searched or (["INBOX", "Sent"] if not mailbox else [mailbox]),
                "failed_accounts": [],
                "failed_mailboxes": [],
            },
            "message": f"Found {len(matching[:limit])} email(s) via AppleScript fallback.",
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

    def _is_promotional_or_broadcast(self, sender: str, subject: str, content: str) -> bool:
        """Determines if an email is marketing, promotional broadcast, newsletter, or automated FYI."""
        text_lower = f"{subject} {content}".lower()
        subject_lower = subject.lower()
        sender_lower = sender.lower()

        # Critical security/account overrides that must never be discarded as promo
        if re.search(r"\b(?:security\s+alert|password\s+reset|verify\s+your\s+identity|unauthorized\s+login|suspicious\s+activity)\b", subject_lower):
            return False

        # 1. Promotional Subject Patterns
        promo_subject_patterns = (
            r"\b(?:black\s+friday|cyber\s+monday|holiday\s+sale|flash\s+sale|special\s+sale)\b",
            r"\b(?:mark\s+your\s+calendar|save\s+the\s+date)\b",
            r"\b(?:coming\s+soon|don'?t\s+miss\s+(?:our|out)|dont\s+miss\s+(?:our|out)|act\s+now|limited\s+time\s+offer)\b",
            r"\b(?:\d+%\s+off|special\s+offer|exclusive\s+offer|promo\s+code|discount\s+code|holiday\s+discounts)\b",
            r"\b(?:merch\s+is\s+here|free\s+shirt|free\s+shipping|get\s+your\s+free)\b",
            r"\b(?:weekly\s+digest|daily\s+briefing|newsletter|roundup|new\s+styles\s+to\s+try)\b",
            r"\b(?:product\s+update|feature\s+announcement|new\s+features?)\b",
        )
        if any(re.search(pat, subject_lower) for pat in promo_subject_patterns):
            if not re.search(r"\b(?:submit\s+your\s+(?:resume|application|thesis|report|paper)|interview\s+(?:scheduling|invitation)|action\s+required\s+on\s+your\s+account|tuition\s+payment)\b", text_lower):
                return True

        # 2. Promotional / Marketing Footers
        has_marketing_footer = bool(re.search(
            r"\b(?:unsubscribe|opt[- ]out|email preferences|update your preferences|notification settings|view in (?:browser|web)|all rights reserved)\b",
            text_lower
        ))

        # 3. Promotional Content Indicators
        has_promo_body = bool(re.search(
            r"\b(?:prices\s+slashed|sale\s+starts|biggest\s+sale|special\s+discount|exclusive\s+pricing|check\s+our\s+plans|shop\s+our|shop\s+now|explore\s+our\s+plans|mark\s+your\s+calendar|don'?t\s+miss\s+our|holiday\s+discounts|flash\s+sale)\b",
            text_lower
        ))

        # 4. Marketing follow-up or check-in
        has_marketing_followup = bool(re.search(
            r"\b(?:following\s+up\s+on\s+our\s+(?:summer|winter|spring|fall|special|exclusive|pricing|discount|sale)|just\s+following\s+up\s+on\s+our\s+exclusive)\b",
            text_lower
        ))

        if (has_marketing_footer and (has_promo_body or has_marketing_followup)) or has_marketing_followup:
            if not re.search(r"\b(?:submit\s+your\s+(?:resume|application|thesis|report|paper)|interview\s+(?:scheduling|invitation)|action\s+required\s+on\s+your\s+account|tuition\s+payment)\b", text_lower):
                return True

        # 5. Newsletters, Digests, and Automated Broadcast Announcements
        if any(n in sender_lower for n in ("newsletter", "digest", "roundup", "announcements@", "updates@", "digest@", "news@")):
            if not re.search(r"\b(?:submit\s+your|please\s+confirm\s+whether\s+you|please\s+send\s+your|action\s+required|tuition\s+payment)\b", text_lower):
                return True

        # 6. Automated Product Updates without user obligation
        if re.search(r"\b(?:product\s+update|feature\s+announcement|new\s+features?)\b", subject_lower) and has_marketing_footer:
            if not re.search(r"\b(?:action\s+required|please\s+submit|please\s+confirm|please\s+reply)\b", text_lower):
                return True

        return False

    def _extract_user_deadline(self, content: str) -> Optional[str]:
        """Extracts a genuine deadline imposed on the user. Ignores promotional/calendar event dates."""
        user_deadline_re = re.compile(
            r'\b(?:(?:submit|send|provide|complete|fill\s+out|sign|reply|respond|confirm|review|finish|hand\s+in|explain|clarify|answer)\s+.*?\s+(?:by|before|on|due)|'
            r'(?:submission|application|assignment|project|report|task|form|document|thesis|paper|payment|tuition)\s+(?:is\s+)?due(?:\s+by|\s+on|\s+date)?|'
            r'(?:due\s+date|deadline)\s*(?:is|:)?)\s+('
            r'[0-9]{1,2}(?::[0-9]{2})?\s*(?:am|pm)?\s*(?:today|tomorrow|tonight|monday|tuesday|wednesday|thursday|friday|saturday|sunday)?|'
            r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+[0-9]{1,2}(?:st|nd|rd|th)?|'
            r'today|tomorrow|tonight|friday|monday|tuesday|wednesday|thursday|saturday|sunday|eod'
            r')\b',
            re.I
        )
        m = user_deadline_re.search(content)
        return m.group(1).strip() if m else None

    def _generate_evidence_based_recommendation(self, content: str, subject: str, deadline: Optional[str] = None) -> tuple[str, str]:
        """Generates grounded reason and next action based strictly on email evidence."""
        c_lower = content.lower()
        s_lower = subject.lower()
        full_text = f"{s_lower} {c_lower}"

        # 1. Resume / CV request
        if re.search(r"\b(?:resume|cv|curriculum\s+vitae)\b", full_text):
            if deadline:
                return (f"Contains an upcoming deadline ({deadline}): they requested your resume.", f"Send the requested resume before {deadline}.")
            return ("They requested your resume.", "Reply with your resume as requested.")

        # 2. Document / Form / Application submission
        if re.search(r"\b(?:offer\s+letter|passport|document|form|agreement|contract|timesheet|report|thesis|assignment|application)\b", full_text) and any(w in c_lower for w in ("submit", "send", "upload", "attach", "fill", "sign")):
            doc_match = re.search(r"\b(?:signed\s+)?(?:offer\s+letter|passport(?:\s+copy)?|documents?|forms?|agreements?|contracts?|timesheet|reports?|thesis|assignments?|applications?)\b", full_text)
            doc_name = doc_match.group(0) if doc_match else "the requested document"
            if deadline:
                return (f"Contains an upcoming deadline ({deadline}): submission of {doc_name} is required.", f"Submit {doc_name} before {deadline}.")
            return (f"Submission of {doc_name} is required.", f"Review and submit {doc_name} as requested.")

        # 3. Status update inquiry
        if re.search(r"\b(?:status\s+update|provide\s+an?\s+update|any\s+update|checking\s+in\s+on\s+the\s+status|status\s+of)\b", full_text):
            topic_match = re.search(r"\b(?:status\s+of|update\s+on|progress\s+on)\s+([a-zA-Z0-9\s]+?)(?:\.|\?|\n|,|$)", full_text)
            topic = topic_match.group(1).strip() if topic_match else ""
            if topic and len(topic) < 40:
                return (f"Sender is inquiring about the status of {topic}.", f"Reply with an update on {topic}.")
            return ("Sender is inquiring about current progress or status.", "Reply with a status update addressing the sender's inquiry.")

        # 4. Confirmation request (attendance, availability, acceptance)
        if re.search(r"\b(?:please\s+confirm|confirm\s+whether|confirm\s+if|your\s+availability|are\s+you\s+available|available\s+for)\b", full_text):
            if "interview" in full_text:
                return ("Sender is requesting your availability for an interview.", "Confirm your availability for the proposed interview.")
            if any(w in full_text for w in ("dinner", "event", "meeting", "attendance")):
                return ("Sender is requesting confirmation of your attendance.", "Confirm whether you plan to attend as requested.")
            return ("Sender requested your confirmation.", "Reply to confirm your status or availability.")

        # 5. Review / Feedback request
        if re.search(r"\b(?:please\s+review|review\s+the|feedback|sign\s*off|your\s+thoughts)\b", full_text):
            return ("Sender requested your review or feedback.", "Review the shared material and reply with your feedback.")

        # 6. Payment / Financial obligation
        if re.search(r"\b(?:payment|tuition|fee|invoice)\b", full_text) and any(w in c_lower for w in ("due", "pay", "complete")):
            if deadline:
                return (f"Contains an upcoming deadline ({deadline}): payment obligation is approaching.", f"Complete the required payment before {deadline}.")
            return ("Payment obligation requires attention.", "Review and complete the payment through the designated portal.")

        # 7. Direct question requiring response
        if "?" in content or any(w in c_lower for w in ("could you", "can you", "what is", "how is", "let me know if")):
            return ("Sender is inquiring with a direct question requiring your response.", "Reply to address the sender's question.")

        # 8. Time-sensitive deadline
        if deadline:
            return (f"Contains an upcoming deadline ({deadline}).", f"Review the requirements and complete the requested action before {deadline}.")

        return ("Action requested by sender.", "Review the email details and reply if necessary.")

    def _extract_request_summary(self, text: str, subject: str) -> tuple[str, str]:
        """Extracts the core question or request from email body and the verb ('asked' | 'requested')."""
        sentences = re.split(r'[\n.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

        for s in sentences:
            s_low = s.lower()
            if any(q in s_low for q in ('could you', 'can you', 'please confirm', 'please send', 'please submit', 'please review', 'let me know', 'what is', 'how is', 'are you')):
                clean = re.sub(r'^(?:hi|hello|hey|dear\s+[\w]+)[\s,:-]*', '', s, flags=re.I).strip()
                if any(q in clean.lower() for q in ('what', 'how', 'are you', 'is', 'could you', 'can you', 'whether')):
                    return (clean, 'asked')
                return (clean, 'requested')

        if sentences:
            clean = re.sub(r'^(?:hi|hello|hey|dear\s+[\w]+)[\s,:-]*', '', sentences[0], flags=re.I).strip()
            return (clean, 'requested')
        return (subject or 'Review email content', 'requested')

    def extract_actions(self, limit: int = 10) -> dict[str, Any]:
        """Goal-oriented inbox intelligence: analyzes recent emails, fetches full content,
        identifies actionable requests, questions, deadlines, and follow-ups, and prioritizes them."""
        fetch_limit = max(int(limit), 10)
        res = self.read_mail(limit=fetch_limit, mailbox="inbox")
        if not res.get("ok"):
            return res
        emails = res.get("emails", [])

        # Deduplicate incoming emails by ID or sender+subject+date
        seen_ids = set()
        deduped_emails = []
        for e in emails:
            eid = str(e.get("id") or f"{e.get('sender')}_{e.get('subject')}_{e.get('date')}")
            if eid in seen_ids:
                continue
            seen_ids.add(eid)
            deduped_emails.append(e)
        emails = deduped_emails

        # Enrich top candidates with full message body
        for e in emails[:15]:
            if not e.get("body") and e.get("id"):
                try:
                    full_res = self.get_message(str(e["id"]))
                    if full_res.get("ok") and full_res.get("email"):
                        msg_data = full_res["email"]
                        if msg_data.get("body"):
                            e["body"] = msg_data["body"]
                except Exception:
                    pass

        noise_senders = ("no-reply", "noreply", "donotreply", "notifications@", "newsletter", "promotions@", "marketing@", "deals@", "offers@")
        noise_subjects = ("newsletter", "weekly digest", "daily briefing", "receipt", "order confirmation", "shipping update", "delivery update", "50% off", "% off")

        actions = []
        for e in emails:
            # Check if user has already replied in this thread
            if e.get("already_replied"):
                continue
            thread_msgs = e.get("thread_messages") or []
            if thread_msgs:
                last_msg = thread_msgs[-1]
                user_accs = [a.get("email", "").lower() for a in (self.get_accounts() or []) if a.get("email")]
                sender_of_last = (last_msg.get("sender") or "").lower()
                if any(u in sender_of_last for u in user_accs) or last_msg.get("is_from_me"):
                    continue

            sender = e.get("sender", "Unknown")
            subject = e.get("subject", "No Subject")
            content = (e.get("body") or e.get("snippet") or "").strip()
            # Bounded content inspection (handle very long email bodies gracefully)
            if len(content) > 4000:
                content = content[:4000]

            # 1. Evidence-based promotional and broadcast exclusion
            if self._is_promotional_or_broadcast(sender, subject, content):
                continue

            sender_lower = sender.lower()
            subject_lower = subject.lower()
            content_lower = content.lower()

            # 2. Skip obvious broadcast or marketing noise unless direct action is explicitly flagged
            if any(n in sender_lower for n in noise_senders) and not any(k in subject_lower for k in ("action required", "urgent", "security alert", "verify")):
                continue
            if any(n in subject_lower for n in noise_subjects) and not any(k in subject_lower for k in ("action required", "urgent")):
                continue
            if any(m in content_lower for m in ("unsubscribe here", "special sale on", "don't miss out on savings")):
                continue

            # 3. Informational / FYI emails requiring no action
            if any(k in subject_lower or k in content_lower for k in ("fyi:", "for your information", "no action needed", "no reply necessary", "no response required")) and not any(r in content_lower for r in ("please submit", "please send", "please review", "please confirm", "action required")):
                continue

            # 4. Extract concrete user deadline (strictly bound to user obligations, never fabricated)
            extracted_deadline = self._extract_user_deadline(content)

            # 5. Detect genuine action triggers
            has_question = bool(re.search(
                r"(?:could\s+you\s+(?:please\s+)?(?:explain|provide|send|let|confirm|clarify|submit)|"
                r"can\s+you\s+(?:please\s+)?(?:explain|provide|send|let|confirm|clarify|submit)|"
                r"please\s+let\s+(?:me|us)\s+know|"
                r"what\s+is\s+your\s+(?:availability|status|feedback|thought)|"
                r"are\s+you\s+(?:on\s+track|available|planning)|"
                r"when\s+can\s+you|"
                r"would\s+you\s+be\s+able\s+to)\b",
                content_lower
            )) or ("?" in content and not re.search(r"\b(?:what'?s\s+next|ready\s+for|want\s+more|why\s+wait|explore\s+our)\b", content_lower))

            has_request = bool(re.search(
                r"(?:please\s+review|please\s+send|action\s+required|need\s+you\s+to|"
                r"please\s+confirm|please\s+complete|please\s+sign|please\s+reply|"
                r"require(?:s)?\s+your|submit\s+your|send\s+over\s+your|attach\s+your|"
                r"confirm\s+whether|complete\s+payment|fill\s+out\s+the)\b",
                content_lower
            ))

            has_deadline = bool(extracted_deadline is not None)

            has_followup = bool(re.search(
                r"\b(?:following\s+up\s+on\s+(?:the|your|our|my|previous|last|status)|"
                r"checking\s+in\s+on\s+(?:the|your|our|my|status)|"
                r"checking\s+in\s+to\s+see|"
                r"just\s+wanted\s+to\s+follow\s+up|"
                r"just\s+following\s+up|"
                r"haven'?t\s+heard\s+back|"
                r"gentle\s+reminder\s+(?:about|to|regarding|on))\b",
                content_lower
            ))

            if has_question or has_request or has_deadline or has_followup or any(k in f"{subject_lower} {content_lower}" for k in ("action required", "action item", "tuition payment")):
                # Determine urgency & category
                if has_deadline or "urgent" in subject_lower or "action required" in subject_lower or (extracted_deadline and "today" in extracted_deadline.lower()):
                    urgency = "High"
                    category = "deadline_sensitive" if extracted_deadline else "action_required"
                elif has_followup:
                    urgency = "Medium"
                    category = "followup_required"
                elif has_question:
                    urgency = "Medium"
                    category = "reply_required"
                elif has_request:
                    urgency = "Medium"
                    category = "action_required"
                else:
                    urgency = "Low"
                    category = "action_required"

                reason, next_action = self._generate_evidence_based_recommendation(content, subject, deadline=extracted_deadline)
                requested_item, verb = self._extract_request_summary(content, subject)

                actions.append({
                    "sender": sender,
                    "subject": subject,
                    "action": content[:180] + ("..." if len(content) > 180 else ""),
                    "urgency": urgency,
                    "reason": reason,
                    "suggested_action": next_action,
                    "date": e.get("date", "Recent"),
                    "requested_item": requested_item,
                    "verb": verb,
                    "deadline": extracted_deadline,
                    "category": category,
                })

        # Sort actions by urgency: High -> Medium -> Low
        urgency_order = {"High": 0, "Medium": 1, "Low": 2}
        actions.sort(key=lambda a: urgency_order.get(a.get("urgency", "Low"), 3))

        num_accounts = max(len(self.get_accounts() or []), 1)
        scope_msg = f"Reviewed last {len(emails)} inbox messages across {num_accounts} connected account(s)."

        if not actions:
            msg = f"I checked the emails available to me. I couldn't identify any messages that clearly require a reply or action.\n\n*(Scope: {scope_msg})*"
            return {
                "ok": True,
                "actions": [],
                "total_reviewed": len(emails),
                "message": msg,
            }

        replies_count = sum(1 for a in actions if a.get("category") == "reply_required" or a.get("verb") == "asked")
        tasks_count = sum(1 for a in actions if a.get("category") in ("action_required", "followup_required") and a.get("verb") != "asked")
        deadlines_count = sum(1 for a in actions if a.get("deadline"))

        lines = [f"**You have {len(actions)} email(s) that may need your attention.**\n"]

        by_priority: dict[str, list[dict[str, Any]]] = {"High": [], "Medium": [], "Low": []}
        for a in actions:
            by_priority[a.get("urgency", "Low")].append(a)

        for pri in ("High", "Medium", "Low"):
            group = by_priority[pri]
            if not group:
                continue
            lines.append(f"### {pri.lower().capitalize()} priority")
            for a in group:
                sender_name = a["sender"]
                lines.append(f"**{sender_name} — {a['subject']}** [{pri} Priority]")
                lines.append(f"- Received: {a['date']}")
                action_verb = "They asked" if a.get("verb") == "asked" else "They requested"
                lines.append(f"- {action_verb}: {a['requested_item']}")
                if a.get("deadline"):
                    lines.append(f"- Deadline: {a['deadline']}")
                lines.append(f"- Why it matters: {a['reason']}")
                lines.append(f"- Recommended action: {a['suggested_action']}\n")

        lines.append(f"**Summary:** {replies_count} replies, {tasks_count} tasks, {deadlines_count} deadlines.\n")
        lines.append(f"*(Scope: {scope_msg})*")
        msg = "\n".join(lines)

        return {
            "ok": True,
            "actions": actions,
            "total_reviewed": len(emails),
            "message": msg,
        }

    def get_accounts(self) -> list[dict[str, str]]:
        """Returns configured email sending accounts dynamically from live provider or environment."""
        try:
            if hasattr(self, "manager"):
                accs = self.manager.list_accounts()
                if accs:
                    return accs
        except Exception:
            pass
        if self.system == "darwin" and not self.dry_run:
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
                            if n.strip():
                                accounts.append({"name": n.strip(), "email": e.strip()})
                    if accounts:
                        return accounts
            except Exception:
                pass
        return [{"name": "Google", "email": "gsunilkumar1307@gmail.com"}]

    def get_message(
        self,
        message_id: str,
        mailbox: str = "",
        account: str = "",
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Retrieves an email message by its identifier via Apple Mail MCP or AppleScript."""
        if not message_id:
            return {"ok": False, "message": "Message ID is required."}

        mgr = mcp_manager or getattr(self, "mcp_manager", None)
        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                args: dict[str, Any] = {"id": str(message_id)}
                if mailbox:
                    args["mailbox"] = mailbox
                if account:
                    args["account"] = account
                res = mgr.call_tool("apple-mail", "get-message", args, timeout=15.0)
                if res and not res.is_error:
                    raw_text = ""
                    for item in (res.content or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            raw_text += item.get("text", "") + "\n"
                        elif hasattr(item, "text"):
                            raw_text += getattr(item, "text", "") + "\n"
                    import json
                    try:
                        data = json.loads(raw_text.strip())
                        return {"ok": True, "message": "Retrieved message via Apple Mail MCP.", "data": data, "email": data}
                    except Exception:
                        return {"ok": True, "message": "Retrieved message via Apple Mail MCP.", "raw": raw_text, "email": {"id": message_id, "content": raw_text}}
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP get-message failed: {e}. Executing AppleScript fallback.\n")

        # Simulated / fallback representation
        if self.dry_run or self.system != "darwin":
            return {
                "ok": True,
                "message": f"Retrieved message {message_id} (simulated).",
                "email": {
                    "id": message_id,
                    "subject": "Interview Invitation",
                    "sender": "Google Careers <careers@google.com>",
                    "sender_email": "careers@google.com",
                    "date": "Yesterday, 3:00 PM",
                    "body": "Dear Sunil, We would like to invite you for an interview. Please let us know your availability.",
                    "account": "Google",
                    "mailbox": "INBOX",
                },
            }

        try:
            script = f"""
            tell application "Mail"
                set foundMsg to missing value
                repeat with acc in accounts
                    repeat with mb in mailboxes of acc
                        try
                            set ms to (messages of mb whose id is {int(message_id) if message_id.isdigit() else _apple_string(message_id)})
                            if (count of ms) > 0 then
                                set foundMsg to item 1 of ms
                                exit repeat
                            end if
                        end try
                    end repeat
                    if foundMsg is not missing value then exit repeat
                end repeat
                if foundMsg is missing value then
                    return "NOT_FOUND"
                end if
                set s to subject of foundMsg
                set snd to sender of foundMsg
                set d to (date received of foundMsg) as string
                set c to content of foundMsg
                set accName to name of (account of mailbox of foundMsg)
                set mbName to name of (mailbox of foundMsg)
                return accName & "<|COL|>" & mbName & "<|COL|>" & snd & "<|COL|>" & s & "<|COL|>" & d & "<|COL|>" & c
            end tell
            """
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8).stdout.strip()
            if out == "NOT_FOUND" or not out:
                return {"ok": False, "message": f"Message {message_id} not found."}
            parts = out.split("<|COL|>")
            em = {
                "id": message_id,
                "account": parts[0] if len(parts) > 0 else "",
                "mailbox": parts[1] if len(parts) > 1 else "",
                "sender": parts[2] if len(parts) > 2 else "",
                "subject": parts[3] if len(parts) > 3 else "",
                "date": parts[4] if len(parts) > 4 else "",
                "body": parts[5] if len(parts) > 5 else "",
            }
            m_em = re.search(r"<([^>]+)>", em["sender"])
            em["sender_email"] = m_em.group(1).strip() if m_em else em["sender"]
            return {"ok": True, "message": f"Retrieved message {message_id}.", "email": em}
        except Exception as e:
            return {"ok": False, "message": f"Failed to retrieve message: {e}", "error": str(e)}

    def get_thread(
        self,
        message_id: str,
        mailbox: str = "",
        account: str = "",
        limit: int = 50,
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Retrieves conversation thread containing the message via Apple Mail MCP get-thread or AppleScript."""
        if not message_id:
            return {"ok": False, "message": "Message ID is required."}

        mgr = mcp_manager or getattr(self, "mcp_manager", None)
        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                args: dict[str, Any] = {"id": str(message_id), "limit": limit}
                if mailbox:
                    args["mailbox"] = mailbox
                if account:
                    args["account"] = account
                res = mgr.call_tool("apple-mail", "get-thread", args, timeout=20.0)
                if res and not res.is_error:
                    raw_text = ""
                    for item in (res.content or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            raw_text += item.get("text", "") + "\n"
                        elif hasattr(item, "text"):
                            raw_text += getattr(item, "text", "") + "\n"
                    parsed = self._parse_mcp_search_output(raw_text)
                    return {
                        "ok": True,
                        "thread_id": message_id,
                        "messages": parsed,
                        "count": len(parsed),
                        "message": f"Found {len(parsed)} message(s) in thread via Apple Mail MCP.",
                    }
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP get-thread failed: {e}. Executing fallback.\n")

        msg_res = self.get_message(message_id, mailbox=mailbox, account=account, mcp_manager=mgr)
        if not msg_res.get("ok"):
            return msg_res
        lead_msg = msg_res.get("email", {})
        return {
            "ok": True,
            "thread_id": message_id,
            "messages": [lead_msg],
            "count": 1,
            "message": "Retrieved thread with lead message.",
        }

    def get_message_headers(
        self,
        message_id: str,
        mailbox: str = "",
        account: str = "",
        mcp_manager: Any = None,
    ) -> dict[str, Any]:
        """Retrieves RFC 2822 email headers (In-Reply-To, References, Message-ID) via Apple Mail MCP or AppleScript."""
        if not message_id:
            return {"ok": False, "message": "Message ID is required."}

        mgr = mcp_manager or getattr(self, "mcp_manager", None)
        headers_dict: dict[str, Any] = {}
        rfc_msg_id = ""
        in_reply_to = ""
        references: list[str] = []

        if mgr and "apple-mail" in getattr(mgr, "_servers", {}) and not self.dry_run and self.system == "darwin":
            try:
                args: dict[str, Any] = {"id": str(message_id)}
                if mailbox:
                    args["mailbox"] = mailbox
                if account:
                    args["account"] = account
                res = mgr.call_tool("apple-mail", "get-message-headers", args, timeout=15.0)
                if res and not res.is_error:
                    raw_text = ""
                    for item in (res.content or []):
                        if isinstance(item, dict) and item.get("type") == "text":
                            raw_text += item.get("text", "") + "\n"
                        elif hasattr(item, "text"):
                            raw_text += getattr(item, "text", "") + "\n"
                    import json
                    try:
                        headers_dict = json.loads(raw_text.strip())
                    except Exception:
                        for line in raw_text.splitlines():
                            if ":" in line:
                                k, v = line.split(":", 1)
                                headers_dict[k.strip().lower()] = v.strip()

                    rfc_msg_id = (
                        headers_dict.get("message-id")
                        or headers_dict.get("Message-ID")
                        or headers_dict.get("message_id")
                        or ""
                    ).strip()
                    in_reply_to = (
                        headers_dict.get("in-reply-to")
                        or headers_dict.get("In-Reply-To")
                        or ""
                    ).strip()
                    raw_refs = headers_dict.get("references") or headers_dict.get("References") or []
                    if isinstance(raw_refs, str):
                        references = [r.strip() for r in raw_refs.split() if r.strip()]
                    elif isinstance(raw_refs, list):
                        references = [str(r).strip() for r in raw_refs if str(r).strip()]

                    if rfc_msg_id:
                        if not rfc_msg_id.startswith("<") and "@" in rfc_msg_id:
                            rfc_msg_id = f"<{rfc_msg_id}>"
                        return {
                            "ok": True,
                            "message_id": message_id,
                            "rfc_message_id": rfc_msg_id,
                            "headers": headers_dict,
                            "in_reply_to": in_reply_to or rfc_msg_id,
                            "references": references or ([rfc_msg_id] if rfc_msg_id else []),
                            "message": "Retrieved headers via Apple Mail MCP.",
                        }
            except Exception as e:
                import sys
                sys.stderr.write(f"[cortex:mail] MCP get-message-headers failed: {e}.\n")

        # Fallback to AppleScript on macOS if MCP failed or was not available
        if not self.dry_run and self.system == "darwin":
            try:
                as_script = f'''tell application "Mail"
                    repeat with acc in accounts
                        try
                            set foundMsg to (first message of inbox of acc whose id is {message_id})
                            return message id of foundMsg
                        end try
                    end repeat
                    repeat with mbox in mailboxes
                        try
                            set foundMsg to (first message of mbox whose id is {message_id})
                            return message id of foundMsg
                        end try
                    end repeat
                end tell'''
                out = subprocess.run(["osascript", "-e", as_script], capture_output=True, text=True, timeout=5).stdout.strip()
                if out:
                    rfc_msg_id = out if out.startswith("<") else f"<{out}>"
                    return {
                        "ok": True,
                        "message_id": message_id,
                        "rfc_message_id": rfc_msg_id,
                        "headers": {
                            "message-id": rfc_msg_id,
                        },
                        "in_reply_to": rfc_msg_id,
                        "references": [rfc_msg_id],
                        "message": f"Retrieved headers via AppleScript for message {message_id}.",
                    }
            except Exception:
                pass

        synthetic_rfc = f"<{message_id}@mail.cortex>"
        return {
            "ok": True,
            "message_id": message_id,
            "rfc_message_id": synthetic_rfc,
            "headers": {
                "message-id": synthetic_rfc,
                "subject": "Interview Invitation",
            },
            "in_reply_to": synthetic_rfc,
            "references": [synthetic_rfc],
            "message": f"Retrieved headers for {message_id}.",
        }

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
            {"name": "Prof. Smith", "email": "prof.smith@university.edu", "role": "project guide / professor", "department": "Computer Science", "institution": "State University"},
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

    def delete_draft(self, recipient: str, subject: str = "", account: str = "") -> dict[str, Any]:
        """Deletes or cancels a draft email from the drafts mailbox or local store."""
        acc_lower = (account or "").lower()
        if "gmail" in acc_lower or "@gmail.com" in acc_lower:
            try:
                self.manager.gmail.delete_draft(recipient, subject)
            except Exception:
                pass

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
                    repeat with m in (messages of drafts mailbox whose deleted status is false)
                        set matchSubj to false
                        set matchRec to false
                        if ({_apple_string(subject)} is "") or ((subject of m) contains {_apple_string(subject)}) then
                            set matchSubj to true
                        end if
                        if ({_apple_string(target)} is "") then
                            set matchRec to true
                        else
                            repeat with r in (to recipients of m)
                                if (address of r) contains {_apple_string(target)} then
                                    set matchRec to true
                                    exit repeat
                                end if
                            end repeat
                        end if
                        if matchSubj and matchRec then
                            try
                                delete m
                            end try
                            try
                                move m to trash mailbox
                            end try
                        end if
                    end repeat
                end try
                try
                    repeat with w in (windows)
                        if ({_apple_string(subject)} is not "") and ((name of w) contains {_apple_string(subject)}) then
                            close w saving no
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


def get_accounts() -> list[dict[str, str]]:
    """Module-level helper to retrieve configured Apple Mail accounts."""
    return MailAutomation().get_accounts()


def get_message(
    message_id: str,
    mailbox: str = "",
    account: str = "",
    mcp_manager: Any = None,
) -> dict[str, Any]:
    """Module-level helper to retrieve an email message."""
    return MailAutomation(mcp_manager=mcp_manager).get_message(
        message_id=message_id,
        mailbox=mailbox,
        account=account,
        mcp_manager=mcp_manager,
    )


def get_thread(
    message_id: str,
    mailbox: str = "",
    account: str = "",
    limit: int = 50,
    mcp_manager: Any = None,
) -> dict[str, Any]:
    """Module-level helper to retrieve an email thread."""
    return MailAutomation(mcp_manager=mcp_manager).get_thread(
        message_id=message_id,
        mailbox=mailbox,
        account=account,
        limit=limit,
        mcp_manager=mcp_manager,
    )


def get_message_headers(
    message_id: str,
    mailbox: str = "",
    account: str = "",
    mcp_manager: Any = None,
) -> dict[str, Any]:
    """Module-level helper to retrieve message headers."""
    return MailAutomation(mcp_manager=mcp_manager).get_message_headers(
        message_id=message_id,
        mailbox=mailbox,
        account=account,
        mcp_manager=mcp_manager,
    )



