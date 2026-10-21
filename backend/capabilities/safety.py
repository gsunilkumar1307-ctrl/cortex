from __future__ import annotations

try:
    from backend.core.contracts import RiskLevel, TaskCommand
except ImportError:
    from core.contracts import RiskLevel, TaskCommand

APPROVAL_REQUIRED = {
    TaskCommand.CLIPBOARD_WRITE,
    TaskCommand.SEND_MESSAGE,
    TaskCommand.SHUTDOWN,
    TaskCommand.RESTART,
    TaskCommand.BROWSER_CLICK,   # clicking on web pages can trigger purchases/forms
    TaskCommand.BROWSER_TYPE,    # typing into forms can submit sensitive data
    TaskCommand.SEND_MAIL,       # sending emails directly requires explicit approval
}

BLOCKED_TERMS = (
    "delete file",
    "delete folder",
    "submit form",
    "payment",
    "buy ",
    "purchase",
)

LOW_RISK_COMMANDS = {
    TaskCommand.WRITE_NOTE,
    TaskCommand.CALCULATE,
    TaskCommand.ASK_QUESTION,
    TaskCommand.WEB_SEARCH,
    TaskCommand.OPEN_URL,        # just navigating is safe
    TaskCommand.BROWSER_SCRAPE,  # read-only extraction
    TaskCommand.SCREEN_VISION,   # read-only screen reading
    TaskCommand.READ_MAIL,       # read-only inbox access
    TaskCommand.SUMMARIZE_MAIL,  # read-only summarization
    TaskCommand.DRAFT_MAIL,      # drafting is safe (doesn't send)
    TaskCommand.SEARCH_MAIL,     # read-only email search
    TaskCommand.EMAIL_BRIEFING,  # read-only briefing
    TaskCommand.EXTRACT_ACTIONS, # read-only action extraction
    TaskCommand.SEARCH_FILES,    # read-only file search
    TaskCommand.READ_FILE,       # read-only file read
    TaskCommand.WRITE_FILE,      # file write within safe sandbox
    TaskCommand.CALENDAR_READ,   # read-only calendar query
    TaskCommand.CALENDAR_CREATE, # create calendar entry
    TaskCommand.PERSONAL_TASK_CREATE, # create personal task
    TaskCommand.PERSONAL_TASK_LIST,   # list personal tasks
    TaskCommand.DAILY_BRIEFING,       # daily overview
}


def classify_command(command: TaskCommand, intent: str) -> tuple[RiskLevel, bool, str | None]:
    text = intent.lower()
    if command in {TaskCommand.WRITE_NOTE, TaskCommand.DRAFT_MAIL, TaskCommand.WRITE_FILE}:
        content_blocked = ("delete file", "delete folder")
        if any(term in text for term in content_blocked):
            return RiskLevel.BLOCKED, False, "This action is outside the MVP safety boundary."
    else:
        if any(term in text for term in BLOCKED_TERMS):
            return RiskLevel.BLOCKED, False, "This action is outside the MVP safety boundary."
    if command == TaskCommand.UNKNOWN:
        return RiskLevel.LOW, False, None
    if command in LOW_RISK_COMMANDS:
        return RiskLevel.LOW, False, None
    if command in APPROVAL_REQUIRED:
        return RiskLevel.HIGH, True, "This command can affect device state and requires approval."
    return RiskLevel.LOW, False, None

