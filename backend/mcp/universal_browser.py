"""
Universal Site-Agnostic Playwright Browser Interaction Engine.

Provides general-purpose browser workflows without hardcoding website names,
selectors, or predetermined site-specific behavior:
1. Dynamic Page Inspection & Element Discovery via PageInspector
2. Universal Search Execution across arbitrary websites
3. Media Search & Playback Verification (e.g. YouTube, music, podcasts)
4. Result Navigation & Content Extraction
5. Form Inspection, Field Mapping & Consequential Approval
6. Authentication Wall & CAPTCHA Detection
7. Adaptive Locator Recovery
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

from backend.mcp.page_inspector import PageInspector, PageSnapshot, ParsedElement
from backend.mcp.playwright_policy import PlaywrightSecurityPolicy

logger = logging.getLogger("cortex.mcp.universal_browser")


class UniversalBrowserEngine:
    """
    Coordinates site-agnostic browser workflows using Playwright MCP tools.
    """

    def __init__(self, manager: Any, server_name: str = "playwright", policy: Optional[PlaywrightSecurityPolicy] = None) -> None:
        self.manager = manager
        self.server_name = server_name
        self.policy = policy or PlaywrightSecurityPolicy()

    # ── Fundamental Actions ──────────────────────────────────────────────────

    def call_tool(self, tool_name: str, args: dict[str, Any], timeout: float = 25.0) -> Any:
        """Invokes a Playwright MCP tool through the process manager."""
        return self.manager.call_tool(self.server_name, tool_name, args, timeout=timeout)

    def navigate(self, url: str, timeout: float = 30.0) -> tuple[bool, str, PageSnapshot]:
        """Navigates to URL and returns the parsed PageSnapshot."""
        # Policy URL check
        is_valid, canon_url, err = self.policy.validate_url(url)
        if not is_valid:
            return False, f"Navigation blocked by security policy: {err}", PageSnapshot()

        res = self.call_tool("browser_navigate", {"url": canon_url}, timeout=timeout)
        if res.is_error:
            return False, f"Navigation failed: {res.get_text_content()}", PageSnapshot()

        # Capture snapshot
        snap = self.get_snapshot(timeout=15.0)
        return True, f"Navigated to {canon_url}", snap

    def get_snapshot(self, timeout: float = 20.0) -> PageSnapshot:
        """Captures a fresh accessibility snapshot and parses it."""
        res = self.call_tool("browser_snapshot", {}, timeout=timeout)
        if res.is_error:
            return PageSnapshot()
        text = res.get_text_content()
        return PageInspector.parse(text)

    # ── Universal Search Execution ───────────────────────────────────────────

    def execute_search(self, query: str, timeout: float = 25.0) -> dict[str, Any]:
        """
        Dynamically discovers the search field on the current page, enters query,
        submits, and verifies that search results or query appear on the page.
        """
        snap = self.get_snapshot(timeout=15.0)
        search_inputs = snap.find_search_inputs()

        if not search_inputs:
            # Fallback 1: Try browser_find for "Search"
            find_res = self.call_tool("browser_find", {"text": "Search"}, timeout=5.0)
            if not find_res.is_error:
                snap = self.get_snapshot(timeout=10.0)
                search_inputs = snap.find_search_inputs()

        if not search_inputs:
            return {
                "ok": False,
                "error": "No visible or enabled search field could be discovered on this page.",
                "snapshot": snap,
            }

        # Try discovered candidates in order of relevance score
        type_success = False
        typed_ref = ""
        last_error = ""

        for candidate, score in search_inputs:
            target_ref = candidate.ref
            # Attempt typing with submit=True
            res = self.call_tool("browser_type", {"target": target_ref, "text": query, "submit": True}, timeout=timeout)
            if not res.is_error:
                type_success = True
                typed_ref = target_ref
                break
            else:
                last_error = res.get_text_content()
                # If target ref was rejected, try with accessible selector
                if candidate.name:
                    alt_target = f'textbox "{candidate.name}"'
                    alt_res = self.call_tool("browser_type", {"target": alt_target, "text": query, "submit": True}, timeout=timeout)
                    if not alt_res.is_error:
                        type_success = True
                        typed_ref = alt_target
                        break

        # If Enter didn't submit, check for adjacent search button
        if type_success:
            # Wait for search results
            time.sleep(2.0)
            post_snap = self.get_snapshot(timeout=15.0)

            # Check if query was submitted or if we need to click search button
            if post_snap.url == snap.url and not post_snap.find_result_links(query):
                search_buttons = post_snap.find_search_buttons()
                if search_buttons:
                    self.call_tool("browser_click", {"target": search_buttons[0].ref}, timeout=10.0)
                    time.sleep(2.0)
                    post_snap = self.get_snapshot(timeout=15.0)

            result_links = post_snap.find_result_links(query)
            return {
                "ok": True,
                "query": query,
                "search_ref": typed_ref,
                "url": post_snap.url,
                "title": post_snap.title,
                "results": [{"name": r.name, "url": r.url, "ref": r.ref} for r in result_links[:10]],
                "snapshot": post_snap,
            }

        return {
            "ok": False,
            "error": f"Failed to type query into discovered search field: {last_error}",
            "snapshot": snap,
        }

    # ── Universal Media Playback Workflow ────────────────────────────────────

    def execute_media_playback(self, media_title: str, timeout: float = 35.0) -> dict[str, Any]:
        """
        Executes a complete, verifiable media playback workflow:
        1. Discover search and search for media_title
        2. Inspect search results and identify matching item
        3. Open selected item
        4. Inspect media player controls to verify active playback
        """
        # Step 1: Search for media title
        search_res = self.execute_search(media_title, timeout=timeout)
        if not search_res.get("ok"):
            return {
                "ok": False,
                "step": "search",
                "error": search_res.get("error", "Search failed."),
            }

        post_snap = search_res.get("snapshot") or self.get_snapshot()
        result_links = post_snap.find_result_links(media_title)

        if not result_links:
            # Broaden search to all content links on the results page
            result_links = post_snap.find_result_links()

        if not result_links:
            return {
                "ok": False,
                "step": "select_result",
                "error": f"No matching results found for '{media_title}'.",
                "url": post_snap.url,
            }

        # Step 2: Select the best match
        selected_link = result_links[0]
        selected_title = selected_link.name
        selected_ref = selected_link.ref

        # Step 3: Open the selected result
        click_res = self.call_tool("browser_click", {"target": selected_ref}, timeout=15.0)
        if click_res.is_error:
            # Fallback: if link has url, navigate directly
            if selected_link.url:
                target_url = selected_link.url
                if target_url.startswith("/"):
                    from urllib.parse import urljoin
                    target_url = urljoin(post_snap.url, target_url)
                self.call_tool("browser_navigate", {"url": target_url}, timeout=20.0)
            else:
                return {
                    "ok": False,
                    "step": "open_result",
                    "error": f"Failed to click result '{selected_title}': {click_res.get_text_content()}",
                }

        # Step 4: Wait for player page to load
        time.sleep(3.0)
        player_snap = self.get_snapshot(timeout=15.0)

        # Step 5: Verify playback state through observable controls
        is_playing, playback_evidence = player_snap.is_media_playing()

        # If paused or waiting for play, attempt to click Play button once
        if not is_playing:
            controls = player_snap.find_media_controls()
            if controls["play_buttons"]:
                play_btn = controls["play_buttons"][0]
                self.call_tool("browser_click", {"target": play_btn.ref}, timeout=10.0)
                time.sleep(2.0)
                player_snap = self.get_snapshot(timeout=10.0)
                is_playing, playback_evidence = player_snap.is_media_playing()

        verified_title = player_snap.title or selected_title

        return {
            "ok": True,
            "media_title": media_title,
            "selected_title": verified_title,
            "url": player_snap.url,
            "is_playing": is_playing,
            "playback_evidence": playback_evidence,
            "snapshot": player_snap,
        }

    # ── Universal Form Workflow ──────────────────────────────────────────────

    def execute_form_fill(
        self,
        form_data: dict[str, str],
        submit: bool = False,
        approved: bool = False,
    ) -> dict[str, Any]:
        """
        Inspects form fields on the page, fills textboxes and dropdowns,
        and requires explicit approval before final submission.
        """
        snap = self.get_snapshot(timeout=15.0)
        filled_fields: list[dict[str, Any]] = []

        # Find matching inputs for each key in form_data
        for field_name, value in form_data.items():
            field_name_l = field_name.lower().strip()
            # Match element
            matched_elem = None
            for elem in snap.elements:
                if elem.role in ("textbox", "combobox", "searchbox") and not elem.disabled:
                    elem_n = elem.name.lower()
                    if field_name_l in elem_n or elem_n in field_name_l:
                        matched_elem = elem
                        break

            if matched_elem:
                res = self.call_tool("browser_type", {"target": matched_elem.ref, "text": value, "submit": False}, timeout=15.0)
                if not res.is_error:
                    filled_fields.append({
                        "field": field_name,
                        "ref": matched_elem.ref,
                        "value": value,
                        "verified": True,
                    })

        if submit:
            is_consequential, reason = self.policy.is_action_consequential("submit_form", {"fields": filled_fields})
            if is_consequential and not approved:
                return {
                    "ok": False,
                    "requires_approval": True,
                    "reason": reason or "Form submission requires explicit approval.",
                    "filled_fields": filled_fields,
                }
            # Find submit button
            submit_btns = [e for e in snap.elements if e.role == "button" and any(w in e.name.lower() for w in ("submit", "send", "save", "confirm"))]
            if submit_btns:
                self.call_tool("browser_click", {"target": submit_btns[0].ref}, timeout=15.0)
                time.sleep(2.0)
                post_snap = self.get_snapshot(timeout=10.0)
                return {
                    "ok": True,
                    "submitted": True,
                    "filled_fields": filled_fields,
                    "url": post_snap.url,
                }

        return {
            "ok": True,
            "submitted": False,
            "filled_fields": filled_fields,
            "url": snap.url,
        }

    # ── Universal Auth & Restrictions ────────────────────────────────────────

    def inspect_access_restrictions(self) -> dict[str, Any]:
        """Inspects current page for login walls, MFA, or CAPTCHA."""
        snap = self.get_snapshot(timeout=15.0)
        is_auth, auth_reason = snap.detect_auth_wall()
        is_captcha, captcha_reason = snap.detect_captcha()

        return {
            "is_restricted": is_auth or is_captcha,
            "auth_wall": is_auth,
            "auth_reason": auth_reason,
            "captcha": is_captcha,
            "captcha_reason": captcha_reason,
            "url": snap.url,
            "title": snap.title,
        }
