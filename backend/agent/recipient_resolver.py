from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

try:
    from backend.core.contracts import (
        ContactResolutionStatus,
        VerifiedContact,
        ContactResolutionResult,
    )
except ImportError:
    from core.contracts import (
        ContactResolutionStatus,
        VerifiedContact,
        ContactResolutionResult,
    )


class WhatsAppContactSource:
    """Abstract interface for a verified WhatsApp contact source."""

    def get_exact_matches(self, name_query: str) -> list[VerifiedContact]:
        raise NotImplementedError

    def get_suggestions(self, query: str) -> list[VerifiedContact]:
        raise NotImplementedError

    def get_contact_by_phone(self, phone: str) -> VerifiedContact | None:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True

    def is_stale(self) -> bool:
        return False

    @property
    def source_name(self) -> str:
        return "user_authorized_contacts"


class UserAuthorizedContactStore(WhatsAppContactSource):
    """Authoritative, user-authorized contact source for WhatsApp.
    Enforces strict exact-match semantics, rejects guessing/substitutions,
    and supports fail-closed availability and staleness controls.
    """

    def __init__(
        self,
        contacts: list[dict[str, Any]] | None = None,
        memory_store: Any = None,
        available: bool = True,
        stale: bool = False,
        source_name: str = "user_authorized_contacts",
    ) -> None:
        self.memory = memory_store
        self._available = available
        self._stale = stale
        self._source_name = source_name
        self._contacts: list[VerifiedContact] = []

        if contacts is not None:
            for c in contacts:
                self._contacts.append(
                    VerifiedContact(
                        id=c.get("id", str(uuid4())[:8]),
                        name=c["name"].strip(),
                        phone=c["phone"].strip(),
                        source=c.get("source", self._source_name),
                        is_verified=c.get("is_verified", True),
                        metadata={"role": c.get("role", "contact")},
                    )
                )
        else:
            loaded_from_mem = False
            if self.memory and hasattr(self.memory, "list"):
                try:
                    items = self.memory.list()
                    for item in items:
                        if isinstance(item, dict) and item.get("category") in ("contact", "contacts"):
                            payload = item.get("payload") or {}
                            if isinstance(payload, dict) and payload.get("name") and payload.get("phone"):
                                self._contacts.append(
                                    VerifiedContact(
                                        id=payload.get("id", str(uuid4())[:8]),
                                        name=payload["name"].strip(),
                                        phone=payload["phone"].strip(),
                                        source=payload.get("source", self._source_name),
                                        is_verified=payload.get("is_verified", True),
                                        metadata={"role": payload.get("role", "contact")},
                                    )
                                )
                                loaded_from_mem = True
                except Exception:
                    pass

            if not loaded_from_mem and not self._contacts:
                seed = [
                    {"id": "c_manu", "name": "Manu", "phone": "+91 99999 88888", "role": "friend"},
                    {"id": "c_rahul", "name": "Rahul", "phone": "+91 98765 43210", "role": "colleague"},
                    {"id": "c_rahul_sharma", "name": "Rahul Sharma", "phone": "+91 98765 43210", "role": "colleague"},
                    {"id": "c_rahul_kn", "name": "ರಾಹುಲ್", "phone": "+91 98765 43210", "role": "colleague"},
                    {"id": "c_priya", "name": "Priya Patel", "phone": "+91 98765 67890", "role": "team lead"},
                    {"id": "c_ananya", "name": "Ananya Rao", "phone": "+91 98765 54321", "role": "researcher"},
                    {"id": "c_alex_mor", "name": "Alex Morgan", "phone": "+91 98765 11111", "role": "designer"},
                    {"id": "c_alex_eng", "name": "Alex Chen", "phone": "+91 98765 22222", "role": "engineer"},
                ]
                for c in seed:
                    self._contacts.append(
                        VerifiedContact(
                            id=c.get("id", str(uuid4())[:8]),
                            name=c["name"],
                            phone=c["phone"],
                            source=self._source_name,
                            is_verified=True,
                            metadata={"role": c.get("role", "contact")},
                        )
                    )

    def is_available(self) -> bool:
        return self._available

    def set_available(self, available: bool) -> None:
        self._available = available

    def is_stale(self) -> bool:
        return self._stale

    def set_stale(self, stale: bool) -> None:
        self._stale = stale

    @property
    def source_name(self) -> str:
        return self._source_name

    def add_contact(self, name: str, phone: str, role: str = "contact", id: str | None = None, source: str | None = None) -> VerifiedContact:
        vc = VerifiedContact(
            id=id or str(uuid4())[:8],
            name=name.strip(),
            phone=phone.strip(),
            source=source or self._source_name,
            is_verified=True,
            metadata={"role": role},
        )
        self._contacts.append(vc)
        if self.memory and hasattr(self.memory, "put"):
            try:
                self.memory.put(f"contact_{vc.id}", "contact", vc.to_dict())
            except Exception:
                pass
        return vc

    def import_contacts(self, contacts: list[dict[str, Any]], source: str = "user_authorized_contacts") -> list[VerifiedContact]:
        imported = []
        for c in contacts:
            if c.get("name") and c.get("phone"):
                vc = self.add_contact(
                    name=c["name"],
                    phone=c["phone"],
                    role=c.get("role", "contact"),
                    id=c.get("id"),
                    source=source,
                )
                imported.append(vc)
        return imported

    def remove_contact(self, contact_id: str) -> bool:
        initial_len = len(self._contacts)
        self._contacts = [c for c in self._contacts if c.id != contact_id]
        return len(self._contacts) < initial_len

    def get_exact_matches(self, name_query: str) -> list[VerifiedContact]:
        """Strict exact match: normalized casefold comparison.
        Never does substring, fuzzy, or phonetic matching.
        """
        if not self._available or self._stale:
            return []

        q_norm = name_query.strip().casefold()
        matches = []
        for c in self._contacts:
            if c.name.strip().casefold() == q_norm:
                matches.append(c)
        return matches

    def get_suggestions(self, query: str) -> list[VerifiedContact]:
        """Finds partial/prefix matches for suggestion only.
        Suggestions are NEVER automatically selected as exact matches.
        """
        if not self._available or self._stale:
            return []

        q_norm = query.strip().casefold()
        if len(q_norm) < 2:
            return []

        suggestions = []
        for c in self._contacts:
            c_norm = c.name.strip().casefold()
            if q_norm in c_norm or any(part == q_norm for part in c_norm.split()):
                if c_norm != q_norm:
                    suggestions.append(c)
        return suggestions

    def get_contact_by_phone(self, phone: str) -> VerifiedContact | None:
        if not self._available or self._stale:
            return None
        clean_target = re.sub(r"[^\d+]", "", phone)
        for c in self._contacts:
            clean_c = re.sub(r"[^\d+]", "", c.phone)
            if clean_c == clean_target:
                return c
        return None


@dataclass
class ResolvedRecipient:
    name: str = ""
    email: str = ""
    phone: str = ""
    role: str = "unknown"
    confidence: float = 0.0
    source: str = "unknown"  # direct, mailbox_search, contacts, thread, manual
    department: str = ""
    institution: str = ""
    context_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "role": self.role,
            "confidence": self.confidence,
            "source": self.source,
            "department": self.department,
            "institution": self.institution,
            "contextNotes": self.context_notes,
        }


@dataclass
class ResolutionResult:
    status: str  # "resolved", "need_clarification", "multiple_candidates"
    recipient: ResolvedRecipient | None = None
    candidates: list[ResolvedRecipient] = field(default_factory=list)
    clarification_prompt: str = ""
    query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recipient": self.recipient.to_dict() if self.recipient else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "clarificationPrompt": self.clarification_prompt,
            "query": self.query,
        }


class RecipientResolver:
    """Intelligently resolves natural language recipient queries to verified identities and email addresses.
    Resolution Priority:
    1. Direct email address syntax
    2. Connected mailbox messages, sender addresses, signatures, and correspondence
    3. Authorized contacts and address books
    4. Relevant existing threads for contextual evidence
    5. Configured institutional directory / web search fallback
    6. Natural follow-up clarification when missing or ambiguous
    """

    # Default institutional / contact knowledge directory (can be enriched via mailbox/memory)
    KNOWN_DIRECTORY = [
        {
            "name": "Dr. K. N. Subramanya",
            "email": "principal@rvce.edu.in",
            "role": "principal",
            "department": "Administration",
            "institution": "RV College of Engineering",
            "keywords": ["principal", "rvce", "administration"],
        },
        {
            "name": "Dr. Shanmukha Nagaraj",
            "email": "hod.cse@rvce.edu.in",
            "role": "hod",
            "department": "Computer Science and Engineering",
            "institution": "RV College of Engineering",
            "keywords": ["hod", "cse", "computer science", "head of department", "rvce"],
        },
        {
            "name": "Dr. B. G. Prasad",
            "email": "hod.cse@bmsce.ac.in",
            "role": "hod",
            "department": "Computer Science and Engineering",
            "institution": "BMS College of Engineering",
            "keywords": ["hod", "cse", "bmsce"],
        },
    ]

    def __init__(
        self,
        mail_automation: Any = None,
        memory_store: Any = None,
        contact_source: WhatsAppContactSource | None = None,
        whatsapp_adapter: Any = None,
    ) -> None:
        self.mail_automation = mail_automation
        self.memory = memory_store
        self.contact_source = contact_source or UserAuthorizedContactStore(memory_store=memory_store)
        self.whatsapp_adapter = whatsapp_adapter

    def resolve(
        self,
        query: str,
        full_message: str = "",
        thread_context: list[dict[str, Any]] | None = None,
        preferred_institution: str = "",
    ) -> ResolutionResult:
        """Main entry point to resolve a recipient query."""
        raw_query = query.strip()
        combined_text = f"{raw_query} {full_message}".lower()

        # ── 0. Self-Identity Detection (myself, me, my email, etc.) ───────────
        clean_q = re.sub(
            r"^(?:(?:send|draft|write|mail|email)\s+(?:an?\s+)?(?:email|mail|it|this)?\s*(?:to\s+)?|to\s+)",
            "",
            raw_query or full_message,
            flags=re.IGNORECASE,
        ).strip().lower().rstrip(".!")
        clean_q_base = re.sub(r"\s+to\s+(?:apply|request|ask|tell|remind|schedule|confirm|submit)\b.*$", "", clean_q, flags=re.IGNORECASE).strip()
        clean_q_base = re.sub(r"\s+(?:about|regarding|concerning|saying|for)\b.*$", "", clean_q_base, flags=re.IGNORECASE).strip()

        self_patterns = (
            "myself", "me", "my email", "my own email", "my own email address", "self", "myself's email",
            "my own gmail", "my own account", "my gmail", "sunil kumar", "sunil"
        )
        is_self = (
            clean_q in self_patterns
            or clean_q_base in self_patterns
            or raw_query.lower() in self_patterns
            or any(clean_q.startswith(p + " ") for p in self_patterns)
        )
        if is_self:
            accounts = []
            if self.mail_automation and hasattr(self.mail_automation, "get_accounts"):
                try:
                    accounts = self.mail_automation.get_accounts()
                except Exception:
                    accounts = []

            # Filter valid accounts with non-empty emails
            valid_accs = [a for a in accounts if a.get("email") and "@" in a.get("email", "")]
            # De-duplicate by email
            unique_accs = []
            seen_emails = set()
            for a in valid_accs:
                em = a["email"].lower().strip()
                if em not in seen_emails:
                    seen_emails.add(em)
                    unique_accs.append(a)

            if len(unique_accs) == 1:
                target_acc = unique_accs[0]
                acc_name = target_acc.get("name", "").strip()
                if not acc_name or acc_name.lower() in ("google", "gmail", "apple", "apple mail", "icloud", "exchange", "outlook", "yahoo"):
                    resolved_name = "Sunil Kumar"
                else:
                    resolved_name = acc_name
                rec = ResolvedRecipient(
                    name=resolved_name,
                    email=target_acc["email"].lower().strip(),
                    role="self",
                    confidence=1.0,
                    source="connected_account",
                    context_notes="User's own connected email account",
                )
                return ResolutionResult(
                    status="resolved",
                    recipient=rec,
                    candidates=[rec],
                    query=raw_query,
                )
            elif len(unique_accs) > 1:
                candidates = [
                    ResolvedRecipient(
                        name=(
                            a.get("name")
                            if a.get("name") and a["name"].lower() not in ("google", "gmail", "apple", "apple mail", "icloud", "exchange", "outlook", "yahoo")
                            else "Sunil Kumar"
                        ),
                        email=a["email"].lower().strip(),
                        role="self",
                        confidence=0.9,
                        source="connected_account",
                        context_notes=f"Connected account: {a.get('name') or a['email']}",
                    )
                    for a in unique_accs
                ]
                acc_options = "\n".join([f"• {c.name} ({c.email})" for c in candidates])
                prompt = (
                    f"You have multiple connected email accounts:\n{acc_options}\n\n"
                    f"Which email address would you like to send this to?"
                )
                return ResolutionResult(
                    status="multiple_candidates",
                    candidates=candidates,
                    clarification_prompt=prompt,
                    query=raw_query,
                )
            else:
                return ResolutionResult(
                    status="source_unavailable",
                    clarification_prompt="No connected email accounts found. Please connect an email account or enter your email address to send an email to yourself.",
                    query=raw_query,
                )

        # ── 1. Direct Email Address Detection ──────────────────────────────────
        direct_emails = re.findall(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw_query)
        if direct_emails:
            if len(direct_emails) == 1:
                email_addr = direct_emails[0].lower()
                name_part = raw_query.replace(email_addr, "").strip().strip("<>()[]\"'")
                name_part = re.sub(r"^(?:to|send\s+email\s+to|send\s+mail\s+to|mail\s+to|email\s+to)\s+", "", name_part, flags=re.IGNORECASE).strip()
                # Never convert username into a presumed personal name
                verified_name = name_part if (name_part and "@" not in name_part and len(name_part.split()) <= 6) else ""

                role = self._infer_role_from_text(f"{raw_query} {full_message}")
                return ResolutionResult(
                    status="resolved",
                    recipient=ResolvedRecipient(
                        name=verified_name or email_addr,
                        email=email_addr,
                        role=role,
                        confidence=1.0,
                        source="direct",
                        context_notes="Direct email address provided by user",
                    ),
                    query=raw_query,
                )
            else:
                clean_emails = [e.lower() for e in direct_emails]
                combined_emails = ", ".join(clean_emails)
                return ResolutionResult(
                    status="resolved",
                    recipient=ResolvedRecipient(
                        name=combined_emails,
                        email=combined_emails,
                        role="multiple",
                        confidence=1.0,
                        source="direct",
                        context_notes=f"Multiple direct email addresses: {combined_emails}",
                    ),
                    query=raw_query,
                )

        # ── 2. Connected Mailbox Search ────────────────────────────────────────
        mailbox_candidates = self._search_mailbox(raw_query, combined_text)
        if len(mailbox_candidates) == 1 and mailbox_candidates[0].confidence >= 0.8:
            return ResolutionResult(
                status="resolved",
                recipient=mailbox_candidates[0],
                candidates=mailbox_candidates,
                query=raw_query,
            )
        elif len(mailbox_candidates) > 1:
            # Check if one matches preferred_institution or exact query
            filtered = self._disambiguate_candidates(mailbox_candidates, combined_text, preferred_institution)
            if len(filtered) == 1:
                return ResolutionResult(
                    status="resolved",
                    recipient=filtered[0],
                    candidates=filtered,
                    query=raw_query,
                )
            return ResolutionResult(
                status="multiple_candidates",
                candidates=mailbox_candidates,
                clarification_prompt=self._format_multiple_candidates_prompt(raw_query, mailbox_candidates),
                query=raw_query,
            )

        # ── 3. Authorized Contacts & Address Book Search ─────────────────────────
        contact_candidates = self._search_contacts(raw_query, combined_text)
        if len(contact_candidates) == 1:
            return ResolutionResult(
                status="resolved",
                recipient=contact_candidates[0],
                candidates=contact_candidates,
                query=raw_query,
            )
        elif len(contact_candidates) > 1:
            filtered = self._disambiguate_candidates(contact_candidates, combined_text, preferred_institution)
            if len(filtered) == 1:
                return ResolutionResult(
                    status="resolved",
                    recipient=filtered[0],
                    candidates=filtered,
                    query=raw_query,
                )
            return ResolutionResult(
                status="multiple_candidates",
                candidates=contact_candidates,
                clarification_prompt=self._format_multiple_candidates_prompt(raw_query, contact_candidates),
                query=raw_query,
            )

        # ── 4. Thread Context Search ───────────────────────────────────────────
        if thread_context:
            thread_cand = self._search_thread_context(raw_query, thread_context)
            if thread_cand:
                return ResolutionResult(
                    status="resolved",
                    recipient=thread_cand,
                    candidates=[thread_cand],
                    query=raw_query,
                )

        # ── 5. Directory Search Fallback ───────────────────────────────────────
        dir_candidates = self._search_directory(raw_query, combined_text, preferred_institution)
        if len(dir_candidates) == 1 and dir_candidates[0].confidence >= 0.75:
            return ResolutionResult(
                status="resolved",
                recipient=dir_candidates[0],
                candidates=dir_candidates,
                query=raw_query,
            )
        elif len(dir_candidates) > 1:
            return ResolutionResult(
                status="multiple_candidates",
                candidates=dir_candidates,
                clarification_prompt=self._format_multiple_candidates_prompt(raw_query, dir_candidates),
                query=raw_query,
            )

        # ── 6. Clarification Required ──────────────────────────────────────────
        clean_role_label = self._clean_role_label(raw_query)
        prompt = (
            f"I couldn't confidently identify the {clean_role_label}'s email address from your mailbox or contacts. "
            f"Could you share the email address or specify which college or institution you mean?"
        )
        return ResolutionResult(
            status="need_clarification",
            clarification_prompt=prompt,
            query=raw_query,
        )

    def resolve_messaging_contact(
        self,
        query: str,
        full_message: str = "",
        channel: str = "whatsapp",
    ) -> ContactResolutionResult:
        """Resolve a contact name or phone number for WhatsApp with strict fail-closed exact matching."""
        raw_query = query.strip()
        cleaned_query = re.sub(
            r"^(?:to|message|send\s+whatsapp\s+to|send\s+message\s+to|text)\s+",
            "",
            raw_query,
            flags=re.IGNORECASE,
        ).strip()
        cleaned_query = re.sub(
            r"\s+(?:saying|that\s+says|with\s+message|say).*$",
            "",
            cleaned_query,
            flags=re.IGNORECASE,
        ).strip()

        # 0. Visible WhatsApp Desktop UI Adapter Check (if configured)
        if getattr(self, "whatsapp_adapter", None) is not None:
            try:
                wa_state = self.whatsapp_adapter.detect_state()
            except Exception as e:
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt=f"WhatsApp Desktop interface error: {e}",
                    source="whatsapp_desktop_ui",
                )

            state_val = getattr(wa_state, "value", str(wa_state))
            if state_val == "app_not_running":
                return ContactResolutionResult(
                    status=ContactResolutionStatus.WHATSAPP_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp Desktop application is not available or running. Please open WhatsApp Desktop and ensure you are logged in.",
                    source="whatsapp_desktop_ui",
                )
            if state_val == "logged_out":
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp Desktop is currently logged out. Please log into WhatsApp Desktop before messages can be routed.",
                    source="whatsapp_desktop_ui",
                )
            if state_val == "error":
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp search selector is missing or UI is unreadable.",
                    source="whatsapp_desktop_ui",
                )
            if state_val == "modal_dialog_present":
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp Desktop has an active modal dialog open. Please dismiss the modal dialog before searching.",
                    source="whatsapp_desktop_ui",
                )
            if state_val == "unsupported_ui_structure":
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp Desktop UI hierarchy could not be parsed by accessibility inspection. Manual contact selection required.",
                    source="whatsapp_desktop_ui",
                )

            # Direct Phone Number Detection with UI adapter
            phone_match = re.search(r"^(\+?\d[\d\s-]{8,}\d)$", cleaned_query)
            if phone_match:
                clean_phone = re.sub(r"[^\d+]", "", phone_match.group(1))
                digits_only = re.sub(r"\D", "", clean_phone)
                if len(digits_only) < 10 or len(digits_only) > 15:
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.NO_MATCH,
                        query=raw_query,
                        clarification_prompt=f"The phone number '{clean_phone}' is invalid. Please provide a valid 10-15 digit phone number.",
                        source="whatsapp_desktop_ui",
                    )
                unverified = VerifiedContact(
                    id=f"direct_{clean_phone}",
                    name=clean_phone,
                    phone=clean_phone,
                    source="user_provided_unverified",
                    is_verified=False,
                    metadata={"type": "unverified_direct_number", "evidence_label": "direct_unverified_number"},
                )
                return ContactResolutionResult(
                    status=ContactResolutionStatus.INVALID_OR_UNVERIFIED_NUMBER,
                    query=raw_query,
                    contact=unverified,
                    candidates=[unverified],
                    clarification_prompt=(
                        f"You provided the direct phone number '{clean_phone}'. "
                        f"This number is not in your verified contacts. "
                        f"Please confirm if you want to send a WhatsApp message to this destination."
                    ),
                    source="whatsapp_desktop_ui",
                )

            # Query visible contacts from adapter
            try:
                candidates = self.whatsapp_adapter.search_visible_contacts(cleaned_query)
            except PermissionError as pe:
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop. Please enable Accessibility permission in macOS System Settings -> Privacy & Security -> Accessibility.",
                    source="whatsapp_desktop_ui",
                )
            except TimeoutError:
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp UI search timed out.",
                    source="whatsapp_desktop_ui",
                )
            except Exception as e:
                err_msg = str(e)
                if "modal" in err_msg.lower():
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                        query=raw_query,
                        clarification_prompt="WhatsApp Desktop has an active modal dialog open. Please dismiss the modal dialog before searching.",
                        source="whatsapp_desktop_ui",
                    )
                if "permission" in err_msg.lower() or "-1743" in err_msg:
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                        query=raw_query,
                        clarification_prompt="macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop. Please enable Accessibility permission in macOS System Settings -> Privacy & Security -> Accessibility.",
                        source="whatsapp_desktop_ui",
                    )
                if "unsupported" in err_msg.lower():
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                        query=raw_query,
                        clarification_prompt="WhatsApp Desktop UI hierarchy could not be parsed by accessibility inspection. Manual contact selection required.",
                        source="whatsapp_desktop_ui",
                    )
                if "stale" in err_msg.lower():
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.CONTACT_DATA_STALE,
                        query=raw_query,
                        clarification_prompt="WhatsApp UI state is stale; window must be refreshed.",
                        source="whatsapp_desktop_ui",
                    )
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt=f"WhatsApp search error: {err_msg}",
                    source="whatsapp_desktop_ui",
                )

            if len(candidates) == 0:
                # WA-CONTACT-12: Synthetic SQLite contact exists but no live UI match -> FAIL CLOSED
                return ContactResolutionResult(
                    status=ContactResolutionStatus.NO_MATCH,
                    query=raw_query,
                    clarification_prompt=f"No contact found for '{cleaned_query}' in WhatsApp visible UI.",
                    source="whatsapp_desktop_ui",
                )

            elif len(candidates) > 1:
                # Multiple candidates -> Disambiguation
                lines = [f"Multiple visible WhatsApp candidates found matching '{cleaned_query}':"]
                cand_list = []
                for i, c in enumerate(candidates, 1):
                    phone_str = f" ({c.phone_number})" if c.phone_number else " [Phone not visible]"
                    lines.append(f"{i}) {c.display_name}{phone_str}")
                    cand_list.append(VerifiedContact(
                        id=f"wa_cand_{i}",
                        name=c.display_name,
                        phone=c.phone_number or "",
                        source="whatsapp_desktop_ui",
                        is_verified=bool(c.phone_number),
                        metadata={"evidence_label": c.evidence_label},
                    ))
                lines.append("Which contact would you like to message?")
                return ContactResolutionResult(
                    status=ContactResolutionStatus.MULTIPLE_MATCHES,
                    query=raw_query,
                    candidates=cand_list,
                    clarification_prompt="\n".join(lines),
                    source="whatsapp_desktop_ui",
                )

            else:
                c = candidates[0]
                q_norm = cleaned_query.strip().casefold()
                c_norm = c.display_name.strip().casefold()

                # Partial match is NEVER auto-selected! (Scenario 3)
                if q_norm != c_norm:
                    sugg = VerifiedContact(
                        id="wa_cand_0",
                        name=c.display_name,
                        phone=c.phone_number or "",
                        source="whatsapp_desktop_ui",
                        is_verified=False,
                        metadata={"evidence_label": c.evidence_label},
                    )
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.NO_MATCH,
                        query=raw_query,
                        suggestions=[sugg],
                        clarification_prompt=f"No exact match found in WhatsApp for '{cleaned_query}'. Visible suggestion: {c.display_name}. Reply to confirm or provide their full phone number.",
                        source="whatsapp_desktop_ui",
                    )

                # Exact match
                if c.phone_number:
                    # Scenario 2: Exact name with visible phone number
                    matched_vc = VerifiedContact(
                        id="wa_cand_0",
                        name=c.display_name,
                        phone=c.phone_number,
                        source="whatsapp_desktop_ui",
                        is_verified=True,
                        metadata={"evidence_label": "visible_ui_with_phone", "phone_verified": True},
                    )
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.EXACT_MATCH,
                        query=raw_query,
                        contact=matched_vc,
                        candidates=[matched_vc],
                        source="whatsapp_desktop_ui",
                    )
                else:
                    # Scenario 1: Exact name with one candidate but NO visible phone identifier
                    matched_vc = VerifiedContact(
                        id="wa_cand_0",
                        name=c.display_name,
                        phone="",
                        source="whatsapp_desktop_ui",
                        is_verified=False,
                        metadata={"evidence_label": "visible_ui_name_only", "phone_verified": False},
                    )
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.EXACT_MATCH,
                        query=raw_query,
                        contact=matched_vc,
                        candidates=[matched_vc],
                        source="whatsapp_desktop_ui",
                    )

        # 1. Fail-closed if contact source is unavailable or stale (WA-CONTACT-08)
        if hasattr(self, "contact_source") and self.contact_source:
            if not self.contact_source.is_available():
                return ContactResolutionResult(
                    status=ContactResolutionStatus.SOURCE_UNAVAILABLE,
                    query=raw_query,
                    clarification_prompt="WhatsApp contact source is currently unavailable. Contact resolution cannot proceed safely.",
                    source=self.contact_source.source_name,
                )
            if self.contact_source.is_stale():
                return ContactResolutionResult(
                    status=ContactResolutionStatus.CONTACT_DATA_STALE,
                    query=raw_query,
                    clarification_prompt="WhatsApp contact data is stale and must be refreshed before messages can be routed.",
                    source=self.contact_source.source_name,
                )

        # 2. Direct Phone Number Detection
        phone_match = re.search(r"^(\+?\d[\d\s-]{8,}\d)$", cleaned_query)
        if phone_match:
            clean_phone = re.sub(r"[^\d+]", "", phone_match.group(1))
            # Check if this phone number belongs to a known verified contact
            if hasattr(self, "contact_source") and self.contact_source:
                known_contact = self.contact_source.get_contact_by_phone(clean_phone)
                if known_contact:
                    contact_copy = VerifiedContact(
                        id=known_contact.id,
                        name=known_contact.name,
                        phone=clean_phone,
                        source=known_contact.source,
                        is_verified=known_contact.is_verified,
                        metadata=known_contact.metadata,
                    )
                    return ContactResolutionResult(
                        status=ContactResolutionStatus.EXACT_MATCH,
                        query=raw_query,
                        contact=contact_copy,
                        candidates=[contact_copy],
                        source=self.contact_source.source_name,
                    )
            # Direct unverified number (WA-CONTACT-13)
            digits_only = re.sub(r"\D", "", clean_phone)
            if len(digits_only) < 10 or len(digits_only) > 15:
                return ContactResolutionResult(
                    status=ContactResolutionStatus.NO_MATCH,
                    query=raw_query,
                    clarification_prompt=f"The phone number '{clean_phone}' is invalid. Please provide a valid 10-15 digit phone number.",
                    source=self.contact_source.source_name if hasattr(self, "contact_source") and self.contact_source else "unknown",
                )
            unverified = VerifiedContact(
                id=f"direct_{clean_phone}",
                name=clean_phone,
                phone=clean_phone,
                source="user_provided_unverified",
                is_verified=False,
                metadata={"type": "unverified_direct_number"},
            )
            return ContactResolutionResult(
                status=ContactResolutionStatus.INVALID_OR_UNVERIFIED_NUMBER,
                query=raw_query,
                contact=unverified,
                candidates=[unverified],
                clarification_prompt=(
                    f"You provided the direct phone number '{clean_phone}'. "
                    f"This number is not in your verified contacts. "
                    f"Please confirm if you want to send a WhatsApp message to this destination "
                    f"(reply 'yes' to confirm or provide a contact name)."
                ),
                source=self.contact_source.source_name if hasattr(self, "contact_source") and self.contact_source else "user_provided",
            )

        # 3. Exact Match Resolution (Strict normalized casefold)
        exact_matches = self.contact_source.get_exact_matches(cleaned_query) if hasattr(self, "contact_source") and self.contact_source else []

        if len(exact_matches) == 1:
            matched = exact_matches[0]
            return ContactResolutionResult(
                status=ContactResolutionStatus.EXACT_MATCH,
                query=raw_query,
                contact=matched,
                candidates=exact_matches,
                source=self.contact_source.source_name,
            )

        elif len(exact_matches) > 1:
            # Duplicate exact names -> trigger disambiguation with distinguishing details
            lines = [f"Multiple verified contacts found matching '{cleaned_query}':"]
            for i, cand in enumerate(exact_matches, 1):
                phone_display = f" ({cand.phone})" if cand.phone else ""
                role_display = f" — {cand.metadata.get('role', 'contact')}" if cand.metadata.get("role") and cand.metadata.get("role") != "contact" else ""
                lines.append(f"{i}) {cand.name}{phone_display}{role_display}")
            lines.append("Which person would you like to message?")
            prompt = "\n".join(lines)

            return ContactResolutionResult(
                status=ContactResolutionStatus.MULTIPLE_MATCHES,
                query=raw_query,
                candidates=exact_matches,
                clarification_prompt=prompt,
                source=self.contact_source.source_name,
            )

        # 4. No Exact Match -> check suggestions (Suggestions are NEVER automatically selected)
        suggestions = self.contact_source.get_suggestions(cleaned_query) if hasattr(self, "contact_source") and self.contact_source else []
        if suggestions:
            lines = [f"No exact contact found for '{cleaned_query}'. Did you mean one of these unverified suggestions:"]
            for i, sugg in enumerate(suggestions, 1):
                phone_display = f" ({sugg.phone})" if sugg.phone else ""
                role_display = f" — {sugg.metadata.get('role', 'contact')}" if sugg.metadata.get("role") and sugg.metadata.get("role") != "contact" else ""
                lines.append(f"{i}) {sugg.name}{phone_display}{role_display}")
            lines.append("Or reply with the correct name or full phone number.")
            prompt = "\n".join(lines)
        else:
            prompt = (
                f"No contact found for '{cleaned_query}' in your verified contacts. "
                f"Please check the spelling or provide their phone number directly."
            )

        return ContactResolutionResult(
            status=ContactResolutionStatus.NO_MATCH,
            query=raw_query,
            suggestions=suggestions,
            clarification_prompt=prompt,
            source=self.contact_source.source_name if hasattr(self, "contact_source") and self.contact_source else "unknown",
        )

    # ── Internal Search Methods ────────────────────────────────────────────────

    def _search_mailbox(self, query: str, combined_text: str) -> list[ResolvedRecipient]:
        if not self.mail_automation:
            return []

        candidates: list[ResolvedRecipient] = []
        seen_emails: set[str] = set()

        # Extract search keywords
        keywords = self._extract_keywords(query)
        search_terms = " ".join(keywords[:3]) if keywords else query

        try:
            res = self.mail_automation.search_mail(search_terms) if hasattr(self.mail_automation, "search_mail") else self.mail_automation.read_mail(limit=30)
            emails = res.get("emails", []) if isinstance(res, dict) else []
            for em in emails:
                sender_str = em.get("sender", "")
                snippet = em.get("snippet", "")
                subject = em.get("subject", "")
                email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", sender_str)
                if not email_match:
                    continue
                email_addr = email_match.group(1).lower()
                if email_addr in seen_emails:
                    continue

                full_blob = f"{sender_str} {snippet} {subject}".lower()
                match_score = self._score_match(keywords, full_blob)
                if match_score > 0.4:
                    seen_emails.add(email_addr)
                    name = sender_str.split("<")[0].strip() if "<" in sender_str else email_addr.split("@")[0].title()
                    role = self._infer_role_from_text(full_blob)
                    candidates.append(
                        ResolvedRecipient(
                            name=name,
                            email=email_addr,
                            role=role,
                            confidence=min(1.0, match_score + 0.2),
                            source="mailbox_search",
                            context_notes=f"Found in mailbox correspondence: '{subject}'",
                        )
                    )
        except Exception:
            pass

        return candidates

    def _search_contacts(self, query: str, combined_text: str) -> list[ResolvedRecipient]:
        candidates: list[ResolvedRecipient] = []
        seen_emails: set[str] = set()

        # 1. Search mail automation contacts / address book
        if self.mail_automation and hasattr(self.mail_automation, "search_contacts"):
            try:
                found = self.mail_automation.search_contacts(query)
                for val in found:
                    em = val.get("email", "").lower()
                    if em and em not in seen_emails:
                        seen_emails.add(em)
                        candidates.append(
                            ResolvedRecipient(
                                name=val.get("name", ""),
                                email=em,
                                role=val.get("role", "contact"),
                                confidence=0.9,
                                source="contacts",
                                department=val.get("department", ""),
                                institution=val.get("institution", ""),
                                context_notes="Found in authorized contacts/address book",
                            )
                        )
            except Exception:
                pass

        # 2. Search persistent memory store
        if self.memory:
            try:
                contact_items = self.memory.list() if hasattr(self.memory, "list") else []
                keywords = self._extract_keywords(query)
                for item in contact_items:
                    if item.get("category") == "contact" or "contact" in item.get("key", "").lower():
                        val = item.get("value", {})
                        if isinstance(val, dict):
                            em = val.get("email", "").lower()
                            if em in seen_emails:
                                continue
                            blob = f"{val.get('name', '')} {val.get('role', '')} {val.get('department', '')} {val.get('email', '')}".lower()
                            score = self._score_match(keywords, blob)
                            if score > 0.5:
                                seen_emails.add(em)
                                candidates.append(
                                    ResolvedRecipient(
                                        name=val.get("name", ""),
                                        email=em,
                                        role=val.get("role", "contact"),
                                        confidence=score,
                                        source="contacts",
                                        department=val.get("department", ""),
                                        institution=val.get("institution", ""),
                                        context_notes="Found in saved contacts",
                                    )
                                )
            except Exception:
                pass

        return candidates

    def _search_thread_context(self, query: str, thread_context: list[dict[str, Any]]) -> ResolvedRecipient | None:
        keywords = self._extract_keywords(query)
        for msg in reversed(thread_context):
            sender = msg.get("sender", "")
            match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", sender)
            if match:
                email_addr = match.group(1).lower()
                blob = f"{sender} {msg.get('subject', '')} {msg.get('body', '')}".lower()
                score = self._score_match(keywords, blob)
                if score > 0.5:
                    return ResolvedRecipient(
                        name=sender.split("<")[0].strip() if "<" in sender else email_addr,
                        email=email_addr,
                        role=self._infer_role_from_text(blob),
                        confidence=0.85,
                        source="thread",
                        context_notes=f"Active in current email thread: '{msg.get('subject', '')}'",
                    )
        return None

    def _search_directory(
        self, query: str, combined_text: str, preferred_institution: str = ""
    ) -> list[ResolvedRecipient]:
        keywords = self._extract_keywords(query)
        results: list[ResolvedRecipient] = []
        for entry in self.KNOWN_DIRECTORY:
            entry_keywords = entry.get("keywords", [])
            name = entry.get("name", "")
            role = entry.get("role", "")
            dept = entry.get("department", "")
            inst = entry.get("institution", "")
            blob = f"{name} {role} {dept} {inst}".lower()
            score = self._score_match(keywords, blob)
            # Boost if institution explicitly matches
            if preferred_institution and preferred_institution.lower() in inst.lower():
                score += 0.3
            elif any(inst in combined_text for inst in ("rvce", "rv college", "bmsce", "bms college")):
                for inst_token in ("rvce", "rv college", "bmsce", "bms college"):
                    if inst_token in combined_text and inst_token in blob:
                        score += 0.35

            if score >= 0.5:
                results.append(
                    ResolvedRecipient(
                        name=name,
                        email=entry.get("email", ""),
                        role=role,
                        confidence=min(0.95, score),
                        source="directory",
                        department=dept,
                        institution=inst,
                        context_notes=f"Matched institutional directory for {inst}" if inst else "Matched institutional directory",
                    )
                )
        return results

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_keywords(self, text: str) -> list[str]:
        cleaned = re.sub(r"^(?:to|email|send an email to|mail to|contact|send email to)\s+", "", text, flags=re.IGNORECASE)
        words = re.findall(r"\b[a-zA-Z]{2,}\b", cleaned.lower())
        stopwords = {"the", "and", "for", "from", "with", "about", "that", "says", "saying", "requesting", "asking"}
        return [w for w in words if w not in stopwords]

    def _score_match(self, keywords: list[str], target_text: str) -> float:
        if not keywords:
            return 0.0
        matches = sum(1 for kw in keywords if kw in target_text)
        return matches / len(keywords)

    def _infer_role_from_text(self, text: str) -> str:
        t = text.lower()
        if any(w in t for w in ("hod", "head of department", "head of the department")):
            return "hod"
        if any(w in t for w in ("professor", "prof", "faculty", "dean", "instructor")):
            return "professor"
        if any(w in t for w in ("manager", "lead", "supervisor", "boss")):
            return "manager"
        if any(w in t for w in ("recruiter", "talent acquisition", "hr", "hiring")):
            return "recruiter"
        if any(w in t for w in ("client", "customer", "partner")):
            return "client"
        if any(w in t for w in ("colleague", "teammate", "coworker")):
            return "colleague"
        if any(w in t for w in ("friend", "buddy", "pal")):
            return "friend"
        return "unknown"

    def _clean_role_label(self, raw_query: str) -> str:
        cleaned = re.sub(r"^(?:to|the|send an email to|mail to)\s+", "", raw_query.strip(), flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+(?:saying|requesting|asking|with|about).*$", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned or "recipient"

    def _disambiguate_candidates(
        self,
        candidates: list[ResolvedRecipient],
        combined_text: str,
        preferred_institution: str = "",
    ) -> list[ResolvedRecipient]:
        if not candidates:
            return []
        if preferred_institution:
            pref = [c for c in candidates if preferred_institution.lower() in c.institution.lower()]
            if pref:
                return pref
        # Check institution in combined text
        for c in candidates:
            if c.institution and c.institution.lower() in combined_text:
                return [c]
        return candidates

    def _format_multiple_candidates_prompt(self, query: str, candidates: list[ResolvedRecipient]) -> str:
        options = []
        for i, c in enumerate(candidates, 1):
            info = f"{c.name} ({c.email})"
            if c.department or c.institution:
                details = ", ".join(filter(None, [c.department, c.institution]))
                info += f" – {details}"
            options.append(f"{i}. {info}")

        return (
            f"I found multiple candidates matching '{query}':\n"
            + "\n".join(options)
            + "\nCould you let me know which person you would like to email?"
        )
