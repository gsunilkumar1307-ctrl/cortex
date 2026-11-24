"""
Universal Page Inspector for Cortex Playwright MCP Browser Automation.

Parses Playwright accessibility snapshots into structured semantic elements,
providing site-agnostic discovery for:
- Search inputs & searchboxes (without hardcoded CSS selectors)
- Buttons (search triggers, submissions, media controls)
- Hyperlinks & search result items
- Form fields (text inputs, dropdowns, checkboxes, radio buttons)
- Media players & playback states (playing, paused, video titles)
- Authentication walls & login prompts
- CAPTCHA & bot detection challenges
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ParsedElement:
    """Represents an interactive element parsed from a Playwright MCP snapshot."""
    ref: str
    role: str
    name: str = ""
    value: str = ""
    url: str = ""
    depth: int = 0
    raw: str = ""
    cursor: str = ""
    disabled: bool = False
    expanded: Optional[bool] = None

    def matches_query(self, query: str) -> bool:
        """Returns True if the element's name, value, or url matches query words."""
        if not query:
            return True
        q_words = [w.lower() for w in re.split(r"\s+", query.strip()) if w]
        text_corpus = f"{self.name} {self.value} {self.url}".lower()
        return all(w in text_corpus for w in q_words)

    def relevance_score(self, target_query: str) -> float:
        """Computes semantic relevance score of the element against target query."""
        if not target_query:
            return 0.5
        q_lower = target_query.lower().strip()
        corpus = f"{self.name} {self.value}".lower().strip()
        if corpus == q_lower:
            return 1.0
        if q_lower in corpus:
            return 0.85
        q_words = set(re.findall(r"\w+", q_lower))
        c_words = set(re.findall(r"\w+", corpus))
        if not q_words or not c_words:
            return 0.0
        overlap = len(q_words & c_words)
        return overlap / len(q_words)


@dataclass
class PageSnapshot:
    """Structured representation of a webpage's live accessibility tree."""
    url: str = ""
    title: str = ""
    elements: list[ParsedElement] = field(default_factory=list)
    raw_snapshot: str = ""

    def find_search_inputs(self) -> list[tuple[ParsedElement, float]]:
        """
        Dynamically discovers and scores search fields on the page without hardcoded site selectors.
        Returns ranked list of (ParsedElement, score) tuples in descending relevance.
        """
        candidates: list[tuple[ParsedElement, float]] = []
        search_terms = ("search", "find", "query", "explore", "lookup", "what are you looking for", "type to search")

        for elem in self.elements:
            if elem.disabled:
                continue

            score = 0.0
            r = elem.role.lower()
            n = elem.name.lower()
            v = elem.value.lower()

            # 1. Primary Signal: Explicit searchbox role
            if r == "searchbox":
                score += 0.95
                if any(t in n for t in search_terms):
                    score += 0.05

            # 2. Strong Signal: Textbox or Combobox with search terminology in name/label
            elif r in ("textbox", "combobox"):
                # Penalize password / username / email inputs
                if any(w in n for w in ("password", "email", "username", "login", "phone", "first name", "last name", "address")):
                    continue

                if any(t in n for t in search_terms):
                    score += 0.85
                    if "search" in n:
                        score += 0.05
                elif any(t in v for t in search_terms):
                    score += 0.70
                elif not n and elem.depth <= 4:
                    # Unlabeled input near the header/top of the page
                    score += 0.40

            # 3. Contextual Signal: Input placed directly inside search landmark or before search button
            if score > 0:
                # Prefer inputs that are not filter-specific (e.g. prefer main search over "Search Processor")
                if any(w in n for w in ("filter", "processor", "brand", "category", "in this page")):
                    score -= 0.20
                candidates.append((elem, score))

        # Sort descending by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates

    def get_primary_search_input(self) -> Optional[ParsedElement]:
        """Returns the highest-scoring search input on the page, or None if not found."""
        candidates = self.find_search_inputs()
        return candidates[0][0] if candidates else None

    def find_search_buttons(self) -> list[ParsedElement]:
        """Finds submit/search buttons associated with search actions."""
        buttons: list[ParsedElement] = []
        for elem in self.elements:
            if elem.role == "button" and not elem.disabled:
                n = elem.name.lower()
                if any(t in n for t in ("search", "find", "go", "submit")):
                    buttons.append(elem)
        return buttons

    def find_form_inputs(self) -> list[ParsedElement]:
        """Discovers form input fields (textboxes, comboboxes, checkboxes, radio buttons)."""
        inputs: list[ParsedElement] = []
        for elem in self.elements:
            if elem.role in ("textbox", "combobox", "checkbox", "radio", "searchbox", "spinbutton") and not elem.disabled:
                inputs.append(elem)
        return inputs

    def find_result_links(self, query: str = "") -> list[ParsedElement]:
        """
        Discovers content / search result hyperlinks on the current page.
        Filters out generic navigation links (e.g., 'Sign In', 'Help', 'Terms', 'Privacy').
        """
        results: list[ParsedElement] = []
        ignored_names = {
            "sign in", "login", "log in", "sign up", "register", "cart",
            "help", "about", "terms", "privacy", "cookie", "cookies",
            "feedback", "contact", "home", "menu", "next", "previous",
            "explore", "more", "settings", "profile", "account",
            "returns & orders", "returns", "orders", "customer service",
            "amazon pay", "todays deals", "new releases", "best sellers",
            "0 items in cart", "skip to main content", "all",
        }

        for elem in self.elements:
            if elem.role != "link" or not elem.name:
                continue

            norm_name = elem.name.strip().lower()
            if norm_name in ignored_names or len(elem.name) < 2:
                continue
            if any(ign in norm_name for ign in ("cart", "returns &", "sign in", "login", "cookie", "skip to")):
                continue

            # Must have reasonable link text and preferably a URL
            if query:
                if elem.relevance_score(query) > 0.2:
                    results.append(elem)
            else:
                results.append(elem)

        if query:
            results.sort(key=lambda x: x.relevance_score(query), reverse=True)
        return results

    def find_buttons(self, target_query: str = "") -> list[ParsedElement]:
        """Returns buttons matching target query."""
        buttons: list[ParsedElement] = []
        for elem in self.elements:
            if elem.role == "button" and not elem.disabled:
                if not target_query or elem.matches_query(target_query):
                    buttons.append(elem)
        return buttons

    def find_media_controls(self) -> dict[str, list[ParsedElement]]:
        """Identifies media elements and playback controls (play, pause, seek, mute)."""
        controls: dict[str, list[ParsedElement]] = {
            "video": [],
            "play_buttons": [],
            "pause_buttons": [],
            "volume": [],
            "other": [],
        }

        for elem in self.elements:
            r = elem.role.lower()
            n = elem.name.lower()

            if r in ("video", "audio") or "video" in n:
                controls["video"].append(elem)
            elif r == "button":
                if any(w in n for w in ("play", "resume", "play (k)")):
                    controls["play_buttons"].append(elem)
                elif any(w in n for w in ("pause", "pause (k)")):
                    controls["pause_buttons"].append(elem)
                elif any(w in n for w in ("mute", "unmute", "volume")):
                    controls["volume"].append(elem)
                elif any(w in n for w in ("seek", "skip", "next video")):
                    controls["other"].append(elem)

        return controls

    def is_media_playing(self) -> tuple[bool, str]:
        """
        Verifies whether media/video is actively playing based on observable controls.
        Evidence: presence of 'Pause' button, media player controls, or active progress.
        """
        controls = self.find_media_controls()
        if controls["pause_buttons"]:
            btn_name = controls["pause_buttons"][0].name or "Pause"
            return True, f"Observable playback verified: '{btn_name}' control is active (media is playing)."
        if controls["video"] and not controls["play_buttons"]:
            return True, "Video element active on page."
        if controls["play_buttons"]:
            return False, "Video is paused or waiting to play (Play button visible)."
        return False, "No observable media playback controls found."

    def detect_auth_wall(self) -> tuple[bool, str]:
        """
        Detects if the page is behind an authentication wall or requires sign-in.
        """
        t_lower = self.title.lower()
        u_lower = self.url.lower()

        if any(w in t_lower for w in ("sign in", "log in", "login", "authentication")):
            return True, f"Authentication wall detected: Page title is '{self.title}'."
        if any(w in u_lower for w in ("/login", "/signin", "/auth", "accounts.google.com")):
            return True, f"Authentication wall detected: URL path indicates login '{self.url}'."

        # Check elements for prominent login forms
        has_pwd = any(e.role == "textbox" and "password" in e.name.lower() for e in self.elements)
        has_login_btn = any(e.role == "button" and e.name.lower() in ("sign in", "log in", "login") for e in self.elements)

        if has_pwd and has_login_btn:
            return True, "Authentication wall detected: Username/Password form present on page."
        return False, ""

    def detect_captcha(self) -> tuple[bool, str]:
        """Detects anti-bot or CAPTCHA challenges."""
        title_lower = (self.title or "").lower()
        url_lower = (self.url or "").lower()
        if any(term in title_lower or term in url_lower for term in (
            "human verification", "verify you are human", "just a moment...", "nocaptcha", "attention required"
        )):
            return True, "Anti-bot challenge / verification screen detected."
        corpus = (self.raw_snapshot or "").lower()
        if any(term in corpus for term in (
            "verify you are human", "please verify you are a human", "cloudflare turnstile", "cf-turnstile", "recaptcha", "g-recaptcha"
        )):
            return True, "Anti-bot challenge / verification screen detected."
        return False, ""


class PageInspector:
    """Parses raw snapshot text from Playwright MCP into a PageSnapshot."""

    @classmethod
    def parse(cls, snapshot_text: str, current_url: str = "", current_title: str = "") -> PageSnapshot:
        """Parses Playwright MCP snapshot text into structured elements."""
        snapshot = PageSnapshot(url=current_url, title=current_title, raw_snapshot=snapshot_text)

        if not snapshot_text:
            return snapshot

        lines = snapshot_text.splitlines()
        elem_stack: list[ParsedElement] = []
        last_link: Optional[ParsedElement] = None

        for line in lines:
            line_s = line.strip()

            # Metadata extraction
            if line_s.startswith("- Page URL:"):
                snapshot.url = line_s.replace("- Page URL:", "").strip()
                continue
            if line_s.startswith("- Page Title:"):
                snapshot.title = line_s.replace("- Page Title:", "").strip()
                continue

            # Child URL attached to link (e.g. '  - /url: https://...')
            if line_s.startswith("- /url:") or line_s.startswith("/url:"):
                u_val = line_s.replace("- /url:", "").replace("/url:", "").strip()
                if last_link:
                    last_link.url = u_val
                continue

            # Check for interactive element with [ref=...]
            m_ref = re.search(r'\[ref=([^\]]+)\]', line)
            if not m_ref:
                continue

            ref_id = m_ref.group(1).strip()
            # Indentation depth
            depth = len(line) - len(line.lstrip(" "))

            # Parse role and accessible name: e.g. "- textbox "Search for products..." [ref=e12]: value"
            # Match role
            role_m = re.search(r'-\s+([a-zA-Z0-9_\-]+)', line)
            role = role_m.group(1).lower() if role_m else "element"

            # Match accessible name in quotes: "Search"
            name = ""
            name_m = re.search(r'-\s+[a-zA-Z0-9_\-]+\s+"([^"]+)"', line)
            if name_m:
                name = name_m.group(1).strip()

            # Match value after colon: e.g. [ref=e12]: typed text
            value = ""
            if ":" in line:
                val_part = line.split(":", 1)[1].strip()
                # If val_part is not another child tag
                if not val_part.startswith("-") and not val_part.startswith("["):
                    value = val_part

            cursor = "pointer" if "[cursor=pointer]" in line else ""
            disabled = "[disabled]" in line

            elem = ParsedElement(
                ref=ref_id,
                role=role,
                name=name,
                value=value,
                depth=depth,
                raw=line_s,
                cursor=cursor,
                disabled=disabled,
            )

            snapshot.elements.append(elem)
            if role == "link":
                last_link = elem
            else:
                last_link = None

        return snapshot
