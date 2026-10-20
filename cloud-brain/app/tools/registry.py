from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any
from .base import BaseTool
from .mail_tool import MailTool
from .file_tool import FileTool
from .desktop_tool import DesktopTool
from .browser_tool import BrowserTool
from .search_tool import WebSearchTool


@dataclass
class ToolDefinition:
    name: str
    description: str
    expected_state_desc: str
    parameters: dict[str, Any] | None = None


class ToolRegistry:
    """Unified catalog of all capabilities and universal tools supported by Cortex."""

    def __init__(self, automation: Any = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._instances: dict[str, BaseTool] = {}
        self.automation = automation
        self._register_defaults()
        self._register_universal_tools()

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def register_instance(self, tool_or_name: str | BaseTool, tool: BaseTool | None = None) -> None:
        if isinstance(tool_or_name, str):
            inst = tool or BaseTool(name=tool_or_name, description="", risk_level=RiskLevel.LOW)
            inst.name = tool_or_name
            self._instances[tool_or_name] = inst
        else:
            self._instances[tool_or_name.name] = tool_or_name

    def get_instance(self, name: str) -> BaseTool | None:
        return self._instances.get(name)

    def list_instances(self) -> list[BaseTool]:
        return list(self._instances.values())

    def _register_universal_tools(self) -> None:
        mail_auto = getattr(self.automation, "_get_mail", lambda: None)() if self.automation else None
        self.register_instance(MailTool(mail_automation=mail_auto))
        self.register_instance(FileTool(automation=self.automation))
        self.register_instance(DesktopTool(automation=self.automation))
        self.register_instance(BrowserTool(automation=self.automation))
        self.register_instance(WebSearchTool())

    def update_automation(self, automation: Any) -> None:
        self.automation = automation
        self._register_universal_tools()

    def _register_defaults(self) -> None:
        defaults = [
            ToolDefinition(
                name="open_application",
                description="Launch an application by name (e.g. Safari, Notes, VS Code)",
                expected_state_desc="Target application process is running and focused in foreground",
            ),
            ToolDefinition(
                name="close_application",
                description="Terminate or quit an application by name",
                expected_state_desc="Target application process has terminated cleanly",
            ),
            ToolDefinition(
                name="web_search",
                description="Search the web using DuckDuckGo/Google search API",
                expected_state_desc="Search results received with page titles and text summaries",
            ),
            ToolDefinition(
                name="search_files",
                description="Search directory tree for files matching a pattern",
                expected_state_desc="List of matching file paths returned",
            ),
            ToolDefinition(
                name="read_file",
                description="Read contents of a file inside the allowed user path sandbox",
                expected_state_desc="File content text returned",
            ),
            ToolDefinition(
                name="write_file",
                description="Write or overwrite contents of a file inside the user path sandbox",
                expected_state_desc="File exists on filesystem with expected byte content",
            ),
            ToolDefinition(
                name="search_mail",
                description="Search Apple Mail inbox for messages matching query or sender",
                expected_state_desc="Matching email objects returned with sender, subject, date",
            ),
            ToolDefinition(
                name="email_briefing",
                description="Generate an executive summary of unread and high priority emails",
                expected_state_desc="Structured email briefing text generated",
            ),
            ToolDefinition(
                name="calendar_read",
                description="Read upcoming scheduled calendar events for today or specified date",
                expected_state_desc="List of calendar events with times and titles returned",
            ),
            ToolDefinition(
                name="calendar_create",
                description="Schedule a new calendar event with title, date, and time",
                expected_state_desc="Calendar event confirmed and scheduled",
            ),
            ToolDefinition(
                name="personal_task_create",
                description="Create a personal reminder or todo task item",
                expected_state_desc="Task recorded in personal task store with pending status",
            ),
            ToolDefinition(
                name="personal_task_list",
                description="List all active and pending personal tasks",
                expected_state_desc="List of task dictionaries returned",
            ),
            ToolDefinition(
                name="daily_briefing",
                description="Compile a unified daily briefing of meetings and pending tasks",
                expected_state_desc="Markdown daily briefing generated",
            ),
            ToolDefinition(
                name="calculate_math",
                description="Safely evaluate mathematical expressions (arithmetic, exponents)",
                expected_state_desc="Numerical computation result returned",
            ),
        ]
        for t in defaults:
            self.register(t)
