from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request

try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False


def _check_weather(query: str) -> list[dict[str, str]] | None:
    """If query is about weather, fetch live weather from wttr.in."""
    q_lower = query.lower()
    if any(w in q_lower for w in ("weather", "temperature", "forecast", "rain in", "how hot is", "how cold is")):
        # Extract location
        loc = re.sub(r"\b(what is the|what's the|tell me the|check|weather in|weather for|temperature in|forecast for|weather|temperature|forecast|today|tomorrow|now)\b", "", query, flags=re.IGNORECASE).strip(" ?.,")
        if not loc:
            loc = ""
        encoded = urllib.parse.quote(loc)
        url = f"https://wttr.in/{encoded}?format=%l:+%C,+%t+(feels+like+%f),+Humidity+%h,+Wind+%w"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=4) as resp:
                text = resp.read().decode("utf-8", errors="ignore").strip()
                if text and "Unknown location" not in text and not text.startswith("<"):
                    return [{
                        "title": f"Live Weather: {loc or 'Current Location'}",
                        "href": f"https://wttr.in/{encoded}",
                        "body": text
                    }]
        except Exception:
            pass
    return None


def _search_wikipedia(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Fallback search using Wikipedia API."""
    try:
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(query)}&format=json&utf8=1&srlimit={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "CortexDesktopAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("query", {}).get("search", [])
            results = []
            for item in items:
                title = item.get("title", "")
                snippet = re.sub(r"<.*?>", "", item.get("snippet", "")).strip()
                results.append({
                    "title": title,
                    "href": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                    "body": snippet
                })
            return results
    except Exception as e:
        print(f"[cortex] Wikipedia search fallback failed: {e}", file=sys.stderr)
        return []


def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Search the web using a resilient multi-source pipeline:
    1. Direct live weather provider (if query is about weather)
    2. DuckDuckGo Search (text & news)
    3. Wikipedia API fallback
    """
    # 1. Weather check
    weather = _check_weather(query)
    if weather:
        return weather

    # 2. DuckDuckGo check
    if HAS_DDG:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                if results:
                    return [
                        {
                            "title": r.get("title", ""),
                            "href": r.get("href", ""),
                            "body": r.get("body", r.get("snippet", ""))
                        }
                        for r in results
                    ]
                # If text returned empty, try news
                news = list(ddgs.news(query, max_results=max_results))
                if news:
                    return [
                        {
                            "title": r.get("title", ""),
                            "href": r.get("url", r.get("href", "")),
                            "body": r.get("body", "")
                        }
                        for r in news
                    ]
        except Exception as e:
            print(f"[cortex] DuckDuckGo search temporarily rate-limited or failed: {e}", file=sys.stderr)

    # 3. Wikipedia fallback
    wiki = _search_wikipedia(query, max_results=max_results)
    if wiki:
        return wiki

    return []

