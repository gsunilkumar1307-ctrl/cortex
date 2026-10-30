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
            account = params.get("account") or params.get("sender_account", "")
            attachments = params.get("attachments") or []
            cc = params.get("cc") or []
            bcc = params.get("bcc") or []
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
                    "account": account,
                    "sender_account": account,
                    "attachments": attachments,
                    "cc": cc,
                    "bcc": bcc,
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

        elif command in (TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP) or (command == TaskCommand.SEND_MESSAGE and params.get("channel") == "whatsapp"):
            rec = params.get("recipient", "")
            phone = params.get("phone", "")
            body = params.get("body", "")
            is_send = (command == TaskCommand.SEND_WHATSAPP or command == TaskCommand.SEND_MESSAGE)
            step = PlanStep(
                action=f"{'Send' if is_send else 'Draft'} WhatsApp message to {rec} ({phone})",
                tool="desktop_tool",
                inputs={
                    "command": command,
                    "params": params,
                    "action": "send_whatsapp" if is_send else "draft_whatsapp",
                    "recipient": rec,
                    "phone": phone,
                    "body": body,
                },
                expected_result=f"WhatsApp message {'dispatched to' if is_send else 'prepared for'} {rec}",
                risk_level=RiskLevel.HIGH if is_send else RiskLevel.LOW,
                approval_required=is_send,
                verification_method="whatsapp_submission_check",
                command=command,
                description=f"Send WhatsApp message to {rec}",
                expected_outcome=f"WhatsApp message sent to {rec}",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.MOVE_FILE:
            src = params.get("source") or params.get("src", "")
            dest = params.get("destination") or params.get("target") or params.get("dest", "")
            step = PlanStep(
                action=f"Move file from {src} to {dest}",
                tool="desktop_tool",
                inputs={"command": command, "params": params, "action": "move_file", "source": src, "destination": dest},
                expected_result=f"File moved to {dest}",
                risk_level=RiskLevel.MEDIUM,
                verification_method="file_exists_check",
                command=command,
                description=f"Move file to {dest}",
                expected_outcome=f"File present at {dest}",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.CREATE_DOCUMENT:
            path_str = params.get("path", "")
            title = params.get("title", "")
            content = params.get("content", "")
            step = PlanStep(
                action=f"Create document {title or path_str}",
                tool="desktop_tool",
                inputs={"command": command, "params": params, "action": "create_document", "path": path_str, "title": title, "content": content},
                expected_result=f"Document created at {path_str}",
                risk_level=RiskLevel.LOW,
                verification_method="file_exists_check",
                command=command,
                description=f"Create document {title or path_str}",
                expected_outcome=f"Document created at {path_str}",
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

        # ── Screen Intelligence & Autonomous Desktop Operator ──
        elif command == TaskCommand.OBSERVE_SCREEN:
            step = PlanStep(
                action=f"Observe desktop screen state",
                tool="desktop_tool",
                inputs={"command": command, "params": params},
                expected_result="Captured multi-source desktop perception context",
                risk_level=RiskLevel.LOW,
                verification_method="screen_context_inspection",
                command=command,
                description=goal or "Observe screen",
                expected_outcome="Screen context observed and normalized",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.CLICK_ELEMENT:
            target = params.get("target") or params.get("target_description") or "target"
            step1 = PlanStep(
                action=f"Resolve UI element '{target}' in active interface",
                tool="desktop_tool",
                inputs={"command": TaskCommand.RESOLVE_UI_ELEMENT, "params": params},
                expected_result=f"Target element '{target}' verified and localized",
                risk_level=RiskLevel.LOW,
                verification_method="target_resolved_check",
                command=TaskCommand.RESOLVE_UI_ELEMENT,
                description=f"Resolve element '{target}'",
                expected_outcome=f"Target '{target}' resolved",
            )
            step2 = PlanStep(
                action=f"Click UI element '{target}'",
                tool="desktop_tool",
                inputs={"command": command, "params": params},
                expected_result=f"Dispatched verified interaction on '{target}'",
                risk_level=RiskLevel.MEDIUM if params.get("is_consequential") else RiskLevel.LOW,
                approval_required=bool(params.get("requires_approval", False)),
                verification_method="screen_state_shift",
                command=command,
                description=f"Click '{target}'",
                expected_outcome=f"Target '{target}' clicked",
            )
            return Plan(goal=goal, steps=[step1, step2])

        elif command == TaskCommand.TYPE_IN_ELEMENT:
            target = params.get("target") or params.get("target_description") or "target"
            text = params.get("text") or params.get("text_to_type") or ""
            step1 = PlanStep(
                action=f"Resolve text target '{target}'",
                tool="desktop_tool",
                inputs={"command": TaskCommand.RESOLVE_UI_ELEMENT, "params": params},
                expected_result=f"Text target '{target}' localized",
                risk_level=RiskLevel.LOW,
                command=TaskCommand.RESOLVE_UI_ELEMENT,
                description=f"Resolve text field '{target}'",
                expected_outcome=f"Text field '{target}' resolved",
            )
            step2 = PlanStep(
                action=f"Type text into '{target}'",
                tool="desktop_tool",
                inputs={"command": command, "params": params},
                expected_result=f"Text typed into '{target}'",
                risk_level=RiskLevel.LOW,
                verification_method="screen_state_shift",
                command=command,
                description=f"Type into '{target}'",
                expected_outcome=f"Text entered in '{target}'",
            )
            return Plan(goal=goal, steps=[step1, step2])

        elif command == TaskCommand.DESKTOP_WORKFLOW:
            workflow_steps = params.get("steps") or []
            plan_steps = []
            for i, st in enumerate(workflow_steps):
                act = st.get("action", "click")
                tgt = st.get("target", f"step_{i}")
                plan_steps.append(
                    PlanStep(
                        action=f"Execute workflow step {i+1}: {act} on '{tgt}'",
                        tool="desktop_tool",
                        inputs={"command": TaskCommand.CLICK_ELEMENT if act == "click" else TaskCommand.TYPE_IN_ELEMENT, "params": st},
                        expected_result=f"Step {i+1} completed on '{tgt}'",
                        risk_level=RiskLevel.MEDIUM if st.get("consequential") else RiskLevel.LOW,
                        approval_required=bool(st.get("requires_approval", False)),
                        verification_method="screen_state_shift",
                        command=TaskCommand.CLICK_ELEMENT if act == "click" else TaskCommand.TYPE_IN_ELEMENT,
                        description=f"Step {i+1}: {act} '{tgt}'",
                        expected_outcome=f"Step {i+1} verified",
                    )
                )
            if not plan_steps:
                plan_steps = [
                    PlanStep(
                        action="Execute desktop workflow",
                        tool="desktop_tool",
                        inputs={"command": command, "params": params},
                        expected_result="Workflow finished",
                        risk_level=RiskLevel.LOW,
                        command=command,
                        description="Desktop workflow",
                        expected_outcome="Workflow finished",
                    )
                ]
            return Plan(goal=goal, steps=plan_steps)

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
