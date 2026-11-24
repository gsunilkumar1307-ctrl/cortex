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

    def _has_tool(self, name: str) -> bool:
        if not self.registry:
            return False
        return bool(self.registry.get(name) or (hasattr(self.registry, "get_instance") and self.registry.get_instance(name)))

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

        elif command in (TaskCommand.READ_MAIL, TaskCommand.SEARCH_MAIL, TaskCommand.SUMMARIZE_MAIL, TaskCommand.EMAIL_BRIEFING):
            action_map = {
                TaskCommand.READ_MAIL: "read_mail",
                TaskCommand.SEARCH_MAIL: "search_mail",
                TaskCommand.SUMMARIZE_MAIL: "email_briefing",
                TaskCommand.EMAIL_BRIEFING: "email_briefing",
            }
            sub_action = action_map.get(command, "read_mail")
            step_inputs = dict(params)
            step_inputs.update({
                "command": command,
                "params": params,
                "action": sub_action,
                "limit": params.get("limit", 5),
                "query": params.get("query", ""),
                "unread_only": params.get("unread_only", False),
            })
            step = PlanStep(
                action=goal or f"Mail action: {sub_action}",
                tool="mail_tool",
                inputs=step_inputs,
                expected_result=f"Completed mail operation: {sub_action}",
                risk_level=RiskLevel.LOW,
                approval_required=False,
                verification_method="mail_result_check",
                command=command,
                description=goal or f"Mail operation: {sub_action}",
                expected_outcome=f"Mail {sub_action} executed and verified",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.WEB_SEARCH:
            query = params.get("query") or goal
            max_results = params.get("max_results", 5)
            step = PlanStep(
                action=f"Search web for '{query}'",
                tool="web_search_tool",
                inputs={"command": command, "params": params, "query": query, "max_results": max_results, **params},
                expected_result=f"Web search results retrieved for '{query}'",
                risk_level=RiskLevel.LOW,
                approval_required=False,
                verification_method="web_search_results_check",
                command=command,
                description=f"Search web for '{query}'",
                expected_outcome=f"Web search results retrieved for '{query}'",
            )
            return Plan(goal=goal, steps=[step])

        elif command in (TaskCommand.SEND_WHATSAPP, TaskCommand.DRAFT_WHATSAPP) or (command == TaskCommand.SEND_MESSAGE and params.get("channel") == "whatsapp"):
            rec = params.get("recipient", "")
            phone = params.get("phone", "")
            body = params.get("formatted_body") or params.get("body", "")
            is_send = (command == TaskCommand.SEND_WHATSAPP or command == TaskCommand.SEND_MESSAGE)
            step_inputs = dict(params)
            step_inputs.update({
                "command": command,
                "params": params,
                "action": "send_message" if is_send else "prepare_draft",
                "recipient": rec,
                "phone": phone,
                "body": body,
                "approval_hash": params.get("approval_hash") or params.get("approved_hash"),
                "approved_hash": params.get("approval_hash") or params.get("approved_hash"),
            })
            step = PlanStep(
                action=f"{'Send' if is_send else 'Draft'} WhatsApp message to {rec} ({phone})",
                tool="whatsapp_adapter",
                inputs=step_inputs,
                expected_result=f"WhatsApp message {'dispatched to' if is_send else 'prepared for'} {rec}",
                risk_level=RiskLevel.HIGH if is_send else RiskLevel.LOW,
                approval_required=is_send,
                verification_method="whatsapp_submission_check",
                command=command,
                description=f"Send WhatsApp message to {rec}",
                expected_outcome=f"WhatsApp message sent to {rec}",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.WRITE_NOTE:
            title = params.get("title") or "Cortex Note"
            body = params.get("body") or ""
            action_type = params.get("action") or "create_note"
            step = PlanStep(
                action=f"Write note '{title}'" if action_type == "create_note" else f"Notes {action_type} for '{title}'",
                tool="notes_adapter",
                inputs={"command": command, "params": params, "action": action_type, "title": title, "body": body, **params},
                expected_result=f"Note '{title}' updated in Apple Notes",
                risk_level=RiskLevel.LOW,
                verification_method="notes_content_inspection",
                command=command,
                description=goal or f"Note '{title}'",
                expected_outcome=f"Note '{title}' created/verified",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.FETCH_WEB_CONTENT:
            urls = params.get("urls") or ([params["url"]] if params.get("url") else [])
            if not urls:
                urls = re.findall(r"https?://[^\s\"'<>]+", goal)
            raw = params.get("raw", False)
            max_length = params.get("max_length", 10000)

            tool = "mcp_fetch" if self._has_tool("mcp_fetch") else "mcp__fetch__fetch"
            plan_steps = []
            for i, u in enumerate(urls):
                plan_steps.append(
                    PlanStep(
                        action=f"Fetch and extract content from {u}",
                        tool=tool,
                        inputs={"url": u, "raw": raw, "max_length": max_length},
                        expected_result=f"Readable markdown content extracted from {u}",
                        risk_level=RiskLevel.LOW,
                        verification_method="web_content_retrieval_check",
                        command=command,
                        description=f"Fetch {u}",
                        expected_outcome=f"Content from {u} retrieved and verified",
                    )
                )
            return Plan(goal=goal, steps=plan_steps)

        # ── Phase P3: Playwright MCP-First Browser Automation ────────
        elif command == TaskCommand.OPEN_URL:
            url = params.get("url", "")
            if not url and params.get("target"):
                url = params.get("target")

            nav_tool = (
                "agent_browser_open" if self._has_tool("agent_browser_open") else (
                    "mcp_agent_browser_open" if self._has_tool("mcp_agent_browser_open") else (
                        "mcp_browser_navigate" if self._has_tool("mcp_browser_navigate") else (
                            "mcp__playwright__browser_navigate" if self._has_tool("mcp__playwright__browser_navigate") else "browser_tool"
                        )
                    )
                )
            )
            snap_tool = (
                "agent_browser_snapshot" if self._has_tool("agent_browser_snapshot") else (
                    "mcp_agent_browser_snapshot" if self._has_tool("mcp_agent_browser_snapshot") else (
                        "mcp_browser_snapshot" if self._has_tool("mcp_browser_snapshot") else (
                            "mcp__playwright__browser_snapshot" if self._has_tool("mcp__playwright__browser_snapshot") else "browser_tool"
                        )
                    )
                )
            )
            type_tool = (
                "agent_browser_type" if self._has_tool("agent_browser_type") else (
                    "mcp_agent_browser_type" if self._has_tool("mcp_agent_browser_type") else (
                        "mcp_browser_type" if self._has_tool("mcp_browser_type") else (
                            "mcp__playwright__browser_type" if self._has_tool("mcp__playwright__browser_type") else "browser_tool"
                        )
                    )
                )
            )
            click_tool = (
                "agent_browser_click" if self._has_tool("agent_browser_click") else (
                    "mcp_agent_browser_click" if self._has_tool("mcp_agent_browser_click") else (
                        "mcp_browser_click" if self._has_tool("mcp_browser_click") else (
                            "mcp__playwright__browser_click" if self._has_tool("mcp__playwright__browser_click") else "browser_tool"
                        )
                    )
                )
            )

            query = params.get("query")
            browser_intent = params.get("browser_intent")

            # 1. MEDIA_PLAYBACK: navigate -> search -> snapshot -> click media result -> verify playback
            if query and browser_intent == "MEDIA_PLAYBACK":
                step1 = PlanStep(
                    action=f"Navigate to {url}",
                    tool=nav_tool,
                    inputs={"url": url, "action": "navigate", "site": params.get("site", "")},
                    expected_result=f"Page loaded: {url}",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_navigation_check",
                    command=command,
                    description=f"Open {url}",
                    expected_outcome=f"Navigated to {url}",
                )
                step2 = PlanStep(
                    action=f"Enter search query '{query}' into search field and submit",
                    tool=type_tool,
                    inputs={
                        "action": "type",
                        "target": params.get("search_target") or "search",
                        "text": query,
                        "submit": True,
                        "site": params.get("site", ""),
                    },
                    expected_result=f"Searched for '{query}' on {url}",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_search_submission_check",
                    command=TaskCommand.BROWSER_TYPE,
                    description=f"Search for '{query}'",
                    expected_outcome=f"Search submitted for '{query}'",
                )
                step3 = PlanStep(
                    action=f"Capture search results page snapshot",
                    tool=snap_tool,
                    inputs={"action": "snapshot"},
                    expected_result=f"Accessible page elements captured for search results",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_snapshot_check",
                    command=TaskCommand.BROWSER_SCRAPE,
                    description=f"Snapshot search results",
                    expected_outcome=f"Search results verified",
                )
                step4 = PlanStep(
                    action=f"Select and open media result for '{query}'",
                    tool=click_tool,
                    inputs={
                        "action": "click",
                        "target": "media_result",
                        "query": query,
                    },
                    expected_result=f"Opened media result for '{query}'",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_click_check",
                    command=TaskCommand.BROWSER_CLICK,
                    description=f"Open media result for '{query}'",
                    expected_outcome=f"Media result opened",
                )
                step5 = PlanStep(
                    action=f"Verify media playback state on {url}",
                    tool=snap_tool,
                    inputs={"action": "snapshot", "verify_playback": True},
                    expected_result=f"Playback state verified",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_snapshot_check",
                    command=TaskCommand.BROWSER_SCRAPE,
                    description=f"Verify playback for '{query}'",
                    expected_outcome=f"Observable playback verified",
                )
                return Plan(goal=goal, steps=[step1, step2, step3, step4, step5])

            # 2. WEBSITE_SEARCH: navigate -> type search query -> snapshot results
            if query and browser_intent in ("WEBSITE_SEARCH", None):
                # If URL already contains a direct search query parameter, a specific path (e.g. repo/item path),
                # or direct destination beyond the domain root, navigation directly lands on the target, so snapshot immediately
                import urllib.parse
                parsed_u = urllib.parse.urlparse(url)
                has_search_query = bool(parsed_u.query and any(k in parsed_u.query.lower() for k in ("q=", "query=", "search=")))
                has_specific_path = bool(parsed_u.path and parsed_u.path.strip("/") and parsed_u.path.strip("/") != "")
                if has_search_query or has_specific_path or "search?q=" in url or "/search?" in url:
                    step1 = PlanStep(
                        action=f"Navigate to {url}",
                        tool=nav_tool,
                        inputs={"url": url, "action": "navigate", "site": params.get("site", "")},
                        expected_result=f"Page loaded: {url}",
                        risk_level=RiskLevel.LOW,
                        verification_method="browser_navigation_check",
                        command=command,
                        description=f"Open {url}",
                        expected_outcome=f"Navigated to {url}",
                    )
                    step2 = PlanStep(
                        action=f"Capture search results page snapshot",
                        tool=snap_tool,
                        inputs={"action": "snapshot"},
                        expected_result=f"Accessible page elements captured for search results",
                        risk_level=RiskLevel.LOW,
                        verification_method="browser_snapshot_check",
                        command=TaskCommand.BROWSER_SCRAPE,
                        description=f"Snapshot search results",
                        expected_outcome=f"Search results verified",
                    )
                    return Plan(goal=goal, steps=[step1, step2])

                step1 = PlanStep(
                    action=f"Navigate to {url}",
                    tool=nav_tool,
                    inputs={"url": url, "action": "navigate", "site": params.get("site", "")},
                    expected_result=f"Page loaded: {url}",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_navigation_check",
                    command=command,
                    description=f"Open {url}",
                    expected_outcome=f"Navigated to {url}",
                )
                step2 = PlanStep(
                    action=f"Enter search query '{query}' into search field and submit",
                    tool=type_tool,
                    inputs={
                        "action": "type",
                        "target": params.get("search_target") or "search",
                        "text": query,
                        "submit": True,
                        "site": params.get("site", ""),
                    },
                    expected_result=f"Searched for '{query}' on {url}",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_search_submission_check",
                    command=TaskCommand.BROWSER_TYPE,
                    description=f"Search for '{query}'",
                    expected_outcome=f"Search submitted for '{query}'",
                )
                step3 = PlanStep(
                    action=f"Capture search results page snapshot",
                    tool=snap_tool,
                    inputs={"action": "snapshot"},
                    expected_result=f"Accessible page elements captured for search results",
                    risk_level=RiskLevel.LOW,
                    verification_method="browser_snapshot_check",
                    command=TaskCommand.BROWSER_SCRAPE,
                    description=f"Snapshot search results",
                    expected_outcome=f"Search results verified",
                )
                return Plan(goal=goal, steps=[step1, step2, step3])

            # 2. OPEN_WEBSITE or standard navigation: navigate -> snapshot
            step1 = PlanStep(
                action=f"Navigate to {url}",
                tool=nav_tool,
                inputs={"url": url, "action": "navigate", "site": params.get("site", "")},
                expected_result=f"Page loaded: {url}",
                risk_level=RiskLevel.LOW,
                verification_method="browser_navigation_check",
                command=command,
                description=f"Open {url}",
                expected_outcome=f"Navigated to {url}",
            )
            step2 = PlanStep(
                action=f"Capture page snapshot for {url}",
                tool=snap_tool,
                inputs={"action": "snapshot"},
                expected_result=f"Accessible page elements captured for {url}",
                risk_level=RiskLevel.LOW,
                verification_method="browser_snapshot_check",
                command=command,
                description=f"Snapshot {url}",
                expected_outcome=f"Page content verified",
            )
            return Plan(goal=goal, steps=[step1, step2])

        elif command == TaskCommand.BROWSER_CLICK:
            target = params.get("target") or params.get("selector") or "target"
            tool = (
                "agent_browser_click" if self._has_tool("agent_browser_click") else (
                    "mcp_agent_browser_click" if self._has_tool("mcp_agent_browser_click") else (
                        "mcp_browser_click" if self._has_tool("mcp_browser_click") else (
                            "mcp__playwright__browser_click" if self._has_tool("mcp__playwright__browser_click") else "browser_tool"
                        )
                    )
                )
            )
            step = PlanStep(
                action=f"Click browser element '{target}'",
                tool=tool,
                inputs=dict(params, action="click"),
                expected_result=f"Clicked element '{target}'",
                risk_level=RiskLevel.HIGH if params.get("requires_approval") else RiskLevel.LOW,
                approval_required=bool(params.get("requires_approval")),
                verification_method="browser_click_check",
                command=command,
                description=f"Click '{target}'",
                expected_outcome=f"Element '{target}' clicked",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.BROWSER_TYPE:
            target = params.get("target") or params.get("selector") or "target"
            text = params.get("text", "")
            tool = (
                "agent_browser_type" if self._has_tool("agent_browser_type") else (
                    "mcp_agent_browser_type" if self._has_tool("mcp_agent_browser_type") else (
                        "mcp_browser_type" if self._has_tool("mcp_browser_type") else (
                            "mcp__playwright__browser_type" if self._has_tool("mcp__playwright__browser_type") else "browser_tool"
                        )
                    )
                )
            )
            step = PlanStep(
                action=f"Type '{text}' into '{target}'",
                tool=tool,
                inputs=dict(params, action="type"),
                expected_result=f"Typed text into '{target}'",
                risk_level=RiskLevel.HIGH if params.get("requires_approval") else RiskLevel.LOW,
                approval_required=bool(params.get("requires_approval")),
                verification_method="browser_type_check",
                command=command,
                description=f"Type into '{target}'",
                expected_outcome=f"Text entered into '{target}'",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.BROWSER_SCRAPE:
            tool = (
                "agent_browser_snapshot" if self._has_tool("agent_browser_snapshot") else (
                    "mcp_agent_browser_snapshot" if self._has_tool("mcp_agent_browser_snapshot") else (
                        "mcp_browser_snapshot" if self._has_tool("mcp_browser_snapshot") else (
                            "mcp__playwright__browser_snapshot" if self._has_tool("mcp__playwright__browser_snapshot") else "browser_tool"
                        )
                    )
                )
            )
            step = PlanStep(
                action=f"Scrape browser page content",
                tool=tool,
                inputs=dict(params, action="snapshot"),
                expected_result=f"Page content extracted",
                risk_level=RiskLevel.LOW,
                verification_method="browser_snapshot_check",
                command=command,
                description="Scrape page",
                expected_outcome="Page content extracted",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.CREATE_DIRECTORY:
            path_str = params.get("path") or params.get("directory") or params.get("name", "")
            if self._has_tool("mcp_create_directory"):
                tool = "mcp_create_directory"
                inputs = {"path": path_str}
                v_method = "directory_created_check"
            elif self._has_tool("mcp__filesystem__create_directory"):
                tool = "mcp__filesystem__create_directory"
                inputs = {"path": path_str}
                v_method = "directory_created_check"
            else:
                tool = "desktop_tool"
                inputs = {"command": command, "params": params, "action": "create_directory", "path": path_str}
                v_method = "file_exists_check"

            step = PlanStep(
                action=f"Create directory {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"Directory {path_str} created on filesystem",
                risk_level=RiskLevel.LOW,
                verification_method=v_method,
                command=command,
                description=f"Create directory {path_str}",
                expected_outcome=f"Directory {path_str} verified",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.MOVE_FILE:
            src = params.get("source") or params.get("src", "")
            dest = params.get("destination") or params.get("target") or params.get("dest", "")
            approved_hash = params.get("approval_hash") or params.get("approved_hash")
            if self._has_tool("mcp_move_file"):
                tool = "mcp_move_file"
                inputs = {"source": src, "destination": dest}
                if approved_hash:
                    inputs["approved_hash"] = approved_hash
            elif self._has_tool("mcp__filesystem__move_file"):
                tool = "mcp__filesystem__move_file"
                inputs = {"source": src, "destination": dest}
                if approved_hash:
                    inputs["approved_hash"] = approved_hash
            else:
                tool = "desktop_tool"
                inputs = {"command": command, "params": params, "action": "move_file", "source": src, "destination": dest}

            step = PlanStep(
                action=f"Move file from {src} to {dest}",
                tool=tool,
                inputs=inputs,
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
            path_str = params.get("path") or params.get("filename") or ""
            content = params.get("content", "")
            approved_hash = params.get("approval_hash") or params.get("approved_hash")
            if self._has_tool("mcp_write_file"):
                tool = "mcp_write_file"
                inputs = {"path": path_str, "content": content}
                if approved_hash:
                    inputs["approved_hash"] = approved_hash
                v_method = "content_sha256_match"
            elif self._has_tool("mcp__filesystem__write_file"):
                tool = "mcp__filesystem__write_file"
                inputs = {"path": path_str, "content": content}
                if approved_hash:
                    inputs["approved_hash"] = approved_hash
                v_method = "content_sha256_match"
            else:
                tool = "file_tool"
                inputs = {"action": "write_file", "path": path_str, "content": content}
                v_method = "content_sha256_match"

            step = PlanStep(
                action=f"Write content to {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"File {path_str} created on filesystem",
                risk_level=RiskLevel.LOW if not params.get("requires_approval") else RiskLevel.HIGH,
                approval_required=bool(params.get("requires_approval")),
                verification_method=v_method,
                command=command,
                description=f"Write file {path_str}",
                expected_outcome=f"File {path_str} verified",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.READ_FILE:
            path_str = params.get("path") or params.get("filename") or ""
            if self._has_tool("mcp_read_text_file"):
                tool = "mcp_read_text_file"
                inputs = {"path": path_str}
            elif self._has_tool("mcp_read_file"):
                tool = "mcp_read_file"
                inputs = {"path": path_str}
            elif self._has_tool("mcp__filesystem__read_text_file"):
                tool = "mcp__filesystem__read_text_file"
                inputs = {"path": path_str}
            elif self._has_tool("mcp__filesystem__read_file"):
                tool = "mcp__filesystem__read_file"
                inputs = {"path": path_str}
            else:
                tool = "file_tool"
                inputs = {"action": "read_file", "path": path_str}

            step = PlanStep(
                action=f"Read file {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"Content of {path_str} retrieved",
                risk_level=RiskLevel.LOW,
                verification_method="file_read_verified",
                command=command,
                description=f"Read file {path_str}",
                expected_outcome=f"File {path_str} content returned",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.LIST_DIRECTORY:
            path_str = params.get("path") or params.get("directory") or "."
            if self._has_tool("mcp_list_directory"):
                tool = "mcp_list_directory"
                inputs = {"path": path_str}
            elif self._has_tool("mcp__filesystem__list_directory"):
                tool = "mcp__filesystem__list_directory"
                inputs = {"path": path_str}
            else:
                tool = "file_tool"
                inputs = {"action": "search_files", "directory": path_str, "pattern": "*"}

            step = PlanStep(
                action=f"List directory {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"Contents of {path_str} retrieved",
                risk_level=RiskLevel.LOW,
                verification_method="directory_list_check",
                command=command,
                description=f"List directory {path_str}",
                expected_outcome=f"Directory {path_str} listed",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.GET_FILE_INFO:
            path_str = params.get("path") or params.get("filename") or ""
            if self._has_tool("mcp_get_file_info"):
                tool = "mcp_get_file_info"
                inputs = {"path": path_str}
            elif self._has_tool("mcp__filesystem__get_file_info"):
                tool = "mcp__filesystem__get_file_info"
                inputs = {"path": path_str}
            else:
                tool = "file_tool"
                inputs = {"action": "read_file", "path": path_str}

            step = PlanStep(
                action=f"Get file info for {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"Information for {path_str} retrieved",
                risk_level=RiskLevel.LOW,
                command=command,
                description=f"Get file info for {path_str}",
                expected_outcome=f"File info for {path_str} retrieved",
            )
            return Plan(goal=goal, steps=[step])

        elif command in (TaskCommand.EDIT_FILE, TaskCommand.APPEND_FILE):
            path_str = params.get("path") or params.get("filename") or ""
            content = params.get("content", "")
            if self._has_tool("mcp_edit_file"):
                tool = "mcp_edit_file"
                inputs = dict(params)
            else:
                tool = "file_tool"
                inputs = {"action": "write_file", "path": path_str, "content": content}

            step = PlanStep(
                action=f"Edit file {path_str}",
                tool=tool,
                inputs=inputs,
                expected_result=f"File {path_str} updated",
                risk_level=RiskLevel.LOW,
                command=command,
                description=f"Edit file {path_str}",
                expected_outcome=f"File {path_str} updated",
            )
            return Plan(goal=goal, steps=[step])

        elif command == TaskCommand.SEARCH_FILES:
            step = PlanStep(
                action=f"Search for files matching '{params.get('pattern', '*')}'",
                tool="file_tool",
                inputs={"action": "search_files", **params, "pattern": params.get("pattern", "*"), "directory": params.get("directory", ".")},
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

        elif command in (TaskCommand.OPEN_APP, TaskCommand.CLOSE_APP, TaskCommand.FOCUS_APP):
            app_name = params.get("appName") or params.get("app_name") or params.get("target", "")
            action_label = {
                TaskCommand.OPEN_APP: f"Open application '{app_name}'",
                TaskCommand.CLOSE_APP: f"Close application '{app_name}'",
                TaskCommand.FOCUS_APP: f"Focus application '{app_name}'",
            }.get(command, f"Application action '{app_name}'")
            step_inputs = dict(params)
            step_inputs["command"] = command
            step_inputs["appName"] = app_name
            step = PlanStep(
                action=action_label,
                tool="desktop_tool",
                inputs=step_inputs,
                expected_result=f"Completed {action_label}",
                risk_level=RiskLevel.LOW,
                approval_required=False,
                verification_method="app_state_check",
                command=command,
                description=action_label,
                expected_outcome=f"Application '{app_name}' action verified",
            )
            return Plan(goal=goal, steps=[step])

        # Default single step (SYS-05 repair: route browser tasks to browser tools instead of defaulting to desktop_tool)
        default_tool = "desktop_tool"
        browser_cmds = (TaskCommand.OPEN_URL, TaskCommand.BROWSER_CLICK, TaskCommand.BROWSER_TYPE, TaskCommand.BROWSER_SCRAPE)
        if command in browser_cmds or params.get("url") or any(h in goal.lower() for h in ("http://", "https://", "browse to", "open site")):
            default_tool = (
                "agent_browser_open" if self._has_tool("agent_browser_open") else (
                    "mcp_agent_browser_open" if self._has_tool("mcp_agent_browser_open") else (
                        "mcp_browser_navigate" if self._has_tool("mcp_browser_navigate") else "browser_tool"
                    )
                )
            )

        step = PlanStep(
            action=goal,
            tool=default_tool,
            inputs={"command": command, "params": params},
            expected_result=f"Executed command {command.value}",
            risk_level=RiskLevel.LOW,
            command=command,
            description=goal,
            expected_outcome=f"Action '{goal}' completed",
        )
        return Plan(goal=goal, steps=[step])
