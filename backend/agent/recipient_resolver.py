from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResolvedRecipient:
    name: str = ""
    email: str = ""
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

    def __init__(self, mail_automation: Any = None, memory_store: Any = None) -> None:
        self.mail_automation = mail_automation
        self.memory = memory_store

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

        # ── 1. Direct Email Address Detection ──────────────────────────────────
        direct_email_match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", raw_query)
        if direct_email_match:
            email_addr = direct_email_match.group(1).lower()
            name_part = raw_query.replace(email_addr, "").strip().strip("<>()[]\"'")
            if not name_part or name_part.lower() == email_addr:
                user_part = email_addr.split("@")[0]
                name_part = user_part.replace(".", " ").replace("_", " ").title()

            role = self._infer_role_from_text(f"{raw_query} {full_message}")
            return ResolutionResult(
                status="resolved",
                recipient=ResolvedRecipient(
                    name=name_part or email_addr,
                    email=email_addr,
                    role=role,
                    confidence=1.0,
                    source="direct",
                    context_notes="Direct email address provided by user",
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
            blob = f"{entry['name']} {entry['role']} {entry['department']} {entry['institution']}".lower()
            score = self._score_match(keywords, blob)
            # Boost if institution explicitly matches
            if preferred_institution and preferred_institution.lower() in entry["institution"].lower():
                score += 0.3
            elif any(inst in combined_text for inst in ("rvce", "rv college", "bmsce", "bms college")):
                for inst_token in ("rvce", "rv college", "bmsce", "bms college"):
                    if inst_token in combined_text and inst_token in blob:
                        score += 0.35

            if score >= 0.5:
                results.append(
                    ResolvedRecipient(
                        name=entry["name"],
                        email=entry["email"],
                        role=entry["role"],
                        confidence=min(0.95, score),
                        source="directory",
                        department=entry.get("department", ""),
                        institution=entry.get("institution", ""),
                        context_notes=f"Matched institutional directory for {entry['institution']}",
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
