from __future__ import annotations

from typing import Any
try:
    from backend.core.contracts import TaskCommand, RiskLevel, Plan, PlanStep, TaskContext
except ImportError:
    from core.contracts import TaskCommand, RiskLevel, Plan, PlanStep, TaskContext


class AutonomousPlanner:
    """Decomposes high-level natural language goals into verifiable execution plans."""

    def __init__(self, registry=None) -> None:
        self.registry = registry

    def plan(
        self,
        goal: str,
        command: TaskCommand = TaskCommand.UNKNOWN,
        params: dict[str, Any] | None = None,
        context: TaskContext | None = None,
    ) -> Plan:
        params = params or {}

        if command in (TaskCommand.SEND_MAIL, TaskCommand.DRAFT_MAIL):
            rec = params.get("recipient", "")
            rec_email = params.get("recipient_email") or rec
            subj = params.get("subject", "")
            raw_body = params.get("body", "")
            formatted_body = params.get("formatted_body") or raw_body
            step_action = "send_mail" if command == TaskCommand.SEND_MAIL else "draft_mail"
            is_approval = command == TaskCommand.SEND_MAIL
            step = PlanStep(
                action=f"{'Send' if is_approval else 'Draft'} email to {rec} regarding '{subj}'",
                tool="mail_tool",
                inputs={
                    "action": step_action,
                    "recipient": rec,
                    "recipient_email": rec_email,
                    "subject": subj,
                    "body": raw_body,
                    "formatted_body": formatted_body,
                },
                expected_result=f"Email {'delivered to' if is_approval else 'drafted for'} {rec}",
                risk_level=RiskLevel.HIGH if is_approval else RiskLevel.LOW,
                approval_required=is_approval,
                verification_method="sent_mailbox_check" if is_approval else "draft_check",
                command=command,
                description=f"Send email to {rec}",
                expected_outcome=f"Email sent to {rec}",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.WRITE_FILE:
            path_str = params.get("path", "")
            content = params.get("content", "")
            step = PlanStep(
                action=f"Write content to {path_str}",
                tool="file_tool",
                inputs={"action": "write_file", "path": path_str, "content": content},
                expected_result=f"File {path_str} created on filesystem",
                risk_level=RiskLevel.MEDIUM,
                verification_method="content_sha256_match",
                command=command,
                description=f"Write file {path_str}",
                expected_outcome=f"File {path_str} verified",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.READ_FILE:
            path_str = params.get("path", "")
            step = PlanStep(
                action=f"Read file {path_str}",
                tool="file_tool",
                inputs={"action": "read_file", "path": path_str},
                expected_result=f"Content of {path_str} retrieved",
                risk_level=RiskLevel.LOW,
                command=command,
                description=f"Read file {path_str}",
                expected_outcome=f"File {path_str} content returned",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.SEARCH_FILES:
            step = PlanStep(
                action=f"Search for files matching '{params.get('pattern', '*')}'",
                tool="file_tool",
                inputs={"action": "search_files", "pattern": params.get("pattern", "*"), "directory": params.get("directory", ".")},
                expected_result="List of matching file paths returned",
                risk_level=RiskLevel.LOW,
                command=command,
                description="Search files",
                expected_outcome="Matching files found",
            )
            return Plan(goal=goal, steps=[step])

        # Default single step
        step = PlanStep(
            action=goal,
            tool="desktop_tool",
            inputs={"command": command, "params": params},
            expected_result=f"Executed command {command.value}",
            risk_level=RiskLevel.LOW,
            command=command,
            description=goal,
            expected_outcome=f"Action '{goal}' completed",
        )
        return Plan(goal=goal, steps=[step])
