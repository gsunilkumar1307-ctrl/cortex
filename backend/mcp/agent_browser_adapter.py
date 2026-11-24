"""
Specialized MCP Tool Adapter for Official Vercel Agent Browser (agent-browser).

Provides authoritative BaseTool integration for:
1. Browser navigation (agent_browser_open / browser_navigate).
2. Accessibility tree snapshots & DOM inspection (agent_browser_snapshot).
3. Semantic element clicking (agent_browser_click).
4. Text input & form filling (agent_browser_fill, agent_browser_type).
5. Keyboard actions (agent_browser_press).
6. Page title and URL queries (agent_browser_get_title, agent_browser_get_url).
7. Visual verification screenshots (agent_browser_screenshot).
8. Lifecycle management (agent_browser_close).
9. Multi-turn session context preservation across LangGraph task turns.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("cortex.mcp.agent_browser")

# Shared across adapter instances to ensure consistent session state across LangGraph steps
_SHARED_AGENT_BROWSER_SESSION_STATE: dict[str, dict[str, Any]] = {}


class MCPAgentBrowserToolAdapter(MCPToolAdapter):
    """
    Official Vercel Agent Browser MCP Tool Adapter implementing Cortex's BaseTool contract:
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
        self.session_data = _SHARED_AGENT_BROWSER_SESSION_STATE.setdefault(
            self.server_name,
            {
                "current_url": "",
                "current_title": "",
                "last_snapshot": "",
                "refs": {},
            },
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _extract_references(self, text: str) -> list[dict[str, str]]:
        """Extracts interactive element references (ref=...) from accessibility snapshot."""
        refs: list[dict[str, str]] = []
        for line in text.splitlines():
            line_s = line.strip()
            m_ref = re.search(r'\[ref=([^\]]+)\]', line_s)
            if m_ref:
                ref_id = m_ref.group(1)
                role_match = re.match(r'-\s+([a-zA-Z0-9_\-]+)\s*(?:"([^"]+)")?', line_s)
                role = role_match.group(1) if role_match else "element"
                label = role_match.group(2) if role_match and role_match.group(2) else ""
                refs.append({
                    "ref": f"@{ref_id}" if not ref_id.startswith("@") else ref_id,
                    "raw_ref": ref_id,
                    "role": role,
                    "label": label,
                    "raw": line_s,
                })
        return refs

    def _format_selector(self, target: str) -> str:
        """Normalizes ref or selector for agent-browser."""
        target = target.strip()
        if re.match(r'^e\d+$', target):
            return f"@{target}"
        return target

    def _extract_structured_data(self, result: Any) -> dict[str, Any]:
        """Extracts normalized structured data dictionary from MCPToolResult."""
        if not result:
            return {}
        raw = getattr(result, "raw_response", None)
        if isinstance(raw, dict):
            structured = raw.get("structuredContent")
            if isinstance(structured, dict):
                resp = structured.get("response")
                if isinstance(resp, dict):
                    data = resp.get("data")
                    if isinstance(data, dict):
                        return data
                    return resp
                return structured
            return raw
        # Fallback: check if text content is formatted JSON
        if hasattr(result, "get_text_content"):
            text = result.get_text_content().strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        data = parsed.get("data")
                        return data if isinstance(data, dict) else parsed
                except Exception:
                    pass
        return {}

    # ── Execution ────────────────────────────────────────────────────────────

    def execute(
        self,
        inputs: dict[str, Any],
        context: TaskContext | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        step_id = inputs.get("step_id", f"mcp-ab-step-{self.name}")

        tool_to_call = self.original_tool_name

        # If invoked via a generic alias or browser_tool, map to Agent Browser tool
        if tool_to_call in ("browser_tool", "mcp_browser_navigate", "browser_navigate", "open_url"):
            tool_to_call = "agent_browser_open"
        elif tool_to_call in ("mcp_browser_snapshot", "browser_snapshot", "browser_scrape"):
            tool_to_call = "agent_browser_snapshot"
        elif tool_to_call in ("mcp_browser_click", "browser_click"):
            tool_to_call = "agent_browser_click"
        elif tool_to_call in ("mcp_browser_type", "browser_type", "browser_fill_form"):
            tool_to_call = "agent_browser_fill"
        elif tool_to_call in ("mcp_browser_close", "browser_close"):
            tool_to_call = "agent_browser_close"

        call_args = self._extract_call_arguments(inputs)

        # ── 1. Open / Navigate (agent_browser_open) ──────────────────────────
        if tool_to_call == "agent_browser_open":
            raw_url = str(call_args.get("url") or inputs.get("url") or inputs.get("params", {}).get("url", "")).strip()
            if not raw_url and inputs.get("target"):
                raw_url = str(inputs.get("target")).strip()

            if not raw_url:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing 'url' parameter for Agent Browser navigation.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            if not (raw_url.startswith("http://") or raw_url.startswith("https://")):
                raw_url = f"https://{raw_url}"

            # Security Policy Validation
            is_valid, canonical_url, sec_err = self.policy.validate_navigation_url(raw_url)
            if not is_valid:
                error_type = getattr(sec_err, "error_type", "SecurityViolation")
                if not error_type:
                    error_type = "SecurityViolation"

                if error_type == "DNSResolutionError":
                    msg = f"Browser navigation failed: {sec_err}"
                elif error_type == "NetworkError":
                    msg = f"Browser network error: {sec_err}"
                elif error_type == "ValidationError":
                    msg = f"Invalid navigation URL: {sec_err}"
                else:
                    msg = f"Browser navigation blocked: {sec_err}"

                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=msg,
                    data={"requested_url": raw_url, "error": str(sec_err)},
                    error=error_type,
                    duration_ms=(time.time() - start_time) * 1000,
                )

            timeout = float(inputs.get("timeout", 60.0))
            try:
                mcp_res: MCPToolResult = self.manager.call_tool(
                    self.server_name,
                    "agent_browser_open",
                    {"url": canonical_url},
                    timeout=timeout,
                )
                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    err_msg = mcp_res.get_text_content() or "Agent Browser navigation failed."
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=err_msg,
                        data={"url": canonical_url},
                        error="NavigationError",
                        duration_ms=duration_ms,
                    )

                # Fetch page title
                page_title = ""
                try:
                    title_res = self.manager.call_tool(
                        self.server_name,
                        "agent_browser_get_title",
                        {},
                        timeout=10.0,
                    )
                    if not title_res.is_error:
                        page_title = title_res.get_text_content().strip()
                except Exception:
                    pass

                # If title was in structured response or text
                if not page_title:
                    raw_text = mcp_res.get_text_content().strip()
                    if raw_text and not raw_text.startswith("{"):
                        page_title = raw_text

                self.session_data["current_url"] = canonical_url
                self.session_data["current_title"] = page_title

                # Automatically obtain snapshot after navigation
                snap_text = ""
                elements = []
                try:
                    snap_res = self.manager.call_tool(
                        self.server_name,
                        "agent_browser_snapshot",
                        {},
                        timeout=15.0,
                    )
                    if not snap_res.is_error:
                        snap_text = snap_res.get_text_content()
                        self.session_data["last_snapshot"] = snap_text
                        elements = self._extract_references(snap_text)
                except Exception:
                    pass

                # Persist in context
                if context is not None:
                    meta = getattr(context, "metadata", None)
                    if isinstance(meta, dict):
                        meta["browser_session"] = dict(self.session_data)
                        meta.setdefault("history", []).append(canonical_url)

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Successfully navigated to {canonical_url} using Agent Browser (Title: '{page_title}').",
                    data={
                        "url": canonical_url,
                        "title": page_title,
                        "snapshot": snap_text,
                        "elements_count": len(elements),
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Agent Browser navigation error for {canonical_url}: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 2. Snapshot (agent_browser_snapshot) ─────────────────────────────
        elif tool_to_call == "agent_browser_snapshot":
            timeout = float(inputs.get("timeout", 30.0))
            try:
                mcp_res = self.manager.call_tool(
                    self.server_name,
                    "agent_browser_snapshot",
                    {},
                    timeout=timeout,
                )
                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or "Agent Browser snapshot failed.",
                        error="SnapshotError",
                        duration_ms=duration_ms,
                    )

                text = mcp_res.get_text_content()
                elements = self._extract_references(text)
                self.session_data["last_snapshot"] = text

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Agent Browser snapshot captured ({len(elements)} elements discovered).",
                    data={
                        "url": self.session_data.get("current_url", ""),
                        "title": self.session_data.get("current_title", ""),
                        "snapshot": text,
                        "elements": elements,
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Agent Browser snapshot error: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 3. Click (agent_browser_click) ───────────────────────────────────
        elif tool_to_call == "agent_browser_click":
            target = call_args.get("selector") or call_args.get("target") or inputs.get("target") or inputs.get("selector") or ""
            target_str = str(target).strip()

            # Dynamic Element Resolution via PageInspector / Snapshot if semantic target given
            if not target_str.startswith("@") and not target_str.startswith("#") and not target_str.startswith("."):
                snap_text = self.session_data.get("last_snapshot", "")
                if not snap_text:
                    try:
                        snap_res = self.manager.call_tool(self.server_name, "agent_browser_snapshot", {}, timeout=10.0)
                        if not snap_res.is_error:
                            snap_text = snap_res.get_text_content()
                            self.session_data["last_snapshot"] = snap_text
                    except Exception:
                        pass

                if snap_text:
                    try:
                        from backend.mcp.page_inspector import PageInspector
                        snap = PageInspector.parse(snap_text, current_url=self.session_data.get("current_url", ""))
                        if target_str.lower() in ("media_result", "first_result", "open_result", "result", "search_result"):
                            q = inputs.get("query") or self.session_data.get("last_typed_query", "")
                            res_links = snap.find_result_links(q) or snap.find_result_links()
                            if res_links:
                                target_str = f"@{res_links[0].ref}" if not res_links[0].ref.startswith("@") else res_links[0].ref
                        else:
                            # Match link or button by name
                            for el in snap.elements:
                                if el.name and target_str.lower() in el.name.lower():
                                    target_str = f"@{el.ref}" if not el.ref.startswith("@") else el.ref
                                    break
                    except Exception:
                        pass

            selector = self._format_selector(target_str)
            if not selector:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing target selector for Agent Browser click.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Consequential check
            is_consequential, reason = self.policy.is_action_consequential("click", {"target": selector})
            has_approval = bool(inputs.get("approved") or inputs.get("approval_hash") or inputs.get("user_confirmed"))
            if is_consequential and not has_approval:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Consequential action requires explicit approval: {reason}",
                    data={"target": selector, "reason": reason, "requires_approval": True},
                    error="ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            timeout = float(inputs.get("timeout", 20.0))
            try:
                mcp_res = self.manager.call_tool(
                    self.server_name,
                    "agent_browser_click",
                    {"selector": selector},
                    timeout=timeout,
                )
                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or f"Click failed on '{selector}'.",
                        data={"selector": selector},
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )

                # Refresh URL & Title in session state
                try:
                    url_res = self.manager.call_tool(self.server_name, "agent_browser_get_url", {}, timeout=5.0)
                    if not url_res.is_error:
                        self.session_data["current_url"] = url_res.get_text_content().strip()
                    title_res = self.manager.call_tool(self.server_name, "agent_browser_get_title", {}, timeout=5.0)
                    if not title_res.is_error:
                        self.session_data["current_title"] = title_res.get_text_content().strip()
                except Exception:
                    pass

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Successfully clicked '{selector}' via Agent Browser.",
                    data={
                        "selector": selector,
                        "current_url": self.session_data.get("current_url"),
                        "current_title": self.session_data.get("current_title"),
                    },
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Agent Browser click failed on '{selector}': {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 4. Fill / Type (agent_browser_fill / agent_browser_type) ─────────
        elif tool_to_call in ("agent_browser_fill", "agent_browser_type"):
            target = call_args.get("selector") or call_args.get("target") or inputs.get("target") or inputs.get("selector") or ""
            target_str = str(target).strip()
            text = str(call_args.get("text") or inputs.get("text") or inputs.get("query") or "")
            submit = bool(call_args.get("submit", inputs.get("submit", False)))

            # If semantic search target given, find searchbox ref via PageInspector
            if str(target_str).lower() in ("search", "searchbox", "search_box", "search_input", "") or not target_str.startswith("@"):
                snap_text = self.session_data.get("last_snapshot", "")
                if not snap_text:
                    try:
                        snap_res = self.manager.call_tool(self.server_name, "agent_browser_snapshot", {}, timeout=10.0)
                        if not snap_res.is_error:
                            snap_text = snap_res.get_text_content()
                            self.session_data["last_snapshot"] = snap_text
                    except Exception:
                        pass

                if snap_text:
                    try:
                        from backend.mcp.page_inspector import PageInspector
                        snap = PageInspector.parse(snap_text, current_url=self.session_data.get("current_url", ""))
                        search_inputs = snap.find_search_inputs()
                        if search_inputs:
                            best_cand, _ = search_inputs[0]
                            target_str = f"@{best_cand.ref}" if not best_cand.ref.startswith("@") else best_cand.ref
                        else:
                            # Also check for buttons or interactive elements with search in name (e.g. GitHub "Search or jump to")
                            for el in snap.elements:
                                if any(t in (el.name or "").lower() for t in ("search", "type to search")):
                                    target_str = f"@{el.ref}" if not el.ref.startswith("@") else el.ref
                                    break
                            if not target_str.startswith("@") and snap.elements:
                                for el in snap.elements:
                                    if el.role in ("textbox", "searchbox"):
                                        target_str = f"@{el.ref}" if not el.ref.startswith("@") else el.ref
                                        break
                    except Exception:
                        pass

            selector = self._format_selector(target_str)
            if not selector:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message="Missing target selector for Agent Browser input.",
                    error="ValidationError",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # Consequential check
            is_consequential, reason = self.policy.is_action_consequential("type", {"target": selector, "text": text})
            has_approval = bool(inputs.get("approved") or inputs.get("approval_hash") or inputs.get("user_confirmed"))
            if is_consequential and not has_approval:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Consequential form submission requires approval: {reason}",
                    data={"target": selector, "text": text, "requires_approval": True},
                    error="ApprovalRequired",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            timeout = float(inputs.get("timeout", 20.0))
            try:
                # Use fill to clear & set text
                mcp_res = self.manager.call_tool(
                    self.server_name,
                    "agent_browser_fill",
                    {"selector": selector, "text": text},
                    timeout=timeout,
                )
                duration_ms = (time.time() - start_time) * 1000

                if mcp_res.is_error:
                    return ExecutionResult(
                        step_id=step_id,
                        ok=False,
                        message=mcp_res.get_text_content() or f"Input failed on '{selector}'.",
                        data={"selector": selector},
                        error="InteractionError",
                        duration_ms=duration_ms,
                    )

                self.session_data["last_typed_query"] = text

                # Submit if requested
                if submit:
                    try:
                        self.manager.call_tool(
                            self.server_name,
                            "agent_browser_press",
                            {"key": "Enter"},
                            timeout=10.0,
                        )
                        time.sleep(1.0)
                    except Exception:
                        pass

                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Entered text '{text}' into '{selector}' via Agent Browser{' (submitted)' if submit else ''}.",
                    data={"selector": selector, "text": text, "submitted": submit},
                    duration_ms=duration_ms,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Agent Browser input failed on '{selector}': {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 5. Get Title (agent_browser_get_title) ───────────────────────────
        elif tool_to_call == "agent_browser_get_title":
            try:
                mcp_res = self.manager.call_tool(self.server_name, "agent_browser_get_title", {}, timeout=10.0)
                title = mcp_res.get_text_content().strip()
                self.session_data["current_title"] = title
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Page title: '{title}'.",
                    data={"title": title},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Failed to get page title: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 6. Get URL (agent_browser_get_url) ───────────────────────────────
        elif tool_to_call == "agent_browser_get_url":
            try:
                mcp_res = self.manager.call_tool(self.server_name, "agent_browser_get_url", {}, timeout=10.0)
                url = mcp_res.get_text_content().strip()
                self.session_data["current_url"] = url
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Current URL: {url}.",
                    data={"url": url},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Failed to get current URL: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 7. Screenshot (agent_browser_screenshot) ─────────────────────────
        elif tool_to_call == "agent_browser_screenshot":
            try:
                mcp_res = self.manager.call_tool(self.server_name, "agent_browser_screenshot", {}, timeout=15.0)
                path = mcp_res.get_text_content().strip()
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message=f"Screenshot captured: {path}.",
                    data={"screenshot_path": path},
                    duration_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Screenshot failed: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── 8. Close (agent_browser_close) ───────────────────────────────────
        elif tool_to_call == "agent_browser_close":
            try:
                self.manager.call_tool(self.server_name, "agent_browser_close", {}, timeout=10.0)
                self.session_data.clear()
                return ExecutionResult(
                    step_id=step_id,
                    ok=True,
                    message="Agent Browser session closed.",
                    duration_ms=(time.time() - start_time) * 1000,
                )
            except Exception as e:
                return ExecutionResult(
                    step_id=step_id,
                    ok=False,
                    message=f"Failed to close Agent Browser: {e}",
                    error=type(e).__name__,
                    duration_ms=(time.time() - start_time) * 1000,
                )

        # ── Generic Passthrough for all other agent_browser_* tools ──────────
        try:
            mcp_res = self.manager.call_tool(
                self.server_name,
                tool_to_call,
                call_args,
                timeout=float(inputs.get("timeout", 30.0)),
            )
            duration_ms = (time.time() - start_time) * 1000
            structured_data = self._extract_structured_data(mcp_res)
            return ExecutionResult(
                step_id=step_id,
                ok=not mcp_res.is_error,
                message=mcp_res.get_text_content(),
                data=structured_data,
                error="BrowserError" if mcp_res.is_error else None,
                duration_ms=duration_ms,
            )
        except Exception as e:
            return ExecutionResult(
                step_id=step_id,
                ok=False,
                message=f"Agent Browser call failed for '{tool_to_call}': {e}",
                error=type(e).__name__,
                duration_ms=(time.time() - start_time) * 1000,
            )

    def observe(self, inputs: dict[str, Any], execution_result: ExecutionResult) -> Observation:
        url = self.session_data.get("current_url", "")
        title = self.session_data.get("current_title", "")
        return Observation(
            target=f"agent_browser:{url or 'session'}",
            state_data={
                "url": url,
                "title": title,
                "ok": execution_result.ok,
            },
            raw_output=execution_result.message,
            evidence_type="browser_page_state",
        )

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
                evidence=f"Agent Browser action failed: {execution_result.error or execution_result.message}",
                error=execution_result.error,
            )
        return VerificationResult(
            verified=True,
            confidence=0.98,
            evidence=f"Agent Browser verified: {execution_result.message}",
        )

    def recover(
        self,
        inputs: dict[str, Any],
        error: ExecutionError,
        attempt: int = 1,
    ) -> dict[str, Any]:
        return {
            "can_retry": attempt < 2,
            "strategy": "retry" if attempt < 2 else "escalate",
            "message": f"Agent Browser execution error: {error.message}.",
        }
