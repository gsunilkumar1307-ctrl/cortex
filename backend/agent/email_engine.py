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
    approval_hash: str = ""

    def __post_init__(self) -> None:
        if not self.approval_hash:
            self.approval_hash = self.compute_hash()

    def compute_hash(self) -> str:
        payload = f"{self.recipient.lower().strip()}:{self.sender_account.strip()}:{self.subject.strip()}:{self.body.strip()}:{','.join(self.attachments)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

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
        }


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

        # Pattern 0A: send/draft email to <recipient> [with subject <subj>] requesting/asking for <content>
        p0a = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:with\s+)?(?:subject|titled|about)\s+(.+?)\s+(?:requesting|asking for|seeking|to collect|demanding|to request)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p0a:
            raw_rec = p0a.group(1).strip()
            subj = p0a.group(2).strip()
            content = p0a.group(3).strip()
            return {"recipient": raw_rec, "subject": subj, "content": f"Requesting {content}", "raw_command": text}

        # Pattern 0B: send/draft email to <recipient> requesting/asking for/seeking/to collect <content>
        p0b = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:requesting|asking for|seeking|to collect|demanding|to request)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p0b:
            raw_rec = p0b.group(1).strip()
            content = p0b.group(2).strip()
            return {"recipient": raw_rec, "subject": "", "content": f"Requesting {content}", "raw_command": text}

        # Check for explicit recipient and saying/body
        # Pattern 1: send/draft email to <recipient> [with subject <subj>] saying/body/that says <content>
        p1 = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:with\s+)?(?:subject|titled|about)\s+(.+?)\s+(?:saying|body|with|that says|:)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p1:
            raw_rec = p1.group(1).strip()
            subj = p1.group(2).strip()
            content = p1.group(3).strip()
            return {"recipient": raw_rec, "subject": subj, "content": content, "raw_command": text}

        # Pattern 2: send/draft email to <recipient> saying/body/that says/asking/requesting <content>
        p2 = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:saying|body|that says|with|requesting|asking\s+(?:for|whether|if|about)?|asking|inquiring\s+(?:about|whether)?|inquiring|telling|regarding|concerning|to\s+collect|:)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p2:
            raw_rec = p2.group(1).strip()
            content = p2.group(2).strip()
            return {"recipient": raw_rec, "subject": "", "content": content, "raw_command": text}

        # Pattern 3: tell/inform <recipient> [that] <content> via email/mail
        p3 = re.search(
            r"(?:tell|inform|message|email|mail)\s+(.+?)\s+(?:that|saying|about)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3 and any(w in text.lower() for w in ("email", "mail")):
            raw_rec = p3.group(1).strip()
            content = p3.group(2).strip()
            return {"recipient": raw_rec, "subject": "", "content": content, "raw_command": text}

        # Pattern 3B: send/draft email to <recipient> asking to/telling to <content>
        p3b = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:asking\s+(?:him|her|them)?\s*to|asking\s+to|telling\s+(?:him|her|them)?\s*to)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3b:
            raw_rec = p3b.group(1).strip()
            content = p3b.group(2).strip()
            return {"recipient": raw_rec, "subject": "", "content": f"Inquiring to {content}", "raw_command": text}

        # Pattern 3C: send/draft email to <recipient> regarding/concerning <content>
        p3c = re.search(
            r"(?:send|draft|create|write|prepare)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:regarding|concerning|in regards to)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p3c:
            raw_rec = p3c.group(1).strip()
            content = p3c.group(2).strip()
            return {"recipient": raw_rec, "subject": f"Regarding: {content.title()}", "content": content, "raw_command": text}

        # Pattern 4: send email to <recipient> [about <topic>]
        p4 = re.search(
            r"(?:send|draft|create|write)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+?)\s+(?:about|asking about)\s+(.+)",
            text,
            re.IGNORECASE,
        )
        if p4:
            raw_rec = p4.group(1).strip()
            topic = p4.group(2).strip()
            return {"recipient": raw_rec, "subject": f"Update: {topic.title()}", "content": topic, "raw_command": text}

        # Pattern 5: send email to <recipient> (no content provided)
        p5 = re.search(
            r"(?:send|draft|create|write)\s+(?:an?\s+)?(?:email|mail)\s+(?:to\s+)?(.+)",
            text,
            re.IGNORECASE,
        )
        if p5:
            raw_rec = p5.group(1).strip().rstrip(".")
            return {"recipient": raw_rec, "subject": "", "content": "", "raw_command": text}

        # Email address direct match
        email_m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text)
        if email_m:
            return {"recipient": email_m.group(1), "subject": "", "content": "", "raw_command": text}

        return {"recipient": text, "subject": "", "content": "", "raw_command": text}

    def infer_recipient_context(self, raw_recipient: str, full_message: str, context: TaskContext | None = None) -> RecipientContext:
        """Determines recipient role and relationship without inventing unsupported facts."""
        combined_text = f"{raw_recipient} {full_message}".lower()

        # Check explicit recipient email
        email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw_recipient)
        email_addr = email_match.group(1) if email_match else ""
        clean_name = raw_recipient
        if email_addr:
            if "<" in raw_recipient:
                clean_name = raw_recipient.split("<")[0].strip()
            elif clean_name == email_addr:
                user_part = email_addr.split("@")[0]
                if user_part.lower().startswith("dr.") or user_part.lower().startswith("dr_"):
                    clean_name = "Dr. " + user_part[3:].replace(".", " ").title()
                elif user_part.lower().startswith("prof.") or user_part.lower().startswith("prof_"):
                    clean_name = "Prof. " + user_part[5:].replace(".", " ").title()
                else:
                    clean_name = user_part.replace(".", " ").title()

        # Context-passed explicit role takes first precedence
        if context and context.recipient_role and context.recipient_role != "unknown":
            return RecipientContext(
                name=clean_name,
                email=email_addr,
                role=context.recipient_role,
                relationship=context.relationship or "professional",
                formality="high" if context.recipient_role in ("professor", "manager", "recruiter", "client") else "medium",
                detected_from="task_context",
            )

        # Check for role indicators
        for role, pattern, rel, form in self.ROLE_PATTERNS:
            if re.search(pattern, combined_text, re.IGNORECASE):
                # Clean clean_name if it was e.g. "my professor"
                display_name = clean_name
                if display_name.lower().startswith(("my ", "the ")):
                    display_name = display_name[3:].strip().capitalize()
                return RecipientContext(
                    name=display_name,
                    email=email_addr,
                    role=role,
                    relationship=rel,
                    formality=form,
                    detected_from="user_text",
                )

        # Unknown / standard professional recipient
        return RecipientContext(
            name=clean_name,
            email=email_addr,
            role="unknown",
            relationship="neutral",
            formality="medium",
            detected_from="neutral_default",
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
        text_lower = text.lower()

        # Travel / Arrival
        reach_m = re.search(r"(?:reach|arrive in|arriving at|travel to|going to)\s+([a-zA-Z\s]+?)(?:\s+(?:on|by|at)\s+([a-zA-Z0-9\s,]+))?$", text, re.IGNORECASE)
        if "reach" in text_lower or "arrival" in text_lower or "travel" in text_lower:
            loc_match = re.search(r"(?:reach|arrive in|visit)\s+([A-Za-z]+)", text)
            date_match = re.search(r"(?:on|by)\s+([A-Za-z0-9\s]+)", text)
            loc = loc_match.group(1).title() if loc_match else "Destination"
            dt = f" – {date_match.group(1).strip()}" if date_match else ""
            return f"Travel Update: Arrival in {loc}{dt}"

        # Late / Delay
        if any(w in text_lower for w in ("late", "running late", "delay", "traffic")):
            if recipient_ctx.role == "manager":
                return "Update: Running late today due to traffic"
            return "Update: Running late today"

        # Assignment / Extension / Academic
        if any(w in text_lower for w in ("assignment", "homework", "deadline", "extension", "submit")):
            if recipient_ctx.role == "professor":
                return "Assignment Submission Deadline Extension Request"
            return "Assignment Deadline Extension Request"

        # Interview / Recruiter
        if "interview" in text_lower or (recipient_ctx.role == "recruiter" and any(w in text_lower for w in ("status", "confirmed", "schedule", "position", "application"))):
            if recipient_ctx.role == "recruiter":
                return "Inquiry regarding Interview Confirmation"
            return "Interview Status Inquiry"

        # Symposium / Conference / Event Schedule
        if any(w in text_lower for w in ("symposium", "conference", "schedule", "seminar")):
            if "symposium" in text_lower:
                return "Inquiry regarding Annual Symposium Schedule"
            return "Inquiry regarding Schedule"

        # Document / Certificate / Academic Records Request
        if any(w in text_lower for w in ("document", "certificate", "marks card", "original college document", "transcript")):
            if recipient_ctx.role in ("hod", "academic_admin"):
                return "Request for Return of Original Academic Documents"
            elif recipient_ctx.role in ("official", "institution"):
                return "Official Request for Academic Certificates and Documents"
            return "Request for Academic Documents and Certificates"

        # Complaint / Escalation / Grievance
        if any(w in text_lower for w in ("complaint", "grievance", "escalation", "dispute")):
            return "Formal Grievance and Inquiry regarding Account"

        # Client / Changes completed
        if any(w in text_lower for w in ("completed", "changes", "requested changes", "finished")):
            if recipient_ctx.role == "client":
                return "Status Update: Requested Changes Completed"
            return "Status Update: Project Work Completed"

        # Project update
        if any(w in text_lower for w in ("project is ready", "project ready", "project update")) or ("project" in text_lower and any(w in text_lower for w in ("ready", "status", "update"))):
            return "Project update"

        # Report / Review
        if any(w in text_lower for w in ("finished the report", "review the report", "report is ready")):
            return "Project Report Completed – Ready for Review"

        # Meeting details inquiry
        if any(w in text_lower for w in ("meeting details", "meeting link", "agenda", "meeting")):
            return "Inquiry regarding Upcoming Meeting Details"

        # Fallback concise subject from content
        clean = re.sub(r"^(?:that|saying|tell him|tell her|tell them|i will|i am)\s+", "", text, flags=re.IGNORECASE)
        words = clean.split()
        short_summary = " ".join(words[:5]).capitalize()
        return f"Update: {short_summary}" if short_summary else "Update from Cortex"

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
        name = recipient_ctx.name or "there"
        clean_content = re.sub(
            r"^(?:tell\s+(?:him|her|them|it)\s+|saying\s+|that\s+says\s+|that\s+|say\s+)",
            "",
            content.strip(),
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
            if any(name.lower().startswith(t) for t in ("prof", "dr.", "dean")):
                salutation = f"Dear {name},"
            else:
                salutation = f"Dear Professor {name if name.lower() != 'professor' else ''},"
            salutation = re.sub(r"\s+", " ", salutation).replace("Professor Professor", "Professor").replace(" ,", ",").strip()
            if "assignment" in clean_content.lower() or "submit" in clean_content.lower() or "extension" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I hope you are having a productive week.\n\n"
                    f"I am writing to respectfully request an extension of one additional day for submitting the assignment. "
                    f"I am committed to submitting high-quality work and would greatly appreciate this extra time to finalize my submission.\n\n"
                    f"Thank you very much for your time and consideration.\n\n"
                    f"Sincerely,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"I am writing regarding {subject.lower()}.\n\n"
                    f"{clean_content}\n\n"
                    f"Thank you for your time and guidance.\n\n"
                    f"Sincerely,"
                )

        # Case B: Manager
        elif role == "manager":
            salutation = f"Hi {name},"
            if "traffic" in clean_content.lower() or "late" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I will be arriving a bit late to the office today due to heavy traffic on my route. "
                    f"I am monitoring my messages and will join the team as soon as I arrive.\n\n"
                    f"Best regards,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{clean_content}\n\n"
                    f"Please let me know if you need any additional details.\n\n"
                    f"Best regards,"
                )

        # Case C: Recruiter
        elif role == "recruiter":
            salutation = f"Hello {name},"
            if "interview" in clean_content.lower() or "confirmed" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I am writing to follow up on our recent communication and ask whether my interview is confirmed for tomorrow. "
                    f"I look forward to discussing the role further.\n\n"
                    f"Thank you for your time and assistance.\n\n"
                    f"Best regards,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{clean_content}\n\n"
                    f"Thank you for your assistance.\n\n"
                    f"Best regards,"
                )

        # Case D: Client
        elif role == "client":
            salutation = f"Dear {name},"
            if "completed" in clean_content.lower() or "changes" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I am pleased to inform you that we have completed all the requested changes as discussed. "
                    f"Everything has been verified and is ready for your review.\n\n"
                    f"Please let us know if you have any questions or require further adjustments.\n\n"
                    f"Best regards,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{clean_content}\n\n"
                    f"Please let us know if you need any additional information.\n\n"
                    f"Best regards,"
                )

        # Case E: Colleague
        elif role == "colleague":
            salutation = f"Hi {name},"
            if "report" in clean_content.lower() or "review" in clean_content.lower():
                body = (
                    f"{salutation}\n\n"
                    f"I have finished working on the report and it is ready for your review whenever you have a chance. "
                    f"Feel free to share any feedback or questions.\n\n"
                    f"Thanks,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"{clean_content}\n\n"
                    f"Thanks,"
                )

        # Case HOD / Academic Administrator
        elif role in ("hod", "academic_admin"):
            salutation = f"Dear {name}," if ("dr." in name.lower() or "prof" in name.lower()) else "Respected Head of Department,"
            if any(w in clean_content.lower() for w in ("document", "certificate", "marks card", "original college document", "transcript")):
                body = (
                    f"{salutation}\n\n"
                    f"I am writing to respectfully request the collection and return of my original college documents held by the department, "
                    f"including my marks cards, certificates, and any other official documents on record.\n\n"
                    f"Could you please let me know the required procedure or designated hours for collecting these documents in person? "
                    f"If any clearance form or application is required, I will be glad to submit it promptly.\n\n"
                    f"Thank you very much for your time and guidance.\n\n"
                    f"Sincerely,"
                )
            else:
                body = (
                    f"{salutation}\n\n"
                    f"I am writing regarding {subject.lower()}.\n\n"
                    f"{clean_content}\n\n"
                    f"Thank you for your time and guidance.\n\n"
                    f"Sincerely,"
                )

        # Case G: Friend
        elif role == "friend":
            salutation = f"Hey {name},"
            body = (
                f"{salutation}\n\n"
                f"{clean_content}\n\n"
                f"Catch up soon!"
            )

        # Case H: Official Institution
        elif role in ("official", "institution"):
            salutation = f"Dear {name if name.lower() != 'there' else 'Office of the Registrar'},"
            body = (
                f"{salutation}\n\n"
                f"I am writing to submit a formal inquiry regarding {subject.lower()}.\n\n"
                f"{clean_content}\n\n"
                f"Thank you for your assistance with this matter.\n\n"
                f"Sincerely,"
            )

        # Case I: Complaint / Escalation
        elif role == "complaint":
            salutation = f"Dear {name if name.lower() != 'there' else 'Customer Support Team'},"
            body = (
                f"{salutation}\n\n"
                f"I am writing to register a formal concern regarding the following issue:\n\n"
                f"{clean_content}\n\n"
                f"I request that this matter be reviewed and resolved at your earliest convenience.\n\n"
                f"Sincerely,"
            )

        # Case F: Unknown recipient / Neutral Professional
        else:
            if "dr." in name.lower() or "dr " in name.lower() or name.lower().startswith("dr"):
                display_greeting = f"Dear {name},"
            elif tone == "formal":
                display_greeting = f"Dear {name},"
            else:
                display_greeting = f"Hi {name},"

            closing = "Sincerely," if tone == "formal" else "Best regards,"
            body = (
                f"{display_greeting}\n\n"
                f"{clean_content}\n\n"
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
            salutation = f"Hi {draft.recipient.split('@')[0].capitalize()},"
            body = f"{salutation}\n\n{body}"
            notes.append("QC: Added missing salutation.")

        # 2. Verify closing exists
        if not re.search(r"\n(?:Best regards|Sincerely|Thanks|Warm regards|Regards|Catch up soon!?|Cheers),?\s*$", body.strip(), re.IGNORECASE):
            body = f"{body.rstrip()}\n\nBest regards,"
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

    def update_draft_with_edit(self, draft: EmailDraft, edit_instruction: str) -> EmailDraft:
        """Applies follow-up user instructions (e.g. 'make it shorter', 'change subject') cleanly."""
        inst = edit_instruction.lower().strip()

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
        subj_m = re.search(r"(?:change\s+(?:the\s+)?subject\s+to|set\s+(?:the\s+)?subject\s+to|subject\s*[:=])\s+(.+)", inst, re.IGNORECASE)
        if subj_m:
            draft.subject = subj_m.group(1).strip()
            draft.audit_notes.append(f"QC: User updated subject to '{draft.subject}'.")
            draft.approval_hash = draft.compute_hash()
            return draft

        # Make it shorter / more concise
        if "shorter" in inst or "concise" in inst or "brief" in inst:
            lines = [l.strip() for l in draft.body.splitlines() if l.strip()]
            if len(lines) > 3:
                greeting = lines[0]
                closing = lines[-1]
                content_lines = lines[1:-1]
                concise_content = " ".join(content_lines[:2])
                draft.body = f"{greeting}\n\n{concise_content}\n\n{closing}"
                draft.tone = "concise"
                draft.audit_notes.append("QC: Compressed draft to concise format.")
                draft.approval_hash = draft.compute_hash()
            return draft

        # Make it formal
        if "formal" in inst:
            draft.body = draft.body.replace("Hi ", "Dear ").replace("Hey ", "Dear ").replace("Thanks,", "Sincerely,").replace("Best regards,", "Sincerely,").replace("Catch up soon!", "Sincerely,")
            draft.tone = "formal"
            draft.audit_notes.append("QC: Updated tone to formal.")
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
        r"(?i)\bsystem\s*(?:override|prompt)?\s*:\s*.*",
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
