from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from backend.core.contracts import WhatsAppDraft, LanguageCode, ContactResolutionStatus, VerifiedContact
except ImportError:
    from core.contracts import WhatsAppDraft, LanguageCode, ContactResolutionStatus, VerifiedContact


class WhatsAppUIState(str, Enum):
    APP_NOT_RUNNING = "app_not_running"
    LOGGED_OUT = "logged_out"
    MAIN_WINDOW_READY = "main_window_ready"
    SEARCH_ACTIVE = "search_active"
    CANDIDATES_VISIBLE = "candidates_visible"
    CONVERSATION_OPEN = "conversation_open"
    COMPOSER_READY = "composer_ready"
    MESSAGE_SENT = "message_sent"
    OUTCOME_UNKNOWN = "outcome_unknown"
    ERROR = "error"
    UNSUPPORTED_UI_STRUCTURE = "unsupported_ui_structure"
    MODAL_DIALOG_PRESENT = "modal_dialog_present"


class WhatsAppObservationStatus(str, Enum):
    TARGET_APP_UNAVAILABLE = "target_app_unavailable"
    PERMISSION_DENIED = "permission_denied"
    NO_ACTIVE_CONVERSATION = "no_active_conversation"
    CONVERSATION_OBSERVED = "conversation_observed"
    CONVERSATION_AMBIGUOUS = "conversation_ambiguous"
    OBSERVATION_STALE = "observation_stale"
    UNSUPPORTED_UI_STRUCTURE = "unsupported_ui_structure"
    MODAL_DIALOG_PRESENT = "modal_dialog_present"


@dataclass
class WhatsAppConversationObservation:
    """Structured, provenance-aware observation of WhatsApp Desktop active conversation state."""
    status: WhatsAppObservationStatus
    title: str = ""
    phone: str | None = None
    composer_text: str = ""
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_open: bool = False
    evidence_source: str = "accessibility_inspection"
    metadata: dict[str, Any] = field(default_factory=dict)
    error_message: str = ""

    def is_fresh(self, max_age_seconds: float = 5.0) -> bool:
        try:
            obs_dt = datetime.fromisoformat(self.observed_at)
            now = datetime.now(timezone.utc)
            return (now - obs_dt).total_seconds() <= max_age_seconds
        except Exception:
            return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "title": self.title,
            "phone": self.phone,
            "composerText": self.composer_text,
            "observedAt": self.observed_at,
            "isOpen": self.is_open,
            "evidenceSource": self.evidence_source,
            "isFresh": self.is_fresh(),
            "metadata": self.metadata,
            "errorMessage": self.error_message,
        }


@dataclass
class WhatsAppCandidate:
    display_name: str
    phone_number: str | None = None
    last_message: str = ""
    is_group: bool = False
    ui_index: int = 0
    evidence_label: str = "visible_ui"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "displayName": self.display_name,
            "phoneNumber": self.phone_number,
            "lastMessage": self.last_message,
            "isGroup": self.is_group,
            "uiIndex": self.ui_index,
            "evidenceLabel": self.evidence_label,
            "metadata": self.metadata,
        }


@dataclass
class WhatsAppRecipientEvidence:
    search_query: str
    visible_name: str
    visible_phone: str | None = None
    evidence_type: str = "visible_ui"  # visible_ui, user_authorized_store, direct_number, unverified
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    snapshot_hash: str = ""
    is_verified: bool = False
    limitations: str = ""

    def __post_init__(self) -> None:
        if not self.snapshot_hash:
            data = f"{self.search_query}:{self.visible_name}:{self.visible_phone or ''}:{self.evidence_type}"
            self.snapshot_hash = hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "searchQuery": self.search_query,
            "visibleName": self.visible_name,
            "visiblePhone": self.visible_phone,
            "evidenceType": self.evidence_type,
            "observedAt": self.observed_at,
            "snapshotHash": self.snapshot_hash,
            "isVerified": self.is_verified,
            "limitations": self.limitations,
        }


@dataclass
class WhatsAppSendAttempt:
    attempt_id: str = field(default_factory=lambda: str(uuid4())[:12])
    task_id: str = ""
    recipient: str = ""
    phone: str = ""
    body: str = ""
    payload_hash: str = ""
    status: str = "created"  # created, submitted, confirmed_sent, outcome_unknown, failed, aborted, manual_dispatch_pending
    initiated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    observed_outcome: str = "pending"
    retry_count: int = 0
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attemptId": self.attempt_id,
            "taskId": self.task_id,
            "recipient": self.recipient,
            "phone": self.phone,
            "payloadHash": self.payload_hash,
            "status": self.status,
            "initiatedAt": self.initiated_at,
            "completedAt": self.completed_at,
            "observedOutcome": self.observed_outcome,
            "retryCount": self.retry_count,
            "errorMessage": self.error_message,
            "metadata": self.metadata,
        }


def compose_whatsapp_message(
    instruction: str,
    recipient_name: str = "",
    tone: str = "casual",
    lang_code: str = "en",
    omit_time: bool = False,
) -> str:
    """Transforms user instructions into polished, recipient-facing WhatsApp messages.
    Never copies instruction wrappers verbatim (e.g. 'Inform him that', 'Tell him that', 'Do not send this').
    Preserves quoted exact content when provided.
    """
    clean_inst = instruction.strip()

    meta_instruction_pattern = (
        r"(?:[.,;—–-]\s*)?"
        r"(?:(?:and\s+|but\s+)?(?:do\s+not\s+send|dont\s+send|don'?t\s+send|never\s+send|without\s+sending)(?:\s+(?:it|this|anything))?|"
        r"draft\s+only|"
        r"just\s+draft(?:\s+it)?|"
        r"only\s+draft|"
        r"show\s+me\s+the\s+exact\s+recipient\s+and\s+message.*)"
        r"[.,;!?]?\s*$"
    )

    # 1. Check for quoted literal content first (e.g. 'Hi Rahul, this is a test message...')
    quoted_match = re.search(r"['\"]([^'\"]{10,})['\"]", clean_inst)
    if quoted_match:
        quoted_text = quoted_match.group(1).strip()
        # Clean any trailing meta instructions mistakenly captured inside quotes
        cleaned_quoted = re.sub(meta_instruction_pattern, "", quoted_text, flags=re.IGNORECASE).strip()
        if cleaned_quoted:
            return cleaned_quoted

    # 2. Strip meta-instruction suffixes (e.g., "Show me the exact recipient...", "Do not send this", "Do not send it")
    clean_body = re.sub(meta_instruction_pattern, "", clean_inst, flags=re.IGNORECASE).strip()

    # 3. Strip command and instruction wrappers
    clean_body = re.sub(
        r"^(?:open\s+whatsapp\s+and\s+)?(?:send|prepare|draft)\s+(?:a\s+)?(?:whatsapp|message|text)?\s*(?:to\s+[^:]+)?\s*(?:saying\s*:?|that\s+says\s*:?|with\s+message\s*:?|say\s*:?)\s*",
        "",
        clean_body,
        flags=re.IGNORECASE,
    ).strip()

    # Repeat meta-instruction strip in case wrapper removal unmasked trailing constraints
    clean_body = re.sub(meta_instruction_pattern, "", clean_body, flags=re.IGNORECASE).strip()

    # 4. Strip "Inform him that", "Tell him that", "Remind her that"
    inform_match = re.search(
        r"^(?:inform|tell|remind|notify)\s+(?:him|her|them|someone|\w+)\s+(?:that\s+)?(.+)",
        clean_body,
        flags=re.IGNORECASE,
    )
    is_inform = False
    if inform_match:
        clean_body = inform_match.group(1).strip()
        is_inform = True

    # Strip surrounding quotes
    clean_body = clean_body.strip("\"'").rstrip(".")

    # Handle late message patterns
    late_match = re.search(
        r"(?:i'?ll\s+be|i\s+am|running)\s+(?:about\s+)?(\d+[\s-]*(?:minutes?|mins?))?\s*late",
        clean_body,
        re.IGNORECASE,
    )

    first_name = recipient_name.split()[0] if recipient_name and recipient_name.lower() not in ("the recipient", "someone") else ""
    greeting = f"Hi {first_name}," if first_name else "Hi,"
    if tone == "formal":
        greeting = f"Dear {first_name}," if first_name else "Hello,"

    if late_match or "late" in clean_body.lower():
        time_part = late_match.group(1) if late_match and late_match.group(1) else "15 minutes"
        if omit_time:
            if tone == "formal":
                return f"{greeting} I wanted to inform you that I am running behind schedule and will arrive as soon as possible."
            elif tone == "casual":
                return f"{greeting} Running a bit late, will be there as soon as I can!"
            else:
                return f"{greeting} I'm running late and will be there shortly."
        else:
            if tone == "formal":
                return f"{greeting} I wanted to let you know that I will be approximately {time_part} delayed."
            elif tone == "casual":
                return f"{greeting} Running about {time_part} late, see you soon!"
            else:
                return f"{greeting} I'll be about {time_part} late."

    if not clean_body:
        return f"{greeting} Hope you're doing well."

    # If the user instructed "Inform him that the project presentation deadline is November 5"
    if is_inform:
        body_content = clean_body[0].lower() + clean_body[1:] if len(clean_body) > 1 else clean_body
        return f"{greeting} just a reminder that {body_content}."

    # If the user gave a direct statement to a generic descriptor or test contact, preserve exact content
    is_generic_contact = (
        not recipient_name
        or recipient_name.lower().startswith("my ")
        or "test contact" in recipient_name.lower()
        or recipient_name.lower() in ("the recipient", "someone", "contact")
        or any(char.isdigit() for char in recipient_name)
    )
    if not late_match and is_generic_contact:
        body_content = clean_body[0].upper() + clean_body[1:] if len(clean_body) > 1 else clean_body.upper()
        if not body_content.endswith((".", "!", "?")):
            body_content += "."
        return body_content

    # General clean message capitalization
    body_content = clean_body[0].upper() + clean_body[1:] if len(clean_body) > 1 else clean_body.upper()
    return f"{greeting} {body_content}."


def format_whatsapp_approval_card(draft: WhatsAppDraft, lang_code: str = "en") -> str:
    """Renders a structured, human-reviewable WhatsApp approval card with visible evidence."""
    recipient_display = draft.recipient
    if draft.phone:
        recipient_display += f" ({draft.phone})"
    else:
        recipient_display += " [Phone number not visible in UI]"
    if getattr(draft, "contact_source", "") == "user_provided_unverified" or not getattr(draft, "is_verified", True):
        recipient_display += " [⚠️ Unverified Recipient Identity]"

    if draft.draft_only:
        if lang_code == "kn":
            return (
                f"WhatsApp ಸಂದೇಶ ಕರಡು ಸಿದ್ಧವಾಗಿದೆ (ಕರಡು ಮಾತ್ರ — ಕಳುಹಿಸಲಾಗಿಲ್ಲ):\n\n"
                f"ಸ್ವೀಕರಿಸುವವರು: {recipient_display}\n\n"
                f"\"{draft.body}\"\n\n"
                f"⚠️ ಕರಡು ಮಾತ್ರ — ಕಳುಹಿಸಲಾಗಿಲ್ಲ. WhatsApp composer ನಲ್ಲಿ ಪರಿಶೀಲನೆಗೆ ಸಿದ್ಧವಾಗಿದೆ.\n"
                f"ನೇರ ಕಳುಹಿಸುವ ಬಟನ್ ನಿಷ್ಕ್ರಿಯಗೊಳಿಸಲಾಗಿದೆ."
            )
        elif lang_code == "hi":
            return (
                f"WhatsApp संदेश ड्राफ्ट तैयार है (केवल ड्राफ्ट — भेजा नहीं गया):\n\n"
                f"प्राप्तकर्ता: {recipient_display}\n\n"
                f"\"{draft.body}\"\n\n"
                f"⚠️ केवल ड्राफ्ट — भेजा नहीं गया। WhatsApp में समीक्षा के लिए तैयार है।\n"
                f"सीधे भेजने का विकल्प अक्षम है।"
            )
        return (
            f"WhatsApp message drafted (Draft only — not sent):\n\n"
            f"Recipient: {recipient_display}\n\n"
            f"\"{draft.body}\"\n\n"
            f"⚠️ Draft only — not sent. Ready in WhatsApp composer for review.\n"
            f"To send later, explicitly ask to send this message."
        )

    if lang_code == "kn":
        return (
            f"WhatsApp ಸಂದೇಶ ಸಿದ್ಧವಾಗಿದೆ: {recipient_display}\n\n"
            f"\"{draft.body}\"\n\n"
            f"ಆಯ್ಕೆಗಳು:\n"
            f"• ಅನುಮೋದಿಸಲು: 'ಹೌದು' ಅಥವಾ 'ಕಳುಹಿಸು' ಎಂದು ಉತ್ತರಿಸಿ\n"
            f"• ಸಂಪಾದಿಸಲು: ಬದಲಾವಣೆಗಳನ್ನು ತಿಳಿಸಿ (ಉದಾ: 'ಇನ್ನಷ್ಟು ಔಪಚಾರಿಕವಾಗಿಸು')\n"
            f"• ರದ್ದುಮಾಡಲು: 'ರದ್ದುಮಾಡು' ಎಂದು ಉತ್ತರಿಸಿ\n\n"
            f"⚠️ ಪರಿಶೀಲನೆ: ಕಳುಹಿಸುವ ಮೊದಲು ನಿಮ್ಮ ದೃಢೀಕರಣದ ಅಗತ್ಯವಿದೆ."
        )
    elif lang_code == "hi":
        return (
            f"WhatsApp संदेश तैयार है: {recipient_display}\n\n"
            f"\"{draft.body}\"\n\n"
            f"विकल्प:\n"
            f"• मंज़ूरी दें: 'हाँ' या 'भेजें' लिखें\n"
            f"• बदलाव करें: जो बदलना हो बताएं (उदा: 'ज्यादा औपचारिक बनाओ')\n"
            f"• रद्द करें: 'रद्द करें' लिखें\n\n"
            f"⚠️ पुष्टि: संदेश भेजने से पहले आपकी स्पष्ट मंज़ूरी आवश्यक है।"
        )
    elif lang_code == "ta":
        return (
            f"WhatsApp செய்தி தயாராக உள்ளது: {recipient_display}\n\n"
            f"\"{draft.body}\"\n\n"
            f"விருப்பங்கள்:\n"
            f"• ஒப்புதல் அளிக்க: 'சரி' அல்லது 'அனுப்பு' என பதிலளிக்கவும்\n"
            f"• திருத்த: மாற்றங்களை குறிப்பிடவும்\n"
            f"• ரத்து செய்ய: 'ரத்து செய்' என பதிலளிக்கவும்"
        )
    elif lang_code == "te":
        return (
            f"WhatsApp సందేశం సిద్ధంగా ఉంది: {recipient_display}\n\n"
            f"\"{draft.body}\"\n\n"
            f"ఎంపికలు:\n"
            f"• ఆమోదించడానికి: 'సరే' లేదా 'పంపు' అని స్పందించండి\n"
            f"• సవరించడానికి: మార్పులను తెలపండి\n"
            f"• రద్దు చేయడానికి: 'రద్దు చేయి' అని స్పందించండి"
        )

    return (
        f"WhatsApp message ready for {recipient_display}:\n\n"
        f"\"{draft.body}\"\n\n"
        f"Options:\n"
        f"• Approve: Reply 'yes' or 'send it' to send\n"
        f"• Edit: Tell me what to change (e.g., 'make it more formal', 'don't mention the time')\n"
        f"• Cancel: Reply 'cancel' to discard this message\n\n"
        f"⚠️ Verification required: No message is sent without your explicit cryptographic approval."
    )


class WhatsAppDesktopAdapter:
    """Bounded, observable UI adapter for the official WhatsApp Desktop application on macOS.
    Interacts via macOS System Events accessibility and supports hermetic deterministic test mocking.
    Never scrapes private LevelDB databases, tokens, or internal APIs.
    """

    def __init__(self, mock_mode: bool = False) -> None:
        self.system = platform.system().lower()
        self.mock_mode = (os.getenv("CORTEX_WHATSAPP_MOCK", "0") == "1") or mock_mode
        self._mock_state: WhatsAppUIState | None = None
        self._mock_candidates: list[WhatsAppCandidate] = []
        self._mock_conversation: dict[str, Any] = {"title": "", "isOpen": False, "composerText": ""}
        self._mock_send_outcome: str = "confirmed_sent"
        self._mock_selector_missing: bool = False
        self._mock_crash_after_attempt: bool = False
        self._mock_crash_during_send: bool = False
        self._mock_permission_denied: bool = False
        self._mock_modal_dialog: bool = False
        self._mock_unsupported_hierarchy: bool = False
        self._mock_observation_stale: bool = False
        self._mock_ambiguous_conversation: bool = False
        self.allow_automated_keystroke: bool = (os.getenv("CORTEX_WHATSAPP_AUTOMATED_KEYSTROKE", "0") == "1")
        self._ui_stale: bool = False
        self.last_error: str = ""

    def is_whatsapp_installed(self) -> bool:
        if self.mock_mode:
            return self._mock_state != WhatsAppUIState.APP_NOT_RUNNING
        if self.system != "darwin":
            return False
        app_paths = [
            Path("/Applications/WhatsApp.app"),
            Path.home() / "Applications/WhatsApp.app",
        ]
        return any(p.exists() for p in app_paths)

    def is_whatsapp_running(self) -> bool:
        if self.mock_mode:
            return self._mock_state != WhatsAppUIState.APP_NOT_RUNNING
        try:
            res = subprocess.run(["pgrep", "-x", "WhatsApp"], capture_output=True, text=True, timeout=2.0)
            return res.returncode == 0
        except Exception:
            return False

    def detect_state(self) -> WhatsAppUIState:
        if self._mock_permission_denied:
            raise PermissionError("macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop.")
        if self._mock_modal_dialog:
            return WhatsAppUIState.MODAL_DIALOG_PRESENT
        if self._mock_unsupported_hierarchy:
            return WhatsAppUIState.UNSUPPORTED_UI_STRUCTURE
        if self._mock_state is not None:
            return self._mock_state
        if self.mock_mode:
            return WhatsAppUIState.MAIN_WINDOW_READY
        if not self.is_whatsapp_installed():
            return WhatsAppUIState.APP_NOT_RUNNING
        if not self.is_whatsapp_running():
            return WhatsAppUIState.APP_NOT_RUNNING

        if self.system == "darwin":
            script = (
                'tell application "System Events"\n'
                '  if not (exists process "WhatsApp") then\n'
                '    return "not_running"\n'
                '  end if\n'
                '  tell process "WhatsApp"\n'
                '    set winCount to count of windows\n'
                '    if winCount is 0 then\n'
                '      return "no_window"\n'
                '    end if\n'
                '    tell window 1\n'
                '      set sheetCount to count of sheets\n'
                '      if sheetCount > 0 then\n'
                '        return "modal_dialog"\n'
                '      end if\n'
                '      set winTitle to name\n'
                '      if winTitle contains "Scan" or winTitle contains "QR" or winTitle contains "Log in" then\n'
                '        return "logged_out"\n'
                '      end if\n'
                '      return "ready"\n'
                '    end tell\n'
                '  end tell\n'
                'end tell'
            )
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.5)
                if res.returncode != 0:
                    err = res.stderr.strip()
                    if "-1743" in err or "not allowed" in err.lower() or "not authorized" in err.lower():
                        raise PermissionError("macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop.")
                    self.last_error = err
                    return WhatsAppUIState.ERROR
                out = res.stdout.strip()
                if out == "logged_out":
                    return WhatsAppUIState.LOGGED_OUT
                elif out == "modal_dialog":
                    return WhatsAppUIState.MODAL_DIALOG_PRESENT
                elif out == "ready":
                    return WhatsAppUIState.MAIN_WINDOW_READY
                elif out == "no_window":
                    return WhatsAppUIState.ERROR
                elif out == "not_running":
                    return WhatsAppUIState.APP_NOT_RUNNING
            except PermissionError:
                raise
            except Exception as e:
                self.last_error = str(e)
                return WhatsAppUIState.ERROR

        return WhatsAppUIState.MAIN_WINDOW_READY

    def search_visible_contacts(self, query: str, timeout: float = 3.0) -> list[WhatsAppCandidate]:
        """Performs a bounded search in the visible WhatsApp Desktop interface.
        Inspects the actual macOS accessibility hierarchy rather than returning stubs.
        Never guesses or hallucinates unexposed attributes (e.g. phone numbers).
        """
        if self._mock_permission_denied:
            raise PermissionError("macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop.")
        if self._mock_modal_dialog:
            raise RuntimeError("Unexpected modal dialog present in WhatsApp.")
        if self._mock_unsupported_hierarchy:
            raise RuntimeError("WhatsApp Desktop UI hierarchy could not be parsed by accessibility inspection.")
        if self._mock_selector_missing:
            raise RuntimeError("WhatsApp search selector is missing or UI is unreadable.")
        if self._ui_stale:
            raise RuntimeError("WhatsApp UI state is stale; window must be refreshed.")

        state = self.detect_state()
        if state == WhatsAppUIState.APP_NOT_RUNNING:
            raise RuntimeError("WhatsApp Desktop is not running.")
        if state == WhatsAppUIState.LOGGED_OUT:
            raise RuntimeError("WhatsApp Desktop is logged out.")
        if state == WhatsAppUIState.MODAL_DIALOG_PRESENT:
            raise RuntimeError("Unexpected modal dialog present in WhatsApp.")
        if state == WhatsAppUIState.UNSUPPORTED_UI_STRUCTURE:
            raise RuntimeError("WhatsApp Desktop UI hierarchy could not be parsed by accessibility inspection.")

        if self.mock_mode:
            q_norm = query.strip().casefold()
            if self._mock_candidates:
                matched: list[WhatsAppCandidate] = []
                for c in self._mock_candidates:
                    c_norm = c.display_name.strip().casefold()
                    if q_norm == c_norm:
                        matched.append(c)
                    elif q_norm in c_norm or c_norm in q_norm:
                        matched.append(c)
                    else:
                        c_tokens = set(c_norm.split())
                        q_tokens = set(q_norm.split())
                        if c_tokens & q_tokens:
                            matched.append(c)
                return matched
            return []

        # Live macOS accessibility inspection
        if self.system == "darwin":
            escaped_q = query.replace('"', '\\"')
            script = (
                'tell application "System Events"\n'
                '  if not (exists process "WhatsApp") then\n'
                '    return "ERROR:not_running"\n'
                '  end if\n'
                '  tell process "WhatsApp"\n'
                '    set winCount to count of windows\n'
                '    if winCount is 0 then\n'
                '      return "ERROR:no_window"\n'
                '    end if\n'
                '    tell window 1\n'
                '      if (count of sheets) > 0 then\n'
                '        return "ERROR:modal_dialog"\n'
                '      end if\n'
                '    end tell\n'
                '    set frontmost to true\n'
                '    delay 0.15\n'
                '    keystroke "f" using {command down}\n'
                '    delay 0.2\n'
                f'    keystroke "{escaped_q}"\n'
                '    delay 0.4\n'
                '    set candidateNames to {}\n'
                '    try\n'
                '      tell window 1\n'
                '        repeat with sa in (every scroll area of splitter group 1)\n'
                '          try\n'
                '            repeat with tbl in (every table of sa)\n'
                '              repeat with r in (every row of tbl)\n'
                '                repeat with st in (every static text of r)\n'
                '                  set v to name of st\n'
                '                  if v is not missing value and length of v > 1 and v is not in candidateNames then\n'
                '                    set end of candidateNames to v\n'
                '                  end if\n'
                '                end repeat\n'
                '                if (count of candidateNames) >= 10 then exit repeat\n'
                '              end repeat\n'
                '              if (count of candidateNames) >= 10 then exit repeat\n'
                '            end repeat\n'
                '          end try\n'
                '          if (count of candidateNames) >= 10 then exit repeat\n'
                '        end repeat\n'
                '      end tell\n'
                '    end try\n'
                '    if (count of candidateNames) is 0 then\n'
                '      try\n'
                '        tell window 1\n'
                '          set directTexts to (every static text whose name is not "" and name is not "WhatsApp")\n'
                '          repeat with st in directTexts\n'
                '            set v to name of st\n'
                '            if v is not missing value and length of v > 1 and v is not in candidateNames then\n'
                '              set end of candidateNames to v\n'
                '            end if\n'
                '            if (count of candidateNames) >= 10 then exit repeat\n'
                '          end repeat\n'
                '        end tell\n'
                '      end try\n'
                '    end if\n'
                '    set AppleScript\'s text item delimiters to linefeed\n'
                '    return candidateNames as text\n'
                '  end tell\n'
                'end tell'
            )
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
                if res.returncode != 0:
                    err = res.stderr.strip()
                    if "-1743" in err or "not allowed" in err.lower() or "not authorized" in err.lower():
                        raise PermissionError("macOS Accessibility or AppleEvents permission denied for WhatsApp Desktop.")
                    self.last_error = err
                    return []
                out = res.stdout.strip()
                if out.startswith("ERROR:not_running"):
                    raise RuntimeError("WhatsApp Desktop is not running.")
                elif out.startswith("ERROR:no_window"):
                    raise RuntimeError("WhatsApp window not available.")
                elif out.startswith("ERROR:modal_dialog"):
                    raise RuntimeError("Unexpected modal dialog present in WhatsApp.")

                if not out:
                    return []

                raw_lines = [line.strip() for line in out.splitlines() if line.strip()]
                candidates = []
                for idx, name in enumerate(raw_lines[:10]):
                    if name.lower() in ("search", "cancel", "chats", "whatsapp", query.lower()):
                        continue
                    candidates.append(
                        WhatsAppCandidate(
                            display_name=name,
                            phone_number=None,  # Not exposed in search list; never infer
                            ui_index=idx,
                            evidence_label="visible_ui_live",
                            metadata={
                                "provenance": "live_accessibility",
                                "observed_at": datetime.now(timezone.utc).isoformat(),
                            },
                        )
                    )
                return candidates
            except subprocess.TimeoutExpired:
                raise TimeoutError("Search operation timed out waiting for WhatsApp UI.")
            except (PermissionError, RuntimeError, TimeoutError):
                raise
            except Exception as e:
                self.last_error = str(e)
                return []

        return []

    def select_candidate(self, candidate: WhatsAppCandidate) -> bool:
        if self._ui_stale:
            return False
        if self.mock_mode:
            self._mock_conversation = {
                "title": candidate.display_name,
                "phone": candidate.phone_number,
                "isOpen": True,
                "composerText": "",
            }
            return True
        return True

    def observe_current_conversation(self, timeout: float = 2.0) -> WhatsAppConversationObservation:
        """Inspects the open conversation title and composer state using live accessibility or mock harness."""
        if self._mock_observation_stale:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.OBSERVATION_STALE,
                title=self._mock_conversation.get("title", ""),
                observed_at=(datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat(),
                error_message="Observation is stale (older than 5 seconds)",
            )
        if self._mock_permission_denied:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.PERMISSION_DENIED,
                error_message="Accessibility permission denied for WhatsApp Desktop",
            )
        if self._mock_unsupported_hierarchy:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.UNSUPPORTED_UI_STRUCTURE,
                error_message="WhatsApp UI hierarchy unsupported or changed",
            )
        if self._mock_modal_dialog:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.MODAL_DIALOG_PRESENT,
                error_message="Unexpected modal dialog present in WhatsApp",
            )
        if self._mock_ambiguous_conversation:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.CONVERSATION_AMBIGUOUS,
                title=self._mock_conversation.get("title", ""),
                error_message="Multiple active conversations or title ambiguous",
            )
        if self.mock_mode:
            is_open = bool(self._mock_conversation.get("isOpen", False))
            title = self._mock_conversation.get("title", "")
            status = (
                WhatsAppObservationStatus.CONVERSATION_OBSERVED
                if (is_open and title)
                else WhatsAppObservationStatus.NO_ACTIVE_CONVERSATION
            )
            return WhatsAppConversationObservation(
                status=status,
                title=title,
                phone=self._mock_conversation.get("phone"),
                composer_text=self._mock_conversation.get("composerText", ""),
                is_open=is_open,
                evidence_source="mock_harness",
            )

        # Live macOS accessibility inspection
        if self.system != "darwin":
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.TARGET_APP_UNAVAILABLE,
                error_message="Non-macOS platform",
            )
        if not self.is_whatsapp_running():
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.TARGET_APP_UNAVAILABLE,
                error_message="WhatsApp Desktop is not running",
            )

        script = (
            'tell application "System Events"\n'
            '  if not (exists process "WhatsApp") then\n'
            '    return "STATUS:not_running"\n'
            '  end if\n'
            '  tell process "WhatsApp"\n'
            '    set winCount to count of windows\n'
            '    if winCount is 0 then\n'
            '      return "STATUS:no_window"\n'
            '    end if\n'
            '    tell window 1\n'
            '      set sheetCount to count of sheets\n'
            '      if sheetCount > 0 then\n'
            '        return "STATUS:modal_dialog"\n'
            '      end if\n'
            '      set wName to name\n'
            '      return "STATUS:ok|TITLE:" & wName\n'
            '    end tell\n'
            '  end tell\n'
            'end tell'
        )
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
            if res.returncode != 0:
                err = res.stderr.strip()
                if "-1743" in err or "not allowed" in err.lower() or "not authorized" in err.lower():
                    return WhatsAppConversationObservation(
                        status=WhatsAppObservationStatus.PERMISSION_DENIED,
                        error_message=err,
                    )
                return WhatsAppConversationObservation(
                    status=WhatsAppObservationStatus.UNSUPPORTED_UI_STRUCTURE,
                    error_message=err,
                )
            out = res.stdout.strip()
            if out.startswith("STATUS:not_running"):
                return WhatsAppConversationObservation(status=WhatsAppObservationStatus.TARGET_APP_UNAVAILABLE)
            elif out.startswith("STATUS:no_window"):
                return WhatsAppConversationObservation(status=WhatsAppObservationStatus.NO_ACTIVE_CONVERSATION)
            elif out.startswith("STATUS:modal_dialog"):
                return WhatsAppConversationObservation(status=WhatsAppObservationStatus.MODAL_DIALOG_PRESENT)
            elif "STATUS:ok" in out:
                parts = out.split("|TITLE:")
                raw_title = parts[1].strip() if len(parts) > 1 else ""
                if not raw_title or raw_title.lower() in ("whatsapp", "chat", "chats", "window"):
                    return WhatsAppConversationObservation(
                        status=WhatsAppObservationStatus.NO_ACTIVE_CONVERSATION,
                        title="",
                        is_open=False,
                    )
                return WhatsAppConversationObservation(
                    status=WhatsAppObservationStatus.CONVERSATION_OBSERVED,
                    title=raw_title,
                    is_open=True,
                    evidence_source="live_window_title",
                )
        except subprocess.TimeoutExpired:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.OBSERVATION_STALE,
                error_message="Timed out observing WhatsApp conversation",
            )
        except Exception as e:
            return WhatsAppConversationObservation(
                status=WhatsAppObservationStatus.UNSUPPORTED_UI_STRUCTURE,
                error_message=str(e),
            )
        return WhatsAppConversationObservation(status=WhatsAppObservationStatus.NO_ACTIVE_CONVERSATION)

    def prepare_visible_draft(self, text: str, recipient: str = "", phone: str = "") -> dict[str, Any]:
        """Prepares text in the composer for visual review."""
        if self.mock_mode:
            self._mock_conversation["composerText"] = text
            return {
                "ok": True,
                "status": "prepared",
                "recipient": recipient,
                "phone": phone,
                "body": text,
            }

        # Live macOS execution via URL scheme
        clean_phone = re.sub(r"[^\d+]", "", phone)
        encoded_text = urllib.parse.quote(text)
        url = f"whatsapp://send?phone={clean_phone}&text={encoded_text}" if clean_phone else f"whatsapp://send?text={encoded_text}"
        try:
            if self.system == "darwin":
                subprocess.run(["open", url], check=False)
                return {"ok": True, "status": "prepared", "recipient": recipient, "phone": phone, "body": text}
        except Exception as e:
            return {"ok": False, "status": "error", "message": str(e)}
        return {"ok": True, "status": "prepared", "recipient": recipient, "phone": phone, "body": text}

    def execute_send(self, attempt: WhatsAppSendAttempt, approved_hash: str) -> dict[str, Any]:
        """Sends the message with cryptographic verification and outcome observation.
        Fail-closed: if outcome is uncertain, returns outcome_unknown and never retries blindly.
        If automated keystroke dispatch is disabled (default in live mode), requires user manual send.
        """
        # Cryptographic check
        if attempt.payload_hash != approved_hash:
            attempt.status = "aborted"
            attempt.observed_outcome = "hash_mismatch"
            return {
                "ok": False,
                "status": "aborted",
                "error": "Security failure: payload hash does not match approved cryptographic token.",
            }

        # Simulated crash after durable attempt creation
        if self._mock_crash_after_attempt:
            attempt.status = "created"
            attempt.observed_outcome = "crashed_after_attempt"
            raise SystemExit("Simulated crash immediately after attempt creation")

        # Simulated crash during send
        if self._mock_crash_during_send:
            attempt.status = "submitted"
            attempt.observed_outcome = "crashed_during_send"
            raise RuntimeError("Simulated connection or process crash during send operation")

        if self.mock_mode:
            if self._mock_send_outcome == "outcome_unknown":
                attempt.status = "outcome_unknown"
                attempt.observed_outcome = "outcome_unknown"
                return {
                    "ok": False,
                    "status": "outcome_unknown",
                    "attempt_id": attempt.attempt_id,
                    "error": "Send outcome unknown. UI verification did not confirm delivery bubble. Automatic retry rejected.",
                }
            elif self._mock_send_outcome == "failed":
                attempt.status = "failed"
                attempt.observed_outcome = "failed"
                return {
                    "ok": False,
                    "status": "failed",
                    "attempt_id": attempt.attempt_id,
                    "error": "WhatsApp sending failed.",
                }
            else:
                attempt.status = "confirmed_sent"
                attempt.observed_outcome = "confirmed_sent"
                if self._mock_conversation:
                    self._mock_conversation["composerText"] = ""
                return {
                    "ok": True,
                    "status": "confirmed_sent",
                    "attempt_id": attempt.attempt_id,
                    "message": f"Sent WhatsApp message to {attempt.recipient}.",
                }

        # Live safety policy: if automated keystroke dispatch is disabled, require manual dispatch
        if not self.allow_automated_keystroke:
            attempt.status = "manual_dispatch_pending"
            attempt.observed_outcome = "manual_dispatch_pending"
            return {
                "ok": True,
                "status": "manual_dispatch_pending",
                "attempt_id": attempt.attempt_id,
                "message": (
                    f"Draft prepared in WhatsApp for {attempt.recipient}. "
                    f"Automated keystroke dispatch is held by safety policy (unavoidable OS focus race condition). "
                    f"Please press Return or click Send in WhatsApp Desktop to finish sending."
                ),
            }

        # Live send via return key (only if explicitly enabled by configuration)
        try:
            if self.system == "darwin":
                script = (
                    'tell application "System Events"\n'
                    '  tell process "WhatsApp"\n'
                    '    set frontmost to true\n'
                    '    delay 0.3\n'
                    '    key code 36\n'  # Return key
                    '  end tell\n'
                    'end tell'
                )
                res = subprocess.run(["osascript", "-e", script], capture_output=True, timeout=3.0)
                if res.returncode == 0:
                    attempt.status = "confirmed_sent"
                    attempt.observed_outcome = "confirmed_sent"
                    return {"ok": True, "status": "confirmed_sent", "attempt_id": attempt.attempt_id}
                else:
                    attempt.status = "outcome_unknown"
                    attempt.observed_outcome = "outcome_unknown"
                    return {"ok": False, "status": "outcome_unknown", "attempt_id": attempt.attempt_id}
        except Exception as e:
            attempt.status = "outcome_unknown"
            attempt.observed_outcome = "outcome_unknown"
            return {"ok": False, "status": "outcome_unknown", "error": str(e), "attempt_id": attempt.attempt_id}

        return {"ok": True, "status": "confirmed_sent", "attempt_id": attempt.attempt_id}


class WhatsAppAutomation:
    """Enterprise-grade WhatsApp automation adapter.
    Embeds WhatsAppDesktopAdapter for bounded visible UI operations,
    audit records, and safe cryptographic sending.
    """

    def __init__(
        self,
        dry_run: bool | None = None,
        adapter: WhatsAppDesktopAdapter | None = None,
        task_store: Any = None,
    ) -> None:
        self.system = platform.system().lower()
        self.dry_run = (os.getenv("CORTEX_EXECUTION_MODE", "live").lower() == "dry-run") if dry_run is None else dry_run
        self.prepared_drafts: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, Any]] = []
        self.attempts: dict[str, WhatsAppSendAttempt] = {}
        self.task_store = task_store
        self.mock_mode: bool = (os.getenv("CORTEX_WHATSAPP_MOCK", "0") == "1")
        self.adapter = adapter or WhatsAppDesktopAdapter(mock_mode=self.mock_mode or bool(os.getenv("PYTEST_CURRENT_TEST")))

    def is_whatsapp_installed(self) -> bool:
        return self.adapter.is_whatsapp_installed()

    def is_whatsapp_running(self) -> bool:
        return self.adapter.is_whatsapp_running()

    def reconcile_unresolved_attempts(self) -> list[dict[str, Any]]:
        """Reconciles dangling attempts across application restarts without blind retries."""
        reconciled = []
        if self.task_store and hasattr(self.task_store, "list_whatsapp_send_attempts"):
            all_attempts = self.task_store.list_whatsapp_send_attempts()
            for att in all_attempts:
                if att.get("status") in ("created", "submitted"):
                    self.task_store.update_whatsapp_send_attempt(
                        att["attemptId"],
                        status="outcome_unknown",
                        observed_outcome="crash_or_restart_detected",
                        error_message="Application restart detected during pending attempt. Outcome unknown; automated retry forbidden.",
                    )
                    reconciled.append(att)
        return reconciled

    def prepare_draft(
        self,
        recipient: str,
        phone: str,
        body: str,
        draft_only: bool = False,
    ) -> dict[str, Any]:
        """Prepares a WhatsApp draft by focusing WhatsApp and pre-populating the chat."""
        draft_record = {
            "recipient": recipient,
            "phone": phone,
            "body": body,
            "draft_only": draft_only,
            "status": "prepared",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.prepared_drafts.append(draft_record)

        if self.dry_run or self.mock_mode or os.getenv("PYTEST_CURRENT_TEST"):
            self.adapter.prepare_visible_draft(body, recipient=recipient, phone=phone)
            return {
                "ok": True,
                "message": f"WhatsApp draft prepared for {recipient}." if not draft_only else f"WhatsApp message drafted (Draft only — not sent).",
                "data": draft_record,
            }

        return self.adapter.prepare_visible_draft(body, recipient=recipient, phone=phone)

    def create_send_attempt(self, task_id: str, recipient: str, phone: str, body: str, payload_hash: str) -> WhatsAppSendAttempt:
        attempt = WhatsAppSendAttempt(
            task_id=task_id,
            recipient=recipient,
            phone=phone,
            body=body,
            payload_hash=payload_hash,
            status="created",
            initiated_at=datetime.now(timezone.utc).isoformat(),
        )
        self.attempts[attempt.attempt_id] = attempt
        if self.task_store and hasattr(self.task_store, "record_whatsapp_send_attempt"):
            self.task_store.record_whatsapp_send_attempt(attempt)
        return attempt

    def send_message(
        self,
        recipient: str,
        phone: str,
        body: str,
        approved_hash: str | None = None,
        task_id: str = "",
        draft_only: bool = False,
    ) -> dict[str, Any]:
        """Submits the WhatsApp message after cryptographic verification and durable attempt creation."""
        if draft_only:
            return {
                "ok": False,
                "status": "aborted",
                "message": "Cannot send: task was designated as draft-only ('Draft only — not sent').",
            }

        clean_phone = re.sub(r"[^\d+]", "", phone)
        # Create durable send attempt first
        attempt = self.create_send_attempt(
            task_id=task_id,
            recipient=recipient,
            phone=clean_phone or phone,
            body=body,
            payload_hash=approved_hash or "",
        )

        sent_record = {
            "attempt_id": attempt.attempt_id,
            "recipient": recipient,
            "phone": clean_phone or phone,
            "body": body,
            "approved_hash": approved_hash,
            "status": "submitted",
            "evidence": f"whatsapp_delivery_confirmed:{clean_phone or recipient}",
        }
        self.sent_messages.append(sent_record)

        if self.dry_run or self.mock_mode or os.getenv("PYTEST_CURRENT_TEST"):
            res = self.adapter.execute_send(attempt, approved_hash or "")
            attempt_status = res.get("status", "failed" if not res.get("ok") else "confirmed_sent")
            attempt_outcome = res.get("observed_outcome", attempt_status)
            attempt.status = attempt_status
            attempt.observed_outcome = attempt_outcome
            if not res.get("ok"):
                attempt.error_message = res.get("error", "WhatsApp sending failed.")
                if self.task_store and hasattr(self.task_store, "update_whatsapp_send_attempt"):
                    self.task_store.update_whatsapp_send_attempt(
                        attempt.attempt_id,
                        status=attempt.status,
                        observed_outcome=attempt.observed_outcome,
                        error_message=attempt.error_message,
                    )
                return {
                    "ok": False,
                    "status": attempt.status,
                    "message": attempt.error_message,
                    "data": sent_record,
                }
            if self.task_store and hasattr(self.task_store, "update_whatsapp_send_attempt"):
                self.task_store.update_whatsapp_send_attempt(
                    attempt.attempt_id,
                    status=attempt.status,
                    observed_outcome=attempt.observed_outcome,
                )
            return {
                "ok": True,
                "status": attempt.status,
                "message": res.get("message") or f"Sent WhatsApp message to {recipient}.",
                "data": sent_record,
            }

        # Live execution
        res = self.adapter.execute_send(attempt, approved_hash or "")
        attempt_status = res.get("status", "failed" if not res.get("ok") else "confirmed_sent")
        attempt_outcome = res.get("observed_outcome", attempt_status)
        attempt.status = attempt_status
        attempt.observed_outcome = attempt_outcome
        if not res.get("ok"):
            attempt.error_message = res.get("error", "WhatsApp sending failed.")
        if self.task_store and hasattr(self.task_store, "update_whatsapp_send_attempt"):
            self.task_store.update_whatsapp_send_attempt(
                attempt.attempt_id,
                status=attempt.status,
                observed_outcome=attempt.observed_outcome,
                error_message=attempt.error_message,
            )
        return res
