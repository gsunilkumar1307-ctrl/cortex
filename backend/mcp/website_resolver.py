"""
Website Resolver for Cortex MCP Browser Automation.

Resolves human-readable website names (e.g. 'Amazon', 'Flipkart', 'GitHub', 'Wikipedia', 'AWS')
to verified official HTTPS URLs using regional localization where appropriate (e.g. India -> amazon.in),
with protection against imitation/phishing domains and integration with PlaywrightSecurityPolicy.
"""

from __future__ import annotations

import locale
import os
import re
from typing import Any
from urllib.parse import urlparse

from backend.mcp.playwright_policy import PlaywrightSecurityPolicy


class WebsiteResolver:
    """Resolves natural language site names to verified official domains."""

    def __init__(self, policy: PlaywrightSecurityPolicy | None = None) -> None:
        self.policy = policy or PlaywrightSecurityPolicy()
        self.region = self._detect_user_region()

    def _detect_user_region(self) -> str:
        """Infers the user's two-letter country code from system locale/environment."""
        env_loc = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
        tz = os.environ.get("TZ", "")
        # macOS system check
        if "IN" in env_loc or "India" in tz or "Calcutta" in tz or "Asia/Kolkata" in tz:
            return "IN"
        if "GB" in env_loc or "UK" in env_loc or "London" in tz:
            return "GB"
        return "IN"  # Default to IN for this environment

    # Regional overrides for localized official web portals
    REGIONAL_OVERRIDES: dict[str, dict[str, str]] = {
        "IN": {
            "amazon": "https://www.amazon.in",
            "google": "https://www.google.co.in",
            "flipkart": "https://www.flipkart.com",
        },
        "GB": {
            "amazon": "https://www.amazon.co.uk",
            "google": "https://www.google.co.uk",
            "flipkart": "https://www.flipkart.com",
        },
        "US": {
            "amazon": "https://www.amazon.com",
            "google": "https://www.google.com",
            "flipkart": "https://www.flipkart.com",
        },
    }

    # Verified canonical services directory
    CANONICAL_SERVICES: dict[str, str] = {
        "amazon": "https://www.amazon.in",
        "flipkart": "https://www.flipkart.com",
        "github": "https://github.com",
        "wikipedia": "https://www.wikipedia.org",
        "aws": "https://aws.amazon.com",
        "aws documentation": "https://docs.aws.amazon.com",
        "aws docs": "https://docs.aws.amazon.com",
        "aws s3": "https://docs.aws.amazon.com/s3/",
        "aws s3 documentation": "https://docs.aws.amazon.com/s3/",
        "youtube": "https://www.youtube.com",
        "reddit": "https://www.reddit.com",
        "google": "https://www.google.com",
        "stackoverflow": "https://stackoverflow.com",
        "stack overflow": "https://stackoverflow.com",
        "netflix": "https://www.netflix.com",
        "linkedin": "https://www.linkedin.com",
        "twitter": "https://x.com",
        "x": "https://x.com",
        "apple": "https://www.apple.com",
        "microsoft": "https://www.microsoft.com",
        "notion": "https://www.notion.so",
        "figma": "https://www.figma.com",
        "canva": "https://www.canva.com",
        "spotify": "https://open.spotify.com",
        "chatgpt": "https://chatgpt.com",
        "openai": "https://www.openai.com",
        "gemini": "https://gemini.google.com",
        "coursera": "https://www.coursera.org",
        "udemy": "https://www.udemy.com",
        "medium": "https://www.medium.com",
        "bbc": "https://www.bbc.com",
        "cnn": "https://www.cnn.com",
        "playwright": "https://playwright.dev",
        "hotstar": "https://www.hotstar.com",
        "disney+ hotstar": "https://www.hotstar.com",
    }

    def resolve_website(self, site_query: str) -> tuple[bool, str, str, str | None]:
        """
        Resolves a site name, domain, or partial query into a canonical official HTTPS URL.
        Returns:
            (success: bool, canonical_url: str, canonical_name: str, error_message: str | None)
        """
        raw = site_query.strip().lower()
        err: str | None = None
        # Clean common prefixes/suffixes
        clean = re.sub(r"^(?:the\s+|official\s+|visit\s+|open\s+|go\s+to\s+)", "", raw).strip()
        clean = re.sub(r"\s+(?:website|site|portal|homepage|home)$", "", clean).strip()

        # 1. If explicit URL given
        if clean.startswith("http://") or clean.startswith("https://"):
            ok, canon_u, err = self.policy.validate_url(clean)
            if not ok:
                return False, clean, clean, err
            parsed = urlparse(canon_u)
            name = parsed.netloc.replace("www.", "").split(".")[0]
            return True, canon_u, name, None

        # 2. If domain format (e.g. 'amazon.in', 'flipkart.com', 'wikipedia.org', 'notion.so')
        if re.search(r"\b[a-zA-Z0-9_\-]+\.(?:com|org|io|net|in|co\.in|co\.uk|gov|edu|dev|so|ai|app)\b", clean):
            target = f"https://{clean}"
            ok, canon_u, err = self.policy.validate_url(target)
            if not ok:
                return False, target, clean, err
            parsed = urlparse(canon_u)
            name = parsed.netloc.replace("www.", "").split(".")[0]
            return True, canon_u, name, None

        # 3. Check regional override first
        reg_map = self.REGIONAL_OVERRIDES.get(self.region, {})
        if clean in reg_map:
            target = reg_map[clean]
            ok, canon_u, err = self.policy.validate_url(target)
            if ok:
                return True, canon_u, clean, None

        # 4. Check canonical services dictionary
        if clean in self.CANONICAL_SERVICES:
            target = self.CANONICAL_SERVICES[clean]
            ok, canon_u, err = self.policy.validate_url(target)
            if ok:
                return True, canon_u, clean, None

        # Check exact token match in canonical services (prevent substring leakage like 'youtube and play believer')
        clean_tokens = set(re.findall(r"\w+", clean))
        # If clean is a single word or recognized multi-word title
        if len(clean_tokens) <= 2:
            for key, s_url in self.CANONICAL_SERVICES.items():
                if key == clean or (len(clean_tokens) == 1 and clean in key.split()):
                    ok, canon_u, err = self.policy.validate_url(s_url)
                    if ok:
                        return True, canon_u, key, None

        # 5. General resolution fallback: construct https://www.<clean>.com
        # Do not resolve common stopwords, search verbs, or multi-word queries to synthetic domains
        stopwords = {
            "search", "for", "and", "the", "a", "an", "in", "on", "at", "to", "of", "with",
            "find", "look", "get", "show", "open", "go", "visit", "browse", "navigate",
            "hub", "macbook", "laptop", "product", "item", "buy", "price", "me", "how", "what", "where"
        }
        clean_tokens = clean.split()
        if len(clean_tokens) <= 2:
            clean_domain_name = re.sub(r"[^a-zA-Z0-9_\-]", "", clean_tokens[0] if clean_tokens else "")
            if clean_domain_name and clean_domain_name not in stopwords:
                general_target = f"https://www.{clean_domain_name}.com"
                ok, canon_u, err = self.policy.validate_url(general_target)
                if ok:
                    return True, canon_u, clean_domain_name, None

        err_detail = f": {err}" if err else ""
        return False, "", clean, f"Could not securely resolve official website for '{site_query}'{err_detail}"

    def get_search_locators(self, site_name: str = "") -> list[str]:
        """
        Returns standard generic HTML search input locators without site-specific hardcoding.
        Dynamic element discovery via PageInspector should be preferred over static selectors.
        """
        return [
            "input[type='search']",
            "input[name='q']",
            "input[name='query']",
            "input[name='search']",
            "input[title*='Search' i]",
            "input[placeholder*='Search' i]",
            "textbox",
            "textarea[name='q']",
        ]
