from __future__ import annotations

import os
import platform
import re
import subprocess
import time
import ast
import json
import operator
import plistlib
from uuid import uuid4
from dataclasses import dataclass
from pathlib import Path
from typing import Any
try:
    from backend.core.contracts import TaskCommand
except ImportError:
    from core.contracts import TaskCommand

try:
    from backend.capabilities.safety import is_real_email_send_allowed
except ImportError:
    try:
        from capabilities.safety import is_real_email_send_allowed
    except ImportError:
        def is_real_email_send_allowed() -> bool:
            return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"



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


class ApplicationDiscovery:
    """
    Native macOS Application Discovery & Identification Engine.
    Discovers installed applications across standard macOS bundle locations,
    resolves bundle identifiers, handles aliases, distinguishes installed from
    running applications, and disambiguates multiple candidate matches.
    """

    STANDARD_APP_DIRS = [
        Path("/Applications"),
        Path("/System/Applications"),
        Path("/System/Applications/Utilities"),
        Path("/System/Library/CoreServices"),
        Path.home() / "Applications",
    ]

    def __init__(self, screen_bridge: Any = None) -> None:
        self.screen_bridge = screen_bridge
        self._installed_cache: dict[str, dict[str, Any]] | None = None
        self._cache_time: float = 0.0

    def scan_installed(self, force: bool = False) -> dict[str, dict[str, Any]]:
        now = time.time()
        if not force and self._installed_cache is not None and (now - self._cache_time) < 60.0:
            return self._installed_cache

        discovered: dict[str, dict[str, Any]] = {}
        for directory in self.STANDARD_APP_DIRS:
            if not directory.exists():
                continue
            try:
                for app_bundle in directory.glob("*.app"):
                    name = app_bundle.stem
                    bundle_id = None
                    plist_path = app_bundle / "Contents" / "Info.plist"
                    if plist_path.exists():
                        try:
                            with open(plist_path, "rb") as fp:
                                pl = plistlib.load(fp)
                                bundle_id = pl.get("CFBundleIdentifier")
                                display_name = pl.get("CFBundleDisplayName") or pl.get("CFBundleName")
                                if display_name and isinstance(display_name, str) and display_name.strip():
                                    name = display_name.strip()
                        except Exception:
                            pass
                    info = {
                        "name": name,
                        "bundle_id": bundle_id,
                        "path": str(app_bundle),
                        "is_installed": True,
                    }
                    discovered[name.lower()] = info
                    if bundle_id:
                        discovered[bundle_id.lower()] = info
            except Exception:
                pass

        self._installed_cache = discovered
        self._cache_time = now
        return discovered

    def resolve(self, query: str, running_apps: list[Any] | None = None) -> dict[str, Any]:
        """
        Resolves query to an application.
        Distinguishes installed from running applications, handles aliases,
        and asks for clarification when ambiguous.
        """
        raw = (query or "").strip()
        if not raw:
            return {
                "status": "error",
                "app_name": "",
                "bundle_id": None,
                "path": None,
                "is_installed": False,
                "is_running": False,
                "is_active": False,
                "candidates": [],
                "message": "No application name provided.",
            }

        # Check compound phrases like "Finder and show downloads"
        first_clause = raw
        if " and " in raw.lower():
            fc = re.split(r"\s+and\s+", raw, flags=re.IGNORECASE)[0].strip()
            if fc.lower() in APP_ALIASES or fc.lower() in ("finder", "safari", "mail", "notes", "terminal", "chrome", "whatsapp"):
                first_clause = fc

        cleaned = first_clause.lower()
        alias_target = APP_ALIASES.get(cleaned)
        lookup_name = alias_target or first_clause

        installed = self.scan_installed()
        running_names: set[str] = set()
        running_map: dict[str, Any] = {}
        if running_apps:
            for app in running_apps:
                a_name = getattr(app, "name", "")
                a_bundle = getattr(app, "bundle_id", "")
                if a_name:
                    running_names.add(a_name.lower())
                    running_map[a_name.lower()] = app
                if a_bundle:
                    running_names.add(a_bundle.lower())
                    running_map[a_bundle.lower()] = app

        # 1. Exact match on installed app name or bundle ID
        target_lower = lookup_name.lower()
        if target_lower in installed:
            matched = installed[target_lower]
            canonical = matched["name"]
            is_run = (canonical.lower() in running_names) or (matched.get("bundle_id", "").lower() in running_names)
            return {
                "status": "resolved",
                "app_name": canonical,
                "bundle_id": matched.get("bundle_id"),
                "path": matched.get("path"),
                "is_installed": True,
                "is_running": is_run,
                "candidates": [canonical],
                "message": f"Resolved application '{canonical}'.",
            }

        # 2. Check if already running by name
        if target_lower in running_names:
            app_obj = running_map[target_lower]
            canonical = getattr(app_obj, "name", lookup_name)
            return {
                "status": "resolved",
                "app_name": canonical,
                "bundle_id": getattr(app_obj, "bundle_id", None),
                "path": None,
                "is_installed": True,
                "is_running": True,
                "candidates": [canonical],
                "message": f"Resolved running application '{canonical}'.",
            }

        # 3. Fuzzy / Substring matches across installed apps
        candidates: dict[str, dict[str, Any]] = {}
        for key, info in installed.items():
            app_name = info["name"]
            if app_name.lower() in [c.lower() for c in candidates]:
                continue
            if target_lower in app_name.lower():
                candidates[app_name] = info

        if len(candidates) == 1:
            matched = list(candidates.values())[0]
            canonical = matched["name"]
            is_run = (canonical.lower() in running_names) or (matched.get("bundle_id", "").lower() in running_names)
            return {
                "status": "resolved",
                "app_name": canonical,
                "bundle_id": matched.get("bundle_id"),
                "path": matched.get("path"),
                "is_installed": True,
                "is_running": is_run,
                "candidates": [canonical],
                "message": f"Resolved application '{canonical}'.",
            }
        elif len(candidates) > 1:
            # Disambiguate if exactly one is running
            running_candidates = [
                info["name"] for info in candidates.values()
                if info["name"].lower() in running_names
            ]
            if len(running_candidates) == 1:
                canonical = running_candidates[0]
                matched = candidates[canonical]
                return {
                    "status": "resolved",
                    "app_name": canonical,
                    "bundle_id": matched.get("bundle_id"),
                    "path": matched.get("path"),
                    "is_installed": True,
                    "is_running": True,
                    "candidates": [canonical],
                    "message": f"Disambiguated to running application '{canonical}'.",
                }

            candidate_names = sorted(list(candidates.keys()))
            return {
                "status": "ambiguous",
                "app_name": raw,
                "bundle_id": None,
                "path": None,
                "is_installed": True,
                "is_running": False,
                "candidates": candidate_names,
                "message": f"Multiple applications match '{raw}': {', '.join(candidate_names)}. Which one would you like to use?",
            }

        # 4. If query was in APP_ALIASES, trust canonical name
        if alias_target:
            return {
                "status": "resolved",
                "app_name": alias_target,
                "bundle_id": None,
                "path": None,
                "is_installed": True,
                "is_running": alias_target.lower() in running_names,
                "candidates": [alias_target],
                "message": f"Resolved alias '{raw}' to '{alias_target}'.",
            }

        # 5. Not installed
        return {
            "status": "not_installed",
            "app_name": raw,
            "bundle_id": None,
            "path": None,
            "is_installed": False,
            "is_running": False,
            "candidates": [],
            "message": f"Application '{raw}' is not installed on this Mac.",
        }


@dataclass(frozen=True)
class DeviceActionResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


class DeviceAutomation:
    def __init__(self, dry_run: bool | None = None, screenshot_dir: str | None = None) -> None:
        self.system = platform.system().lower()
        self._dry_run = (os.getenv("CORTEX_EXECUTION_MODE", "live").lower() == "dry-run") if dry_run is None else dry_run
        self.screenshot_dir = Path(screenshot_dir or "screenshots")
        self._note_store: dict[str, dict[str, Any]] = {}
        self._browser = None   # lazy-loaded BrowserAutomation
        self._mail = None      # lazy-loaded MailAutomation
        self._whatsapp = None  # lazy-loaded WhatsAppAutomation
        self._discovery = None # lazy-loaded ApplicationDiscovery
        self._notes_adapter = None # lazy-loaded NotesAdapter
        self._whatsapp_adapter = None # lazy-loaded WhatsAppAdapter

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @dry_run.setter
    def dry_run(self, val: bool) -> None:
        self._dry_run = val
        if self._notes_adapter is not None:
            self._notes_adapter.dry_run = val
        if self._whatsapp_adapter is not None:
            self._whatsapp_adapter.dry_run = val
        if self._mail is not None:
            self._mail.dry_run = val
            if hasattr(self._mail, "_manager") and self._mail._manager is not None:
                self._mail._manager.dry_run = val
                self._mail._manager.gmail.sandbox = val
                self._mail._manager.apple_mail.dry_run = val

    def _get_browser(self):
        if self._browser is None:
            from .browser_actions import BrowserAutomation
            self._browser = BrowserAutomation(headless=False)
        return self._browser

    def _get_mail(self):
        if self._mail is None:
            from .mail_actions import MailAutomation
            self._mail = MailAutomation(dry_run=self.dry_run, mcp_manager=getattr(self, "mcp_manager", None))
        elif getattr(self._mail, "mcp_manager", None) is None and getattr(self, "mcp_manager", None) is not None:
            self._mail.mcp_manager = self.mcp_manager
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

    def _get_notes_adapter(self):
        if self._notes_adapter is None:
            try:
                from backend.adapters.notes_adapter import NotesAdapter
            except ImportError:
                from adapters.notes_adapter import NotesAdapter
            self._notes_adapter = NotesAdapter(dry_run=self.dry_run)
            self._notes_adapter._simulated_store = self._note_store
        return self._notes_adapter

    @property
    def notes_adapter(self):
        return self._get_notes_adapter()

    @notes_adapter.setter
    def notes_adapter(self, val):
        self._notes_adapter = val

    def _get_whatsapp_adapter(self):
        if self._whatsapp_adapter is None:
            try:
                from backend.adapters.whatsapp_adapter import WhatsAppAdapter
            except ImportError:
                from adapters.whatsapp_adapter import WhatsAppAdapter
            t_store = getattr(self, "task_store", None)
            self._whatsapp_adapter = WhatsAppAdapter(dry_run=self.dry_run, task_store=t_store)
            if self._whatsapp is not None and hasattr(self._whatsapp, "adapter"):
                self._whatsapp_adapter.desktop_adapter = self._whatsapp.adapter
        elif getattr(self._whatsapp_adapter, "task_store", None) is None and getattr(self, "task_store", None) is not None:
            self._whatsapp_adapter.task_store = getattr(self, "task_store", None)
        if self._whatsapp is not None and getattr(self._whatsapp_adapter, "whatsapp_automation", None) is None:
            self._whatsapp_adapter.whatsapp_automation = self._whatsapp
        return self._whatsapp_adapter

    @property
    def whatsapp_adapter(self):
        return self._get_whatsapp_adapter()

    @whatsapp_adapter.setter
    def whatsapp_adapter(self, val):
        self._whatsapp_adapter = val

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
    def discovery(self) -> ApplicationDiscovery:
        if not hasattr(self, "_discovery") or self._discovery is None:
            self._discovery = ApplicationDiscovery(self.screen_bridge)
        return self._discovery

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
        if command in (TaskCommand.DRAFT_MAIL, TaskCommand.REPLY_MAIL, TaskCommand.FORWARD_MAIL):
            return self.create_email_draft(
                str(params.get("recipient", "")),
                str(params.get("subject", "")),
                str(params.get("body", "")),
                account=str(params.get("account") or params.get("sender_account") or ""),
                attachments=params.get("attachments"),
                cc=params.get("cc"),
                bcc=params.get("bcc"),
                in_reply_to=str(params.get("in_reply_to", "")),
                references=params.get("references"),
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
            mail = self._get_mail()
            res = mail.search_mail(
                query=str(params.get("query", "")),
                sender=str(params.get("sender", "")),
                recipient=str(params.get("recipient", "")),
                subject=str(params.get("subject", "")),
                date_from=params.get("date_from"),
                date_to=params.get("date_to"),
                unread_only=bool(params.get("unread_only", False)),
                account=str(params.get("account", "")),
                mailbox=str(params.get("mailbox", "")),
                limit=int(params.get("limit", 25) if str(params.get("limit", "")).isdigit() else 25),
                mcp_manager=getattr(self, "mcp_manager", getattr(mail, "mcp_manager", None)),
            )
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res)
        if command == TaskCommand.EMAIL_BRIEFING:
            res = self._get_mail().email_briefing(int(params.get("limit", 10)))
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res.get("data"))
        if command == TaskCommand.EXTRACT_ACTIONS:
            res = self._get_mail().extract_actions(int(params.get("limit", 5)))
            return DeviceActionResult(res.get("ok", False), res.get("message", ""), res)

        # ── Phase 7: Files & Personal Assistant ───────────────
        if command == TaskCommand.CREATE_DIRECTORY:
            return self._create_directory(str(params.get("path") or params.get("directory") or params.get("name") or ""))
        if command == TaskCommand.WRITE_FILE:
            return self._write_file(str(params.get("path", "")), str(params.get("content", "")))
        if command == TaskCommand.READ_FILE:
            return self._read_file(str(params.get("path", "")))
        if command == TaskCommand.SEARCH_FILES:
            return self._search_files(
                pattern=str(params.get("pattern", "*")),
                directory=str(params.get("directory") or params.get("folder") or "."),
                limit=int(params.get("limit", 5) if str(params.get("limit", "")).isdigit() else 5),
                open_finder=bool(params.get("open_finder", False)),
                sort_by=str(params.get("sort_by", "alphabetical")),
            )
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
        if command == TaskCommand.OPEN_APP:
            return self._open_app(
                str(params.get("appName") or params.get("app_name") or params.get("target") or ""),
                folder=str(params.get("folder") or ""),
                file_path=str(params.get("file_path") or params.get("path") or ""),
            )
        if command == TaskCommand.CLOSE_APP:
            return self._close_app(str(params.get("appName") or params.get("app_name") or params.get("target") or ""))
        if command == TaskCommand.FOCUS_APP:
            return self._focus_app(str(params.get("appName") or params.get("app_name") or params.get("target") or ""))
        if command == TaskCommand.CLOSE_WINDOW:
            return self._close_window(str(params.get("appName") or params.get("app_name") or params.get("target") or ""))
        if command == TaskCommand.QUIT_APP:
            return self._close_app(str(params.get("appName") or params.get("app_name") or params.get("target") or ""), force=bool(params.get("force", False)))
        if command == TaskCommand.INSPECT_APP:
            return self._inspect_app(str(params.get("appName") or params.get("target") or ""))
        if command == TaskCommand.TYPE_TEXT:
            return self._type_text(str(params.get("text") or ""), str(params.get("appName") or ""))
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
        
        # 1. MCP Agent Browser delegation (SYS-03 repair: no leak to native/legacy)
        mcp_mgr = getattr(self, "mcp_manager", None)
        if mcp_mgr and mcp_mgr.is_running("agent-browser"):
            try:
                res = mcp_mgr.call_tool("agent-browser", "agent_browser_open", {"url": url})
                if res and res.is_error:
                    return DeviceActionResult(False, f"Agent Browser failed: {res.error_message or 'Unknown error'}")
                return DeviceActionResult(True, f"Opened {url} in Agent Browser.", {"url": url, "mcp_server": "agent-browser"})
            except Exception as e:
                logger.warning(f"Failed to open {url} via agent-browser MCP: {e}")

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
        mcp_mgr = getattr(self, "mcp_manager", None)
        if mcp_mgr and mcp_mgr.is_running("agent-browser"):
            try:
                res = mcp_mgr.call_tool("agent-browser", "agent_browser_click", {"selector": selector})
                if res and res.is_error:
                    return DeviceActionResult(False, f"Agent Browser click failed: {res.error_message or 'Unknown error'}")
                return DeviceActionResult(True, f"Clicked '{selector}' in Agent Browser.", {"selector": selector})
            except Exception as e:
                logger.warning(f"Failed to click via agent-browser MCP: {e}")
        result = self._get_browser().click(selector, url)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _browser_type(self, selector: str, text: str, url: str = "") -> DeviceActionResult:
        if not selector or not text:
            return DeviceActionResult(False, "Selector and text are required for browser type.")
        mcp_mgr = getattr(self, "mcp_manager", None)
        if mcp_mgr and mcp_mgr.is_running("agent-browser"):
            try:
                res = mcp_mgr.call_tool("agent-browser", "agent_browser_fill", {"selector": selector, "text": text})
                if res and res.is_error:
                    return DeviceActionResult(False, f"Agent Browser type failed: {res.error_message or 'Unknown error'}")
                return DeviceActionResult(True, f"Typed into '{selector}' in Agent Browser.", {"selector": selector, "text": text})
            except Exception as e:
                logger.warning(f"Failed to type via agent-browser MCP: {e}")
        result = self._get_browser().type_text(selector, text, url)
        return DeviceActionResult(result.ok, result.message, result.data)

    def _browser_scrape(self, url: str, selector: str = "body") -> DeviceActionResult:
        if not url:
            return DeviceActionResult(False, "No URL provided for scrape.")
        mcp_mgr = getattr(self, "mcp_manager", None)
        if mcp_mgr and mcp_mgr.is_running("agent-browser"):
            try:
                res = mcp_mgr.call_tool("agent-browser", "agent_browser_snapshot", {})
                if res and res.is_error:
                    return DeviceActionResult(False, f"Agent Browser scrape failed: {res.error_message or 'Unknown error'}")
                return DeviceActionResult(True, f"Captured snapshot via Agent Browser.", {"content": res.content or res.raw_payload})
            except Exception as e:
                logger.warning(f"Failed to scrape via agent-browser MCP: {e}")
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
        in_reply_to: str = "",
        references: list[str] | None = None,
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
            in_reply_to=in_reply_to,
            references=references,
        )

    def update_email_draft(
        self,
        draft_id: str,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        old_subject: str = "",
    ) -> DeviceActionResult:
        mail_inst = self._get_mail()
        if hasattr(mail_inst, "update_draft"):
            result = mail_inst.update_draft(
                draft_id=draft_id,
                recipient=recipient,
                subject=subject,
                body=body,
                account=account,
                attachments=attachments,
                cc=cc,
                bcc=bcc,
                old_subject=old_subject,
            )
        else:
            result = mail_inst.draft_mail(recipient, subject, body, account=account)
        return DeviceActionResult(result.get("ok", False), result.get("message", ""), result.get("data"))

    def _draft_mail(
        self,
        recipient: str,
        subject: str,
        body: str,
        account: str = "",
        attachments: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        in_reply_to: str = "",
        references: list[str] | None = None,
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
            if has_varkw or "in_reply_to" in sig.parameters: kwargs["in_reply_to"] = in_reply_to
            if has_varkw or "references" in sig.parameters: kwargs["references"] = references
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
        if not is_real_email_send_allowed():
            return DeviceActionResult(
                False,
                f"Email sending to {recipient} is blocked by safety policy. Real email transmission is disabled in Phase P7.2.",
                {"recipient": recipient, "subject": subject, "account": account, "error": "SEND_BLOCKED_BY_POLICY"},
            )
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
        if not raw:
            return ""
        # Handle compound requests like "Finder and list my downloads" or "Safari and search"
        if " and " in raw.lower():
            first_clause = re.split(r"\s+and\s+", raw, flags=re.IGNORECASE)[0].strip()
            if first_clause.lower() in APP_ALIASES or first_clause.lower() in ("finder", "safari", "mail", "notes", "terminal", "chrome", "whatsapp"):
                raw = first_clause
        cleaned = raw.lower()
        if cleaned in APP_ALIASES:
            return APP_ALIASES[cleaned]
        res = self.discovery.resolve(raw)
        if res.get("status") == "resolved" and res.get("app_name"):
            return res["app_name"]
        return APP_ALIASES.get(cleaned, raw)

    def is_app_running(self, app_name: str) -> bool:
        """Determines whether target application process is active and running."""
        canonical = self.resolve_app_name(app_name)
        if not canonical:
            return False
        if self.dry_run:
            if hasattr(self, "_mock_running_apps"):
                return canonical.lower() in [a.lower() for a in self._mock_running_apps]
            if hasattr(self.screen_bridge, "list_running_apps"):
                for a in self.screen_bridge.list_running_apps():
                    if a.name.lower() == canonical.lower() or (a.bundle_id and a.bundle_id.lower() == canonical.lower()):
                        return True
            return False

        if self.system == "darwin":
            # 1. Native screen bridge check via cortex_screen_helper (fast Cocoa NSRunningApplication)
            try:
                running = self.screen_bridge.list_running_apps()
                for app in running:
                    if app.name.lower() == canonical.lower() or (app.bundle_id and app.bundle_id.lower() == canonical.lower()):
                        return True
            except Exception:
                pass
            # 2. AppleScript check via System Events
            script = f'tell application "System Events" to (name of processes) contains "{canonical}"'
            try:
                res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
                if "true" in res.stdout.lower():
                    return True
            except Exception:
                pass
            # 3. pgrep fallback
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

    def is_app_active(self, app_name: str) -> bool:
        """Determines whether target application is currently frontmost and active."""
        canonical = self.resolve_app_name(app_name)
        if not canonical:
            return False
        if self.dry_run:
            if hasattr(self, "_mock_active_app"):
                return self._mock_active_app.lower() == canonical.lower()
            front = self.screen_bridge.get_frontmost_app()
            return bool(front and (front.name.lower() == canonical.lower() or (front.bundle_id and front.bundle_id.lower() == canonical.lower())))

        if self.system == "darwin":
            front = self.screen_bridge.get_frontmost_app()
            if front and (front.name.lower() == canonical.lower() or (front.bundle_id and front.bundle_id.lower() == canonical.lower())):
                return True
        return False

    def has_unsaved_changes(self, app_name: str) -> bool:
        """Inspects application windows to detect unsaved work before closing or quitting."""
        canonical = self.resolve_app_name(app_name)
        if not canonical or self.dry_run:
            if hasattr(self, "_mock_unsaved_changes"):
                return canonical.lower() in [a.lower() for a in self._mock_unsaved_changes]
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

    def _open_app(self, app_name: str, folder: str = "", file_path: str = "") -> DeviceActionResult:
        # Fallback: if app_name is an existing file path and file_path was not set, treat as file_path
        if not file_path and app_name:
            try:
                p_cand = Path(app_name).expanduser()
                if p_cand.exists() and p_cand.is_file():
                    file_path = str(p_cand)
                    app_name = ""
            except Exception:
                pass

        # 1. Opening a file with default or specified application
        if file_path:
            p_resolved = Path(file_path).expanduser().resolve()
            if not p_resolved.exists():
                return DeviceActionResult(False, f"Cannot open file: '{p_resolved.name}' was not found.")

            # Default application opening via macOS Launch Services (open <file>)
            if not app_name or app_name.lower() in ("default", "system default", "default application", "none", ""):
                if self.dry_run:
                    return DeviceActionResult(
                        True,
                        f"Opened {p_resolved.name} in its default application.",
                        {"appName": "Default Application", "file_path": str(p_resolved), "wasRunning": True, "isActive": True},
                    )
                if self.system == "darwin":
                    try:
                        res = subprocess.run(["open", str(p_resolved)], capture_output=True, text=True, check=False)
                        if res.returncode == 0:
                            return DeviceActionResult(
                                True,
                                f"Opened {p_resolved.name} in its default application.",
                                {"appName": "Default Application", "file_path": str(p_resolved), "wasRunning": True, "isActive": True},
                            )
                        return DeviceActionResult(False, f"Cannot open {p_resolved.name}: {res.stderr.strip()}")
                    except Exception as e:
                        return DeviceActionResult(False, f"Failed to open {p_resolved.name}: {e}")

            # Explicit application requested (e.g. Preview, TextEdit)
            resolution = self.discovery.resolve(app_name, running_apps=self.screen_bridge.list_running_apps())
            if not self.dry_run and resolution.get("status") == "not_installed":
                return DeviceActionResult(
                    False,
                    f"Cannot open '{p_resolved.name}': Application '{app_name}' is not installed on this Mac.",
                    {"appName": app_name, "isInstalled": False, "file_path": str(p_resolved)},
                )

            canonical = resolution.get("app_name") or self.resolve_app_name(app_name) or app_name
            if self.dry_run:
                return DeviceActionResult(
                    True,
                    f"Opened {p_resolved.name} in {canonical}.",
                    {"appName": canonical, "file_path": str(p_resolved), "wasRunning": True, "isActive": True},
                )
            if self.system == "darwin":
                try:
                    res = subprocess.run(["open", "-a", canonical, str(p_resolved)], capture_output=True, text=True, check=False)
                    if res.returncode == 0:
                        return DeviceActionResult(
                            True,
                            f"Opened {p_resolved.name} in {canonical}.",
                            {"appName": canonical, "file_path": str(p_resolved), "wasRunning": True, "isActive": True},
                        )
                    return DeviceActionResult(False, f"Cannot open {p_resolved.name} in {canonical}: {res.stderr.strip()}")
                except Exception as e:
                    return DeviceActionResult(False, f"Failed to open {p_resolved.name} in {canonical}: {e}")

        # 2. Opening a folder in Finder
        if folder:
            p_folder = Path(folder).expanduser().resolve()
            if not p_folder.exists():
                return DeviceActionResult(False, f"Cannot open folder: '{p_folder}' does not exist.")
            if self.dry_run:
                return DeviceActionResult(True, f"Opened folder {p_folder.name} in Finder.", {"appName": "Finder", "folder": str(p_folder)})
            if self.system == "darwin":
                try:
                    res = subprocess.run(["open", str(p_folder)], capture_output=True, text=True, check=False)
                    if res.returncode == 0:
                        return DeviceActionResult(True, f"Opened folder '{p_folder.name}' in Finder.", {"appName": "Finder", "folder": str(p_folder)})
                    return DeviceActionResult(False, f"Cannot open folder: {res.stderr.strip()}")
                except Exception as e:
                    return DeviceActionResult(False, f"Failed to open folder: {e}")

        # 3. Standard application launch
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")

        resolution = self.discovery.resolve(app_name, running_apps=self.screen_bridge.list_running_apps())
        if resolution.get("status") == "ambiguous":
            return DeviceActionResult(
                False,
                resolution["message"],
                {"isAmbiguous": True, "candidates": resolution.get("candidates", []), "appName": app_name},
            )
        if not self.dry_run and resolution.get("status") == "not_installed":
            return DeviceActionResult(
                False,
                f"Cannot open '{app_name}': Application is not installed on this Mac.",
                {"appName": app_name, "isInstalled": False},
            )

        canonical = resolution.get("app_name") or self.resolve_app_name(app_name)
        bundle_id = resolution.get("bundle_id")

        if self.dry_run:
            if self.is_app_running(canonical):
                return DeviceActionResult(
                    True,
                    f"Focused already running application {canonical}.",
                    {
                        "appName": canonical,
                        "bundleId": bundle_id,
                        "wasRunning": True,
                        "isActive": True,
                        "mechanism": "activate_existing",
                    },
                )
            return DeviceActionResult(
                True,
                f"Opened {canonical}.",
                {"appName": canonical, "wasRunning": False, "isActive": True, "mechanism": "mock_launch"},
            )

        if canonical == "Finder":
            if self.system == "darwin":
                try:
                    if folder:
                        target = Path.home() / "Downloads" if "download" in folder.lower() else Path(folder).expanduser()
                        subprocess.run(["open", "-a", "Finder", str(target)], capture_output=True, text=True, check=False)
                        return DeviceActionResult(True, f"Opened Finder in {folder}.", {"appName": "Finder", "folder": str(target), "wasRunning": True, "isActive": True})
                    subprocess.run(["open", "-a", "Finder"], capture_output=True, text=True, check=False)
                    return DeviceActionResult(True, "Opened Finder.", {"appName": "Finder", "wasRunning": True, "isActive": True})
                except Exception as e:
                    return DeviceActionResult(False, f"Failed to open Finder: {e}")

        # Check if already running -> focus it instead of duplicating
        if self.is_app_running(canonical):
            focus_res = self._focus_app(canonical)
            return DeviceActionResult(
                True,
                f"Focused already running application {canonical}.",
                {
                    "appName": canonical,
                    "bundleId": bundle_id,
                    "wasRunning": True,
                    "isActive": focus_res.ok,
                    "mechanism": "activate_existing",
                },
            )

        if self.dry_run:
            return DeviceActionResult(
                True,
                f"Opened {canonical}.",
                {"appName": canonical, "wasRunning": False, "isActive": True, "mechanism": "mock_launch"},
            )

        if self.system == "darwin":
            try:
                cmd = ["open", "-a", canonical]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    err_msg = res.stderr.strip() or "Unable to find application."
                    return DeviceActionResult(False, f"Cannot open {canonical}: {err_msg}", {"appName": canonical})

                # Polling verification of process and foreground state
                is_running = False
                is_active = False
                pid = None
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if self.is_app_running(canonical):
                        is_running = True
                        break
                    time.sleep(0.1)

                if is_running:
                    front = self.screen_bridge.get_frontmost_app()
                    if front and (front.name.lower() == canonical.lower() or (bundle_id and front.bundle_id == bundle_id)):
                        is_active = True
                        pid = front.pid
                    else:
                        for a in self.screen_bridge.list_running_apps():
                            if a.name.lower() == canonical.lower() or (bundle_id and a.bundle_id == bundle_id):
                                pid = a.pid
                                break
                    return DeviceActionResult(
                        True,
                        f"Opened {canonical}.",
                        {
                            "appName": canonical,
                            "bundleId": bundle_id,
                            "wasRunning": False,
                            "isRunning": True,
                            "isActive": is_active,
                            "pid": pid,
                            "mechanism": "open_cli",
                        },
                    )
                else:
                    return DeviceActionResult(
                        False,
                        f"Launched {canonical}, but the application process did not appear.",
                        {"appName": canonical, "wasRunning": False, "isRunning": False},
                    )
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
        resolution = self.discovery.resolve(app_name, running_apps=self.screen_bridge.list_running_apps())
        if resolution.get("status") == "ambiguous":
            return DeviceActionResult(
                False,
                resolution["message"],
                {"isAmbiguous": True, "candidates": resolution.get("candidates", []), "appName": app_name},
            )

        canonical = resolution.get("app_name") or self.resolve_app_name(app_name)
        bundle_id = resolution.get("bundle_id")

        if self.dry_run:
            return DeviceActionResult(True, f"Focused {canonical}.", {"appName": canonical, "isActive": True})

        # If app is not running, launch it so focusing opens the application
        if not self.is_app_running(canonical):
            return self._open_app(canonical)

        if self.system == "darwin":
            try:
                script = f'tell application "{canonical}" to activate'
                subprocess.run(["osascript", "-e", script], check=True, capture_output=True)

                is_active = False
                deadline = time.time() + 1.5
                while time.time() < deadline:
                    front = self.screen_bridge.get_frontmost_app()
                    if front and (front.name.lower() == canonical.lower() or (bundle_id and front.bundle_id == bundle_id)):
                        is_active = True
                        break
                    time.sleep(0.1)

                return DeviceActionResult(
                    True,
                    f"Focused {canonical}.",
                    {"appName": canonical, "isActive": is_active, "mechanism": "apple_events_activate"},
                )
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
        resolution = self.discovery.resolve(app_name, running_apps=self.screen_bridge.list_running_apps())
        canonical = resolution.get("app_name") or self.resolve_app_name(app_name)

        if self.dry_run:
            return DeviceActionResult(True, f"Closed {canonical}.", {"appName": canonical, "closed": True})

        if not self.is_app_running(canonical):
            return DeviceActionResult(
                True,
                f"{canonical} is not running.",
                {"appName": canonical, "wasRunning": False, "closed": True},
            )

        if not force and self.has_unsaved_changes(canonical):
            return DeviceActionResult(
                False,
                f"Application {canonical} has unsaved changes. Please save your work or confirm quitting.",
                {"appName": canonical, "hasUnsavedChanges": True},
            )

        if self.system == "darwin":
            try:
                if force:
                    subprocess.run(["pkill", "-9", "-if", canonical], capture_output=True)
                else:
                    script = f'tell application "{canonical}" to quit'
                    subprocess.run(["osascript", "-e", script], capture_output=True)

                # Polling verification of termination
                terminated = False
                deadline = time.time() + 2.0
                while time.time() < deadline:
                    if not self.is_app_running(canonical):
                        terminated = True
                        break
                    time.sleep(0.1)

                if terminated:
                    return DeviceActionResult(True, f"Closed {canonical}.", {"appName": canonical, "closed": True})
                else:
                    return DeviceActionResult(
                        False,
                        f"Application {canonical} refused to close or is still running (may require saving documents).",
                        {"appName": canonical, "closed": False, "isStillRunning": True},
                    )
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
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        resolution = self.discovery.resolve(app_name, running_apps=self.screen_bridge.list_running_apps())
        canonical = resolution.get("app_name") or self.resolve_app_name(app_name)
        bundle_id = resolution.get("bundle_id")
        is_installed = resolution.get("is_installed", True)

        is_running = self.is_app_running(canonical)
        front = self.screen_bridge.get_frontmost_app()
        is_active = bool(front and (front.name.lower() == canonical.lower() or (bundle_id and front.bundle_id == bundle_id)))

        data = {
            "appName": canonical,
            "bundleId": bundle_id,
            "isInstalled": is_installed,
            "isRunning": is_running,
            "isActive": is_active,
            "system": self.system,
        }
        if is_running and self.system == "darwin" and not self.dry_run:
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
        elif is_running:
            data["windowCount"] = 1

        data["capabilities"] = self.app_registry.inspect_app_capabilities(canonical)
        if is_running:
            state_str = "active and in the foreground" if is_active else "running in the background"
            msg = f"{canonical} is currently {state_str}."
        else:
            msg = f"{canonical} is not running."
        return DeviceActionResult(True, msg, data)

    def _observe_screen(self, capture: bool = False, run_ocr: bool = False, pid: int | None = None, params: dict[str, Any] | None = None) -> DeviceActionResult:
        params = params or {}
        max_elements = int(params.get("max_elements", 5))

        # 1. Verify permissions
        perms = self.screen_bridge.get_permissions()

        # 2. Check frontmost application
        app = None
        if pid:
            for running in self.screen_bridge.list_running_apps():
                if running.pid == pid:
                    app = running
                    break
        else:
            app = self.screen_bridge.get_frontmost_app()

        app_name = app.name if app and app.name else "Unavailable"
        limitations_list: list[str] = []

        # Permission check: Accessibility
        if not perms.accessibility:
            if "failed" in perms.status_message.lower():
                limitations_list.append(perms.status_message)
            else:
                limitations_list.append("Accessibility permission denied. Please grant Accessibility access in System Settings > Privacy & Security > Accessibility.")
            formatted_msg = (
                f"- **Active application:** {app_name}\n"
                f"- **Active window:** Unavailable\n"
                f"- **Visible elements:** None\n"
                f"- **Limitations:** {'; '.join(limitations_list)}"
            )
            return DeviceActionResult(
                False,
                formatted_msg,
                {
                    "app": app.to_dict() if app else None,
                    "window": None,
                    "window_title": "Unavailable",
                    "visible_elements": [],
                    "elements": [],
                    "limitations": "; ".join(limitations_list),
                    "permissions": perms.to_dict(),
                    "observed_facts": [],
                    "model_inferences": [],
                }
            )

        # 3. Accessibility inspection
        ax = self.ax_engine.inspect_current_application(pid=pid)
        if not ax.ok:
            err_msg = ax.error or "Failed to inspect accessibility tree."
            limitations_list.append(err_msg)
            formatted_msg = (
                f"- **Active application:** {app_name}\n"
                f"- **Active window:** Unavailable\n"
                f"- **Visible elements:** None\n"
                f"- **Limitations:** {'; '.join(limitations_list)}"
            )
            return DeviceActionResult(
                False,
                formatted_msg,
                {
                    "app": app.to_dict() if app else None,
                    "window": None,
                    "window_title": "Unavailable",
                    "visible_elements": [],
                    "elements": [],
                    "limitations": "; ".join(limitations_list),
                    "permissions": perms.to_dict(),
                    "observed_facts": [],
                    "model_inferences": [],
                }
            )

        if ax.app and ax.app.name:
            app_name = ax.app.name

        # 4. Active window resolution (Never infer window title from application name)
        window = ax.window
        window_title = "Unavailable"
        if window and window.title and window.title.strip():
            window_title = window.title.strip()
        else:
            limitations_list.append("No active window title found.")

        # 5. Extract visible elements from accessibility hierarchy
        visible_elements: list[str] = []
        element_dicts: list[dict[str, Any]] = []
        seen_labels: set[str] = set()

        for el in ax.elements:
            if getattr(el, "role", None) and hasattr(el.role, "value") and el.role.value.lower() in ("unknown", "-1"):
                continue
            label = (el.title or el.description or el.value or "").strip()
            if not label or label in seen_labels:
                continue
            if label.lower() in ("-1", "unknown", "[unknown]", "none", "null") or label == "-1":
                continue
            if hasattr(el.role, "value") and label.startswith(el.role.value + "_"):
                continue
            # Redact/skip sensitive content
            if any(s in label.lower() for s in ("password", "secret", "token", "private_key", "bearer")):
                continue
            seen_labels.add(label)
            role_name = el.role.value.replace("_", " ").capitalize()
            visible_elements.append(f"[{role_name}] {label} (source: accessibility)")
            element_dicts.append({
                "role": el.role.value,
                "label": label,
                "source": "accessibility",
                "is_interactive": el.is_interactive,
            })
            if len(visible_elements) >= max_elements:
                break

        # 6. Screen capture and OCR when requested or when elements < max_elements
        screenshot_path = None
        should_run_ocr = run_ocr or (len(visible_elements) < max_elements) or capture
        if should_run_ocr:
            if not perms.screen_recording:
                limitations_list.append("Screen recording permission denied (Apple Vision OCR unavailable).")
            else:
                self.screenshot_dir.mkdir(parents=True, exist_ok=True)
                screenshot_path = str((self.screenshot_dir / f"screen_{int(time.time())}.png").resolve())
                cap_ok, cap_msg = self.screen_bridge.capture_screenshot(screenshot_path)
                if not cap_ok:
                    limitations_list.append(f"Screenshot capture failed: {cap_msg}")
                else:
                    ocr_obs = self.screen_bridge.run_ocr(screenshot_path)
                    if not ocr_obs and run_ocr:
                        limitations_list.append("Apple Vision OCR returned no text.")
                    elif ocr_obs and len(visible_elements) < max_elements:
                        for o in ocr_obs:
                            t = o.text.strip()
                            if not t or t in seen_labels:
                                continue
                            if t.lower() in ("-1", "unknown", "[unknown]", "none", "null") or t == "-1":
                                continue
                            if any(s in t.lower() for s in ("password", "secret", "token", "private_key")):
                                continue
                            seen_labels.add(t)
                            # Ground strictly as Text, not as button/control
                            visible_elements.append(f"[Text] {t} (source: vision_ocr)")
                            element_dicts.append({
                                "role": "text",
                                "label": t,
                                "source": "vision_ocr",
                                "confidence": o.confidence,
                            })
                            if len(visible_elements) >= max_elements:
                                break

        # 7. Partial observation / empty limitations
        if len(visible_elements) == 0:
            limitations_list.append("No accessible UI elements or visible text found.")
        elif len(visible_elements) < max_elements and "No active window title found." not in limitations_list:
            limitations_list.append(f"Only {len(visible_elements)} visible elements could be identified.")

        limitations_str = "; ".join(limitations_list) if limitations_list else "None"

        # 8. Build ScreenContext for multi-source fusion & persistence
        ctx = self.fusion_engine.fuse(ax, screenshot_path=screenshot_path, task_context=params)
        distinctions = ctx.distinguish_facts_and_inferences()

        # 9. Format visible elements list for markdown
        if visible_elements:
            elem_lines = "\n".join(f"  {idx + 1}. {e}" for idx, e in enumerate(visible_elements))
            elem_str = f"\n{elem_lines}"
        else:
            elem_str = " None"

        formatted_msg = (
            f"- **Active application:** {app_name}\n"
            f"- **Active window:** {window_title}\n"
            f"- **Visible elements:**{elem_str}\n"
            f"- **Limitations:** {limitations_str}"
        )

        task_id = params.get("task_id") if params else None
        if hasattr(self, "task_store") and self.task_store:
            try:
                self.task_store.record_screen_observation(
                    context_id=ctx.context_id,
                    task_id=task_id,
                    app_name=app_name,
                    window_title=window_title if window_title != "Unavailable" else None,
                    elements_count=len(visible_elements),
                    modal_dialog=any(el.is_modal for el in ax.elements),
                    screenshot_path=screenshot_path,
                    facts=[f.to_dict() for f in ctx.facts],
                )
            except Exception:
                pass

        summary_data = {
            "app": {"name": app_name, "pid": app.pid if app else 0},
            "window": window.to_dict() if window else None,
            "window_title": window_title,
            "visible_elements": visible_elements,
            "elements": element_dicts,
            "limitations": limitations_str,
            "permissions": perms.to_dict(),
            "observed_facts": distinctions.get("observed_facts", []),
            "model_inferences": distinctions.get("model_inferences", []),
            "screenshot_path": screenshot_path,
        }

        return DeviceActionResult(True, formatted_msg, summary_data)

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
            elif action in ("open_url", "navigate"):
                target_url = step_data.get("url") or target
                step_res = self._browser_open_url(target_url)
            elif action in ("snapshot", "scrape"):
                target_url = step_data.get("url") or target
                step_res = self._browser_scrape(target_url, selector=step_data.get("selector", "body"))
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
        clean_text = re.sub(
            r"^(?:exactly\s*[:=]?|text\s*[:=]?)\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        if not clean_text:
            return DeviceActionResult(False, "No text was provided.")

        canonical = self.resolve_app_name(app_name) if app_name else ""

        if self.dry_run:
            return DeviceActionResult(
                True,
                "Typed text.",
                {"text": clean_text, "appName": canonical, "verified": True, "already_present": False},
            )

        if self.system == "darwin":
            if canonical == "Notes":
                return self._type_text_macos_notes(clean_text)
            elif canonical:
                return self._type_text_macos_generic(clean_text, canonical)
            else:
                return self._type_text_macos_generic(clean_text)
        elif self.system == "windows":
            if canonical:
                focus = self._focus_app(canonical)
                if not focus.ok:
                    return focus
            escaped = clean_text.replace("'", "''")
            script = f"$ws=New-Object -ComObject WScript.Shell; $ws.SendKeys('{escaped}')"
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
            return DeviceActionResult(True, "Typed text.", {"text": clean_text, "appName": canonical, "verified": True})
        else:
            return DeviceActionResult(False, "Type text is not implemented for this OS.")

    def _type_text_macos_notes(self, text: str) -> DeviceActionResult:
        # Step 1: Ensure Notes is running
        if not self.is_app_running("Notes"):
            open_res = self._open_app("Notes")
            if not open_res.ok:
                return DeviceActionResult(False, f"Failed to launch Notes: {open_res.message}", {"text": text, "appName": "Notes", "verified": False})
            time.sleep(0.5)

        # Step 2: Ensure Notes is activated and focused
        focus_res = self._focus_app("Notes")
        if not focus_res.ok:
            return DeviceActionResult(False, f"Failed to focus Notes: {focus_res.message}", {"text": text, "appName": "Notes", "verified": False})

        # Step 3: Delegate to NotesAdapter
        adapter = self.notes_adapter
        res = adapter._execute_type_text(text, time.time())
        return DeviceActionResult(
            ok=res.success,
            message=res.message,
            data=res.data,
        )

    def _type_text_macos_generic(self, text: str, app_name: str = "") -> DeviceActionResult:
        canonical = self.resolve_app_name(app_name) if app_name else ""
        if canonical:
            if not self.is_app_running(canonical):
                open_res = self._open_app(canonical)
                if not open_res.ok:
                    return open_res
                time.sleep(0.5)
            focus_res = self._focus_app(canonical)
            if not focus_res.ok:
                return focus_res

        escaped_text = self._apple_string(text)
        script = f"""
        tell application "System Events"
            set frontProc to first process whose frontmost is true
            set focElem to missing value
            try
                set focElem to (first UI element of frontProc whose focused is true)
            end try
            set beforeVal to ""
            try
                if focElem is not missing value then
                    set beforeVal to (value of focElem as string)
                end if
            end try

            if beforeVal contains {escaped_text} then
                return "ALREADY_PRESENT"
            end if

            keystroke {escaped_text}
            delay 0.2

            set afterVal to ""
            try
                if focElem is not missing value then
                    set afterVal to (value of focElem as string)
                end if
            end try

            if afterVal contains {escaped_text} then
                return "VERIFIED"
            else
                if focElem is missing value or afterVal is "" then
                    return "UNVERIFIED_ACCESSIBILITY_UNAVAILABLE"
                else
                    return "UNVERIFIED"
                end if
            end if
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8.0)
            output = (res.stdout or "").strip()
            if output == "VERIFIED":
                return DeviceActionResult(
                    True,
                    f"Typed text into {canonical or 'active application'} and verified.",
                    {"text": text, "appName": canonical, "verified": True, "already_present": False},
                )
            elif output == "ALREADY_PRESENT":
                return DeviceActionResult(
                    True,
                    f"Text already present in {canonical or 'active application'}. Duplicate typing prevented.",
                    {"text": text, "appName": canonical, "verified": True, "already_present": True},
                )
            elif output == "UNVERIFIED_ACCESSIBILITY_UNAVAILABLE":
                return DeviceActionResult(
                    True,
                    f"Typed text into {canonical or 'active application'}, but target element does not expose accessibility value for verification.",
                    {"text": text, "appName": canonical, "verified": False, "unverified": True},
                )
            elif output == "UNVERIFIED":
                return DeviceActionResult(
                    False,
                    f"Typed text into {canonical or 'active application'}, but text was not verified in target field.",
                    {"text": text, "appName": canonical, "verified": False, "unverified": True},
                )
            else:
                return DeviceActionResult(
                    True,
                    f"Dispatched keystroke to {canonical or 'active application'}.",
                    {"text": text, "appName": canonical, "verified": False, "unverified": True},
                )
        except Exception as e:
            return DeviceActionResult(
                False,
                f"Keystroke dispatch failed: {e}",
                {"text": text, "appName": canonical, "verified": False},
            )

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
        adapter = self.notes_adapter
        res = adapter.execute_action("create_note", {"title": title, "body": body})
        if res.success:
            self._note_store[title] = {"title": title, "body": body}
            return DeviceActionResult(True, res.message, res.data)
        return DeviceActionResult(False, res.message, res.data)

    def update_note_title(self, old_title: str, new_title: str) -> DeviceActionResult:
        """Modifies the title of an existing note in Apple Notes."""
        adapter = self.notes_adapter
        res = adapter.execute_action("update_title", {"old_title": old_title, "new_title": new_title})
        if res.success:
            if old_title in self._note_store:
                data = self._note_store.pop(old_title)
                data["title"] = new_title
                self._note_store[new_title] = data
            else:
                self._note_store[new_title] = {"title": new_title, "body": ""}
            return DeviceActionResult(True, res.message, res.data)
        return DeviceActionResult(False, res.message, res.data)

    def append_note(self, title: str, addition: str) -> DeviceActionResult:
        """Appends new points or content to an existing note without creating duplicates."""
        adapter = self.notes_adapter
        res = adapter.execute_action("append_note", {"title": title, "addition": addition})
        if res.success:
            if title in self._note_store:
                self._note_store[title]["body"] += f"\n{addition}"
            else:
                self._note_store[title] = {"title": title, "body": addition}
            return DeviceActionResult(True, res.message, res.data)
        return DeviceActionResult(False, res.message, res.data)

    def open_note(self, title: str) -> DeviceActionResult:
        """Opens and focuses an existing note in Apple Notes."""
        adapter = self.notes_adapter
        res = adapter.execute_action("open_note", {"title": title})
        return DeviceActionResult(res.success, res.message, res.data)

    def verify_note(self, title: str, expected_content: str = "") -> dict[str, Any]:
        """Queries Apple Notes to verify that the note exists with expected title and body."""
        adapter = self.notes_adapter
        obs = adapter.observe({"title": title, "text": expected_content})
        note_exists = obs.state_data.get("note_exists", False)
        note_content = obs.state_data.get("note_content", "")
        if not note_exists and title in self._note_store:
            note_exists = True
            note_content = self._note_store[title].get("body", "")
        verified = bool(note_exists and (not expected_content or expected_content.lower() in note_content.lower()))
        return {
            "verified": verified,
            "title": obs.state_data.get("note_title", title),
            "body": note_content,
            "evidence": f"Note '{title}' confirmed in Apple Notes" if verified else f"Note '{title}' not found",
        }

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

    def _create_directory(self, path_str: str) -> DeviceActionResult:
        safe, p = _is_safe_path(path_str)
        if not safe:
            return DeviceActionResult(False, f"Blocked unsafe path traversal: {path_str}")
        try:
            p.mkdir(parents=True, exist_ok=True)
            return DeviceActionResult(True, f"Created directory '{p.name}'", {"path": str(p), "directory": str(p), "name": p.name})
        except Exception as e:
            return DeviceActionResult(False, f"Failed to create directory: {e}")

    def _write_file(self, path_str: str, content: str) -> DeviceActionResult:
        if not path_str or str(path_str).strip() in ("", "."):
            path_str = str(Path.home() / "Desktop" / "notes.txt")
        safe, p = _is_safe_path(path_str)
        if not safe:
            return DeviceActionResult(False, f"Blocked unsafe path traversal: {path_str}")
        if p.is_dir():
            p = p / "notes.txt"
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

    def _search_files(
        self,
        pattern: str = "*",
        directory: str = ".",
        limit: int = 5,
        open_finder: bool = False,
        sort_by: str = "alphabetical",
    ) -> DeviceActionResult:
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
            target_dir = str(Path(directory).expanduser())

        safe, d = _is_safe_path(target_dir)
        if not safe:
            return DeviceActionResult(
                False,
                f"Access blocked: Path '{directory}' is restricted or contains invalid traversal.",
                {"error": "AccessBlocked", "directory": str(directory)},
            )
        if not d.exists():
            return DeviceActionResult(
                False,
                f"Directory not found: '{d}'. The specified path does not exist on this system.",
                {"error": "DirectoryNotFound", "directory": str(d)},
            )
        if not d.is_dir():
            return DeviceActionResult(
                False,
                f"Path is not a directory: '{d}'.",
                {"error": "NotADirectory", "directory": str(d)},
            )

        # ── Finder activation and navigation (macOS Darwin) ──────────────────
        finder_navigated = False
        finder_error = None
        finder_window_items: list[str] = []

        if open_finder and self.system == "darwin" and not self.dry_run:
            try:
                osa_script = (
                    f'tell application "Finder"\n'
                    f'  activate\n'
                    f'  open (POSIX file "{d.resolve()}" as alias)\n'
                    f'end tell'
                )
                res = subprocess.run(["osascript", "-e", osa_script], capture_output=True, text=True, timeout=3.0)
                if res.returncode == 0:
                    finder_navigated = True
                else:
                    res_open = subprocess.run(["open", "-a", "Finder", str(d.resolve())], capture_output=True, text=True, timeout=3.0)
                    if res_open.returncode == 0:
                        finder_navigated = True
                    else:
                        finder_error = (res.stderr or res_open.stderr or "Finder command returned error").strip()
            except Exception as e:
                finder_error = str(e)

            if finder_navigated:
                try:
                    osa_items = (
                        f'tell application "Finder"\n'
                        f'  get name of every item of (POSIX file "{d.resolve()}" as alias)\n'
                        f'end tell'
                    )
                    res_items = subprocess.run(["osascript", "-e", osa_items], capture_output=True, text=True, timeout=3.0)
                    if res_items.returncode == 0 and res_items.stdout.strip():
                        finder_window_items = [
                            n.strip()
                            for n in res_items.stdout.strip().split(",")
                            if n.strip() and not n.strip().startswith(".")
                        ]
                except Exception:
                    finder_window_items = []
        elif open_finder and self.dry_run:
            finder_navigated = True

        # ── Read-only filesystem inspection ──────────────────────────────────
        matches: list[str] = []
        pat_clean = (pattern or "").strip().lower()
        is_broad = pat_clean in ("*", "", "all", "files", "list", "show files", "list files", "downloads", "my downloads", "finder")

        try:
            if is_broad:
                with os.scandir(d) as it:
                    for entry in it:
                        name = entry.name
                        if not name.startswith("."):
                            matches.append(name)
            else:
                for root, _, files in os.walk(str(d)):
                    for f in files:
                        if not f.startswith(".") and pat_clean in f.lower():
                            rel_or_full = str(Path(root) / f) if root != str(d) else f
                            matches.append(rel_or_full)
        except PermissionError:
            err_msg = f"Permission denied accessing directory: '{d}'. Ensure Cortex has permission to read this directory."
            return DeviceActionResult(
                False,
                err_msg,
                {
                    "error": "PermissionDenied",
                    "directory": str(d),
                    "finder_navigated": finder_navigated,
                    "finder_error": finder_error,
                },
            )
        except OSError as oe:
            err_msg = f"Filesystem error accessing '{d}': {oe}"
            return DeviceActionResult(
                False,
                err_msg,
                {
                    "error": "OSError",
                    "directory": str(d),
                    "finder_navigated": finder_navigated,
                    "finder_error": finder_error,
                },
            )

        # Sort deterministically
        if sort_by == "mtime":
            def _get_mtime(fname: str) -> float:
                try:
                    return (d / fname).stat().st_mtime
                except Exception:
                    return 0.0
            matches.sort(key=_get_mtime, reverse=True)
            ordering_desc = "Modification time (newest first)"
        else:
            matches.sort(key=str.lower)
            ordering_desc = "Alphabetical (case-insensitive, ascending)"

        total_count = len(matches)
        top_names = matches[:limit]

        dir_display = d.name or str(d)
        lines: list[str] = [f"### Finder Inspection: {dir_display}\n"]

        if open_finder:
            if finder_navigated:
                lines.append(f"• **Finder Status:** Activated and navigated to `{d}`.")
            else:
                err_str = f" ({finder_error})" if finder_error else ""
                lines.append(f"• **Finder Status:** Navigation failed or unavailable{err_str}.")

        lines.append("• **Inspection Type:** Directory entries (read-only filesystem listing).")
        lines.append(f"• **Ordering:** {ordering_desc}.")

        if total_count == 0:
            lines.append("• **Items displayed:** 0 entries found (directory is empty).\n")
            lines.append(f"The directory `{dir_display}` contains no visible files.")
        else:
            count_label = f"{len(top_names)} of {total_count}" if total_count > len(top_names) else f"{len(top_names)}"
            lines.append(f"• **Items displayed:** First {count_label} entries.\n")
            for idx, name in enumerate(top_names, 1):
                lines.append(f"{idx}. `{name}`")

        if finder_window_items:
            lines.append(f"\n• **Finder Window Verification:** Confirmed matching front Finder window items via macOS Finder AppleScript.")
        else:
            lines.append(f"\n• **Finder Window Verification:** Directory entries verified via filesystem API.")

        lines.append("• **Filesystem Status:** Verified read-only inspection. No files were created, modified, renamed, or deleted.")

        msg = "\n".join(lines)
        return DeviceActionResult(
            True,
            msg,
            {
                "directory": str(d),
                "count": total_count,
                "displayed_count": len(top_names),
                "names": top_names,
                "all_matches": matches,
                "files": [str(d / n) for n in top_names],
                "finder_navigated": finder_navigated,
                "finder_window_verified": bool(finder_window_items),
                "finder_window_items": finder_window_items[:limit] if finder_window_items else [],
                "ordering": ordering_desc,
                "read_only": True,
            },
        )

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
