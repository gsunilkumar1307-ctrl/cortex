from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BrowserResult:
    ok: bool
    message: str
    data: dict[str, Any] | None = None


def _run(coro):
    """Run an async coroutine synchronously."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class BrowserAutomation:
    """Playwright-based browser automation. Launches a real browser window."""

    def __init__(self, headless: bool = False) -> None:
        self.headless = headless  # False = user sees the browser
        self._browser = None
        self._page = None

    # ── Public API (sync wrappers) ────────────────────────────────────────────

    def open_url(self, url: str) -> BrowserResult:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return _run(self._open_url(url))

    def click(self, selector: str, url: str = "") -> BrowserResult:
        return _run(self._click(selector, url))

    def type_text(self, selector: str, text: str, url: str = "") -> BrowserResult:
        return _run(self._type_text(selector, text, url))

    def scrape(self, url: str, selector: str = "body") -> BrowserResult:
        return _run(self._scrape(url, selector))

    def close(self) -> None:
        if self._browser:
            _run(self._close())

    # ── Async implementations ─────────────────────────────────────────────────

    async def _ensure_browser(self):
        from playwright.async_api import async_playwright
        if self._browser is None:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self.headless)
        if self._page is None or self._page.is_closed():
            self._page = await self._browser.new_page()
        return self._page

    async def _open_url(self, url: str) -> BrowserResult:
        try:
            page = await self._ensure_browser()
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            title = await page.title()
            return BrowserResult(True, f"Opened: {title}", {"url": url, "title": title})
        except Exception as e:
            return BrowserResult(False, f"Failed to open {url}: {e}")

    async def _click(self, selector: str, url: str = "") -> BrowserResult:
        try:
            page = await self._ensure_browser()
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.click(selector, timeout=10_000)
            return BrowserResult(True, f"Clicked '{selector}'.", {"selector": selector})
        except Exception as e:
            return BrowserResult(False, f"Could not click '{selector}': {e}")

    async def _type_text(self, selector: str, text: str, url: str = "") -> BrowserResult:
        try:
            page = await self._ensure_browser()
            if url:
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await page.fill(selector, text, timeout=10_000)
            return BrowserResult(True, f"Typed into '{selector}'.", {"text": text})
        except Exception as e:
            return BrowserResult(False, f"Could not type into '{selector}': {e}")

    async def _scrape(self, url: str, selector: str = "body") -> BrowserResult:
        try:
            page = await self._ensure_browser()
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            text = await page.inner_text(selector, timeout=10_000)
            # Trim to a reasonable length
            trimmed = text.strip()[:4000]
            return BrowserResult(True, trimmed, {"url": url, "selector": selector, "raw": trimmed})
        except Exception as e:
            return BrowserResult(False, f"Failed to scrape {url}: {e}")

    async def _close(self):
        if self._page and not self._page.is_closed():
            await self._page.close()
        if self._browser:
            await self._browser.close()
        if hasattr(self, "_pw"):
            await self._pw.stop()
        self._browser = None
        self._page = None
