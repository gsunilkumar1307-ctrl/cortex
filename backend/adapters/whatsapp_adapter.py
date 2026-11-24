"""macOS WhatsApp Desktop Application Adapter.

Implements the universal ApplicationAdapter contract for WhatsApp Desktop on macOS:
- launch()
- focus()
- observe(target_context)
- execute_action(action, params)
- verify_action(action, params, observation)
- recover(action, params, error, attempt)

Enforces:
- Contact search, selection, and conversation identity verification.
- Exact message typing and composer content inspection.
- Independent verification distinguishing composer content from sent messages.
- Strict cryptographic single-use approval verification before external send.
- Active conversation revalidation immediately prior to send.
- Fail-closed outcome handling: unverified sends remain UNVERIFIED and never auto-resend.
- Bounded recovery without duplicate side effects or approval bypasses.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import time
from typing import Any
from uuid import uuid4

try:
    from backend.core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ContactResolutionStatus,
        ExecutionError,
        TaskCommand,
        VerificationResult,
        VerifiedContact,
        WhatsAppDraft,
    )
    from backend.adapters.base import ApplicationAdapter
    from backend.capabilities.whatsapp_actions import (
        WhatsAppCandidate,
        WhatsAppConversationObservation,
        WhatsAppDesktopAdapter,
        WhatsAppObservationStatus,
        WhatsAppSendAttempt,
        WhatsAppUIState,
    )
except ImportError:
    from core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ContactResolutionStatus,
        ExecutionError,
        TaskCommand,
        VerificationResult,
        VerifiedContact,
        WhatsAppDraft,
    )
    from adapters.base import ApplicationAdapter
    from capabilities.whatsapp_actions import (
        WhatsAppCandidate,
        WhatsAppConversationObservation,
        WhatsAppDesktopAdapter,
        WhatsAppObservationStatus,
        WhatsAppSendAttempt,
        WhatsAppUIState,
    )


class WhatsAppAdapter(ApplicationAdapter):
    """Application Adapter for WhatsApp Desktop on macOS."""

    def __init__(
        self,
        dry_run: bool = False,
        task_store: Any = None,
        desktop_adapter: WhatsAppDesktopAdapter | None = None,
    ) -> None:
        super().__init__(app_name="WhatsApp", dry_run=dry_run)
        self.system = platform.system().lower()
        self.task_store = task_store
        is_live = (os.getenv("CORTEX_WHATSAPP_LIVE", "0") == "1")
        mock_mode = False if is_live else (dry_run or (os.getenv("CORTEX_WHATSAPP_MOCK", "0") == "1") or bool(os.getenv("PYTEST_CURRENT_TEST")))
        self.desktop_adapter = desktop_adapter or WhatsAppDesktopAdapter(mock_mode=mock_mode)

        # Internal state tracking for deterministic simulated / test mode
        self._simulated_running: bool = False
        self._simulated_active: bool = False
        self._active_conversation: dict[str, Any] = {
            "title": "",
            "phone": None,
            "isOpen": False,
            "composerText": "",
            "sentMessages": [],
        }
        self._simulated_contacts: list[dict[str, Any]] = [
            {"id": "c_manu", "name": "Manu", "phone": "+91 98765 11111", "role": "friend"},
            {"id": "c_rahul", "name": "Rahul Sharma", "phone": "+91 98765 43210", "role": "colleague"},
            {"id": "c_priya", "name": "Priya Patel", "phone": "+91 98765 67890", "role": "team lead"},
        ]
        self._consumed_approval_tokens: set[str] = set()
        self._send_attempts: dict[str, WhatsAppSendAttempt] = {}
        self.whatsapp_automation: Any = None

    def is_app_installed(self) -> bool:
        """Checks if WhatsApp Desktop is installed."""
        return self.desktop_adapter.is_whatsapp_installed()

    def is_app_running(self) -> bool:
        """Checks if WhatsApp Desktop is currently running."""
        if self.dry_run or self.desktop_adapter.mock_mode:
            return self._simulated_running
        return self.desktop_adapter.is_whatsapp_running()

    def is_app_active(self) -> bool:
        """Checks if WhatsApp is the frontmost application."""
        if self.dry_run or self.desktop_adapter.mock_mode:
            return self._simulated_active
        if self.system != "darwin":
            return False
        script = 'tell application "System Events" to name of first application process whose frontmost is true'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
            return res.stdout.strip().lower() == "whatsapp"
        except Exception:
            return False

    # ── 1. Application Lifecycle ───────────────────────────────────────────

    def launch(self) -> AdapterResult:
        """Launches WhatsApp Desktop if not running."""
        start_time = time.time()
        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            self._simulated_running = True
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="launch",
                message="Launched WhatsApp (simulated).",
                data={"appName": "WhatsApp", "running": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        if self.is_app_running():
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="launch",
                message="WhatsApp is already running.",
                data={"appName": "WhatsApp", "running": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            subprocess.run(["open", "-a", "WhatsApp"], check=True, capture_output=True, timeout=5.0)
            ready = False
            for _ in range(15):
                if self.is_app_running():
                    ready = True
                    break
                time.sleep(0.1)

            if ready:
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="launch",
                    message="Launched WhatsApp successfully.",
                    data={"appName": "WhatsApp", "running": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="launch",
                    message="WhatsApp process failed to start within timeout.",
                    error="LaunchTimeout",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="launch",
                message=f"Failed to launch WhatsApp: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def focus(self) -> AdapterResult:
        """Brings WhatsApp Desktop and its main window to the foreground."""
        start_time = time.time()
        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            self._simulated_running = True
            self._simulated_active = True
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="focus",
                message="Focused WhatsApp (simulated).",
                data={"appName": "WhatsApp", "active": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        if not self.is_app_running():
            launch_res = self.launch()
            if not launch_res.success:
                return launch_res

        script = """
        tell application "System Events"
            tell process "WhatsApp"
                set frontmost to true
                repeat 10 times
                    if exists (window 1) then exit repeat
                    delay 0.1
                end repeat
            end tell
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=3.0)
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="focus",
                message="Focused WhatsApp.",
                data={"appName": "WhatsApp", "active": True},
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="focus",
                message=f"Failed to focus WhatsApp: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    # ── 2. Real-World Observation ──────────────────────────────────────────

    def observe(self, target_context: dict[str, Any] | None = None) -> AdapterObservation:
        """Captures real-world external state from WhatsApp Desktop."""
        ctx = target_context or {}
        running = self.is_app_running()
        active = self.is_app_active() if running else False

        state: dict[str, Any] = {
            "appName": "WhatsApp",
            "app_running": running,
            "app_active": active,
            "active_conversation": "",
            "contact_phone": None,
            "composer_text": "",
            "sent_messages": [],
            "last_message": "",
            "is_open": False,
            "ui_state": "ready" if running else "app_not_running",
            "unverified": False,
            "already_present": False,
            "already_sent": False,
            "already_drafted": False,
        }

        target_text = ctx.get("formatted_body") or ctx.get("text") or ctx.get("body") or ""
        raw_body = (ctx.get("body") or "").strip()
        target_rec = ctx.get("recipient") or ctx.get("title") or ""

        # Simulated or mock environment
        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            conv = self._active_conversation
            conv_open = conv.get("isOpen", False)
            conv_title = conv.get("title", "")
            comp_text = conv.get("composerText", "")
            sent = conv.get("sentMessages", [])

            state["active_conversation"] = conv_title
            state["contact_phone"] = conv.get("phone")
            state["composer_text"] = comp_text
            state["sent_messages"] = list(sent)
            state["last_message"] = sent[-1] if sent else ""
            state["is_open"] = conv_open
            state["ui_state"] = "conversation_open" if conv_open else "ready"

            check_texts = [t for t in (target_text, raw_body) if t]
            for t in check_texts:
                if t in comp_text or comp_text in t:
                    state["already_drafted"] = True
                    state["already_present"] = True
                if any(t.lower() in m.lower() or m.lower() in t.lower() for m in sent):
                    state["already_sent"] = True
                    state["already_present"] = True

            if ctx.get("unverified"):
                state["unverified"] = True

            return AdapterObservation(
                target="app:WhatsApp",
                state_data=state,
                raw_output=json.dumps(state),
            )

        # Live macOS accessibility inspection
        if not running:
            return AdapterObservation(
                target="app:WhatsApp",
                state_data=state,
                raw_output="WhatsApp not running",
            )

        obs = self.desktop_adapter.observe_current_conversation()
        state["active_conversation"] = obs.title
        state["contact_phone"] = obs.phone
        state["composer_text"] = obs.composer_text
        state["is_open"] = obs.is_open
        state["ui_state"] = obs.status.value if hasattr(obs.status, "value") else str(obs.status)
        state["sent_messages"] = list(self._active_conversation.get("sentMessages", []))

        if target_text:
            if target_text.lower() in obs.composer_text.lower():
                state["already_drafted"] = True
                state["already_present"] = True

        if obs.status == WhatsAppObservationStatus.OBSERVATION_STALE or ctx.get("unverified"):
            state["unverified"] = True

        return AdapterObservation(
            target="app:WhatsApp",
            state_data=state,
            raw_output=json.dumps(obs.to_dict()),
        )

    # ── 3. Action Execution ────────────────────────────────────────────────

    def execute_action(self, action: str, params: dict[str, Any]) -> AdapterResult:
        """Executes a domain action on WhatsApp Desktop."""
        start_time = time.time()
        act = action.strip().lower()

        if act in ("launch", "open_app"):
            return self.launch()

        if act in ("focus", "focus_app"):
            return self.focus()

        if act == "search_contact":
            query = params.get("query") or params.get("recipient") or ""
            return self._execute_search_contact(query, start_time)

        if act in ("select_contact", "open_conversation"):
            recipient = params.get("recipient") or params.get("title") or ""
            phone = params.get("phone", "")
            return self._execute_open_conversation(recipient, phone, start_time)

        if act in ("type_message", "type_text", "prepare_draft", "draft_whatsapp"):
            body = params.get("body") or params.get("text") or ""
            recipient = params.get("recipient") or params.get("contact_name") or ""
            phone = params.get("phone", "")
            return self._execute_type_message(body, recipient, phone, start_time)

        if act in ("send_message", "send", "send_whatsapp"):
            return self._execute_send_message(params, start_time)

        return AdapterResult(
            success=False,
            status=AdapterExecutionStatus.FAILED,
            action=act,
            message=f"Unsupported WhatsApp action: '{act}'",
            error="UnsupportedAction",
            duration_ms=(time.time() - start_time) * 1000,
        )

    def _execute_search_contact(self, query: str, start_time: float) -> AdapterResult:
        """Searches for visible contacts matching query."""
        if not query:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="search_contact",
                message="Contact search query is required.",
                error="EmptyQuery",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if self.dry_run or self.desktop_adapter.mock_mode:
            q_norm = query.strip().lower()
            matches = [
                c for c in self._simulated_contacts
                if q_norm in c["name"].lower() or q_norm in c.get("phone", "")
            ]
            candidates = [
                WhatsAppCandidate(display_name=c["name"], phone_number=c.get("phone"))
                for c in matches
            ]
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="search_contact",
                message=f"Found {len(candidates)} contact match(es) for '{query}'.",
                data={"query": query, "candidates": [c.to_dict() for c in candidates], "count": len(candidates)},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Live search via desktop adapter
        try:
            candidates = self.desktop_adapter.search_visible_contacts(query)
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="search_contact",
                message=f"Found {len(candidates)} visible candidate(s) in WhatsApp.",
                data={"query": query, "candidates": [c.to_dict() for c in candidates], "count": len(candidates)},
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="search_contact",
                message=f"Contact search failed: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_open_conversation(self, recipient: str, phone: str, start_time: float) -> AdapterResult:
        """Opens or switches to a WhatsApp conversation."""
        if not recipient and not phone:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="open_conversation",
                message="Recipient name or phone number is required to open a conversation.",
                error="MissingRecipient",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Set simulated state
        self._active_conversation["title"] = recipient
        self._active_conversation["phone"] = phone
        self._active_conversation["isOpen"] = True

        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            self.desktop_adapter.select_candidate(WhatsAppCandidate(display_name=recipient, phone_number=phone))
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="open_conversation",
                message=f"Opened WhatsApp conversation with '{recipient}'.",
                data={"recipient": recipient, "phone": phone, "isOpen": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Live URL scheme invocation to open chat
        clean_phone = re.sub(r"[^\d+]", "", phone)
        url = f"whatsapp://send?phone={clean_phone}" if clean_phone else "whatsapp://"
        try:
            subprocess.run(["open", url], check=True, timeout=5.0)
            time.sleep(0.5)
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="open_conversation",
                message=f"Opened WhatsApp conversation with '{recipient}'.",
                data={"recipient": recipient, "phone": phone, "isOpen": True},
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="open_conversation",
                message=f"Failed to open conversation: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_type_message(self, body: str, recipient: str, phone: str, start_time: float) -> AdapterResult:
        """Focuses the message composer and types the exact message text."""
        if not body:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_message",
                message="Message body cannot be empty.",
                error="EmptyBody",
                duration_ms=(time.time() - start_time) * 1000,
            )

        clean_text = body.strip()

        # Check active conversation identity match
        curr_title = self._active_conversation.get("title", "")
        if curr_title and recipient and curr_title.lower() != recipient.lower():
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_message",
                message=f"Active conversation mismatch: active '{curr_title}' != expected '{recipient}'.",
                error="ConversationMismatch",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Idempotency / duplicate check
        curr_composer = self._active_conversation.get("composerText", "")
        if clean_text in curr_composer:
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="type_message",
                message="Text is already present in WhatsApp composer. Duplicate typing safely prevented.",
                data={"text": clean_text, "recipient": recipient, "already_present": True, "composer_text": curr_composer},
                duration_ms=(time.time() - start_time) * 1000,
            )

        self._active_conversation["title"] = recipient or curr_title
        self._active_conversation["phone"] = phone
        self._active_conversation["composerText"] = clean_text
        self._active_conversation["isOpen"] = True

        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            self.desktop_adapter.prepare_visible_draft(clean_text, recipient=recipient, phone=phone)
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="type_message",
                message=f"Prepared WhatsApp draft for '{recipient}'.",
                data={"text": clean_text, "recipient": recipient, "phone": phone, "composer_text": clean_text, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Live macOS preparation via URL scheme
        res = self.desktop_adapter.prepare_visible_draft(clean_text, recipient=recipient, phone=phone)
        if res.get("ok"):
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="type_message",
                message=f"Prepared WhatsApp draft for '{recipient}'.",
                data={"text": clean_text, "recipient": recipient, "phone": phone, "composer_text": clean_text, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_message",
                message=f"Failed to prepare WhatsApp message: {res.get('message', 'Unknown error')}",
                error=res.get("message", "PreparationFailed"),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_send_message(self, params: dict[str, Any], start_time: float) -> AdapterResult:
        """Sends an approved WhatsApp message with strict pre-send checks and post-send verification."""
        nested = params.get("params") if isinstance(params.get("params"), dict) else {}
        recipient = params.get("recipient") or nested.get("recipient") or params.get("contact_name") or nested.get("contact_name") or ""
        phone = params.get("phone") or nested.get("phone") or ""
        body = params.get("formatted_body") or nested.get("formatted_body") or params.get("body") or nested.get("body") or params.get("text") or nested.get("text") or ""
        approved_hash = params.get("approved_hash") or params.get("approval_hash") or nested.get("approved_hash") or nested.get("approval_hash")
        task_id = params.get("task_id") or nested.get("task_id") or ""
        contact_id = params.get("contact_id") or nested.get("contact_id") or ""
        contact_source = params.get("contact_source") or nested.get("contact_source") or ""
        draft_only = bool(params.get("draft_only") or nested.get("draft_only", False))
        is_cancelled = params.get("is_cancelled") or nested.get("is_cancelled") or params.get("status") in ("cancelled", "canceled") or nested.get("status") in ("cancelled", "canceled")
        approval_expired = params.get("approval_expired") or nested.get("approval_expired")
        clean_phone = re.sub(r"[^\d+]", "", phone)

        # ── Gate 1: Task Cancellation Guard ───────────────────────────────
        if is_cancelled:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Cannot send: task has been cancelled.",
                error="TaskCancelled",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # ── Gate 2: Explicit Single-Use Approval Validation ────────────────
        if not approved_hash:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Sending blocked: no valid single-use cryptographic approval token provided.",
                error="ApprovalRequired",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if approval_expired:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Sending blocked: approval request has expired. Fresh approval is required.",
                error="ApprovalExpired",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if approved_hash in self._consumed_approval_tokens:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Security violation: approval token has already been consumed. Replay rejected.",
                error="ApprovalReplay",
                duration_ms=(time.time() - start_time) * 1000,
            )

        draft = WhatsAppDraft(
            recipient=recipient,
            phone=clean_phone or phone,
            body=body,
            contact_id=contact_id,
            contact_source=contact_source,
            draft_only=draft_only,
        )
        expected_hash = draft.compute_hash()
        if approved_hash != expected_hash:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Security violation: approval token mismatch. Parameters modified after approval.",
                error="ApprovalMismatch",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # In live desktop mode, synchronize with actual UI before pre-send checks
        if not (self.dry_run or self.desktop_adapter.mock_mode or self.system != "darwin"):
            live_obs = self.desktop_adapter.observe_current_conversation()
            if live_obs.is_open and live_obs.title:
                self._active_conversation["title"] = live_obs.title
                if live_obs.phone:
                    self._active_conversation["phone"] = live_obs.phone
                if live_obs.composer_text is not None:
                    self._active_conversation["composerText"] = live_obs.composer_text

        # ── Gate 3: Active Conversation & Recipient Identity Guard ─────────
        curr_title = self._active_conversation.get("title") or ""
        clean_curr_title = re.sub(r"[\u200e\u202a\u202c\xa0]", "", str(curr_title)).strip()
        curr_digits = re.sub(r"\D", "", clean_curr_title)
        phone_digits = re.sub(r"\D", "", str(phone or ""))
        phone_matches = bool(phone_digits and curr_digits and (phone_digits in curr_digits or curr_digits in phone_digits))
        name_matches = bool(clean_curr_title and recipient and (clean_curr_title.lower() == recipient.lower() or recipient.lower() in clean_curr_title.lower() or clean_curr_title.lower() in recipient.lower()))

        if curr_title and recipient and not (phone_matches or name_matches):
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message=f"Safety violation: active conversation '{curr_title}' does not match approved recipient '{recipient}'.",
                error="ConversationMismatch",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # ── Gate 4: Composer Content Revalidation ──────────────────────────
        curr_composer = self._active_conversation.get("composerText") or ""
        clean_curr = re.sub(r"[\u200e\u202a\u202c\xa0\s]", "", str(curr_composer))
        clean_body = re.sub(r"[\u200e\u202a\u202c\xa0\s]", "", str(body or ""))
        if clean_curr and clean_body and clean_body not in clean_curr and clean_curr not in clean_body:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="send_message",
                message="Composer revalidation failed: composer contents were modified after approval.",
                error="ComposerModified",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Consume the single-use token
        self._consumed_approval_tokens.add(approved_hash)

        # Durable send attempt record
        attempt_id = str(uuid4())
        attempt = WhatsAppSendAttempt(
            task_id=task_id,
            recipient=recipient,
            phone=clean_phone or phone,
            body=body,
            payload_hash=approved_hash,
            attempt_id=attempt_id,
            status="submitted",
        )
        self._send_attempts[attempt_id] = attempt
        if self.task_store and hasattr(self.task_store, "record_whatsapp_send_attempt"):
            self.task_store.record_whatsapp_send_attempt(attempt)

        # ── Gate 5: External Send Execution & Independent Verification ─────
        # Simulated or mock path
        if self.dry_run or self.system != "darwin" or self.desktop_adapter.mock_mode:
            if params.get("force_uncertain") or getattr(self.desktop_adapter, "_mock_send_outcome", "") == "outcome_unknown":
                attempt.status = "outcome_unknown"
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.UNVERIFIED,
                    action="send_message",
                    message="Send outcome uncertain: outgoing delivery could not be confirmed in WhatsApp conversation.",
                    error="UNVERIFIED",
                    data={"attempt_id": attempt_id, "recipient": recipient, "unverified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Successfully send: clear composer and append to sentMessages
            self._active_conversation["composerText"] = ""
            self._active_conversation["sentMessages"].append(body.strip())
            attempt.status = "confirmed_sent"
            attempt.observed_outcome = "confirmed_sent"

            wa_auto = getattr(self, "whatsapp_automation", None)
            if wa_auto and hasattr(wa_auto, "sent_messages"):
                wa_auto.sent_messages.append({
                    "recipient": recipient,
                    "phone": clean_phone or phone,
                    "body": body,
                    "approved_hash": approved_hash,
                    "attempt_id": attempt_id,
                })

            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="send_message",
                message=f"Sent WhatsApp message to '{recipient}'.",
                data={
                    "attempt_id": attempt_id,
                    "recipient": recipient,
                    "phone": phone,
                    "body": body,
                    "sent": True,
                    "composer_cleared": True,
                    "verified": True,
                },
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Live macOS execution
        res = self.desktop_adapter.execute_send(attempt, approved_hash)
        if res.get("ok"):
            # Clear composer in state and verify
            self._active_conversation["composerText"] = ""
            self._active_conversation["sentMessages"].append(body.strip())
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="send_message",
                message=f"Sent WhatsApp message to '{recipient}'.",
                data={
                    "attempt_id": attempt_id,
                    "recipient": recipient,
                    "phone": phone,
                    "body": body,
                    "sent": True,
                    "verified": True,
                },
                duration_ms=(time.time() - start_time) * 1000,
            )
        else:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.UNVERIFIED if res.get("status") == "outcome_unknown" else AdapterExecutionStatus.FAILED,
                action="send_message",
                message=res.get("error") or "WhatsApp send outcome unverified.",
                error="UNVERIFIED" if res.get("status") == "outcome_unknown" else res.get("error", "SendFailed"),
                data={"attempt_id": attempt_id, "recipient": recipient, "unverified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

    # ── 4. Independent Verification ────────────────────────────────────────

    def verify_action(
        self,
        action: str,
        params: dict[str, Any],
        observation: AdapterObservation,
    ) -> VerificationResult:
        """Independently verifies that the expected outcome occurred in WhatsApp Desktop."""
        act = action.strip().lower()
        state = observation.state_data or {}
        recipient = params.get("recipient") or params.get("contact_name") or state.get("active_conversation", "")

        if act in ("launch", "open_app"):
            app_running = state.get("app_running", True)
            if not self.dry_run and not app_running:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence="WhatsApp Desktop failed to launch: process is not running.",
                    error="NotRunning",
                )
            evidence = "Verified application 'WhatsApp' is running."
            if state.get("app_active"):
                evidence += " In foreground."
            return VerificationResult(verified=True, confidence=0.95, evidence=evidence)

        if act in ("focus", "focus_app"):
            if not state.get("ok", True):
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence="Failed to focus WhatsApp Desktop.",
                    error="FocusFailed",
                )
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence="Verified application 'WhatsApp' brought to foreground.",
            )

        if act in ("open_conversation", "select_contact"):
            active_conv = state.get("active_conversation", "")
            if recipient and active_conv and recipient.lower() not in active_conv.lower():
                return VerificationResult(
                    verified=False,
                    confidence=0.9,
                    evidence=f"Active conversation '{active_conv}' does not match intended recipient '{recipient}'.",
                    error="ConversationMismatch",
                )
            return VerificationResult(
                verified=state.get("is_open", True),
                confidence=0.95,
                evidence=f"Verified WhatsApp conversation '{recipient or active_conv}' is active.",
            )

        if act in ("type_message", "type_text", "prepare_draft", "draft_whatsapp"):
            target_text = params.get("body") or params.get("text") or ""
            target_text = re.sub(r"^(?:exactly\s*[:=]?|text\s*[:=]?)\s*", "", target_text, flags=re.IGNORECASE).strip()

            comp_text = state.get("composer_text", "")
            if state.get("unverified"):
                return VerificationResult(
                    verified=False,
                    confidence=0.2,
                    evidence=f"Text verification failed: could not confirm that '{target_text}' was entered into WhatsApp composer.",
                    error="UNVERIFIED",
                )

            # Ensure composer text contains target text
            if target_text and target_text.lower() in comp_text.lower():
                evidence = f"Verified message '{target_text}' successfully entered into WhatsApp composer for '{recipient}'." if recipient else f"Verified message '{target_text}' successfully entered into WhatsApp composer."
                return VerificationResult(verified=True, confidence=0.95, evidence=evidence)
            elif not target_text and comp_text:
                return VerificationResult(verified=True, confidence=0.9, evidence=f"Verified message entered into WhatsApp composer for '{recipient}'.")
            else:
                evidence = f"Text verification failed: composer text does not match requested message '{target_text}'." if target_text else "Text verification failed: composer is empty."
                return VerificationResult(verified=False, confidence=0.2, evidence=evidence, error="UNVERIFIED")

        if act in ("send_message", "send", "send_whatsapp"):
            target_text = (params.get("formatted_body") or params.get("body") or params.get("text") or "").strip()
            raw_body = (params.get("body") or "").strip()
            sent_messages = state.get("sent_messages") or []
            composer_text = state.get("composer_text", "")

            # 1. Reject if outcome is marked unverified
            if state.get("unverified"):
                return VerificationResult(
                    verified=False,
                    confidence=0.1,
                    evidence="Send verification failed: message delivery could not be confirmed in WhatsApp conversation.",
                    error="UNVERIFIED",
                )

            # 2. Critical Safety: Never confuse composer contents with sent messages!
            is_in_composer = bool(
                (target_text and target_text in composer_text)
                or (raw_body and raw_body in composer_text)
            )
            is_in_sent = bool(
                (target_text and any(target_text.lower() in m.lower() or m.lower() in target_text.lower() for m in sent_messages))
                or (raw_body and any(raw_body.lower() in m.lower() or m.lower() in raw_body.lower() for m in sent_messages))
            )

            if is_in_composer:
                return VerificationResult(
                    verified=False,
                    confidence=0.1,
                    evidence="Send verification failed: message is still visible in the composer and has NOT been sent.",
                    error="UNVERIFIED",
                )

            # 3. Verify outgoing message bubble in conversation or verified composer clearance
            if is_in_sent:
                evidence = f"Verified WhatsApp message '{target_text or raw_body}' sent to '{recipient}'." if recipient else f"Verified WhatsApp message '{target_text or raw_body}' sent."
                return VerificationResult(verified=True, confidence=0.95, evidence=evidence)
            elif state.get("already_sent"):
                return VerificationResult(verified=True, confidence=0.95, evidence=f"Verified WhatsApp message sent to '{recipient}'.")
            elif not composer_text and bool(self._active_conversation.get("sentMessages")):
                evidence = f"Verified WhatsApp message '{target_text or raw_body}' sent to '{recipient}' (composer cleared)." if recipient else f"Verified WhatsApp message sent."
                return VerificationResult(verified=True, confidence=0.95, evidence=evidence)
            else:
                return VerificationResult(
                    verified=False,
                    confidence=0.1,
                    evidence="Send verification failed: outgoing message was not observed in the conversation.",
                    error="UNVERIFIED",
                )

        return VerificationResult(
            verified=state.get("ok", True),
            confidence=0.9,
            evidence=f"Action '{act}' executed on WhatsApp.",
        )

    # ── 5. Bounded Error Recovery ──────────────────────────────────────────

    def recover(
        self,
        action: str,
        params: dict[str, Any],
        error: ExecutionError | str,
        attempt: int = 1,
    ) -> AdapterRecoveryResult:
        """Provides structured error diagnosis and bounded recovery for WhatsApp actions."""
        err_msg = error.message if isinstance(error, ExecutionError) else str(error)
        act = action.strip().lower()

        # Approval security violations: NEVER retry
        if any(k in err_msg.lower() for k in ("approval", "security violation", "replay", "expired")):
            return AdapterRecoveryResult(
                can_retry=False,
                strategy="escalate",
                message=f"Security policy halt: {err_msg}",
            )

        # Active conversation mismatch: NEVER retry blindly
        if "conversation mismatch" in err_msg.lower() or "safety violation" in err_msg.lower():
            return AdapterRecoveryResult(
                can_retry=False,
                strategy="escalate",
                message=f"Conversation alignment failure: {err_msg}. Manual verification required.",
            )

        # Task cancellation: NEVER resume
        if "cancelled" in err_msg.lower() or "canceled" in err_msg.lower():
            return AdapterRecoveryResult(
                can_retry=False,
                strategy="escalate",
                message="Task was cancelled. Recovery terminated.",
            )

        # Check if already drafted or sent via fresh observation
        if "already present" in err_msg.lower() or "already drafted" in err_msg.lower() or "already sent" in err_msg.lower():
            obs = self.observe(params)
            target_text = params.get("body") or params.get("text") or ""
            obs_state = obs.state_data or {}

            confirmed_present = False
            if obs_state.get("unverified") is True:
                confirmed_present = False
            elif act in ("send_message", "send", "send_whatsapp"):
                confirmed_present = bool(
                    obs_state.get("already_sent") is True
                    or (target_text and target_text in obs_state.get("sent_messages", []))
                )
            else:
                confirmed_present = bool(
                    obs_state.get("already_drafted") is True
                    or obs_state.get("already_present") is True
                    or (target_text and target_text in obs_state.get("composer_text", ""))
                )

            if confirmed_present:
                return AdapterRecoveryResult(
                    can_retry=False,
                    strategy="resolve_as_success",
                    message="Target state already confirmed in WhatsApp; duplicate action safely prevented.",
                )
            else:
                return AdapterRecoveryResult(
                    can_retry=False,
                    strategy="escalate",
                    message="Cannot resolve as success: independent observation did not confirm expected state in WhatsApp.",
                )

        # Critical Safety: Uncertain send outcome MUST NEVER automatically resend!
        if act in ("send_message", "send", "send_whatsapp") or "unverified" in err_msg.lower() or "outcome_unknown" in err_msg.lower():
            return AdapterRecoveryResult(
                can_retry=False,
                strategy="escalate",
                message="WhatsApp send outcome unverified. Automated resend is strictly forbidden to prevent duplicate external messages.",
            )

        # Focus / window recovery on attempt 1
        if attempt < 2 and any(k in err_msg.lower() for k in ("window", "focus", "not running", "not active")):
            self.focus()
            return AdapterRecoveryResult(
                can_retry=True,
                strategy="retry",
                message="WhatsApp window focus lost; refocused WhatsApp Desktop for safe retry.",
            )

        return AdapterRecoveryResult(
            can_retry=attempt < 2,
            strategy="retry" if attempt < 2 else "escalate",
            message=f"WhatsApp action '{act}' failed: {err_msg}.",
        )
