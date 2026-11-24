from __future__ import annotations

try:
    from backend.core.contracts import RiskLevel, TaskCommand
except ImportError:
    from core.contracts import RiskLevel, TaskCommand

APPROVAL_REQUIRED = {
    TaskCommand.CLIPBOARD_WRITE,
    TaskCommand.SEND_MESSAGE,
    TaskCommand.SEND_WHATSAPP,
    TaskCommand.SHUTDOWN,
    TaskCommand.RESTART,
    TaskCommand.BROWSER_CLICK,   # clicking on web pages can trigger purchases/forms
    TaskCommand.BROWSER_TYPE,    # typing into forms can submit sensitive data
    TaskCommand.SEND_MAIL,       # sending emails directly requires explicit approval
    TaskCommand.MOVE_FILE,       # moving files is consequential and requires approval
}

BLOCKED_PATTERNS = (
    r"\b(?:delete|remove|erase|wipe|destroy|format|purge)\s+(?:system\s+files?|system\s+data|all\s+files?|files?|folders?|directories|directory|disk|drive)\b",
    r"\b(?:delete|remove|erase|wipe|format)\s+[\"']?(?:/System|/etc|/usr|/bin|/sbin|/var|/Library|C:\\Windows)\b",
    r"\b(?:rm\s+-rf|format\s+[c-z]:)\b",
    r"\bsubmit\s+form\b",
    r"\bpayment\b",
    r"\bbuy\s+",
    r"\bpurchase\b",
)

LOW_RISK_COMMANDS = {
    TaskCommand.WRITE_NOTE,
    TaskCommand.CALCULATE,
    TaskCommand.ASK_QUESTION,
    TaskCommand.WEB_SEARCH,
    TaskCommand.FETCH_WEB_CONTENT, # read-only web content retrieval via MCP
    TaskCommand.OPEN_URL,        # just navigating is safe
    TaskCommand.BROWSER_SCRAPE,  # read-only extraction
    TaskCommand.SCREEN_VISION,   # read-only screen reading
    TaskCommand.READ_MAIL,       # read-only inbox access
    TaskCommand.SUMMARIZE_MAIL,  # read-only summarization
    TaskCommand.DRAFT_MAIL,      # drafting is safe (doesn't send)
    TaskCommand.REPLY_MAIL,      # reply drafting is safe (doesn't send)
    TaskCommand.FORWARD_MAIL,    # forward drafting is safe (doesn't send)
    TaskCommand.SEARCH_MAIL,     # read-only email search
    TaskCommand.EMAIL_BRIEFING,  # read-only briefing
    TaskCommand.EXTRACT_ACTIONS, # read-only action extraction
    TaskCommand.SEARCH_FILES,    # read-only file search
    TaskCommand.READ_FILE,       # read-only file read
    TaskCommand.WRITE_FILE,      # file write within safe sandbox
    TaskCommand.CREATE_DIRECTORY,# create directory within safe sandbox
    TaskCommand.LIST_DIRECTORY,  # read-only directory listing
    TaskCommand.GET_FILE_INFO,   # read-only file info
    TaskCommand.APPEND_FILE,     # append file within safe sandbox
    TaskCommand.EDIT_FILE,       # edit file within safe sandbox
    TaskCommand.COPY_FILE,       # copy file within safe sandbox
    TaskCommand.CALENDAR_READ,   # read-only calendar query
    TaskCommand.CALENDAR_CREATE, # create calendar entry
    TaskCommand.PERSONAL_TASK_CREATE, # create personal task
    TaskCommand.PERSONAL_TASK_LIST,   # list personal tasks
    TaskCommand.DAILY_BRIEFING,       # daily overview
    TaskCommand.OBSERVE_SCREEN,       # read-only multi-source desktop perception
    TaskCommand.RESOLVE_UI_ELEMENT,   # read-only UI element localization
}


def classify_command(command: TaskCommand, intent: str) -> tuple[RiskLevel, bool, str | None]:
    text = intent.lower()

    # Milestone 9 Security Hardening: Consequential UI element interactions require explicit approval
    if command in (TaskCommand.CLICK_ELEMENT, TaskCommand.DESKTOP_WORKFLOW):
        consequential_targets = ("delete", "remove", "send", "purchase", "buy", "pay", "format", "empty trash", "submit")
        if any(word in text for word in consequential_targets):
            return RiskLevel.HIGH, True, f"Clicking consequential UI element matching '{text}' requires explicit user approval."

    import re

    # 1. Deletion of files and folders: explain that current filesystem tools do not support deletion
    if (
        re.search(r"\b(?:delete|remove|erase|wipe|destroy|purge)\s+(?:the\s+)?(?:folder|file|directory)\b", text, re.IGNORECASE)
        or re.search(r"\bdelete\s+(?:the\s+)?[a-zA-Z0-9_\-\./]+", text, re.IGNORECASE)
    ):
        return RiskLevel.BLOCKED, False, "File deletion is not currently supported by my filesystem tools. No file was deleted."

    file_deletion_patterns = (
        r"\b(?:delete|remove|erase|wipe|destroy|format|purge)\s+(?:system\s+files?|system\s+data|all\s+files?|files?|folders?|directories|directory|disk|drive)\b",
        r"\b(?:delete|remove|erase|wipe|format)\s+[\"']?(?:/System|/etc|/usr|/bin|/sbin|/var|/Library|C:\\Windows)\b",
        r"\b(?:rm\s+-rf|format\s+[c-z]:)\b",
    )
    for pattern in file_deletion_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return RiskLevel.BLOCKED, False, "This action is outside the Cortex safety boundary and has been blocked."

    # 2. For notes, email drafts, and file writes, do not block conversational terms like 'buy milk'
    if command not in {TaskCommand.WRITE_NOTE, TaskCommand.DRAFT_MAIL, TaskCommand.REPLY_MAIL, TaskCommand.FORWARD_MAIL, TaskCommand.WRITE_FILE, TaskCommand.CREATE_DIRECTORY, TaskCommand.EDIT_FILE, TaskCommand.APPEND_FILE}:
        commerce_blocked_patterns = (
            r"\bsubmit\s+form\b",
            r"\bpayment\b",
            r"\bbuy\s+",
            r"\bpurchase\b",
        )
        for pattern in commerce_blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return RiskLevel.BLOCKED, False, "This action is outside the Cortex safety boundary and has been blocked."

    # 3. SSRF & Prohibited Destination Guard for Web Content Retrieval
    if command == TaskCommand.FETCH_WEB_CONTENT:
        try:
            from backend.mcp.fetch_policy import FetchSecurityPolicy
        except ImportError:
            from mcp.fetch_policy import FetchSecurityPolicy
        fetch_policy = FetchSecurityPolicy()
        urls = re.findall(r"https?://[^\s\"\'<>]+", intent)
        for u in urls:
            valid, _, err = fetch_policy.validate_url(u)
            if not valid:
                return RiskLevel.BLOCKED, False, f"Access blocked by security policy: {err}"

    if command == TaskCommand.UNKNOWN:
        return RiskLevel.LOW, False, None
    if command in LOW_RISK_COMMANDS:
        return RiskLevel.LOW, False, None
    if command in APPROVAL_REQUIRED:
        return RiskLevel.HIGH, True, "This command can affect device state and requires approval."
    return RiskLevel.LOW, False, None


def is_real_email_send_allowed() -> bool:
    """
    Mandatory safety gate: Outbound real email transmission is permitted ONLY when
    os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1".

    All other values (unset, empty string, '0', 'false', 'False', 'no', 'off',
    'true', 'yes', etc.) evaluate to False (BLOCK).
    """
    import os
    return os.getenv("CORTEX_ALLOW_REAL_EMAIL_SEND", "").strip() == "1"


