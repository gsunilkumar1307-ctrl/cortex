from __future__ import annotations

import html as html_lib
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


def disambiguate_query(query: str) -> str:
    """Expands ambiguous acronyms like 'AI' into 'artificial intelligence' for search queries."""
    q = query.strip()
    # Replace standalone 'AI' or 'ai' with 'artificial intelligence'
    q_expanded = re.sub(r"\bAI\b", "artificial intelligence", q)
    if q_expanded == q:
        q_expanded = re.sub(r"\bai\b", "artificial intelligence", q, flags=re.IGNORECASE)
    return q_expanded


def is_result_relevant(result: dict[str, str], query: str) -> bool:
    """Evaluates whether a search result is semantically relevant to the user query,
    filtering out homonyms and false positives (e.g., aircraft engines for AI queries).
    """
    title = result.get("title", "").lower()
    body = result.get("body", "").lower()
    combined = f"{title} {body}"
    q_lower = query.lower()

    # Exclusions for AI / Artificial Intelligence
    if any(term in q_lower for term in ("ai", "artificial intelligence", "machine learning", "llm")):
        # Reject aircraft engines, aviation, military turbines
        engine_signals = ("turbofan", "aircraft", "ivchenko", "lotarev", "soviet", "engine", "twin-shaft", "thrust")
        if any(sig in combined for sig in engine_signals) and not any(sig in q_lower for sig in ("engine", "turbofan", "aircraft", "jet")):
            return False
        # Reject movie / entertainment if query is about tech/developments
        if any(dev in q_lower for dev in ("development", "update", "latest", "news", "trend", "model", "research")):
            if "film" in combined or "directed by" in combined or "box office" in combined:
                return False

    # Positive concept matching: at least one meaningful keyword must match
    stop_words = {"the", "a", "an", "in", "on", "for", "and", "or", "of", "to", "what", "is", "are", "tell", "me", "about", "latest", "update", "search"}
    keywords = [w for w in re.findall(r"\b[a-z]{2,}\b", q_lower) if w not in stop_words]
    if "ai" in re.findall(r"\b[a-z]{2,}\b", q_lower):
        keywords.extend(["ai", "artificial", "intelligence"])

    if keywords:
        matches = [kw for kw in set(keywords) if kw in combined]
        if not matches:
            return False

    return True


def _search_duckduckgo_html(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Fetches high-quality live search results from DuckDuckGo HTML endpoint without rate-limits."""
    encoded_q = urllib.parse.quote(query)
    url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            page = resp.read().decode("utf-8", errors="ignore")

        results = []
        blocks = re.split(r"<div class=\"[^\"]*result results_links", page)
        for block in blocks[1:]:
            title_m = re.search(r"<a[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.DOTALL)
            snippet_m = re.search(r"<a[^>]*class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>", block, re.DOTALL)
            if title_m:
                raw_href = title_m.group(1)
                raw_title = title_m.group(2)
                parsed = urllib.parse.urlparse(raw_href)
                qs = urllib.parse.parse_qs(parsed.query)
                clean_url = qs.get("uddg", [raw_href])[0]
                clean_title = html_lib.unescape(re.sub(r"<.*?>", "", raw_title).strip())
                snippet = ""
                if snippet_m:
                    snippet = html_lib.unescape(re.sub(r"<.*?>", "", snippet_m.group(1)).strip())
                if clean_title and clean_url.startswith("http"):
                    results.append({"title": clean_title, "href": clean_url, "body": snippet})
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        print(f"[cortex] DuckDuckGo HTML search failed: {e}", file=sys.stderr)
        return []


def search_web(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Search the web using a resilient multi-source pipeline with relevance evaluation:
    1. Direct live weather provider (if query is about weather)
    2. DuckDuckGo Search API (text & news)
    3. DuckDuckGo HTML parser (rate-limit resistant live web search)
    4. Wikipedia API with relevance filtering
    """
    # 1. Weather check
    weather = _check_weather(query)
    if weather:
        return weather

    search_q = re.sub(r"^(?:tell\s+me\s+about|what\s+is|what\s+are|who\s+is|who\s+was|explain|describe)\s+", "", query, flags=re.IGNORECASE).strip() or query
    expanded_q = disambiguate_query(search_q)

    candidate_results: list[dict[str, str]] = []

    # 2. DuckDuckGo API check
    if HAS_DDG:
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(expanded_q, max_results=max_results))
                if results:
                    candidate_results = [
                        {
                            "title": r.get("title", ""),
                            "href": r.get("href", ""),
                            "body": r.get("body", r.get("snippet", ""))
                        }
                        for r in results
                    ]
                if not candidate_results:
                    news = list(ddgs.news(expanded_q, max_results=max_results))
                    if news:
                        candidate_results = [
                            {
                                "title": r.get("title", ""),
                                "href": r.get("url", r.get("href", "")),
                                "body": r.get("body", "")
                            }
                            for r in news
                        ]
        except Exception as e:
            print(f"[cortex] DuckDuckGo API search temporarily rate-limited or failed: {e}", file=sys.stderr)

    # 3. DuckDuckGo HTML endpoint fallback (always available and avoids API 403 blocks)
    if not candidate_results:
        candidate_results = _search_duckduckgo_html(expanded_q, max_results=max_results)
        if not candidate_results and expanded_q != search_q:
            candidate_results = _search_duckduckgo_html(search_q, max_results=max_results)

    # 4. Wikipedia fallback if still empty
    if not candidate_results:
        candidate_results = _search_wikipedia(expanded_q, max_results=max_results)

    # Apply semantic relevance filtering
    filtered_results = [r for r in candidate_results if is_result_relevant(r, query)]

    # If filtering removed everything but candidate_results exists, fallback to candidate_results only if not blatant mismatch
    if not filtered_results and candidate_results:
        # If query was for AI and results are about aircraft engines, do NOT return them
        if any(term in query.lower() for term in ("ai", "artificial intelligence")) and any("engine" in r.get("body", "").lower() for r in candidate_results):
            filtered_results = []
        else:
            filtered_results = candidate_results[:max_results]

    return filtered_results[:max_results]

