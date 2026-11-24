"""
Security Policy and Permission Boundary for Playwright MCP Browser Automation.

Enforces:
1. URL Safety & SSRF Guard: Prohibits loopback, private networks, cloud metadata, and forbidden schemes.
2. Consequential Action Classification: Distinguishes safe browsing (navigate, read, search, filter, paginate)
   from consequential actions (orders, payments, form submissions with sensitive data, deletions, messaging).
3. Tool Restrictions: Disables dangerous tools such as browser_run_code_unsafe.
4. Prompt-Injection Isolation: Encloses untrusted page content and snapshot trees.
"""

from __future__ import annotations

import re
from typing import Any

from .fetch_policy import FetchSecurityPolicy

try:
    from backend.core.contracts import RiskLevel
except ImportError:
    from core.contracts import RiskLevel


# Keywords identifying consequential actions requiring explicit confirmation
CONSEQUENTIAL_ACTION_KEYWORDS = [
    "buy",
    "order",
    "place order",
    "purchase",
    "pay",
    "payment",
    "checkout",
    "book now",
    "reserve",
    "confirm booking",
    "delete",
    "remove account",
    "cancel subscription",
    "change password",
    "update email",
    "transfer",
    "publish",
    "post comment",
    "send message",
]

# Prohibited dangerous tools from Playwright MCP
PROHIBITED_PLAYWRIGHT_TOOLS = {
    "browser_run_code_unsafe",
}


class PlaywrightSecurityPolicy:
    """
    Security and authorization policy for Playwright MCP browser interactions.
    """

    def __init__(
        self,
        fetch_policy: FetchSecurityPolicy | None = None,
        require_approval_for_consequential: bool = True,
    ) -> None:
        self.fetch_policy = fetch_policy or FetchSecurityPolicy()
        self.require_approval_for_consequential = require_approval_for_consequential

    def validate_navigation_url(self, url: str) -> tuple[bool, str, str]:
        """
        Validates target URL against SSRF and protocol restrictions.
        Returns:
            (is_valid, canonical_url, error_message)
        """
        return self.fetch_policy.validate_url(url)

    def validate_url(self, url: str) -> tuple[bool, str, str]:
        """Alias for validate_navigation_url."""
        return self.validate_navigation_url(url)

    def is_consequential_action(
        self,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Alias for is_action_consequential."""
        return self.is_action_consequential(action, params)

    def detect_adversarial_content(self, text: str) -> tuple[bool, str]:
        """
        Detects potential prompt injection or adversarial instructions embedded in web content.
        Returns:
            (is_safe, threat_description)
        """
        if not text:
            return True, ""
        lower = text.lower()
        patterns = [
            (r"ignore\s+(?:all\s+)?previous\s+instructions", "Prompt injection: ignore previous instructions"),
            (r"system\s+override", "Prompt injection: system override directive"),
            (r"delete\s+(?:all\s+)?(?:files|desktop|documents)", "Destructive command in untrusted content"),
            (r"disregard\s+(?:all\s+)?prior\s+rules", "Prompt injection: disregard prior rules"),
            (r"you\s+are\s+now\s+in\s+developer\s+mode", "Jailbreak attempt: developer mode"),
        ]
        for pattern, desc in patterns:
            if re.search(pattern, lower):
                return False, desc
        return True, ""

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Checks if the MCP tool is permitted under Cortex security policy."""
        if tool_name in PROHIBITED_PLAYWRIGHT_TOOLS:
            return False
        return True

    def is_action_consequential(
        self,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """
        Determines whether a proposed browser action is consequential and requires explicit user approval.
        Returns:
            (is_consequential, reason)
        """
        params = params or {}
        combined_text = f"{action} {params.get('target', '')} {params.get('element', '')} {params.get('text', '')}".lower()

        # Check for submit buttons or fields that trigger orders, payments, or destructive mutations
        for kw in CONSEQUENTIAL_ACTION_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", combined_text):
                return True, f"Action contains consequential trigger '{kw}'. Explicit user confirmation required."

        # If a form fill contains credit card, password, or financial fields
        fields = params.get("fields", [])
        if isinstance(fields, list):
            for field in fields:
                fname = str(field.get("name", "")).lower()
                ftype = str(field.get("type", "")).lower()
                if any(k in fname for k in ["card", "cvv", "password", "pin", "ssn", "secret"]):
                    return True, f"Form field '{fname}' contains sensitive credentials/financial data. Confirmation required."

        return False, ""

    def sanitize_page_text(self, text: str) -> str:
        """Sanitizes webpage extracted text to prevent prompt injection breakouts."""
        if not text:
            return ""
        return (
            text.replace("</webpage_content>", "&lt;/webpage_content&gt;")
            .replace("</system>", "&lt;/system&gt;")
            .replace("<system>", "&lt;system&gt;")
        )
