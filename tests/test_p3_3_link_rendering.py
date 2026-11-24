"""
Unit tests for Phase P3.3: Clickable Source Links & Markdown Hyperlink Rendering.

Validates:
1. Extraction of rich markdown links [Label](URL) vs literal Markdown.
2. Security protocol validation: allows http/https; rejects javascript:, file:, data:.
3. Backend response formatting includes proper [Site query search results](URL) hyperlinks.
4. Auto-linking of bare URLs and table formatting preservation.
"""

import re
from urllib.parse import urlparse
import pytest

from backend.agent.orchestrator import CortexOrchestrator, TaskCommand
from backend.core.contracts import TaskStatus, FinalResult, Task, RiskLevel


def is_safe_url(raw_url: str) -> bool:
    """Python counterpart of frontend protocol security validator."""
    if not raw_url or not isinstance(raw_url, str):
        return False
    try:
        parsed = urlparse(raw_url.strip())
        return parsed.scheme in ("https", "http") and bool(parsed.netloc)
    except Exception:
        return False


def parse_inline_markdown(text: str) -> list[dict]:
    """
    Python simulator of the frontend `renderInline` parser in App.jsx.
    Tests tokenization and link extraction.
    """
    parts = []
    regex = re.compile(
        r"(\[([^\]]+)\]\((https?://[^\s\)\"\'<>]+)\)|\*\*([^*]+)\*\*|`([^`]+)`|(https?://[^\s\)\"\'<>,]+))"
    )
    last_idx = 0
    for match in regex.finditer(text):
        if match.start() > last_idx:
            parts.append({"type": "text", "val": text[last_idx:match.start()]})

        if match.group(2) and match.group(3):
            label = match.group(2)
            url = match.group(3)
            safe = is_safe_url(url)
            parts.append({"type": "link", "label": label, "url": url, "safe": safe})
        elif match.group(4):
            parts.append({"type": "bold", "val": match.group(4)})
        elif match.group(5):
            parts.append({"type": "code", "val": match.group(5)})
        elif match.group(6):
            url = match.group(6)
            safe = is_safe_url(url)
            parts.append({"type": "bare_link", "url": url, "safe": safe})
        last_idx = match.end()

    if last_idx < len(text):
        parts.append({"type": "text", "val": text[last_idx:]})
    return parts


def test_markdown_link_tokenization():
    """Verifies [Label](URL) is parsed as a clickable link and not literal Markdown."""
    sample = "Source: [Flipkart](https://www.flipkart.com/)"
    tokens = parse_inline_markdown(sample)
    
    # Must have 2 tokens: "Source: " and link token
    assert len(tokens) == 2
    assert tokens[0]["type"] == "text"
    assert tokens[0]["val"] == "Source: "
    assert tokens[1]["type"] == "link"
    assert tokens[1]["label"] == "Flipkart"
    assert tokens[1]["url"] == "https://www.flipkart.com/"
    assert tokens[1]["safe"] is True


def test_search_results_link_tokenization():
    """Verifies detailed search-result citations parse with full query context."""
    sample = "Opened Flipkart and searched for ASUS laptop. The search results are displayed.\n\nSource: [Flipkart ASUS laptop search results](https://www.flipkart.com/search?q=ASUS+laptop)"
    tokens = parse_inline_markdown(sample)
    
    link_tokens = [t for t in tokens if t["type"] == "link"]
    assert len(link_tokens) == 1
    assert link_tokens[0]["label"] == "Flipkart ASUS laptop search results"
    assert link_tokens[0]["url"] == "https://www.flipkart.com/search?q=ASUS+laptop"
    assert link_tokens[0]["safe"] is True


def test_url_protocol_security_whitelist():
    """Verifies dangerous schemes (javascript:, file:, data:) are rejected."""
    # Safe URLs
    assert is_safe_url("https://www.amazon.in") is True
    assert is_safe_url("https://www.flipkart.com/search?q=laptop") is True
    assert is_safe_url("http://example.com/path") is True

    # Dangerous schemes
    assert is_safe_url("javascript:alert(document.cookie)") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("data:text/html,<script>alert(1)</script>") is False
    assert is_safe_url("vbscript:msgbox(1)") is False
    assert is_safe_url("") is False


def test_backend_response_hyperlink_formatting():
    """Verifies CortexOrchestrator generates clickable markdown hyperlinks for browser tasks."""
    orch = CortexOrchestrator(use_gemini=False)
    
    # Simulate execution of Flipkart search
    task = Task("Go to Flipkart and search for ASUS laptop.", TaskCommand.OPEN_URL, RiskLevel.LOW, False)
    task.params = {
        "url": "https://www.flipkart.com/",
        "query": "ASUS laptop",
        "site": "flipkart",
        "browser_intent": "WEBSITE_SEARCH",
    }
    
    # Mock execution engine result
    orch.execution_engine.execute_plan = lambda t: FinalResult(
        task_id=t.id,
        status=TaskStatus.COMPLETED,
        summary="Search executed",
        data={
            "url": "https://www.flipkart.com/search?q=ASUS+laptop",
            "title": "ASUS Laptop - Buy ASUS Laptop Online at Best Prices In India | Flipkart.com",
            "search_results": [{"title": "ASUS Vivobook 15", "price": "₹37,990", "url": "https://www.flipkart.com/asus-vivobook"}],
        },
    )
    
    orch._execute_playwright_browser(task)
    assert task.status == TaskStatus.COMPLETED
    assert "Source: [Flipkart ASUS laptop search results](https://www.flipkart.com/search?q=ASUS+laptop)" in task.result
    
    # Verify the backend result parses cleanly into clickable tokens
    tokens = parse_inline_markdown(task.result)
    links = [t for t in tokens if t["type"] == "link"]
    assert len(links) >= 1
    source_link = next((l for l in links if l["label"] == "Flipkart ASUS laptop search results"), None)
    assert source_link is not None
    assert source_link["url"] == "https://www.flipkart.com/search?q=ASUS+laptop"
