from __future__ import annotations

import os
import time
import json
import re
import sys
import threading
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
            if cmd in (
                TaskCommand.OPEN_APP,
                TaskCommand.CLOSE_APP,
                TaskCommand.SHUTDOWN,
                TaskCommand.RESTART,
                TaskCommand.CALCULATE,
                TaskCommand.SCREENSHOT,
                TaskCommand.WEB_SEARCH,
            ):
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

        # General questions (for recipient clarification or disambiguation, questions are unrelated)
        if step in ("waiting_for_recipient_clarification", "waiting_for_recipient_disambiguation", "waiting_for_recipient", "confirm_send"):
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
            r"^(?:no[,\s]+)?(?:please\s+)?(?:cancel|abort|discard|stop)(?:\s+(?:the\s+|this\s+)?(?:draft|email|mail|task|action|it|that))?$",
            r"^(?:no[,\s]+)?(?:please\s+)?(?:don'?t|do\s+not|never)\s+send(?:\s+(?:the\s+|this\s+)?(?:draft|email|mail|it|that|anything))?.*$",
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
                is_edit = any(kw in msg_lower for kw in (
                    "shorter", "concise", "formal", "casual", "brief", "subject", "reason",
                    "before", "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday",
                    "deadline", "urgent", "professor", "prof", "dr", "dear", "address", "account",
                    "college email", "work email", "add", "remove", "change", "include", "mention",
                    "make it", "update", "rewrite", "replace", "warm regards", "sincerely", "regards",
                    "kannada", "hindi", "tamil", "telugu", "english", "translate", "write it in", "write in",
                    "keep the", "ಕನ್ನಡ", "ಕನ್ನಡದಲ್ಲಿ", "हिंदी", "हिंदी में", "தமிழ்", "தமிழில்", "తెలుగు", "తెలుగులో",
                )) or ("don't mention" in msg_lower or "dont mention" in msg_lower or "omit the reason" in msg_lower)
                has_negation = (
                    bool(re.search(r"\b(?:don'?t|do\s+not|never|stop|cancel|reject|abort|discard)\b", msg_lower))
                    or msg_lower in ("no", "n", "nope", "nahi", "nahi bhejna", "नहीं")
                    or any(kw in msg_lower for kw in ("ಬೇಡ", "ಕಳಿಸಬೇಡ", "ಕಳುಹಿಸಬೇಡ", "मत", "नहीं", "வேண்டாம்", "அனுப்பாதே", "వద్దు", "పంపవద్దు", "పంపకండి"))
                )
                if has_negation and not is_edit:
                    return self._handle_cancellation(message, raw_lang_code, detected_lang)

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
                    self.pending_action = None
                    approved_task = self.approve(task_id, approved=True)
                    if approved_task.get("status") in (TaskStatus.FAILED.value, TaskStatus.FAILED, "failed"):
                        return {
                            "task": approved_task,
                            "message": approved_task.get("error") or "Failed to send email.",
                        }
                    return {
                        "task": approved_task,
                        "message": localize("email_sent", p_lang, recipient=recipient),
                    }
                elif is_edit or (" " in msg_lower and not any(kw in msg_lower for kw in ("open ", "close ", "screenshot", "calculate", "find "))):
                    task_id = pending["task_id"]
                    task = self.tasks[task_id]
                    draft = pending.get("draft")
                    if not draft:
                        draft = EmailDraft(recipient=pending["recipient"], subject=pending["subject"], body=pending.get("formatted_body") or pending["body"], sender_account=pending.get("sender_account", ""))
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

            elif pending.get("type") == "whatsapp_draft" and pending.get("step") == "confirm_send":
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
        elif (command in (TaskCommand.SEND_MESSAGE, TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP)) and ("whatsapp" in message.lower() or command in (TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP) or params.get("channel") == "whatsapp"):
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
                    self.tasks[task.id] = task
                    self._persist_task(task)
                    return {
                        "task": task.to_dict(),
                        "message": f"Cannot prepare email: attachment file not found at '{missing_att}'. Please provide a valid file path.",
                    }

                clean_body, meta = convert_instruction_to_recipient_content(raw_body)
                content_for_draft = clean_body or raw_body
                tone_override = meta.get("extracted_tone")

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
                    task.result = f"Draft created for {draft.recipient} with subject '{draft.subject}'."
                    task.add_event("completed", task.result)
                    response = task.result
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
            response = task.result or localize("action_done", raw_lang_code)

        # Update conversation history on success
        if risk != RiskLevel.BLOCKED and not approval and command != TaskCommand.UNKNOWN:
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
            if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED, TaskStatus.CANCELED}:
                task.add_event("cancel_ignored", "Task already reached a terminal state.")
            else:
                task.request_cancellation(reason="User interrupted the task.")
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

    def _summarize_search(self, query: str, results: list[dict[str, str]]) -> str:
        # Check direct answer first
        direct = resolve_direct_answer(query)
        if direct:
            return direct

        if self._is_gemini_available():
            try:
                model = self._create_gemini_model()
                formatted = "\n\n".join([
                    f"Title: {r['title']}\nContent: {clean_search_response(r['body'])}"
                    for r in results if r.get("body")
                ])
                prompt = (
                    f"You are Cortex, a direct AI assistant like Google, Claude, and ChatGPT.\n"
                    f"Answer the question below using ONLY the provided facts. Be concise, direct, and well-structured.\n"
                    f"Rules: Lead with the answer. No preamble. No 'I hope this helps'. Use markdown formatting and bullet points for lists.\n\n"
                    f"Question: {query}\n\n"
                    f"Facts:\n{formatted}"
                )
                response = model.generate_content(prompt, request_options={"timeout": 6.0})
                if response and response.text:
                    return clean_search_response(response.text.strip())
            except Exception as e:
                self._handle_gemini_error(e, context="summarize search")

        # Offline fallback: clean snippets thoroughly (unescape HTML entities, strip tags)
        cleaned_bodies = [clean_search_response(r.get("body", "")) for r in results if r.get("body")]
        cleaned_bodies = [b for b in cleaned_bodies if b]
        if cleaned_bodies:
            return cleaned_bodies[0] if len(cleaned_bodies) == 1 else cleaned_bodies[0] + "\n\n" + cleaned_bodies[1]

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
        doc_match = re.search(r"\b(?:summarize\s+(?:document|file|text|this))\s+(.+)", query, flags=re.IGNORECASE)
        if doc_match:
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
            or (any(q_lower.startswith(w) for w in ("hi ", "hello", "hey ", "greetings", "namaste", "namaskara", "vanakkam", "namaskaram")) and len(q_lower.split()) <= 4)
        )
        is_status = any(p in q_lower for p in (
            "how are you", "hegidira", "hegiddira", "hegidiya", "chennagidira",
            "ಹೇಗಿದ್ದೀರಿ", "ಹೇಗಿದ್ದೀರಾ", "ಚೆನ್ನಾಗಿದ್ದೀರಾ", "kaisa hai", "kaise ho", "kya haal", "haal chal",
            "आप कैसे हैं", "कैसे हो", "क्या हाल है", "हाल चाल", "eppadi irukinga", "epdi irukinga", "eppadi irukka",
            "எப்படி இருக்கிறீர்கள்", "எப்படி இருக்கீங்க", "ela unnaru", "bagunnara", "bagunara", "ఎలా ఉన్నారు", "బాగున్నారా"
        ))
        is_identity = any(p in q_lower for p in (
            "who are you", "what can you do", "ನಿಮ್ಮ ಹೆಸರೇನು", "ನೀವು ಯಾರು", "ನೀವೇನು ಮಾಡಬಲ್ಲಿರಿ", "ಏನು ಮಾಡಬಹುದು",
            "आप कौन हैं", "तुम्हारा नाम क्या है", "आप क्या कर सकते हैं", "நீங்கள் யார்", "మీరు ఎవరు"
        ))

        if is_status:
            return get_cortex_status(lang_code)
        if is_greeting or is_identity:
            return get_cortex_identity(lang_code)

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

        # 4. Web search fallback for factual queries
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
            task.add_event("web_search_started", f"Searching the web for: {query}")
            results = search_web(query)
            if results:
                task.add_event("web_search_completed", f"Found {len(results)} results.")
                answer = self._summarize_search(query, results)
                task.status = TaskStatus.COMPLETED
                task.result = answer
                task.add_event("completed", "Web search results summarized.")
            else:
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
                    task.error = "No search results found."
                    task.add_event("failed", "Web search returned no results.")
            return

        # ── Phase 5: Mail Automation Execution ─────────────────────────
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

        # Pipeline execution with execute -> observe -> verify -> recover loop
        if not task.plan:
            task.plan = self.planner.plan(task.intent, task.command, task.params, task.context)
        final_res = self.execution_engine.execute_plan(task)
        lang = str(task.language.value if task.language else "en")
        if final_res.status == TaskStatus.COMPLETED:
            task.status = TaskStatus.COMPLETED
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
                task.result = final_res.summary or task.result or "Completed."
        else:
            task.status = TaskStatus.FAILED
            task.error = final_res.summary or task.error or "Execution failed."

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
            match = re.search(r"(?:open|launch|start|close|quit|exit)\s+(.+)", text, re.IGNORECASE)
            if command == TaskCommand.FOCUS_APP:
                match = re.search(r"(?:focus|switch to|bring up|activate)\s+(.+)", text, re.IGNORECASE)
            app_raw = match.group(1).strip() if match else text
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
            titled = re.search(r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:called|titled|named)\s+(.+?)\s+(?:saying|with|that says|:)\s+(.+)", text, re.IGNORECASE)
            if titled:
                title = titled.group(1).strip()
                body = titled.group(2).strip().rstrip(".")
                return {"title": title, "body": body}
            titled_only = re.search(r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:called|titled|named)\s+(.+)", text, re.IGNORECASE)
            if titled_only:
                title = titled_only.group(1).strip().rstrip(".")
                return {"title": title, "body": ""}
            match = re.search(r"(?:write|create|take)\s+(?:a\s+)?note\s+(?:saying|with|that says|:)\s*(.+)", text, re.IGNORECASE)
            if match:
                body = match.group(1).strip().rstrip(".")
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
            url_match = re.search(r"https?://\S+", text)
            if url_match:
                return {"url": url_match.group(0)}
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
            if clean_cmd.lower() in mail_triggers:
                return {"recipient": "", "subject": "", "body": ""}

            # Indic recipient and content patterns:
            # 1. Hindi: recipient को ... ईमेल भेजो कि body / recipient को ईमेल भेजो कि body
            hi_m = re.search(r"(.+?)\s*को\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|करो|लिखो)(?:\s*(?:कि|की|के\s*लिए)\s*(.+))?", clean_cmd)
            if hi_m and hi_m.group(2):
                return {"recipient": hi_m.group(1).strip(), "subject": "", "body": hi_m.group(2).strip()}
            hi_m2 = re.search(r"(.+?)\s*को\s*(.+?)\s*(?:के\s*बारे\s*में|के\s*लिए)?\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|करो|लिखो)", clean_cmd)
            if hi_m2:
                return {"recipient": hi_m2.group(1).strip(), "subject": "", "body": hi_m2.group(2).strip()}
            if hi_m:
                return {"recipient": hi_m.group(1).strip(), "subject": "", "body": ""}

            # 2. Kannada: recipient ಗೆ ... ಎಂದು/ಬಗ್ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸು or recipient ಗೆ ಇಮೇಲ್ ಕಳುಹಿಸು ... ಎಂದು/ಬಗ್ಗೆ
            kn_m = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ)\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಕಳುಹಿಸಿ|ಮಾಡು|ಬರೆ)(?:\s*(?:ಎಂದು|ಬಗ್ಗೆ)\s*(.+))?", clean_cmd)
            if kn_m and kn_m.group(2):
                return {"recipient": kn_m.group(1).strip(), "subject": "", "body": kn_m.group(2).strip()}
            kn_m2 = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ)\s*(.+?)\s*(?:ಎಂದು|ಬಗ್ಗೆ)?\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಕಳುಹಿಸಿ|ಮಾಡು|ಬರೆ)", clean_cmd)
            if kn_m2:
                return {"recipient": kn_m2.group(1).strip(), "subject": "", "body": kn_m2.group(2).strip()}
            if kn_m:
                return {"recipient": kn_m.group(1).strip(), "subject": "", "body": ""}

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
            query = re.sub(r"^(?:google|search the web for|search for|search|look up)\s+", "", text, flags=re.IGNORECASE).strip()
            filter_m = re.search(r"^(.*?)\s+(?:under|below|less than|priced under|priced at most)\s+([₹$€£]?\s*[\d,]+.*)$", query, re.IGNORECASE)
            if filter_m:
                clean_q = filter_m.group(1).strip()
                filter_val = filter_m.group(2).strip().rstrip(".")
                return {
                    "query": clean_q,
                    "filter": f"price <= {filter_val}",
                    "raw_query": query.rstrip("."),
                }
            return {"query": query if query else text}
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
            m = re.search(r"(?:find file|search file|look for file|locate file|find the file)\s+(.+?)(?:\s+in\s+(.+))?$", text, re.IGNORECASE)
            if m:
                pat = m.group(1).strip()
                dir_ = m.group(2).strip() if m.group(2) else "."
                return {"pattern": pat, "directory": dir_}
            return {"pattern": text, "directory": "."}
        if command == TaskCommand.READ_FILE:
            m = re.search(r"(?:read file|open file|view file|show file)\s+(.+)", text, re.IGNORECASE)
            return {"path": m.group(1).strip() if m else text}
        if command == TaskCommand.SEARCH_MAIL:
            m = re.search(r"(?:find email|search email|search mail|find emails from|emails from|emails about)\s+(.+)", text, re.IGNORECASE)
            return {"query": m.group(1).strip() if m else text}
        return {}

    def _split_sequence(self, message: str) -> list[str]:
        parts = [
            part.strip()
            for part in re.split(r"\s+(?:then|and then)\s+", message, flags=re.IGNORECASE)
            if part.strip()
        ]
        return parts if len(parts) > 1 else [message]
