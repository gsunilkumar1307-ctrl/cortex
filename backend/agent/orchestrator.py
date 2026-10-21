from __future__ import annotations

import os
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from backend.capabilities import DeviceAutomation, classify_command
    from backend.persistence import EncryptedMemoryStore
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
    )
    from backend.core.language_detector import detect_language, language_instruction
    from backend.core.localization import (
        localize,
        normalize_app_name,
        get_cortex_identity,
        get_cortex_status,
        get_offline_knowledge,
    )
    from backend.integrations.search import search_web
    from backend.agent.policy import PolicyEngine
    from backend.tools.registry import ToolRegistry
    from backend.agent.execution_engine import ExecutionEngine
    from backend.agent.planner import AutonomousPlanner
    from backend.agent.email_engine import ProfessionalEmailEngine, EmailDraft, sanitize_untrusted_email_content
    from backend.agent.recipient_resolver import RecipientResolver, ResolutionResult, ResolvedRecipient
except ImportError:
    from capabilities import DeviceAutomation, classify_command
    from persistence import EncryptedMemoryStore
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
    )
    from core.language_detector import detect_language, language_instruction
    from core.localization import (
        localize,
        normalize_app_name,
        get_cortex_identity,
        get_cortex_status,
        get_offline_knowledge,
    )
    from integrations.search import search_web
    from policy import PolicyEngine
    from tools.registry import ToolRegistry
    from execution_engine import ExecutionEngine
    from planner import AutonomousPlanner
    from email_engine import ProfessionalEmailEngine, EmailDraft, sanitize_untrusted_email_content
    from recipient_resolver import RecipientResolver, ResolutionResult, ResolvedRecipient

try:
    import google.generativeai as genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

SYSTEM_PROMPT = """You are Cortex, a powerful AI desktop assistant and knowledge engine.
You understand natural language commands for both computer control AND general questions.

ANSWERING STYLE — BE LIKE GOOGLE:
- Answer DIRECTLY. Lead with the fact/answer immediately — no preamble, no "Great question!", no "Sure!"
- Be concise. 1-3 sentences for simple facts. Use bullet points only if listing multiple items.
- For questions: give the answer first, then a brief explanation if needed.
- For greetings: be warm but brief.
- NEVER pad answers with filler phrases like "I hope that helps!", "Feel free to ask!", "As an AI..."
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
- "screen_vision": Analyze what's on screen. Parameter: {"question": string (optional)}
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


class CortexOrchestrator:
    def __init__(
        self,
        automation: DeviceAutomation | None = None,
        memory: EncryptedMemoryStore | None = None,
        use_gemini: bool | None = None,
    ) -> None:
        self.automation = automation or DeviceAutomation()
        self.memory = memory or EncryptedMemoryStore(str(Path("work") / "cortex-memory.sqlite3"))
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

    def _analyze_intent(self, message: str, lang_code: str = "en") -> dict[str, Any]:
        if not self.use_gemini:
            return self._analyze_intent_fallback(message)

        try:
            # Build a language-aware system prompt
            lang_instr = language_instruction(lang_code)
            system = SYSTEM_PROMPT
            if lang_instr:
                system = SYSTEM_PROMPT + f"\n\nLanguage Directive:\n{lang_instr}"

            model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system)
            
            # Construct standard chat history context for Gemini
            chat_contents = []
            for h in self.history:
                chat_contents.append(h)
            
            current_message = f"User intent: {message}"
            chat_contents.append({"role": "user", "parts": [current_message]})

            response = model.generate_content(
                chat_contents,
                generation_config={"response_mime_type": "application/json"}
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
            print(f"[cortex] Gemini analysis failed: {exc}. Falling back to regex parser.", file=sys.stderr)
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

        if lang_code == "en":
            sender_str = f"From: {sender_account}\n" if sender_account else ""
            attachments_str = f"Attachments: {', '.join(attachments)}\n" if attachments else ""
            header = "Draft created and saved to your mailbox:\n" if draft_saved else f"Draft prepared (Note: draft could not be saved to your mailbox - {save_error}):\n"
            return (
                f"{header}"
                f"To: {recipient}\n"
                f"{sender_str}"
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

    def chat(self, message: str, source: str = "text") -> dict[str, Any]:
        # Handle history clearing
        if message.lower().strip() in ("clear history", "reset conversation", "clear memory"):
            self.history = []
            self._save_history()
            return {
                "message": "Memory cleared.",
                "task": Task(message, TaskCommand.UNKNOWN, RiskLevel.LOW, False).to_dict()
            }

        # ── Phase 6: Detect language before any intent analysis ────────────────
        raw_lang_code = detect_language(message)
        detected_lang = LanguageCode.from_string(raw_lang_code)

        # ── Progressive multi-turn completion for missing info / partial commands ──
        if self.pending_action:
            pending = self.pending_action
            p_lang = pending.get("lang") or raw_lang_code
            if pending.get("step") == "confirm_send":
                msg_lower = message.strip().lower().rstrip(".!")
                # If user starts a brand new task or email to another recipient, discard pending draft
                if (
                    re.match(r"^(?:send|draft|compose|write)\s+(?:an?\s+)?(?:email|mail)\s+to\b", msg_lower)
                    or any(msg_lower.startswith(w) for w in ("open ", "close ", "screenshot", "calculate ", "check ", "read "))
                ):
                    self.pending_action = None
                else:
                    is_cancel = any(kw in msg_lower for kw in ("cancel", "reject", "don't send", "dont send", "stop", "discard", "abort", "ಬೇಡ", "ರದ್ದು", "मत भेजो", "नहीं", "வேண்டாம்", "వద్దు")) or msg_lower in ("no", "n", "nope")
                    is_show_draft = any(kw in msg_lower for kw in ("show me", "show draft", "view draft", "complete draft", "see draft", "display draft", "read draft"))
                    is_edit = any(kw in msg_lower for kw in (
                        "shorter", "concise", "formal", "casual", "brief", "subject", "reason",
                        "before", "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday",
                        "deadline", "urgent", "professor", "prof", "dr", "dear", "address", "account",
                        "college email", "work email", "add", "remove", "change", "include", "mention",
                        "don't", "dont", "make it", "update", "rewrite", "replace", "warm regards", "sincerely", "regards"
                    ))
                    is_confirm = (
                        not is_cancel
                        and not is_edit
                        and not is_show_draft
                        and (
                            bool(re.search(r"\b(yes|send\s+it|approve|go\s+ahead|send|sure|ok|okay|please\s+send|y|yep|agree|confirmed)\b", msg_lower))
                            or any(kw in msg_lower for kw in ("ಕಳುಹಿಸು", "ಕಳಿಸು", "ಸರಿ", "ಹೌದು", "ಆಯ್ತು", "भेजो", "भेजें", "हाँ", "हां", "ठीक है", "அனுப்பு", "சரி", "పంపు", "సరే"))
                        )
                    )

                if is_cancel:
                    task_id = pending["task_id"]
                    self.pending_action = None
                    cancelled_task = self.approve(task_id, approved=False)
                    return {
                        "task": cancelled_task,
                        "message": localize("action_cancelled", p_lang),
                    }
                elif is_show_draft:
                    task_id = pending["task_id"]
                    task = self.tasks[task_id]
                    draft = pending.get("draft")
                    if not draft:
                        draft = EmailDraft(recipient=pending["recipient"], subject=pending["subject"], body=pending.get("formatted_body") or pending["body"], sender_account=pending.get("sender_account", ""))
                    response = self._format_approval_card(draft, lang_code=p_lang)
                    return {"task": task.to_dict(), "message": response}
                elif is_edit or (" " in msg_lower and not is_confirm and not any(kw in msg_lower for kw in ("open ", "close ", "screenshot", "calculate", "find "))):
                    task_id = pending["task_id"]
                    task = self.tasks[task_id]
                    draft = pending.get("draft")
                    if not draft:
                        draft = EmailDraft(recipient=pending["recipient"], subject=pending["subject"], body=pending.get("formatted_body") or pending["body"], sender_account=pending.get("sender_account", ""))
                    updated_draft = self.email_engine.update_draft_with_edit(draft, message)
                    pending["subject"] = updated_draft.subject
                    pending["body"] = updated_draft.body
                    pending["draft"] = updated_draft
                    pending["sender_account"] = updated_draft.sender_account
                    pending["attachments"] = updated_draft.attachments
                    task.params["subject"] = updated_draft.subject
                    task.params["body"] = updated_draft.body
                    task.params["formatted_body"] = updated_draft.body
                    task.params["sender_account"] = updated_draft.sender_account
                    task.params["attachments"] = updated_draft.attachments
                    task.params["approval_hash"] = updated_draft.approval_hash
                    task.status = TaskStatus.WAITING_APPROVAL
                    task.add_event("draft_edited", f"Draft updated: {message}")

                    draft_saved = True
                    save_error = ""
                    try:
                        res = self.automation.execute(TaskCommand.DRAFT_MAIL, {"recipient": updated_draft.recipient, "subject": updated_draft.subject, "body": updated_draft.body, "account": updated_draft.sender_account})
                        if hasattr(res, "ok") and not res.ok:
                            draft_saved = False
                            save_error = res.message
                    except Exception as e:
                        draft_saved = False
                        save_error = str(e)

                    response = self._format_approval_card(updated_draft, lang_code=p_lang, draft_saved=draft_saved, save_error=save_error)
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
                    rec_display = f"{resolved.name} <{resolved.email}>" if resolved.name and resolved.name != resolved.email else resolved.email
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
                clean_body = re.sub(
                    r"^(?:tell\s+(?:him|her|them|it)\s+|saying\s+|that\s+says\s+|that\s+|say\s+)",
                    "",
                    message.strip(),
                    flags=re.IGNORECASE,
                ).strip()
                if clean_body:
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
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_recipient_clarification",
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
                    self.pending_action = {
                        "type": "email_draft",
                        "step": "waiting_for_recipient_disambiguation",
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
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient_clarification",
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
                self.pending_action = {
                    "type": "email_draft",
                    "step": "waiting_for_recipient_disambiguation",
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
                draft = self.email_engine.compose_email(
                    raw_intent=message,
                    recipient_raw=rec_display,
                    content=raw_body,
                    subject_override=params.get("subject", ""),
                    use_gemini=self.use_gemini,
                    gemini_model=self.gemini_model,
                )
                draft = self.email_engine.run_quality_control(draft, known_facts=[raw_body])
                draft.approval_hash = draft.compute_hash()

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

                task.params["recipient"] = raw_rec if raw_rec else draft.recipient
                task.params["recipient_email"] = draft.recipient
                task.params["subject"] = draft.subject
                task.params["formatted_body"] = draft.body
                task.params["sender_account"] = draft.sender_account
                task.params["approval_hash"] = draft.approval_hash
                task.params["attachments"] = draft.attachments
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
                        "draft": draft,
                        "lang": raw_lang_code,
                    }
                    response = self._format_approval_card(draft, lang_code=raw_lang_code, draft_saved=draft_saved, save_error=save_error)
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

    def approve(self, task_id: str, approved: bool) -> dict[str, Any]:
        task = self._get_task(task_id)
        if task.status != TaskStatus.WAITING_APPROVAL:
            task.add_event("approval_ignored", "Task was not waiting for approval.")
            return task.to_dict()
        if not approved:
            task.status = TaskStatus.CANCELED
            task.result = "Approval rejected. No action was taken."
            task.add_event("approval_rejected", "User rejected the action.")
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
            if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                expected_hash = task.params.get("approval_hash")
                if expected_hash:
                    current_hash = EmailDraft(
                        recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
                        subject=task.params.get("subject", ""),
                        body=task.params.get("formatted_body") or task.params.get("body", ""),
                        sender_account=task.params.get("sender_account", ""),
                        attachments=task.params.get("attachments", []),
                    ).compute_hash()
                    if current_hash != expected_hash:
                        task.status = TaskStatus.WAITING_APPROVAL
                        task.add_event("approval_invalidated", "Draft changed after approval requested.")
                        task.error = "Approval invalidated: draft content was modified. Please review and approve again."
                        self._persist_task(task)
                        return task.to_dict()

            self._execute(task)
        self._persist_task(task)
        return task.to_dict()

    def cancel(self, task_id: str) -> dict[str, Any]:
        task = self._get_task(task_id)
        if task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED}:
            task.add_event("cancel_ignored", "Task already reached a terminal state.")
        else:
            task.status = TaskStatus.CANCELED
            task.result = "Task canceled."
            task.add_event("canceled", "User interrupted the task.")
            if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                try:
                    self.automation.mail.delete_draft(
                        recipient=task.params.get("recipient", ""),
                        subject=task.params.get("subject", ""),
                    )
                except Exception:
                    pass
        self._persist_task(task)
        return task.to_dict()

    def cancel_task(self, task_id: str, reason: str = "") -> dict[str, Any]:
        task = self._get_task(task_id)
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.BLOCKED}:
            task.status = TaskStatus.CANCELED
            task.result = f"Task canceled: {reason}" if reason else "Task canceled."
            task.add_event("canceled", reason or "User interrupted the task.")
            if task.command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
                try:
                    self.automation.mail.delete_draft(
                        recipient=task.params.get("recipient", ""),
                        subject=task.params.get("subject", ""),
                    )
                except Exception:
                    pass
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
    ) -> dict[str, Any]:
        """Programmatic structured editing of a pending draft task."""
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
            task.params["attachments"] = attachments

        draft = EmailDraft(
            recipient=task.params.get("recipient_email") or task.params.get("recipient", ""),
            subject=task.params.get("subject", ""),
            body=task.params.get("formatted_body") or task.params.get("body", ""),
            sender_account=task.params.get("sender_account", ""),
            attachments=task.params.get("attachments", []),
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

    def _summarize_search(self, query: str, results: list[dict[str, str]]) -> str:
        if self.use_gemini and self.api_key:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                formatted = "\n\n".join([
                    f"Title: {r['title']}\nContent: {r['body']}"
                    for r in results if r.get("body")
                ])
                prompt = (
                    f"You are Cortex, a direct AI assistant like Google.\n"
                    f"Answer the question below using ONLY the provided facts. Be concise and direct.\n"
                    f"Rules: Lead with the answer. No preamble. No 'I hope this helps'. Use bullet points for lists.\n\n"
                    f"Question: {query}\n\n"
                    f"Facts:\n{formatted}"
                )
                response = model.generate_content(prompt)
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                print(f"[cortex] Failed to summarize search with Gemini: {e}", file=sys.stderr)

        # Offline fallback: use raw snippets directly
        bodies = [r.get("body", "").strip() for r in results if r.get("body", "").strip()]
        if bodies:
            return bodies[0] if len(bodies) == 1 else bodies[0] + "\n\n" + bodies[1]

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

        if not self.use_gemini:
            lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')} ({e.get('date', 'Recent')})" for e in emails]
            return f"You have {len(emails)} recent emails:\n" + "\n".join(lines)

        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
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
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"[cortex] Failed to summarize emails: {e}", file=sys.stderr)
            lines = [f"• From {e.get('sender', 'Unknown')}: {e.get('subject', 'No subject')}" for e in emails]
            return f"You have {len(emails)} recent emails:\n" + "\n".join(lines)

    def _answer_general_question(self, query: str, lang_code: str = "en") -> str:
        """Google-style direct answering: fact first, explanation after."""
        q_lower = query.lower().strip()

        # 1. Curated offline knowledge base (Instant fact answering for common queries in Indic & English)
        offline_fact = get_offline_knowledge(query, lang_code)
        if offline_fact:
            return offline_fact

        # 2. Greeting / Identity / Status shortcuts in target language
        greeting_words = {
            "hi", "hello", "hey", "namaste", "vanakkam", "namaskara", "namaskaram",
            "ನಮಸ್ಕಾರ", "ಹಲೋ", "ನಮಸ್ತೆ", "ಶುಭೋದಯ", "नमस्ते", "नमस्कार", "प्रणाम", "வணக்கம்", "నమస్కారం"
        }
        is_greeting = (
            q_lower in greeting_words
            or (any(q_lower.startswith(w) for w in ("hi ", "hello", "hey ", "greetings")) and len(q_lower.split()) <= 4)
        )
        is_status = any(p in q_lower for p in (
            "how are you", "ಹೇಗಿದ್ದೀರಿ", "ಹೇಗಿದ್ದೀರಾ", "आप कैसे हैं", "कैसे हो", "क्या हाल है", "எப்படி இருக்கிறீர்கள்", "ఎలా ఉన్నారు", "బాగున్నారా"
        ))
        is_identity = any(p in q_lower for p in (
            "who are you", "what can you do", "ನಿಮ್ಮ ಹೆಸರೇನು", "ನೀವು ಯಾರು", "ನೀವೇನು ಮಾಡಬಲ್ಲಿರಿ", "ಏನು ಮಾಡಬಹುದು",
            "आप कौन हैं", "तुम्हारा नाम क्या है", "आप क्या कर सकते हैं", "நீங்கள் யார்", "మీరు ఎవరు"
        ))

        if is_status:
            return get_cortex_status(lang_code)
        if is_greeting or is_identity:
            return get_cortex_identity(lang_code)

        # 3. Try Gemini — Direct answer
        if self.use_gemini and self.api_key:
            try:
                lang_instr = language_instruction(lang_code)
                system = (
                    "You are Cortex, a powerful AI assistant. Answer like Google — direct, concise, factual.\n"
                    "Rules:\n"
                    "- Lead with the answer immediately. No preamble like 'Great question!' or 'Sure!'.\n"
                    "- Simple facts: 1-2 sentences max.\n"
                    "- Lists/steps: use bullet points.\n"
                    "- Technical questions: include code if relevant.\n"
                    "- NEVER end with 'I hope that helps!' or 'Feel free to ask more!'.\n"
                    "- Match the user's language. If they ask in Hindi, answer in Hindi. Same for Kannada, Tamil, Telugu.\n"
                    "- Never say 'As an AI...' or 'I'm just an AI'.\n"
                    "- You CAN answer any factual question, definition, how-to, news, math, code, science, etc.\n"
                )
                if lang_instr:
                    system += f"\n{lang_instr}\n"

                model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system)

                chat_contents = list(self.history)
                chat_contents.append({"role": "user", "parts": [query]})

                resp = model.generate_content(chat_contents)
                if resp and resp.text:
                    return resp.text.strip()
            except Exception as e:
                print(f"[cortex] Gemini API question error: {e}", file=sys.stderr)

        # 4. Web search fallback for factual queries
        try:
            results = search_web(query, max_results=3)
            if results:
                return self._summarize_search(query, results)
        except Exception as e:
            print(f"[cortex] Knowledge lookup error: {e}", file=sys.stderr)

        return localize("no_confident_answer", lang_code, query=query)

    def _execute(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        task.add_event("running", "Execution started.")
        task.params = task.params or {}

        # ── General Conversation / Knowledge Answering ─────────────────
        if task.command in (TaskCommand.ASK_QUESTION, TaskCommand.UNKNOWN):
            lang = str(task.language.value if task.language else "en")
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
                if self.use_gemini:
                    try:
                        model = genai.GenerativeModel("gemini-1.5-flash")
                        resp = model.generate_content(
                            f"You are Cortex, a warm, caring, and thoughtful AI friend. Answer this query in a natural, friendly, conversational way (2-3 sentences):\n{query}"
                        )
                        task.status = TaskStatus.COMPLETED
                        task.result = resp.text.strip()
                        task.add_event("completed", "Answered using assistant knowledge.")
                        return
                    except Exception as e:
                        print(f"[cortex] Knowledge fallback failed: {e}", file=sys.stderr)
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

    def _get_task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise KeyError(f"Unknown task: {task_id}")
        return self.tasks[task_id]

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
        if command == TaskCommand.SEND_MESSAGE:
            named_saying = re.search(
                r"send\s+(.+?)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message\s+(?:saying|that says|with|:)\s+(.+)",
                text,
                re.IGNORECASE,
            )
            if named_saying:
                recipient = named_saying.group(1).strip()
                body = named_saying.group(2).strip().rstrip(".")
                return {"recipient": recipient, "body": body}
            to_saying = re.search(
                r"(?:send\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message|text|message)\s+(?:to\s+)?(.+?)\s+(?:saying|that says|with|:)\s+(.+)",
                text,
                re.IGNORECASE,
            )
            if to_saying:
                recipient = to_saying.group(1).strip()
                body = to_saying.group(2).strip().rstrip(".")
                return {"recipient": recipient, "body": body}
            named_only = re.search(
                r"send\s+(.+?)\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message",
                text,
                re.IGNORECASE,
            )
            if named_only:
                recipient = named_only.group(1).strip().rstrip(".")
                return {"recipient": recipient, "body": ""}
            to_only = re.search(
                r"(?:send\s+(?:a\s+)?(?:whatsapp|sms|text|imessage)?\s*message|text|message)\s+(?:to\s+)?(.+)",
                text,
                re.IGNORECASE,
            )
            if to_only:
                recipient = to_only.group(1).strip().rstrip(".")
                return {"recipient": recipient, "body": ""}
            return {"recipient": "", "body": ""}
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

            # Indic recipient patterns:
            kn_m = re.search(r"(.+?)(?:ಗೆ|ರಿಗೆ)\s*(?:ಇಮೇಲ್|ಮೇಲ್)\s*(?:ಕಳುಹಿಸು|ಮಾಡು|ಬರೆ)", clean_cmd)
            if kn_m:
                return {"recipient": kn_m.group(1).strip(), "subject": "", "body": ""}
            hi_m = re.search(r"(.+?)\s*को\s*(?:ईमेल|मेल)\s*(?:भेजो|भेजें|करो)", clean_cmd)
            if hi_m:
                return {"recipient": hi_m.group(1).strip(), "subject": "", "body": ""}
            ta_m = re.search(r"(.+?)(?:க்கு|வுக்கு)\s*(?:மின்னஞ்சல்|மெயில்)\s*(?:அனுப்பு)", clean_cmd)
            if ta_m:
                return {"recipient": ta_m.group(1).strip(), "subject": "", "body": ""}
            te_m = re.search(r"(.+?)(?:కి|కు)\s*(?:ఇమెయیل|మెయిల్)\s*(?:పంపు|పంపించు)", clean_cmd)
            if te_m:
                return {"recipient": te_m.group(1).strip(), "subject": "", "body": ""}

            # Extract via robust email engine
            extracted = self.email_engine.extract_command_and_content(text)
            rec = extracted.get("recipient", "").strip()
            email_m = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", rec)
            recipient = email_m.group(1) if email_m else rec
            subj = extracted.get("subject", "")
            body = extracted.get("content", "")

            if not subj and body:
                if any(w in body.lower() for w in ("reach", "arrival")):
                    subj = "Update: Arrival Time"
                elif any(w in body.lower() for w in ("traffic", "late", "delay")):
                    subj = "Update: Running late today"
                elif any(w in body.lower() for w in ("project", "ready", "status")):
                    subj = "Project update"
                elif any(w in body.lower() for w in ("document", "certificate", "marks card")):
                    subj = "Request for Original Academic Documents"

            return {
                "recipient": recipient,
                "subject": subj,
                "body": body,
            }
            return {"recipient": text.strip().rstrip("."), "subject": "", "body": ""}
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
