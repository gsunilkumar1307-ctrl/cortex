from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any
try:
    from backend.core.contracts import RiskLevel, TaskCommand
except ImportError:
    from cortex_sdk import RiskLevel, TaskCommand


@dataclass
class PolicyRule:
    command: TaskCommand
    risk_level: RiskLevel
    requires_approval: bool
    is_irreversible: bool
    description: str


class DuplicateCheckResult(tuple):
    """Result of duplicate / uncertainty check.
    Functions as a 2-tuple (is_duplicate, reason) for legacy tuple unpacking,
    while also supporting dict/attribute style access (.can_proceed, ['reason'], etc.).
    """
    def __new__(cls, is_duplicate: bool, reason: str | None = None, status: str | None = None):
        return super().__new__(cls, (is_duplicate, reason))

    def __init__(self, is_duplicate: bool, reason: str | None = None, status: str | None = None):
        super().__init__()
        self._is_duplicate = is_duplicate
        self._reason = reason
        self._status = status

    @property
    def is_duplicate(self) -> bool:
        return self._is_duplicate

    @property
    def can_proceed(self) -> bool:
        return not self._is_duplicate

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def status(self) -> str | None:
        return self._status

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            if item == "can_proceed":
                return self.can_proceed
            if item == "is_duplicate":
                return self.is_duplicate
            if item == "reason":
                return self.reason
            if item == "status":
                return self.status
        return super().__getitem__(item)


class PolicyEngine:
    """Centralized safety, risk evaluation, and duplicate action protection for Cortex."""

    def __init__(self, custom_rules: dict[TaskCommand, PolicyRule] | None = None) -> None:
        self.rules: dict[TaskCommand, PolicyRule] = {}
        self._executed_actions: dict[str, dict[str, Any]] = {}
        self._init_default_rules()
        if custom_rules:
            self.rules.update(custom_rules)

    def _init_default_rules(self) -> None:
        default_rules = [
            # Low Risk: Read-only, informational, or harmless local commands
            PolicyRule(TaskCommand.ASK_QUESTION, RiskLevel.LOW, False, False, "General question answering"),
            PolicyRule(TaskCommand.CALCULATE, RiskLevel.LOW, False, False, "Local math calculation"),
            PolicyRule(TaskCommand.WEB_SEARCH, RiskLevel.LOW, False, False, "Public web search"),
            PolicyRule(TaskCommand.OPEN_APP, RiskLevel.LOW, False, False, "Launch installed desktop application"),
            PolicyRule(TaskCommand.CLOSE_APP, RiskLevel.LOW, False, False, "Close running application"),
            PolicyRule(TaskCommand.FOCUS_APP, RiskLevel.LOW, False, False, "Switch active application window"),
            PolicyRule(TaskCommand.OPEN_URL, RiskLevel.LOW, False, False, "Navigate browser to destination URL"),
            PolicyRule(TaskCommand.SCREENSHOT, RiskLevel.LOW, False, False, "Capture screen image"),
            PolicyRule(TaskCommand.SCREEN_VISION, RiskLevel.LOW, False, False, "Observe and analyze visible screen content"),
            PolicyRule(TaskCommand.READ_MAIL, RiskLevel.LOW, False, False, "Read recent messages from inbox"),
            PolicyRule(TaskCommand.SUMMARIZE_MAIL, RiskLevel.LOW, False, False, "Summarize email messages"),
            PolicyRule(TaskCommand.DRAFT_MAIL, RiskLevel.LOW, False, False, "Create draft email (does not send)"),
            PolicyRule(TaskCommand.SEARCH_MAIL, RiskLevel.LOW, False, False, "Search email messages"),
            PolicyRule(TaskCommand.EMAIL_BRIEFING, RiskLevel.LOW, False, False, "Generate email briefing"),
            PolicyRule(TaskCommand.EXTRACT_ACTIONS, RiskLevel.LOW, False, False, "Extract action items from email"),
            PolicyRule(TaskCommand.CLIPBOARD_READ, RiskLevel.LOW, False, False, "Read clipboard contents"),
            PolicyRule(TaskCommand.NOTIFICATION, RiskLevel.LOW, False, False, "Post desktop notification"),
            PolicyRule(TaskCommand.REMINDER, RiskLevel.LOW, False, False, "Set local reminder"),
            PolicyRule(TaskCommand.READ_FILE, RiskLevel.LOW, False, False, "Read file within sandbox"),
            PolicyRule(TaskCommand.SEARCH_FILES, RiskLevel.LOW, False, False, "Search files in folder"),
            PolicyRule(TaskCommand.CALENDAR_READ, RiskLevel.LOW, False, False, "Read calendar events"),
            PolicyRule(TaskCommand.CALENDAR_CREATE, RiskLevel.LOW, False, False, "Create calendar appointment"),
            PolicyRule(TaskCommand.PERSONAL_TASK_CREATE, RiskLevel.LOW, False, False, "Add personal task"),
            PolicyRule(TaskCommand.PERSONAL_TASK_LIST, RiskLevel.LOW, False, False, "List personal tasks"),
            PolicyRule(TaskCommand.DAILY_BRIEFING, RiskLevel.LOW, False, False, "Compile daily briefing"),
            PolicyRule(TaskCommand.WRITE_NOTE, RiskLevel.LOW, False, False, "Create local note"),

            # Medium Risk: Keystrokes, non-destructive file writes, scraping
            PolicyRule(TaskCommand.TYPE_TEXT, RiskLevel.MEDIUM, False, False, "Type text into target application"),
            PolicyRule(TaskCommand.KEYSTROKE, RiskLevel.MEDIUM, False, False, "Press shortcut in target application"),
            PolicyRule(TaskCommand.MENU_ITEM, RiskLevel.MEDIUM, False, False, "Select application menu item"),
            PolicyRule(TaskCommand.BROWSER_SCRAPE, RiskLevel.MEDIUM, False, False, "Extract text from webpage"),
            PolicyRule(TaskCommand.WRITE_FILE, RiskLevel.MEDIUM, False, False, "Write file within sandbox"),

            # High Risk: External communication, browser actions submitting data, device control
            PolicyRule(TaskCommand.SEND_MAIL, RiskLevel.HIGH, True, True, "Send email to external recipient"),
            PolicyRule(TaskCommand.SEND_MESSAGE, RiskLevel.HIGH, True, True, "Send message via iMessage/WhatsApp/SMS"),
            PolicyRule(TaskCommand.BROWSER_CLICK, RiskLevel.HIGH, True, False, "Click element on external webpage"),
            PolicyRule(TaskCommand.BROWSER_TYPE, RiskLevel.HIGH, True, False, "Input data into external webpage form"),
            PolicyRule(TaskCommand.CLIPBOARD_WRITE, RiskLevel.HIGH, True, False, "Modify system clipboard"),
            PolicyRule(TaskCommand.SHUTDOWN, RiskLevel.HIGH, True, True, "Power off local computer"),
            PolicyRule(TaskCommand.RESTART, RiskLevel.HIGH, True, True, "Reboot local computer"),
        ]
        for r in default_rules:
            self.rules[r.command] = r

    def evaluate(self, command: TaskCommand | str, intent: str, params: dict[str, Any] | None = None) -> tuple[RiskLevel, bool, str | None]:
        text = intent.lower().strip()
        params = params or {}

        # 1. Critical / Blocked keywords always blocked
        blocked_keywords = [
            "delete file",
            "delete folder",
            "format disk",
            "rm -rf",
            "submit form",
            "payment",
            "buy ",
            "purchase",
            "wire money",
            "transfer money",
        ]
        if any(term in text for term in blocked_keywords):
            return RiskLevel.BLOCKED, False, "This action involves payments or destructive operations and is blocked."

        cmd_enum = self._to_command_enum(command)
        if cmd_enum == TaskCommand.UNKNOWN:
            return RiskLevel.BLOCKED, False, "Cortex does not support that device action yet."

        rule = self.rules.get(cmd_enum)
        if not rule:
            return RiskLevel.MEDIUM, True, "No specific policy rule defined; requiring approval for safety."

        return rule.risk_level, rule.requires_approval, None

    def _to_command_enum(self, command: TaskCommand | str) -> TaskCommand:
        if isinstance(command, TaskCommand):
            return command
        cmd_str = str(command).lower().strip()
        if cmd_str in ("send_email", "send_mail"):
            return TaskCommand.SEND_MAIL
        try:
            return TaskCommand(cmd_str)
        except Exception:
            return TaskCommand.UNKNOWN

    def is_irreversible(self, command: TaskCommand | str) -> bool:
        cmd_str = str(command.value if isinstance(command, TaskCommand) else command).lower()
        if cmd_str in ("send_email", "send_mail", "shutdown", "restart", "delete_file"):
            return True
        cmd_enum = self._to_command_enum(command)
        rule = self.rules.get(cmd_enum)
        return rule.is_irreversible if rule else False

    # ── Duplicate Action Protection ─────────────────────────────────────────────
    def compute_idempotency_key(self, command: TaskCommand | str, params: dict[str, Any]) -> str:
        """Derives a deterministic fingerprint for a command and its core parameters."""
        cmd_enum = self._to_command_enum(command)
        cmd_val = cmd_enum.value if cmd_enum != TaskCommand.UNKNOWN else str(command)
        normalized = f"{cmd_val}:"
        if cmd_enum in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL) or "mail" in cmd_val or "email" in cmd_val:
            rec = str(params.get("recipient", "")).lower().strip()
            subj = str(params.get("subject", "")).strip()
            body = str(params.get("body", "")).strip()
            normalized += f"{rec}:{subj}:{body}"
        elif cmd_enum == TaskCommand.SEND_MESSAGE or "message" in cmd_val:
            rec = str(params.get("recipient", "")).lower().strip()
            body = str(params.get("body", "")).strip()
            normalized += f"{rec}:{body}"
        elif cmd_enum == TaskCommand.WRITE_FILE:
            p = str(params.get("path", "")).strip()
            content = str(params.get("content", ""))
            normalized += f"{p}:{content}"
        else:
            sorted_items = sorted(params.items())
            normalized += str(sorted_items)

        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get_idempotency_key(self, command: TaskCommand | str, params: dict[str, Any]) -> str:
        return self.compute_idempotency_key(command, params)

    def record_execution_attempt(self, idempotency_key: str, command: TaskCommand | str = "action", metadata: dict[str, Any] | None = None) -> None:
        cmd_str = command.value if isinstance(command, TaskCommand) else str(command)
        self._executed_actions[idempotency_key] = {
            "command": cmd_str,
            "timestamp": time.time(),
            "status": "in_progress",
            "metadata": metadata or {},
        }

    def mark_execution_started(self, idempotency_key: str, command: TaskCommand | str = "action", metadata: dict[str, Any] | None = None) -> None:
        self.record_execution_attempt(idempotency_key, command, metadata)

    def mark_execution_completed(self, idempotency_key: str, status: str = "completed") -> None:
        if idempotency_key in self._executed_actions:
            self._executed_actions[idempotency_key]["status"] = status
            self._executed_actions[idempotency_key]["completed_at"] = time.time()

    def check_duplicate_or_uncertain(self, idempotency_key: str, window_seconds: float = 300.0) -> DuplicateCheckResult:
        """Prevents duplicate execution of identical actions within a time window,
        especially when an earlier attempt may have already executed or timed out.
        """
        if idempotency_key not in self._executed_actions:
            return DuplicateCheckResult(False, None, None)

        record = self._executed_actions[idempotency_key]
        elapsed = time.time() - record["timestamp"]
        if elapsed > window_seconds:
            return DuplicateCheckResult(False, None, None)

        status = record.get("status")
        if status == "completed":
            msg = f"Duplicate action prevented: this identical {record['command']} was already executed successfully {int(elapsed)}s ago."
            return DuplicateCheckResult(True, msg, "already_completed")
        if status in ("in_progress", "uncertain"):
            msg = f"Uncertain execution state: a prior {record['command']} attempt is pending or unverified. Cortex will observe state before retrying."
            return DuplicateCheckResult(True, msg, "in_flight")

        return DuplicateCheckResult(False, None, None)
