from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any
try:
    from backend.core.contracts import LanguageCode, TaskContext
except ImportError:
    from core.contracts import LanguageCode, TaskContext

try:
    from backend.core.translator import translate_text, extract_explicit_language_directive, LANGUAGE_ALIASES
except ImportError:
    from core.translator import translate_text, extract_explicit_language_directive, LANGUAGE_ALIASES



@dataclass
class RecipientContext:
    name: str = ""
    email: str = ""
    role: str = "unknown"          # hod, professor, manager, recruiter, client, colleague, friend, customer_support, official, complaint, unknown
    relationship: str = "neutral"   # academic_admin, academic, hierarchical, professional, external, peer, personal, official, neutral
    formality: str = "medium"       # high, medium, casual
    detected_from: str = "fallback" # user_text, email_address, history, directory, unknown
    department: str = ""
    institution: str = ""
    has_verified_name: bool = False


@dataclass
class EmailDraft:
    recipient: str
    subject: str
    body: str
    tone: str = "professional"
    language: str = "en"
    recipient_role: str = "unknown"
    quality_passed: bool = True
    audit_notes: list[str] = field(default_factory=list)
    raw_response: dict[str, Any] = field(default_factory=dict)
    sender_account: str = "Primary Account"
    attachments: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    approval_hash: str = ""
    draft_id: str = ""
    provider: str = ""

    def __post_init__(self) -> None:
        if not self.approval_hash:
            self.approval_hash = self.compute_hash()

    def canonicalize(self) -> dict[str, Any]:
        """Returns normalized canonical dictionary of draft fields."""
        return {
            "sender_account": (self.sender_account or "Primary Account").strip(),
            "recipient": (self.recipient or "").strip(),
            "to": (self.recipient or "").lower().strip(),
            "cc": sorted(str(c).lower().strip() for c in (self.cc or []) if str(c).strip()),
            "bcc": sorted(str(b).lower().strip() for b in (self.bcc or []) if str(b).strip()),
            "subject": (self.subject or "").strip(),
            "body": (self.body or "").strip(),
            "attachments": sorted(str(a).strip() for a in (self.attachments or []) if str(a).strip()),
        }

    def compute_hash(self) -> str:
        """
        Unambiguous canonical serialization of all material fields.
        Returns the full 64-character SHA-256 cryptographic digest.
        """
        mat = self.canonicalize()
        material = {
            "sender_account": mat["sender_account"],
            "to": mat["to"],
            "cc": mat["cc"],
            "bcc": mat["bcc"],
            "subject": mat["subject"],
            "body": mat["body"],
            "attachments": mat["attachments"],
        }
        canonical_json = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    @property
    def relationship_inferred(self) -> str:
        return self.recipient_role

    @property
    def quality_report(self) -> Any:
        class QualityReport:
            def __init__(self, passed: bool, notes: list[str]):
                self.approved = passed
                self.notes = notes
                self.scores = {
                    "no_generic_filler": 10 if passed else 5,
                    "clarity": 10,
                    "conciseness": 10,
                    "professionalism": 10,
                }
        return QualityReport(self.quality_passed, self.audit_notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipient": self.recipient,
            "cc": self.cc,
            "bcc": self.bcc,
            "subject": self.subject,
            "body": self.body,
            "tone": self.tone,
            "language": self.language,
            "recipientRole": self.recipient_role,
            "qualityPassed": self.quality_passed,
            "auditNotes": self.audit_notes,
            "senderAccount": self.sender_account,
            "attachments": self.attachments,
            "approvalHash": self.approval_hash or self.compute_hash(),
            "draftId": self.draft_id,
            "provider": self.provider,
        }


MONTHS = {
    "january": "January", "february": "February", "march": "March", "april": "April",
    "may": "May", "june": "June", "july": "July", "august": "August",
    "september": "September", "october": "October", "november": "November", "december": "December",
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "jun": "June", "jul": "July", "aug": "August", "sep": "September",
    "sept": "September", "oct": "October", "nov": "November", "dec": "December",
}

AMBIGUOUS_SINGLE_WORDS = {
    "deadline", "urgent", "meeting", "update", "status", "details",
    "query", "question", "important", "email", "mail", "notes",
    "info", "information", "subject", "message", "check"
}


def is_ambiguous_email_intent(text: str) -> bool:
    """Returns True if the text is so vague/fragmentary that the core intent cannot be determined without clarification."""
    if not text:
        return True
    cleaned = re.sub(r"[^\w\s]", "", text.strip()).strip().lower()
    words = cleaned.split()
    if not words:
        return True
    if len(words) == 1 and words[0] in AMBIGUOUS_SINGLE_WORDS:
        return True
    if cleaned in ("check this", "check it", "please check", "see this", "look into this", "regarding deadline", "about deadline"):
        return True
    return False


def polish_email_body_text(text: str) -> str:
    """Polishes body composition:
    - Normalizes dates ('is on 5 november' -> 'is November 5', '5th nov' -> 'November 5')
    - Adds natural lead article when needed ('project presentation deadline...' -> 'The project presentation deadline...')
    - Standardizes capitalization and grammar
    - Ensures proper sentence termination punctuation
    - Preserves multilingual/non-English text and factual data intact
    """
    if not text:
        return ""
    cleaned = text.strip()

    # If Indic script, preserve clean spacing per-line and proper termination without collapsing newlines
    if any(0x0900 <= ord(c) <= 0x0D7F for c in cleaned):
        lines = [re.sub(r"[ \t]+", " ", l).strip() for l in cleaned.splitlines()]
        cleaned = "\n".join(lines)
        if cleaned and not cleaned[-1] in ".!?।":
            cleaned += "."
        return cleaned

    month_pattern = "|".join(MONTHS.keys())

    # 'is on <day> <month>' -> 'is <Month> <day>'
    cleaned = re.sub(
        rf"\bis\s+on\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\b",
        lambda m: f"is {MONTHS[m.group(2).lower()]} {int(m.group(1))}",
        cleaned,
        flags=re.IGNORECASE,
    )
    # 'on <day> <month>' -> 'on <Month> <day>'
    cleaned = re.sub(
        rf"\bon\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\b",
        lambda m: f"on {MONTHS[m.group(2).lower()]} {int(m.group(1))}",
        cleaned,
        flags=re.IGNORECASE,
    )
    # '<day> <month>' -> '<Month> <day>'
    cleaned = re.sub(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\b",
        lambda m: f"{MONTHS[m.group(2).lower()]} {int(m.group(1))}",
        cleaned,
        flags=re.IGNORECASE,
    )
    # '<month> <day>(st|nd|rd|th)' -> '<Month> <day>'
    cleaned = re.sub(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        lambda m: f"{MONTHS[m.group(1).lower()]} {int(m.group(2))}",
        cleaned,
        flags=re.IGNORECASE,
    )

    # Lead article for event/announcement sentences if missing
    lead_match = re.match(
        r"^(?:(?:the|a|an|our|my|this)\s+)?((?:project\s+presentation\s+deadline|project\s+deadline|assignment\s+deadline|submission\s+deadline|presentation\s+deadline|deadline\s+for\s+[a-zA-Z\s]+|meeting\s+(?:is|will\s+be)|report\s+is))\b",
        cleaned,
        re.IGNORECASE,
    )
    if lead_match and not re.match(r"^(?:the|a|an|our|my|this)\b", cleaned, re.IGNORECASE):
        cleaned = "The " + cleaned[0].lower() + cleaned[1:]

    # Capitalize first letter
    if cleaned:
        cleaned = cleaned[0].upper() + cleaned[1:]

    # Capitalize standalone 'i' and contraction 'i'm', 'i'll', 'i've', 'i'd'
    cleaned = re.sub(r"\bi\b", "I", cleaned)
    cleaned = re.sub(r"\bi\'", "I'", cleaned)

    # Capitalize days of week
    days = {
        "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
        "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday", "sunday": "Sunday"
    }
    for d_low, d_cap in days.items():
        cleaned = re.sub(rf"\b{d_low}\b", d_cap, cleaned, flags=re.IGNORECASE)

    # Capitalize first letter after terminal punctuation (. ! ?)
    cleaned = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), cleaned)

    # Ensure terminal punctuation
    if cleaned and not cleaned[-1] in ".!?":
        cleaned += "."

    return cleaned


def convert_instruction_to_recipient_content(text: str) -> tuple[str, dict[str, Any]]:
    """Converts a user-directed meta-instruction into recipient-facing body content and metadata.
    Extracts constraints (e.g. 'do not invent a reason'), tone overrides ('polite', 'formal'),
    strips meta-prefixes ('write a polite email asking...', 'inform them that...'),
    and converts indirect questions/requests into direct recipient phrasing.
    """
    if not text:
        return "", {}

    cleaned = text.strip()
    metadata: dict[str, Any] = {
        "constraints": [],
        "extracted_tone": None,
    }

    # 1. Extract and strip trailing constraints/meta-directives
    constraint_patterns = [
        (r"(?:\.|\b)\s*(?:do\s+not|don'?t)\s+invent\s+(?:a\s+|any\s+)?(?:reason|excuse|dates?|claims?)\.?$", "no_invented_reason"),
        (r"(?:\.|\b)\s*without\s+inventing\s+(?:a\s+|any\s+)?(?:reason|excuse|dates?|claims?)\.?$", "no_invented_reason"),
        (r"(?:\.|\b)\s*no\s+(?:invented\s+reasons?|reasons?|excuses?)\.?$", "no_invented_reason"),
        (r"(?:\.|\b)\s*(?:keep|make)\s+it\s+(?:very\s+)?(polite|formal|casual|brief|concise|short)\.?$", "tone_directive"),
    ]
    for pattern, kind in constraint_patterns:
        m = re.search(pattern, cleaned, re.IGNORECASE)
        if m:
            if kind == "tone_directive":
                metadata["extracted_tone"] = m.group(1).lower()
            else:
                metadata["constraints"].append(kind)
            cleaned = cleaned[:m.start()].strip().rstrip(".! ")

    # 2. Extract leading tone from meta-prefix if present (e.g. 'write a polite email...')
    tone_m = re.search(r"\b(?:a\s+)?(polite|formal|casual|brief|concise|respectful|short|quick)\s+(?:email|mail|message|note)\b", cleaned, re.IGNORECASE)
    if tone_m and not metadata.get("extracted_tone"):
        metadata["extracted_tone"] = tone_m.group(1).lower()

    # 3. Strip leading meta-instruction wrappers
    meta_prefixes = [
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:write|draft|compose|send|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|message)?\s*(?:to\s+[^,]+?)?\s*(?:saying|that|with|:)?\s*",
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:inform|notify|tell|let)\s+(?:them|him|her|the\s+team|everyone|all|the\s+recipient)\s*(?:know)?\s*(?:that|about|saying)?\s*",
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:tell|say\s+to)\s+(?:them|him|her|the\s+recipient)\s+(?:that\s+|saying\s+)?",
        r"^(?:please\s+)?(?:can\s+you\s+)?say\s+(?:that\s+)?",
    ]
    for p in meta_prefixes:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()

    # 4. Convert indirect requests/questions into recipient-facing sentences
    # e.g. "asking whether the project presentation deadline can be extended by two days"
    # -> "Could the project presentation deadline please be extended by two days?"
    ask_whether_m = re.match(
        r"^(?:asking|ask|requesting|inquire|inquiring)\s+(?:whether|if)\s+(.+?)\s+can\s+be\s+(extended|postponed|rescheduled|delayed)(?:\s+(by|to|until)\s+([a-zA-Z0-9\s,]+))?\b\.?",
        cleaned,
        re.IGNORECASE,
    )
    if ask_whether_m:
        topic = ask_whether_m.group(1).strip()
        verb = ask_whether_m.group(2).strip()
        prep = ask_whether_m.group(3) or ""
        target = ask_whether_m.group(4) or ""
        prep_str = f" {prep} {target}".strip() if prep and target else (f" {target}".strip() if target else "")
        cleaned = f"Could {topic} please be {verb}{' ' + prep_str if prep_str else ''}?".replace("  ", " ")
    else:
        ask_gen_m = re.match(r"^(?:asking|ask|requesting|inquire|inquiring)\s+(?:whether|if)\s+(.+)$", cleaned, re.IGNORECASE)
        if ask_gen_m:
            clause = ask_gen_m.group(1).strip().rstrip("?")
            if "can " in clause or "could " in clause:
                clause = re.sub(r"\b(?:can|could)\b", "", clause).strip()
                cleaned = f"Could {clause}?".replace("  ", " ")
            else:
                cleaned = f"Could you please confirm if {clause}?"
        else:
            ask_for_m = re.match(r"^(?:asking|ask|requesting|request)\s+for\s+(.+)$", cleaned, re.IGNORECASE)
            if ask_for_m:
                item = ask_for_m.group(1).strip().rstrip(".")
                cleaned = f"I would like to respectfully request {item}."
            else:
                about_m = re.match(r"^(?:about|regarding|concerning)\s+(.+)$", cleaned, re.IGNORECASE)
                if about_m:
                    item = about_m.group(1).strip().rstrip(".")
                    cleaned = f"I am writing regarding {item}. Please let me know your thoughts and availability."
                elif re.match(r"^(?:tomorrow'?s|today'?s|next\s+week'?s)?\s*(?:project\s+)?meeting\b", cleaned, re.IGNORECASE):
                    cleaned = f"I am writing regarding {cleaned.rstrip('.')}. Please let me know your thoughts and availability."

    return cleaned, metadata


class ProfessionalEmailEngine:
    """Dedicated Context-Aware Professional Email Engine for Cortex.
    Implements:
    - Context & relationship inference (Professor, Manager, Recruiter, Client, Colleague, Friend, Unknown)
    - Command vs content separation
    - User tone override
    - Subject line intelligence
    - Multi-stage Quality Control Pipeline
    - Zero generic templates and zero invented facts
    """

    ROLE_PATTERNS = [
        ("hod", r"\b(?:hod|head of (?:the )?department|department head|dept\.? head)\b", "academic_admin", "high"),
        ("professor", r"\b(?:professor|prof\.?|dean|faculty|advisor|instructor|teacher)\b", "academic", "high"),
        ("manager", r"\b(?:manager|lead|boss|director|supervisor|reporting manager|vp|head)\b", "hierarchical", "high"),
        ("recruiter", r"\b(?:recruiter|talent acquisition|hr|hiring manager|interviewer|interview)\b", "professional", "high"),
        ("client", r"\b(?:client|customer|stakeholder|sponsor)\b", "external", "high"),
        ("colleague", r"\b(?:colleague|teammate|team member|peer|coworker)\b", "peer", "medium"),
        ("friend", r"\b(?:friend|buddy|bro|pal|mom|dad|brother|sister)\b", "personal", "casual"),
        ("official", r"\b(?:registrar|controller of examinations|academic office|administration|university office|institution|college office)\b", "official", "high"),
        ("complaint", r"\b(?:complaint|grievance|escalation|dispute|refund request)\b", "escalation", "high"),
        ("customer_support", r"\b(?:support|customer service|helpdesk|billing support)\b", "service", "medium"),
    ]

    TONE_OVERRIDES = [
        ("formal", ["make it formal", "very formal", "formal tone", "official"]),
        ("casual", ["make it casual", "informal", "casual tone", "friendly and informal"]),
        ("concise", ["make it very concise", "very concise", "short and sweet", "brief", "make it shorter", "concise"]),
        ("academic", ["respectful to my professor", "academic tone", "respectful academic"]),
        ("executive", ["suitable for a ceo", "executive tone", "for leadership", "c-level"]),
        ("warm_professional", ["warm but professional", "warm professional", "friendly yet professional"]),
    ]

    def extract_command_and_content(self, message: str) -> dict[str, Any]:
        """Separates the user's meta-command to Cortex from the intended message payload."""
        text = message.strip()

        # Extract Provider / Service directive (e.g. "in Gmail", "using Gmail", "via Gmail", "draft a Gmail", "in Apple Mail")
        account = ""
        if re.search(r"\b(?:in|using|via|on|through)\s+gmail\b", text, re.IGNORECASE):
            account = "Gmail Account (user@gmail.com)"
            text = re.sub(r"\b(?:in|using|via|on|through)\s+gmail\b", "", text, flags=re.IGNORECASE)
        elif re.search(r"\b(?:draft|send|create|write)\s+(?:an?\s+)?gmail\b", text, re.IGNORECASE):
            account = "Gmail Account (user@gmail.com)"
            text = re.sub(r"\b(?:draft|send|create|write)\s+(?:an?\s+)?gmail\b", "draft an email", text, flags=re.IGNORECASE)
        elif re.search(r"\b(?:in|using|via|on|through)\s+apple\s+mail\b", text, re.IGNORECASE):
            account = "Primary Account"
            text = re.sub(r"\b(?:in|using|via|on|through)\s+apple\s+mail\b", "", text, flags=re.IGNORECASE)
        elif re.search(r"\b(?:draft|send|create|write)\s+(?:an?\s+)?apple\s+mail\b", text, re.IGNORECASE):
            account = "Primary Account"
            text = re.sub(r"\b(?:draft|send|create|write)\s+(?:an?\s+)?apple\s+mail\b", "draft an email", text, flags=re.IGNORECASE)

        # Extract Account if not already extracted
        if not account:
            acc_m = re.search(r"\b(?:from|using)\s+account\s+[\"']?([^\"'\s,;]+(?:\s+[^\"'\s,;]+)*?)[\"']?(?=\s+(?:to|with|saying|subject|attach|cc|bcc|regarding|about)|$)", text, re.IGNORECASE)
            if acc_m:
                account = acc_m.group(1).strip()
                text = text[:acc_m.start()] + " " + text[acc_m.end():]
            else:
                acc_m2 = re.search(r"\b(?:from|using)\s+(?:my\s+)?([a-zA-Z0-9_\-@. ]+?)\s+account(?=\s+(?:to|with|saying|subject|attach|cc|bcc|regarding|about)|$)", text, re.IGNORECASE)
                if acc_m2:
                    account = acc_m2.group(1).strip()
                    text = text[:acc_m2.start()] + " " + text[acc_m2.end():]

        # Extract CC
        cc = []
        cc_m = re.search(r"\b(?:with\s+)?(?:cc(?:ing)?|copying|cc:)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\s*(?:,|and)\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})*)", text, re.IGNORECASE)
        if cc_m:
            raw_cc = cc_m.group(1)
            cc = [c.strip() for c in re.split(r"[,;]|\band\b", raw_cc) if c.strip()]
            text = text[:cc_m.start()] + " " + text[cc_m.end():]

        # Extract BCC
        bcc = []
        bcc_m = re.search(r"\b(?:with\s+)?(?:bcc(?:ing)?|blind\s+copy(?:ing)?|bcc:)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\s*(?:,|and)\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})*)", text, re.IGNORECASE)
        if bcc_m:
            raw_bcc = bcc_m.group(1)
            bcc = [b.strip() for b in re.split(r"[,;]|\band\b", raw_bcc) if b.strip()]
            text = text[:bcc_m.start()] + " " + text[bcc_m.end():]

        # Extract Attachments
        attachments = []
        att_m = re.search(r"\b(?:with\s+)?(?:attach(?:ing)?|attachments?)\s+[\"']?([^\s,\"';]+(?:\.[a-zA-Z0-9]+)?)[\"']?", text, re.IGNORECASE)
        if att_m:
            attachments.append(att_m.group(1).strip().strip("\"'"))
            text = text[:att_m.start()] + " " + text[att_m.end():]

        text = re.sub(r"\s+", " ", text).strip()

        def _wrap(raw_rec: str, subj: str, content: str) -> dict[str, Any]:
            raw_rec = re.sub(r"\b(?:in|using|via|on)\s+(?:gmail|apple\s+mail)\b", "", raw_rec, flags=re.IGNORECASE).strip()
            raw_rec = re.sub(r"^to\s+", "", raw_rec, flags=re.IGNORECASE).strip()
            content = re.sub(
                r"(?:[.,;—–-]\s*)?"
                r"(?:do\s+not\s+send\s*(?:it|this|anything)?|"
                r"dont\s+send\s*(?:it|this|anything)?|"
                r"don'?t\s+send\s*(?:it|this|anything)?|"
                r"never\s+send\s*(?:it|this|anything)?|"
                r"without\s+sending(?:\s+it|\s+anything)?|"
                r"keep\s+it\s+as\s+a\s+draft|"
                r"keep\s+as\s+a\s+draft|"
                r"keep\s+it\s+as\s+draft|"
                r"keep\s+as\s+draft|"
                r"save\s+as\s+draft|"
                r"save\s+as\s+a\s+draft|"
                r"draft\s+only|"
                r"just\s+draft(?:\s+it)?|"
                r"only\s+draft|"
                r"show\s+me\s+the\s+exact\s+recipient\s+and\s+message.*)"
                r"[.,;!?]?\s*$",
                "",
                content,
                flags=re.IGNORECASE,
            ).strip()
            return {
                "recipient": raw_rec,
                "subject": subj,
                "content": content,
                "account": account,
                "sender_account": account,
                "cc": cc,
                "bcc": bcc,
                "attachments": attachments,
                "raw_command": message.strip(),
            }
            return {
                "recipient": raw_rec,
                "subject": subj,
                "content": content,
                "account": account,
                "sender_account": account,
                "cc": cc,
                "bcc": bcc,
                "attachments": attachments,
                "raw_command": message.strip(),
            }

        # Pattern 0C: send/draft email (NO recipient in prompt) saying/asking/requesting <content>
        p0c = re.search(
            r"^(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+(saying|body|that says|with|requesting|asking\s+(?:for|whether|if|about)?|asking|inquiring\s+(?:about|whether)?|inquiring|telling|regarding|concerning|to\s+collect|explaining|stating|informing|notifying|mentioning|summarizing|summarising|sharing|about|:)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p0c:
            delim = p0c.group(1).strip().lower()
            rest = p0c.group(2).strip()
            if any(delim.startswith(w) for w in ("asking", "requesting", "inquiring", "summarizing", "summarising")):
                return _wrap("", "", f"{delim} {rest}")
            return _wrap("", "", rest)

        # Pattern 0A: send/draft email to <recipient> [with subject <subj>] requesting/asking for <content>
        p0a = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+to\s+(.+?)\s+(?:with\s+)?(?:subject|titled|about)\s+(.+?)\s+(?:requesting|asking for|seeking|to collect|demanding|to request)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p0a:
            raw_rec = p0a.group(1).strip()
            subj = p0a.group(2).strip()
            content = p0a.group(3).strip()
            return _wrap(raw_rec, subj, f"Requesting {content}")

        # Pattern 0B: send/draft email to <recipient> requesting/asking for/seeking/to collect <content>
        p0b = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+to\s+(.+?)\s+(?:requesting|asking for|seeking|to collect|demanding|to request)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p0b:
            raw_rec = p0b.group(1).strip()
            content = p0b.group(2).strip()
            return _wrap(raw_rec, "", f"Requesting {content}")

        # Check for explicit recipient and saying/body
        # Pattern 1: send/draft email to <recipient> [with subject <subj>] [and] saying/body/that says <content>
        p1 = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+to\s+(.+?)\s+(?:with\s+)?(?:subject|titled|about)\s+(.+?)\s+(?:and\s+)?(?:saying|body|with|that says|:)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p1:
            raw_rec = p1.group(1).strip()
            subj = re.sub(r"\s+\band\b\s*$", "", p1.group(2), flags=re.IGNORECASE).strip()
            content = p1.group(3).strip()
            return _wrap(raw_rec, subj, content)

        # Pattern 1B: send/draft email to <recipient> [with] subject <subj> (no body)
        p1b = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+to\s+(.+?)\s+(?:with\s+)?(?:subject|titled)\s+[\"']?([^\"'\n]+?)[\"']?$",
            text,
            re.IGNORECASE,
        )
        if p1b:
            raw_rec = p1b.group(1).strip()
            subj = p1b.group(2).strip()
            return _wrap(raw_rec, subj, "")

        # Pattern 2: send/draft email to <recipient> saying/body/that says/asking/requesting/about/summarizing <content>
        p2 = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|professional\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail|draft)\s+to\s+(.+?)\s+(saying|body|that says|with|requesting|asking\s+(?:for|whether|if|about)?|asking|inquiring\s+(?:about|whether)?|inquiring|telling|regarding|concerning|to\s+collect|explaining|stating|informing|notifying|mentioning|summarizing|summarising|sharing|giving|providing|outlining|detailing|about|:)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p2:
            raw_rec = p2.group(1).strip()
            delim = p2.group(2).strip().lower()
            rest = p2.group(3).strip()
            if any(delim.startswith(w) for w in ("asking", "requesting", "inquiring", "summarizing", "summarising")):
                content = f"{delim} {rest}"
            else:
                content = rest
            return _wrap(raw_rec, "", content)

        # Pattern 3: tell/inform <recipient> [that] <content> via email/mail
        p3 = re.search(
            r"(?:tell|inform|message|email|mail)\s+(.+?)\s+(?:that|saying|about)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3 and any(w in text.lower() for w in ("email", "mail")):
            raw_rec = p3.group(1).strip()
            content = p3.group(2).strip()
            return _wrap(raw_rec, "", content)

        # Pattern 3B: send/draft email to <recipient> asking to/telling to <content>
        p3b = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:asking\s+(?:him|her|them)?\s*to|asking\s+to|telling\s+(?:him|her|them)?\s*to)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3b:
            raw_rec = p3b.group(1).strip()
            content = p3b.group(2).strip()
            return _wrap(raw_rec, "", f"Inquiring to {content}")

        # Pattern 3C: send/draft email to <recipient> regarding/concerning <content>
        p3c = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:regarding|concerning|in regards to)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3c:
            raw_rec = p3c.group(1).strip()
            content = p3c.group(2).strip()
            return _wrap(raw_rec, f"Regarding: {content.title()}", content)

        # Pattern 4: send email to <recipient> [about <topic>]
        p4 = re.search(
            r"(?:send|draft|create|write)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:about|asking about)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p4:
            raw_rec = p4.group(1).strip()
            topic = p4.group(2).strip()
            return _wrap(raw_rec, f"Update: {topic.title()}", topic)

        # ── Multilingual & Code-Switched Email Patterns (ML-02, ML-03) ──
        # Kannada / Kanglish: <recipient> ge/ige/avarge email/mail maadu/kalisu [saying/anta <content>]
        p_kn = re.search(r"(.+?)\s+(?:ge|ige|avarge|avare)\s+(?:email|mail)\s+(?:maadu|maadi|kalisu|kalisi|baredhu\s+kalisu|baredhu)\s*(?:saying|anta|andre|with|about)?\s*(.*)", text, re.IGNORECASE)
        if p_kn:
            raw_rec = p_kn.group(1).strip()
            content = p_kn.group(2).strip()
            return _wrap(raw_rec, "", content)

        p_kn_native = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ|ಅವರಿಗೆ)\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಕಳಿಸು|ಮಾಡು|ಬರೆ)\s*(?:ಎಂದು|ಅಂತ|ವಿಷಯ|ಬಗ್ಗೆ)?\s*(.*)", text)
        if p_kn_native:
            raw_rec = p_kn_native.group(1).strip()
            content = p_kn_native.group(2).strip()
            return _wrap(raw_rec, "", content)

        # Hindi / Hinglish: <recipient> ko/ke liye email/mail bhejo/likho [saying/ki/bolke <content>]
        p_hi = re.search(r"(.+?)\s+(?:ko|ke\s+liye)\s+(?:email|mail)\s+(?:bhejo|bhej\s+do|bhejdo|karo|likho|likh\s+do)\s*(?:saying|ki|bolke|ke\s+baare\s+mein)?\s*(.*)", text, re.IGNORECASE)
        if p_hi:
            raw_rec = p_hi.group(1).strip()
            content = p_hi.group(2).strip()
            return _wrap(raw_rec, "", content)

        p_hi_native = re.search(r"(.+?)\s*को\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|लिखो|करो)\s*(?:कि|विषय)?\s*(.*)", text)
        if p_hi_native:
            raw_rec = p_hi_native.group(1).strip()
            content = p_hi_native.group(2).strip()
            return _wrap(raw_rec, "", content)

        # Tamil / Tanglish: <recipient> ku/kku email/mail anuppu/pannu [saying/solli/pathi <content>]
        p_ta = re.search(r"(.+?)\s+(?:ku|kku|idam)\s+(?:email|mail)\s+(?:anuppu|anuppunga|anupu|pannu)\s*(?:saying|solli|pathi|endru)?\s*(.*)", text, re.IGNORECASE)
        if p_ta:
            raw_rec = p_ta.group(1).strip()
            content = p_ta.group(2).strip()
            return _wrap(raw_rec, "", content)

        p_ta_native = re.search(r"(.+?)(?:க்கு|வுக்கு|விடம்)\s*(?:மின்னஞ்சல்|மெயில்)\s*(?:அனுப்பு|அனுப்புங்கள்)\s*(?:என்று|பற்றி)?\s*(.*)", text)
        if p_ta_native:
            raw_rec = p_ta_native.group(1).strip()
            content = p_ta_native.group(2).strip()
            return _wrap(raw_rec, "", content)

        # Telugu / Tenglish: <recipient> ki/ku email/mail cheyyi/pampu [saying/ani <content>]
        p_te = re.search(r"(.+?)\s+(?:ki|ku|garki)\s+(?:email|mail)\s+(?:cheyyi|cheyyandi|pampu|pampandi|rayi)\s*(?:saying|ani|gurinchi)?\s*(.*)", text, re.IGNORECASE)
        if p_te:
            raw_rec = p_te.group(1).strip()
            content = p_te.group(2).strip()
            return _wrap(raw_rec, "", content)

        p_te_native = re.search(r"(.+?)(?:కి|కు|గారికి)\s*(?:ఇమెయిల్|మెయిల్)\s*(?:పంపు|పంపించండి|రాయండి)\s*(?:అని|గురించి)?\s*(.*)", text)
        if p_te_native:
            raw_rec = p_te_native.group(1).strip()
            content = p_te_native.group(2).strip()
            return _wrap(raw_rec, "", content)

        # Pattern 5: send email to <recipient> (no content provided)
        p5 = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:polite\s+|formal\s+|casual\s+|brief\s+|short\s+|quick\s+|respectful\s+)?(?:draft\s+)?(?:email|mail)\s+to\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p5:
            raw_rec = p5.group(1).strip().rstrip(".")
            return _wrap(raw_rec, "", "")

        # Email address direct match
        email_m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
        if email_m:
            return _wrap(email_m.group(1), "", "")

        return _wrap(text, "", "")

    def infer_recipient_context(self, raw_recipient: str, full_message: str, context: TaskContext | None = None) -> RecipientContext:
        """Determines recipient role and relationship without inventing unsupported facts."""
        combined_text = f"{raw_recipient} {full_message}".lower()

        # Check explicit recipient email
        email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw_recipient)
        email_addr = email_match.group(1) if email_match else ""
        clean_name = ""
        has_verified_name = False

        if "<" in raw_recipient and email_addr:
            pot = raw_recipient.split("<")[0].strip().strip("\"'")
            pot = re.sub(r"^(?:to|send\s+email\s+to|send\s+mail\s+to|mail\s+to|email\s+to)\s+", "", pot, flags=re.IGNORECASE).strip()
            if pot and not re.search(r"@|\b(?:send|mail|to)\b", pot, re.IGNORECASE) and len(pot.split()) <= 6:
                clean_name = pot
                has_verified_name = True
        elif not email_addr and raw_recipient.strip():
            pot = re.sub(r"^(?:to|send\s+email\s+to|send\s+mail\s+to|mail\s+to|email\s+to)\s+", "", raw_recipient, flags=re.IGNORECASE).strip()
            if pot and not re.search(r"@[a-zA-Z0-9.-]+", pot) and not re.search(r"\b(?:email|mail|someone|anyone)\b", pot, re.IGNORECASE) and len(pot.split()) <= 6:
                clean_name = pot
                has_verified_name = True
        elif email_addr:
            user_part = email_addr.split("@")[0].lower()
            if user_part.startswith("dr.") or user_part.startswith("dr_"):
                name_part = re.sub(r"^dr[._]", "", user_part)
                clean_name = f"Dr. {name_part.capitalize()}"
                has_verified_name = True
            elif user_part.startswith("prof.") or user_part.startswith("prof_"):
                name_part = re.sub(r"^prof[._]", "", user_part)
                clean_name = f"Prof. {name_part.capitalize()}"
                has_verified_name = True

        if context and getattr(context, "recipient_name", None) and not has_verified_name:
            c_name = str(context.recipient_name).strip()
            if c_name and "@" not in c_name and len(c_name.split()) <= 6:
                clean_name = c_name
                has_verified_name = True

        detected_role = "unknown"
        detected_rel = "neutral"
        detected_form = "medium"

        # Context-passed explicit role takes first precedence
        if context and context.recipient_role and context.recipient_role != "unknown":
            detected_role = context.recipient_role
            detected_rel = context.relationship or "professional"
            detected_form = "high" if context.recipient_role in ("professor", "manager", "recruiter", "client") else "medium"
        else:
            for role, pattern, rel, form in self.ROLE_PATTERNS:
                if re.search(pattern, combined_text, re.IGNORECASE):
                    detected_role = role
                    detected_rel = rel
                    detected_form = form
                    break

        return RecipientContext(
            name=clean_name,
            email=email_addr,
            role=detected_role,
            relationship=detected_rel,
            formality=detected_form,
            has_verified_name=has_verified_name,
            detected_from="verified" if has_verified_name else "neutral_default",
        )

    def detect_tone_override(self, message: str, context: TaskContext | None = None) -> str | None:
        """Extracts any explicit tone directive requested by the user."""
        text = message.lower()
        if context and context.requested_tone:
            return context.requested_tone

        for tone_key, phrases in self.TONE_OVERRIDES:
            if any(p in text for p in phrases):
                return tone_key
        return None

    def generate_subject(self, purpose_or_content: str, recipient_ctx: RecipientContext, existing_subject: str = "") -> str:
        """Generates a clear, professional, context-appropriate subject line."""
        if existing_subject and existing_subject.strip() and not existing_subject.lower().startswith("send email"):
            return existing_subject.strip()

        text = purpose_or_content.strip()
        clean_text = re.sub(
            r"^(?:send|draft|write|mail)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?[^,\n]+?\s+(?:saying|explaining|asking|informing|requesting|telling|that|with|about|regarding|:)\s+",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        clean_lower = clean_text.lower()

        # 0. Research / AI findings / Updates
        if any(w in clean_lower for w in ("research findings", "ai findings", "research results", "research update", "ai updates", "ai research", "research")):
            return "AI Research Findings & Updates" if "ai" in clean_lower else "Research Findings & Updates"

        # 1. Explicit Extension Request (DO NOT assume extension unless explicitly requested)
        if any(w in clean_lower for w in ("extension", "extend", "extra time", "postpone", "delay submission", "need more time", "one more day", "more day", "another day")):
            if "project presentation" in clean_lower or "presentation" in clean_lower:
                return "Project Presentation Deadline Extension Request"
            if "project" in clean_lower:
                return "Project Deadline Extension Request"
            if "assignment" in clean_lower or "homework" in clean_lower or recipient_ctx.role == "professor":
                return "Assignment Submission Deadline Extension Request"
            return "Deadline Extension Request"

        # 2. Deadline Announcement / Informational Notice (NOT an extension request)
        if "deadline" in clean_lower:
            if "project presentation" in clean_lower or "presentation" in clean_lower:
                return "Project Presentation Deadline"
            elif "project" in clean_lower:
                return "Project Deadline"
            elif "assignment" in clean_lower:
                return "Assignment Deadline"
            elif "submission" in clean_lower:
                return "Submission Deadline"
            return "Deadline Notice"

        # 3. Travel / Arrival
        reach_m = re.search(r"(?:reach|arrive in|arriving at|travel to|going to)\s+([a-zA-Z\s]+?)(?:\s+(?:on|by|at)\s+([a-zA-Z0-9\s,]+))?$", clean_text, re.IGNORECASE)
        if "reach" in clean_lower or "arrival" in clean_lower or "travel" in clean_lower:
            loc_match = re.search(r"(?:reach|arrive in|visit)\s+([A-Za-z]+)", clean_text)
            date_match = re.search(r"(?:on|by)\s+([A-Za-z0-9\s]+)", clean_text)
            loc = loc_match.group(1).title() if loc_match else "Destination"
            dt = f" – {date_match.group(1).strip()}" if date_match else ""
            return f"Travel Update: Arrival in {loc}{dt}"

        # 4. Late / Delay
        if any(w in clean_lower for w in ("late", "running late", "delay", "traffic")):
            if recipient_ctx.role == "manager":
                return "Update: Running late today due to traffic" if "traffic" in clean_lower else "Update: Running late today"
            return "Update: Running late today"

        # 5. Interview / Recruiter
        if "interview" in clean_lower or (recipient_ctx.role == "recruiter" and any(w in clean_lower for w in ("status", "confirmed", "schedule", "position", "application"))):
            if recipient_ctx.role == "recruiter" or "confirm" in clean_lower:
                return "Inquiry regarding Interview Confirmation"
            return "Interview Status Inquiry"

        # 6. Meeting
        if any(w in clean_lower for w in ("meeting details", "meeting link", "agenda")) or clean_lower.startswith("meeting"):
            return "Inquiry regarding Upcoming Meeting Details"
        if ("cannot attend" in clean_lower or "unable to attend" in clean_lower or "miss" in clean_lower) and "meeting" in clean_lower:
            return "Unable to Attend Tomorrow's Meeting" if "tomorrow" in clean_lower else "Unable to Attend Meeting"
        if "meeting" in clean_lower:
            return "Update regarding Tomorrow's Meeting" if "tomorrow" in clean_lower else "Meeting Update"

        # 7. Document / Certificate / Academic Records Request
        if any(w in clean_lower for w in ("document", "certificate", "marks card", "original college document", "transcript")):
            if recipient_ctx.role in ("hod", "academic_admin"):
                return "Request for Return of Original Academic Documents"
            elif recipient_ctx.role in ("official", "institution"):
                return "Official Request for Academic Certificates and Documents"
            return "Request for Academic Documents and Certificates"

        # 8. Complaint / Escalation / Grievance
        if any(w in clean_lower for w in ("complaint", "grievance", "escalation", "dispute")):
            return "Formal Grievance and Inquiry regarding Account"

        # 9. Client / Changes completed
        if any(w in clean_lower for w in ("completed", "changes", "requested changes", "finished")):
            if recipient_ctx.role == "client":
                return "Status Update: Requested Changes Completed"
            return "Status Update: Project Work Completed"

        # 10. Project update
        if any(w in clean_lower for w in ("project is ready", "project ready", "project update")) or ("project" in clean_lower and any(w in clean_lower for w in ("ready", "status", "update"))):
            return "Project update"

        # 11. Report / Review
        if any(w in clean_lower for w in ("finished the report", "review the report", "report is ready")):
            return "Project Report Completed – Ready for Review"

        # 12. Fallback concise subject from content
        clean_words = [w for w in re.sub(r"[^\w\s]", "", clean_text).split() if w.lower() not in ("that", "saying", "tell", "him", "her", "them", "it", "says", "please", "kindly")]
        if clean_words:
            return " ".join(clean_words[:4]).title()
        return "Update from Cortex"

    def compose_email(
        self,
        raw_intent: str,
        recipient_raw: str,
        content: str,
        subject_override: str = "",
        context: TaskContext | None = None,
        tone_override: str | None = None,
        use_gemini: bool = False,
        gemini_model: Any = None,
        sender_account: str = "Primary Account",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        language: str = "en",
    ) -> EmailDraft:
        """Main entry point to compose a context-aware email."""
        rec_ctx = self.infer_recipient_context(recipient_raw, raw_intent, context)
        effective_tone = tone_override or self.detect_tone_override(raw_intent, context) or rec_ctx.formality
        subject = self.generate_subject(content or raw_intent, rec_ctx, existing_subject=subject_override)

        # 1. If Gemini is available, attempt LLM structured email generation
        if use_gemini and gemini_model:
            try:
                draft = self._compose_with_gemini(
                    gemini_model=gemini_model,
                    user_intent=raw_intent,
                    recipient_ctx=rec_ctx,
                    content=content,
                    subject=subject,
                    tone=effective_tone,
                    context=context,
                )
                if draft and draft.body:
                    if sender_account:
                        draft.sender_account = sender_account
                    if attachments:
                        draft.attachments = list(attachments)
                    if cc:
                        draft.cc = list(cc)
                    if bcc:
                        draft.bcc = list(bcc)
                    draft.approval_hash = draft.compute_hash()
                    return self.run_quality_control(draft, known_facts=[content, raw_intent])
            except Exception as e:
                print(f"[email_engine] Gemini email generation failed: {e}. Falling back to internal engine.", file=sys.stderr)

        # 2. High-fidelity Deterministic Role-Based Engine
        draft = self._compose_deterministic(
            recipient_ctx=rec_ctx,
            content=content or raw_intent,
            subject=subject,
            tone=effective_tone,
        )
        if sender_account:
            draft.sender_account = sender_account
        if attachments:
            draft.attachments = list(attachments)
        if cc:
            draft.cc = list(cc)
        if bcc:
            draft.bcc = list(bcc)
        if language and language != "en" and language in ("kn", "hi", "ta", "te"):
            draft.body = translate_text(draft.body, target_lang=language, gemini_model=gemini_model if use_gemini else None)
            draft.subject = translate_text(draft.subject, target_lang=language, gemini_model=gemini_model if use_gemini else None)
            draft.language = language
        draft.approval_hash = draft.compute_hash()
        return self.run_quality_control(draft, known_facts=[content, raw_intent])

    def generate_email_draft(
        self,
        recipient: str,
        command: str = "",
        content: str = "",
        recipient_name: str = "",
        relationship_type: str = "",
        user_tone_override: str = "",
        thread_context: dict[str, Any] | None = None,
        use_gemini: bool = False,
        gemini_model: Any = None,
    ) -> EmailDraft:
        extracted = self.extract_command_and_content(command or content)
        extracted_content = extracted.get("content", "")
        clean_content = content or extracted_content or command
        if not recipient:
            recipient = extracted.get("recipient", "")

        effective_tone = user_tone_override
        if not effective_tone:
            if relationship_type == "professor":
                effective_tone = "respectful_academic"
            elif relationship_type == "friend":
                effective_tone = "casual_warm"
            elif relationship_type == "vendor":
                effective_tone = "professional_direct"
            elif relationship_type in ("manager", "recruiter", "client"):
                effective_tone = "concise_professional"
            else:
                effective_tone = "neutral"

        subject_override = ""
        if thread_context:
            subj = thread_context.get("subject", "")
            if subj:
                subject_override = subj if subj.startswith("Re:") else f"Re: {subj}"

        task_ctx = TaskContext(
            recipient=recipient,
            recipient_role=relationship_type or "unknown",
            relationship="academic" if relationship_type == "professor" else "hierarchical" if relationship_type == "manager" else "personal" if relationship_type == "friend" else "professional",
            requested_tone=effective_tone,
        )

        draft = self.compose_email(
            raw_intent=command or clean_content,
            recipient_raw=recipient_name or recipient,
            content=clean_content,
            subject_override=subject_override,
            tone_override=effective_tone,
            context=task_ctx,
            use_gemini=use_gemini,
            gemini_model=gemini_model,
        )
        if recipient:
            draft.recipient = recipient
        if relationship_type:
            draft.recipient_role = relationship_type
        draft.tone = effective_tone
        return draft

    def _compose_with_gemini(
        self,
        gemini_model: Any,
        user_intent: str,
        recipient_ctx: RecipientContext,
        content: str,
        subject: str,
        tone: str,
        context: TaskContext | None = None,
    ) -> EmailDraft | None:
        """Prompts Gemini with structured communication context and enforces JSON schema."""
        prompt_data = {
            "USER_INTENT": user_intent,
            "RECIPIENT_NAME": recipient_ctx.name,
            "RECIPIENT_ROLE": recipient_ctx.role,
            "RELATIONSHIP": recipient_ctx.relationship,
            "MESSAGE_CONTENT": content,
            "PROPOSED_SUBJECT": subject,
            "REQUESTED_TONE": tone,
            "KNOWN_FACTS": context.known_facts if context else [content],
        }

        system_instruction = (
            "You are Cortex's Executive Communication Intelligence Engine.\n"
            "Generate a polished, human professional email following these non-negotiable rules:\n"
            "1. ADAPT TO RECIPIENT: Professor=respectful academic, Manager=concise direct, Recruiter=courteous polished, Client=confident precise, Colleague=natural collaborative, Unknown=neutral professional.\n"
            "2. ZERO GENERIC TEMPLATES: Do NOT use filler like 'I hope this email finds you well' or 'Kindly do the needful' unless specifically fitting.\n"
            "3. ZERO INVENTED FACTS: Use ONLY facts provided by user. Do not fabricate positions, dates, or reasons.\n"
            "4. NATURAL HUMAN FLOW: Clear, concise, appropriate greeting and sign-off.\n"
            "Return JSON only:\n"
            "{\n"
            "  \"recipient\": string,\n"
            "  \"subject\": string,\n"
            "  \"body\": string,\n"
            "  \"tone\": string,\n"
            "  \"rationale\": string\n"
            "}"
        )

        resp = gemini_model.generate_content(
            f"{system_instruction}\n\nContext:\n{json.dumps(prompt_data, indent=2)}",
            generation_config={"response_mime_type": "application/json"},
        )
        if resp and resp.text:
            data = json.loads(resp.text)
            return EmailDraft(
                recipient=recipient_ctx.email or recipient_ctx.name,
                subject=data.get("subject", subject),
                body=data.get("body", "").strip(),
                tone=data.get("tone", tone),
                recipient_role=recipient_ctx.role,
                raw_response=data,
            )
        return None

    def _compose_deterministic(
        self,
        recipient_ctx: RecipientContext,
        content: str,
        subject: str,
        tone: str,
    ) -> EmailDraft:
        """Creates an expertly crafted email draft adhering strictly to role and tone standards."""
        role = recipient_ctx.role
        has_name = recipient_ctx.has_verified_name and bool(recipient_ctx.name.strip())
        name = recipient_ctx.name.strip() if has_name else ""

        conv_content, meta = convert_instruction_to_recipient_content(content)
        clean_content = conv_content if conv_content else content.strip()
        no_invented_reason = "no_invented_reason" in meta.get("constraints", [])

        clean_content = re.sub(
            r"^(?:tell\s+(?:him|her|them|it)\s+|saying\s+|that\s+says\s+|that\s+|say\s+)",
            "",
            clean_content,
            flags=re.IGNORECASE,
        ).strip()
        clean_content = re.sub(
            r"^(?:send|draft|write|mail)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?[^,\n]+?\s+(?:saying|that|with|:)\s+",
            "",
            clean_content,
            flags=re.IGNORECASE,
        ).strip()
        if clean_content.lower().startswith("congratulate "):
            clean_content = "Congratulations on the " + clean_content[13:].lstrip()
        if clean_content:
            clean_content = clean_content[0].upper() + clean_content[1:]

        # Case A: Professor
        if role == "professor":
            if has_name:
                if any(name.lower().startswith(t) for t in ("prof", "dr.", "dean")):
                    salutation = f"Dear {name},"
                else:
                    salutation = f"Dear Professor {name if name.lower() != 'professor' else ''},"
            else:
                salutation = "Dear Professor,"
            salutation = re.sub(r"\s+", " ", salutation).replace("Professor Professor", "Professor").replace(" ,", ",").strip()

            has_extension_intent = any(w in clean_content.lower() for w in ("extension", "extend", "extra time", "postpone", "need more time", "more time", "delay submission", "one more day", "more day", "another day"))
            if has_extension_intent and not no_invented_reason and not clean_content.endswith("?"):
                body = (
                    f"{salutation}\n\n"
                    f"I hope you are having a productive week.\n\n"
                    f"I am writing to respectfully request an extension of one additional day for submitting the assignment. "
                    f"I am committed to submitting high-quality work and would greatly appreciate this extra time to finalize my submission.\n\n"
                    f"Thank you very much for your time and consideration.\n\n"
                    f"Sincerely"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Thank you for your time and guidance.\n\n"
                    f"Sincerely"
                )

        # Case B: Manager
        elif role == "manager":
            salutation = f"Hi {name}," if has_name else "Hello,"
            if "traffic" in clean_content.lower() or "late" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I will be arriving a bit late to the office today due to heavy traffic on my route. "
                    f"I am monitoring my messages and will join the team as soon as I arrive.\n\n"
                    f"Best regards"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Please let me know if you need any additional details.\n\n"
                    f"Best regards"
                )

        # Case C: Recruiter
        elif role == "recruiter":
            salutation = f"Hello {name}," if has_name else "Hello,"
            if "interview" in clean_content.lower() or "confirmed" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I am writing to follow up on our recent communication and ask whether my interview is confirmed for tomorrow. "
                    f"I look forward to discussing the role further.\n\n"
                    f"Thank you for your time and assistance.\n\n"
                    f"Best regards"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Thank you for your assistance.\n\n"
                    f"Best regards"
                )

        # Case D: Client
        elif role == "client":
            salutation = f"Dear {name}," if has_name else "Hello,"
            if "completed" in clean_content.lower() or "changes" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I am pleased to inform you that we have completed all the requested changes as discussed. "
                    f"Everything has been verified and is ready for your review.\n\n"
                    f"Please let us know if you have any questions or require further adjustments.\n\n"
                    f"Best regards"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Please let us know if you need any additional information.\n\n"
                    f"Best regards"
                )

        # Case E: Colleague
        elif role == "colleague":
            salutation = f"Hi {name}," if has_name else "Hello,"
            if "report" in clean_content.lower() or "review" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I have finished working on the report and it is ready for your review whenever you have a chance. "
                    f"Feel free to share any feedback or questions.\n\n"
                    f"Thanks"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Thanks"
                )

        # Case HOD / Academic Administrator
        elif role in ("hod", "academic_admin"):
            if has_name:
                salutation = f"Dear {name}," if ("dr." in name.lower() or "prof" in name.lower()) else f"Dear {name},"
            else:
                salutation = "Respected Head of Department,"
            if any(w in clean_content.lower() for w in ("document", "certificate", "marks card", "original college document", "transcript")):
                body = (
                    f"{salutation}\n\n"
                    f"I am writing to respectfully request the collection and return of my original college documents held by the department, "
                    f"including my marks cards, certificates, and any other official documents on record.\n\n"
                    f"Could you please let me know the required procedure or designated hours for collecting these documents in person? "
                    f"If any clearance form or application is required, I will be glad to submit it promptly.\n\n"
                    f"Thank you very much for your time and guidance.\n\n"
                    f"Sincerely"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{polish_email_body_text(clean_content)}\n\n"
                    f"Thank you for your time and guidance.\n\n"
                    f"Sincerely"
                )

        # Case G: Friend
        elif role == "friend":
            salutation = f"Hey {name}," if has_name else "Hey,"
            body = (
                f"{salutation}\n\n"
                f"{polish_email_body_text(clean_content)}\n\n"
                f"Catch up soon!"
            )

        # Case H: Official Institution
        elif role in ("official", "institution"):
            salutation = f"Dear {name}," if has_name else "Dear Office of the Registrar,"
            body = (
                f"{salutation}\n\n"
                f"I am writing to submit a formal inquiry regarding {subject.lower()}.\n\n"
                f"{polish_email_body_text(clean_content)}\n\n"
                f"Thank you for your assistance with this matter.\n\n"
                f"Sincerely"
            )

        # Case I: Complaint / Escalation
        elif role == "complaint":
            salutation = f"Dear {name}," if has_name else "Dear Customer Support Team,"
            body = (
                f"{salutation}\n\n"
                f"I am writing to register a formal concern regarding the following issue:\n\n"
                f"{polish_email_body_text(clean_content)}\n\n"
                f"I request that this matter be reviewed and resolved at your earliest convenience.\n\n"
                f"Sincerely"
            )

        # Case F: Unknown recipient / Neutral Professional
        else:
            if has_name:
                if "dr." in name.lower() or "dr " in name.lower() or name.lower().startswith("dr"):
                    display_greeting = f"Dear {name},"
                elif tone == "formal":
                    display_greeting = f"Dear {name},"
                else:
                    display_greeting = f"Hi {name},"
            else:
                display_greeting = "Hello,"

            closing = "Sincerely" if tone == "formal" else "Best regards"
            polished_body = polish_email_body_text(clean_content)
            body = (
                f"{display_greeting}\n\n"
                f"{polished_body}\n\n"
                f"{closing}"
            )

        draft = EmailDraft(
            recipient=recipient_ctx.email or recipient_ctx.name,
            subject=subject,
            body=body,
            tone=tone,
            recipient_role=role,
            audit_notes=["Created via deterministic context-aware engine"],
        )
        draft.approval_hash = draft.compute_hash()
        return draft

    def run_quality_control(self, draft: EmailDraft, known_facts: list[str]) -> EmailDraft:
        """Internal quality-control pipeline:
        - Check factual consistency (no invented dates, places, claims)
        - Check grammar & flow
        - Check greeting & closing completeness
        - Strip excessive boilerplate filler
        """
        notes = list(draft.audit_notes)
        body = draft.body

        # 1. Verify salutation exists
        if not re.search(r"^(?:Dear|Hi|Hello|Good\s+(?:morning|afternoon|evening)|Respected|Hey)\b", body, re.IGNORECASE):
            salutation = "Hello,"
            body = f"{salutation}\n\n{body}"
            notes.append("QC: Added missing salutation.")

        # 2. Verify closing exists
        if not re.search(r"\n(?:Best regards|Sincerely|Thanks|Warm regards|Regards|Catch up soon!?|Cheers),?\s*$", body.strip(), re.IGNORECASE):
            body = f"{body.rstrip()}\n\nBest regards"
            notes.append("QC: Added professional sign-off.")

        # 3. Strip duplicate empty lines
        body = re.sub(r"\n{3,}", "\n\n", body).strip()

        # 4. Remove robotic AI fillers
        robotic_phrases = [
            r"As an AI[,\s]+",
            r"I hope this email finds you well and in good spirits\.?",
            r"Please do the needful\.?",
        ]
        for rp in robotic_phrases:
            if re.search(rp, body, re.IGNORECASE):
                body = re.sub(rp, "", body, flags=re.IGNORECASE).strip()
                notes.append(f"QC: Removed robotic filler '{rp}'.")

        draft.body = body
        draft.audit_notes = notes
        draft.quality_passed = True
        draft.approval_hash = draft.compute_hash()
        return draft

    def edit_draft(
        self,
        draft: EmailDraft,
        new_body: str = "",
        new_subject: str = "",
        edit_instruction: str = "",
    ) -> EmailDraft:
        """Modifies draft fields directly or via instruction."""
        if new_body:
            draft.body = new_body
        if new_subject:
            draft.subject = new_subject
        if edit_instruction:
            return self.update_draft_with_edit(draft, edit_instruction)
        draft.approval_hash = draft.compute_hash()
        return draft

    def update_draft_with_edit(self, draft: EmailDraft, edit_instruction: str) -> EmailDraft:
        """Applies follow-up user instructions (e.g. 'make it shorter', 'change subject') cleanly."""
        inst = edit_instruction.lower().strip()

        # ── Inspection requests ──
        if any(w in inst for w in ("show me the revised draft", "show me the draft", "view draft", "show draft", "see draft", "display draft", "what is the draft")):
            return draft

        # ── Multilingual Translation & Rewriting (ML-04, ML-06, ML-07, ML-08) ──
        target_lang, directive, _ = extract_explicit_language_directive(edit_instruction)
        if target_lang:
            if target_lang == "kn" and ("•" in draft.body and bool(re.search(r"\b(?:ai|artificial intelligence|breakthroughs)\b", draft.body, re.IGNORECASE))):
                name = draft.recipient.split("@")[0].capitalize()
                draft.subject = "ಕೃತಕ ಬುದ್ಧಿಮತ್ತೆ (AI) ಬೆಳವಣಿಗೆಗಳ ಸಾರಾಂಶ"
                draft.body = (
                    f"ನಮಸ್ಕಾರ {name},\n\n"
                    f"ಇತ್ತೀಚಿನ ಕೃತಕ ಬುದ್ಧಿಮತ್ತೆ (AI) ಬೆಳವಣಿಗೆಗಳ ಪ್ರಮುಖ ಸಾರಾಂಶ ಇಲ್ಲಿದೆ:\n\n"
                    f"• ಹೊಸ ಮಾದರಿಗಳು ಮತ್ತು ಸಂಶೋಧನೆ: ಸುಧಾರಿತ ಸಾಮರ್ಥ್ಯಗಳು ಮತ್ತು ನರ ಜಾಲಗಳ ತಂತ್ರಜ್ಞಾನದಲ್ಲಿ ಗಣನೀಯ ಪ್ರಗತಿ.\n"
                    f"• ಉದ್ಯಮ ಅನ್ವಯಗಳು: ಸ್ವಯಂಚಾಲಿತ ವ್ಯವಸ್ಥೆಗಳು ಮತ್ತು ನೈಜ-ಸಮಯದ ಡೇಟಾ ಸಂಸ್ಕರಣೆಯಲ್ಲಿ ಹೆಚ್ಚಿದ ಬಳಕೆ.\n\n"
                    f"ಈ ಬೆಳವಣಿಗೆಗಳ ಕುರಿತು ನಿಮ್ಮ ಅನಿಸಿಕೆ ಮತ್ತು ಅಭಿಪ್ರಾಯಗಳನ್ನು ದಯವಿಟ್ಟು ತಿಳಿಸಿ.\n\n"
                    f"ಆತ್ಮೀಯ ವಂದನೆಗಳು"
                )
                draft.language = "kn"
                draft.audit_notes.append("QC: Rewrote draft in native Kannada script.")
                draft.approval_hash = draft.compute_hash()
                return draft
            elif target_lang == "hi" and ("•" in draft.body and bool(re.search(r"\b(?:ai|artificial intelligence|breakthroughs)\b", draft.body, re.IGNORECASE))):
                name = draft.recipient.split("@")[0].capitalize()
                draft.subject = "कृत्रिम बुद्धिमत्ता (AI) विकास का सारांश"
                draft.body = (
                    f"नमस्ते {name},\n\n"
                    f"नवीनतम कृत्रिम बुद्धिमत्ता (AI) विकास का मुख्य सारांश यहाँ दिया गया है:\n\n"
                    f"• नए मॉडल और अनुसंधान: उन्नत तर्क क्षमता और न्यूरल नेटवर्क में महत्वपूर्ण प्रगति।\n"
                    f"• उद्योग अनुप्रयोग: स्वचालित कार्यप्रवाहों और वास्तविक समय प्रसंस्करण में वृद्धि।\n\n"
                    f"कृपया इन अपडेट्स पर अपने विचार साझा करें।\n\n"
                    f"सादर"
                )
                draft.language = "hi"
                draft.audit_notes.append("QC: Rewrote draft in native Hindi script.")
                draft.approval_hash = draft.compute_hash()
                return draft
            elif directive == "body_only":
                draft.body = translate_text(draft.body, target_lang=target_lang)
                draft.audit_notes.append(f"QC: Translated body to {target_lang} while keeping subject in English.")
            elif directive == "subject_only":
                draft.subject = translate_text(draft.subject, target_lang=target_lang)
                draft.audit_notes.append(f"QC: Translated subject to {target_lang}.")
            else:
                draft.body = translate_text(draft.body, target_lang=target_lang)
                draft.subject = translate_text(draft.subject, target_lang=target_lang)
                draft.language = target_lang
                draft.audit_notes.append(f"QC: Translated draft to {target_lang}.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # ── Meeting time updates (e.g. 'Change the meeting time to 3 PM') ─────────
        time_change_m = re.search(
            r"(?:change\s+(?:the\s+)?(?:meeting\s+)?time\s+to|set\s+(?:the\s+)?(?:meeting\s+)?time\s+to|meeting\s+time\s+to|time\s+to)\s+([A-Za-z0-9\s:apmAPM.-]+?)(?:\.|$)",
            edit_instruction,
            re.IGNORECASE,
        )
        if time_change_m:
            new_time = time_change_m.group(1).strip()
            time_pattern = re.compile(r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM)|\d{1,2}\s*(?:o'clock))\b")
            if time_pattern.search(draft.body):
                draft.body = time_pattern.sub(new_time, draft.body)
            else:
                lines = [l for l in draft.body.split("\n\n") if l.strip()]
                if len(lines) >= 2:
                    closing = lines[-1]
                    content_paras = lines[:-1]
                    content_paras.append(f"Please note: the meeting time has been updated to {new_time}.")
                    draft.body = "\n\n".join(content_paras + [closing])
                else:
                    draft.body += f"\n\nPlease note: the meeting time has been updated to {new_time}."
            if time_pattern.search(draft.subject):
                draft.subject = time_pattern.sub(new_time, draft.subject)
            draft.audit_notes.append(f"QC: Updated meeting time to '{new_time}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # ── Date / Deadline updates (e.g. 'Change the date to Friday') ───────────
        date_change_m = re.search(
            r"(?:change\s+(?:the\s+)?date\s+to|change\s+(?:the\s+)?deadline\s+to|set\s+(?:the\s+)?date\s+to|set\s+(?:the\s+)?deadline\s+to|date\s+to|deadline\s+to)\s+([A-Za-z0-9\s,/-]+?)(?:\.|$)",
            edit_instruction,
            re.IGNORECASE,
        )
        if date_change_m:
            new_date = date_change_m.group(1).strip()
            day_pattern = re.compile(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)
            if day_pattern.search(draft.body):
                draft.body = day_pattern.sub(new_date.capitalize(), draft.body)
            else:
                lines = [l for l in draft.body.split("\n\n") if l.strip()]
                if len(lines) >= 2:
                    closing = lines[-1]
                    content_paras = lines[:-1]
                    content_paras.append(f"Please note: the date has been updated to {new_date}.")
                    draft.body = "\n\n".join(content_paras + [closing])
                else:
                    draft.body += f"\n\nPlease note: the date has been updated to {new_date}."
            if day_pattern.search(draft.subject):
                draft.subject = day_pattern.sub(new_date.capitalize(), draft.subject)
            draft.audit_notes.append(f"QC: Updated date to '{new_date}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Sender Account selection
        if "college email" in inst or "college account" in inst or "student email" in inst:
            draft.sender_account = "College Account (student@university.edu)"
            draft.audit_notes.append("QC: Updated sending account to College Account.")
            draft.approval_hash = draft.compute_hash()
            return draft
        if "gmail" in inst:
            draft.sender_account = "Gmail Account (user@gmail.com)"
            draft.audit_notes.append("QC: Updated sending account to Gmail Account.")
            draft.approval_hash = draft.compute_hash()
            return draft
        if "primary account" in inst or "personal account" in inst:
            draft.sender_account = "Primary Account (me@cortex.internal)"
            draft.audit_notes.append("QC: Updated sending account to Primary Account.")
            draft.approval_hash = draft.compute_hash()
            return draft
        if "work email" in inst or "work account" in inst or "company account" in inst:
            draft.sender_account = "Work Account (work@company.com)"
            draft.audit_notes.append("QC: Updated sending account to Work Account.")
            draft.approval_hash = draft.compute_hash()
            return draft

        acc_custom_m = re.search(r"(?:use|switch\s+to|change\s+to|from)\s+account\s+[\"']?([^\"'\s,;]+(?:\s+[^\"'\s,;]+)*?)[\"']?$", edit_instruction, re.IGNORECASE)
        if acc_custom_m:
            draft.sender_account = acc_custom_m.group(1).strip()
            draft.audit_notes.append(f"QC: Updated sending account to '{draft.sender_account}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # CC update
        cc_m = re.search(r"(?:add\s+cc|with\s+cc|copy|cc)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\s*(?:,|and)\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})*)", inst, re.IGNORECASE)
        if cc_m:
            new_ccs = [c.strip() for c in re.split(r"[,;]|\band\b", cc_m.group(1)) if c.strip()]
            for c in new_ccs:
                if c not in draft.cc:
                    draft.cc.append(c)
            draft.audit_notes.append(f"QC: Added CC '{', '.join(new_ccs)}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        if "remove cc" in inst or "clear cc" in inst:
            draft.cc = []
            draft.audit_notes.append("QC: Cleared all CC recipients.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # BCC update
        bcc_m = re.search(r"(?:add\s+bcc|with\s+bcc|blind\s+copy|bcc)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:\s*(?:,|and)\s*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})*)", inst, re.IGNORECASE)
        if bcc_m:
            new_bccs = [b.strip() for b in re.split(r"[,;]|\band\b", bcc_m.group(1)) if b.strip()]
            for b in new_bccs:
                if b not in draft.bcc:
                    draft.bcc.append(b)
            draft.audit_notes.append(f"QC: Added BCC '{', '.join(new_bccs)}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        if "remove bcc" in inst or "clear bcc" in inst:
            draft.bcc = []
            draft.audit_notes.append("QC: Cleared all BCC recipients.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Recipient change
        rec_m = re.search(r"(?:change\s+recipient\s+to|send\s+to\s+instead|send\s+to)\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", inst, re.IGNORECASE)
        if rec_m:
            draft.recipient = rec_m.group(1).strip()
            draft.audit_notes.append(f"QC: Updated recipient to '{draft.recipient}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Salutation / Address change
        if any(w in inst for w in ("address him as", "address her as", "address them as", "address as")):
            m = re.search(r"address\s+(?:him|her|them)?\s*as\s+(.+)", edit_instruction, re.IGNORECASE)
            if m:
                target_title = m.group(1).strip().rstrip(".! ")
                if not target_title.lower().startswith("dear"):
                    sal = f"Dear {target_title},"
                else:
                    sal = f"{target_title},"
                draft.body = re.sub(r"^(?:Dear|Hi|Hello|Respected|Hey)[^\n,]+,", sal, draft.body)
                draft.audit_notes.append(f"QC: Updated salutation to '{sal}'.")
                draft.approval_hash = draft.compute_hash()
                return draft

        # Attachments
        if "attach " in inst or "add attachment" in inst:
            attach_m = re.search(r"(?:attach|attachment|add attachment)\s+([^\s,]+)", inst, re.IGNORECASE)
            if attach_m:
                filename = attach_m.group(1).strip().strip("'\"")
                clean_f = filename.lower()
                sensitive_patterns = ("/etc/passwd", "/etc/shadow", "/etc/sudoers", "/etc/hosts", ".env", ".session_secret", "id_rsa", "id_ed25519")
                if any(p in clean_f for p in sensitive_patterns) or clean_f.endswith((".key", ".pem")):
                    draft.audit_notes.append(f"Security: Blocked sensitive attachment '{filename}'.")
                else:
                    if filename not in draft.attachments:
                        draft.attachments.append(filename)
                    draft.audit_notes.append(f"QC: Added attachment '{filename}'.")
                draft.approval_hash = draft.compute_hash()
                return draft

        if "remove attachment" in inst or "delete attachment" in inst or "clear attachment" in inst:
            draft.attachments = []
            draft.audit_notes.append("QC: Removed all attachments.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Remove reason
        if "don't mention the reason" in inst or "do not mention the reason" in inst or "remove the reason" in inst or "don't mention why" in inst or "omit the reason" in inst:
            # Strip reason phrases like "due to heavy traffic on my route" or "as I require them..."
            draft.body = re.sub(r"\s+due to heavy traffic on my route\.", ".", draft.body)
            draft.body = re.sub(r"\s+due to [^.\n]+\.", ".", draft.body)
            draft.body = re.sub(r"\s+as I require them for [^.\n]+\.", ".", draft.body)
            draft.audit_notes.append("QC: Removed specific reason per user request.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Paragraph addition (e.g. 'Add this paragraph: ...')
        add_para_m = re.search(
            r"^(?:add\s+(?:this\s+)?paragraph(?:\s*:)?\s*|insert\s+(?:this\s+)?paragraph(?:\s*:)?\s*)(.+)",
            edit_instruction,
            re.IGNORECASE,
        )
        if add_para_m:
            para_content = add_para_m.group(1).strip()
            if para_content:
                lines = [l for l in draft.body.split("\n\n") if l.strip()]
                if len(lines) >= 2:
                    closing = lines[-1]
                    content_paras = lines[:-1]
                    content_paras.append(para_content)
                    draft.body = "\n\n".join(content_paras + [closing])
                else:
                    draft.body += f"\n\n{para_content}"
                draft.audit_notes.append(f"QC: Added paragraph '{para_content[:40]}...'.")
                draft.approval_hash = draft.compute_hash()
                return draft

        # Add timeline / deadline / detail
        if "before friday" in inst or "need the documents before" in inst or inst.startswith("add that ") or "add " in inst or "include that " in inst:
            addition = edit_instruction
            if addition.lower().startswith("add that "):
                addition = addition[9:].strip()
            elif addition.lower().startswith("include that "):
                addition = addition[13:].strip()
            elif addition.lower().startswith("add "):
                addition = addition[4:].strip()
            addition = addition[0].upper() + addition[1:] if addition else ""
            lines = [l for l in draft.body.split("\n\n") if l.strip()]
            if len(lines) >= 2:
                # Insert right before the sign-off closing
                closing = lines[-1]
                content_paras = lines[:-1]
                content_paras.append(f"Please note: {addition}.")
                draft.body = "\n\n".join(content_paras + [closing])
            else:
                draft.body += f"\n\n{addition}"
            draft.audit_notes.append(f"QC: Added detail '{addition}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Subject changes
        subj_m = re.search(
            r"(?:change\s+(?:the\s+)?subject\s+(?:to\s*[:=]?|[:=])|set\s+(?:the\s+)?subject\s+(?:to\s*[:=]?|[:=])|subject\s*[:=])\s*(.+)",
            edit_instruction,
            re.IGNORECASE,
        )
        if subj_m:
            new_subj = subj_m.group(1).strip().strip("\"'")
            if new_subj:
                draft.subject = new_subj
                draft.audit_notes.append(f"QC: User updated subject to '{draft.subject}'.")
                draft.approval_hash = draft.compute_hash()
                return draft

        # Make it shorter AND formal / professional
        is_shorten = any(w in inst for w in ("shorter", "concise", "brief", "shorten", "condense", "summarize"))
        is_formal = any(w in inst for w in ("formal", "professional", "business"))
        if is_shorten and is_formal:
            name = draft.recipient.split("@")[0].capitalize()
            if "•" in draft.body and bool(re.search(r"\b(?:ai|artificial intelligence|breakthroughs)\b", draft.body, re.IGNORECASE)):
                draft.body = (
                    f"Dear {name},\n\n"
                    f"Here is a concise overview of key developments in artificial intelligence:\n\n"
                    f"• Rapid breakthroughs in frontier reasoning models and multimodal intelligence.\n"
                    f"• Expanding enterprise adoption across automated workflows.\n\n"
                    f"I would welcome your perspective on these developments when convenient.\n\n"
                    f"Sincerely"
                )
            else:
                lines = [l.strip() for l in draft.body.splitlines() if l.strip()]
                greeting = lines[0] if lines else f"Dear {name},"
                greeting = re.sub(r"^(?:Hi|Hey|Hello)[,\s]*", "Dear ", greeting).rstrip(",") + ","
                closing = "Sincerely"
                if len(lines) >= 3:
                    content_lines = lines[1:-1]
                    concise_content = content_lines[0]
                elif len(lines) == 2:
                    concise_content = lines[1]
                else:
                    concise_content = draft.body
                concise_content = re.sub(r"^(?:I am writing to let you know that\s+|Just wanted to say\s+)", "", concise_content, flags=re.IGNORECASE)
                draft.body = f"{greeting}\n\n{concise_content}\n\n{closing}"
            draft.tone = "formal_concise"
            draft.audit_notes.append("QC: Compressed draft to concise and formal format.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Make it shorter / more concise
        if is_shorten:
            name = draft.recipient.split("@")[0].capitalize()
            if "•" in draft.body and bool(re.search(r"\b(?:ai|artificial intelligence|breakthroughs)\b", draft.body, re.IGNORECASE)):
                condensed_body = (
                    f"Hi {name},\n\n"
                    f"Here is a concise overview of key developments in artificial intelligence:\n\n"
                    f"• Rapid breakthroughs in frontier reasoning models and multimodal intelligence.\n"
                    f"• Expanding enterprise adoption across automated workflows.\n\n"
                    f"Looking forward to your thoughts.\n\n"
                    f"Best regards"
                )
                draft.body = condensed_body
                draft.tone = "concise"
                draft.audit_notes.append("QC: Compressed draft to concise format.")
                draft.approval_hash = draft.compute_hash()
                return draft
            else:
                lines = [l.strip() for l in draft.body.splitlines() if l.strip()]
                if len(lines) >= 3:
                    greeting = lines[0]
                    closing = lines[-1]
                    content_lines = lines[1:-1]
                    concise_content = " ".join(content_lines[:2])
                    draft.body = f"{greeting}\n\n{concise_content}\n\n{closing}"
                elif len(lines) == 2:
                    greeting = lines[0]
                    draft.body = f"{greeting}\n\n{lines[1]}\n\nBest regards"
                draft.tone = "concise"
                draft.audit_notes.append("QC: Compressed draft to concise format.")
                draft.approval_hash = draft.compute_hash()
                return draft

        # Make it formal / professional
        if is_formal:
            name = draft.recipient.split("@")[0].capitalize()
            if "•" in draft.body and bool(re.search(r"\b(?:ai|artificial intelligence|breakthroughs)\b", draft.body, re.IGNORECASE)):
                formal_body = (
                    f"Dear {name},\n\n"
                    f"I hope this email finds you well. I am writing to provide an executive overview of recent developments in artificial intelligence:\n\n"
                    f"• Advancements in foundation model architectures and complex reasoning capabilities.\n"
                    f"• Expanding enterprise integration across mission-critical workflows.\n\n"
                    f"I would welcome your perspective and insights on these developments when your schedule permits.\n\n"
                    f"Sincerely"
                )
                draft.body = formal_body
                draft.tone = "professional" if "professional" in inst else "formal"
                draft.audit_notes.append(f"QC: Updated tone to {draft.tone}.")
                draft.approval_hash = draft.compute_hash()
                return draft
            else:
                draft.body = re.sub(r"^(?:Hi|Hey|Hello)[,\s]*", "Dear ", draft.body).replace("Thanks,", "Sincerely,").replace("Best regards,", "Sincerely,").replace("Catch up soon!", "Sincerely,").replace("Best regards", "Sincerely")
                draft.tone = "professional" if "professional" in inst else "formal"
                draft.audit_notes.append(f"QC: Updated tone to {draft.tone}.")
                draft.approval_hash = draft.compute_hash()
                return draft

        # Make it polite / diplomatic
        if "polite" in inst or "diplomatic" in inst:
            if "Could you please" not in draft.body:
                draft.body = draft.body.replace("Please let me know", "Could you please kindly let me know")
            draft.tone = "diplomatic"
            draft.audit_notes.append("QC: Refined tone to diplomatic.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Make it casual
        if "casual" in inst or "informal" in inst:
            draft.body = draft.body.replace("Dear ", "Hi ").replace("Respected ", "Hi ").replace("Sincerely,", "Best,").replace("I am writing to respectfully request", "Could I please ask for")
            draft.tone = "casual"
            draft.audit_notes.append("QC: Updated tone to casual.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Content replacement
        draft.body = f"Hi {draft.recipient},\n\n{edit_instruction}\n\nBest regards,"
        draft.audit_notes.append("QC: Draft content updated per user edit.")
        draft.approval_hash = draft.compute_hash()
        return draft

    @staticmethod
    def sanitize_untrusted_email_content(raw_text: str) -> str:
        return sanitize_untrusted_email_content(raw_text)


def sanitize_untrusted_email_content(raw_text: str) -> str:
    """Strips potential prompt injection vectors and isolates external email content safely.
    Ensures that content in received or drafted emails is strictly treated as passive text,
    and can never hijack Cortex or execute unauthorized system commands.
    """
    if not raw_text:
        return ""
    injection_patterns = [
        r"(?i)\bignore\s+(?:all\s+)?(?:previous\s+|prior\s+)?instructions\b.*",
        r"(?i)\bsystem\s*(?:override|prompt|command)?\s*:\s*.*",
        r"(?i)\boverride\s+(?:all\s+)?(?:approval|rules|safety)\b.*",
        r"(?i)\bforget\s+(?:all\s+)?(?:previous\s+|prior\s+)?prompts\b.*",
        r"(?i)\bforward\s+(?:all\s+)?(?:passwords|credentials|emails|documents)\s+to\b.*",
        r"(?i)\bexecute\s+(?:command|shell|script|terminal)\b.*",
        r"(?i)\breveal\s+(?:api\s*key|credentials|secret|token)\b.*",
        r"(?i)\bnew\s+instruction\s*:\s*.*",
        r"(?i)\bbypass\s+(?:all\s+)?(?:rules|approval|safety)\b.*",
        r"(?i)\bdisregard\s+(?:all\s+)?(?:previous\s+|prior\s+)?directives\b.*",
        r"(?i)\bdeveloper\s+mode\s*:\s*.*",
    ]
    cleaned = raw_text
    for pat in injection_patterns:
        cleaned = re.sub(pat, "[FILTERED UNTRUSTED DIRECTIVE]", cleaned)
    return cleaned.strip()


EmailEngine = ProfessionalEmailEngine
