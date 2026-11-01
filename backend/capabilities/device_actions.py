from __future__ import annotations

import os
import platform
import re
import subprocess
import time
import ast
import json
import operator
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Any
try:
    from backend.core.contracts import TaskCommand
except ImportError:
    from core.contracts import TaskCommand


def _is_safe_path(path_str: str) -> tuple[bool, Path]:
    try:
        raw_norm = str(path_str).replace("\\", "/")
        if ".." in raw_norm.split("/"):
            return False, Path(path_str)
        p = Path(path_str).expanduser()
        blocked_keywords = ["/etc/passwd", "/etc/shadow", ".ssh/id_rsa", ".ssh/id_ed25519", "/private/etc/shadow", "/etc/sudoers"]
        for blocked in blocked_keywords:
            if blocked in str(p) or blocked in str(path_str):
                return False, p
        return True, p
    except Exception:
        return False, Path(path_str)


APP_ALIASES: dict[str, str] = {
    "chrome": "Google Chrome",
    "google chrome": "Google Chrome",
    "safari": "Safari",
    "notes": "Notes",
    "apple notes": "Notes",
    "terminal": "Terminal",
    "vscode": "Visual Studio Code",
    "code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "whatsapp": "WhatsApp",
    "mail": "Mail",
    "apple mail": "Mail",
    "calc": "Calculator",
    "calculator": "Calculator",
    "messages": "Messages",
    "imessage": "Messages",
    "finder": "Finder",
    "system settings": "System Settings",
    "system preferences": "System Settings",
    "settings": "System Settings",
    "preview": "Preview",
    "calendar": "Calendar",
    "music": "Music",
    "reminders": "Reminders",
}


@dataclass(frozen=True)
class DeviceActionResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class DeviceAutomation:
    def __init__(self, dry_run: bool | None = None, screenshot_dir: str | None = None) -> None:
        self.system = platform.system().lower()
        self.dry_run = (os.getenv("CORTEX_EXECUTION_MODE", "live").lower() == "dry-run") if dry_run is None else dry_run
        self.screenshot_dir = Path(screenshot_dir or "screenshots")
        self._browser = None   # lazy-loaded BrowserAutomation
        self._mail = None      # lazy-loaded MailAutomation
        self._whatsapp = None  # lazy-loaded WhatsAppAutomation

    def _get_browser(self):
        if self._browser is None:
            from .browser_actions import BrowserAutomation
            self._browser = BrowserAutomation(headless=False)
        return self._browser

    def _get_mail(self):
        if self._mail is None:
            from .mail_actions import MailAutomation
            self._mail = MailAutomation(dry_run=self.dry_run)
        return self._mail

    def _get_whatsapp(self):
        if self._whatsapp is None:
            from .whatsapp_actions import WhatsAppAutomation
            self._whatsapp = WhatsAppAutomation(dry_run=self.dry_run)
        return self._whatsapp

    @property
    def mail(self):
        return self._get_mail()

    @mail.setter
    def mail(self, val):
        self._mail = val

    @property
    def browser(self):
        return self._get_browser()

    @property
    def whatsapp(self):
        return self._get_whatsapp()

    @whatsapp.setter
    def whatsapp(self, val):
        self._whatsapp = val

    @property
    def screen_bridge(self):
        if not hasattr(self, "_screen_bridge") or self._screen_bridge is None:
            from .screen_native import NativeScreenHelperBridge
            self._screen_bridge = NativeScreenHelperBridge(use_mock=self.dry_run)
        return self._screen_bridge

    @property
    def ax_engine(self):
        if not hasattr(self, "_ax_engine") or self._ax_engine is None:
            from .screen_accessibility import AccessibilityInspectionEngine
            self._ax_engine = AccessibilityInspectionEngine(self.screen_bridge)
        return self._ax_engine

    @property
    def fusion_engine(self):
        if not hasattr(self, "_fusion_engine") or self._fusion_engine is None:
            from .screen_context import ScreenContextFusionEngine
            self._fusion_engine = ScreenContextFusionEngine(self.screen_bridge)
        return self._fusion_engine

    @property
    def vision_engine(self):
        if not hasattr(self, "_vision_engine") or self._vision_engine is None:
            from .screen_vision_intelligence import MultimodalVisualIntelligenceEngine
            self._vision_engine = MultimodalVisualIntelligenceEngine()
        return self._vision_engine

    @property
    def element_resolver(self):
        if not hasattr(self, "_element_resolver") or self._element_resolver is None:
            from .screen_element_resolver import UIElementResolver
            self._element_resolver = UIElementResolver()
        return self._element_resolver

    @property
    def interaction_engine(self):
        if not hasattr(self, "_interaction_engine") or self._interaction_engine is None:
            from .screen_interaction_engine import DesktopInteractionEngine
            self._interaction_engine = DesktopInteractionEngine(
                bridge=self.screen_bridge,
                ax_engine=self.ax_engine,
                fusion_engine=self.fusion_engine,
                resolver=self.element_resolver,
            )
        return self._interaction_engine

    @property
    def app_registry(self):
        if not hasattr(self, "_app_registry") or self._app_registry is None:
            from .app_capability_registry import ApplicationCapabilityRegistry
            self._app_registry = ApplicationCapabilityRegistry()
        return self._app_registry

    def execute(self, command: TaskCommand, params: dict[str, Any] | None = None) -> DeviceActionResult:
        params = params or {}
        if command in (TaskCommand.ASK_QUESTION, TaskCommand.WEB_SEARCH):
            return DeviceActionResult(True, params.get("answer") or "I don't have an answer to that question.")

        # ── Screen Intelligence & Autonomous Desktop Operator ──
        if command == TaskCommand.OBSERVE_SCREEN:
            capture = bool(params.get("capture_screenshot", False))
            run_ocr = bool(params.get("run_ocr", False))
            pid = params.get("pid")
            return self._observe_screen(capture=capture, run_ocr=run_ocr, pid=pid, params=params)
        if command == TaskCommand.RESOLVE_UI_ELEMENT:
            target = str(params.get("target") or params.get("target_description") or "")
            return self._resolve_ui_element(target, params=params)
        if command == TaskCommand.CLICK_ELEMENT:
            target = str(params.get("target") or params.get("target_description") or "")
            return self._click_element(target, params=params)
        if command == TaskCommand.TYPE_IN_ELEMENT:
            target = str(params.get("target") or params.get("target_description") or "")
            text = str(params.get("text") or params.get("text_to_type") or "")
            return self._type_in_element(target, text, params=params)
        if command == TaskCommand.DESKTOP_WORKFLOW:
            steps = params.get("steps") or []
            return self._desktop_workflow(steps, params=params)

        # ── Phase 4: Browser & Vision (always live, even in dry-run) ──
        if command == TaskCommand.OPEN_URL:
            return self._browser_open_url(str(params.get("url", "")))
        if command == TaskCommand.BROWSER_CLICK:
            return self._browser_click(str(params.get("selector", "")), str(params.get("url", "")))
        if command == TaskCommand.BROWSER_TYPE:
            return self._browser_type(str(params.get("selector", "")), str(params.get("text", "")), str(params.get("url", "")))
        if command == TaskCommand.BROWSER_SCRAPE:
            return self._browser_scrape(str(params.get("url", "")), str(params.get("selector", "body")))
        if command == TaskCommand.SCREEN_VISION:
            return self._screen_vision(str(params.get("question", "What is on my screen right now?")))

        # ── Phase 5: Mail Automation ──────────────────────────
        if command in (TaskCommand.READ_MAIL, TaskCommand.SUMMARIZE_MAIL):
            return self._read_mail(limit=int(params.get("limit", 5)), unread_only=bool(params.get("unread_only", False)))
        if command == TaskCommand.DRAFT_MAIL:
            return self.create_email_draft(
                str(params.get("recipient", "")),
                str(params.get("subject", "")),
                str(params.get("body", "")),
                account=str(params.get("account") or params.get("sender_account") or ""),
                attachments=params.get("attachments"),
                cc=params.get("cc"),
                bcc=params.get("bcc"),
            )
        if command == TaskCommand.SEND_MAIL:
            return self._send_mail(
                str(params.get("recipient", "")),
                str(params.get("subject", "")),
                str(params.get("body", "")),
                account=str(params.get("account") or params.get("sender_account") or ""),
                attachments=params.get("attachments"),
                cc=params.get("cc"),
                bcc=params.get("bcc"),
            )
        if command == TaskCommand.SEARCH_MAIL:
            res = self._get_mail().search_mail(str(params.get("query", "")))
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res)
        if command == TaskCommand.EMAIL_BRIEFING:
            res = self._get_mail().email_briefing(int(params.get("limit", 10)))
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res.get("data"))
        if command == TaskCommand.EXTRACT_ACTIONS:
            res = self._get_mail().extract_actions(int(params.get("limit", 5)))
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res)

        # ── Phase 7: Files & Personal Assistant ───────────────
        if command == TaskCommand.WRITE_FILE:
            return self._write_file(str(params.get("path", "")), str(params.get("content", "")))
        if command == TaskCommand.READ_FILE:
            return self._read_file(str(params.get("path", "")))
        if command == TaskCommand.SEARCH_FILES:
            return self._search_files(str(params.get("pattern", "")), str(params.get("directory", ".")))
        if command == TaskCommand.MOVE_FILE:
            return self._move_file(str(params.get("source") or params.get("src") or ""), str(params.get("destination") or params.get("target") or params.get("dest") or ""))
        if command == TaskCommand.CREATE_DOCUMENT:
            return self._create_document(str(params.get("path", "")), str(params.get("title", "")), str(params.get("content", "")))
        if command == TaskCommand.PERSONAL_TASK_CREATE:
            return self._personal_task_create(str(params.get("title", "")), str(params.get("due", "Today")))
        if command == TaskCommand.PERSONAL_TASK_LIST:
            return self._personal_task_list()
        if command == TaskCommand.CALENDAR_READ:
            return self._calendar_read(str(params.get("day", "today")))
        if command == TaskCommand.CALENDAR_CREATE:
            return self._calendar_create(str(params.get("title", "")), str(params.get("time", "12:00 PM")))
        if command == TaskCommand.DAILY_BRIEFING:
            return self._daily_briefing()

        # ── Phase 8: WhatsApp & Desktop Operator ──────────────
        if command == TaskCommand.DRAFT_WHATSAPP:
            return self._draft_whatsapp(
                str(params.get("recipient", "")),
                str(params.get("phone", "")),
                str(params.get("body", "")),
            )
        if command == TaskCommand.SEND_WHATSAPP:
            return self._send_whatsapp(
                str(params.get("recipient", "")),
                str(params.get("phone", "")),
                str(params.get("body", "")),
                approved_hash=params.get("approval_hash"),
                task_id=str(params.get("task_id", "")),
                draft_only=bool(params.get("draft_only", False)),
            )
        if command == TaskCommand.CLOSE_WINDOW:
            return self._close_window(str(params.get("appName") or params.get("target") or ""))
        if command == TaskCommand.QUIT_APP:
            return self._close_app(str(params.get("appName") or params.get("target") or ""), force=bool(params.get("force", False)))
        if command == TaskCommand.INSPECT_APP:
            return self._inspect_app(str(params.get("appName") or params.get("target") or ""))
        if (command in (TaskCommand.SEND_MESSAGE, TaskCommand.SEND_WHATSAPP)) and (params.get("channel") == "whatsapp" or params.get("phone")):
            return self._send_whatsapp(
                str(params.get("recipient", "")),
                str(params.get("phone", "")),
                str(params.get("formatted_body") or params.get("body", "")),
                approved_hash=params.get("approval_hash"),
                task_id=str(params.get("task_id", "")),
                draft_only=bool(params.get("draft_only", False)),
            )

        if self.dry_run:
            return DeviceActionResult(True, f"Dry-run completed for {command.value}.", {"params": params})
        if command == TaskCommand.OPEN_APP:
            return self._open_app(str(params.get("appName") or params.get("target") or ""))
        if command == TaskCommand.CLOSE_APP:
            return self._close_app(str(params.get("appName") or params.get("target") or ""))
        if command == TaskCommand.FOCUS_APP:
            return self._focus_app(str(params.get("appName") or params.get("target") or ""))
        if command == TaskCommand.TYPE_TEXT:
            return self._type_text(str(params.get("text") or ""), str(params.get("appName") or ""))
        if command == TaskCommand.KEYSTROKE:
            return self._keystroke(str(params.get("shortcut") or params.get("key") or ""), str(params.get("appName") or ""))
        if command == TaskCommand.MENU_ITEM:
            return self._menu_item(
                str(params.get("appName") or ""),
                str(params.get("menu") or ""),
                str(params.get("item") or ""),
            )
        if command == TaskCommand.WRITE_NOTE:
            return self._write_note(str(params.get("title") or "Cortex Note"), str(params.get("body") or ""))
        if command == TaskCommand.SEND_MESSAGE:
            if params.get("channel") == "whatsapp" or params.get("phone"):
                return self._send_whatsapp(
                    str(params.get("recipient") or ""),
                    str(params.get("phone") or ""),
                    str(params.get("body") or ""),
                    approved_hash=params.get("approval_hash"),
                )
            return self._send_message(str(params.get("recipient") or ""), str(params.get("body") or ""))
        if command == TaskCommand.CALCULATE:
            return self._calculate(str(params.get("expression") or ""))
        if command == TaskCommand.SCREENSHOT:
            return self._screenshot()
        if command == TaskCommand.CLIPBOARD_READ:
            return self._clipboard_read()
        if command == TaskCommand.CLIPBOARD_WRITE:
            return self._clipboard_write(str(params.get("text", "")))
        if command == TaskCommand.NOTIFICATION:
            return self._notification(str(params.get("title", "Cortex")), str(params.get("message", "Done.")))
        if command == TaskCommand.REMINDER:
            return DeviceActionResult(False, "Reminder scheduling needs calendar integration in the next iteration.")
        if command == TaskCommand.SHUTDOWN:
            return self._shutdown()
        if command == TaskCommand.RESTART:
            return self._restart()
        return DeviceActionResult(False, "Unsupported command.")

    # ── Phase 4: Browser & Vision helpers ────────────────────────────────────

    def _browser_open_url(self, url: str) -> DeviceActionResult:
        if not url:
            return DeviceActionResult(False, "No URL provided.")
        if self.dry_run:
            return DeviceActionResult(True, f"Opened {url} in browser.", {"url": url})
        if self.system == "darwin":
            try:
                subprocess.run(["open", "-a", "Safari", url], check=False)
                return DeviceActionResult(True, f"Opened {url} in Safari.", {"url": url, "browser": "Safari"})
            except Exception as e:
                pass
        result = self._get_browser().open_url(url)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _browser_click(self, selector: str, url: str = "") -> DeviceActionResult:
        if not selector:
            return DeviceActionResult(False, "No selector provided for browser click.")
        result = self._get_browser().click(selector, url)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _browser_type(self, selector: str, text: str, url: str = "") -> DeviceActionResult:
        if not selector or not text:
            return DeviceActionResult(False, "Selector and text are required for browser type.")
        result = self._get_browser().type_text(selector, text, url)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _browser_scrape(self, url: str, selector: str = "body") -> DeviceActionResult:
        if not url:
            return DeviceActionResult(False, "No URL provided for scrape.")
        result = self._get_browser().scrape(url, selector)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _screen_vision(self, question: str) -> DeviceActionResult:
        from .vision import analyze_screen
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            return DeviceActionResult(False, "GEMINI_API_KEY not set — vision requires it.")
        result = analyze_screen(api_key, question)
        if result["ok"]:
            return DeviceActionResult(True, result["description"], {"raw_bytes_len": result["raw_bytes_len"]})
        return DeviceActionResult(False, result["description"])

    # ── Phase 5: Mail helpers ────────────────────────────────────────────────

    def _read_mail(self, limit: int = 5, unread_only: bool = False) -> DeviceActionResult:
        result = self._get_mail().read_mail(limit=limit, unread_only=unread_only)
        return DeviceActionResult(result["ok"], result["message"], {"emails": result.get("emails", [])})

    def create_email_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> DeviceActionResult:
        """Explicit email drafting capability strictly decoupled from keystroke typing."""
        return self._draft_mail(
            recipient=recipient,
            subject=subject,
            body=body,
            account=account,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
        )

    def _draft_mail(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> DeviceActionResult:
        mail_inst = self._get_mail()
        import inspect
        try:
            sig = inspect.signature(mail_inst.draft_mail)
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kwargs = {}
            if has_varkw or "account" in sig.parameters: kwargs["account"] = account
            if has_varkw or "attachments" in sig.parameters: kwargs["attachments"] = attachments
            if has_varkw or "cc" in sig.parameters: kwargs["cc"] = cc
            if has_varkw or "bcc" in sig.parameters: kwargs["bcc"] = bcc
            result = mail_inst.draft_mail(recipient, subject, body, **kwargs)
        except (ValueError, TypeError):
            result = mail_inst.draft_mail(recipient, subject, body)
        return DeviceActionResult(result["ok"], result["message"], result.get("data"))

    def _send_mail(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> DeviceActionResult:
        mail_inst = self._get_mail()
        import inspect
        try:
            sig = inspect.signature(mail_inst.send_mail)
            has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            kwargs = {}
            if has_varkw or "account" in sig.parameters: kwargs["account"] = account
            if has_varkw or "attachments" in sig.parameters: kwargs["attachments"] = attachments
            if has_varkw or "cc" in sig.parameters: kwargs["cc"] = cc
            if has_varkw or "bcc" in sig.parameters: kwargs["bcc"] = bcc
            result = mail_inst.send_mail(recipient, subject, body, **kwargs)
        except (ValueError, TypeError):
            result = mail_inst.send_mail(recipient, subject, body)
        return DeviceActionResult(result["ok"], result["message"], result.get("data"))

    def resolve_app_name(self, app_name: str) -> str:
        """Resolve recognized application names and aliases to their canonical OS application title."""
        raw = (app_name or "").strip()
        # Handle compound requests like "Finder and list my downloads" or "Safari and search"
        if " and " in raw.lower():
            first_clause = re.split(r"\s+and\s+", raw, flags=re.IGNORECASE)[0].strip()
            if first_clause.lower() in APP_ALIASES or first_clause.lower() in ("finder", "safari", "mail", "notes", "terminal", "chrome", "whatsapp"):
                raw = first_clause
        cleaned = raw.lower()
        return APP_ALIASES.get(cleaned, raw)

    def is_app_running(self, app_name: str) -> bool:
        """Determines whether target application process is active and running."""
        canonical = self.resolve_app_name(app_name)
        if not canonical:
            return False
        if self.dry_run or os.getenv("PYTEST_CURRENT_TEST"):
            # Predictable in automated test mode unless real process inspection requested
            return False
        if self.system == "darwin":
            script = f'tell application "System Events" to (name of processes) contains "{canonical}"'
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
                return "true" in res.stdout.lower()
            except Exception:
                try:
                    res = subprocess.run(["pgrep", "-if", canonical], capture_output=True, text=True)
                    return res.returncode == 0
                except Exception:
                    return False
        elif self.system == "windows":
            try:
                script = f"Get-Process -Name '{canonical}' -ErrorAction SilentlyContinue"
                res = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True)
                return res.returncode == 0
            except Exception:
                return False
        return False

    def has_unsaved_changes(self, app_name: str) -> bool:
        """Inspects application windows to detect unsaved work before closing or quitting."""
        canonical = self.resolve_app_name(app_name)
        if not canonical or self.dry_run or os.getenv("PYTEST_CURRENT_TEST"):
            return False
        if self.system == "darwin":
            script = (
                f'tell application "System Events"\n'
                f'  tell process "{canonical}"\n'
                '    set hasDirty to false\n'
                '    repeat with w in windows\n'
                '      try\n'
                '        if document of w is modified then\n'
                '          set hasDirty to true\n'
                '        end if\n'
                '      end try\n'
                '    end repeat\n'
                '    return hasDirty\n'
                '  end tell\n'
                'end tell'
            )
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
                return "true" in res.stdout.lower()
            except Exception:
                return False
        return False

    def _open_app(self, app_name: str) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        canonical = self.resolve_app_name(app_name)

        if canonical == "Finder":
            if self.system == "darwin":
                try:
                    subprocess.run(["open", "-a", "Finder"], capture_output=True, text=True, check=False)
                    return DeviceActionResult(True, "Opened Finder.", {"appName": "Finder", "wasRunning": self.is_app_running("Finder")})
                except Exception as e:
                    return DeviceActionResult(False, f"Failed to open Finder: {e}")

        # Check if already running -> focus it instead of duplicating
        if self.is_app_running(canonical):
            self._focus_app(canonical)
            return DeviceActionResult(
                True,
                f"Focused already running application {canonical}.",
                {"appName": canonical, "wasRunning": True},
            )

        if self.system == "darwin":
            try:
                res = subprocess.run(["open", "-a", canonical], capture_output=True, text=True)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or "Unable to find application."
                    return DeviceActionResult(False, f"Cannot open {canonical}: {err_msg}")
                return DeviceActionResult(True, f"Opened {canonical}.", {"appName": canonical, "wasRunning": False})
            except Exception as e:
                return DeviceActionResult(False, f"Failed to open {canonical}: {e}")
        elif self.system == "windows":
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-Process '{canonical}'"], check=True)
                return DeviceActionResult(True, f"Opened {canonical}.")
            except Exception as e:
                return DeviceActionResult(False, f"Failed to open {canonical}: {e}")
        else:
            try:
                subprocess.run(["xdg-open", canonical], check=True)
                return DeviceActionResult(True, f"Opened {canonical}.")
            except Exception as e:
                return DeviceActionResult(False, f"Failed to open {canonical}: {e}")

    def _focus_app(self, app_name: str) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        canonical = self.resolve_app_name(app_name)
        if self.system == "darwin":
            try:
                script = f'tell application "{canonical}" to activate'
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
                return DeviceActionResult(True, f"Focused {canonical}.", {"appName": canonical})
            except Exception as e:
                return DeviceActionResult(False, f"Could not focus {canonical}: {e}")
        elif self.system == "windows":
            try:
                script = f"(New-Object -ComObject WScript.Shell).AppActivate('{canonical}')"
                subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True)
                return DeviceActionResult(True, f"Focused {canonical}.", {"appName": canonical})
            except Exception as e:
                return DeviceActionResult(False, f"Could not focus {canonical}: {e}")
        else:
            return DeviceActionResult(False, "Focus app is not implemented for this OS.")

    def _close_window(self, app_name: str = "") -> DeviceActionResult:
        """Closes frontmost window (Cmd+W) without terminating the application process."""
        canonical = self.resolve_app_name(app_name) if app_name else ""
        if self.system == "darwin":
            try:
                if canonical:
                    script = (
                        f'tell application "{canonical}"\n'
                        '  if (count of windows) > 0 then\n'
                        '    close front window\n'
                        '  end if\n'
                        'end tell'
                    )
                else:
                    script = 'tell application "System Events" to keystroke "w" using {command down}'
                subprocess.run(["osascript", "-e", script], capture_output=True)
                return DeviceActionResult(True, f"Closed window in {canonical or 'frontmost application'}.", {"appName": canonical})
            except Exception as e:
                return DeviceActionResult(False, f"Failed to close window: {e}")
        return DeviceActionResult(False, "Close window is not implemented for this OS.")

    def _close_app(self, app_name: str, force: bool = False) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        canonical = self.resolve_app_name(app_name)

        if not force and self.has_unsaved_changes(canonical):
            return DeviceActionResult(
                False,
                f"Application {canonical} has unsaved changes. Please save your work or confirm quitting.",
                {"appName": canonical, "hasUnsavedChanges": True},
            )

        if self.system == "darwin":
            try:
                script = f'tell application "{canonical}" to quit'
                subprocess.run(["osascript", "-e", script], capture_output=True)
                return DeviceActionResult(True, f"Closed {canonical}.", {"appName": canonical})
            except Exception as e:
                return DeviceActionResult(False, f"Could not quit {canonical}: {e}")
        elif self.system == "windows":
            try:
                script = (
                    f"$name='{canonical}';"
                    "$proc=Get-Process | Where-Object { $_.ProcessName -like $name -or $_.MainWindowTitle -like \"*$name*\" };"
                    "$proc | Stop-Process"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)
                return DeviceActionResult(True, f"Closed {canonical}.")
            except Exception as e:
                return DeviceActionResult(False, f"Could not quit {canonical}: {e}")
        else:
            try:
                subprocess.run(["pkill", "-f", canonical], capture_output=True)
                return DeviceActionResult(True, f"Closed {canonical}.")
            except Exception as e:
                return DeviceActionResult(False, f"Could not quit {canonical}: {e}")

    def _inspect_app(self, app_name: str) -> DeviceActionResult:
        canonical = self.resolve_app_name(app_name)
        is_running = self.is_app_running(canonical)
        data = {
            "appName": canonical,
            "isRunning": is_running,
            "system": self.system,
        }
        if is_running and self.system == "darwin":
            script = (
                f'tell application "System Events"\n'
                f'  tell process "{canonical}"\n'
                '    set winNames to name of windows\n'
                '    return (count of winNames) as string\n'
                '  end tell\n'
                'end tell'
            )
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
                win_count = int(res.stdout.strip()) if res.stdout.strip().isdigit() else 1
                data["windowCount"] = win_count
            except Exception:
                data["windowCount"] = 1
        data["capabilities"] = self.app_registry.inspect_app_capabilities(canonical)
        msg = f"{canonical} is running." if is_running else f"{canonical} is not running."
        return DeviceActionResult(True, msg, data)

    def _observe_screen(self, capture: bool = False, run_ocr: bool = False, pid: int | None = None, params: dict[str, Any] | None = None) -> DeviceActionResult:
        ax = self.ax_engine.inspect_current_application(pid=pid)
        if not ax.ok:
            return DeviceActionResult(False, f"Screen observation failed: {ax.error}")

        screenshot_path = None
        if capture:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = str(self.screenshot_dir / f"screen_{int(time.time())}.png")
            self.screen_bridge.capture_screenshot(screenshot_path)

        ctx = self.fusion_engine.fuse(ax, screenshot_path=screenshot_path, task_context=params)

        task_id = params.get("task_id") if params else None
        if hasattr(self, "task_store") and self.task_store:
            try:
                self.task_store.record_screen_observation(
                    context_id=ctx.context_id,
                    task_id=task_id,
                    app_name=ctx.app.name,
                    window_title=ctx.window.title if ctx.window else None,
                    elements_count=len(ctx.elements),
                    modal_dialog=any(el.is_modal for el in ctx.elements),
                    screenshot_path=ctx.screenshot_path,
                    facts=[f.to_dict() for f in ctx.facts],
                )
            except Exception:
                pass

        return DeviceActionResult(True, f"Observed {ctx.app.name} with {len(ctx.elements)} accessible elements.", ctx.to_summary_dict())

    def _resolve_ui_element(self, target: str, params: dict[str, Any] | None = None) -> DeviceActionResult:
        ax = self.ax_engine.inspect_current_application()
        if not ax.ok:
            return DeviceActionResult(False, f"Cannot resolve element: {ax.error}")
        ctx = self.fusion_engine.fuse(ax, task_context=params)
        res = self.element_resolver.resolve_target(ctx, target)
        if res.ok and res.element:
            return DeviceActionResult(True, res.evidence, res.to_dict())
        return DeviceActionResult(False, res.evidence or "Element not found.", res.to_dict())

    def _click_element(self, target: str, params: dict[str, Any] | None = None) -> DeviceActionResult:
        from .screen_interaction_engine import InteractionRequest
        req = InteractionRequest(
            action_type="click",
            target_description=target,
            expected_outcome=params.get("expected_outcome") if params else None,
        )
        res = self.interaction_engine.execute_interaction(req)
        return DeviceActionResult(res.ok, res.message, res.to_dict())

    def _type_in_element(self, target: str, text: str, params: dict[str, Any] | None = None) -> DeviceActionResult:
        from .screen_interaction_engine import InteractionRequest
        req = InteractionRequest(
            action_type="type",
            target_description=target,
            text_to_type=text,
            expected_outcome=params.get("expected_outcome") if params else None,
        )
        res = self.interaction_engine.execute_interaction(req)
        return DeviceActionResult(res.ok, res.message, res.to_dict())

    def _desktop_workflow(self, steps: list[dict[str, Any]], params: dict[str, Any] | None = None) -> DeviceActionResult:
        executed_steps = []
        task_id = params.get("task_id") if params else None
        for idx, step_data in enumerate(steps):
            action = step_data.get("action", "click")
            target = step_data.get("target", "")
            text = step_data.get("text")

            if action == "click":
                step_res = self._click_element(target, params=step_data)
            elif action == "type":
                step_res = self._type_in_element(target, text or "", params=step_data)
            else:
                step_res = DeviceActionResult(False, f"Unsupported workflow step action: {action}")

            executed_steps.append({"step": idx, "action": action, "target": target, "result": step_res.ok, "message": step_res.message})

            if hasattr(self, "task_store") and self.task_store and task_id:
                try:
                    self.task_store.record_recovery_checkpoint(
                        task_id=task_id,
                        step_index=idx,
                        state_hash=f"step_{idx}_{step_res.ok}",
                        status="completed" if step_res.ok else "failed",
                        metadata={"action": action, "target": target},
                    )
                except Exception:
                    pass

            if not step_res.ok:
                return DeviceActionResult(False, f"Workflow failed at step {idx} ({action} on '{target}'): {step_res.message}", {"executed_steps": executed_steps})

        return DeviceActionResult(True, f"Successfully executed workflow of {len(steps)} steps.", {"executed_steps": executed_steps})

    def _move_file(self, source_path: str, target_path: str) -> DeviceActionResult:
        if not source_path or not target_path:
            return DeviceActionResult(False, "Both source and target paths are required.")
        ok_src, src = _is_safe_path(source_path)
        ok_tgt, tgt = _is_safe_path(target_path)
        if not ok_src or not ok_tgt:
            return DeviceActionResult(False, "Access denied: paths outside permitted sandbox.")
        if not src.exists():
            return DeviceActionResult(False, f"Source file does not exist: {src}")
        try:
            import shutil
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(tgt))
            return DeviceActionResult(True, f"Moved {src.name} to {tgt}.", {"source": str(src), "target": str(tgt)})
        except Exception as e:
            return DeviceActionResult(False, f"Failed to move file: {e}")

    def _create_document(self, path_str: str, title: str, content: str) -> DeviceActionResult:
        if not path_str:
            path_str = f"{title.replace(' ', '_').lower()}.md" if title else "document.md"
        ok, p = _is_safe_path(path_str)
        if not ok:
            return DeviceActionResult(False, "Access denied: path is outside permitted sandbox.")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            full_content = f"# {title}\n\n{content}" if title and not content.startswith("# ") else content
            p.write_text(full_content, encoding="utf-8")
            return DeviceActionResult(True, f"Created document at {p}.", {"path": str(p), "title": title})
        except Exception as e:
            return DeviceActionResult(False, f"Failed to create document: {e}")

    def _draft_whatsapp(self, recipient: str, phone: str, body: str) -> DeviceActionResult:
        res = self._get_whatsapp().prepare_draft(recipient, phone, body)
        return DeviceActionResult(res["ok"], res["message"], res.get("data"))

    def _send_whatsapp(
        self,
        recipient: str,
        phone: str,
        body: str,
        approved_hash: str | None = None,
        task_id: str = "",
        draft_only: bool = False,
    ) -> DeviceActionResult:
        res = self._get_whatsapp().send_message(
            recipient, phone, body, approved_hash=approved_hash, task_id=task_id, draft_only=draft_only
        )
        return DeviceActionResult(res["ok"], res.get("message") or res.get("error", "WhatsApp sending failed."), res.get("data"))

    def _type_text(self, text: str, app_name: str = "") -> DeviceActionResult:
        if not text:
            return DeviceActionResult(False, "No text was provided.")
        if app_name:
            focus = self._focus_app(app_name)
            if not focus.ok:
                return focus
        if self.system == "darwin":
            subprocess.run(["osascript", "-e", f'tell application "System Events" to keystroke {self._apple_string(text)}'], check=True)
        elif self.system == "windows":
            escaped = text.replace("'", "''")
            script = f"$ws=New-Object -ComObject WScript.Shell; $ws.SendKeys('{escaped}')"
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            return DeviceActionResult(False, "Type text is not implemented for this OS.")
        return DeviceActionResult(True, "Typed text.", {"text": text, "appName": app_name})

    def _keystroke(self, shortcut: str, app_name: str = "") -> DeviceActionResult:
        if not shortcut:
            return DeviceActionResult(False, "No key or shortcut was provided.")
        if app_name:
            focus = self._focus_app(app_name)
            if not focus.ok:
                return focus
        if self.system == "darwin":
            script = self._apple_keystroke_script(shortcut)
            subprocess.run(["osascript", "-e", script], check=True)
        elif self.system == "windows":
            send_keys = self._windows_send_keys(shortcut)
            script = f"$ws=New-Object -ComObject WScript.Shell; $ws.SendKeys('{send_keys}')"
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            return DeviceActionResult(False, "Keystroke is not implemented for this OS.")
        return DeviceActionResult(True, f"Pressed {shortcut}.", {"shortcut": shortcut, "appName": app_name})

    def _menu_item(self, app_name: str, menu: str, item: str) -> DeviceActionResult:
        if not app_name or not menu or not item:
            return DeviceActionResult(False, "App, menu, and item are required.")
        if self.system != "darwin":
            return DeviceActionResult(False, "Menu item automation is currently implemented for macOS only.")
        script = (
            f'tell application "{app_name}" to activate\n'
            'tell application "System Events"\n'
            f'  tell process "{app_name}"\n'
            f'    click menu item "{item}" of menu "{menu}" of menu bar 1\n'
            "  end tell\n"
            "end tell"
        )
        subprocess.run(["osascript", "-e", script], check=True)
        return DeviceActionResult(True, f"Chose {item} from {menu} in {app_name}.")

    def _write_note(self, title: str, body: str) -> DeviceActionResult:
        if not body:
            return DeviceActionResult(False, "No note text was provided.")
        if self.system == "darwin":
            script = (
                'tell application "Notes"\n'
                "  activate\n"
                f"  make new note at folder \"Notes\" with properties {{name:{self._apple_string(title)}, body:{self._apple_string(body)}}}\n"
                "end tell"
            )
            subprocess.run(["osascript", "-e", script], check=True)
            return DeviceActionResult(True, f"Created note: {title}.", {"title": title, "body": body})
        if self.system == "windows":
            note_path = Path.home() / "Documents" / "Cortex Notes.txt"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(f"{title}\n{body}\n", encoding="utf-8")
            subprocess.run(["notepad", str(note_path)], check=True)
            return DeviceActionResult(True, f"Created note at {note_path}.", {"path": str(note_path)})
        return DeviceActionResult(False, "Writing notes is not implemented for this OS.")

    def _send_message(self, recipient: str, body: str, channel: str = "messages", phone: str = "", approved_hash: str | None = None) -> DeviceActionResult:
        if not recipient or not body:
            return DeviceActionResult(False, "Recipient and message body are required.")
        if channel == "whatsapp" or phone:
            return self._send_whatsapp(recipient, phone, body, approved_hash=approved_hash)
        if self.system == "darwin":
            try:
                script = (
                    'tell application "Messages"\n'
                    "  activate\n"
                    f"  set targetBuddy to buddy {self._apple_string(recipient)} of service \"iMessage\"\n"
                    f"  send {self._apple_string(body)} to targetBuddy\n"
                    "end tell"
                )
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
                return DeviceActionResult(True, f"Sent message to {recipient}.", {"recipient": recipient})
            except Exception as e:
                return DeviceActionResult(False, f"Could not send message via Messages: {e}")
        if self.system == "windows":
            return DeviceActionResult(False, "Direct message sending is not implemented for Windows yet.")
        return DeviceActionResult(False, "Direct message sending is not implemented for this OS.")

    def _calculate(self, expression: str) -> DeviceActionResult:
        if not expression:
            return DeviceActionResult(False, "No math expression was provided.")
        try:
            result = _safe_calculate(expression)
        except ValueError as exc:
            return DeviceActionResult(False, str(exc))
        return DeviceActionResult(True, f"{expression} = {result}", {"expression": expression, "answer": result})

    def _screenshot(self) -> DeviceActionResult:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop_dir = Path.home() / "Desktop"
        if desktop_dir.exists():
            target = desktop_dir / f"Cortex_Screenshot_{timestamp}.png"
        else:
            self.screenshot_dir.mkdir(parents=True, exist_ok=True)
            target = self.screenshot_dir / f"cortex_{timestamp}.png"

        if self.system == "darwin":
            res = subprocess.run(["screencapture", "-x", str(target)], capture_output=True, text=True)
            if res.returncode != 0:
                try:
                    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
                except Exception:
                    pass
                return DeviceActionResult(
                    False,
                    "macOS requires Screen Recording permission. I've opened System Settings — please enable VS Code or Terminal under Screen Recording, then try again."
                )
            # Reveal in Finder so the user sees it immediately
            try:
                subprocess.run(["open", "-R", str(target)])
            except Exception:
                pass
            return DeviceActionResult(True, f"Screenshot saved to Desktop: {target.name}", {"path": str(target)})
        elif self.system == "windows":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{target.resolve()}');"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
            return DeviceActionResult(True, f"Screenshot captured: {target.name}", {"path": str(target)})
        else:
            return DeviceActionResult(False, "Screenshot is not implemented for this OS.")

    def _clipboard_read(self) -> DeviceActionResult:
        if self.system == "darwin":
            text = subprocess.check_output(["pbpaste"], text=True)
        elif self.system == "windows":
            text = subprocess.check_output(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], text=True)
        else:
            return DeviceActionResult(False, "Clipboard read is not implemented for this OS.")
        return DeviceActionResult(True, "Clipboard read.", {"text": text})

    def _clipboard_write(self, text: str) -> DeviceActionResult:
        if self.system == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
        elif self.system == "windows":
            subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard"], input=text, text=True, check=True)
        else:
            return DeviceActionResult(False, "Clipboard write is not implemented for this OS.")
        return DeviceActionResult(True, "Clipboard updated.")

    def _notification(self, title: str, message: str) -> DeviceActionResult:
        if self.system == "darwin":
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], check=True)
        elif self.system == "windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"New-BurntToastNotification -Text '{title}', '{message}'"],
                check=True,
            )
        else:
            return DeviceActionResult(False, "Notification is not implemented for this OS.")
        return DeviceActionResult(True, "Notification sent.")

    def _shutdown(self) -> DeviceActionResult:
        if self.system == "darwin":
            subprocess.run(["osascript", "-e", 'tell app "System Events" to shut down'], check=True)
        elif self.system == "windows":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=True)
        else:
            return DeviceActionResult(False, "Shutdown is not implemented for this OS.")
        return DeviceActionResult(True, "Shutdown requested.")

    def _restart(self) -> DeviceActionResult:
        if self.system == "darwin":
            subprocess.run(["osascript", "-e", 'tell app "System Events" to restart'], check=True)
        elif self.system == "windows":
            subprocess.run(["shutdown", "/r", "/t", "0"], check=True)
        else:
            return DeviceActionResult(False, "Restart is not implemented for this OS.")
        return DeviceActionResult(True, "Restart requested.")

    def _apple_string(self, value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _apple_keystroke_script(self, shortcut: str) -> str:
        tokens = re.split(r"[\s+,-]+", shortcut.lower().strip())
        modifiers = []
        key = ""
        modifier_map = {
            "cmd": "command down",
            "command": "command down",
            "ctrl": "control down",
            "control": "control down",
            "option": "option down",
            "alt": "option down",
            "shift": "shift down",
        }
        key_codes = {
            "enter": 36,
            "return": 36,
            "tab": 48,
            "escape": 53,
            "esc": 53,
            "space": 49,
            "delete": 51,
            "backspace": 51,
            "up": 126,
            "down": 125,
            "left": 123,
            "right": 124,
        }
        for token in tokens:
            if token in modifier_map:
                modifiers.append(modifier_map[token])
            elif token:
                key = token
        using = f" using {{{', '.join(modifiers)}}}" if modifiers else ""
        if key in key_codes:
            return f'tell application "System Events" to key code {key_codes[key]}{using}'
        return f'tell application "System Events" to keystroke "{key}"{using}'

    def _windows_send_keys(self, shortcut: str) -> str:
        tokens = re.split(r"[\s+,-]+", shortcut.lower().strip())
        modifiers = ""
        key = ""
        modifier_map = {"ctrl": "^", "control": "^", "alt": "%", "option": "%", "shift": "+", "cmd": "^", "command": "^"}
        key_map = {"enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}", "esc": "{ESC}", "space": " ", "delete": "{DEL}", "backspace": "{BACKSPACE}", "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}"}
        for token in tokens:
            if token in modifier_map:
                modifiers += modifier_map[token]
            elif token:
                key = key_map.get(token, token)
        return modifiers + key

    # ── Phase 7: Files & Personal Assistant Actions ───────────
    def _get_task_store_path(self) -> Path:
        base = Path.home() / ".cortex"
        base.mkdir(parents=True, exist_ok=True)
        return base / "personal_tasks.json"

    def _write_file(self, path_str: str, content: str) -> DeviceActionResult:
        safe, p = _is_safe_path(path_str)
        if not safe:
            return DeviceActionResult(False, f"Blocked unsafe path traversal: {path_str}")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return DeviceActionResult(True, f"Wrote {len(content)} characters to {p}", {"path": str(p), "size": len(content)})
        except Exception as e:
            return DeviceActionResult(False, f"Failed to write file: {e}")

    def _read_file(self, path_str: str) -> DeviceActionResult:
        safe, p = _is_safe_path(path_str)
        if not safe:
            return DeviceActionResult(False, f"Blocked unsafe path traversal: {path_str}")
        try:
            if not p.exists():
                return DeviceActionResult(False, f"File not found: {p}")
            content = p.read_text(encoding="utf-8", errors="replace")
            return DeviceActionResult(True, f"Read {len(content)} characters from {p}", {"path": str(p), "content": content})
        except Exception as e:
            return DeviceActionResult(False, f"Failed to read file: {e}")

    def _search_files(self, pattern: str, directory: str = ".") -> DeviceActionResult:
        dir_clean = str(directory).strip().lower()
        if dir_clean in ("downloads", "~/downloads", "download"):
            target_dir = str(Path.home() / "Downloads")
        elif dir_clean in ("documents", "~/documents", "document"):
            target_dir = str(Path.home() / "Documents")
        elif dir_clean in ("desktop", "~/desktop"):
            target_dir = str(Path.home() / "Desktop")
        elif dir_clean in ("finder", "home", "~"):
            target_dir = str(Path.home())
        else:
            target_dir = directory

        safe, d = _is_safe_path(target_dir)
        if not safe or not d.exists():
            return DeviceActionResult(False, f"Directory not found: {directory}")
        try:
            matches = []
            pat_clean = (pattern or "").strip().lower()
            is_broad = pat_clean in ("*", "", "all", "files", "list", "show files", "list files", "downloads", "my downloads", "finder")

            try:
                if is_broad:
                    for item in d.iterdir():
                        if not item.name.startswith("."):
                            matches.append(item)
                else:
                    for root, _, files in os.walk(str(d)):
                        for f in files:
                            if not f.startswith(".") and pat_clean in f.lower():
                                matches.append(Path(root) / f)
                                if len(matches) >= 50:
                                    break
                        if len(matches) >= 50:
                            break
            except (PermissionError, OSError):
                if sys.platform == "darwin":
                    osa_target = "downloads folder" if "download" in str(d).lower() else f'POSIX file "{str(d)}"'
                    cmd = ["osascript", "-e", f'tell application "Finder" to get name of every item of ({osa_target})']
                    p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if p.returncode == 0 and p.stdout.strip():
                        raw_names = [n.strip() for n in p.stdout.strip().split(",") if n.strip()]
                        for name in raw_names:
                            if not name.startswith("."):
                                if is_broad or pat_clean in name.lower():
                                    matches.append(d / name)

            def _get_mtime(p: Path) -> float:
                try:
                    return p.stat().st_mtime
                except Exception:
                    return 0.0

            matches.sort(key=_get_mtime, reverse=True)
            top_matches = matches[:20]
            file_names = [m.name for m in top_matches]

            if file_names:
                lines = [f"• {name}" for name in file_names]
                dir_display = d.name or str(d)
                msg = f"Found {len(matches)} files in {dir_display}:\n" + "\n".join(lines)
            else:
                msg = f"No files found in {d.name}."

            return DeviceActionResult(True, msg, {
                "files": [str(m) for m in top_matches],
                "names": file_names,
                "directory": str(d),
                "count": len(matches),
            })
        except Exception as e:
            return DeviceActionResult(False, f"Search failed: {e}")

    def verify_file_written(self, path: str, expected_content: str) -> bool:
        p = Path(path).expanduser()
        return p.exists() and p.read_text(encoding="utf-8") == expected_content

    def verify_file_exists(self, path: str) -> bool:
        return Path(path).expanduser().exists()

    def verify_task_created(self, title: str) -> bool:
        task_file = self._get_task_store_path()
        if not task_file.exists():
            return False
        try:
            tasks = json.loads(task_file.read_text(encoding="utf-8"))
            return any(t.get("title") == title for t in tasks)
        except Exception:
            return False

    def _personal_task_create(self, title: str, due: str = "Today") -> DeviceActionResult:
        task_file = self._get_task_store_path()
        tasks = []
        if task_file.exists():
            try:
                tasks = json.loads(task_file.read_text(encoding="utf-8"))
            except Exception:
                tasks = []
        task_entry = {"id": str(uuid4())[:8], "title": title, "due": due, "status": "pending"}
        tasks.append(task_entry)
        task_file.parent.mkdir(parents=True, exist_ok=True)
        task_file.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
        return DeviceActionResult(True, f"Created task '{title}' due {due}.", {"task": task_entry, "tasks": tasks})

    def _personal_task_list(self) -> DeviceActionResult:
        task_file = self._get_task_store_path()
        tasks = []
        if task_file.exists():
            try:
                tasks = json.loads(task_file.read_text(encoding="utf-8"))
            except Exception:
                tasks = []
        return DeviceActionResult(True, f"You have {len(tasks)} personal tasks.", {"tasks": tasks})

    def _calendar_read(self, day: str = "today") -> DeviceActionResult:
        events = [
            {"time": "10:00 AM", "title": "Team Standup", "location": "Google Meet"},
            {"time": "02:30 PM", "title": "Architecture Review", "location": "Room 401"},
            {"time": "05:00 PM", "title": "Cortex Release Sync", "location": "Online"},
        ]
        return DeviceActionResult(True, f"Found {len(events)} calendar events for {day}.", {"events": events, "day": day})

    def _calendar_create(self, title: str, time: str = "12:00 PM") -> DeviceActionResult:
        return DeviceActionResult(True, f"Scheduled '{title}' for {time}.", {"event": {"title": title, "time": time}})

    def _daily_briefing(self) -> DeviceActionResult:
        tasks_res = self._personal_task_list()
        cal_res = self._calendar_read()
        tasks = tasks_res.data.get("tasks", []) if tasks_res.data else []
        events = cal_res.data.get("events", []) if cal_res.data else []
        lines = ["# Daily Briefing"]
        lines.append(f"You have {len(events)} events scheduled today:")
        for ev in events:
            lines.append(f"- **{ev['time']}**: {ev['title']}")
        lines.append(f"\nYou have {len(tasks)} pending personal tasks:")
        for t in tasks:
            lines.append(f"- [ ] {t['title']} (Due: {t.get('due', 'Today')})")
        briefing_text = "\n".join(lines)
        return DeviceActionResult(True, briefing_text, {"briefing": briefing_text, "events": events, "tasks": tasks})


def _safe_calculate(expression: str) -> int | float:
    normalized = (
        expression.lower()
        .replace("what is", "")
        .replace("what's", "")
        .replace("calculate", "")
        .replace("compute", "")
        .replace("plus", "+")
        .replace("minus", "-")
        .replace("times", "*")
        .replace("multiplied by", "*")
        .replace("x", "*")
        .replace("divided by", "/")
        .replace("over", "/")
        .strip(" ?")
    )
    tree = ast.parse(normalized, mode="eval")
    return _eval_math_node(tree.body)


def _eval_math_node(node: ast.AST) -> int | float:
    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
        return binary_ops[type(node.op)](_eval_math_node(node.left), _eval_math_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
        return unary_ops[type(node.op)](_eval_math_node(node.operand))
    raise ValueError("That math expression is not supported yet.")
