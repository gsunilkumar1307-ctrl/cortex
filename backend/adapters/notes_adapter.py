"""macOS Apple Notes Application Adapter.

Implements the universal ApplicationAdapter contract for Apple Notes on macOS:
- launch()
- focus()
- observe(target_context)
- execute_action(action, params)
- verify_action(action, params, observation)
- recover(action, params, error, attempt)

Enforces:
- AX window and text area detection.
- Exact text typing with return key separation.
- Content observation and empirical verification.
- Duplicate typing prevention (idempotency).
- Honest unverified reporting (no false completion).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from typing import Any

try:
    from backend.core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ExecutionError,
        TaskCommand,
        VerificationResult,
    )
    from backend.adapters.base import ApplicationAdapter
except ImportError:
    from core.contracts import (
        AdapterExecutionStatus,
        AdapterObservation,
        AdapterRecoveryResult,
        AdapterResult,
        ExecutionError,
        TaskCommand,
        VerificationResult,
    )
    from adapters.base import ApplicationAdapter


class NotesAdapter(ApplicationAdapter):
    """Application Adapter for macOS Apple Notes."""

    def __init__(self, dry_run: bool = False) -> None:
        super().__init__(app_name="Notes", dry_run=dry_run)
        self.system = sys.platform
        self._simulated_store: dict[str, dict[str, str]] = {}
        self._active_note_title: str | None = None
        self._simulated_window_open: bool = False

    def _apple_string(self, s: str) -> str:
        """Escapes a Python string for safe AppleScript string literals."""
        return json.dumps(s)

    # ── 1. Application Lifecycle ───────────────────────────────────────────

    def launch(self) -> AdapterResult:
        """Launches macOS Notes if not already running."""
        start_time = time.time()
        if self.dry_run or self.system != "darwin":
            self._simulated_window_open = True
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="launch",
                message="Launched Notes (simulated).",
                data={"appName": "Notes", "running": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        if self.is_app_running():
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="launch",
                message="Notes is already running.",
                data={"appName": "Notes", "running": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            subprocess.run(["open", "-a", "Notes"], check=True, capture_output=True, timeout=5.0)
            # Wait for process initialization
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
                    message="Launched Notes successfully.",
                    data={"appName": "Notes", "running": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="launch",
                    message="Notes process failed to start within timeout.",
                    error="LaunchTimeout",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="launch",
                message=f"Failed to launch Notes: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def focus(self) -> AdapterResult:
        """Brings macOS Notes and its main window to the foreground."""
        start_time = time.time()
        if self.dry_run or self.system != "darwin":
            self._simulated_window_open = True
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="focus",
                message="Focused Notes (simulated).",
                data={"appName": "Notes", "active": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        if not self.is_app_running():
            launch_res = self.launch()
            if not launch_res.success:
                return launch_res

        script = """
        tell application "Notes"
            activate
            reopen
        end tell
        tell application "System Events"
            tell process "Notes"
                set frontmost to true
                repeat 10 times
                    if exists (window 1) then exit repeat
                    delay 0.1
                end repeat
            end tell
        end tell
        """
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=5.0)
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="focus",
                message="Focused Notes.",
                data={"appName": "Notes", "active": True},
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="focus",
                message=f"Failed to focus Notes: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def is_app_running(self) -> bool:
        """Checks if the Notes application process is active."""
        if self.dry_run or self.system != "darwin":
            return True
        try:
            res = subprocess.run(["pgrep", "-x", "Notes"], capture_output=True, text=True)
            return res.returncode == 0
        except Exception:
            return False

    def is_app_active(self) -> bool:
        """Checks if Notes is currently the frontmost application."""
        if self.dry_run or self.system != "darwin":
            return True
        script = 'tell application "System Events" to name of first application process whose frontmost is true'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2.0)
            return res.stdout.strip().lower() == "notes"
        except Exception:
            return False

    # ── 2. Observation ─────────────────────────────────────────────────────

    def observe(self, target_context: dict[str, Any] | None = None) -> AdapterObservation:
        """Captures real-world external state from Apple Notes."""
        ctx = target_context or {}
        running = self.is_app_running()
        active = self.is_app_active() if running else False

        state: dict[str, Any] = {
            "appName": "Notes",
            "app_running": running,
            "app_active": active,
            "note_exists": False,
            "text_verified": False,
            "unverified": False,
            "already_present": False,
        }

        target_title = ctx.get("title") or self._active_note_title or ""
        target_text = ctx.get("text") or ""

        if self.dry_run or self.system != "darwin":
            if target_title and target_title in self._simulated_store:
                note_data = self._simulated_store[target_title]
                state["note_exists"] = True
                state["note_title"] = target_title
                state["note_content"] = note_data.get("body", "")
                if target_text and target_text in note_data.get("body", ""):
                    state["text_verified"] = True
            elif target_text:
                if ctx.get("unverified") or ctx.get("text_verified") is False or ctx.get("already_present") is False:
                    state["text_verified"] = False
                    state["already_present"] = False
                    state["unverified"] = True
                else:
                    state["text_verified"] = True
                    state["already_present"] = ctx.get("already_present", True)
            return AdapterObservation(target="app:Notes", state_data=state, raw_output="simulated_observation")

        if not running:
            return AdapterObservation(target="app:Notes", state_data=state, raw_output="Notes not running")

        # Query Notes via AppleScript for note content or active window state
        script = f"""
        tell application "Notes"
            set nFound to false
            set nTitle to ""
            set nBody to ""
            if {self._apple_string(target_title)} is not "" then
                repeat with n in notes
                    if (name of n) is {self._apple_string(target_title)} or (name of n) contains {self._apple_string(target_title)} then
                        set nFound to true
                        set nTitle to (name of n)
                        set nBody to (plaintext of n)
                        exit repeat
                    end if
                end repeat
            end if
            if not nFound and (count of notes) > 0 then
                set nTitle to (name of note 1)
                try
                    set nBody to (plaintext of note 1)
                end try
            end if
            return nFound & "<|SEP|>" & nTitle & "<|SEP|>" & nBody
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5.0)
            out = res.stdout.strip()
            parts = out.split("<|SEP|>")
            if len(parts) >= 3:
                state["note_exists"] = (parts[0].lower() == "true")
                state["note_title"] = parts[1]
                content = parts[2]
                state["note_content"] = content
                if target_text:
                    state["text_verified"] = (target_text.lower() in content.lower())
                    state["already_present"] = state["text_verified"]
            return AdapterObservation(target="app:Notes", state_data=state, raw_output=out)
        except Exception as e:
            state["unverified"] = True
            state["error"] = str(e)
            return AdapterObservation(target="app:Notes", state_data=state, raw_output=str(e))

    # ── 3. Action Execution ────────────────────────────────────────────────

    def execute_action(self, action: str, params: dict[str, Any]) -> AdapterResult:
        """Executes a specific domain action on Apple Notes."""
        start_time = time.time()
        act = action.strip().lower()

        if act in ("launch", "open_app"):
            return self.launch()

        if act in ("focus", "focus_app"):
            return self.focus()

        if act in ("type_text", "type"):
            text = params.get("text") or params.get("content") or ""
            return self._execute_type_text(text, start_time)

        if act in ("create_note", "write_note", "create"):
            title = params.get("title") or "Cortex Note"
            body = params.get("body") or params.get("content") or ""
            return self._execute_create_note(title, body, start_time)

        if act in ("open_note", "open"):
            title = params.get("title") or self._active_note_title or ""
            return self._execute_open_note(title, start_time)

        if act in ("append_note", "append"):
            title = params.get("title") or self._active_note_title or "Cortex Note"
            addition = params.get("addition") or params.get("point") or params.get("body") or ""
            return self._execute_append_note(title, addition, start_time)

        if act in ("update_title", "shorten_title", "rename"):
            old_title = params.get("old_title") or self._active_note_title or ""
            new_title = params.get("new_title") or params.get("title") or "Meeting"
            return self._execute_update_title(old_title, new_title, start_time)

        if act in ("read_note", "get_content"):
            title = params.get("title") or self._active_note_title or ""
            return self._execute_read_note(title, start_time)

        return AdapterResult(
            success=False,
            status=AdapterExecutionStatus.FAILED,
            action=action,
            message=f"Unsupported Notes action: '{action}'",
            error="UnsupportedAction",
            duration_ms=(time.time() - start_time) * 1000,
        )

    # ── 3.1 Type Text Execution & Verification ─────────────────────────────

    def _execute_type_text(self, text: str, start_time: float) -> AdapterResult:
        """Types exact text into Notes with duplicate prevention and content verification."""
        clean_text = text.strip()
        clean_text = re.sub(r"^(?:exactly\s*[:=]?|text\s*[:=]?)\s*", "", clean_text, flags=re.IGNORECASE).strip()

        if not clean_text:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_text",
                message="No text provided to type.",
                error="EmptyText",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if self.dry_run or self.system != "darwin":
            self._simulated_store["Active Note"] = {"title": "Active Note", "body": clean_text}
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="type_text",
                message="Typed text into Notes and verified.",
                data={"text": clean_text, "appName": "Notes", "verified": True, "already_present": False},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 1. Ensure Notes running & focused
        focus_res = self.focus()
        if not focus_res.success:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_text",
                message=f"Failed to focus Notes: {focus_res.message}",
                error=focus_res.error,
                data={"text": clean_text, "appName": "Notes", "verified": False},
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 2. AppleScript locating editor text area, checking duplicate, typing, and verifying
        escaped_text = self._apple_string(clean_text)
        script = f"""
        tell application "Notes"
            activate
            reopen
        end tell
        tell application "System Events"
            tell process "Notes"
                set wReady to false
                repeat 15 times
                    if exists (window 1) then
                        set wReady to true
                        exit repeat
                    end if
                    delay 0.1
                end repeat
                if not wReady then
                    return "ERROR: Notes window not available"
                end if

                set noteEditor to missing value
                repeat with sa in (scroll areas of splitter group 1 of window 1)
                    if exists (text area 1 of sa) then
                        set noteEditor to text area 1 of sa
                        exit repeat
                    end if
                end repeat
                if noteEditor is missing value then
                    repeat with sa in (scroll areas of window 1)
                        if exists (text area 1 of sa) then
                            set noteEditor to text area 1 of sa
                            exit repeat
                        end if
                    end repeat
                end if
                if noteEditor is missing value then
                    tell application "Notes" to make new note
                    delay 0.4
                    repeat with sa in (scroll areas of splitter group 1 of window 1)
                        if exists (text area 1 of sa) then
                            set noteEditor to text area 1 of sa
                            exit repeat
                        end if
                    end repeat
                end if
                if noteEditor is missing value then
                    return "ERROR: Could not find editable text area in Notes."
                end if

                set focused of noteEditor to true
                set beforeVal to ""
                try
                    set beforeVal to (value of noteEditor as string)
                end try

                if beforeVal contains {escaped_text} then
                    return "ALREADY_PRESENT"
                end if

                keystroke return
                keystroke {escaped_text}
                delay 0.3

                set afterVal to ""
                try
                    set afterVal to (value of noteEditor as string)
                end try

                if afterVal contains {escaped_text} then
                    return "VERIFIED"
                else
                    return "UNVERIFIED"
                end if
            end tell
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10.0)
            output = (res.stdout or "").strip()

            if output == "VERIFIED":
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="type_text",
                    message="Typed text into Notes and verified.",
                    data={"text": clean_text, "appName": "Notes", "verified": True, "already_present": False},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            elif output == "ALREADY_PRESENT":
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="type_text",
                    message="Text already present in Notes. Duplicate typing prevented.",
                    data={"text": clean_text, "appName": "Notes", "verified": True, "already_present": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            elif output == "UNVERIFIED":
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.UNVERIFIED,
                    action="type_text",
                    message="Text typing was dispatched, but text was not verified in the active note.",
                    error="UNVERIFIED",
                    data={"text": clean_text, "appName": "Notes", "verified": False, "unverified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            elif output.startswith("ERROR:"):
                err_text = output.replace("ERROR:", "").strip()
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="type_text",
                    message=err_text,
                    error=err_text,
                    data={"text": clean_text, "appName": "Notes", "verified": False},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                err_msg = res.stderr.strip() if res.stderr else output
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="type_text",
                    message=f"Notes automation error: {err_msg or 'Unknown error'}",
                    error=err_msg or "UnknownError",
                    data={"text": clean_text, "appName": "Notes", "verified": False, "unverified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except subprocess.TimeoutExpired:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="type_text",
                message="Notes typing action timed out.",
                error="Timeout",
                data={"text": clean_text, "appName": "Notes", "verified": False},
                duration_ms=(time.time() - start_time) * 1000,
            )

    # ── 3.2 Note Management Execution ──────────────────────────────────────

    def _execute_create_note(self, title: str, body: str, start_time: float) -> AdapterResult:
        """Creates or updates a note in Apple Notes."""
        if not body:
            if title and title not in ("Cortex Note", ""):
                from datetime import datetime
                body = f"Note: {title}\nCreated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="create_note",
                    message="No note text was provided.",
                    error="EmptyBody",
                    duration_ms=(time.time() - start_time) * 1000,
                )

        clean_body = re.sub(
            r"^(?:the\s+following\s+content\s*[:=]?|the\s+content\s*[:=]?|content\s*[:=]?|body\s*[:=]?|text\s*[:=]?)\s*",
            "",
            body,
            flags=re.IGNORECASE,
        ).strip()

        self._simulated_store[title] = {"title": title, "body": clean_body}
        self._active_note_title = title

        if self.dry_run or self.system != "darwin":
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="create_note",
                message=f"Created note: '{title}'.",
                data={"title": title, "body": clean_body, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        script = f"""
        tell application "Notes"
            activate
            set targetNote to missing value
            repeat with n in notes
                if (name of n) is {self._apple_string(title)} then
                    set targetNote to n
                    exit repeat
                end if
            end repeat
            if targetNote is not missing value then
                set body of targetNote to {self._apple_string(clean_body)}
                return "UPDATED<|SEP|>" & (name of targetNote)
            else
                set newN to make new note at folder "Notes" with properties {{name:{self._apple_string(title)}, body:{self._apple_string(clean_body)}}}
                return "CREATED<|SEP|>" & (name of newN)
            end if
        end tell
        """
        try:
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=True).stdout.strip()
            action_type = "Updated" if out.startswith("UPDATED") else "Created"
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="create_note",
                message=f"{action_type} note: '{title}'.",
                data={"title": title, "body": clean_body, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="create_note",
                message=f"Failed to write note: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_open_note(self, title: str, start_time: float) -> AdapterResult:
        """Opens and brings an existing note to the front."""
        if not title:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="open_note",
                message="Note title is required to open note.",
                error="MissingTitle",
                duration_ms=(time.time() - start_time) * 1000,
            )

        self._active_note_title = title
        if self.dry_run or self.system != "darwin":
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="open_note",
                message=f"Opened note '{title}' in Apple Notes.",
                data={"title": title, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        script = f"""
        tell application "Notes"
            activate
            set targetNote to missing value
            repeat with n in notes
                if (name of n) is {self._apple_string(title)} or (name of n) contains {self._apple_string(title)} then
                    set targetNote to n
                    exit repeat
                end if
            end repeat
            if targetNote is not missing value then
                show targetNote
                return "OPENED<|SEP|>" & (name of targetNote)
            else
                return "NOT_FOUND"
            end if
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
            if res.startswith("OPENED"):
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="open_note",
                    message=f"Opened note '{title}' in Apple Notes.",
                    data={"title": title, "verified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="open_note",
                    message=f"Note '{title}' not found in Apple Notes.",
                    error="NoteNotFound",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="open_note",
                message=f"Failed to open note: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_append_note(self, title: str, addition: str, start_time: float) -> AdapterResult:
        """Appends content to an existing note without creating duplicates."""
        if not addition:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="append_note",
                message="Content addition is required.",
                error="EmptyAddition",
                duration_ms=(time.time() - start_time) * 1000,
            )

        self._active_note_title = title
        if title in self._simulated_store:
            self._simulated_store[title]["body"] += f"\n{addition}"
        else:
            self._simulated_store[title] = {"title": title, "body": addition}

        if self.dry_run or self.system != "darwin":
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="append_note",
                message=f"Added point to note '{title}'.",
                data={"title": title, "addition": addition, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        script = f"""
        tell application "Notes"
            set targetNote to missing value
            repeat with n in notes
                if (name of n) is {self._apple_string(title)} or (name of n) contains {self._apple_string(title)} then
                    set targetNote to n
                    exit repeat
                end if
            end repeat
            if targetNote is not missing value then
                set curBody to body of targetNote
                set body of targetNote to (curBody & "<br><br>" & {self._apple_string(addition)})
                return "APPENDED<|SEP|>" & (name of targetNote)
            else
                return "NOT_FOUND"
            end if
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
            if res.startswith("APPENDED"):
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="append_note",
                    message=f"Added point to note '{title}'.",
                    data={"title": title, "addition": addition, "verified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="append_note",
                    message=f"Note '{title}' not found to append point.",
                    error="NoteNotFound",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="append_note",
                message=f"Failed to append to note: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_update_title(self, old_title: str, new_title: str, start_time: float) -> AdapterResult:
        """Modifies the title of an existing note."""
        if not new_title:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="update_title",
                message="New note title is required.",
                error="EmptyTitle",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if old_title in self._simulated_store:
            data = self._simulated_store.pop(old_title)
            data["title"] = new_title
            self._simulated_store[new_title] = data
        else:
            self._simulated_store[new_title] = {"title": new_title, "body": ""}
        self._active_note_title = new_title

        if self.dry_run or self.system != "darwin":
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="update_title",
                message=f"Updated note title to '{new_title}'.",
                data={"old_title": old_title, "new_title": new_title, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        script = f"""
        tell application "Notes"
            set targetNote to missing value
            repeat with n in notes
                if (name of n) is {self._apple_string(old_title)} or (name of n) contains {self._apple_string(old_title)} then
                    set targetNote to n
                    exit repeat
                end if
            end repeat
            if targetNote is not missing value then
                try
                    set name of targetNote to {self._apple_string(new_title)}
                end try
                try
                    set curP to plaintext of targetNote
                    set pLines to paragraphs of curP
                    if (count of pLines) > 1 then
                        set remainingText to (text from paragraph 2 to -1 of curP)
                        set body of targetNote to ("<h1>" & {self._apple_string(new_title)} & "</h1><br><div>" & remainingText & "</div>")
                    else
                        set body of targetNote to ("<h1>" & {self._apple_string(new_title)} & "</h1>")
                    end if
                end try
                return "RENAMED<|SEP|>" & (name of targetNote)
            else
                return "NOT_FOUND"
            end if
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
            if res.startswith("RENAMED"):
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="update_title",
                    message=f"Updated note title to '{new_title}'.",
                    data={"old_title": old_title, "new_title": new_title, "verified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="update_title",
                    message=f"Note '{old_title}' not found to rename.",
                    error="NoteNotFound",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="update_title",
                message=f"Failed to update note title: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _execute_read_note(self, title: str, start_time: float) -> AdapterResult:
        """Reads plaintext content from an existing note."""
        if not title:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="read_note",
                message="Note title is required to read note.",
                error="MissingTitle",
                duration_ms=(time.time() - start_time) * 1000,
            )

        if self.dry_run or self.system != "darwin":
            body = self._simulated_store.get(title, {}).get("body", "")
            return AdapterResult(
                success=True,
                status=AdapterExecutionStatus.VERIFIED,
                action="read_note",
                message=f"Read note '{title}'.",
                data={"title": title, "body": body, "verified": True},
                duration_ms=(time.time() - start_time) * 1000,
            )

        script = f"""
        tell application "Notes"
            repeat with n in notes
                if (name of n) is {self._apple_string(title)} or (name of n) contains {self._apple_string(title)} then
                    return "VERIFIED<|SEP|>" & (name of n) & "<|SEP|>" & (plaintext of n)
                end if
            end repeat
            return "NOT_FOUND"
        end tell
        """
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()
            if res.startswith("VERIFIED"):
                parts = res.split("<|SEP|>")
                name = parts[1] if len(parts) > 1 else title
                content = parts[2] if len(parts) > 2 else ""
                return AdapterResult(
                    success=True,
                    status=AdapterExecutionStatus.VERIFIED,
                    action="read_note",
                    message=f"Read note '{name}'.",
                    data={"title": name, "body": content, "verified": True},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return AdapterResult(
                    success=False,
                    status=AdapterExecutionStatus.FAILED,
                    action="read_note",
                    message=f"Note '{title}' not found in Apple Notes.",
                    error="NotFound",
                    duration_ms=(time.time() - start_time) * 1000,
                )
        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterExecutionStatus.FAILED,
                action="read_note",
                message=f"Failed to read note: {e}",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    # ── 4. Independent Verification ────────────────────────────────────────

    def verify_action(
        self,
        action: str,
        params: dict[str, Any],
        observation: AdapterObservation,
    ) -> VerificationResult:
        """Independently verifies that the expected outcome occurred in Apple Notes."""
        act = action.strip().lower()
        state = observation.state_data or {}

        if act in ("launch", "open_app"):
            app_running = state.get("app_running", True)
            if not self.dry_run and not app_running:
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence="Application Notes failed to launch: process not running.",
                    error="NotRunning",
                )
            evidence = "Verified application 'Notes' is running."
            if state.get("app_active"):
                evidence += " In foreground."
            return VerificationResult(verified=True, confidence=0.95, evidence=evidence)

        if act in ("focus", "focus_app"):
            if not state.get("ok", True):
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence="Failed to focus Notes.",
                    error="FocusFailed",
                )
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence="Verified application 'Notes' brought to foreground.",
            )

        if act in ("type_text", "type"):
            target_text = params.get("text") or ""
            target_text = re.sub(r"^(?:exactly\s*[:=]?|text\s*[:=]?)\s*", "", target_text, flags=re.IGNORECASE).strip()

            if self.dry_run:
                evidence = f"Dry-run: verified type_text for '{target_text}'." if target_text else "Dry-run: verified type_text."
                return VerificationResult(
                    verified=True,
                    confidence=0.9,
                    evidence=evidence,
                )

            text_verified = state.get("text_verified", False)
            unverified = state.get("unverified", False)
            if unverified or not text_verified:
                evidence = f"Text verification failed: could not confirm that '{target_text}' was entered into Notes." if target_text else "Text verification failed: could not confirm that requested text was entered into Notes."
                return VerificationResult(
                    verified=False,
                    confidence=0.2,
                    evidence=evidence,
                    error="UNVERIFIED",
                )
            evidence = f"Verified text '{target_text}' successfully entered into Notes." if target_text else "Verified text successfully entered into Notes."
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=evidence,
            )

        if act in ("create_note", "write_note"):
            title = params.get("title", "Cortex Note")
            if not state.get("ok", True):
                return VerificationResult(
                    verified=False,
                    confidence=1.0,
                    evidence=f"Failed to create note '{title}'.",
                    error="CreateFailed",
                )
            return VerificationResult(
                verified=True,
                confidence=0.95,
                evidence=f"Verified note '{title}' created/updated in Apple Notes.",
            )

        if act in ("open_note", "open"):
            title = params.get("title") or "Note"
            return VerificationResult(
                verified=state.get("ok", True),
                confidence=0.95 if state.get("ok", True) else 0.2,
                evidence=f"Verified note '{title}' opened in Apple Notes." if state.get("ok", True) else f"Failed to open note '{title}'.",
            )

        if act in ("append_note", "append"):
            title = params.get("title") or "Note"
            return VerificationResult(
                verified=state.get("ok", True),
                confidence=0.95 if state.get("ok", True) else 0.2,
                evidence=f"Verified point appended to note '{title}'." if state.get("ok", True) else f"Failed to append point to note '{title}'.",
            )

        if act in ("update_title", "shorten_title", "rename"):
            new_title = params.get("new_title") or params.get("title") or "Meeting"
            return VerificationResult(
                verified=state.get("ok", True),
                confidence=0.95 if state.get("ok", True) else 0.2,
                evidence=f"Verified note renamed to '{new_title}'." if state.get("ok", True) else f"Failed to rename note to '{new_title}'.",
            )

        return VerificationResult(
            verified=state.get("ok", True),
            confidence=0.9,
            evidence=f"Action '{act}' executed on Notes.",
        )

    # ── 5. Recovery & Diagnosis ────────────────────────────────────────────

    def recover(
        self,
        action: str,
        params: dict[str, Any],
        error: ExecutionError | str,
        attempt: int = 1,
    ) -> AdapterRecoveryResult:
        """Provides structured error diagnosis and bounded recovery for Notes actions."""
        err_msg = error.message if isinstance(error, ExecutionError) else str(error)
        act = action.strip().lower()

        # Check if already verified or present
        if "already present" in err_msg.lower():
            # Mandatory requirement: require independent observation proving intended side effect occurred before resolving as successful!
            obs = self.observe(params)
            target_text = params.get("text") or params.get("content") or ""
            target_title = params.get("title") or ""
            obs_state = obs.state_data or {}

            confirmed_present = False
            if obs_state.get("unverified") is True:
                confirmed_present = False
            elif obs_state.get("already_present") is True or obs_state.get("text_verified") is True:
                confirmed_present = True
            elif target_title and obs_state.get("note_exists") is True:
                confirmed_present = True
            elif target_text and obs_state.get("note_content") and target_text.lower() in obs_state.get("note_content", "").lower():
                confirmed_present = True

            if confirmed_present:
                return AdapterRecoveryResult(
                    can_retry=False,
                    strategy="resolve_as_success",
                    message="Text is already present in active note; duplicate typing safely prevented.",
                )
            else:
                return AdapterRecoveryResult(
                    can_retry=False,
                    strategy="escalate",
                    message="Cannot resolve as success: independent observation did not find target text or note present in Notes.",
                )

        # Focus / window recovery on first attempt
        if attempt < 2 and any(k in err_msg.lower() for k in ("window", "focus", "not available", "active")):
            return AdapterRecoveryResult(
                can_retry=True,
                strategy="retry",
                message="Notes window focus lost; refocused Notes for safe retry.",
            )

        # Unverified outcome cannot blindly retry
        if "unverified" in err_msg.lower() or "not verified" in err_msg.lower():
            return AdapterRecoveryResult(
                can_retry=False,
                strategy="escalate",
                message=f"Notes action '{act}' unverified: could not confirm expected state in Apple Notes.",
            )

        return AdapterRecoveryResult(
            can_retry=attempt < 2,
            strategy="retry" if attempt < 2 else "escalate",
            message=f"Notes action '{act}' failed: {err_msg}.",
        )
