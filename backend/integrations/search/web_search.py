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
    """Fallback search using Wikipedia API with full article summary extraction."""
    # Clean query of search/research noise phrases
    clean_q = re.sub(r"\b(?:search\s+for|research|look\s+up|tell\s+me\s+about|what\s+is|who\s+is|explain|in\s+safari|using\s+safari|on\s+safari)\b", "", query, flags=re.IGNORECASE).strip(" ?.,:")
    if not clean_q:
        clean_q = query.strip()

    try:
        # 1. Search for matching page titles
        url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote(clean_q)}&format=json&utf8=1&srlimit={max_results}"
        req = urllib.request.Request(url, headers={"User-Agent": "CortexDesktopAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            items = data.get("query", {}).get("search", [])

        if not items:
            return []

        results = []
        # 2. For the top item, attempt to get the authoritative introductory extract
        for item in items[:2]:
            title = item.get("title", "")
            if not title:
                continue
            encoded_title = urllib.parse.quote(title.replace(" ", "_"))
            summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"
            summary_req = urllib.request.Request(summary_url, headers={"User-Agent": "CortexDesktopAssistant/1.0"})
            extract = ""
            try:
                with urllib.request.urlopen(summary_req, timeout=3) as s_resp:
                    s_data = json.loads(s_resp.read().decode("utf-8"))
                    extract = s_data.get("extract", "").strip()
            except Exception:
                pass

            if not extract:
                # Fall back to cleaned snippet if summary endpoint is unreachable
                extract = re.sub(r"<.*?>", "", item.get("snippet", "")).strip()

            if extract:
                results.append({
                    "title": title,
                    "href": f"https://en.wikipedia.org/wiki/{encoded_title}",
                    "body": f"**{title}**: {extract}"
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

    search_q = re.sub(r"^(?:tell\s+me\s+about|what\s+is|what\s+are|who\s+is|who\s+was|explain|describe)\s+", "", query, flags=re.IGNORECASE).strip() or query

    # 2. DuckDuckGo check
    if HAS_DDG:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(search_q, max_results=max_results))
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
                news = list(ddgs.news(search_q, max_results=max_results))
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
    wiki = _search_wikipedia(search_q, max_results=max_results)
    if wiki:
        return wiki

    return []

