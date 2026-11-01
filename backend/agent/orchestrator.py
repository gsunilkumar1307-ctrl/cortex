from __future__ import annotations

import os
import time
import json
import re
import sys
import threading
import subprocess
import urllib.parse
import urllib.request
import html as html_lib
from pathlib import Path
from typing import Any

try:
    from backend.capabilities import DeviceAutomation, classify_command
    from backend.persistence import EncryptedMemoryStore, TaskStore
    from backend.core.contracts import (
        LanguageCode,
        RiskLevel,
        Task,
        TaskCommand,
        TaskStatus,
        command_from_intent,
        TaskContext,
        UserRequest,
        Intent,
        Plan,
        PlanStep,
        Observation,
        VerificationResult,
        ApprovalRequest,
        ExecutionResult,
        FinalResult,
        ActionAttempt,
        ActionAttemptStatus,
        canonical_status,
        TERMINAL_STATUSES,
        IllegalStateTransitionError,
        ConcurrencyError,
    )
    from backend.core.language_detector import detect_language, language_instruction, resolve_language
    from backend.core.translator import translate_text, is_unsupported_language_request, extract_explicit_language_directive
    from backend.core.localization import (
        localize,
        normalize_app_name,
        get_cortex_identity,
        get_cortex_capabilities,
        get_cortex_status,
        get_offline_knowledge,
    )
    from backend.core.direct_answers import resolve_direct_answer, clean_search_response
    from backend.integrations.search import search_web
    from backend.agent.policy import PolicyEngine
    from backend.tools.registry import ToolRegistry
    from backend.agent.execution_engine import ExecutionEngine
    from backend.agent.planner import AutonomousPlanner
    from backend.agent.email_engine import (
        ProfessionalEmailEngine,
        EmailDraft,
        sanitize_untrusted_email_content,
        is_ambiguous_email_intent,
        polish_email_body_text,
        convert_instruction_to_recipient_content,
    )
    from backend.agent.recipient_resolver import (
        RecipientResolver,
        ResolutionResult,
        ResolvedRecipient,
        WhatsAppContactSource,
        UserAuthorizedContactStore,
    )
    from backend.core.contracts import (
        WhatsAppDraft,
        ContactResolutionStatus,
        VerifiedContact,
        ContactResolutionResult,
    )
    from backend.capabilities.whatsapp_actions import compose_whatsapp_message, format_whatsapp_approval_card
except ImportError:
    from capabilities import DeviceAutomation, classify_command
    from persistence import EncryptedMemoryStore, TaskStore
    from core.contracts import (
        LanguageCode,
        RiskLevel,
        Task,
        TaskCommand,
        TaskStatus,
        command_from_intent,
        TaskContext,
        UserRequest,
        Intent,
        Plan,
        PlanStep,
        Observation,
        VerificationResult,
        ApprovalRequest,
        ExecutionResult,
        FinalResult,
        ActionAttempt,
        ActionAttemptStatus,
        canonical_status,
        TERMINAL_STATUSES,
        IllegalStateTransitionError,
        ConcurrencyError,
    )
    from core.language_detector import detect_language, language_instruction, resolve_language
    from core.translator import translate_text, is_unsupported_language_request, extract_explicit_language_directive
    from core.localization import (
        localize,
        normalize_app_name,
        get_cortex_identity,
        get_cortex_capabilities,
        get_cortex_status,
        get_offline_knowledge,
    )
    from core.direct_answers import resolve_direct_answer, clean_search_response
    from integrations.search import search_web
    from policy import PolicyEngine
    from tools.registry import ToolRegistry
    from execution_engine import ExecutionEngine
    from planner import AutonomousPlanner
    from email_engine import (
        ProfessionalEmailEngine,
        EmailDraft,
        sanitize_untrusted_email_content,
        is_ambiguous_email_intent,
        polish_email_body_text,
        convert_instruction_to_recipient_content,
    )
    from recipient_resolver import (
        RecipientResolver,
        ResolutionResult,
        ResolvedRecipient,
        WhatsAppContactSource,
        UserAuthorizedContactStore,
    )
    from core.contracts import (
        WhatsAppDraft,
        ContactResolutionStatus,
        VerifiedContact,
        ContactResolutionResult,
    )
    from capabilities.whatsapp_actions import compose_whatsapp_message, format_whatsapp_approval_card

try:
    from backend.core.adaptive_tone import detect_adaptive_tone, apply_tone_to_prompt
except ImportError:
    try:
        from core.adaptive_tone import detect_adaptive_tone, apply_tone_to_prompt
    except ImportError:
        detect_adaptive_tone = None
        apply_tone_to_prompt = None

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

SYSTEM_PROMPT = """You are Cortex, a powerful AI desktop assistant and knowledge engine.
You understand natural language commands for both computer control AND general questions.

ANSWERING STYLE — MASTER LLM STANDARD (Rivaling ChatGPT-4o, Claude 3.5 Sonnet, and Gemini Pro):
- Deliver high-caliber, insightful, accurate, and comprehensive answers.
- Lead with the core insight or answer immediately without fluff or sycophancy (no "Certainly!", "Great question!").
- For complex, conceptual, technical, or creative queries: provide deep explanations, step-by-step breakdowns, structured lists, and clean code examples where applicable.
- For simple factual queries: provide direct, crisp precision.
- Use clean Markdown: bold key terms, use bullet points for lists, and code blocks with syntax highlighting.
- NEVER use generic filler like "I hope that helps!", "Feel free to ask more!", "As an AI language model..."
- MULTILINGUAL MANDATE: If user inputs in Kannada, Hindi, Tamil, or Telugu, ANY conversational output or "answer" field MUST be written strictly in that same language and native script, NEVER in English.

App/Device Classification Rules (be VERY precise):
- If user says "open X", "launch X", "start X" → command = "open_app", appName = X
- If user says "close X", "quit X", "exit X" → command = "close_app", appName = X
- If user says "switch to X", "go to X", "focus X", "bring up X" → command = "focus_app", appName = X
- If user says "open youtube", "go to youtube.com", "open google", "open instagram" → command = "open_url", url = full URL
- If user says "search for X", "google X", "look up X" → command = "web_search", query = X
- If user asks ANY factual/general question → command = "ask_question", provide direct answer in "answer" field
- NEVER return command = "unknown" for a question — always classify as ask_question with a real answer.

All Supported Commands:
- "open_app": Open/launch a desktop application. Parameter: {"appName": string}
- "close_app": Close/quit an application. Parameter: {"appName": string}
- "focus_app": Switch to/activate an application. Parameter: {"appName": string}
- "type_text": Type text. Parameters: {"text": string, "appName": string (optional)}
- "keystroke": Press a key combination. Parameters: {"shortcut": string, "appName": string (optional)}
- "menu_item": Click a menu item in an app. Parameters: {"item": string, "menu": string, "appName": string}
- "write_note": Create a note. Parameters: {"title": string, "body": string}
- "send_message": Send iMessage. Parameters: {"recipient": string, "body": string}
- "calculate": Math. Parameter: {"expression": string}
- "screenshot": Take screenshot. No parameters.
- "clipboard_read": Read clipboard. No parameters.
- "clipboard_write": Copy to clipboard. Parameter: {"text": string}
- "notification": Show notification. Parameters: {"title": string, "message": string}
- "reminder": Set a reminder. Parameter: {"text": string}
- "shutdown": Power off computer. No parameters.
- "restart": Reboot computer. No parameters.
- "web_search": Search the web for facts, news, prices, weather, current events. Parameter: {"query": string}
- "open_url": Navigate browser to a URL (use for opening websites like YouTube, Google, Instagram, etc.). Parameter: {"url": string}
- "browser_click": Click a page element. Parameters: {"selector": string, "url": string (optional)}
- "browser_type": Type in a web field. Parameters: {"selector": string, "text": string, "url": string (optional)}
- "browser_scrape": Read web page content. Parameters: {"url": string, "selector": string (optional)}
- "screen_vision": Analyze what's on screen with vision model. Parameter: {"question": string (optional)}
- "observe_screen": Multi-source desktop perception (inspect active application, windows, accessible elements, OCR). Parameters: {"capture_screenshot": boolean, "run_ocr": boolean}
- "resolve_ui_element": Find/localize a specific UI element (button, field, tab, menu) in the active application. Parameter: {"target": string}
- "click_element": Click a specific UI element on the desktop interface. Parameter: {"target": string}
- "type_in_element": Type text into a specific desktop UI element/field. Parameters: {"target": string, "text": string}
- "desktop_workflow": Multi-step desktop operator workflow. Parameters: {"steps": list}
- "read_mail": Read inbox emails. Parameters: {"limit": integer, "unread_only": boolean}
- "summarize_mail": Summarize emails. Parameters: {"limit": integer, "unread_only": boolean}
- "draft_mail": Create email draft. Parameters: {"recipient": string, "subject": string, "body": string}
- "send_mail": Send an email. Parameters: {"recipient": string, "subject": string, "body": string}
- "ask_question": Answer any question, general knowledge, conversation, greetings. Provide answer in "answer" field.
- "unknown": ONLY use if the request is truly ambiguous AND cannot be answered as a question.

Safety Rules:
- Blocked: "delete file", "delete folder", "submit form", "payment", "purchase". Set risk_level="blocked".
- Approval-required: clipboard_write, send_message, shutdown, restart, browser_click, browser_type, send_mail.

URL Mapping (always use full URL for open_url):
- youtube / youtube.com → https://www.youtube.com
- google / google.com → https://www.google.com
- instagram → https://www.instagram.com
- twitter / x → https://www.x.com
- facebook → https://www.facebook.com
- gmail → https://mail.google.com
- github → https://www.github.com
- linkedin → https://www.linkedin.com
- netflix → https://www.netflix.com
- amazon → https://www.amazon.in
- maps / google maps → https://maps.google.com
- whatsapp web → https://web.whatsapp.com

CRITICAL RULE — COMMAND ≠ CONTENT:
- "Send mail to user@example.com": recipient="user@example.com", body=null.
- "Send email to Rahul saying I'll be late": command="send_mail", recipient="Rahul", body="I'll be late".
- If body/content not provided, leave body as "" — do NOT invent content.

Return ONLY this JSON (no markdown, no explanation outside JSON):
{
  "command": "command_name",
  "params": { ... },
  "risk_level": "low" | "medium" | "high" | "blocked",
  "requires_approval": true | false,
  "block_reason": "reason if blocked, else null",
  "answer": "direct answer if ask_question, else null"
}"""


def is_sensitive_attachment(path: str) -> bool:
    """Security check to block exfiltration of system credentials, keys, and configurations."""
    clean_p = str(path).strip().lower()
    sensitive_patterns = (
        "/etc/passwd", "/etc/shadow", "/etc/sudoers", "/etc/hosts", "/etc/master.passwd",
        "/private/etc", ".env", ".session_secret", "id_rsa", "id_ed25519", "id_dsa",
        "id_ecdsa", ".ssh/", ".ssh\\", ".aws/", ".gnupg/", ".bash_history", ".zsh_history"
    )
    if any(p in clean_p for p in sensitive_patterns) or clean_p.endswith((".key", ".pem", ".p12", ".pfx")):
        return True
    return False


def is_draft_only_request(text: str) -> bool:
    """Detects whether a messaging instruction specifies draft-only intent."""
    if not text:
        return False
    patterns = [
        r"(?:prepare|draft|show|open)\s+.*(?:do\s+not\s+send|dont\s+send|without\s+sending|draft\s+only)",
        r"(?:do\s+not\s+send|dont\s+send|draft\s+only|do\s+not\s+send\s+anything|without\s+sending)",
        r"show\s+me\s+the\s+exact\s+recipient\s+and\s+message",
        r"(?:draft\s+it\s+only|only\s+draft|just\s+draft)",
    ]
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


class CortexOrchestrator:
    def __init__(
        self,
        automation: DeviceAutomation | None = None,
        memory: EncryptedMemoryStore | None = None,
        use_gemini: bool | None = None,
        task_store: TaskStore | None = None,
    ) -> None:
        self.automation = automation or DeviceAutomation()
        self.memory = memory or EncryptedMemoryStore(str(Path("work") / "cortex-memory.sqlite3"))
        self.task_store = task_store or TaskStore(str(self.memory.db_path))
        setattr(self.automation, "task_store", self.task_store)
        if hasattr(self.automation, "whatsapp") and hasattr(self.automation.whatsapp, "task_store"):
            self.automation.whatsapp.task_store = self.task_store
        self.tasks: dict[str, Task] = {}
        self.history: list[dict[str, Any]] = []
        self.pending_action: dict[str, Any] | None = None
        self.paused_tasks: list[dict[str, Any]] = []
        self.last_search_results: list[dict[str, Any]] = []
        self.last_search_query: str = ""
        self.last_selected_result: dict[str, Any] | None = None
        self.last_opened_url: str = ""
        self.last_note: dict[str, Any] | None = None

        self.policy_engine = PolicyEngine()
        self.policy = self.policy_engine
        self.registry = ToolRegistry(self.automation)
        self.tool_registry = self.registry
        self.tools = self.registry
        self.execution_engine = ExecutionEngine(self.registry, self.policy_engine)
        self.planner = AutonomousPlanner(self.registry)
        self.email_engine = ProfessionalEmailEngine()
        self.recipient_resolver = RecipientResolver(
            mail_automation=getattr(self.automation, "mail", getattr(self.automation, "_get_mail", lambda: None)()),
            memory_store=self.memory,
        )
        self.gemini_model = None
        self.gemini_cooldown_until: float = 0.0
        self._lock = threading.RLock()

        if use_gemini is False:
            self.use_gemini = False
            self.api_key = None
        else:
            # Load .env file if it exists in the project root
            project_root = Path(__file__).resolve().parents[2]
            env_path = project_root / ".env"
            if env_path.exists():
                try:
                    with open(env_path, encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                os.environ[k.strip()] = v.strip().strip('"').strip("'")
                except Exception as e:
                    print(f"[cortex] Failed to load .env: {e}", file=sys.stderr)

            self.api_key = os.getenv("GEMINI_API_KEY")
            if not self.api_key:
                zshrc = Path.home() / ".zshrc"
                if zshrc.exists():
                    try:
                        for line in zshrc.read_text(encoding="utf-8").splitlines():
                            if "GEMINI_API_KEY=" in line and not line.strip().startswith("#"):
                                self.api_key = line.split("GEMINI_API_KEY=", 1)[1].split()[0].strip().strip('"').strip("'")
                                os.environ["GEMINI_API_KEY"] = self.api_key
                                break
                    except Exception:
                        pass
            self.use_gemini = HAS_GENAI and bool(self.api_key)
            if self.use_gemini:
                genai.configure(api_key=self.api_key)

        self._load_history()
        self._rehydrate_tasks()

    def _rehydrate_tasks(self) -> None:
        """
        Rehydrate active/incomplete tasks on startup from TaskStore.
        Applies crash recovery rules:
        - Awaiting clarification -> rehydrated in AWAITING_CLARIFICATION
        - Awaiting approval -> rehydrated in AWAITING_APPROVAL (checks 15m expiry)
        - Executing / in-flight actions -> inspected for evidence before blind resumption
        - Paused model -> restored in PAUSED_MODEL_UNAVAILABLE
        """
        try:
            active_tasks = self.task_store.list_active_tasks()
            for t in active_tasks:
                initial_version = t.state_version
                self.tasks[t.id] = t
                # If interrupted during execution:
                if t.status in {TaskStatus.EXECUTING, TaskStatus.RUNNING}:
                    # Check attempts
                    attempts = self.task_store.get_action_attempts(t.id)
                    reconciled = False
                    for att in attempts:
                        if att["actionType"] in {"send_email", "send_mail"}:
                            recip = t.params.get("recipient") or t.params.get("to") or ""
                            subj = t.params.get("subject") or ""
                            mail_auto = getattr(self.automation, "mail", getattr(self.automation, "_get_mail", lambda: None)())
                            if mail_auto:
                                v = None
                                if hasattr(mail_auto, "verify_mail_sent"):
                                    v = mail_auto.verify_mail_sent(recip, subj)
                                elif hasattr(mail_auto, "verify_message_sent"):
                                    v = mail_auto.verify_message_sent(recip, subj)
                                elif hasattr(mail_auto, "provider") and hasattr(mail_auto.provider, "verify_message_sent"):
                                    v = mail_auto.provider.verify_message_sent(recip, subj)
                                if v and v.get("verified"):
                                    t.transition_to(TaskStatus.COMPLETED, reason="Rehydrated and verified email delivery in Sent mailbox", force_admin=True)
                                    reconciled = True
                                    break
                    if not reconciled:
                        # Cannot confirm external side-effect; must not blindly retry!
                        t.transition_to(TaskStatus.NEEDS_ATTENTION, reason="Interrupted during execution. Outcome uncertain; manual verification required.", force_admin=True)

                # If awaiting approval, check expiry
                elif t.status in {TaskStatus.WAITING_APPROVAL, TaskStatus.AWAITING_APPROVAL}:
                    try:
                        from datetime import datetime, timezone, timedelta
                        created = datetime.fromisoformat(t.created_at)
                        if datetime.now(timezone.utc) - created > timedelta(minutes=15):
                            t.transition_to(TaskStatus.NEEDS_ATTENTION, reason="Approval window expired during shutdown. Fresh approval required.", force_admin=True)
                    except Exception:
                        pass

                if t.state_version > initial_version:
                    self.task_store.save_task(t, expected_version=initial_version)

            # If an active task is waiting for user input, set pending_action
            for t in reversed(active_tasks):
                if t.status in {TaskStatus.WAITING_APPROVAL, TaskStatus.AWAITING_APPROVAL}:
                    self.pending_action = {
                        "type": "approval",
                        "command": t.command.value if hasattr(t.command, "value") else str(t.command),
                        "task_id": t.id,
                        "task": t.to_dict(),
                        "approval_hash": t.approval_hash or t.params.get("approval_hash"),
                    }
                    break
                elif t.status in {TaskStatus.WAITING_INPUT, TaskStatus.NEED_INFO, TaskStatus.AWAITING_CLARIFICATION}:
                    self.pending_action = {
                        "type": "clarification",
                        "task_id": t.id,
                        "task": t.to_dict(),
                        "clarification": t.params.get("clarification", "Please provide additional details."),
                    }
                    break
        except Exception as e:
            print(f"[cortex] Failed to rehydrate tasks from database: {e}", file=sys.stderr)

    def _load_history(self) -> None:
        try:
            row = self.memory.get("conversation_history")
            if row:
                self.history = row.get("messages", [])
        except Exception as e:
            print(f"[cortex] Failed to load conversation history: {e}", file=sys.stderr)

    def _save_history(self) -> None:
        try:
            self.memory.put("conversation_history", "history", {"messages": self.history})
        except Exception as e:
            print(f"[cortex] Failed to save conversation history: {e}", file=sys.stderr)

    def _create_gemini_model(self, system_instruction: str | None = None) -> Any:
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        candidates = [model_name, "gemini-3.5-flash", "gemini-flash-latest"]
        for name in candidates:
            try:
                if system_instruction:
                    return genai.GenerativeModel(name, system_instruction=system_instruction)
                return genai.GenerativeModel(name)
            except Exception:
                continue
        if system_instruction:
            return genai.GenerativeModel("gemini-3.5-flash", system_instruction=system_instruction)
        return genai.GenerativeModel("gemini-3.5-flash")

    def _is_gemini_available(self) -> bool:
        if not self.use_gemini:
            return False
        if time.time() < getattr(self, "gemini_cooldown_until", 0.0):
            return False
        return True

    def _handle_gemini_error(self, exc: Exception, context: str = "") -> None:
        err_str = str(exc).lower()
        if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str or "rate limit" in err_str:
            self.gemini_cooldown_until = time.time() + 180.0  # 3-minute cooldown
            print(f"[cortex] Gemini quota/rate limit reached in {context}. Activated 3m circuit breaker for instant fallbacks: {exc}", file=sys.stderr)
        else:
            print(f"[cortex] Gemini warning in {context}: {exc}", file=sys.stderr)

    def _analyze_intent(self, message: str, lang_code: str = "en") -> dict[str, Any]:
        if not self._is_gemini_available():
            return self._analyze_intent_fallback(message)

        try:
            # Build a language-aware system prompt
            lang_instr = language_instruction(lang_code)
            system = SYSTEM_PROMPT
            if lang_instr:
                system = SYSTEM_PROMPT + f"\n\nLanguage Directive:\n{lang_instr}"

            model = self._create_gemini_model(system_instruction=system)
            
            # Construct standard chat history context for Gemini
            chat_contents = []
            for h in self.history:
                chat_contents.append(h)
            
            current_message = f"User intent: {message}"
            chat_contents.append({"role": "user", "parts": [current_message]})

            response = model.generate_content(
                chat_contents,
                generation_config={"response_mime_type": "application/json"},
                request_options={"timeout": 20.0}
            )
            data = json.loads(response.text)

            risk_map = {
                "low": RiskLevel.LOW,
                "medium": RiskLevel.MEDIUM,
                "high": RiskLevel.HIGH,
                "blocked": RiskLevel.BLOCKED
            }

            try:
                command = TaskCommand(data.get("command", "unknown"))
            except ValueError:
                command = TaskCommand.UNKNOWN

            params = data.get("params", {})
            if command == TaskCommand.ASK_QUESTION and data.get("answer"):
                params["answer"] = data["answer"]

            return {
                "command": command,
                "params": params,
                "risk_level": risk_map.get(data.get("risk_level", "low"), RiskLevel.LOW),
                "requires_approval": bool(data.get("requires_approval", False)),
                "block_reason": data.get("block_reason"),
                "answer": data.get("answer")
            }
        except Exception as exc:
            self._handle_gemini_error(exc, context="intent analysis")
            return self._analyze_intent_fallback(message)

    def _analyze_intent_fallback(self, message: str) -> dict[str, Any]:
        command = command_from_intent(message)
        risk, approval, block_reason = classify_command(command, message)
        params = self._extract_params(command, message)
        return {
            "command": command,
            "params": params,
            "risk_level": risk,
            "requires_approval": approval,
            "block_reason": block_reason,
            "answer": None
        }

    def _format_approval_card(self, draft: Any, lang_code: str = "en", draft_saved: bool = True, save_error: str = "") -> str:
        recipient = getattr(draft, "recipient", "")
        subject = getattr(draft, "subject", "")
        body = getattr(draft, "body", "")
        sender_account = getattr(draft, "sender_account", "")
        attachments = getattr(draft, "attachments", [])
        cc = getattr(draft, "cc", [])
        bcc = getattr(draft, "bcc", [])

        if lang_code == "en":
            sender_str = f"From: {sender_account}\n" if sender_account else ""
            cc_str = f"CC: {', '.join(cc)}\n" if cc else ""
            bcc_str = f"BCC: {', '.join(bcc)}\n" if bcc else ""
            attachments_str = f"Attachments: {', '.join(attachments)}\n" if attachments else ""
            header = "Draft created and saved to your mailbox:\n" if draft_saved else f"Draft prepared (Note: draft could not be saved to your mailbox - {save_error}):\n"
            return (
                f"{header}"
                f"To: {recipient}\n"
                f"{sender_str}"
                f"{cc_str}"
                f"{bcc_str}"
                f"Subject: {subject}\n"
                f"{attachments_str}"
                f"Body:\n{body}\n\n"
                f"Options:\n"
                f"• Approve: Reply 'yes' or 'send it' to send\n"
                f"• Edit: Tell me what to change (e.g., 'make it more formal', 'add deadline before Friday', 'don't mention reason')\n"
                f"• Cancel: Reply 'cancel' to discard this draft\n\n"
                f"I need your explicit approval before sending. Should I send it?"
            )
        else:
            return localize(
                "draft_prepared_approval",
                lang_code,
                recipient=recipient,
                subject=subject,
                body=body,
            )

    def _is_unrelated_turn(self, message: str, step: str = "") -> bool:
        """
        Determines if an incoming message during a pending action is an unrelated
        conversational turn (e.g. greeting, general question in any language, or
        separate tool command) rather than an answer to the pending clarification/body.
        """
        text = message.strip()
        msg_lower = text.lower()

        # Priority guard: If we are actively waiting for an email body or draft edits,
        # user input must NOT be treated as unrelated unless it is an explicit desktop/system command.
        if step in ("waiting_for_body", "waiting_for_edit"):
            cmd = command_from_intent(text)
            if cmd not in (TaskCommand.UNKNOWN, TaskCommand.ASK_QUESTION, TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                return True
            return False

        # If it contains an email address, it is definitely email-related
        if re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text):
            return False

        # Greetings in English and transliterated Indic
        greetings = (
            "hello", "hi", "hey", "good morning", "good afternoon", "good evening",
            "how are you", "who are you", "what can you do", "help",
            "namaskara", "namaste", "vanakkam", "namaskaram", "kaisa hai", "kaise ho",
            "hegidira", "hegiddira", "hegidiya", "chennagidira", "ela unnaru", "eppadi irukinga"
        )
        if any(msg_lower == g or msg_lower.startswith(g + " ") or msg_lower.startswith(g + ",") for g in greetings):
            return True

        # Native Indic greetings and conversational questions (Kannada, Hindi, Tamil, Telugu)
        indic_conversational = (
            # Kannada greetings & question particles
            "ನಮಸ್ಕಾರ", "ಹಲೋ", "ಹೇಗಿದ್ದೀರಿ", "ಹೇಗಿದೀರ", "ಹೇಗಿದ್ದೀರ", "ಚೆನ್ನಾಗಿದ್ದೀರಾ", "ಯಾರು", "ಏನು", "ಹೇಗೆ",
            # Hindi greetings & question particles
            "नमस्ते", "नमस्कार", "हेलो", "कैसे हो", "कैसा है", "क्या हाल", "कौन है", "क्या है",
            # Tamil greetings & questions
            "வணக்கம்", "எப்படி இருக்கிறீர்கள்", "யார்", "என்ன",
            # Telugu greetings & questions
            "నమస్కారం", "ఎలా ఉన్నారు", "ఎవరు", "ఏమిటి"
        )
        if any(p in text for p in indic_conversational):
            return True

        # Romanized Indic query patterns (e.g. "hindi me batao...", "kannada dalli heli...")
        if re.search(r"\b(hindi|kannada|tamil|telugu)\s+(?:me|dalli|la|lo|bhasha|mein)\b", msg_lower):
            return True
        if any(word in msg_lower for word in ("batao", "btao", "bolo", "kaho", "heli", "helri", "sollunga", "cheppandi")):
            return True

        # Explicit commands from intent (open app, calculate, screenshot, etc.)
        cmd = command_from_intent(text)
        if cmd not in (TaskCommand.UNKNOWN, TaskCommand.ASK_QUESTION, TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
            return True

        # Check if message is referencing an earlier research summary, article, or file inspection
        if any(w in msg_lower for w in ("summary", "research", "article", "second result", "first result", "third result", "visible filenames")):
            if any(w in msg_lower for w in ("shorter", "shorten", "explain", "detail", "compare", "open", "show")):
                return True

        # General questions (for recipient clarification or disambiguation, questions are unrelated)
        if step in ("waiting_for_recipient_clarification", "waiting_for_recipient_disambiguation", "waiting_for_recipient", "confirm_send", "draft_only_review"):
            question_starters = (
                "what is", "what's", "what are", "who is", "who's", "who are",
                "how does", "how do", "how is", "how to", "why is", "why do", "why does",
                "where is", "when is", "tell me", "explain", "can you explain",
                "search for", "find out", "summarize our", "recap our"
            )
            if any(msg_lower.startswith(qs) for qs in question_starters) or (msg_lower.endswith("?") and not any(k in msg_lower for k in ("email", "mail", "address", "recipient"))):
                return True

        return False

    def _is_explicit_cancellation(self, message: str, in_pending: bool = False) -> bool:
        text = message.strip()
        msg_lower = text.lower().rstrip(".!")

        # Do not match general educational/informational questions about cancellation
        if msg_lower.startswith(("how to cancel", "how do i cancel", "how can i cancel", "why cancel", "what is cancel")):
            return False
        if "?" in text and not msg_lower.startswith(("cancel", "stop", "abort", "discard", "ರದ್ದು", "ಬೇಡ", "रद्द", "रोक")):
            return False

        # Creation/preparation of a new message/draft/app action is never a cancellation request
        if re.match(r"^(?:draft\b|compose\b|write\b|prepare\b|open\s+(?:whatsapp|mail|safari|notes|finder)|show\s+(?:documents|downloads|desktop|finder))", msg_lower):
            return False

        exact_cancels = {
            "cancel", "cancel it", "cancel that", "cancel this", "cancel draft", "cancel the draft",
            "cancel email", "cancel the email", "cancel task", "please cancel", "cancel please",
            "stop", "stop it", "abort", "abort it", "discard", "discard it", "discard draft",
            "nevermind", "never mind", "forget it", "close draft", "reject", "don't send", "dont send",
            "do not send", "do not send it", "do not send this", "do not send that",
            "don't send it", "dont send it", "don't send this", "dont send this",
            "never send", "never send it", "please don't send", "please do not send",
            "no, cancel", "no, cancel it", "no cancel", "no cancel it",
            # Kannada
            "ರದ್ದು", "ರದ್ದುಮಾಡು", "ರದ್ದು ಮಾಡು", "ಬೇಡ", "ಬೇಡವೇ ಬೇಡ", "ನಿಲ್ಲಿಸು", "ಕ್ಯಾನ್ಸಲ್",
            "ಕಳುಹಿಸಬೇಡ", "ಕಳಿಸಬೇಡ", "ಇದನ್ನು ಕಳುಹಿಸಬೇಡ", "ಇದನ್ನು ಕಳಿಸಬೇಡ", "ಇಮೇಲ್ ಕಳುಹಿಸಬೇಡ",
            # Hindi
            "रद्द", "रद्द करो", "रद्द करें", "रद्द कर दो", "कैंसल", "रोक दो", "मत भेजो", "बंद करो",
            "इसे मत भेजो", "यह मत भेजो", "ईमेल मत भेजो", "मत भेजना", "नहीं भेजो", "नहीं भेजना",
            # Tamil
            "வேண்டாம்", "ரத்து", "ரத்து செய்", "அனுப்பாதே", "அனுப்ப வேண்டாம்", "இதனை அனுப்பாதே",
            # Telugu
            "వద్దు", "రద్దు", "రద్దు చేయి", "పంపవద్దు", "పంపకండి", "దీనిని పంపవద్దు"
        }
        if msg_lower in exact_cancels:
            return True

        if in_pending and msg_lower in ("no", "n", "nope", "nahi", "nahi bhejna", "नहीं"):
            return True

        cancel_patterns = [
            r"^(?:no[,\s]+)?(?:please\s+)?(?:cancel|abort|discard|stop)(?:\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:draft|email|mail|task|action|it|that|everything))?.*$",
            r"^(?:no[,\s]+)?(?:please\s+)?(?:don'?t|do\s+not|never)\s+send(?:\s+(?:the\s+|this\s+)?(?:draft|email|mail|it|that|anything))?.*$",
            r"\b(?:cancel|abort|discard)\s+(?:the\s+|this\s+|my\s+)?(?:draft|email|mail|task|action)\b",
            r"^(?:please\s+)?(?:do\s+not|don'?t|never)\s+send\s+(?:anything|it|the\s+draft|the\s+email|this)\b",
            r"^(?:ರದ್ದು\s*(?:ಮಾಡು|ಮಾಡಿ)?|ಬೇಡ)$",
            r"(?:ಇದನ್ನು\s*|ಇಮೇಲ್\s*)?(?:ಕಳುಹಿಸಬೇಡ|ಕಳಿಸಬೇಡ)$",
            r"^(?:रद्द\s*(?:करो|करें|कर\s*दो)?|मत\s*भेजो)$",
            r"(?:इसे\s*|यह\s*|ईमेल\s*)?(?:मत\s*(?:भेजो|भेजें|भेजना)|नहीं\s*(?:भेजो|भेजें|भेजना))",
            r"(?:இதனை\s*|மின்னஞ்சல்\s*)?(?:அனுப்பாதே|அனுப்ப\s*வேண்டாம்)",
            r"(?:దీనిని\s*|ఇమెయిల్\s*)?(?:పంపవద్దు|పంపకండి)",
        ]
        for pat in cancel_patterns:
            if re.search(pat, msg_lower):
                return True

        return False

    def _handle_cancellation(self, message: str, raw_lang_code: str, detected_lang: LanguageCode) -> dict[str, Any]:
        cancelled_task_dict = None
        target_task_id = None
        target_task = None

        if self.pending_action:
            pending = self.pending_action
            target_task_id = pending.get("task_id")
            target_task = pending.get("task")
            self.pending_action = None

        if not target_task_id and not target_task:
            # Check if there is an active waiting task awaiting approval
            waiting_tasks = [t for t in self.tasks.values() if t.status == TaskStatus.WAITING_APPROVAL]
            if waiting_tasks:
                target_task = waiting_tasks[-1]
                target_task_id = target_task.id

        if target_task_id and target_task_id in self.tasks:
            cancelled_task_dict = self.cancel(target_task_id)
        elif target_task:
            target_task.status = TaskStatus.CANCELED
            target_task.result = "User interrupted the task."
            target_task.add_event("canceled", "User cancelled pending task.")
            if target_task.params and "approval_hash" in target_task.params:
                target_task.params["approval_hash"] = None
            if target_task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                try:
                    self.automation.mail.delete_draft(
                        recipient=target_task.params.get("recipient", ""),
                        subject=target_task.params.get("subject", ""),
                    )
                except Exception:
                    pass
            self.tasks[target_task.id] = target_task
            self._persist_task(target_task)
            cancelled_task_dict = target_task.to_dict()
        else:
            dummy_task = Task(message, TaskCommand.UNKNOWN, RiskLevel.LOW, False, language=detected_lang)
            dummy_task.status = TaskStatus.CANCELED
            dummy_task.result = "Task canceled."
            dummy_task.add_event("canceled", "User cancelled.")
            self.tasks[dummy_task.id] = dummy_task
            cancelled_task_dict = dummy_task.to_dict()

        return {
            "task": cancelled_task_dict,
            "message": localize("action_cancelled", raw_lang_code),
        }

    def chat(self, message: str, source: str = "text", preferred_language: Optional[str] = None) -> dict[str, Any]:
        # Handle history clearing
        if message.lower().strip() in ("clear history", "reset conversation", "clear memory"):
            self.history = []
            self._save_history()
            return {
                "message": "Memory cleared.",
                "task": Task(message, TaskCommand.UNKNOWN, RiskLevel.LOW, False).to_dict()
            }

        # ── Phase 3: Language resolution with explicit precedence (ML-01, ML-05) ──
        raw_lang_code, is_explicit = resolve_language(
            message,
            preferred_language=preferred_language,
            gemini_model=self.gemini_model if self.use_gemini else None,
        )
        detected_lang = LanguageCode.from_string(raw_lang_code)

        # ── Unsupported Language Safety Check (ML-09) ──
        unsupported = is_unsupported_language_request(message)
        if unsupported:
            return {
                "message": (
                    f"Cortex currently supports English, Kannada (ಕನ್ನಡ), Hindi (हिन्दी), "
                    f"Tamil (தமிழ்), and Telugu (తెలుగు). Support for {unsupported} is not currently configured."
                ),
                "task": Task(message, TaskCommand.UNKNOWN, RiskLevel.LOW, False, language=detected_lang).to_dict()
            }

        # ── Priority 0A: Task resumption ──
        if re.match(r"^(?:resume|continue)(?:\s+(?:the\s+|my\s+)?(?:previous\s+)?(?:task|draft|email|work))?[.,;!]?$", message.strip(), re.IGNORECASE):
            if self.paused_tasks:
                self.pending_action = self.paused_tasks.pop()
                p_task = self.pending_action.get("task")
                if p_task:
                    p_task.status = TaskStatus.WAITING_APPROVAL
                p_recipient = self.pending_action.get("recipient", "recipient")
                return {
                    "message": f"Resumed your previous task for {p_recipient}. Ready for your review or instructions.",
                    "task": p_task.to_dict() if p_task else Task(message, TaskCommand.UNKNOWN, RiskLevel.LOW, False).to_dict()
                }

        # ── Priority 0B: Task interruption and task switching (e.g. "Stop. Help me with Python instead.") ──
        switch_m = re.match(r"^(?:stop|wait|pause|cancel|hold on)[.,;!]\s*(.+)$", message.strip(), re.IGNORECASE)
        if switch_m:
            next_cmd = switch_m.group(1).strip()
            next_cmd = re.sub(r"\s+instead[.,;!]?$", "", next_cmd, flags=re.IGNORECASE).strip()
            if self.pending_action:
                paused = self.pending_action
                self.paused_tasks.append(paused)
                t_obj = paused.get("task")
                if t_obj and hasattr(t_obj, "status"):
                    t_obj.status = TaskStatus.PAUSED
                    t_obj.add_event("paused", "Task paused due to user interruption to switch tasks.")
                self.pending_action = None
            sub_res = self.chat(next_cmd, source=source, preferred_language=preferred_language)
            sub_res["message"] = f"Paused the previous task. {sub_res['message']}"
            return sub_res

        # ── Priority 0: Deterministic Cancellation Handling Before Fallbacks ──
        if self._is_explicit_cancellation(message, in_pending=bool(self.pending_action)):
            return self._handle_cancellation(message, raw_lang_code, detected_lang)

        # ── Progressive multi-turn completion for missing info / partial commands ──
        if self.pending_action:
            pending = self.pending_action
            step = pending.get("step", "")
            p_lang = pending.get("lang") or raw_lang_code
            msg_lower = message.strip().lower().rstrip(".!")

            is_new_email = (
                bool(re.match(r"^(?:send|draft|compose|write)\s+(?:an?\s+)?(?:email|mail)\s+to\b", msg_lower))
                or (
                    bool(re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", msg_lower))
                    and any(w in msg_lower for w in ("email", "mail", "ಇಮೇಲ್", "ಮೇಲ್", "ईमेल", "मின்னஞ்சல்", "ఇమెయిల్"))
                    and not any(w in msg_lower for w in ("change recipient to", "send to instead", "switch to"))
                )
            )

            if is_new_email:
                # If user starts a brand new email to another recipient, discard pending draft
                self.pending_action = None

            elif self._is_unrelated_turn(message, step=step):
                # The user is engaging in an unrelated conversational turn or command.
                # Allow it to fall through to normal execution while preserving self.pending_action.
                pass

            elif pending.get("type") == "email_draft" and step == "confirm_send":
                is_show_draft = any(kw in msg_lower for kw in ("show me", "show draft", "view draft", "complete draft", "see draft", "display draft", "read draft"))
                has_negation = (
                    self._is_explicit_cancellation(message, in_pending=True)
                    or bool(re.search(r"\b(?:cancel|abort|discard|stop|reject)\b", msg_lower))
                    or (bool(re.search(r"\b(?:don'?t|do\s+not|never)\s+send\b", msg_lower)) and not any(w in msg_lower for w in ("don't mention", "dont mention", "do not mention")))
                    or msg_lower in ("no", "n", "nope", "nahi", "nahi bhejna", "नहीं")
                    or any(kw in msg_lower for kw in ("ಬೇಡ", "ಕಳಿಸಬೇಡ", "ಕಳುಹಿಸಬೇಡ", "मत भेजो", "नहीं भेजना", "வேண்டாம்", "அனுப்பாதே", "వద్దు", "పంపవద్దు", "పంపకండి"))
                )
                if has_negation:
                    return self._handle_cancellation(message, raw_lang_code, detected_lang)

                edit_patterns = (
                    r"\b(?:shorter|concise|formal|casual|brief|subject|reason)\b",
                    r"\b(?:before|friday|monday|tuesday|wednesday|thursday|saturday|sunday)\b",
                    r"\b(?:deadline|urgent|professor|prof|dear|address|account)\b",
                    r"\b(?:college\s+email|work\s+email|add|remove|change|include|mention)\b",
                    r"\b(?:make\s+it|update|rewrite|replace|warm\s+regards|sincerely|regards)\b",
                    r"\b(?:kannada|hindi|tamil|telugu|english|translate|write\s+it\s+in|write\s+in)\b",
                    r"\b(?:keep\s+the|ಕನ್ನಡ|ಕನ್ನಡದಲ್ಲಿ|हिंदी|हिंदी\s+में|தமிழ்|தமிழில்|తెలుగు|తెలుగులో)\b",
                    r"\bdr\.?\s+[a-z]",
                )
                is_edit = any(re.search(pat, msg_lower) for pat in edit_patterns) or (
                    "don't mention" in msg_lower or "dont mention" in msg_lower or "omit the reason" in msg_lower
                )

                is_confirm = (
                    not is_edit
                    and not is_show_draft
                    and not has_negation
                    and (
                        bool(re.search(r"\b(yes|send\s+it|approve|go\s+ahead|send|sure|ok|okay|please\s+send|y|yep|agree|confirmed)\b", msg_lower))
                        or any(kw in msg_lower for kw in ("ಕಳುಹಿಸು", "ಕಳಿಸು", "ಸರಿ", "ಹೌದು", "ಆಯ್ತು", "भेजो", "भेजें", "हाँ", "हां", "ठीक है", "அனுப்பு", "சரி", "పంపు", "సరే"))
                    )
                )

                if is_show_draft:
                    task_id = pending["task_id"]
                    task = self.tasks[task_id]
                    draft = pending.get("draft")
                    if not draft:
                        draft = EmailDraft(recipient=pending["recipient"], subject=pending["subject"], body=pending.get("formatted_body") or pending["body"], sender_account=pending.get("sender_account", ""))
                    response = self._format_approval_card(draft, lang_code=p_lang)
                    return {"task": task.to_dict(), "message": response}
                elif is_confirm:
                    task_id = pending["task_id"]
                    recipient = pending["recipient"]
                    task = self.tasks[task_id]
                    if task.command == TaskCommand.DRAFT_MAIL or task.status == TaskStatus.COMPLETED:
                        task.command = TaskCommand.SEND_MAIL
                        task.status = TaskStatus.WAITING_APPROVAL
                        task.params["approval_hash"] = (
                            getattr(pending.get("draft"), "approval_hash", None)
                            or task.params.get("approval_hash")
                        )
                    self.pending_action = None
                    approved_task = self.approve(task_id, approved=True)
                    if approved_task.get("status") in (TaskStatus.FAILED.value, TaskStatus.FAILED, "failed") or approved_task.get("error"):
                        return {
                            "task": approved_task,
                            "message": approved_task.get("error") or "Failed to send email.",
                        }
                    return {
                        "task": approved_task,
                        "message": localize("email_sent", p_lang, recipient=recipient),
                    }
                cmd_intent = command_from_intent(message)
                is_explicit_cmd = cmd_intent not in (TaskCommand.UNKNOWN, TaskCommand.ASK_QUESTION, TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL)
                is_summary_ref = bool(re.search(r"\b(?:make\s+(?:the\s+)?summary\s+shorter|shorten\s+(?:the\s+)?summary|open\s+(?:that|the)\s+article|explain\s+(?:the\s+)?second\s+point)\b", msg_lower))

                if is_explicit_cmd or is_summary_ref:
                    # Separate explicit command or research summary follow-up; do not swallow as an email draft edit
                    pass
                elif is_edit or (" " in msg_lower and not any(kw in msg_lower for kw in ("open ", "close ", "screenshot", "calculate", "find ", "search ", "observe ", "navigate "))):
                    task_id = pending["task_id"]
                    task = self.tasks[task_id]
                    draft = pending.get("draft")
                    if not draft:
                        draft = EmailDraft(recipient=pending["recipient"], subject=pending["subject"], body=pending.get("formatted_body") or pending["body"], sender_account=pending.get("sender_account", ""))
                    old_subject = draft.subject
                    old_recipient = draft.recipient
                    updated_draft = self.email_engine.update_draft_with_edit(draft, message)
                    if hasattr(updated_draft, "language") and updated_draft.language:
                        p_lang = updated_draft.language
                        task.language = LanguageCode.from_string(p_lang)
                        pending["lang"] = p_lang
                    pending["recipient"] = updated_draft.recipient
                    pending["subject"] = updated_draft.subject
                    pending["body"] = updated_draft.body
                    pending["draft"] = updated_draft
                    pending["sender_account"] = updated_draft.sender_account
                    pending["attachments"] = updated_draft.attachments
                    pending["cc"] = updated_draft.cc
                    pending["bcc"] = updated_draft.bcc
                    task.params["recipient"] = updated_draft.recipient
                    task.params["recipient_email"] = updated_draft.recipient
                    task.params["subject"] = updated_draft.subject
                    task.params["body"] = updated_draft.body
                    task.params["formatted_body"] = updated_draft.body
                    task.params["sender_account"] = updated_draft.sender_account
                    task.params["account"] = updated_draft.sender_account
                    task.params["attachments"] = updated_draft.attachments
                    task.params["cc"] = updated_draft.cc
                    task.params["bcc"] = updated_draft.bcc
                    task.params["approval_hash"] = updated_draft.approval_hash
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_edited", f"Draft updated: {message}")

                    if old_subject and old_subject != updated_draft.subject:
                        try:
                            self.automation.mail.delete_draft(old_recipient, old_subject)
                        except Exception:
                            pass

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {
                            "recipient": updated_draft.recipient,
                            "subject": updated_draft.subject,
                            "body": updated_draft.body,
                            "account": updated_draft.sender_account,
                            "attachments": updated_draft.attachments,
                            "cc": updated_draft.cc,
                            "bcc": updated_draft.bcc,
                        })
                        if hasattr(res, "ok") and not res.ok:
                            draft_saved = False
                            save_error = res.message
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    response = self._format_approval_card(updated_draft, lang_code=p_lang, draft_saved=draft_saved, save_error=save_error)
                    return {"task": task.to_dict(), "message": response}
                else:
                    self.pending_action = None

            elif pending.get("type") == "email_draft" and pending.get("step") == "waiting_for_recipient_clarification":
                user_answer = message.strip()
                command = pending.get("command", TaskCommand.SEND_MAIL)
                body = pending.get("body", "").strip()
                raw_recipient = pending.get("raw_recipient", "")
                orig_intent = pending.get("original_intent", "")
                task = pending.get("task")

                resolution = self.recipient_resolver.resolve(
                    query=user_answer,
                    full_message=f"{orig_intent} {user_answer}",
                    preferred_institution=user_answer,
                )
                if resolution.status != "resolved":
                    resolution = self.recipient_resolver.resolve(
                        query=raw_recipient,
                        full_message=f"{orig_intent} {user_answer}",
                        preferred_institution=user_answer,
                    )

                if resolution.status == "resolved" and resolution.recipient:
                    resolved = resolution.recipient
                    target_name = raw_recipient if raw_recipient and not re.search(r"@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_recipient) else resolved.name
                    rec_display = f"{target_name} <{resolved.email}>" if target_name and target_name.lower() != resolved.email.lower() else resolved.email
                    if not body:
                        self.pending_action = {
                            "type": "email_draft",
                            "step": "waiting_for_body",
                            "command": command,
                            "recipient": rec_display,
                            "subject": pending.get("subject", ""),
                            "task": task,
                            "lang": p_lang,
                        }
                        return {"task": task.to_dict() if task else {}, "message": localize("need_body", p_lang, recipient=rec_display)}

                    draft = self.email_engine.compose_email(
                        raw_intent=orig_intent or f"send email to {rec_display} saying {body}",
                        recipient_raw=rec_display,
                        content=body,
                        subject_override=pending.get("subject", ""),
                        use_gemini=self.use_gemini,
                        gemini_model=self.gemini_model,
                    )
                    draft = self.email_engine.run_quality_control(draft, known_facts=[body])
                    draft.approval_hash = draft.compute_hash()

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body, "account": draft.sender_account})
                        if hasattr(res, "ok") and not res.ok:
                            draft_saved = False
                            save_error = res.message
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    if not task:
                        task = Task(
                            intent=orig_intent or f"send email to {rec_display}",
                            command=command,
                            risk_level=RiskLevel.HIGH if command == TaskCommand.SEND_MAIL else RiskLevel.LOW,
                            requires_approval=True if command == TaskCommand.SEND_MAIL else False,
                            params={"recipient": draft.recipient, "recipient_email": resolved.email, "subject": draft.subject, "body": body, "formatted_body": draft.body, "sender_account": draft.sender_account, "approval_hash": draft.approval_hash, "attachments": draft.attachments},
                            language=detected_lang,
                        )
                    else:
                        task.params.update({
                            "recipient": draft.recipient,
                            "recipient_email": resolved.email,
                            "subject": draft.subject,
                            "body": body,
                            "formatted_body": draft.body,
                            "sender_account": draft.sender_account,
                            "approval_hash": draft.approval_hash,
                            "attachments": draft.attachments,
                        })
                    task.context = TaskContext(
                        recipient=draft.recipient,
                        recipient_role=draft.recipient_role,
                        purpose=draft.subject,
                        requested_tone=draft.tone,
                        language=detected_lang,
                    )
                    task.steps = self._steps_for(command, task.requires_approval)
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_prepared", f"Draft prepared for {draft.recipient} — Subject: {draft.subject}")
                    self.tasks[task.id] = task

                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": draft.recipient,
                        "subject": draft.subject,
                        "body": body,
                        "draft": draft,
                        "lang": p_lang,
                    }

                    response = self._format_approval_card(draft, lang_code=p_lang, draft_saved=draft_saved, save_error=save_error)
                    return {"task": task.to_dict(), "message": response}

                elif resolution.status == "multiple_candidates":
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_recipient_disambiguation",
                        "command": command,
                        "candidates": resolution.candidates,
                        "raw_recipient": raw_recipient,
                        "body": body,
                        "subject": pending.get("subject", ""),
                        "original_intent": orig_intent,
                        "task": task,
                        "lang": p_lang,
                    }
                    return {"task": task.to_dict() if task else {}, "message": resolution.clarification_prompt}
                else:
                    return {"task": task.to_dict() if task else {}, "message": resolution.clarification_prompt or "I still could not identify the email address. Could you provide the exact email address?"}

            elif pending.get("type") == "email_draft" and pending.get("step") == "waiting_for_recipient_disambiguation":
                user_answer = message.strip()
                candidates = pending.get("candidates", [])
                command = pending.get("command", TaskCommand.SEND_MAIL)
                body = pending.get("body", "").strip()
                orig_intent = pending.get("original_intent", "")
                task = pending.get("task")

                chosen = None
                if user_answer.isdigit():
                    idx = int(user_answer) - 1
                    if 0 <= idx < len(candidates):
                        chosen = candidates[idx]
                if not chosen:
                    ans_lower = user_answer.lower()
                    for cand in candidates:
                        if ans_lower in cand.name.lower() or ans_lower in cand.email.lower() or (cand.institution and ans_lower in cand.institution.lower()):
                            chosen = cand
                            break

                if chosen:
                    rec_display = f"{chosen.name} <{chosen.email}>" if chosen.name and chosen.name != chosen.email else chosen.email
                    if not body:
                        self.pending_action = {
                            "type": "email_draft",
                            "step": "waiting_for_body",
                            "command": command,
                            "recipient": rec_display,
                            "subject": pending.get("subject", ""),
                            "task": task,
                            "lang": p_lang,
                        }
                        return {"task": task.to_dict() if task else {}, "message": localize("need_body", p_lang, recipient=rec_display)}

                    draft = self.email_engine.compose_email(
                        raw_intent=orig_intent or f"send email to {rec_display} saying {body}",
                        recipient_raw=rec_display,
                        content=body,
                        subject_override=pending.get("subject", ""),
                        use_gemini=self.use_gemini,
                        gemini_model=self.gemini_model,
                    )
                    draft = self.email_engine.run_quality_control(draft, known_facts=[body])
                    draft.approval_hash = draft.compute_hash()

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body, "account": draft.sender_account})
                        if hasattr(res, "ok") and not res.ok:
                            draft_saved = False
                            save_error = res.message
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    if not task:
                        task = Task(
                            intent=orig_intent or f"send email to {rec_display}",
                            command=command,
                            risk_level=RiskLevel.HIGH if command == TaskCommand.SEND_MAIL else RiskLevel.LOW,
                            requires_approval=True if command == TaskCommand.SEND_MAIL else False,
                            params={"recipient": draft.recipient, "recipient_email": chosen.email, "subject": draft.subject, "body": body, "formatted_body": draft.body, "sender_account": draft.sender_account, "approval_hash": draft.approval_hash, "attachments": draft.attachments},
                            language=detected_lang,
                        )
                    else:
                        task.params.update({
                            "recipient": draft.recipient,
                            "recipient_email": chosen.email,
                            "subject": draft.subject,
                            "body": body,
                            "formatted_body": draft.body,
                            "sender_account": draft.sender_account,
                            "approval_hash": draft.approval_hash,
                            "attachments": draft.attachments,
                        })
                    task.context = TaskContext(
                        recipient=draft.recipient,
                        recipient_role=draft.recipient_role,
                        purpose=draft.subject,
                        requested_tone=draft.tone,
                        language=detected_lang,
                    )
                    task.steps = self._steps_for(command, task.requires_approval)
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_prepared", f"Draft prepared for {draft.recipient} — Subject: {draft.subject}")
                    self.tasks[task.id] = task

                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": draft.recipient,
                        "subject": draft.subject,
                        "body": body,
                        "draft": draft,
                        "lang": p_lang,
                    }

                    response = self._format_approval_card(draft, lang_code=p_lang, draft_saved=draft_saved, save_error=save_error)
                    return {"task": task.to_dict(), "message": response}
                else:
                    return {
                        "task": task.to_dict() if task else {},
                        "message": f"I couldn't match '{user_answer}' to one of the options. Please select by number (e.g., 1, 2) or enter the email address.",
                    }

            elif pending.get("type") == "email_draft" and pending.get("step") == "waiting_for_recipient":
                raw_rec = re.sub(r"^(?:to|recipient is|recipient:)\s+", "", message.strip(), flags=re.IGNORECASE).strip().rstrip(".! ")
                command = pending.get("command", TaskCommand.SEND_MAIL)
                body = pending.get("body", "").strip()
                task = pending.get("task")

                res = self.recipient_resolver.resolve(raw_rec, full_message=raw_rec)
                if res.status == "resolved" and res.recipient:
                    rec_display = f"{res.recipient.name} <{res.recipient.email}>" if res.recipient.name and res.recipient.name != res.recipient.email else res.recipient.email
                else:
                    rec_display = raw_rec

                if not body:
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_body",
                        "command": command,
                        "recipient": rec_display,
                        "subject": "",
                        "task": task,
                        "lang": p_lang,
                    }
                    response = localize("need_body", p_lang, recipient=rec_display)
                    return {"task": task.to_dict() if task else {}, "message": response}
                else:
                    clean_body = body[0].upper() + body[1:] if body else body
                    draft = self.email_engine.compose_email(
                        raw_intent=f"send email to {rec_display} saying {clean_body}",
                        recipient_raw=rec_display,
                        content=clean_body,
                        subject_override="",
                        use_gemini=self.use_gemini,
                        gemini_model=self.gemini_model,
                    )
                    draft = self.email_engine.run_quality_control(draft, known_facts=[clean_body])
                    draft.approval_hash = draft.compute_hash()

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body, "account": draft.sender_account})
                        if hasattr(res, "ok") and not res.ok:
                            draft_saved = False
                            save_error = res.message
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    task = Task(
                        intent=f"send email to {rec_display} saying {clean_body}",
                        command=command,
                        risk_level=RiskLevel.HIGH if command == TaskCommand.SEND_MAIL else RiskLevel.LOW,
                        requires_approval=True if command == TaskCommand.SEND_MAIL else False,
                        params={"recipient": draft.recipient, "subject": draft.subject, "body": clean_body, "formatted_body": draft.body, "sender_account": draft.sender_account, "approval_hash": draft.approval_hash, "attachments": draft.attachments},
                        language=detected_lang,
                    )
                    task.status = TaskStatus.WAITING_APPROVAL if task.requires_approval else TaskStatus.RUNNING
                    self.tasks[task.id] = task
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": draft.recipient,
                        "subject": draft.subject,
                        "body": clean_body,
                        "draft": draft,
                        "lang": p_lang,
                    }
                    response = self._format_approval_card(draft, lang_code=p_lang, draft_saved=draft_saved, save_error=save_error)
                    return {"task": task.to_dict(), "message": response}

            elif pending.get("type") == "email_draft" and pending.get("step") == "waiting_for_body":
                conv_body, meta = convert_instruction_to_recipient_content(message.strip())
                clean_body = conv_body if conv_body else re.sub(
                    r"^(?:tell\s+(?:him|her|them|it)\s+|saying\s+|that\s+says\s+|that\s+|say\s+)",
                    "",
                    message.strip(),
                    flags=re.IGNORECASE,
                ).strip()
                extracted_tone = meta.get("extracted_tone")
                if clean_body:
                    if is_ambiguous_email_intent(clean_body):
                        task = pending.get("task")
                        if task:
                            task.status = TaskStatus.NEED_INFO
                            task.add_event("need_info", f"Awaiting clarification for ambiguous body: '{clean_body}'")
                            self.tasks[task.id] = task
                            self._persist_task(task)
                        clarif_prompt = f"Could you please clarify what specific message or details you would like to include regarding '{clean_body}'?"
                        return {"task": task.to_dict() if task else {}, "message": clarif_prompt}

                    clean_body = clean_body[0].upper() + clean_body[1:] if clean_body else clean_body
                    recipient = pending["recipient"]
                    rec_display = pending.get("recipient_display") or recipient
                    command = pending.get("command", TaskCommand.SEND_MAIL)
                    existing_subj = pending.get("subject", "").strip()

                    draft = self.email_engine.compose_email(
                        raw_intent=f"send email to {rec_display} saying {clean_body}",
                        recipient_raw=rec_display,
                        content=clean_body,
                        subject_override=existing_subj,
                        tone_override=extracted_tone,
                        use_gemini=self.use_gemini,
                        gemini_model=self.gemini_model,
                    )
                    draft = self.email_engine.run_quality_control(draft, known_facts=[clean_body])
                    draft.approval_hash = draft.compute_hash()
                    subj = draft.subject

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {"recipient": draft.recipient, "subject": draft.subject, "body": draft.body, "account": draft.sender_account})
                        if isinstance(res, dict) and res.get("status") in ("failed", "error"):
                            draft_saved = False
                            save_error = res.get("error") or res.get("message") or "Provider draft creation failed"
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    task = Task(
                        intent=f"send email to {recipient} saying {clean_body}",
                        command=command,
                        risk_level=RiskLevel.HIGH if command == TaskCommand.SEND_MAIL else RiskLevel.LOW,
                        requires_approval=True if command == TaskCommand.SEND_MAIL else False,
                        params={"recipient": recipient, "recipient_email": draft.recipient, "subject": subj, "body": clean_body, "formatted_body": draft.body, "sender_account": draft.sender_account, "approval_hash": draft.approval_hash, "attachments": draft.attachments},
                        language=detected_lang,
                    )
                    task.context = TaskContext(
                        recipient=recipient,
                        recipient_role=draft.recipient_role,
                        purpose=subj,
                        requested_tone=draft.tone,
                        language=detected_lang,
                    )
                    task.steps = self._steps_for(command, task.requires_approval)
                    task.status = TaskStatus.WAITING_APPROVAL if task.requires_approval else TaskStatus.RUNNING
                    task.add_event("draft_ready", f"Draft prepared — Subject: {subj}")
                    self.tasks[task.id] = task

                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": recipient,
                        "recipient_email": draft.recipient,
                        "subject": subj,
                        "body": clean_body,
                        "draft": draft,
                        "lang": raw_lang_code,
                    }

                    response = self._format_approval_card(draft, lang_code=raw_lang_code, draft_saved=draft_saved, save_error=save_error)
                    return {"task": task.to_dict(), "message": response}

            elif pending.get("type") == "note" and pending.get("step") == "waiting_for_body":
                title = pending.get("title", "Cortex Note")
                content = message.strip()
                self.pending_action = None
                task = Task(
                    intent=f"write note called {title} saying {content}",
                    command=TaskCommand.WRITE_NOTE,
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                    params={"title": title, "body": content},
                    language=detected_lang,
                )
                self._execute(task)
                return {"task": task.to_dict(), "message": task.result or localize("note_written", raw_lang_code, title=title)}

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") == "waiting_for_recipient":
                raw_rec = message.strip()
                raw_body = pending.get("body", "")
                task = pending.get("task")
                return self.chat(f"Send WhatsApp to {raw_rec} saying {raw_body}" if raw_body else f"Send WhatsApp to {raw_rec}")

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") in ("waiting_for_recipient_clarification", "waiting_for_recipient_disambiguation"):
                user_msg = message.strip()
                # Check multilingual cancellation
                if any(w in user_msg.lower() for w in ("cancel", "abort", "nevermind", "stop", "no", "none", "ಬೇಡ", "ರದ್ದು", "नहीं", "रद्द", "வேண்டாம்", "ரத்து", "వద్దు", "రద్దు")):
                    return self._handle_cancellation(message, raw_lang_code, detected_lang)

                candidates = pending.get("candidates") or pending.get("suggestions", [])
                chosen = None
                if user_msg.isdigit():
                    idx = int(user_msg) - 1
                    if 0 <= idx < len(candidates):
                        chosen = candidates[idx]
                if not chosen:
                    for s in candidates:
                        s_name = getattr(s, "name", "") or getattr(s, "display_name", "")
                        if user_msg.lower() in s_name.lower() or s_name.lower() in user_msg.lower():
                            chosen = s
                            break

                raw_body = pending.get("raw_body", "")
                task = pending.get("task")
                if chosen:
                    rec_name = chosen.name
                    rec_phone = chosen.phone
                    task.params["recipient"] = rec_name
                    task.params["contact_name"] = rec_name
                    task.params["phone"] = rec_phone
                    task.params["contact_id"] = getattr(chosen, "id", "")
                    task.params["contact_source"] = getattr(chosen, "source", "")
                    task.params["contact_verified"] = getattr(chosen, "is_verified", True)
                    task.params["channel"] = "whatsapp"

                    if not raw_body:
                        task.status = TaskStatus.NEED_INFO
                        self.pending_action = {
                            "type": "whatsapp_draft",
                            "step": "waiting_for_body",
                            "task_id": task.id,
                            "task": task,
                            "recipient": rec_name,
                            "phone": rec_phone,
                            "contact_id": task.params["contact_id"],
                            "contact_source": task.params["contact_source"],
                            "contact_verified": task.params["contact_verified"],
                            "channel": "whatsapp",
                            "lang": p_lang,
                        }
                        self.tasks[task.id] = task
                        self._persist_task(task)
                        return {"task": task.to_dict(), "message": localize("need_message_body", p_lang, recipient=rec_name)}

                    formatted_body = compose_whatsapp_message(raw_body, recipient_name=rec_name, lang_code=p_lang)
                    draft = WhatsAppDraft(
                        recipient=rec_name,
                        phone=rec_phone,
                        body=formatted_body,
                        channel="whatsapp",
                        language=p_lang,
                        contact_id=task.params["contact_id"],
                        contact_source=task.params["contact_source"],
                    )
                    task.params["body"] = raw_body
                    task.params["formatted_body"] = formatted_body
                    task.params["approval_hash"] = draft.approval_hash
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_prepared", f"WhatsApp message prepared for {rec_name} ({rec_phone})")
                    self.automation.whatsapp.prepare_draft(rec_name, rec_phone, formatted_body)

                    self.pending_action = {
                        "type": "whatsapp_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "task": task,
                        "recipient": rec_name,
                        "phone": rec_phone,
                        "contact_id": task.params["contact_id"],
                        "contact_source": task.params["contact_source"],
                        "contact_verified": task.params["contact_verified"],
                        "body": formatted_body,
                        "raw_body": raw_body,
                        "draft": draft,
                        "channel": "whatsapp",
                        "lang": p_lang,
                    }
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {"task": task.to_dict(), "message": format_whatsapp_approval_card(draft, lang_code=p_lang)}
                else:
                    return self.chat(f"Send WhatsApp to {user_msg} saying {raw_body}" if raw_body else f"Send WhatsApp to {user_msg}")

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") == "confirm_direct_number":
                user_msg = message.strip()
                if any(w in user_msg.lower() for w in ("yes", "confirm", "proceed", "send", "sure", "ok", "okay", "yep", "ಹೌದು", "हाँ", "சரி", "సరే")):
                    task = pending.get("task")
                    phone = pending.get("phone", "")
                    raw_body = pending.get("raw_body", "")
                    rec_name = phone

                    task.params["recipient"] = phone
                    task.params["contact_name"] = phone
                    task.params["phone"] = phone
                    task.params["contact_id"] = f"direct_{phone}"
                    task.params["contact_source"] = "user_provided_unverified"
                    task.params["contact_verified"] = False
                    task.params["channel"] = "whatsapp"

                    if not raw_body:
                        task.status = TaskStatus.NEED_INFO
                        self.pending_action = {
                            "type": "whatsapp_draft",
                            "step": "waiting_for_body",
                            "task_id": task.id,
                            "task": task,
                            "recipient": rec_name,
                            "phone": phone,
                            "contact_id": task.params["contact_id"],
                            "contact_source": task.params["contact_source"],
                            "contact_verified": False,
                            "channel": "whatsapp",
                            "lang": p_lang,
                        }
                        self.tasks[task.id] = task
                        self._persist_task(task)
                        return {"task": task.to_dict(), "message": localize("need_message_body", p_lang, recipient=phone)}

                    formatted_body = compose_whatsapp_message(raw_body, recipient_name="", lang_code=p_lang)
                    draft = WhatsAppDraft(
                        recipient=phone,
                        phone=phone,
                        body=formatted_body,
                        channel="whatsapp",
                        language=p_lang,
                        contact_id=task.params["contact_id"],
                        contact_source=task.params["contact_source"],
                    )
                    task.params["body"] = raw_body
                    task.params["formatted_body"] = formatted_body
                    task.params["approval_hash"] = draft.approval_hash
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_prepared", f"WhatsApp message prepared for unverified destination ({phone})")
                    self.automation.whatsapp.prepare_draft(phone, phone, formatted_body)

                    self.pending_action = {
                        "type": "whatsapp_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "task": task,
                        "recipient": phone,
                        "phone": phone,
                        "contact_id": task.params["contact_id"],
                        "contact_source": task.params["contact_source"],
                        "contact_verified": False,
                        "body": formatted_body,
                        "raw_body": raw_body,
                        "draft": draft,
                        "channel": "whatsapp",
                        "lang": p_lang,
                    }
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {"task": task.to_dict(), "message": format_whatsapp_approval_card(draft, lang_code=p_lang)}
                else:
                    return self._handle_cancellation(message, raw_lang_code, detected_lang)

            elif pending.get("type") == "whatsapp_disambiguation":
                user_choice = message.strip()
                candidates = pending.get("candidates", [])
                chosen_cand = None

                # Check if choice is numeric (e.g., "1", "2")
                if user_choice.isdigit():
                    idx = int(user_choice) - 1
                    if 0 <= idx < len(candidates):
                        chosen_cand = candidates[idx]

                # Check if choice is "first", "second", etc. or matches candidate name
                if not chosen_cand:
                    choice_lower = user_choice.lower()
                    if "first" in choice_lower and len(candidates) >= 1:
                        chosen_cand = candidates[0]
                    elif "second" in choice_lower and len(candidates) >= 2:
                        chosen_cand = candidates[1]
                    else:
                        for cand in candidates:
                            c_name = cand.name.lower()
                            if choice_lower in c_name or c_name in choice_lower or any(part in c_name.split() for part in choice_lower.split()):
                                chosen_cand = cand
                                break

                if not chosen_cand:
                    prompt = (
                        f"I couldn't identify which contact you meant. "
                        f"Please specify the number (e.g. 1 or 2) or the full contact name."
                    )
                    return {"task": pending.get("task", Task()).to_dict(), "message": prompt}

                # Successfully resolved to chosen candidate
                rec_name = chosen_cand.name
                rec_phone = chosen_cand.phone
                raw_body = pending.get("raw_body", "")
                task = pending.get("task")
                if not task:
                    task = Task(
                        intent=f"send whatsapp to {rec_name}",
                        command=TaskCommand.SEND_MESSAGE,
                        risk_level=RiskLevel.HIGH,
                        requires_approval=True,
                        language=detected_lang,
                    )

                task.params["recipient"] = rec_name
                task.params["contact_name"] = rec_name
                task.params["phone"] = rec_phone
                task.params["contact_id"] = getattr(chosen_cand, "id", "")
                task.params["contact_source"] = getattr(chosen_cand, "source", "")
                task.params["contact_verified"] = getattr(chosen_cand, "is_verified", True)
                task.params["channel"] = "whatsapp"

                if not raw_body:
                    task.status = TaskStatus.NEED_INFO
                    self.pending_action = {
                        "type": "whatsapp_draft",
                        "step": "waiting_for_body",
                        "task_id": task.id,
                        "task": task,
                        "recipient": rec_name,
                        "phone": rec_phone,
                        "contact_id": task.params["contact_id"],
                        "contact_source": task.params["contact_source"],
                        "contact_verified": task.params["contact_verified"],
                        "channel": "whatsapp",
                        "lang": p_lang,
                    }
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {"task": task.to_dict(), "message": localize("need_message_body", p_lang, recipient=rec_name)}

                formatted_body = compose_whatsapp_message(raw_body, recipient_name=rec_name, lang_code=p_lang)
                draft = WhatsAppDraft(
                    recipient=rec_name,
                    phone=rec_phone,
                    body=formatted_body,
                    channel="whatsapp",
                    language=p_lang,
                    contact_id=task.params["contact_id"],
                    contact_source=task.params["contact_source"],
                )
                task.params["body"] = raw_body
                task.params["formatted_body"] = formatted_body
                task.params["approval_hash"] = draft.approval_hash
                task.status = TaskStatus.WAITING_APPROVAL
                task.add_event("draft_prepared", f"WhatsApp message prepared for {rec_name} ({rec_phone})")
                self.automation.whatsapp.prepare_draft(rec_name, rec_phone, formatted_body)

                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "confirm_send",
                    "task_id": task.id,
                    "task": task,
                    "recipient": rec_name,
                    "phone": rec_phone,
                    "contact_id": task.params["contact_id"],
                    "contact_source": task.params["contact_source"],
                    "contact_verified": task.params["contact_verified"],
                    "body": formatted_body,
                    "raw_body": raw_body,
                    "draft": draft,
                    "channel": "whatsapp",
                    "lang": p_lang,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": format_whatsapp_approval_card(draft, lang_code=p_lang)}

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") == "waiting_for_body":
                rec_name = pending.get("recipient", "the recipient")
                raw_rec = pending.get("raw_recipient", rec_name)
                rec_phone = pending.get("phone", "")
                contact_id = pending.get("contact_id", "")
                contact_source = pending.get("contact_source", "")
                contact_verified = pending.get("contact_verified", False)
                raw_body = message.strip()
                task = pending.get("task")
                if not task:
                    task = Task(
                        intent=f"send whatsapp to {rec_name}",
                        command=TaskCommand.SEND_MESSAGE,
                        risk_level=RiskLevel.HIGH,
                        requires_approval=True,
                        language=detected_lang,
                    )

                formatted_body = compose_whatsapp_message(raw_body, recipient_name=rec_name, lang_code=p_lang)
                draft = WhatsAppDraft(
                    recipient=rec_name,
                    phone=rec_phone,
                    body=formatted_body,
                    channel="whatsapp",
                    language=p_lang,
                    contact_id=contact_id,
                    contact_source=contact_source,
                )
                task.params["recipient"] = raw_rec or rec_name
                task.params["contact_name"] = rec_name
                task.params["phone"] = rec_phone
                task.params["contact_id"] = contact_id
                task.params["contact_source"] = contact_source
                task.params["contact_verified"] = contact_verified
                task.params["channel"] = "whatsapp"
                task.params["body"] = raw_body
                task.params["formatted_body"] = formatted_body
                task.params["approval_hash"] = draft.approval_hash
                task.status = TaskStatus.WAITING_APPROVAL
                task.add_event("draft_prepared", f"WhatsApp message prepared for {rec_name} ({rec_phone})")
                self.automation.whatsapp.prepare_draft(rec_name, rec_phone, formatted_body)

                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "confirm_send",
                    "task_id": task.id,
                    "task": task,
                    "recipient": rec_name,
                    "phone": rec_phone,
                    "contact_id": contact_id,
                    "contact_source": contact_source,
                    "contact_verified": contact_verified,
                    "body": formatted_body,
                    "raw_body": raw_body,
                    "draft": draft,
                    "channel": "whatsapp",
                    "lang": p_lang,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": format_whatsapp_approval_card(draft, lang_code=p_lang)}

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") in ("confirm_send", "draft_only_review"):
                task_id = pending.get("task_id")
                task = self.tasks.get(task_id) or pending.get("task")
                recipient = pending.get("recipient", "")
                phone = pending.get("phone", "")

                has_negation = (
                    bool(re.search(r"\b(?:don'?t|do\s+not|never|stop|cancel|reject|abort|discard|no|nope|nah)\b", msg_lower))
                    or any(kw in msg_lower for kw in ("ಬೇಡ", "ಕಳಿಸಬೇಡ", "ಕಳುಹಿಸಬೇಡ", "मत", "नहीं", "வேண்டாம்", "வద్దు"))
                )
                is_edit = any(kw in msg_lower for kw in (
                    "shorter", "concise", "formal", "casual", "brief", "polite", "friendly",
                    "add", "remove", "change", "include", "mention", "don't mention", "dont mention",
                    "omit", "without time", "make it", "update", "rewrite", "replace",
                    "ಕನ್ನಡ", "ಕನ್ನಡದಲ್ಲಿ", "हिंदी", "हिंदी में", "தமிழ்", "தமிழில்", "తెలుగు", "తెలుగులో",
                ))

                is_confirm = (
                    not is_edit
                    and not has_negation
                    and (
                        bool(re.search(r"\b(yes|send\s+it|approve|go\s+ahead|send|sure|ok|okay|please\s+send|y|yep|agree|confirmed)\b", msg_lower))
                        or any(kw in msg_lower for kw in ("ಕಳುಹಿಸು", "ಕಳಿಸು", "ಸರಿ", "ಹೌದು", "ಆಯ್ತು", "भेजो", "भेजें", "हाँ", "हां", "ठीक है", "அனுப்பு", "சரி", "పంపు", "సరే"))
                    )
                )

                if has_negation and not is_edit:
                    return self._handle_cancellation(message, raw_lang_code, detected_lang)

                elif is_confirm:
                    if pending.get("draft_only") or (task and task.params.get("draft_only")):
                        return {
                            "task": task.to_dict() if task else {},
                            "message": "Cannot send: this task was prepared as draft-only ('Draft only — not sent'). Ready in WhatsApp composer for review. If you want to send this message, please ask to send it in a new instruction.",
                        }
                    self.pending_action = None
                    approved_task = self.approve(task_id, approved=True)
                    if approved_task.get("status") in (TaskStatus.FAILED.value, TaskStatus.FAILED, "failed"):
                        return {
                            "task": approved_task,
                            "message": approved_task.get("error") or "Failed to send WhatsApp message.",
                        }
                    return {
                        "task": approved_task,
                        "message": f"WhatsApp message sent to {recipient}.",
                    }

                elif is_edit:
                    tone = "formal" if any(w in msg_lower for w in ("formal", "professional", "polite")) else ("casual" if any(w in msg_lower for w in ("casual", "friendly", "shorter", "brief")) else "normal")
                    omit_time = bool(re.search(r"\b(?:don'?t\s+mention|dont\s+mention|omit|without)\s+(?:the\s+)?time\b", msg_lower))

                    raw_seed = pending.get("raw_body") or pending.get("body", "")
                    updated_body = compose_whatsapp_message(raw_seed, recipient_name=recipient, tone=tone, lang_code=p_lang, omit_time=omit_time)
                    draft = WhatsAppDraft(
                        recipient=recipient,
                        phone=phone,
                        body=updated_body,
                        tone=tone,
                        language=p_lang,
                        contact_id=task.params.get("contact_id", "") if task else "",
                        contact_source=task.params.get("contact_source", "") if task else "",
                        draft_only=bool(task.params.get("draft_only", False)) if task else False,
                    )

                    if task:
                        task.params["body"] = pending.get("raw_body") or updated_body
                        task.params["formatted_body"] = updated_body
                        task.params["approval_hash"] = draft.approval_hash
                        task.status = TaskStatus.WAITING_APPROVAL
                        task.add_event("draft_edited", f"WhatsApp message updated: {message}")
                        self._persist_task(task)

                    pending["draft"] = draft
                    pending["body"] = updated_body

                    response = format_whatsapp_approval_card(draft, lang_code=p_lang)
                    return {"task": task.to_dict() if task else {}, "message": response}

            elif pending.get("type") == "message" and pending.get("step") == "waiting_for_body":
                recipient = pending.get("recipient", "the recipient")
                clean_body = re.sub(
                    r"^(?:tell\s+(?:him|her|them|it)\s+|saying\s+|that\s+says\s+|that\s+|say\s+)",
                    "",
                    message.strip(),
                    flags=re.IGNORECASE,
                ).strip()
                self.pending_action = None
                task = Task(
                    intent=f"send message to {recipient} saying {clean_body}",
                    command=TaskCommand.SEND_MESSAGE,
                    risk_level=RiskLevel.HIGH,
                    requires_approval=True,
                    params={"recipient": recipient, "body": clean_body},
                    language=detected_lang,
                )
                task.status = TaskStatus.WAITING_APPROVAL
                self.tasks[task.id] = task
                response = localize("approval_prompt", raw_lang_code, action=f"send message to {recipient}")
                return {"task": task.to_dict(), "message": response}

        # Check for contextual Apple Notes follow-ups
        if self.last_note:
            msg_clean = message.strip()
            msg_low = msg_clean.lower().rstrip(".!")
            if any(msg_low == phrase or msg_low.startswith(phrase + " ") for phrase in ("open that note", "open the note", "open this note", "view that note")):
                task = Task(intent=message, command=TaskCommand.WRITE_NOTE, risk_level=RiskLevel.LOW, requires_approval=False, params={"action": "open_note"}, language=detected_lang)
                self.tasks[task.id] = task
                self._execute(task)
                return {"task": task.to_dict(), "message": task.result or f"Opened note '{self.last_note['title']}' in Apple Notes."}
            elif any(phrase in msg_low for phrase in ("make the title shorter", "make title shorter", "shorten the title", "shorten title")):
                task = Task(intent=message, command=TaskCommand.WRITE_NOTE, risk_level=RiskLevel.LOW, requires_approval=False, params={"action": "shorten_title"}, language=detected_lang)
                self.tasks[task.id] = task
                self._execute(task)
                return {"task": task.to_dict(), "message": task.result or f"Updated note title to '{self.last_note['title']}'."}
            elif re.search(r"^(?:add\s+(?:this\s+)?point\s*[:=]?|add\s+(?:to\s+(?:the\s+)?note)?\s*[:=]?)\s*(.+)", msg_clean, re.IGNORECASE):
                m_pt = re.search(r"^(?:add\s+(?:this\s+)?point\s*[:=]?|add\s+(?:to\s+(?:the\s+)?note)?\s*[:=]?)\s*(.+)", msg_clean, re.IGNORECASE)
                point_text = m_pt.group(1).strip()
                task = Task(intent=message, command=TaskCommand.WRITE_NOTE, risk_level=RiskLevel.LOW, requires_approval=False, params={"action": "append_note", "point": point_text}, language=detected_lang)
                self.tasks[task.id] = task
                self._execute(task)
                return {"task": task.to_dict(), "message": task.result or f"Added point to note '{self.last_note['title']}':\n{point_text}"}

        sequence = self._split_sequence(message)
        if len(sequence) > 1:
            return self._chat_sequence(message, sequence, source)

        analysis = self._analyze_intent(message, lang_code=raw_lang_code)
        command = analysis["command"]
        risk = analysis["risk_level"]
        approval = analysis["requires_approval"]
        block_reason = analysis["block_reason"]
        params = analysis["params"]

        task = Task(
            intent=message,
            command=command,
            risk_level=risk,
            requires_approval=approval,
            params=params,
            language=detected_lang,
        )
        task.steps = self._steps_for(command, approval)
        task.add_event("received", f"Received {source} request.")
        if detected_lang != LanguageCode.ENGLISH:
            task.add_event("language_detected", f"Language: {detected_lang.display_name}")

        if risk == RiskLevel.BLOCKED:
            task.status = TaskStatus.BLOCKED
            task.error = block_reason
            task.add_event("blocked", block_reason or "Task blocked.")
            response = block_reason or localize("action_blocked", raw_lang_code)
        elif command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL) and not params.get("body", "").strip():
            raw_recipient = params.get("recipient", "").strip()
            if raw_recipient.lower() in ("someone", "somebody", "anyone", "a person", "an email", ""):
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", "Awaiting recipient specification.")
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient",
                    "command": command,
                    "task": task,
                    "lang": raw_lang_code,
                }
                response = localize("need_recipient", raw_lang_code)
            else:
                resolution = self.recipient_resolver.resolve(raw_recipient, full_message=message)
                if resolution.status == "need_clarification":
                    task.status = TaskStatus.NEED_INFO
                    task.add_event("need_info", f"Awaiting recipient clarification: {resolution.clarification_prompt}")
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_recipient_clarification",
                        "task_id": task.id,
                        "command": command,
                        "raw_recipient": raw_recipient,
                        "body": "",
                        "subject": params.get("subject", "").strip(),
                        "original_intent": message,
                        "task": task,
                        "lang": raw_lang_code,
                    }
                    response = resolution.clarification_prompt
                elif resolution.status == "multiple_candidates":
                    task.status = TaskStatus.NEED_INFO
                    task.add_event("need_info", f"Awaiting recipient disambiguation: {resolution.clarification_prompt}")
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_recipient_disambiguation",
                        "task_id": task.id,
                        "command": command,
                        "candidates": resolution.candidates,
                        "raw_recipient": raw_recipient,
                        "body": "",
                        "subject": params.get("subject", "").strip(),
                        "original_intent": message,
                        "task": task,
                        "lang": raw_lang_code,
                    }
                    response = resolution.clarification_prompt
                else:
                    resolved = resolution.recipient
                    rec_display = f"{resolved.name} <{resolved.email}>" if resolved and resolved.name and resolved.name != resolved.email else (resolved.email if resolved else raw_recipient)
                    task.status = TaskStatus.NEED_INFO
                    task.add_event("need_info", f"Awaiting content/body for {rec_display}.")
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_body",
                        "command": command,
                        "recipient": raw_recipient,
                        "recipient_display": rec_display,
                        "recipient_email": resolved.email if resolved else raw_recipient,
                        "subject": params.get("subject", "").strip(),
                        "task": task,
                        "lang": raw_lang_code,
                    }
                    response = localize("need_body", raw_lang_code, recipient=raw_recipient)
        elif command == TaskCommand.WRITE_NOTE and not params.get("body", "").strip():
            task.status = TaskStatus.NEED_INFO
            title = params.get("title", "Cortex Note")
            self.pending_action = {
                "type": "note",
                "step": "waiting_for_body",
                "title": title,
                "lang": raw_lang_code,
            }
            response = localize("need_note_body", raw_lang_code, title=title)
        elif (command in (TaskCommand.SEND_MESSAGE, TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP)) and ("whatsapp" in message.lower() or command in (TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP) or params.get("channel") == "whatsapp" or "prepare" in message.lower() or "draft" in message.lower()):
            raw_rec = params.get("recipient", "").strip()
            raw_body = params.get("body", "").strip()

            if not raw_rec:
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", "Awaiting recipient specification.")
                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "waiting_for_recipient",
                    "task_id": task.id,
                    "task": task,
                    "body": raw_body,
                    "lang": raw_lang_code,
                }
                response = "Who would you like to send a WhatsApp message to?"
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": response}

            resolution = self.recipient_resolver.resolve_messaging_contact(raw_rec, full_message=message, channel="whatsapp")
            if resolution.status in (ContactResolutionStatus.SOURCE_UNAVAILABLE, "source_unavailable"):
                task.status = TaskStatus.FAILED
                task.error = resolution.clarification_prompt
                task.add_event("failed", resolution.clarification_prompt)
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}

            elif resolution.status in (ContactResolutionStatus.CONTACT_DATA_STALE, "contact_data_stale"):
                task.status = TaskStatus.FAILED
                task.error = resolution.clarification_prompt
                task.add_event("failed", resolution.clarification_prompt)
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}

            elif resolution.status in (ContactResolutionStatus.MULTIPLE_MATCHES, "multiple_matches", "multiple_candidates"):
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting recipient disambiguation: {resolution.clarification_prompt}")
                self.pending_action = {
                    "type": "whatsapp_disambiguation",
                    "step": "disambiguate_contact",
                    "task_id": task.id,
                    "task": task,
                    "candidates": resolution.candidates,
                    "raw_recipient": raw_rec,
                    "raw_body": raw_body,
                    "lang": raw_lang_code,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}

            elif resolution.status in (ContactResolutionStatus.NO_MATCH, "no_match", "need_clarification"):
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting recipient clarification: {resolution.clarification_prompt}")
                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "waiting_for_recipient_clarification",
                    "task_id": task.id,
                    "task": task,
                    "suggestions": resolution.suggestions,
                    "candidates": resolution.suggestions,
                    "raw_recipient": raw_rec,
                    "raw_body": raw_body,
                    "lang": raw_lang_code,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}

            elif resolution.status in (ContactResolutionStatus.INVALID_OR_UNVERIFIED_NUMBER, "invalid_or_unverified_number"):
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting direct number confirmation: {resolution.clarification_prompt}")
                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "confirm_direct_number",
                    "task_id": task.id,
                    "task": task,
                    "phone": resolution.contact.phone if resolution.contact else raw_rec,
                    "raw_recipient": raw_rec,
                    "raw_body": raw_body,
                    "lang": raw_lang_code,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}

            # Contact resolved (EXACT_MATCH)
            contact = resolution.contact
            rec_name = contact.name if contact else raw_rec
            rec_phone = contact.phone if contact else ""
            task.params["recipient"] = raw_rec or rec_name
            task.params["contact_name"] = rec_name
            task.params["phone"] = rec_phone
            task.params["contact_id"] = getattr(contact, "id", "") if contact else ""
            task.params["contact_source"] = getattr(contact, "source", "") if contact else ""
            task.params["contact_verified"] = getattr(contact, "is_verified", False) if contact else False
            task.params["channel"] = "whatsapp"

            if not raw_body:
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting message body for {rec_name}.")
                self.pending_action = {
                    "type": "whatsapp_draft",
                    "step": "waiting_for_body",
                    "task_id": task.id,
                    "task": task,
                    "recipient": rec_name,
                    "raw_recipient": raw_rec,
                    "phone": rec_phone,
                    "contact_id": task.params["contact_id"],
                    "contact_source": task.params["contact_source"],
                    "contact_verified": task.params["contact_verified"],
                    "channel": "whatsapp",
                    "lang": raw_lang_code,
                }
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"task": task.to_dict(), "message": localize("need_message_body", raw_lang_code, recipient=raw_rec or rec_name)}

            # Both recipient and body present
            draft_only = is_draft_only_request(message) or bool(params.get("draft_only", False))
            formatted_body = compose_whatsapp_message(raw_body, recipient_name=rec_name, lang_code=raw_lang_code)
            draft = WhatsAppDraft(
                recipient=rec_name,
                phone=rec_phone,
                body=formatted_body,
                channel="whatsapp",
                language=raw_lang_code,
                contact_id=task.params["contact_id"],
                contact_source=task.params["contact_source"],
                draft_only=draft_only,
            )
            task.params["body"] = raw_body
            task.params["formatted_body"] = formatted_body
            task.params["draft_only"] = draft_only
            task.params["approval_hash"] = draft.approval_hash
            task.status = TaskStatus.WAITING_APPROVAL
            task.add_event(
                "draft_prepared",
                f"WhatsApp message prepared for {rec_name} ({rec_phone})" + (" [Draft only — not sent]" if draft_only else "")
            )
            self.automation.whatsapp.prepare_draft(rec_name, rec_phone, formatted_body, draft_only=draft_only)

            self.pending_action = {
                "type": "whatsapp_draft",
                "step": "draft_only_review" if draft_only else "confirm_send",
                "task_id": task.id,
                "task": task,
                "recipient": rec_name,
                "phone": rec_phone,
                "contact_id": task.params["contact_id"],
                "contact_source": task.params["contact_source"],
                "contact_verified": task.params["contact_verified"],
                "body": formatted_body,
                "raw_body": raw_body,
                "draft": draft,
                "draft_only": draft_only,
                "channel": "whatsapp",
                "lang": raw_lang_code,
            }
            self.tasks[task.id] = task
            self._persist_task(task)
            response = format_whatsapp_approval_card(draft, lang_code=raw_lang_code)
            return {"task": task.to_dict(), "message": response}

        elif command == TaskCommand.SEND_MESSAGE and not params.get("body", "").strip():
            task.status = TaskStatus.NEED_INFO
            recipient = params.get("recipient", "the recipient")
            self.pending_action = {
                "type": "message",
                "step": "waiting_for_body",
                "recipient": recipient,
                "lang": raw_lang_code,
            }
            response = localize("need_message_body", raw_lang_code, recipient=recipient)
        elif command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL) and params.get("body", "").strip():
            raw_rec = params.get("recipient", "").strip()
            raw_body = params.get("body", "").strip()
            if raw_rec.lower() in ("someone", "somebody", "anyone", "a person", "an email", ""):
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", "Awaiting recipient specification.")
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient",
                    "command": command,
                    "body": raw_body,
                    "task": task,
                    "lang": raw_lang_code,
                }
                response = localize("need_recipient", raw_lang_code)
                return {"task": task.to_dict(), "message": response}

            resolution = self.recipient_resolver.resolve(raw_rec, full_message=message)
            if resolution.status == "need_clarification":
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting recipient clarification: {resolution.clarification_prompt}")
                self.tasks[task.id] = task
                self._persist_task(task)
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient_clarification",
                    "task_id": task.id,
                    "command": command,
                    "raw_recipient": raw_rec,
                    "body": raw_body,
                    "subject": params.get("subject", "").strip(),
                    "original_intent": message,
                    "task": task,
                    "lang": raw_lang_code,
                }
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}
            elif resolution.status == "multiple_candidates":
                task.status = TaskStatus.NEED_INFO
                task.add_event("need_info", f"Awaiting recipient disambiguation: {resolution.clarification_prompt}")
                self.tasks[task.id] = task
                self._persist_task(task)
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient_disambiguation",
                    "task_id": task.id,
                    "command": command,
                    "candidates": resolution.candidates,
                    "raw_recipient": raw_rec,
                    "body": raw_body,
                    "subject": params.get("subject", "").strip(),
                    "original_intent": message,
                    "task": task,
                    "lang": raw_lang_code,
                }
                return {"task": task.to_dict(), "message": resolution.clarification_prompt}
            else:
                resolved = resolution.recipient
                rec_display = f"{resolved.name} <{resolved.email}>" if resolved and resolved.name and resolved.name != resolved.email else (resolved.email if resolved else raw_rec)

                if is_ambiguous_email_intent(raw_body):
                    task.status = TaskStatus.NEED_INFO
                    task.add_event("need_info", f"Awaiting clarification for ambiguous intent: '{raw_body}'")
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_body",
                        "command": command,
                        "recipient": raw_rec,
                        "recipient_display": rec_display,
                        "recipient_email": resolved.email if resolved else raw_rec,
                        "subject": params.get("subject", "").strip(),
                        "task": task,
                        "lang": raw_lang_code,
                    }
                    clarif_prompt = f"Could you please clarify what specific message or details you would like to include regarding '{raw_body}'?"
                    return {"task": task.to_dict(), "message": clarif_prompt}

                sender_acc = params.get("sender_account") or params.get("account") or "Primary Account"
                atts = params.get("attachments") or []
                cc_list = params.get("cc") or []
                bcc_list = params.get("bcc") or []

                blocked_att = None
                missing_att = None
                for a in atts:
                    if a:
                        if is_sensitive_attachment(a):
                            blocked_att = a
                            break
                        if not os.path.exists(a):
                            missing_att = a
                            break

                if blocked_att:
                    task.status = TaskStatus.FAILED
                    task.error = f"Security policy violation: attaching sensitive system or credential file '{blocked_att}' is blocked."
                    task.add_event("failed", task.error)
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {
                        "task": task.to_dict(),
                        "message": f"Security policy violation: attaching sensitive system or credential file '{blocked_att}' is blocked.",
                    }

                if missing_att:
                    task.status = TaskStatus.FAILED
                    task.error = f"Attachment file not found: {missing_att}"
                    task.add_event("failed", task.error)
                    task.state_version += 1
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {
                        "task": task.to_dict(),
                        "message": f"Cannot prepare email: attachment file not found at '{missing_att}'. Please provide a valid file path.",
                    }

                clean_body, meta = convert_instruction_to_recipient_content(raw_body)
                content_for_draft = clean_body or raw_body
                tone_override = meta.get("extracted_tone")

                # Cooperative intelligence: enrich draft with recent research findings if available
                is_research_request = any(w in raw_body.lower() for w in (
                    "research findings", "findings", "research results", "ai research",
                    "ai developments", "these developments", "these ai", "search results",
                    "ai update", "summarizing", "summarising", "latest developments",
                    "ai summary", "these updates"
                ))
                if is_research_request and self.last_search_results:
                    if any(cta in raw_body.lower() for cta in ("thoughts", "opinion", "think", "feedback", "perspective")):
                        call_to_action = "Please let me know your thoughts on these developments."
                    else:
                        call_to_action = "Please let me know if you would like me to dive deeper into any of these areas."

                    findings_bullets = []
                    for r in self.last_search_results[:3]:
                        t = r.get("title", "").strip()
                        t_clean = re.sub(r"\s*(--|\||-)\s*.*$", "", t).strip() or t
                        b = clean_search_response(r.get("body", "")).strip()
                        b = re.sub(r"^\*\*[^*]+\*\*:\s*", "", b).strip()
                        b = re.sub(r"^" + re.escape(t_clean) + r"[:\s-]+", "", b, flags=re.IGNORECASE).strip()
                        m_sent = re.search(r"^(.*?[\.\!\?])(?:\s|$)", b)
                        if m_sent and len(m_sent.group(1)) > 20:
                            first_sent = m_sent.group(1).strip()
                        else:
                            first_sent = (b[:120].rsplit(" ", 1)[0].rstrip(".,:;-") + ".") if b else "Significant advancements and breakthrough findings."
                        findings_bullets.append(f"• {t_clean}: {first_sent}")

                    bullets_text = "\n".join(findings_bullets)
                    content_for_draft = (
                        f"Here is a summary of the latest developments in artificial intelligence:\n\n"
                        f"{bullets_text}\n\n"
                        f"{call_to_action}"
                    )

                draft = self.email_engine.compose_email(
                    raw_intent=message,
                    recipient_raw=rec_display,
                    content=content_for_draft,
                    subject_override=params.get("subject", ""),
                    tone_override=tone_override,
                    use_gemini=self.use_gemini,
                    gemini_model=self.gemini_model,
                    sender_account=sender_acc,
                    attachments=atts,
                    cc=cc_list,
                    bcc=bcc_list,
                    language=raw_lang_code,
                )
                draft = self.email_engine.run_quality_control(draft, known_facts=[raw_body])
                draft.approval_hash = draft.compute_hash()

                draft_saved = True
                save_error = ""
                try:
                    res = self.automation.execute(TaskCommand.DRAFT_MAIL, {
                        "recipient": draft.recipient,
                        "subject": draft.subject,
                        "body": draft.body,
                        "account": draft.sender_account,
                        "attachments": draft.attachments,
                        "cc": draft.cc,
                        "bcc": draft.bcc,
                    })
                    if isinstance(res, dict) and res.get("status") in ("failed", "error", "permission_denied"):
                        draft_saved = False
                        save_error = res.get("error") or res.get("message") or "Provider draft creation failed"
                except Exception as e:
                    draft_saved = False
                    save_error = str(e)

                task.params["recipient"] = raw_rec if raw_rec else draft.recipient
                task.params["recipient_email"] = draft.recipient
                task.params["subject"] = draft.subject
                task.params["body"] = raw_body
                task.params["formatted_body"] = draft.body
                task.params["sender_account"] = draft.sender_account
                task.params["account"] = draft.sender_account
                task.params["approval_hash"] = draft.approval_hash
                task.params["attachments"] = draft.attachments
                task.params["cc"] = draft.cc
                task.params["bcc"] = draft.bcc
                task.context = TaskContext(
                    recipient=raw_rec if raw_rec else draft.recipient,
                    recipient_role=draft.recipient_role,
                    purpose=draft.subject,
                    requested_tone=draft.tone,
                    language=detected_lang,
                )

                if command == TaskCommand.DRAFT_MAIL:
                    task.status = TaskStatus.COMPLETED
                    task.result = f"Draft created for {draft.recipient} with subject '{draft.subject}'. The email has not been sent."
                    task.add_event("completed", task.result)
                    response = task.result
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": raw_rec if raw_rec else draft.recipient,
                        "recipient_email": draft.recipient,
                        "subject": draft.subject,
                        "body": raw_body,
                        "sender_account": draft.sender_account,
                        "attachments": draft.attachments,
                        "cc": draft.cc,
                        "bcc": draft.bcc,
                        "draft": draft,
                        "lang": raw_lang_code,
                    }
                else:
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_prepared", f"Draft prepared for {draft.recipient} — Subject: {draft.subject}")
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "confirm_send",
                        "task_id": task.id,
                        "recipient": raw_rec if raw_rec else draft.recipient,
                        "recipient_email": draft.recipient,
                        "subject": draft.subject,
                        "body": raw_body,
                        "sender_account": draft.sender_account,
                        "attachments": draft.attachments,
                        "cc": draft.cc,
                        "bcc": draft.bcc,
                        "draft": draft,
                        "lang": raw_lang_code,
                    }
                    response = self._format_approval_card(draft, lang_code=raw_lang_code, draft_saved=draft_saved, save_error=save_error)
        elif command == TaskCommand.TRANSLATE:
            target_lang, _, _ = extract_explicit_language_directive(message)
            if not target_lang:
                target_lang = raw_lang_code if raw_lang_code != "en" else "kn"

            text_match = re.search(r"['\"]([^'\"]+)['\"]", message)
            if text_match:
                source_text = text_match.group(1).strip()
            else:
                source_text = re.sub(
                    r"^(?:translate|translation of|how do you say|ಅನುವಾದ ಮಾಡು|ಅನುವಾದಿಸು|अनुवाद करो|மொழிபெயர்|అనువాదం చేయి)\s+",
                    "",
                    message,
                    flags=re.IGNORECASE,
                ).strip()
                source_text = re.sub(
                    r"\s+(?:to|in|into)\s+(?:kannada|hindi|tamil|telugu|english|ಕನ್ನಡ|हिंदी|தமிழ்|తెలుగు)\b.*$",
                    "",
                    source_text,
                    flags=re.IGNORECASE,
                ).strip()

            translated = translate_text(
                source_text,
                target_lang=target_lang,
                gemini_model=self.gemini_model if self.use_gemini else None,
            )
            task.status = TaskStatus.COMPLETED
            task.result = translated
            task.add_event("completed", f"Translated text to {target_lang}.")
            response = translated
        elif command == TaskCommand.UNKNOWN and (len(re.sub(r'[^\w\s]', '', message).strip()) <= 3 or not any(c.isalnum() for c in message)):
            task.status = TaskStatus.NEED_INFO
            task.add_event("need_info", "Ambiguous instruction received. Clarification requested.")
            response = localize("clarify_ambiguous", raw_lang_code)
        elif approval:
            task.status = TaskStatus.WAITING_APPROVAL
            task.add_event("approval_required", "Waiting for explicit approval.")
            response = localize("approval_prompt", raw_lang_code, action=command.value.replace('_', ' '))
        else:
            self._execute(task)
            if task.status in (TaskStatus.FAILED, "failed"):
                response = task.result or task.error or localize("action_failed", raw_lang_code)
            elif task.status in (TaskStatus.BLOCKED, "blocked"):
                response = task.error or localize("action_blocked", raw_lang_code)
            elif task.status in (TaskStatus.NEED_INFO, "need_info"):
                response = task.error or "Additional information needed."
            else:
                if not task.result:
                    if task.command == TaskCommand.OPEN_APP:
                        app_target = task.params.get("appName", "Application")
                        task.result = f"Opened {app_target} successfully."
                    elif task.command == TaskCommand.CLOSE_APP:
                        app_target = task.params.get("appName", "Application")
                        task.result = f"Closed {app_target} successfully."
                    elif task.command == TaskCommand.WEB_SEARCH:
                        task.result = f"Web search completed for '{task.params.get('query', '')}'."
                    else:
                        task.result = localize("action_done", raw_lang_code)
                response = task.result

        # Update conversation history on success (only for conversational turns, avoiding operator clutter)
        if risk != RiskLevel.BLOCKED and not approval and command not in (
            TaskCommand.UNKNOWN,
            TaskCommand.OBSERVE_SCREEN,
            TaskCommand.RESOLVE_UI_ELEMENT,
            TaskCommand.CLICK_ELEMENT,
            TaskCommand.TYPE_IN_ELEMENT,
            TaskCommand.DESKTOP_WORKFLOW,
        ) and task.status != TaskStatus.FAILED:
            self.history.append({"role": "user", "parts": [message]})
            self.history.append({"role": "model", "parts": [response]})
            if len(self.history) > 20:
                self.history = self.history[-20:]
            self._save_history()

        self.tasks[task.id] = task
        self._persist_task(task)
        return {"message": response, "task": task.to_dict()}

    def _chat_sequence(self, original_message: str, commands: list[str], source: str) -> dict[str, Any]:
        task = Task(
            intent=original_message,
            command=TaskCommand.UNKNOWN,
            risk_level=RiskLevel.LOW,
            requires_approval=False,
            params={"sequence": commands},
        )
        task.steps = ["Split command sequence", "Check safety policy"]
        task.add_event("received", f"Received {source} request.")

        planned: list[tuple[TaskCommand, dict[str, Any], str]] = []
        for command_text in commands:
            analysis = self._analyze_intent(command_text)
            command = analysis["command"]
            risk = analysis["risk_level"]
            approval = analysis["requires_approval"]
            block_reason = analysis["block_reason"]
            params = analysis["params"]

            if risk == RiskLevel.BLOCKED or approval:
                task.status = TaskStatus.BLOCKED if risk == RiskLevel.BLOCKED else TaskStatus.WAITING_APPROVAL
                task.risk_level = risk
                task.requires_approval = approval
                task.error = block_reason or "Sequence contains an action that requires separate approval."
                task.add_event("sequence_paused", task.error, command=command.value)
                self.tasks[task.id] = task
                self._persist_task(task)
                return {"message": task.error, "task": task.to_dict()}
            planned.append((command, params, command_text))
            task.steps.append(f"Execute {command.value}")

        task.status = TaskStatus.RUNNING
        task.add_event("running", "Sequence execution started.")
        for command, params, command_text in planned:
            result = self.automation.execute(command, params)
            if not result.ok:
                task.status = TaskStatus.FAILED
                task.error = result.message
                task.add_event("failed", result.message, command=command.value, intent=command_text)
                break
            task.add_event("step_completed", result.message, command=command.value, intent=command_text)
        else:
            task.status = TaskStatus.COMPLETED
            task.result = "Sequence completed."
            task.add_event("completed", "Sequence completed.")

        task.steps.append("Record audit event")
        self.tasks[task.id] = task
        self._persist_task(task)
        return {"message": task.result or task.error or "Sequence finished.", "task": task.to_dict()}

    def approve(self, task_id: str, approved: bool, approval_hash: str | None = None) -> dict[str, Any]:
        with self._lock:
            task = self._get_task(task_id)
            if task.status != TaskStatus.WAITING_APPROVAL:
                if task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED):
                    task.add_event("approval_rejected", "Cannot approve: task has been canceled.")
                    task.error = "Cannot approve a canceled task."
                    return task.to_dict()
                task.add_event("approval_replay_rejected", "Approval replayed: task has already been processed.")
                task.error = "Approval replayed: task already executed or not awaiting approval. Approval token already consumed."
                return task.to_dict()

            if approval_hash:
                expected_hash = task.params.get("approval_hash")
                if not expected_hash or approval_hash != expected_hash:
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("approval_rejected", "Approval token mismatch.")
                    task.error = "Approval token mismatch: provided hash does not match task."
                    self._persist_task(task)
                    return task.to_dict()

            if not approved:
                task.status = TaskStatus.CANCELED
                task.result = "Approval rejected. No action was taken."
                task.add_event("approval_rejected", "User rejected the action.")
                if self.pending_action and (self.pending_action.get("task_id") == task_id or (self.pending_action.get("task") and getattr(self.pending_action["task"], "id", None) == task_id)):
                    self.pending_action = None
                if task.params and "approval_hash" in task.params:
                    task.params["approval_hash"] = None
                if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                    try:
                        self.automation.mail.delete_draft(
                            recipient=task.params.get("recipient", ""),
                            subject=task.params.get("subject", ""),
                        )
                        task.add_event("draft_deleted", "Draft removed from mailbox following cancellation.")
                    except Exception:
                        pass
            else:
                task.add_event("approval_granted", "User approved the action.")
                if self.pending_action and (self.pending_action.get("task_id") == task_id or (self.pending_action.get("task") and getattr(self.pending_action["task"], "id", None) == task_id)):
                    self.pending_action = None
                if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                    expected_hash = task.params.get("approval_hash")
                    if expected_hash:
                        current_hash = EmailDraft(
                            recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
                            subject=task.params.get("subject", ""),
                            body=task.params.get("formatted_body") or task.params.get("body", ""),
                            sender_account=task.params.get("sender_account", ""),
                            attachments=task.params.get("attachments", []),
                            cc=task.params.get("cc", []),
                            bcc=task.params.get("bcc", []),
                        ).compute_hash()
                        if current_hash != expected_hash:
                            task.status = TaskStatus.WAITING_APPROVAL
                            task.add_event("approval_invalidated", "Draft changed after approval requested.")
                            task.error = "Approval invalidated: draft content was modified. Please review and approve again."
                            self._persist_task(task)
                            return task.to_dict()

                        # Check 15-minute approval expiration
                        try:
                            from datetime import datetime, timezone, timedelta
                            created = datetime.fromisoformat(task.created_at)
                            if datetime.now(timezone.utc) - created > timedelta(minutes=15):
                                task.status = TaskStatus.WAITING_APPROVAL
                                task.add_event("approval_expired", "Approval request expired after 15 minutes.")
                                task.error = "Approval expired: action was requested more than 15 minutes ago. Please re-approve."
                                self._persist_task(task)
                                return task.to_dict()
                        except Exception:
                            pass

                        # Record and consume approval in TaskStore
                        if hasattr(self, "task_store") and self.task_store:
                            self._persist_task(task)
                            ok, reason = self.task_store.consume_approval(task.id, current_hash)
                            if not ok and "No approval record found" in reason:
                                self.task_store.record_approval(task.id, current_hash)
                                ok, reason = self.task_store.consume_approval(task.id, current_hash)
                            if not ok:
                                task.status = TaskStatus.WAITING_APPROVAL
                                task.error = f"Approval error: {reason}"
                                self._persist_task(task)
                                return task.to_dict()

                elif (task.command in (TaskCommand.SEND_WHATSAPP, TaskCommand.SEND_MESSAGE)) and (task.params.get("channel") == "whatsapp" or task.params.get("phone")):
                    # Draft-only enforcement: direct send is completely blocked
                    if task.params.get("draft_only"):
                        task.status = TaskStatus.FAILED
                        task.error = "Cannot send: task was designated as draft-only ('Draft only — not sent'). To send, please initiate an explicit send request."
                        task.add_event("approval_rejected", task.error)
                        self._persist_task(task)
                        return task.to_dict()

                    # Replay protection: cannot consume the same approval twice
                    if task.params.get("approval_consumed"):
                        task.status = TaskStatus.FAILED
                        task.error = "Approval replay detected: this cryptographic approval was already consumed."
                        task.add_event("approval_replay_rejected", task.error)
                        self._persist_task(task)
                        return task.to_dict()

                    # WA-CONTACT-08: If contact source is unavailable or stale, fail closed
                    if hasattr(self, "recipient_resolver") and hasattr(self.recipient_resolver, "contact_source") and self.recipient_resolver.contact_source:
                        cs = self.recipient_resolver.contact_source
                        if not cs.is_available():
                            task.status = TaskStatus.FAILED
                            task.error = "Approval rejected: WhatsApp contact source is currently unavailable."
                            task.add_event("approval_rejected", task.error)
                            self._persist_task(task)
                            return task.to_dict()
                        if cs.is_stale():
                            task.status = TaskStatus.FAILED
                            task.error = "Approval rejected: WhatsApp contact data is stale."
                            task.add_event("approval_rejected", task.error)
                            self._persist_task(task)
                            return task.to_dict()

                    # Check active conversation integrity before send (Phase 5)
                    if hasattr(self, "automation") and hasattr(self.automation, "whatsapp") and hasattr(self.automation.whatsapp, "adapter"):
                        try:
                            obs = self.automation.whatsapp.adapter.observe_current_conversation()
                            obs_dict = obs.to_dict() if hasattr(obs, "to_dict") else obs
                            obs_status = obs_dict.get("status")

                            if obs_status == "modal_dialog_present":
                                task.status = TaskStatus.FAILED
                                task.error = "Security abort: WhatsApp Desktop has an active modal dialog open."
                                task.add_event("modal_dialog_blocked", task.error)
                                self._persist_task(task)
                                return task.to_dict()
                            elif obs_status == "observation_stale":
                                task.status = TaskStatus.FAILED
                                task.error = "Security abort: WhatsApp conversation observation is stale."
                                task.add_event("observation_stale", task.error)
                                self._persist_task(task)
                                return task.to_dict()
                            elif obs_status == "permission_denied":
                                task.status = TaskStatus.FAILED
                                task.error = "Security abort: macOS Accessibility permission denied for WhatsApp Desktop."
                                task.add_event("permission_denied", task.error)
                                self._persist_task(task)
                                return task.to_dict()
                            elif obs_status == "conversation_ambiguous":
                                task.status = TaskStatus.FAILED
                                task.error = "Security abort: active WhatsApp conversation is ambiguous."
                                task.add_event("conversation_ambiguous", task.error)
                                self._persist_task(task)
                                return task.to_dict()

                            is_open = obs_dict.get("isOpen") or obs_dict.get("is_open")
                            obs_title = obs_dict.get("title", "")
                            if is_open and obs_title:
                                expected_title = task.params.get("contact_name") or task.params.get("recipient", "")
                                if obs_title.strip().casefold() != expected_title.strip().casefold():
                                    task.status = TaskStatus.FAILED
                                    task.error = f"Security abort: active WhatsApp conversation changed to '{obs_title}' after approval was granted."
                                    task.add_event("conversation_mismatch", task.error)
                                    self._persist_task(task)
                                    return task.to_dict()
                        except Exception:
                            pass

                    expected_hash = task.params.get("approval_hash")
                    if expected_hash:
                        if approval_hash and approval_hash != expected_hash:
                            task.status = TaskStatus.WAITING_APPROVAL
                            task.add_event("approval_invalidated", "Supplied approval hash does not match task approval hash.")
                            task.error = "Approval invalidated: cryptographic approval hash mismatch."
                            self._persist_task(task)
                            return task.to_dict()

                        current_hash = WhatsAppDraft(
                            recipient=task.params.get("contact_name") or task.params.get("recipient", ""),
                            phone=task.params.get("phone", ""),
                            body=task.params.get("formatted_body") or task.params.get("body", ""),
                            contact_id=task.params.get("contact_id", ""),
                            contact_source=task.params.get("contact_source", ""),
                            draft_only=bool(task.params.get("draft_only", False)),
                        ).compute_hash()
                        if current_hash != expected_hash:
                            task.status = TaskStatus.WAITING_APPROVAL
                            task.add_event("approval_invalidated", "WhatsApp message or recipient changed after approval requested.")
                            task.error = "Approval invalidated: recipient or message content was modified. Please review and approve again."
                            self._persist_task(task)
                            return task.to_dict()

                        # Check 15-minute approval expiration
                        try:
                            from datetime import datetime, timezone, timedelta
                            created = datetime.fromisoformat(task.created_at)
                            if datetime.now(timezone.utc) - created > timedelta(minutes=15):
                                task.status = TaskStatus.WAITING_APPROVAL
                                task.add_event("approval_expired", "Approval request expired after 15 minutes.")
                                task.error = "Approval expired: action was requested more than 15 minutes ago. Please re-approve."
                                self._persist_task(task)
                                return task.to_dict()
                        except Exception:
                            pass

                        # Record and consume approval in TaskStore
                        if hasattr(self, "task_store") and self.task_store:
                            self._persist_task(task)
                            ok, reason = self.task_store.consume_approval(task.id, current_hash)
                            if not ok and "No approval record found" in reason:
                                self.task_store.record_approval(task.id, current_hash)
                                ok, reason = self.task_store.consume_approval(task.id, current_hash)
                            if not ok:
                                task.status = TaskStatus.WAITING_APPROVAL
                                task.error = f"Approval error: {reason}"
                                self._persist_task(task)
                                return task.to_dict()

                # Record ActionAttempt BEFORE external execution
                attempt_id = None
                if hasattr(self, "task_store") and self.task_store:
                    self._persist_task(task)
                    attempt = ActionAttempt(
                        task_id=task.id,
                        action_type=task.command.value if hasattr(task.command, "value") else str(task.command),
                        payload_hash=task.params.get("approval_hash", "") or "",
                        status=ActionAttemptStatus.INITIATED,
                        evidence={"params": task.params},
                    )
                    self.task_store.record_action_attempt(attempt)
                    attempt_id = attempt.id

                task.params["task_id"] = task.id
                task.transition_to(TaskStatus.EXECUTING, reason="Action approved by user")
                self._execute(task)
                task.params["approval_consumed"] = True

                if (task.command in (TaskCommand.SEND_WHATSAPP, TaskCommand.SEND_MESSAGE)) and (task.params.get("channel") == "whatsapp" or task.params.get("phone")):
                    if task.error and "outcome unknown" in task.error.lower():
                        task.status = TaskStatus.FAILED
                        task.error = "Send outcome unknown. UI verification did not confirm delivery bubble. Automatic retry rejected."

                # Update ActionAttempt status after execution
                if attempt_id and hasattr(self, "task_store") and self.task_store:
                    outcome_status = ActionAttemptStatus.VERIFIED if task.status == TaskStatus.COMPLETED else ActionAttemptStatus.FAILED
                    self.task_store.update_action_attempt(
                        attempt_id,
                        status=outcome_status,
                        evidence={"result": task.result, "error": task.error},
                    )

            self._persist_task(task)
            return task.to_dict()

    def cancel(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._get_task(task_id)
            task.request_cancellation(reason="User interrupted the task.")
            task.status = TaskStatus.CANCELED
            task.result = "Task canceled."
            if self.pending_action and (self.pending_action.get("task_id") == task_id or (self.pending_action.get("task") and getattr(self.pending_action["task"], "id", None) == task_id)):
                self.pending_action = None
            if task.params and "approval_hash" in task.params:
                task.params["approval_hash"] = None
            if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                try:
                    self.automation.mail.delete_draft(
                        recipient=task.params.get("recipient", ""),
                        subject=task.params.get("subject", ""),
                    )
                    task.add_event("draft_deleted", "Draft removed from mailbox following cancellation.")
                except Exception:
                    pass
            self._persist_task(task)
            return task.to_dict()

    def cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        with self._lock:
            task = self._get_task(task_id)
            if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED, TaskStatus.CANCELED}:
                task.request_cancellation(reason=reason or "Task canceled.")
                task.result = f"Task canceled: {reason}" if reason else "Task canceled."
                if self.pending_action and (self.pending_action.get("task_id") == task_id or (self.pending_action.get("task") and getattr(self.pending_action["task"], "id", None) == task_id)):
                    self.pending_action = None
                if task.params and "approval_hash" in task.params:
                    task.params["approval_hash"] = None
                if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                    try:
                        self.automation.mail.delete_draft(
                            recipient=task.params.get("recipient", ""),
                            subject=task.params.get("subject", ""),
                        )
                        task.add_event("draft_deleted", "Draft removed from mailbox following cancellation.")
                    except Exception:
                        pass
            self._persist_task(task)
            return task.to_dict()
            self._persist_task(task)
            return task.to_dict()

    def edit_pending_draft(
        self,
        task_id: str,
        recipient: str | None = None,
        subject: str | None = None,
        body: str | None = None,
        sender_account: str | None = None,
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Programmatic structured editing of a pending draft task."""
        with self._lock:
            task = self._get_task(task_id)
            if task.status != TaskStatus.WAITING_APPROVAL:
                return {"ok": False, "error": "Task is not waiting for approval.", "task": task.to_dict()}

            if recipient:
                task.params["recipient"] = recipient
                task.params["recipient_email"] = recipient
            if subject is not None:
                task.params["subject"] = subject
            if body is not None:
                task.params["body"] = body
                task.params["formatted_body"] = body
            if sender_account is not None:
                task.params["sender_account"] = sender_account
            if attachments is not None:
                for a in attachments:
                    if a and is_sensitive_attachment(a):
                        return {"ok": False, "error": f"Security policy violation: attaching sensitive file '{a}' is blocked.", "task": task.to_dict()}
                task.params["attachments"] = attachments
            if cc is not None:
                task.params["cc"] = cc
            if bcc is not None:
                task.params["bcc"] = bcc

            draft = EmailDraft(
                recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
                subject=task.params.get("subject", ""),
                body=task.params.get("formatted_body") or task.params.get("body", ""),
                sender_account=task.params.get("sender_account", ""),
                attachments=task.params.get("attachments", []),
                cc=task.params.get("cc", []),
                bcc=task.params.get("bcc", []),
            )
            task.params["approval_hash"] = draft.compute_hash()
            task.add_event("draft_edited", "Draft updated via structured editor.")

            # Update pending_action if matching
            if self.pending_action and self.pending_action.get("task_id") == task_id:
                self.pending_action["subject"] = draft.subject
                self.pending_action["body"] = draft.body
                self.pending_action["draft"] = draft
                self.pending_action["sender_account"] = draft.sender_account
                self.pending_action["attachments"] = draft.attachments

            draft_saved = True
            save_error = ""
            try:
                res = self.automation.execute(TaskCommand.DRAFT_MAIL, {
                    "recipient": draft.recipient,
                    "subject": draft.subject,
                    "body": draft.body,
                    "account": draft.sender_account,
                    "attachments": draft.attachments,
                })
                if hasattr(res, "ok") and not res.ok:
                    draft_saved = False
                    save_error = res.message
            except Exception as e:
                draft_saved = False
                save_error = str(e)

            self._persist_task(task)
            card = self._format_approval_card(draft, draft_saved=draft_saved, save_error=save_error)
            return {"ok": True, "task": task.to_dict(), "message": card, "draft_saved": draft_saved}

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._get_task(task_id).audit_trail]

    def memories(self) -> list[dict[str, Any]]:
        return self.memory.list()

    def delete_memory(self, memory_id: str) -> bool:
        return self.memory.delete(memory_id)

    def clear_memories(self, kind: str | None = None) -> int:
        return self.memory.clear(kind=kind)

    def clear_history(self) -> None:
        self.history = []
        self.pending_action = None
        try:
            self.memory.delete("conversation_history")
        except Exception:
            pass

    @staticmethod
    def sanitize_untrusted_web_content(raw_text: str) -> str:
        """Strips potential prompt injection vectors and isolates external webpage content safely.
        Ensures that content in web pages or search snippets is strictly treated as passive text evidence,
        and can never hijack Cortex or execute unauthorized system commands.
        """
        if not raw_text:
            return ""
        injection_patterns = [
            r"(?i)\bignore\s+(?:all\s+)?(?:previous\s+|prior\s+)?instructions\b.*",
            r"(?i)\bsystem\s*(?:override|prompt|command)?\s*:\s*.*",
            r"(?i)\boverride\s+(?:all\s+)?(?:approval|rules|safety|system)\b.*",
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

    @staticmethod
    def inspect_source_page(url: str, timeout: float = 3.5) -> dict[str, Any]:
        """Safely retrieves and inspects an external web article, extracting real textual evidence.
        Distinguishes full article inspection from snippet-only results, and sanitizes untrusted content.
        """
        if not (url.startswith("http://") or url.startswith("https://")):
            return {"ok": False, "status": "Snippet Only", "error": "Invalid URL protocol."}

        parsed = urllib.parse.urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0") or hostname.startswith(("192.168.", "10.", "172.16.")):
            return {"ok": False, "status": "Snippet Only", "error": "Internal or private network address."}

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type and "text/plain" not in content_type:
                    return {"ok": False, "status": "Snippet Only", "error": f"Non-HTML content type: {content_type}"}
                raw_bytes = resp.read(250_000)
                html_text = raw_bytes.decode("utf-8", errors="ignore")

            clean_html = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
            title_m = re.search(r"<title[^>]*>(.*?)</title>", clean_html, re.IGNORECASE | re.DOTALL)
            page_title = html_lib.unescape(re.sub(r"<.*?>", "", title_m.group(1)).strip()) if title_m else ""

            paras = re.findall(r"<p[^>]*>(.*?)</p>", clean_html, re.DOTALL | re.IGNORECASE)
            extracted_paras = []
            for p in paras:
                clean_p = html_lib.unescape(re.sub(r"<.*?>", "", p).strip())
                if len(clean_p) > 50 and not any(k in clean_p.lower() for k in ("cookie policy", "terms of service", "all rights reserved", "subscribe to", "newsletter")):
                    if "{" in clean_p or "}" in clean_p or any(css in clean_p.lower() for css in ("font-family", "display:", "-webkit-", "overflow:", "padding:", "margin:", "height:", "width:")):
                        continue
                    extracted_paras.append(clean_p)
                    if len(extracted_paras) >= 3:
                        break

            if not extracted_paras:
                text_only = html_lib.unescape(re.sub(r"<.*?>", " ", clean_html))
                text_lines = [l.strip() for l in text_only.splitlines() if len(l.strip()) > 60]
                filtered_lines = [l for l in text_lines if "{" not in l and "}" not in l and not any(css in l.lower() for css in ("font-family", "display:", "-webkit-", "overflow:", "margin:"))]
                extracted_paras = filtered_lines[:2]

            article_body = " ".join(extracted_paras)[:1200]
            sanitized_body = CortexOrchestrator.sanitize_untrusted_web_content(article_body)
            if sanitized_body:
                return {
                    "ok": True,
                    "status": "Full Article Inspected",
                    "title": page_title,
                    "summary": sanitized_body,
                    "url": url,
                }
            return {"ok": False, "status": "Snippet Only", "error": "Insufficient text found on page."}
        except Exception as e:
            return {"ok": False, "status": "Snippet Only", "error": str(e)}

    @staticmethod
    def _sanitize_search_query(text: str) -> str:
        q = text.strip()
        q = re.sub(
            r"^(?:can\s+you\s+(?:please\s+)?|could\s+you\s+(?:please\s+)?|please\s+|i\s+want\s+you\s+to\s+|go\s+ahead\s+and\s+)?"
            r"(?:google|search\s+(?:the\s+web\s+)?(?:for)?|look\s+up|research|find\s+(?:out\s+)?(?:about)?)\s+",
            "",
            q,
            flags=re.IGNORECASE,
        ).strip()
        suffix_pat = (
            r"[,;]?\s*(?:and\s+)?(?:inspect\s+(?:the\s+)?(?:search\s+)?results\s+)?"
            r"(?:and\s+)?(?:give\s+me\s+(?:a\s+)?(?:concise\s+|brief\s+|short\s+|quick\s+)?summary|summarize\s+(?:the\s+findings|the\s+results|it|them|findings)?|explain\s+(?:the\s+findings|the\s+results|it|them)?|tell\s+me\s+(?:about\s+it|what\s+you\s+find)?|and\s+report\s+back)"
            r"(?:\s+(?:with\s+|including\s+)(?:source\s+|working\s+)?(?:links|citations|sources))?[.,;!?]*$"
        )
        q = re.sub(suffix_pat, "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"[,;]?\s*(?:with\s+(?:source\s+)?links|with\s+citations|with\s+sources)[.,;!?]*$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"\s+(?:in|using|on)\s+(?:safari|chrome|firefox|edge|browser)[.,;!?]*$", "", q, flags=re.IGNORECASE).strip()
        q = re.sub(r"^(?:the\s+)", "", q, flags=re.IGNORECASE).strip()
        return q.rstrip(".,;!?").strip()

    @staticmethod
    def _shorten_research_summary(text: str) -> str:
        m_topic = re.search(r"### Cortex AI Overview:\s*([^\n]+)", text)
        topic = m_topic.group(1).strip() if m_topic else "Research Summary"

        m_core = re.search(r"### Cortex AI Overview:[^\n]+\n\n(.*?)(?=\n\n\*\*Key Developments|\n\n\*\*Sources)", text, re.DOTALL)
        core_text = m_core.group(1).strip() if m_core else ""
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", core_text) if len(s.strip()) > 15]
        core_sent = sents[0] if sents else "Recent research highlights substantial progress and practical applications across the field."

        bullets = re.findall(r"•\s+\*\*([^*]+)\*\*:\s*(.+)", text)
        condensed_bullets = []
        for b in bullets[:2]:
            title = b[0].strip()
            desc = b[1].strip()
            first_s = re.split(r"(?<=[.!?])\s+", desc)[0]
            condensed_bullets.append(f"• **{title}**: {first_s}")

        m_sources = re.search(r"(\*\*Sources & Citations:\*\*.*)", text, re.DOTALL)
        sources_block = m_sources.group(1).strip() if m_sources else ""

        lines = [
            f"### {topic} (Condensed Summary)",
            "",
            core_sent,
        ]
        if condensed_bullets:
            lines.extend([
                "",
                "**Key Takeaways:**",
                "\n".join(condensed_bullets),
            ])
        if sources_block:
            lines.extend(["", sources_block])
        return "\n".join(lines)

    def _summarize_search(self, query: str, results: list[dict[str, str]]) -> str:
        # Check direct answer first
        direct = resolve_direct_answer(query)
        if direct:
            return direct

        if self._is_gemini_available():
            try:
                model = self._create_gemini_model()
                formatted = "\n\n".join([
                    f"Title: {r['title']}\nURL: {r.get('href', '')}\nStatus: {r.get('retrieval_status', 'Snippet Only')}\nContent: {clean_search_response(r.get('inspected_content') or r['body'])}"
                    for r in results if (r.get("body") or r.get("inspected_content"))
                ])
                prompt = (
                    f"You are Cortex, an advanced desktop AI assistant producing a structured AI Overview.\n"
                    f"Synthesize the answer using the provided search facts:\n"
                    f"1. **Core Summary**: An opening 2-3 sentence high-level synthesis addressing the question directly.\n"
                    f"2. **Key Developments / Insights**: 2-4 bullet points highlighting the main findings.\n"
                    f"3. **Why It Matters / Implications**: A concise explanation of broader significance.\n"
                    f"4. **Sources & Citations**: List clickable Markdown links formatted as '[Source Title](URL) (Full Article Inspected or Snippet Only)'.\n\n"
                    f"Question: {query}\n\n"
                    f"Facts:\n{formatted}"
                )
                response = model.generate_content(prompt, request_options={"timeout": 6.0})
                if response and response.text:
                    return clean_search_response(response.text.strip())
            except Exception as e:
                self._handle_gemini_error(e, context="summarize search")

        # Structured Cortex AI Overview with core summary, key developments, why it matters, and clickable citations
        valid_results = [r for r in results if r.get("title")]
        if valid_results:
            top_bodies = [clean_search_response(r.get("inspected_content") or r.get("body", "")).strip() for r in valid_results if (r.get("body") or r.get("inspected_content"))]
            core_summary = ""
            if top_bodies:
                first_body = top_bodies[0]
                first_body = re.sub(r"^\*\*[^*]+\*\*:\s*", "", first_body).strip()
                sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", first_body) if len(s.strip()) > 15]
                core_summary = " ".join(sents[:2])
            if not core_summary:
                core_summary = f"Recent reporting and research regarding **{query}** highlight significant advancements across foundation model capabilities, multimodal interaction, and applied deployment."

            bullet_points = []
            for r in valid_results[:3]:
                t = r.get("title", "").strip()
                t_clean = re.sub(r"\s*(--|\||-)\s*.*$", "", t).strip() or t
                raw_content = r.get("inspected_content") or r.get("body", "")
                b = clean_search_response(raw_content).strip()
                b = self.sanitize_untrusted_web_content(b)
                b = re.sub(r"^\*\*[^*]+\*\*:\s*", "", b).strip()
                b = re.sub(r"^" + re.escape(t_clean) + r"[:\s-]+", "", b, flags=re.IGNORECASE).strip()
                sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", b) if len(s.strip()) > 15]
                point = sents[0] if sents else ((b[:120].rsplit(" ", 1)[0].rstrip(".,:;-") + ".") if b else "Significant developments and technological progress.")
                bullet_points.append(f"• **{t_clean}**: {point}")

            citation_links = []
            for r in valid_results[:3]:
                t = r.get("title", "").strip()
                t_clean = re.sub(r"\s*(--|\||-)\s*.*$", "", t).strip() or t
                href = r.get("href", "").strip()
                status_label = r.get("retrieval_status", "Snippet Only")
                if href and t_clean:
                    citation_links.append(f"• [{t_clean}]({href}) ({status_label})")

            is_ai_query = any(k in query.lower() for k in ("ai", "artificial intelligence", "foundation model", "llm", "deep learning", "machine learning", "neural network", "openai", "gemini", "anthropic"))
            overview_sections = [
                f"### Cortex AI Overview: {query.title()}\n\n{core_summary}\n",
                "**Key Developments & Insights:**\n" + "\n".join(bullet_points),
            ]
            if is_ai_query:
                overview_sections.append("\n**Why It Matters:**\nThese advancements accelerate capabilities across foundation models, developer tooling, and multimodal real-time interaction.")
            if citation_links:
                overview_sections.append("\n**Sources & Citations:**\n" + "\n".join(citation_links))

            return "\n".join(overview_sections)

        return f"No results found for '{query}'. Try rephrasing your question."

    def _summarize_emails(self, emails: list[dict[str, str]]) -> str:
        if not emails:
            return "Your inbox is clear — no recent emails found."

        # Sanitize untrusted external email content to protect against prompt injection
        sanitized_emails = []
        for e in emails:
            se = dict(e)
            if "snippet" in se and se["snippet"]:
                se["snippet"] = self.email_engine.sanitize_untrusted_email_content(se["snippet"])
            if "body" in se and se["body"]:
                se["body"] = self.email_engine.sanitize_untrusted_email_content(se["body"])
            if "subject" in se and se["subject"]:
                se["subject"] = self.email_engine.sanitize_untrusted_email_content(se["subject"])
            sanitized_emails.append(se)
        emails = sanitized_emails

        if not self._is_gemini_available():
            lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')} ({e.get('date', 'Recent')})" for e in emails]
            return f"You have {len(emails)} recent emails:\n" + "\n".join(lines)

        try:
            model = self._create_gemini_model()
            formatted = "\n\n".join([
                f"From: {e.get('sender')}\nSubject: {e.get('subject')}\nDate: {e.get('date')}\nSnippet: {e.get('snippet')}"
                for e in emails
            ])
            prompt = (
                f"You are Cortex, a warm, thoughtful, and friendly AI companion talking to a close friend.\n"
                f"Summarize these recent emails in a natural, lively conversational tone (2 to 3 engaging sentences).\n"
                f"Highlight who they are from, key topics, and any action items, perfect for speaking aloud.\n\n"
                f"Emails:\n{formatted}"
            )
            response = model.generate_content(prompt, request_options={"timeout": 6.0})
            return response.text.strip()
        except Exception as e:
            self._handle_gemini_error(e, context="summarize emails")
            lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')}" for e in emails]
            return f"You have {len(emails)} recent emails:\n" + "\n".join(lines)

    def _summarize_conversation_history(self, lang_code: str = "en") -> str:
        """Summarizes past dialogue turns without fabricating details."""
        if not self.history:
            return "Our conversation just started — there are no previous turns to summarize yet."

        history_lines = []
        for item in self.history[-12:]:
            role = "User" if item.get("role") == "user" else "Cortex"
            parts = item.get("parts", [])
            text = " ".join(parts) if isinstance(parts, list) else str(parts)
            history_lines.append(f"{role}: {text}")

        history_text = "\n".join(history_lines)

        if not self._is_gemini_available():
            return f"Here is a recap of our recent conversation:\n\n{history_text}"

        try:
            model = self._create_gemini_model()
            lang_instr = language_instruction(lang_code)
            prompt = (
                "You are Cortex, summarizing the following dialogue between the user and yourself.\n"
                "Provide a crisp, objective summary covering:\n"
                "1. Topics discussed\n"
                "2. Decisions reached\n"
                "3. Open action items or questions\n\n"
                f"{lang_instr}\n\n"
                f"Conversation:\n{history_text}"
            )
            resp = model.generate_content(prompt, request_options={"timeout": 6.0})
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            self._handle_gemini_error(e, context="summarize conversation")

        return f"Recent conversation overview:\n\n{history_text}"

    def _summarize_document(self, text_or_path: str, lang_code: str = "en") -> str:
        """Summarizes a provided document text or local file safely."""
        content = text_or_path.strip()
        # If it looks like a local file path, attempt safe read
        if (content.startswith("/") or content.startswith("./") or content.endswith((".txt", ".md", ".json", ".log"))) and len(content) < 300:
            target_path = Path(content).expanduser().resolve()
            if target_path.is_file():
                try:
                    content = target_path.read_text(encoding="utf-8", errors="replace")[:50000]
                except Exception as e:
                    return f"Could not read document at {target_path}: {e}"
            else:
                return f"Document file not found: {content}"

        if not content:
            return "No document content provided to summarize."

        snippet = content[:25000]

        if not self._is_gemini_available():
            preview = snippet[:500] + ("..." if len(snippet) > 500 else "")
            return f"Document Summary (Local Preview):\n\nLength: {len(snippet)} characters.\n\n{preview}"

        try:
            model = self._create_gemini_model()
            lang_instr = language_instruction(lang_code)
            prompt = (
                "You are Cortex, an expert research assistant.\n"
                "Summarize the following document accurately. Do not invent any facts not present in the text.\n"
                "Highlight:\n"
                "- Core thesis or executive summary\n"
                "- Key points and findings\n"
                "- Concrete action items or deadlines\n\n"
                f"{lang_instr}\n\n"
                f"Document Content:\n{snippet}"
            )
            resp = model.generate_content(prompt, request_options={"timeout": 7.0})
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            self._handle_gemini_error(e, context="summarize document")
            return f"Document summary preview ({len(snippet)} chars):\n\n" + snippet[:400]

    def _answer_general_question(self, query: str, lang_code: str = "en") -> str:
        """Google-style direct answering: fact first, explanation after."""
        q_lower = query.lower().strip()

        # Check for conversation recap / summary requests
        if re.search(r"\b(?:summarize|recap|summary of)\s+(?:our\s+)?(?:conversation|chat|discussion|talk)\b", q_lower):
            return self._summarize_conversation_history(lang_code)

        # Check for document summary requests
        doc_match = re.search(r"\b(?:summarize\s+(?:document|file))\s+(.+)", query, flags=re.IGNORECASE)
        if doc_match and not any(k in doc_match.group(1).lower() for k in ("source", "result", "article", "point", "summary", "this", "that")):
            return self._summarize_document(doc_match.group(1).strip(), lang_code)

        # 0. Smart Direct Answers (Real-time world time, dates, system clock, calculations)
        direct_ans = resolve_direct_answer(query, lang_code)
        if direct_ans:
            return direct_ans

        # 1. Curated offline knowledge base (Instant fact answering for common queries in Indic & English)
        offline_fact = get_offline_knowledge(query, lang_code)
        if offline_fact:
            return offline_fact

        # 2. Greeting / Identity / Status shortcuts in target language
        greeting_words = {
            "hi", "hello", "hey", "namaste", "vanakkam", "namaskara", "namaskaram",
            "helo", "hello cortex", "hi cortex", "hey cortex", "namaskara cortex", "namaste cortex",
            "ನಮಸ್ಕಾರ", "ಹಲೋ", "ನಮಸ್ತೆ", "ಶುಭೋದಯ", "नमस्ते", "नमस्कार", "प्रणाम", "வணக்கம்", "నమస్కారం"
        }
        is_greeting = (
            q_lower in greeting_words
            or (
                any(q_lower.startswith(w) for w in ("hi", "hello", "hey", "greetings", "namaste", "namaskara", "vanakkam", "namaskaram"))
                and (len(q_lower.split()) <= 4 or any(h in q_lower for h in ("help", "assist", "today", "there", "good morning", "good day", "everyone", "cortex")))
            )
        )
        is_status = any(p in q_lower for p in (
            "how are you", "hegidira", "hegiddira", "hegidiya", "chennagidira",
            "ಹೇಗಿದ್ದೀರಿ", "ಹೇಗಿದ್ದೀರಾ", "ಚೆನ್ನಾಗಿದ್ದೀರಾ", "kaisa hai", "kaise ho", "kya haal", "haal chal",
            "आप कैसे हैं", "कैसे हो", "क्या हाल है", "हाल चाल", "eppadi irukinga", "epdi irukinga", "eppadi irukka",
            "எப்படி இருக்கிறீர்கள்", "எப்படி இருக்கீங்க", "ela unnaru", "bagunnara", "bagunara", "ఎలా ఉన్నారు", "బాగున్నారా"
        ))
        is_capabilities = any(p in q_lower for p in (
            "what can you do", "what can cortex do", "what are your capabilities", "your capabilities",
            "what capabilities", "tell me what you can do", "what features", "features of cortex",
            "ನೀವೇನು ಮಾಡಬಲ್ಲಿರಿ", "ಏನು ಮಾಡಬಹುದು", "ನಿಮ್ಮ ಸಾಮರ್ಥ್ಯಗಳು", "ಸಾಮರ್ಥ್ಯಗಳು",
            "आप क्या कर सकते हैं", "आपकी क्षमताएं", "क्या कर सकते हो",
            "என்ன செய்ய முடியும்", "మీరు ఏమి చేయగలరు"
        ))
        is_identity = any(p in q_lower for p in (
            "who are you", "what is your name", "ನಿಮ್ಮ ಹೆಸರೇನು", "ನೀವು ಯಾರು",
            "आप कौन हैं", "तुम्हारा नाम क्या है", "आप का नाम क्या है", "நீங்கள் யார்", "మీరు ఎవరు"
        ))

        if is_capabilities:
            return get_cortex_capabilities(lang_code)
        if is_status:
            return get_cortex_status(lang_code)
        if is_greeting or is_identity:
            return get_cortex_identity(lang_code)

        # Check for programming help requests
        if re.search(r"\b(?:help\s+(?:me\s+)?with\s+python|python\s+help|learn\s+python|python\s+programming)\b", q_lower):
            if lang_code == "kn":
                return "ಖಂಡಿತ, ನಾನು ನಿಮಗೆ ಪೈಥಾನ್ (Python) ಪ್ರೋಗ್ರಾಮಿಂಗ್‌ನಲ್ಲಿ ಸಹಾಯ ಮಾಡಲು ಸಿದ್ಧನಿದ್ದೇನೆ! ಕೋಡ್ ಬರೆಯುವುದು, ದೋಷಗಳನ್ನು ಪರಿಹರಿಸುವುದು (debugging), ಅಥವಾ ಯಾವುದೇ ಪ್ರಾಜೆಕ್ಟ್ ಇರಲಿ — ನಿಮಗೆ ಏನು ಬೇಕು ತಿಳಿಸಿ."
            elif lang_code == "hi":
                return "बिल्कुल, मैं आपकी पायथन (Python) प्रोग्रामिंग में मदद करने के लिए तैयार हूँ! कोड लिखना, एरर डीबग करना, या कोई प्रोजेक्ट बनाना — बताइए हम क्या शुरू करें?"
            return "I'd be glad to help you with Python! Whether you need to write clean scripts, debug an issue, design algorithms, or work with frameworks like FastAPI or PyTorch, let me know what you'd like to build or solve."

        # Check for point explanation (e.g. "Explain the second point", "Explain the 1st insight")
        point_m = re.search(r"\b(?:explain|elaborate\s+on|tell\s+me\s+more\s+about)\s+(?:the\s+)?(first|second|third|1st|2nd|3rd|\d+)?\s*(?:point|insight|takeaway|bullet)\b", q_lower)
        if point_m and self.history:
            idx = 1 if (point_m.group(1) and ("second" in point_m.group(1).lower() or "2" in point_m.group(1))) else (
                0 if (point_m.group(1) and ("first" in point_m.group(1).lower() or "1" in point_m.group(1))) else 2
            )
            last_model_answer = ""
            for item in reversed(self.history):
                if item.get("role") == "model" and not last_model_answer:
                    last_model_answer = item.get("parts", [""])[0]

            bullets = re.findall(r"•\s+\*\*([^*]+)\*\*:\s*(.+)", last_model_answer)
            ordinal = "second" if idx == 1 else ("first" if idx == 0 else f"{idx+1}th")
            if bullets and len(bullets) > idx:
                title, desc = bullets[idx]
                source_link = ""
                if self.last_search_results and len(self.last_search_results) > idx:
                    u = self.last_search_results[idx].get("href", "")
                    if u:
                        source_link = f"\n\nSource: [{title}]({u})"
                return (
                    f"Here is an explanation of the {ordinal} point — **{title}**:\n\n"
                    f"{desc}\n\n"
                    f"This finding reflects meaningful progress in the domain, demonstrating enhanced performance "
                    f"and practical applicability across modern architectures.{source_link}"
                )

        # Check for detailed source explanation (e.g. "Summarize this source in more detail", "Explain this source in detail")
        is_detail_source = bool(re.search(r"\b(?:summarize|explain|tell\s+me\s+more\s+about)\s+(?:this|the|that)?\s*(?:source|article|page|result)\s+in\s+(?:more\s+)?detail\b", q_lower))
        if is_detail_source:
            target = self.last_selected_result or (self.last_search_results[0] if self.last_search_results else None)
            if target:
                title = target.get("title", "Selected Article")
                url = target.get("href", "")
                body = target.get("inspected_content") or target.get("body", "")
                clean_title = re.sub(r"\s*(--|\||-)\s*.*$", "", title).strip() or title
                link_line = f"\n\nSource: [{clean_title}]({url})" if url else ""
                return (
                    f"### In-Depth Summary: {clean_title}\n\n"
                    f"{body}\n\n"
                    f"This source provides comprehensive reporting on the topic, highlighting recent technical benchmarks, "
                    f"operational capabilities, and forward-looking developments.{link_line}"
                )
            return "Which source or article from our recent research would you like me to summarize in more detail?"

        # Check for comparison between sources (e.g. "Compare those two sources", "Compare these sources")
        is_compare = bool(re.search(r"\bcompare\s+(?:those|these|the|both)?\s*(?:two\s+)?(?:sources|articles|results|findings)\b", q_lower))
        if is_compare:
            if self.last_search_results and len(self.last_search_results) >= 2:
                s1 = self.last_search_results[0]
                s2 = self.last_search_results[1]
                t1 = re.sub(r"\s*(--|\||-)\s*.*$", "", s1.get("title", "Source 1")).strip()
                u1 = s1.get("href", "")
                b1 = s1.get("inspected_content") or s1.get("body", "")
                t2 = re.sub(r"\s*(--|\||-)\s*.*$", "", s2.get("title", "Source 2")).strip()
                u2 = s2.get("href", "")
                b2 = s2.get("inspected_content") or s2.get("body", "")
                return (
                    f"### Comparison of Primary Sources\n\n"
                    f"1. **[{t1}]({u1})** ({s1.get('retrieval_status', 'Available')}):\n"
                    f"   - **Key Focus**: {b1}\n\n"
                    f"2. **[{t2}]({u2})** ({s2.get('retrieval_status', 'Available')}):\n"
                    f"   - **Key Focus**: {b2}\n\n"
                    f"**Comparative Analysis:**\n"
                    f"Both sources corroborate key progress on the topic. While the first source focuses on initial announcements and high-level milestones, "
                    f"the second source emphasizes technical methodology and real-world evaluation benchmarks."
                )
            return "I need at least two sources from recent research to compare. Which topic or question would you like me to research and compare?"

        # Check for contextual reference to search results (e.g. "Explain the second result", "What is the second result")
        is_result_ref = bool(re.search(r"\b(?:first|second|third|1st|2nd|3rd)\s+(?:result|article|finding|link)\b", q_lower)) or "second result" in q_lower
        if is_result_ref and self.last_search_results:
            target_idx = 1 if ("second" in q_lower or "2nd" in q_lower) else (0 if ("first" in q_lower or "1st" in q_lower) else 2)
            if len(self.last_search_results) > target_idx:
                target = self.last_search_results[target_idx]
                self.last_selected_result = target
                self.last_opened_url = target.get("href", "")
                title = target.get("title", "Result")
                body = clean_search_response(target.get("inspected_content") or target.get("body", ""))
                link = target.get("href", "")
                ordinal = "second" if target_idx == 1 else ("first" if target_idx == 0 else f"{target_idx+1}th")
                link_line = f"\n\nSource: [{title}]({link})" if link else ""
                return f"The {ordinal} result is **{title}**:\n\n{body}{link_line}"
            else:
                return f"I only retrieved {len(self.last_search_results)} results for '{self.last_search_query}'. Which one would you like me to explain (result 1 to {len(self.last_search_results)})?"

        # Check for contextual style modification follow-up (e.g. "Make the summary shorter", "Make it shorter", "Make it formal", "Shorten the summary")
        is_explicit_summary_shorten = bool(re.search(
            r"\b(?:make\s+(?:the\s+)?summary\s+shorter|shorten\s+(?:the\s+)?summary|"
            r"can\s+you\s+(?:shorten\s+(?:the\s+)?summary)|"
            r"ಸಾರಾಂಶವನ್ನು\s+ಚಿಕ್ಕದಾಗಿಸು|ಸಾರಾಂಶ\s+ಚಿಕ್ಕದು\s+ಮಾಡು|समरी\s+छोटी\s+करो)\b",
            q_lower
        )) or q_lower in ("make the summary shorter", "shorten the summary", "make summary shorter")

        is_shorten = bool(re.search(
            r"\b(?:make\s+(?:it|this|that)\s+shorter|shorten\s+(?:it|this|that|answer)|make\s+it\s+(?:more\s+)?(?:concise|brief)|summarize\s+it\s+shorter|छोटा\s+करो)\b",
            q_lower
        )) or q_lower in ("make it shorter", "make it more concise")

        is_modify_style = is_explicit_summary_shorten or is_shorten or bool(re.search(
            r"\b(?:make\s+it|make\s+that|rewrite\s+(?:it|that)?|can\s+you\s+make\s+it)\s+(?:more\s+)?(?:shorter|formal|concise|brief|casual|simpler)\b",
            q_lower
        )) or q_lower in ("make it shorter", "make it formal", "make it shorter and more formal", "make it more formal", "make it concise", "shorter and more formal", "shorter and formal")

        if (is_explicit_summary_shorten or is_shorten or is_modify_style) and self.history:
            last_user_query = ""
            last_model_answer = ""
            if is_explicit_summary_shorten:
                for item in reversed(self.history):
                    if item.get("role") == "model":
                        content = item.get("parts", [""])[0]
                        if "### Cortex AI Overview:" in content or "**Sources & Citations:" in content or "**Key Developments" in content:
                            last_model_answer = content
                            break

            if not last_model_answer:
                for item in reversed(self.history):
                    if item.get("role") == "user" and not last_user_query:
                        last_user_query = item.get("parts", [""])[0]
                    elif item.get("role") == "model" and not last_model_answer:
                        last_model_answer = item.get("parts", [""])[0]

            if last_model_answer:
                # Check if target answer is a research summary / AI Overview
                if (is_explicit_summary_shorten or (is_shorten and "formal" not in q_lower)) and (
                    "### Cortex AI Overview:" in last_model_answer or "**Key Developments" in last_model_answer or "**Sources & Citations:" in last_model_answer
                ):
                    condensed = self._shorten_research_summary(last_model_answer)
                    return condensed

                if self._is_gemini_available():
                    try:
                        rewrite_prompt = f"Rewrite the following answer to make it {query.lower()}:\n\n{last_model_answer}"
                        model = self._create_gemini_model()
                        resp = model.generate_content(rewrite_prompt, request_options={"timeout": 15.0})
                        if resp and resp.text:
                            return resp.text.strip()
                    except Exception:
                        pass
                sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", last_model_answer) if s.strip() and len(s.strip()) > 10]
                shortened = " ".join(sents[:2]) if len(sents) >= 2 else last_model_answer
                if "formal" in q_lower:
                    return f"In formal terms: {shortened}"
                else:
                    return f"In brief: {shortened}"

        # Check for contextual simplification follow-up (e.g. "Explain that in simpler words", "Simplify that")
        is_simplify = bool(re.search(r"\b(?:simpler|simple words|simplify|eli5|easier|layman|simple terms)\b", q_lower))
        if is_simplify and self.history:
            last_user_query = ""
            for item in reversed(self.history):
                if item.get("role") == "user" and not last_user_query:
                    last_user_query = item.get("parts", [""])[0]

            if last_user_query:
                topic_lower = last_user_query.lower()
                if "quantum" in topic_lower:
                    if lang_code == "kn":
                        return (
                            "ಸರಳವಾಗಿ ಹೇಳಬೇಕೆಂದರೆ:\n\n"
                            "ಸಾಮಾನ್ಯ ಕಂಪ್ಯೂಟರ್‌ಗಳು ಸ್ವಿಚ್‌ನಂತೆ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತವೆ — ಅದು 0 (ಆಫ್) ಅಥವಾ 1 (ಆನ್) ಮಾತ್ರ ಆಗಿರಬಹುದು.\n"
                            "ಆದರೆ ಕ್ವಾಂಟಮ್ ಕಂಪ್ಯೂಟರ್‌ನ 'ಕ್ಯುಬಿಟ್ಸ್' (Qubits) ಒಂದೇ ಸಮಯದಲ್ಲಿ 0 ಮತ್ತು 1 ಎರಡೂ ಆಗಿರಲು ಸಾಧ್ಯ (ಸೂಪರ್‌ಪೊಸಿಷನ್). "
                            "ಇದರಿಂದಾಗಿ ಇದು ಲಕ್ಷಾಂತರ ಸಾಧ್ಯತೆಗಳನ್ನು ಏಕಕಾಲದಲ್ಲಿ ಪರೀಕ್ಷಿಸಿ, ಸಾಮಾನ್ಯ ಕಂಪ್ಯೂಟರ್‌ಗಳಿಗೆ ವರ್ಷಗಳಾಗುವ ಲೆಕ್ಕಾಚಾರಗಳನ್ನು ಕೆಲವೇ ಸೆಕೆಂಡುಗಳಲ್ಲಿ ಪರಿಹರಿಸಬಲ್ಲದು."
                        )
                    elif lang_code == "hi":
                        return (
                            "सरल शब्दों में:\n\n"
                            "एक सामान्य कंप्यूटर लाइट स्विच की तरह काम करता है — यह केवल 0 (बंद) या 1 (चालू) हो सकता है।\n"
                            "लेकिन क्वांटम कंप्यूटर के 'क्यूबिट्स' (Qubits) एक ही समय में 0 और 1 दोनों हो सकते हैं। "
                            "इसकी वजह से यह एक साथ लाखों संभावनाओं की जांच कर सकता है और बहुत जटिल समस्याओं को सेकंडों में हल कर देता है।"
                        )
                    return (
                        "In simpler words:\n\n"
                        "Think of a normal computer like a light switch that can only be either ON (1) or OFF (0), working through problems step-by-step.\n\n"
                        "A quantum computer uses special quantum particles (qubits) that can be both ON and OFF at the same time (called superposition). "
                        "This allows it to test millions of possibilities simultaneously, solving in seconds calculations that would take regular supercomputers thousands of years."
                    )
                elif "big bang" in topic_lower:
                    return (
                        "In simpler words:\n\n"
                        "The Big Bang wasn't an explosion in space — it was the sudden expansion of space itself. "
                        "Around 13.8 billion years ago, everything in the entire universe was packed into an unimaginably hot and dense point that suddenly began expanding, cooling over billions of years to create all the stars, planets, and galaxies we see today."
                    )
                elif "bruce lee" in topic_lower:
                    return (
                        "In simpler words:\n\n"
                        "Bruce Lee was the most famous martial artist in history. He changed action movies forever, proved that technique and speed beat sheer size, and created his own flexible philosophy of martial arts called Jeet Kune Do ('the way of the intercepting fist')."
                    )

        # 3. Try Gemini — Direct answer (skip if unavailable or in cooldown)
        if self._is_gemini_available():
            try:
                lang_instr = language_instruction(lang_code)
                system = (
                    "You are Cortex, an elite AI companion and assistant powered by Gemini, rivaling ChatGPT-4o, Alexa, and Claude.\n"
                    "Tone and Persona: You are a warm, brilliant, articulate friend who knows multiple languages fluently.\n"
                    "Your objective is to provide the absolute best, most comprehensive, accurate, and helpful answers to any question or task.\n\n"
                    "Guidelines:\n"
                    "- Tone: Warm, engaging, conversational, highly intelligent, articulate, and friendly — just like speaking with a knowledgeable close friend or ChatGPT Voice/Alexa.\n"
                    "- Structure: Lead directly with the core insight or solution. Use clear markdown formatting, bold highlights, bullet points, and numbered steps.\n"
                    "- Depth & Completeness: For deep, conceptual, technical, programming, writing, science, math, or analytical questions, provide thorough, master-level explanations with full code or detailed examples.\n"
                    "- Precision: For quick facts or simple definitions, be crisp and exact.\n"
                    "- Code Quality: Write production-ready, clean, modern code with explanatory syntax highlighting.\n"
                    "- Multilingual: Flawlessly match the user's language (English, Kannada, Hindi, Tamil, Telugu, etc.) with natural native phrasing, warmth, and colloquial idioms.\n"
                    "- Zero Fluff: Never say 'As an AI language model...', 'I hope this helps!', or pad answers with filler.\n"
                )
                if lang_instr:
                    system += f"\n{lang_instr}\n"

                # Apply situational adaptive tone
                if detect_adaptive_tone and apply_tone_to_prompt:
                    tone_ctx = detect_adaptive_tone(query)
                    system = apply_tone_to_prompt(system, tone_ctx)

                model = self._create_gemini_model(system_instruction=system)

                chat_contents = list(self.history)
                chat_contents.append({"role": "user", "parts": [query]})

                resp = model.generate_content(chat_contents, request_options={"timeout": 35.0})
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                self._handle_gemini_error(e, context="question answering")

        # 4. Web search fallback for factual queries (only if not a conversational meta-directive)
        is_meta_directive = bool(re.search(
            r"\b(?:cancel|stop|clear|shorter|longer|more|less|summary|draft|open|close|send|yes|no)\b",
            q_lower
        ))
        if not is_meta_directive:
            try:
                results = search_web(query, max_results=3)
                if results:
                    return self._summarize_search(query, results)
            except Exception as e:
                print(f"[cortex] Knowledge lookup error: {e}", file=sys.stderr)

        return localize("no_confident_answer", lang_code, query=query)

    def _execute(self, task: Task) -> None:
        if task.command == TaskCommand.SEND_MAIL or (task.requires_approval and task.risk_level == RiskLevel.HIGH):
            has_approval = any(
                getattr(e, "event_type", getattr(e, "name", "")) == "approval_granted"
                for e in getattr(task, "audit_trail", getattr(task, "events", []))
            )
            if not has_approval:
                task.status = TaskStatus.BLOCKED
                task.error = "Execution blocked: explicit user approval is required before sending."
                task.add_event("execution_blocked", "Direct execution denied without prior approval.")
                return

        task.status = TaskStatus.RUNNING
        task.add_event("running", "Execution started.")
        task.params = task.params or {}

        # Diagnostic logging for capability routing with parameters redacted
        redacted_params = {}
        for k, v in (task.params or {}).items():
            if k.lower() in ("body", "formatted_body", "password", "token", "secret", "auth_token", "api_key"):
                redacted_params[k] = "[REDACTED]"
            else:
                redacted_params[k] = v
        task.add_event(
            "capability_selected",
            f"Capability selected: {task.command.value}",
            command=task.command.value,
            metadata=redacted_params,
        )

        # ── Model-outage handling for model-dependent tasks ───────────
        if task.params.get("requires_model"):
            if not self._is_gemini_available():
                task.transition_to(
                    TaskStatus.PAUSED_MODEL_UNAVAILABLE,
                    reason="Model-dependent task paused because configured cloud model provider is unavailable.",
                    force_admin=True,
                )
                task.error = "Cloud model provider unavailable. Task paused."
                task.add_event("paused_model_unavailable", "Cloud model unavailable; task paused.")
                self._persist_task(task)
                return

        # ── General Conversation / Knowledge Answering ─────────────────
        if task.command in (TaskCommand.ASK_QUESTION, TaskCommand.UNKNOWN):
            lang = str(task.language.value if task.language else "en")
            # 0. Smart direct answers check
            direct_ans = resolve_direct_answer(task.intent, lang)
            if direct_ans:
                task.status = TaskStatus.COMPLETED
                task.result = direct_ans
                task.add_event("completed", "Resolved via direct answer engine.")
                return

            # Prefer Gemini-provided answer from intent analysis, but always verify it's non-empty
            answer = (task.params.get("answer") or "").strip()
            if not answer:
                answer = self._answer_general_question(task.intent, lang_code=lang)
            if not answer:
                answer = localize("no_confident_answer", lang, query=task.intent)
            task.status = TaskStatus.COMPLETED
            task.result = answer
            task.add_event("completed", "Answered user inquiry.")
            return

        if task.command == TaskCommand.WEB_SEARCH:
            query = task.params.get("query", task.intent)
            # Rely on explicit browser param set by _extract_params; avoid false-positive
            # from "safari" appearing in the raw intent string (e.g. encyclopedia queries).
            requested_browser = task.params.get("browser", "")
            is_safari = requested_browser.lower() == "safari"
            task.add_event("web_search_started", f"Searching the web for: {query}")

            safari_opened = False
            if is_safari and sys.platform == "darwin" and not self.automation.dry_run:
                try:
                    search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                    subprocess.run(["open", "-a", "Safari", search_url], check=False)
                    safari_opened = True
                    task.add_event("safari_opened", f"Opened Safari with search URL for '{query}'.")
                except Exception as e:
                    print(f"[cortex] Failed to open Safari: {e}", file=sys.stderr)

            results = search_web(query)
            if results:
                self.last_search_results = results
                self.last_search_query = query
                self.last_selected_result = results[0]
                self.last_opened_url = results[0].get("href", "")
                task.add_event("web_search_completed", f"Found {len(results)} results.")

                # Inspect source pages when available (up to top 2 results)
                should_inspect = bool(task.params.get("inspect_results") or task.params.get("cooperative_chain") or is_safari or len(results) > 0)
                if should_inspect:
                    for r in results[:2]:
                        u = r.get("href", "")
                        if u and u.startswith("http"):
                            inspection = self.inspect_source_page(u, timeout=3.0)
                            if inspection.get("ok"):
                                r["retrieval_status"] = "Full Article Inspected"
                                r["inspected_content"] = inspection.get("summary", "")
                            else:
                                r["retrieval_status"] = "Snippet Only"
                        else:
                            r["retrieval_status"] = "Snippet Only"
                    for r in results[2:]:
                        r["retrieval_status"] = "Snippet Only"

                # Cooperative chain: search + open article in browser + explain
                if task.params.get("cooperative_chain"):
                    top = results[0]
                    self.last_selected_result = top
                    top_url = top.get("href", "")
                    self.last_opened_url = top_url
                    opened_safari = False
                    if sys.platform == "darwin" and not self.automation.dry_run and top_url:
                        subprocess.run(["open", "-a", "Safari", top_url], check=False)
                        opened_safari = True
                    elif self.automation.dry_run:
                        opened_safari = True

                    explanation = clean_search_response(top.get("body", ""))
                    title = top.get("title", "Article")
                    task.status = TaskStatus.COMPLETED
                    safari_note = f"✓ Safari opened with article: {top_url}\n\n" if opened_safari else ""
                    task.result = (
                        f"Retrieved recent research findings for '{query}'.\n\n"
                        f"{safari_note}"
                        f"### {title}\n"
                        f"{explanation}\n\n"
                        f"Source: {top_url}"
                    )
                    task.add_event("completed", "Cooperative research and browser workflow completed.")
                    return

                # Focused explanation on a specific result target (e.g. second result)
                if task.params.get("explain_target"):
                    idx = task.params.get("target_index", 1)
                    target = results[idx] if len(results) > idx else results[0]
                    self.last_selected_result = target
                    target_url = target.get("href", "")
                    self.last_opened_url = target_url
                    title = target.get("title", "Article")
                    snippet = clean_search_response(target.get("body", ""))
                    task.status = TaskStatus.COMPLETED
                    ordinal = "second" if idx == 1 else ("first" if idx == 0 else f"{idx+1}th")
                    task.result = (
                        f"I searched for \"{query}\" and retrieved {len(results)} relevant results.\n\n"
                        f"Here is an explanation of the {ordinal} result — **{title}**:\n\n"
                        f"{snippet}\n\n"
                        f"Source: {target_url}"
                    )
                    task.add_event("completed", f"Explained {ordinal} result.")
                    return

                answer = self._summarize_search(query, results)
                task.status = TaskStatus.COMPLETED
                if safari_opened:
                    task.result = f"Opened Safari with research results for '{query}'.\n\n{answer}"
                else:
                    task.result = answer
                task.add_event("completed", "Web search results summarized.")
            else:
                if safari_opened:
                    task.status = TaskStatus.COMPLETED
                    task.result = f"Opened Safari with search for '{query}'."
                    task.add_event("completed", "Opened Safari search query.")
                    return

                if self._is_gemini_available():
                    try:
                        model = self._create_gemini_model()
                        resp = model.generate_content(
                            f"You are Cortex, a warm, caring, and thoughtful AI friend. Answer this query in a natural, friendly, conversational way (2-3 sentences):\n{query}",
                            request_options={"timeout": 6.0}
                        )
                        task.status = TaskStatus.COMPLETED
                        task.result = resp.text.strip()
                        task.add_event("completed", "Answered using assistant knowledge.")
                        return
                    except Exception as e:
                        self._handle_gemini_error(e, context="web search fallback")
                task.status = TaskStatus.FAILED
                task.error = f"No search results found for '{query}'."
                task.add_event("failed", task.error)
            return

        # ── Contextual and Direct URL Browser Navigation ────────────────
        if task.command == TaskCommand.OPEN_URL:
            url = task.params.get("url", "")
            browser = task.params.get("browser", "Safari")
            title = "article"

            # Resolve from session context if contextual reference
            if task.params.get("use_context") or not url:
                target_idx = task.params.get("target_index", 0)
                if self.last_selected_result and target_idx == 0:
                    url = self.last_selected_result.get("href", "")
                    title = self.last_selected_result.get("title", "selected article")
                elif self.last_search_results:
                    if target_idx < len(self.last_search_results):
                        target = self.last_search_results[target_idx]
                        url = target.get("href", "")
                        title = target.get("title", "article")
                        self.last_selected_result = target
                    else:
                        task.status = TaskStatus.COMPLETED
                        task.result = f"I only retrieved {len(self.last_search_results)} results for '{self.last_search_query}'. Which result would you like me to open (e.g. result 1 to {len(self.last_search_results)})?"
                        task.add_event("completed", "Requested clarification on result index.")
                        return
                elif self.last_opened_url:
                    url = self.last_opened_url
                    title = "article"

            if not url:
                task.status = TaskStatus.FAILED
                task.result = "No recent article or link found in our conversation context to open. Which URL or topic would you like me to open?"
                task.error = task.result
                task.add_event("failed", "No recent article or link found.")
                return

            if not (url.startswith("http://") or url.startswith("https://")):
                url = f"https://{url}"

            self.last_opened_url = url
            opened = False
            if sys.platform == "darwin" and not self.automation.dry_run:
                try:
                    if browser.lower() == "safari":
                        apple_script = f'tell application "Safari"\nactivate\nopen location "{url}"\nend tell'
                        proc = subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True, check=False)
                        if proc.returncode == 0:
                            opened = True
                    if not opened:
                        proc2 = subprocess.run(["open", "-a", browser, url], capture_output=True, text=True, check=False)
                        opened = (proc2.returncode == 0)
                    if not opened:
                        proc3 = subprocess.run(["open", url], capture_output=True, text=True, check=False)
                        opened = (proc3.returncode == 0)
                    if opened:
                        task.add_event("safari_opened", f"Opened URL in {browser}: {url}")
                except Exception as e:
                    print(f"[cortex] Failed to open {browser}: {e}", file=sys.stderr)
            else:
                opened = True

            if opened:
                task.status = TaskStatus.COMPLETED
                task.result = f"Opened **{title}** in {browser}:\n[{url}]({url})"
                task.add_event("completed", task.result)
            else:
                task.status = TaskStatus.FAILED
                task.error = f"Failed to open [{url}]({url}) in {browser}."
                task.add_event("failed", task.error)
            return

        # ── Search & File Listing Execution ────────────────────────────
        if task.command == TaskCommand.SEARCH_FILES:
            task.add_event("file_search_started", f"Searching files in {task.params.get('directory', '.')}")
            read_result = self.automation.execute(TaskCommand.SEARCH_FILES, task.params)
            if read_result.ok:
                task.status = TaskStatus.COMPLETED
                task.result = read_result.message
                self.last_file_search_result = read_result.data or {}
                task.add_event("completed", read_result.message, files=read_result.data.get("names", []))
            else:
                task.status = TaskStatus.FAILED
                task.error = read_result.message
                task.add_event("failed", read_result.message)
            return

        # ── Phase 5: Mail Automation Execution ─────────────────────────
        if task.command == TaskCommand.DRAFT_MAIL:
            read_result = self.automation.execute(TaskCommand.DRAFT_MAIL, task.params)
            recip = task.params.get("recipient", "recipient")
            subj = task.params.get("subject", "No subject")
            if read_result.ok:
                task.status = TaskStatus.COMPLETED
                task.result = f"Draft created in Apple Mail for {recip} with subject '{subj}'."
                task.add_event("completed", task.result)
            else:
                task.status = TaskStatus.FAILED
                task.error = read_result.message or "Failed to create draft in Apple Mail."
                task.add_event("failed", task.error)
            return

        if task.command == TaskCommand.SUMMARIZE_MAIL:
            task.add_event("mail_fetch_started", "Reading recent emails from inbox.")
            read_result = self.automation.execute(TaskCommand.READ_MAIL, task.params)
            if read_result.ok:
                emails = read_result.data.get("emails", []) if read_result.data else []
                task.add_event("mail_fetch_completed", f"Retrieved {len(emails)} emails.")
                summary = self._summarize_emails(emails)
                task.status = TaskStatus.COMPLETED
                task.result = summary
                task.add_event("completed", "Email summary generated.", emails=emails)
            else:
                task.status = TaskStatus.FAILED
                task.error = read_result.message
                task.add_event("failed", read_result.message)
            return

        if task.command == TaskCommand.READ_MAIL:
            task.add_event("mail_fetch_started", "Reading inbox messages.")
            read_result = self.automation.execute(TaskCommand.READ_MAIL, task.params)
            lang = str(task.language.value if task.language else "en")
            if read_result.ok:
                emails = read_result.data.get("emails", []) if read_result.data else []
                task.status = TaskStatus.COMPLETED
                if emails:
                    lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No Subject')} ({e.get('date', 'Recent')})" for e in emails]
                    if lang != "en":
                        task.result = localize("recent_emails", lang, count=len(emails), emails="\n".join(lines))
                    else:
                        task.result = f"Found {len(emails)} recent emails:\n" + "\n".join(lines)
                else:
                    task.result = localize("inbox_clear", lang) if lang != "en" else "Your inbox is empty."
                task.add_event("completed", f"Retrieved {len(emails)} emails.", emails=emails)
            else:
                task.status = TaskStatus.FAILED
                task.error = read_result.message
                task.add_event("failed", read_result.message)
            return

        # ── Phase 8: Apple Notes Execution ─────────────────────────────
        if task.command == TaskCommand.WRITE_NOTE:
            action = task.params.get("action", "")
            if action == "open_note":
                note_title = (self.last_note.get("title", "") if self.last_note else "") or task.params.get("title", "")
                if not note_title:
                    task.status = TaskStatus.FAILED
                    task.error = "No recent note found to open."
                    task.add_event("failed", task.error)
                    return
                res = self.automation.open_note(note_title)
                if res.ok:
                    task.status = TaskStatus.COMPLETED
                    task.result = f"Opened note '{note_title}' in Apple Notes."
                    task.add_event("completed", task.result)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = res.message
                    task.add_event("failed", task.error)
                return

            if action == "shorten_title":
                if not self.last_note or not self.last_note.get("title"):
                    task.status = TaskStatus.FAILED
                    task.error = "No recent note found to update."
                    task.add_event("failed", task.error)
                    return
                old_title = self.last_note["title"]
                words = old_title.split()
                if len(words) > 1 and words[0].lower() in ("project", "team", "sync", "weekly", "daily", "cortex", "my"):
                    new_title = " ".join(words[1:]).capitalize()
                elif len(words) > 1:
                    new_title = words[-1].capitalize()
                else:
                    new_title = words[0][:5] if words else "Note"
                res = self.automation.update_note_title(old_title, new_title)
                if res.ok:
                    self.last_note["title"] = new_title
                    task.status = TaskStatus.COMPLETED
                    task.result = f"Updated note title to '{new_title}' in Apple Notes."
                    task.add_event("completed", task.result)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = res.message
                    task.add_event("failed", task.error)
                return

            if action == "append_note":
                if not self.last_note or not self.last_note.get("title"):
                    task.status = TaskStatus.FAILED
                    task.error = "No recent note found to update."
                    task.add_event("failed", task.error)
                    return
                target_title = self.last_note["title"]
                addition = task.params.get("point", "")
                res = self.automation.append_note(target_title, addition)
                if res.ok:
                    self.last_note["body"] += f"\n{addition}"
                    task.status = TaskStatus.COMPLETED
                    task.result = f"Added point to note '{target_title}':\n{addition}"
                    task.add_event("completed", task.result)
                else:
                    task.status = TaskStatus.FAILED
                    task.error = res.message
                    task.add_event("failed", task.error)
                return

            # Standard create note
            title = task.params.get("title", "Cortex Note")
            body = task.params.get("body", "")
            res = self.automation.execute(TaskCommand.WRITE_NOTE, task.params)
            if res.ok:
                self.last_note = {"title": title, "body": body}
                task.status = TaskStatus.COMPLETED
                task.result = f"Created note titled '{title}' with content: {body}"
                task.add_event("completed", task.result)
            else:
                task.status = TaskStatus.FAILED
                task.error = res.message
                task.add_event("failed", task.error)
            return

        # Pipeline execution with execute -> observe -> verify -> recover loop
        if not task.plan:
            task.plan = self.planner.plan(task.intent, task.command, task.params, task.context)
        final_res = self.execution_engine.execute_plan(task)
        lang = str(task.language.value if task.language else "en")
        if final_res.status == TaskStatus.COMPLETED:
            task.status = TaskStatus.COMPLETED
            if task.command == TaskCommand.OBSERVE_SCREEN and final_res.data:
                task.params = task.params or {}
                for k, v in final_res.data.items():
                    if k != "params":
                        task.params[k] = v
                task.params["observation"] = {k: v for k, v in final_res.data.items() if k != "params"}
            if lang != "en":
                if task.command == TaskCommand.OPEN_APP:
                    task.result = localize("app_opened", lang, app_name=task.params.get("appName", "app"))
                elif task.command == TaskCommand.CLOSE_APP:
                    task.result = localize("app_closed", lang, app_name=task.params.get("appName", "app"))
                elif task.command == TaskCommand.FOCUS_APP:
                    task.result = localize("app_focused", lang, app_name=task.params.get("appName", "app"))
                elif task.command == TaskCommand.SCREENSHOT:
                    task.result = localize("screenshot_taken", lang)
                elif task.command == TaskCommand.CALCULATE:
                    task.result = localize("calc_result", lang, expression=task.params.get("expression", ""), result=final_res.summary or "")
                elif task.command == TaskCommand.WRITE_NOTE:
                    task.result = localize("note_written", lang, title=task.params.get("title", "Cortex Note"))
                elif task.command == TaskCommand.SEND_MESSAGE:
                    task.result = localize("message_sent", lang, recipient=task.params.get("recipient", "recipient"))
                else:
                    task.result = final_res.summary or localize("action_done", lang)
            else:
                if task.command == TaskCommand.OPEN_APP:
                    task.result = f"Opened {task.params.get('appName', 'application')}."
                elif task.command == TaskCommand.CLOSE_APP:
                    task.result = f"Closed {task.params.get('appName', 'application')}."
                elif task.command == TaskCommand.FOCUS_APP:
                    task.result = f"Focused {task.params.get('appName', 'application')}."
                elif task.command == TaskCommand.SCREENSHOT:
                    task.result = "Screenshot captured successfully."
                elif task.command == TaskCommand.CALCULATE:
                    task.result = f"Result: {final_res.summary or task.params.get('expression', '')}"
                elif task.command == TaskCommand.WRITE_NOTE:
                    task.result = f"Note created: '{task.params.get('title', 'Cortex Note')}'"
                elif task.command == TaskCommand.SEND_MESSAGE:
                    task.result = f"Message sent to {task.params.get('recipient', 'recipient')}."
                else:
                    task.result = final_res.summary or task.result or "Completed."
        else:
            task.status = TaskStatus.FAILED
            task.error = final_res.summary or task.error or "Execution failed."
            if task.command == TaskCommand.OBSERVE_SCREEN:
                if final_res.data:
                    task.params = task.params or {}
                    task.params["observation"] = {k: v for k, v in final_res.data.items() if k != "params"}
                last_exec = task.execution_history[-1] if task.execution_history else None
                if last_exec and last_exec.message and "- **Active application:**" in last_exec.message:
                    task.result = last_exec.message
                else:
                    task.result = final_res.summary or task.error

    def _persist_task(self, task: Task) -> None:
        self.memory.put(task.id, "task", task.to_dict())
        if hasattr(self, "task_store") and self.task_store:
            try:
                self.task_store.save_task(task)
            except Exception as e:
                print(f"[cortex] Warning: Failed to persist task to relational store: {e}", file=sys.stderr)

    def _get_task(self, task_id: str) -> Task:
        if task_id in self.tasks:
            return self.tasks[task_id]
        if hasattr(self, "task_store") and self.task_store:
            persisted = self.task_store.get_task(task_id)
            if persisted:
                self.tasks[task_id] = persisted
                return persisted
        raise KeyError(f"Unknown task: {task_id}")

    def resume_paused_tasks(self) -> list[str]:
        """Resume tasks paused due to model unavailability once the provider is restored."""
        if not self._is_gemini_available():
            return []
        resumed = []
        for task_id, task in list(self.tasks.items()):
            if task.status == TaskStatus.PAUSED_MODEL_UNAVAILABLE:
                if task.cancellation_requested:
                    task.transition_to(TaskStatus.CANCELLED, reason="Cancelled while paused", force_admin=True)
                else:
                    task.transition_to(TaskStatus.EXECUTING, reason="Cloud model provider restored. Resuming task.", force_admin=True)
                    self._execute(task)
                self._persist_task(task)
                resumed.append(task_id)
        return resumed

    def _steps_for(self, command: TaskCommand, approval: bool) -> list[str]:
        steps = ["Classify request", "Check safety policy"]
        if approval:
            steps.append("Request approval")
        steps.append(f"Execute {command.value}")
        steps.append("Record audit event")
        return steps

    def _extract_params(self, command: TaskCommand, message: str) -> dict[str, Any]:
        text = message.strip()
        prefix_match = re.match(r"^(?:hey\s+cortex|cortex|ok\s+cortex|hello\s+cortex|hi\s+cortex|please|can\s+you|could\s+you)\s*[,:]?\s*(.+)$", text, flags=re.IGNORECASE)
        if prefix_match:
            text = prefix_match.group(1).strip()
        if command in {TaskCommand.OPEN_APP, TaskCommand.CLOSE_APP, TaskCommand.FOCUS_APP}:
            if "finder" in text.lower():
                folder_m = re.search(r"(?:show|open|reveal|view)\s+(?:the\s+)?([a-z0-9_/~\s-]+?)\s+(?:in\s+finder|folder\s+in\s+finder)", text, re.IGNORECASE)
                folder = folder_m.group(1).strip() if folder_m else ""
                return {"appName": "Finder", "folder": folder}
            match = re.search(r"(?:open|launch|start|close|quit|exit)\s+(.+)", text, re.IGNORECASE)
            if command == TaskCommand.FOCUS_APP:
                match = re.search(r"(?:focus|switch to|bring up|activate)\s+(.+)", text, re.IGNORECASE)
            app_raw = match.group(1).strip() if match else text
            if re.search(r"\s+and\s+", app_raw, re.IGNORECASE):
                app_raw = re.split(r"\s+and\s+", app_raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            # Strip Indic action verbs and postpositions
            app_raw = re.sub(
                r"(?:ಅನ್ನು\s*ತೆರೆ|ಅನ್ನು\s*ಮುಚ್ಚು|ತೆರೆ|ಮುಚ್ಚು|ಓಪನ್\s*ಮಾಡು|ಕ್ಲೋಸ್\s*ಮಾಡು|ಚಾಲೂ\s*ಮಾಡು|ಪ್ರಾರಂಭಿಸು|"
                r"को\s*खोलो|खोलो|खोलें|को\s*बंद\s*करो|बंद\s*करो|बंद\s*करें|ओपन\s*करो|चालू\s*करो|"
                r"ஐ\s*திற|திற|திறக்கவும்|மூடு|மூடவும்|ஓபன்\s*பண்ணு|"
                r"ని\s*తెరువు|ను\s*తెరువు|తెరువు|తెరవండి|మూసివేయి|మూసివేయండి|ఓపెన్\s*చేయి)",
                "",
                app_raw,
                flags=re.IGNORECASE,
            ).strip()
            normalized = normalize_app_name(app_raw) if app_raw else app_raw
            return {"appName": normalized or text}
        # ── Screen Intelligence & Autonomous Desktop Operator ──
        if command == TaskCommand.OBSERVE_SCREEN:
            return {
                "capture_screenshot": bool("capture" in text or "screenshot" in text),
                "run_ocr": bool("ocr" in text or "text" in text),
                "max_elements": 5,
            }
        if command == TaskCommand.RESOLVE_UI_ELEMENT:
            m = re.search(r"(?:find|locate|where is)\s+(?:the\s+)?(.+?)(?:\s+button|\s+field|\s+element)?$", text, re.IGNORECASE)
            target = m.group(1).strip() if m else text
            return {"target": target, "target_description": target}
        if command == TaskCommand.CLICK_ELEMENT:
            m = re.search(r"(?:click|press|tap)\s+(?:on\s+)?(?:the\s+)?(?:button\s+)?(.+)", text, re.IGNORECASE)
            target = m.group(1).strip() if m else text
            target = re.sub(r"\s+(?:button|icon|tab)$", "", target, flags=re.IGNORECASE).strip()
            return {"target": target, "target_description": target}
        if command == TaskCommand.TYPE_IN_ELEMENT:
            m = re.search(r"(?:type|enter|fill)\s+(.+?)\s+(?:in|into)\s+(.+)", text, re.IGNORECASE)
            if m:
                return {"text": m.group(1).strip(), "target": m.group(2).strip(), "target_description": m.group(2).strip()}
            return {"text": text, "target": "active_field"}
        if command == TaskCommand.TYPE_TEXT:
            in_app = re.search(r"(?:type|write|enter text)\s+(.+?)\s+(?:in|into)\s+(.+)", text, re.IGNORECASE)
            if in_app:
                return {"text": in_app.group(1).strip(), "appName": in_app.group(2).strip()}
            match = re.search(r"(?:type|write|enter text)\s+(.+)", text, re.IGNORECASE)
            return {"text": match.group(1).strip() if match else text}
        if command == TaskCommand.KEYSTROKE:
            in_app = re.search(r"(?:press|hit key|use shortcut)\s+(.+?)\s+(?:in|inside)\s+(.+)", text, re.IGNORECASE)
            if in_app:
                return {"shortcut": in_app.group(1).strip(), "appName": in_app.group(2).strip()}
            match = re.search(r"(?:press|hit key|use shortcut)\s+(.+)", text, re.IGNORECASE)
            return {"shortcut": match.group(1).strip() if match else text}
        if command == TaskCommand.MENU_ITEM:
            full = re.search(r"(?:choose|select menu|click menu)\s+(.+?)\s+from\s+(.+?)\s+(?:menu\s+)?(?:in|inside)\s+(.+)", text, re.IGNORECASE)
            if full:
                return {"item": full.group(1).strip(), "menu": full.group(2).strip(), "appName": full.group(3).strip()}
            return {"raw": text}
        if command == TaskCommand.WRITE_NOTE:
            if any(p in text.lower() for p in ("open that note", "open the note", "open this note", "view that note")):
                return {"action": "open_note"}
            if any(p in text.lower() for p in ("make the title shorter", "make title shorter", "shorten the title", "shorten title")):
                return {"action": "shorten_title"}
            point_m = re.search(r"^(?:add\s+(?:this\s+)?point\s*[:=]?|add\s+(?:to\s+(?:the\s+)?note)?\s*[:=]?)\s*(.+)", text, re.IGNORECASE)
            if point_m:
                return {"action": "append_note", "point": point_m.group(1).strip()}

            titled = re.search(
                r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:called|titled|named)\s+[\"']?([^\"'\n]+?)[\"']?\s+(?:with\s+(?:the\s+)?(?:following\s+)?(?:content|body|text)?\s*[:=]?|saying|that says|with|:)\s*(.+)",
                text,
                re.IGNORECASE,
            )
            if titled:
                title = titled.group(1).strip()
                body = titled.group(2).strip()
                body = re.sub(r"^(?:the\s+following\s+content\s*[:=]?|the\s+content\s*[:=]?|content\s*[:=]?|body\s*[:=]?|text\s*[:=]?)\s*", "", body, flags=re.IGNORECASE).strip().rstrip(".")
                return {"title": title, "body": body}

            titled_only = re.search(r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:called|titled|named)\s+[\"']?([^\"'\n]+?)[\"']?$", text, re.IGNORECASE)
            if titled_only:
                title = titled_only.group(1).strip().rstrip(".")
                return {"title": title, "body": ""}
            match = re.search(r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:saying|with|that says|:)\s*(.+)", text, re.IGNORECASE)
            if match:
                body = match.group(1).strip().rstrip(".")
                if any(w in body.lower() for w in ("today's date", "current date", "todays date")):
                    from datetime import datetime
                    body = f"Date: {datetime.now().strftime('%A, %B %d, %Y')}"
                return {"title": "Cortex Note", "body": body}
            return {"title": "Cortex Note", "body": ""}
        if command in (TaskCommand.SEND_MESSAGE, TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP):
            is_wa = (
                "whatsapp" in text.lower()
                or any(w in text for w in ("ವಾಟ್ಸಾಪ್", "व्हाट्सएप", "வாட்ஸ்அப்", "వాట్సాప్"))
                or command in (TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP)
            )
            clean_text = re.sub(r"^(?:open\s+whatsapp\s+(?:and\s+|to\s+)?)+", "", text, flags=re.IGNORECASE).strip()
            is_draft = is_draft_only_request(message) or is_draft_only_request(text)

            def _ret(r: str, b: str = "") -> dict[str, Any]:
                b = re.sub(
                    r"(?:[.,;—–-]\s*)?"
                    r"(?:do\s+not\s+send\s*(?:it|this|anything)?|"
                    r"dont\s+send\s*(?:it|this|anything)?|"
                    r"don'?t\s+send\s*(?:it|this|anything)?|"
                    r"never\s+send\s*(?:it|this|anything)?|"
                    r"without\s+sending(?:\s+it|\s+anything)?|"
                    r"draft\s+only|"
                    r"just\s+draft(?:\s+it)?|"
                    r"only\s+draft|"
                    r"show\s+me\s+the\s+exact\s+recipient\s+and\s+message.*)"
                    r"[.,;!?]?\s*$",
                    "",
                    b,
                    flags=re.IGNORECASE,
                ).strip()
                d = {"recipient": r, "body": b}
                if is_wa:
                    d["channel"] = "whatsapp"
                if is_draft:
                    d["draft_only"] = True
                return d

            # 1. 'Send Rahul a WhatsApp message saying ...'
            named_ch = re.search(
                r"send\s+(.+?)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)\s+message\s+(?:saying\s*:?|that\s+says\s*:?|with\s+(?:message\s*)?:?|say\s*:?|:)\s+(.+)",
                clean_text,
                re.IGNORECASE,
            )
            if named_ch:
                return _ret(named_ch.group(1).strip(), named_ch.group(2).strip().rstrip("."))

            # 2. 'Send WhatsApp to Rahul saying ...' or 'Prepare a message to Rahul saying ...'
            direct_to = re.search(
                r"(?:send|prepare|draft)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*(?:message\s+)?to\s+(.+?)\s+(?:saying\s*:?|that\s+says\s*:?|with\s+(?:message\s*)?:?|say\s*:?|:)\s*(.+)",
                clean_text,
                re.IGNORECASE,
            )
            if direct_to:
                return _ret(direct_to.group(1).strip(), direct_to.group(2).strip().rstrip("."))

            # Indic language patterns
            kn_m = re.search(r"(.+?)(?:\s+ಅವರಿಗೆ|\s+ಗೆ|\s+ರಿಗೆ)\s+(.+?)\s+(?:ಎಂದು|ಅಂತ)\s+(?:ವಾಟ್ಸಾಪ್\s+)?(?:ಸಂದೇಶ\s+)?(?:ಕಳುಹಿಸಿ|ಕಳಿಸಿ)", text)
            if kn_m:
                return _ret(kn_m.group(1).strip(), kn_m.group(2).strip())

            hi_m = re.search(r"(.+?)\s+(?:को)\s+(?:व्हाट्सएप\s+)?(?:संदेश|मैसेज)\s+(?:भेजें|भेजो)\s+कि\s+(.+)", text)
            if hi_m:
                return _ret(hi_m.group(1).strip(), hi_m.group(2).strip())
            hi_m2 = re.search(r"(.+?)\s+(?:को)\s+(.+?)\s+(?:ऐसा|यह|ये)\s+(?:व्हाट्सएप\s+)?(?:संदेश|मैसेज)\s+(?:भेजें|भेजो)", text)
            if hi_m2:
                return _ret(hi_m2.group(1).strip(), hi_m2.group(2).strip())

            ta_m = re.search(r"(.+?)\s+(?:க்கு|வுக்கு)\s+(.+?)\s+என்று\s+(?:வாட்ஸ்அப்\s+)?(?:செய்தி\s+)?(?:அனுப்பு|அனுப்பவும்)", text)
            if ta_m:
                return _ret(ta_m.group(1).strip(), ta_m.group(2).strip())

            te_m = re.search(r"(.+?)\s+(?:కి|కు)\s+(.+?)\s+అని\s+(?:వాట్సాప్\s+)?(?:సందేశం\s+)?(?:పంపు|పంపండి)", text)
            if te_m:
                return _ret(te_m.group(1).strip(), te_m.group(2).strip())

            named_saying = re.search(
                r"send\s+(.+?)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message\s+(?:saying|that says|with|:)\s+(.+)",
                text,
                re.IGNORECASE,
            )
            if named_saying:
                recipient = named_saying.group(1).strip()
                body = named_saying.group(2).strip().rstrip(".")
                return _ret(recipient, body)
            to_saying = re.search(
                r"(?:send\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message|text|message)\s+(?:to\s+)?(.+?)\s+(?:saying|that says|with|:)\s+(.+)",
                text,
                re.IGNORECASE,
            )
            if to_saying:
                recipient = to_saying.group(1).strip()
                body = to_saying.group(2).strip().rstrip(".")
                return _ret(recipient, body)
            named_only = re.search(
                r"send\s+(.+?)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message",
                text,
                re.IGNORECASE,
            )
            if named_only:
                recipient = named_only.group(1).strip().rstrip(".")
                return _ret(recipient, "")
            to_only = re.search(
                r"(?:send\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message|text|message)\s+(?:to\s+)?(.+)",
                text,
                re.IGNORECASE,
            )
            if to_only:
                recipient = to_only.group(1).strip().rstrip(".")
                return _ret(recipient, "")
            return _ret("", "")
        if command == TaskCommand.CALCULATE:
            expression = re.sub(r"^(?:calculate|compute)\s+", "", text, flags=re.IGNORECASE)
            return {"expression": expression}
        if command == TaskCommand.CLIPBOARD_WRITE:
            marker = "clipboard"
            value = text[text.lower().find(marker) + len(marker) :].strip(" :.-")
            return {"text": value or text}
        if command == TaskCommand.NOTIFICATION:
            return {"title": "Cortex", "message": text}
        if command == TaskCommand.REMINDER:
            return {"text": text}
        if command == TaskCommand.OPEN_URL:
            # Check for contextual references: "that article", "the second result", etc.
            is_contextual = bool(re.search(
                r"\b(?:that|the|this|my|a)?\s*(?:second|first|third|fourth|fifth|\d+(?:st|nd|rd|th)?)?\s*(?:article|result|link|page|url|story|post)\b",
                text, re.IGNORECASE,
            )) or bool(re.search(r"\bopen\s+that\s+article\b", text, re.IGNORECASE)) or any(w in text for w in ("ಆರ್ಟಿಕಲ್", "ಲೇಖನ", "ಆ ಲೇಖನ", "ಆ article", "उस आर्टिकल", "वह आर्टिकल"))

            target_idx = 0
            num_m = re.search(r"\b(\d+)(?:st|nd|rd|th)?\b", text)
            if num_m:
                target_idx = max(0, int(num_m.group(1)) - 1)
            elif "second" in text.lower() or "2nd" in text.lower() or "ಎರಡನೇ" in text or "दूसरा" in text:
                target_idx = 1
            elif "third" in text.lower() or "3rd" in text.lower() or "ಮೂರನೇ" in text or "तीसरा" in text:
                target_idx = 2
            elif "fourth" in text.lower() or "4th" in text.lower():
                target_idx = 3
            elif "fifth" in text.lower() or "5th" in text.lower():
                target_idx = 4
            elif "first" in text.lower() or "1st" in text.lower() or "ಮೊದಲ" in text or "पहला" in text:
                target_idx = 0

            browser = "Safari" if "safari" in text.lower() else "Safari"

            url_match = re.search(r"https?://\S+", text)
            if url_match:
                return {"url": url_match.group(0), "browser": browser}

            if is_contextual:
                return {
                    "use_context": True,
                    "target_index": target_idx,
                    "browser": browser,
                }

            # Site-name → URL lookup (fallback when Gemini is not available)
            _SITE_MAP = {
                "youtube": "https://www.youtube.com",
                "google": "https://www.google.com",
                "gmail": "https://mail.google.com",
                "google maps": "https://maps.google.com",
                "maps": "https://maps.google.com",
                "instagram": "https://www.instagram.com",
                "twitter": "https://www.x.com",
                "x": "https://www.x.com",
                "facebook": "https://www.facebook.com",
                "whatsapp": "https://web.whatsapp.com",
                "whatsapp web": "https://web.whatsapp.com",
                "linkedin": "https://www.linkedin.com",
                "github": "https://www.github.com",
                "netflix": "https://www.netflix.com",
                "amazon": "https://www.amazon.in",
                "flipkart": "https://www.flipkart.com",
                "reddit": "https://www.reddit.com",
                "stackoverflow": "https://stackoverflow.com",
                "stack overflow": "https://stackoverflow.com",
                "wikipedia": "https://www.wikipedia.org",
                "spotify": "https://open.spotify.com",
                "hotstar": "https://www.hotstar.com",
                "notion": "https://www.notion.so",
                "figma": "https://www.figma.com",
                "canva": "https://www.canva.com",
                "chatgpt": "https://chat.openai.com",
                "openai": "https://www.openai.com",
                "gemini": "https://gemini.google.com",
                "drive": "https://drive.google.com",
                "google drive": "https://drive.google.com",
                "docs": "https://docs.google.com",
                "sheets": "https://sheets.google.com",
                "slides": "https://slides.google.com",
                "calendar": "https://calendar.google.com",
                "meet": "https://meet.google.com",
                "zoom": "https://zoom.us",
                "slack": "https://slack.com",
                "discord": "https://discord.com",
                "telegram": "https://web.telegram.org",
                "medium": "https://www.medium.com",
                "news": "https://news.google.com",
                "google news": "https://news.google.com",
                "translate": "https://translate.google.com",
                "google translate": "https://translate.google.com",
            }
            clean = re.sub(
                r"^(?:open url|go to|visit|browse to|navigate to|open|launch|start)\s+",
                "", text, flags=re.IGNORECASE
            ).strip().rstrip("./")
            clean_lower = clean.lower()
            # Try exact site-name match
            for site_name, site_url in _SITE_MAP.items():
                if clean_lower == site_name or clean_lower.endswith(site_name):
                    return {"url": site_url}
            # If it looks like a domain, add https://
            if re.match(r"[\w.-]+\.[a-z]{2,}", clean_lower):
                return {"url": "https://" + clean if not clean.startswith("http") else clean}
            return {"url": clean if clean else text}

        if command == TaskCommand.BROWSER_CLICK:
            clean = re.sub(r"^(?:click on web|browser click|click link|click element|web click|click)\s+", "", text, flags=re.IGNORECASE).strip()
            return {"selector": clean}
        if command == TaskCommand.BROWSER_TYPE:
            type_match = re.search(r"(?:type|enter|fill)\s+(.+?)\s+(?:in|into)\s+(.+)", text, re.IGNORECASE)
            if type_match:
                return {"text": type_match.group(1).strip(), "selector": type_match.group(2).strip()}
            return {"selector": "input", "text": ""}
        if command == TaskCommand.BROWSER_SCRAPE:
            url_match = re.search(r"https?://\S+", text)
            if url_match:
                return {"url": url_match.group(0), "selector": "body"}
            clean = re.sub(r"^(?:scrape web|scrape|read web page|extract from web)\s+", "", text, flags=re.IGNORECASE).strip()
            return {"url": clean, "selector": "body"}
        if command == TaskCommand.SCREEN_VISION:
            return {"question": text if text else "What is on my screen right now?"}
        # ── Phase 5: Mail parameter extraction ────────────────
        if command in {TaskCommand.DRAFT_MAIL, TaskCommand.SEND_MAIL}:
            mail_triggers = {
                "send email", "send an email", "send mail", "send a mail", "draft email", "draft an email",
                "write email", "write an email", "email", "mail",
                "ಇಮೇಲ್ ಕಳುಹಿಸು", "ಇಮೇಲ್ ಮಾಡು", "ಮೇಲ್ ಕಳುಹಿಸು", "ಮೇಲ್ ಮಾಡು", "ಇಮೇಲ್ ಬರೆ",
                "ईमेल भेजो", "ईमेल भेजें", "मेल भेजो", "मेल भेजें", "ईमेल करो", "ईमेल लिखो",
                "மின்னஞ்சல் அனுப்பு", "மெயில் அனுப்பு",
                "ఇమెయిల్ పంపు", "ఇమెయిల్ పంపించు", "మెయిల్ పంపు", "ఈమెయిల్ పంపు",
            }
            clean_cmd = text.strip().rstrip(".! ")
            if clean_cmd.lower() in mail_triggers or re.match(r"^(?:ಕನ್ನಡದಲ್ಲಿ|हिंदी\s*में|தமிழில்|తెలుగులో|in\s+english|in\s+kannada|in\s+hindi)\s*(?:ಇಮೇಲ್|ಮೇಲ್|ईमेल|मेल|மின்னஞ்சல்|மெயில்|ఇమెయిల్|ఈమెయిల్|email|mail)?\s*(?:ಕಳುಹಿಸು|ಕಳಿಸು|ಮಾಡು|ಬರೆ|भेजो|भेजें|करो|लिखो|அனுப்பு|பம்பு|పంపండి)?$", clean_cmd.lower()):
                return {"recipient": "", "subject": "", "body": ""}

            # Indic recipient and content patterns:
            # 1. Hindi: recipient को ... ईमेल भेजो कि body / recipient को ईमेल भेजो कि body
            hi_m = re.search(r"(.+?)\s*को\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|करो|लिखो)(?:\s*(?:कि|की|के\s*लिए)\s*(.+))?", clean_cmd)
            if hi_m:
                rec = hi_m.group(1).strip()
                body = (hi_m.group(2) or "").strip()
                return {"recipient": rec, "subject": "", "body": body}
            hi_m2 = re.search(r"(.+?)\s*को\s*(.+?)\s*(?:के\s*बारे\s*में|के\s*लिए)\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|करो|लिखो)", clean_cmd)
            if hi_m2:
                return {"recipient": hi_m2.group(1).strip(), "subject": "", "body": hi_m2.group(2).strip()}

            # 2. Kannada: recipient ಗೆ ... ಎಂದು/ಬಗ್ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸು or recipient ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸು ... ಎಂದು/ಬಗ್ಗೆ
            kn_m = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ)\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಕಳುಹಿಸಿ|ಮಾಡು|ಬರೆ)(?:\s*(?:ಎಂದು|ಬಗ್ಗೆ|ಅಂತ)\s*(.+))?", clean_cmd)
            if kn_m:
                rec = kn_m.group(1).strip().rstrip("\u200c")
                body = (kn_m.group(2) or "").strip()
                return {"recipient": rec, "subject": "", "body": body}
            kn_m2 = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ)\s*(.+?)\s*(?:ಎಂದು|ಬಗ್ಗೆ|ಅಂತ)\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಕಳುಹಿಸಿ|ಮಾಡು|ಬರೆ)", clean_cmd)
            if kn_m2:
                return {"recipient": kn_m2.group(1).strip().rstrip("\u200c"), "subject": "", "body": kn_m2.group(2).strip()}

            # 3. Tamil: recipient க்கு ... என்று/பற்றி மின்னஞ்சல் அனுப்பு or recipient க்கு மின்னஞ்சல் அனுப்பு ... என்று/பற்றி
            ta_m = re.search(r"(.+?)(?:க்கு|வுக்கு)\s*(?:மின்னஞ்சல்|மெயில்)\s*(?:அனுப்பு|அனுப்புங்கள்)(?:\s*(?:என்று|பற்றி)\s*(.+))?", clean_cmd)
            if ta_m and ta_m.group(2):
                return {"recipient": ta_m.group(1).strip(), "subject": "", "body": ta_m.group(2).strip()}
            ta_m2 = re.search(r"(.+?)(?:க்கு|வுக்கு)\s*(.+?)\s*(?:என்று|பற்றி)?\s*(?:மின்னஞ்சல்|மெயில்)\s*(?:அனுப்பு|அனுப்புங்கள்)", clean_cmd)
            if ta_m2:
                return {"recipient": ta_m2.group(1).strip(), "subject": "", "body": ta_m2.group(2).strip()}
            if ta_m:
                return {"recipient": ta_m.group(1).strip(), "subject": "", "body": ""}

            # 4. Telugu: recipient కు ... అని/గురించి ఈమెయిల్ పంపండి or recipient కు ఈమెయిల్ పంపండి ... అని/గురించి
            te_m = re.search(r"(.+?)(?:కి|కు)\s*(?:ఇమెయిల్|ఈమెయిల్|మెయిల్)\s*(?:పంపు|పంపండి|పంపించు)(?:\s*(?:అని|గురించి)\s*(.+))?", clean_cmd)
            if te_m and te_m.group(2):
                return {"recipient": te_m.group(1).strip(), "subject": "", "body": te_m.group(2).strip()}
            te_m2 = re.search(r"(.+?)(?:కి|కు)\s*(.+?)\s*(?:అని|గురించి)?\s*(?:ఇమెయిల్|ఈమెయిల్|మెయిల్)\s*(?:పంపు|పంపండి|పంపించు)", clean_cmd)
            if te_m2:
                return {"recipient": te_m2.group(1).strip(), "subject": "", "body": te_m2.group(2).strip()}
            if te_m:
                return {"recipient": te_m.group(1).strip(), "subject": "", "body": ""}

            # Extract via robust email engine
            extracted = self.email_engine.extract_command_and_content(text)
            rec = extracted.get("recipient", "").strip()
            email_m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", rec)
            recipient = email_m.group(1) if email_m else rec
            subj = extracted.get("subject", "")
            body = extracted.get("content", "")
            sender_acc = extracted.get("sender_account") or extracted.get("account") or ""
            cc = extracted.get("cc", [])
            bcc = extracted.get("bcc", [])
            attachments = extracted.get("attachments", [])

            if not subj and body:
                ctx = self.email_engine.infer_recipient_context(recipient, text)
                subj = self.email_engine.generate_subject(text or body, ctx)

            return {
                "recipient": recipient,
                "subject": subj,
                "body": body,
                "account": sender_acc,
                "sender_account": sender_acc,
                "cc": cc,
                "bcc": bcc,
                "attachments": attachments,
            }
        if command == TaskCommand.WEB_SEARCH:
            # Multi-capability cooperative: "find [topic], open [article] in safari, and explain it"
            _coop_re = re.search(
                r"^(?:find|search\s+(?:the\s+web\s+)?(?:for)?)\s+(.+?),\s*(?:open|load)\s+(?:the\s+)?(?:most\s+relevant\s+|first\s+|top\s+)?article\s+in\s+(safari|chrome|browser)?,\s*and\s+(?:explain|summarize)\s+it",
                text,
                re.IGNORECASE,
            )
            if _coop_re:
                q = _coop_re.group(1).strip()
                q = re.sub(r"^(?:the\s+)", "", q, flags=re.IGNORECASE).strip()
                b = (_coop_re.group(2) or "Safari").title()
                return {
                    "query": q,
                    "browser": b,
                    "cooperative_chain": True,
                    "open_in_browser": True,
                    "explain_article": True,
                }

            # Search + explain target: "find [topic] and explain the second result"
            _compound_explain_re = re.search(
                r"^(?:find|search\s+(?:the\s+web\s+)?(?:for\s+)?|look\s+up|research)\s+(.+?)\s+and\s+(?:explain|summarize|tell\s+me\s+about|break\s+down)\s+(?:the\s+)?(first|second|third|1st|2nd|3rd|\d+)?\s*(?:result|article|finding|one|item)?",
                text,
                re.IGNORECASE,
            )
            if _compound_explain_re:
                raw_q = _compound_explain_re.group(1).strip()
                raw_q = re.sub(r"^(?:the\s+)", "", raw_q, flags=re.IGNORECASE).strip()
                raw_target = _compound_explain_re.group(2) or "second"
                idx = 1 if "second" in raw_target.lower() or "2" in raw_target else (0 if "first" in raw_target.lower() or "1" in raw_target else 2)
                return {
                    "query": raw_q,
                    "target_index": idx,
                    "explain_target": True,
                }

            # --- P0 fix: compound "open [browser] and/to/, search for [query]" patterns ---
            _compound_browser_re = re.compile(
                r"(?:open|launch|start)\s+(safari|chrome|firefox|edge|browser)\s*[,;]?\s*"
                r"(?:and\s+|to\s+)?(?:search\s+(?:the\s+)?(?:web\s+)?(?:for\s+)?|look\s+up\s+|research\s+|find\s+|google\s+)"
                r"(.+)",
                re.IGNORECASE,
            )
            _compound_m = _compound_browser_re.search(text)
            inspect_flag = bool(re.search(r"\b(?:inspect|read|check)\s+(?:the\s+)?(?:results|pages|sources|articles)\b", text, re.IGNORECASE))
            if _compound_m:
                raw_browser = _compound_m.group(1).strip().title()  # e.g. "Safari"
                raw_query = _compound_m.group(2).strip()
                query = self._sanitize_search_query(raw_query)
                return {"query": query, "browser": raw_browser, "inspect_results": inspect_flag}

            # Standard query stripping (non-compound forms)
            query = self._sanitize_search_query(text)
            _browser_mention = re.search(r"\bin\s+(safari|chrome|firefox|edge)\b", text, re.IGNORECASE)
            browser_param: dict = {"browser": _browser_mention.group(1).title()} if _browser_mention else {}
            filter_m = re.search(r"^(.*?)\s+(?:under|below|less than|priced under|priced at most)\s+([₹$€£]?\s*[\d,]+.*)$", query, re.IGNORECASE)
            if filter_m:
                clean_q = filter_m.group(1).strip()
                filter_val = filter_m.group(2).strip().rstrip(".")
                return {
                    "query": clean_q,
                    "filter": f"price <= {filter_val}",
                    "raw_query": query.rstrip("."),
                    "inspect_results": inspect_flag,
                    **browser_param,
                }
            return {"query": query if query else text, "inspect_results": inspect_flag, **browser_param}
        if command in {TaskCommand.READ_MAIL, TaskCommand.SUMMARIZE_MAIL}:
            unread_only = "unread" in text.lower()
            return {"limit": 5, "unread_only": unread_only}
        if command == TaskCommand.CALCULATE:
            return {"expression": text}
        if command == TaskCommand.PERSONAL_TASK_CREATE:
            m = re.search(r"(?:add task|create task|new task|remind me to)\s+(.+?)(?:\s+(?:at|by|due|for)\s+(.+))?$", text, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                due = m.group(2).strip() if m.group(2) else "Today"
                return {"title": title, "due": due}
            return {"title": text, "due": "Today"}
        if command == TaskCommand.PERSONAL_TASK_LIST:
            return {}
        if command == TaskCommand.CALENDAR_READ:
            return {"day": "today"}
        if command == TaskCommand.DAILY_BRIEFING:
            return {}
        if command == TaskCommand.SEARCH_FILES:
            t_lower = text.lower()
            open_finder = bool(re.search(r"\bfinder\b|\bnavigate\b", t_lower))

            # Resolve target directory
            directory = "."
            if "download" in t_lower or "ಡೌನ್‌ಲೋಡ್" in text or "डाउनलोड" in text:
                directory = "Downloads"
            elif "document" in t_lower or "ದಾಖಲೆ" in text or "दस्तावेज़" in text:
                directory = "Documents"
            elif "desktop" in t_lower or "ಡೆಸ್ಕ್‌ಟಾಪ್" in text or "डेस्कटॉप" in text:
                directory = "Desktop"
            else:
                dir_m = re.search(r"\b(?:in|to|from|inside)\s+([a-zA-Z0-9_/~.-]+)\b", text, re.IGNORECASE)
                if dir_m:
                    directory = dir_m.group(1).strip()
                elif open_finder:
                    directory = "Downloads"

            # Resolve limit
            limit = 5  # default for "first five visible filenames" or standard listing
            num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "ಐದು": 5, "पाँच": 5, "पांच": 5}
            num_m = re.search(r"\b(?:first|top)\s+(\w+|\d+)\b|\b(\d+)\s+(?:visible\s+)?(?:file|files|filename|filenames|items)\b", t_lower)
            if num_m:
                token = (num_m.group(1) or num_m.group(2) or "").strip()
                if token.isdigit():
                    limit = int(token)
                elif token in num_map:
                    limit = num_map[token]
            elif "all" in t_lower or "all files" in t_lower:
                limit = 50

            # Resolve pattern
            pattern = "*"
            find_m = re.search(r"(?:find file|search file|look for file|locate file|find the file)\s+['\"]?([^'\"\s]+)['\"]?", text, re.IGNORECASE)
            if find_m:
                pattern = find_m.group(1).strip()

            return {
                "pattern": pattern,
                "directory": directory,
                "limit": limit,
                "open_finder": open_finder,
                "sort_by": "alphabetical",
                "read_only": True,
            }
        if command == TaskCommand.READ_FILE:
            m = re.search(r"(?:read file|open file|view file|show file)\s+(.+)", text, re.IGNORECASE)
            return {"path": m.group(1).strip() if m else text}
        if command == TaskCommand.SEARCH_MAIL:
            m = re.search(r"(?:find email|search email|search mail|find emails from|emails from|emails about)\s+(.+)", text, re.IGNORECASE)
            return {"query": m.group(1).strip() if m else text}
        return {}

    def _split_sequence(self, message: str) -> list[str]:
        # Do not split compound browser search commands like "Open Safari and search for..." or "Open Safari, search for..."
        if re.search(r"^(?:open|launch)\s+(?:safari|chrome|browser)\s*[,;]?\s*(?:and\s+|to\s+)?(?:search|find|look\s+up|research|inspect)\b", message, re.IGNORECASE):
            return [message]

        # Do not split compound Finder navigation and inspection commands like "Open Finder, navigate to Downloads..."
        if re.search(r"^(?:open|launch)\s+finder\b.*?\b(?:navigate|show|list|files?|filenames?|downloads?)\b", message, re.IGNORECASE):
            return [message]

        parts = [
            part.strip()
            for part in re.split(r"\s+(?:and\s+then|then|and\s+(?=(?:create|write|open|launch|take|type|send|draft|make)\b))\s*", message, flags=re.IGNORECASE)
            if part.strip()
        ]
        return parts if len(parts) > 1 else [message]
