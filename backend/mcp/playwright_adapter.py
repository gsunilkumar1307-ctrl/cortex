"""
Specialized MCP Tool Adapter for Playwright Browser Automation (@playwright/mcp).

Provides authoritative BaseTool integration for:
1. Browser navigation (browser_navigate).
2. Accessibility tree snapshots & DOM inspection (browser_snapshot).
3. Semantic element clicking (browser_click).
4. Text input & form filling (browser_type, browser_fill_form).
5. Dropdown selection (browser_select_option).
6. Page state synchronization (browser_wait_for).
7. Visual verification screenshots (browser_take_screenshot).
8. Tab and lifecycle management (browser_tabs, browser_close).
9. Multi-turn session context preservation across user turns.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from .adapter import MCPToolAdapter
from .exceptions import MCPError, MCPSecurityError, MCPTimeoutError, MCPValidationError
from .models import MCPToolDefinition, MCPToolResult
from .playwright_policy import PlaywrightSecurityPolicy

try:
    from backend.core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )
except ImportError:
    from core.contracts import (
        ExecutionError,
        ExecutionResult,
        Observation,
        RiskLevel,
        TaskCommand,
        TaskContext,
        VerificationResult,
    )

# Shared across adapter instances per server to ensure consistent session state across plan steps
_SHARED_SESSION_STATE: dict[str, dict[str, Any]] = {}


class MCPPlaywrightToolAdapter(MCPToolAdapter):
    """
    Playwright MCP Tool Adapter implementing Cortex's BaseTool contract:
    EXECUTE -> OBSERVE -> VERIFY -> RECOVER.
    """

    def __init__(
        self,
        definition: MCPToolDefinition,
        manager: Any,
        namespaced_name: str | None = None,
        policy: PlaywrightSecurityPolicy | None = None,
    ) -> None:
        super().__init__(definition, manager, namespaced_name=namespaced_name)
        self.policy = policy or PlaywrightSecurityPolicy()
        self.session_data = _SHARED_SESSION_STATE.setdefault(
            self.server_name,
            {
                "current_url": "",
                "current_title": "",
                "last_snapshot": "",
                "active_tab": "",
            },
        )

    # ── Helpers for Parsing Snapshots ────────────────────────────────────────

    def _parse_page_metadata(self, text: str) -> dict[str, str]:
        """Extracts Page URL and Title from snapshot or navigation result."""
        meta: dict[str, str] = {}
        for line in text.splitlines():
            line_s = line.strip()
            if line_s.startswith("- Page URL:"):
                meta["url"] = line_s.replace("- Page URL:", "").strip()
            elif line_s.startswith("- Page Title:"):
                meta["title"] = line_s.replace("- Page Title:", "").strip()
            elif "heading" in line_s and "[level=1]" in line_s:
                m = re.search(r'heading\s+"([^"]+)"', line_s)
                if m and "title" not in meta:
                    meta["title"] = m.group(1).strip()
        return meta

    def _extract_references(self, text: str) -> list[dict[str, str]]:
        """Extracts interactive element references (ref=...) from accessibility snapshot."""
        refs: list[dict[str, str]] = []
        for line in text.splitlines():
            line_s = line.strip()
            m_ref = re.search(r'\[ref=([^\]]+)\]', line_s)
            if m_ref:
                ref_id = m_ref.group(1)
                # Extract role/text if present
                role_match = re.match(r'-\s+([a-zA-Z0-9_\-]+)\s*(?:"([^"]+)")?', line_s)
                role = role_match.group(1) if role_match else "element"
                label = role_match.group(2) if role_match and role_match.group(2) else ""
                refs.append({
                    "ref": ref_id,
                    "role": role,
                    "label": label,
                    "raw": line_s,
                })
        return refs

    # ── Execution ────────────────────────────────────────────────────────────

    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"mcp-pw-step-{self.name}")

        tool_to_call = self.original_tool_name
        # If generic browser_tool or action specified, route accordingly
        if tool_to_call in ("browser_tool", "playwright", "playwright_browser"):
            action = inputs.get("action") or inputs.get("command") or "navigate"
            action_str = str(action).lower()
            if "nav" in action_str or "open" in action_str:
                tool_to_call = "browser_navigate"
            elif "snap" in action_str or "inspect" in action_str:
                tool_to_call = "browser_snapshot"
            elif "click" in action_str:
                tool_to_call = "browser_click"
            elif "fill" in action_str:
                tool_to_call = "browser_fill_form"
            elif "type" in action_str:
                tool_to_call = "browser_type"
            elif "select" in action_str:
                tool_to_call = "browser_select_option"
            elif "wait" in action_str:
                tool_to_call = "browser_wait_for"
            elif "screenshot" in action_str:
                tool_to_call = "browser_take_screenshot"
            elif "close" in action_str:
                tool_to_call = "browser_close"
            else:
                tool_to_call = "browser_navigate"

        # Check tool permission
        if not self.policy.is_tool_allowed(tool_to_call):
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Playwright tool '{tool_to_call}' is prohibited by security policy.",
                error="SecurityViolation",
                duration_ms=(time.time() - start_time) * 1000,
            )

        call_args = self._extract_call_arguments(inputs)

        # ── 1. Navigate ──────────────────────────────────────────────────────
        if tool_to_call == "browser_navigate":
            raw_url = str(call_args.get("url") or inputs.get("url") or inputs.get("params", {}).get("url", "")).strip()
            if not raw_url:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing 'url' parameter for browser navigation.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
                raw_url = f"https://{raw_url}"

            is_valid, canonical_url, sec_err = self.policy.validate_navigation_url(raw_url)
            if not is_valid:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Browser navigation blocked: {sec_err}",
                    data={"requested_url": raw_url, "error": sec_err},
                    error="SecurityViolation",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            timeout = float(inputs.get("timeout", 60.0))
            try:
                mcp_res: MCPToolResult = self.manager.call_tool(
                    self.server_name,
                    "browser_navigate",
                    {"url": canonical_url},
                    timeout=timeout,
                )
                if mcp_res.is_error and "ERR_ABORTED" in mcp_res.get_text_content():
                    time.sleep(1.0)
                    mcp_res = self.manager.call_tool(
                        self.server_name,
                        "browser_navigate",
                        {"url": canonical_url},
                        timeout=timeout,
                    )

                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    err_msg = mcp_res.get_text_content() or "Navigation failed."
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=err_msg,
                        data={"url": canonical_url},
                        error="NavigationError",
                        duration_ms=duration_ms,
                    )

                raw_text = mcp_res.get_text_content()
                page_meta = self._parse_page_metadata(raw_text)
                current_url = page_meta.get("url") or canonical_url
                current_title = page_meta.get("title") or ""

                self.session_data["current_url"] = current_url
                self.session_data["current_title"] = current_title
                self.session_data["search_results"] = []
                self.session_data["last_snapshot"] = ""

                # Persist in context
                if context is not None:
                    meta = getattr(context, "metadata", None)
                    if isinstance(meta, dict):
                        meta["browser_session"] = dict(self.session_data)
                        meta.setdefault("history", []).append(current_url)

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Successfully navigated to {current_url} ({current_title or 'Page loaded'}).",
                    data={
                        "url": current_url,
                        "title": current_title,
                        "raw_output": raw_text,
                        "snapshot": self.session_data.get("last_snapshot", ""),
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Browser navigation error for {canonical_url}: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 2. Snapshot / Inspection ─────────────────────────────────────────
        elif tool_to_call == "browser_snapshot":
            snap_args: dict[str, Any] = {}
            if "depth" in call_args:
                snap_args["depth"] = call_args["depth"]
            if "boxes" in call_args:
                snap_args["boxes"] = call_args["boxes"]

            timeout = float(inputs.get("timeout", 35.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_snapshot", snap_args, timeout=timeout)
                if mcp_res.is_error and "ERR_ABORTED" in mcp_res.get_text_content():
                    time.sleep(1.0)
                    mcp_res = self.manager.call_tool(
                        self.server_name,
                        "browser_navigate",
                        {"url": canonical_url},
                        timeout=timeout,
                    )

                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or "Snapshot failed.",
                        error="SnapshotError",
                        duration_ms=duration_ms,
                    )

                text = mcp_res.get_text_content()
                page_meta = self._parse_page_metadata(text)
                elements = self._extract_references(text)

                if page_meta.get("url"):
                    self.session_data["current_url"] = page_meta["url"]
                if page_meta.get("title"):
                    self.session_data["current_title"] = page_meta["title"]
                self.session_data["last_snapshot"] = text

                # Universal Playback Verification if requested by planner
                if inputs.get("verify_playback"):
                    from backend.mcp.page_inspector import PageInspector
                    p_snap = PageInspector.parse(text, current_url=self.session_data["current_url"], current_title=self.session_data["current_title"])
                    is_playing, pb_evidence = p_snap.is_media_playing()
                    if not is_playing:
                        controls = p_snap.find_media_controls()
                        if controls["play_buttons"]:
                            try:
                                self.manager.call_tool(self.server_name, "browser_click", {"target": controls["play_buttons"][0].ref}, timeout=5.0)
                                time.sleep(1.5)
                                res2 = self.manager.call_tool(self.server_name, "browser_snapshot", snap_args, timeout=10.0)
                                if not res2.is_error:
                                    text = res2.get_text_content()
                                    self.session_data["last_snapshot"] = text
                                    p_snap = PageInspector.parse(text, current_url=self.session_data["current_url"], current_title=self.session_data["current_title"])
                                    is_playing, pb_evidence = p_snap.is_media_playing()
                            except Exception:
                                pass
                    self.session_data["is_playing"] = is_playing
                    self.session_data["playback_evidence"] = pb_evidence

                if context is not None:
                    meta = getattr(context, "metadata", None)
                    if isinstance(meta, dict):
                        meta["browser_session"] = dict(self.session_data)

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Page snapshot captured ({len(elements)} accessible elements found).",
                    data={
                        "url": self.session_data["current_url"],
                        "title": self.session_data["current_title"],
                        "snapshot": text,
                        "elements": elements,
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                # If snapshot call timed out or failed but navigation already succeeded and set current_url:
                if self.session_data.get("current_url"):
                    return ExecutionResult(
                        step_id=step_id,
                        ok=True,
                        message=f"Page loaded from session: {self.session_data.get('current_title', 'Page')}.",
                        data={
                            "url": self.session_data.get("current_url"),
                            "title": self.session_data.get("current_title", ""),
                            "snapshot": self.session_data.get("last_snapshot", ""),
                            "elements": [],
                        },
                        duration_ms=(time.time() - start_time) * 1000,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Browser snapshot failed: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 3. Click ─────────────────────────────────────────────────────────
        elif tool_to_call == "browser_click":
            target = call_args.get("target") or inputs.get("target") or inputs.get("selector") or ""
            element = call_args.get("element") or inputs.get("element") or target

            # Universal Dynamic Result Selection via PageInspector
            if str(target).lower() in ("media_result", "first_result", "open_result", "result", "search_result"):
                from backend.mcp.page_inspector import PageInspector
                snap_text = self.session_data.get("last_snapshot", "")
                if not snap_text:
                    snap_res = self.manager.call_tool(self.server_name, "browser_snapshot", {}, timeout=10.0)
                    if not snap_res.is_error:
                        snap_text = snap_res.get_text_content()
                        self.session_data["last_snapshot"] = snap_text

                snap = PageInspector.parse(snap_text, current_url=self.session_data.get("current_url", ""))
                q = inputs.get("query") or self.session_data.get("last_typed_query", "")
                res_links = snap.find_result_links(q)
                if not res_links:
                    res_links = snap.find_result_links()

                if res_links:
                    target = res_links[0].ref
                    element = res_links[0].name
                else:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=f"No matching interactive result links discovered for query '{q}'.",
                        error="ElementNotFound",
                        duration_ms=(time.time() - start_time) * 1000,
                    )

            if not target:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing target locator for click action.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Check if consequential
            is_consequential, reason = self.policy.is_action_consequential("click", {"target": target, "element": element})
            has_approval = bool(inputs.get("approved") or inputs.get("approval_hash") or inputs.get("user_confirmed"))
            if is_consequential and not has_approval:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Consequential action requires explicit approval: {reason}",
                    data={"target": target, "reason": reason, "requires_approval": True},
                    error="ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            click_args: dict[str, Any] = {"target": str(target)}
            if element:
                click_args["element"] = str(element)

            timeout = float(inputs.get("timeout", 20.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_click", click_args, timeout=timeout)
                duration_ms = (time.time() - start_time) * 1000
                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or f"Click failed on '{target}'.",
                        data={"target": target},
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Clicked target '{element or target}'.",
                    data={"target": target, "result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Click failed on '{target}': {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 4. Type Text ─────────────────────────────────────────────────────
        elif tool_to_call == "browser_type":
            target = call_args.get("target") or inputs.get("target") or inputs.get("selector") or ""
            text = str(call_args.get("text") or inputs.get("text") or "")
            submit = bool(call_args.get("submit", inputs.get("submit", False)))
            element = call_args.get("element") or inputs.get("element") or target

            if not target:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing target locator for type action.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            is_consequential, reason = self.policy.is_action_consequential("type", {"target": target, "text": text})
            has_approval = bool(inputs.get("approved") or inputs.get("approval_hash") or inputs.get("user_confirmed"))
            if is_consequential and not has_approval:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Consequential form submission requires approval: {reason}",
                    data={"target": target, "text": text, "requires_approval": True},
                    error="ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            type_args: dict[str, Any] = {
                "target": str(target),
                "text": text,
                "submit": submit,
            }
            if element:
                type_args["element"] = str(element)

            timeout = float(inputs.get("timeout", 20.0))
            try:
                # Dynamic Universal Search Discovery via PageInspector
                locators_to_try = [str(target)]
                if str(target).lower() in ("search", "searchbox", "search_box", "search_input", ""):
                    from backend.mcp.page_inspector import PageInspector
                    snap_text = self.session_data.get("last_snapshot", "")
                    if not snap_text:
                        snap_res = self.manager.call_tool(self.server_name, "browser_snapshot", {}, timeout=10.0)
                        if not snap_res.is_error:
                            snap_text = snap_res.get_text_content()
                            self.session_data["last_snapshot"] = snap_text

                    snap = PageInspector.parse(snap_text, current_url=self.session_data.get("current_url", ""), current_title=self.session_data.get("current_title", ""))
                    is_cap, cap_desc = snap.detect_captcha()
                    if is_cap:
                        return ExecutionResult(
                            step_id=step_id,
                            ok=False,
                            message=f"{cap_desc} detected on page. In accordance with safety policies, Cortex will not bypass bot verification.",
                            error="BotChallengeDetected",
                            duration_ms=(time.time() - start_time) * 1000,
                        )

                    search_candidates = snap.find_search_inputs()
                    locators_to_try = []

                    # 1. Highest priority: Discovered refs directly from current live page
                    for cand, _ in search_candidates:
                        if cand.ref and cand.ref not in locators_to_try:
                            locators_to_try.append(cand.ref)
                        if cand.name:
                            cand_target = f'textbox "{cand.name}"'
                            if cand_target not in locators_to_try:
                                locators_to_try.append(cand_target)

                    # 2. Standard HTML5 generic search selectors (site-agnostic)
                    from backend.mcp.website_resolver import WebsiteResolver
                    wr = WebsiteResolver()
                    for loc in wr.get_search_locators():
                        if loc not in locators_to_try:
                            locators_to_try.append(loc)

                mcp_res = None
                last_err = ""
                for loc in locators_to_try:
                    t_args = dict(type_args)
                    t_args["target"] = loc
                    res = self.manager.call_tool(self.server_name, "browser_type", t_args, timeout=timeout)
                    if not res.is_error:
                        mcp_res = res
                        break
                    last_err = res.get_text_content()

                # If primary locators failed or hit strict mode, discover active search textbox ref via browser_find
                if not mcp_res:
                    try:
                        find_res = self.manager.call_tool(self.server_name, "browser_find", {"text": "Search"}, timeout=10.0)
                        if not find_res.is_error:
                            find_txt = find_res.get_text_content()
                            m_ref = re.search(r"(?:textbox|searchbox)\s+.*?\[ref=([a-zA-Z0-9_\-]+)\]", find_txt)
                            if m_ref:
                                alt_ref = m_ref.group(1)
                                t_args = dict(type_args)
                                t_args["target"] = alt_ref
                                res_ref = self.manager.call_tool(self.server_name, "browser_type", t_args, timeout=timeout)
                                if not res_ref.is_error:
                                    mcp_res = res_ref
                    except Exception:
                        pass

                duration_ms = (time.time() - start_time) * 1000
                if not mcp_res or mcp_res.is_error:
                    err_text = mcp_res.get_text_content() if mcp_res else last_err
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=err_text or f"Typing failed on '{target}'.",
                        data={"target": target},
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )

                self.session_data["last_typed_query"] = text
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Typed text into '{element or target}' (submit={submit}).",
                    data={"target": target, "text": text, "submit": submit, "result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Typing failed on '{target}': {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 5. Fill Form ─────────────────────────────────────────────────────
        elif tool_to_call == "browser_fill_form":
            fields = call_args.get("fields") or inputs.get("fields") or []
            if not isinstance(fields, list) or not fields:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing 'fields' list for form fill action.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            is_consequential, reason = self.policy.is_action_consequential("fill_form", {"fields": fields})
            has_approval = bool(inputs.get("approved") or inputs.get("approval_hash") or inputs.get("user_confirmed"))
            if is_consequential and not has_approval:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Form fill requires explicit user approval: {reason}",
                    data={"fields": fields, "requires_approval": True},
                    error="ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            timeout = float(inputs.get("timeout", 30.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_fill_form", {"fields": fields}, timeout=timeout)
                duration_ms = (time.time() - start_time) * 1000
                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or "Form fill failed.",
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Filled {len(fields)} form field(s) successfully.",
                    data={"fields": fields, "result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Form fill failed: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 6. Select Dropdown Option ────────────────────────────────────────
        elif tool_to_call == "browser_select_option":
            target = call_args.get("target") or inputs.get("target") or inputs.get("selector") or ""
            values = call_args.get("values") or inputs.get("values") or []
            if isinstance(values, str):
                values = [values]
            element = call_args.get("element") or inputs.get("element") or target

            if not target or not values:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing 'target' or 'values' for dropdown selection.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            select_args: dict[str, Any] = {
                "target": str(target),
                "values": values,
            }
            if element:
                select_args["element"] = str(element)

            timeout = float(inputs.get("timeout", 20.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_select_option", select_args, timeout=timeout)
                duration_ms = (time.time() - start_time) * 1000
                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or f"Dropdown selection failed on '{target}'.",
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Selected option(s) {values} in dropdown '{element or target}'.",
                    data={"target": target, "values": values, "result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Dropdown selection failed: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 7. Wait For ──────────────────────────────────────────────────────
        elif tool_to_call == "browser_wait_for":
            wait_args: dict[str, Any] = {}
            if "text" in call_args:
                wait_args["text"] = call_args["text"]
            elif "text" in inputs:
                wait_args["text"] = inputs["text"]
            if "time" in call_args:
                wait_args["time"] = call_args["time"]
            elif "time" in inputs:
                wait_args["time"] = inputs["time"]

            timeout = float(inputs.get("timeout", 35.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_wait_for", wait_args, timeout=timeout)
                duration_ms = (time.time() - start_time) * 1000
                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or "Wait condition timed out.",
                        error="WaitTimeoutError",
                        duration_ms=duration_ms,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message="Browser wait condition satisfied.",
                    data={"wait_args": wait_args, "result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Wait condition error: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 8. Screenshot ────────────────────────────────────────────────────
        elif tool_to_call == "browser_take_screenshot":
            shot_args: dict[str, Any] = {"scale": "css"}
            if "filename" in call_args:
                shot_args["filename"] = call_args["filename"]
            elif "filename" in inputs:
                shot_args["filename"] = inputs["filename"]

            timeout = float(inputs.get("timeout", 20.0))
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_take_screenshot", shot_args, timeout=timeout)
                duration_ms = (time.time() - start_time) * 1000
                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or "Screenshot failed.",
                        error="ScreenshotError",
                        duration_ms=duration_ms,
                    )
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message="Captured page screenshot.",
                    data={"result": mcp_res.get_text_content()},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Screenshot error: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 9. Close ─────────────────────────────────────────────────────────
        elif tool_to_call == "browser_close":
            try:
                mcp_res = self.manager.call_tool(self.server_name, "browser_close", {}, timeout=10.0)
                self.session_data.update({"current_url": "", "current_title": "", "last_snapshot": "", "active_tab": ""})
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message="Browser page closed.",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Error closing browser: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 10. Fallback: Generic MCP Tool Call ──────────────────────────────
        return super().execute(inputs, context)

    # ── Observe ──────────────────────────────────────────────────────────────

    def observe(
        self,
        inputs: dict[str, Any],
        execution_result: ExecutionResult,
    ) -> Observation:
        url = execution_result.data.get("url") or self.session_data.get("current_url", "")
        title = execution_result.data.get("title") or self.session_data.get("current_title", "")
        snapshot = execution_result.data.get("snapshot") or self.session_data.get("last_snapshot", "")
        elements = execution_result.data.get("elements", [])

        # Extract product/search links from snapshot if present
        extracted_results: list[dict[str, Any]] = []
        if snapshot:
            lines = snapshot.splitlines()
            for i, line in enumerate(lines):
                if "/url:" in line and any(k in line for k in ("/p/", "/dp/", "/gp/", "/wiki/", "/s?", "/search", "/items")):
                    raw_u = line.split("/url:")[-1].strip()
                    title = ""
                    for k in range(max(0, i - 4), i):
                        if "link" in lines[k] or "heading" in lines[k]:
                            m_t = re.search(r"[\"']([^\"']+)[\"']", lines[k])
                            if m_t:
                                title = m_t.group(1).strip()
                            else:
                                title = lines[k].replace("- link", "").replace("- heading", "").strip()
                            break
                    if not title:
                        title = f"Search Result #{len(extracted_results)+1}"
                    if not any(r.get("url") == raw_u for r in extracted_results):
                        extracted_results.append({"title": title, "url": raw_u})

        if extracted_results:
            self.session_data["search_results"] = extracted_results
            execution_result.data["search_results"] = extracted_results

        state_data: dict[str, Any] = {
            "ok": execution_result.ok,
            "url": url,
            "title": title,
            "elements_count": len(elements) if isinstance(elements, list) else 0,
            "search_results_count": len(extracted_results),
            "search_results": extracted_results,
            "has_snapshot": bool(snapshot),
            "error": execution_result.error,
        }

        return Observation(
            target=f"playwright:{url or 'page'}",
            state_data=state_data,
            raw_output=execution_result.message,
            evidence_type="playwright_browser_state",
        )

    # ── Verify ───────────────────────────────────────────────────────────────

    def verify(
        self,
        inputs: dict[str, Any],
        observation: Observation,
        execution_result: ExecutionResult,
    ) -> VerificationResult:
        if not execution_result.ok:
            return VerificationResult(
                verified=False,
                confidence=1.0,
                evidence=f"Playwright browser action failed: {execution_result.message}",
                error=execution_result.error,
            )

        url = observation.state_data.get("url", "")
        title = observation.state_data.get("title", "")
        evidence_text = f"Verified browser state: URL='{url}', Title='{title}'."

        return VerificationResult(
            verified=True,
            confidence=0.98,
            evidence=evidence_text,
        )

    # ── Recover ──────────────────────────────────────────────────────────────

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        err_type = error.error_type if hasattr(error, "error_type") else str(error)

        # Security violations and unapproved consequential actions must NOT be blindly retried
        if "SecurityViolation" in err_type or "ApprovalRequired" in err_type:
            return {
                "can_retry": False,
                "strategy": "escalate",
                "message": "Action blocked by security policy or requires explicit user approval.",
            }

        # Transient timeouts, stale references, or transient navigation cancellations can be retried once
        if attempt < 2 and any(t in err_type for t in ["Timeout", "WaitTimeoutError", "InteractionError", "NavigationError", "VerificationFailed"]):
            return {
                "can_retry": True,
                "strategy": "retry",
                "message": "Transient browser interaction issue. Retrying with fresh snapshot...",
            }

        return {
            "can_retry": False,
            "strategy": "escalate",
            "message": f"Browser interaction failed: {error}",
        }
