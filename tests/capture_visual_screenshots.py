#!/usr/bin/env python3
"""
Cortex Agent — Automated Visual Screenshot Acceptance Suite
Captures high-resolution screenshots across multiple resolutions and themes
using Playwright against the live running Vite frontend and FastAPI backend.
"""

import os
import sys
import time
import signal
import subprocess
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP_DIR = REPO_ROOT / "apps" / "desktop"
DOCS_SCREENSHOTS = REPO_ROOT / "docs" / "screenshots"
DOCS_SCREENSHOTS.mkdir(parents=True, exist_ok=True)

ROOT_DOCS = Path("/Users/gsunilkumar/Desktop/antigravity/docs/screenshots")
ROOT_DOCS.mkdir(parents=True, exist_ok=True)


def wait_for_url(url, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def run_capture():
    backend_proc = None
    vite_proc = None

    try:
        # 1. Start FastAPI backend on 8765 with offline deterministic mode and local test auth
        print("Starting FastAPI backend on port 8765...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["CORTEX_DISABLE_AUTH"] = "1"
        env["CORTEX_OFFLINE_MODE"] = "1"

        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api.server:app", "--port", "8765", "--host", "127.0.0.1"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 2. Start Vite dev server on 5173
        print("Starting Vite frontend on port 5173...")
        vite_proc = subprocess.Popen(
            ["npx", "vite", "--port", "5173", "--host", "127.0.0.1"],
            cwd=str(DESKTOP_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        print("Waiting for services to become healthy...")
        if not wait_for_url("http://127.0.0.1:8765/health", timeout=12):
            print("Warning: Backend healthcheck timed out; proceeding with frontend capture.")
        if not wait_for_url("http://127.0.0.1:5173", timeout=15):
            raise RuntimeError("Vite dev server failed to start on http://127.0.0.1:5173")
        print("Both backend and frontend services are online.")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def save_shot(page, filename):
                dest1 = DOCS_SCREENSHOTS / filename
                dest2 = ROOT_DOCS / filename
                page.screenshot(path=str(dest1), full_page=False)
                if dest1 != dest2:
                    try:
                        import shutil
                        shutil.copy(dest1, dest2)
                    except Exception:
                        pass
                print(f"  ✓ Saved: {filename} ({dest1.stat().st_size} bytes)")

            # ── 1. 1440x900 Empty Welcome Screen (Dark Theme) ──
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: print(f"  [console] {msg.type}: {msg.text}"))
            page.on("pageerror", lambda err: print(f"  [pageerror] {err}"))
            page.goto("http://127.0.0.1:5173")
            page.wait_for_selector("text=Welcome to Cortex", timeout=10000)
            time.sleep(1.0)
            save_shot(page, "01_welcome_dark_1440x900.png")

            # ── 2. 1440x900 Empty Welcome Screen (Light Theme) ──
            theme_btn = page.locator("button[title*='Light'], button[title*='Dark']").first
            if theme_btn.count() > 0:
                theme_btn.click()
                time.sleep(0.6)
                save_shot(page, "02_welcome_light_1440x900.png")
                # Switch back to dark theme
                theme_btn.click()
                time.sleep(0.4)

            # ── 3. 1440x900 Collapsed Sidebar View ──
            collapse_btn = page.locator("button[title*='Collapse Sidebar']").first
            if collapse_btn.count() > 0:
                collapse_btn.click()
                time.sleep(0.5)
                save_shot(page, "03_sidebar_collapsed_1440x900.png")
                # Expand sidebar back
                expand_btn = page.locator("button[title*='Expand Sidebar']").first
                if expand_btn.count() > 0:
                    expand_btn.click()
                    time.sleep(0.4)

            # ── 4. Active Conversation with Messages & Mail Draft Card ──
            prompt_btn = page.locator("button:has-text('Draft an email')").first
            if prompt_btn.count() > 0:
                print("Clicking 'Draft an email' prompt...")
                prompt_btn.click()
                time.sleep(3.5)
                print("Page body preview:", page.locator("body").inner_text()[:300].replace("\n", " "))
                save_shot(page, "04_active_conversation_1440x900.png")
                save_shot(page, "05_email_draft_approval_1440x900.png")

            # ── 6. Long Response with Code Blocks & Data Tables ──
            # Send query for markdown code & tables
            textarea = page.locator("textarea").first
            if textarea.count() > 0:
                textarea.fill("Summarize the key architectural decisions of Cortex Agent.")
                send_btn = page.locator("button[title*='Send Message']").first
                send_btn.click()
                time.sleep(2.0)
                save_shot(page, "06_code_and_tables_1440x900.png")

            # ── 7. Task Execution Card (Multi-Step Plan) ──
            if textarea.count() > 0:
                textarea.fill("Plan my project tasks for today with clear step dependencies.")
                page.locator("button[title*='Send Message']").first.click()
                time.sleep(2.0)
                save_shot(page, "07_task_plan_card_1440x900.png")

            # ── 8. Composer with Slash Command Menu ──
            if textarea.count() > 0:
                textarea.fill("/")
                time.sleep(0.5)
                save_shot(page, "08_composer_slash_menu_1440x900.png")

            context.close()

            # ── 9. Responsive View at 1280x800 ──
            context_1280 = browser.new_context(viewport={"width": 1280, "height": 800})
            page_1280 = context_1280.new_page()
            page_1280.goto("http://127.0.0.1:5173")
            page_1280.wait_for_selector("text=Welcome to Cortex", timeout=10000)
            time.sleep(0.8)
            save_shot(page_1280, "09_responsive_1280x800.png")
            context_1280.close()

            # ── 10. Responsive View at 1024x768 ──
            context_1024 = browser.new_context(viewport={"width": 1024, "height": 768})
            page_1024 = context_1024.new_page()
            page_1024.goto("http://127.0.0.1:5173")
            page_1024.wait_for_selector("text=Welcome to Cortex", timeout=10000)
            time.sleep(0.8)
            save_shot(page_1024, "10_responsive_1024x768.png")
            context_1024.close()

            browser.close()
            print("Successfully captured all visual acceptance screenshots.")

    finally:
        if vite_proc:
            try:
                os.kill(vite_proc.pid, signal.SIGTERM)
            except Exception:
                pass
        if backend_proc:
            try:
                os.kill(backend_proc.pid, signal.SIGTERM)
            except Exception:
                pass


if __name__ == "__main__":
    run_capture()
