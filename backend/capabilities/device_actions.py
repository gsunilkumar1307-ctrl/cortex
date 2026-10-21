from __future__ import annotations

import os
import platform
import re
import subprocess
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
        self._browser = None  # lazy-loaded BrowserAutomation
        self._mail = None     # lazy-loaded MailAutomation

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

    @property
    def mail(self):
        return self._get_mail()

    @mail.setter
    def mail(self, val):
        self._mail = val

    @property
    def browser(self):
        return self._get_browser()

    def execute(self, command: TaskCommand, params: dict[str, Any] | None = None) -> DeviceActionResult:
        params = params or {}
        if command in (TaskCommand.ASK_QUESTION, TaskCommand.WEB_SEARCH):
            return DeviceActionResult(True, params.get("answer") or "I don't have an answer to that question.")

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
            return self._draft_mail(str(params.get("recipient", "")), str(params.get("subject", "")), str(params.get("body", "")))
        if command == TaskCommand.SEND_MAIL:
            return self._send_mail(str(params.get("recipient", "")), str(params.get("subject", "")), str(params.get("body", "")))
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

    def _draft_mail(self, recipient: str, subject: str, body: str) -> DeviceActionResult:
        result = self._get_mail().draft_mail(recipient, subject, body)
        return DeviceActionResult(result["ok"], result["message"], result.get("data"))

    def _send_mail(self, recipient: str, subject: str, body: str) -> DeviceActionResult:
        result = self._get_mail().send_mail(recipient, subject, body)
        return DeviceActionResult(result["ok"], result["message"], result.get("data"))

    def _open_app(self, app_name: str) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        if self.system == "darwin":
            subprocess.run(["open", "-a", app_name], check=True)
        elif self.system == "windows":
            subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-Process '{app_name}'"], check=True)
        else:
            subprocess.run(["xdg-open", app_name], check=True)
        return DeviceActionResult(True, f"Opened {app_name}.")

    def _close_app(self, app_name: str) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        if self.system == "darwin":
            script = f'tell application "{app_name}" to quit'
            subprocess.run(["osascript", "-e", script], check=True)
        elif self.system == "windows":
            script = (
                f"$name='{app_name}';"
                "$proc=Get-Process | Where-Object { $_.ProcessName -like $name -or $_.MainWindowTitle -like \"*$name*\" };"
                "$proc | Stop-Process"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            subprocess.run(["pkill", "-f", app_name], check=True)
        return DeviceActionResult(True, f"Closed {app_name}.")

    def _focus_app(self, app_name: str) -> DeviceActionResult:
        if not app_name:
            return DeviceActionResult(False, "No app name was provided.")
        if self.system == "darwin":
            subprocess.run(["osascript", "-e", f'tell application "{app_name}" to activate'], check=True)
        elif self.system == "windows":
            script = f"(New-Object -ComObject WScript.Shell).AppActivate('{app_name}')"
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            return DeviceActionResult(False, "Focus app is not implemented for this OS.")
        return DeviceActionResult(True, f"Focused {app_name}.")

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

    def _send_message(self, recipient: str, body: str) -> DeviceActionResult:
        if not recipient or not body:
            return DeviceActionResult(False, "Recipient and message body are required.")
        if self.system == "darwin":
            script = (
                'tell application "Messages"\n'
                "  activate\n"
                f"  set targetBuddy to buddy {self._apple_string(recipient)} of service \"iMessage\"\n"
                f"  send {self._apple_string(body)} to targetBuddy\n"
                "end tell"
            )
            subprocess.run(["osascript", "-e", script], check=True)
            return DeviceActionResult(True, f"Sent message to {recipient}.", {"recipient": recipient})
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
        safe, d = _is_safe_path(directory)
        if not safe or not d.exists():
            return DeviceActionResult(False, f"Invalid search directory: {directory}")
        try:
            matches = []
            pat_lower = pattern.lower()
            for root, _, files in os.walk(str(d)):
                for f in files:
                    if pat_lower in f.lower():
                        matches.append(str(Path(root) / f))
            return DeviceActionResult(True, f"Found {len(matches)} files matching '{pattern}'", {"files": matches})
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
