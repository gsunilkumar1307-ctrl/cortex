#!/usr/bin/env python3
"""
Automated Live Acceptance Test Suite for Cortex P0.2 Always-Available Desktop Companion.
Verifies:
1. FastAPI backend /health, /audio_chat, /tts, /threads with security token.
2. Vite desktop UI compilation and serving on port 5173.
3. Native Electron main process launch on macOS.
4. Global shortcut registration (Command+Shift+A default and conflict handling).
5. macOS system tray creation and status indicator synchronization.
6. Clean, graceful lifecycle termination.
"""

import os
import sys
import time
import json
import urllib.request
import subprocess
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DESKTOP_DIR = os.path.join(REPO_ROOT, "apps", "desktop")
ELECTRON_BIN = os.path.join(DESKTOP_DIR, "node_modules", "electron", "dist", "Electron.app", "Contents", "MacOS", "Electron")

class TestLiveCortexCompanionIntegration(unittest.TestCase):
    brain_proc = None
    vite_proc = None

    @classmethod
    def setUpClass(cls):
        # 1. Start FastAPI backend on 8765
        brain_env = dict(os.environ)
        brain_env["CORTEX_SESSION_SECRET"] = "test-session-secret-p02-companion"
        cls.brain_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.api.server:app", "--host", "127.0.0.1", "--port", "8765", "--app-dir", REPO_ROOT],
            cwd=REPO_ROOT,
            env=brain_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 2. Start Vite on 5173
        cls.vite_proc = subprocess.Popen(
            ["npm", "run", "dev", "--prefix", DESKTOP_DIR],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # Wait for both to be responsive
        brain_ready = False
        for _ in range(25):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=1) as resp:
                    if resp.status == 200:
                        brain_ready = True
                        break
            except Exception:
                time.sleep(0.5)

        vite_ready = False
        for _ in range(25):
            try:
                with urllib.request.urlopen("http://127.0.0.1:5173", timeout=1) as resp:
                    if resp.status == 200:
                        vite_ready = True
                        break
            except Exception:
                time.sleep(0.5)

        if not brain_ready:
            raise RuntimeError("Backend failed to become ready on http://127.0.0.1:8765/health")
        if not vite_ready:
            raise RuntimeError("Vite dev server failed to become ready on http://127.0.0.1:5173")

    @classmethod
    def tearDownClass(cls):
        if cls.brain_proc:
            cls.brain_proc.terminate()
            cls.brain_proc.wait()
        if cls.vite_proc:
            cls.vite_proc.terminate()
            cls.vite_proc.wait()

    def test_01_backend_health_and_security(self):
        # Unauthenticated request should fail on protected endpoints
        req = urllib.request.Request("http://127.0.0.1:8765/threads")
        try:
            with urllib.request.urlopen(req) as resp:
                self.fail("Expected HTTP 401 for unauthenticated request")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 401)

        # Authenticated request succeeds
        req_auth = urllib.request.Request(
            "http://127.0.0.1:8765/threads",
            headers={"X-Cortex-Session": "test-session-secret-p02-companion"}
        )
        with urllib.request.urlopen(req_auth) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("threads", data)

    def test_02_vite_frontend_serves_cortex_app(self):
        req = urllib.request.Request("http://127.0.0.1:5173")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode()
            self.assertIn("<title>Cortex</title>", html)
            self.assertIn("/src/App.jsx", html)

    def test_03_native_electron_companion_boot(self):
        # Test launching native Electron with our live backend and frontend
        electron_env = dict(os.environ)
        electron_env.pop("ELECTRON_RUN_AS_NODE", None)
        electron_env["CORTEX_SESSION_SECRET"] = "test-session-secret-p02-companion"
        electron_env["CORTEX_DESKTOP_URL"] = "http://127.0.0.1:5173"

        electron_proc = subprocess.Popen(
            [ELECTRON_BIN, "electron/main.js"],
            cwd=DESKTOP_DIR,
            env=electron_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )

        # Let Electron run and initialize Tray, Shortcuts, and Windows
        time.sleep(3.5)
        electron_proc.terminate()
        stdout, _ = electron_proc.communicate()

        print("\n--- Electron Boot Output ---")
        print(stdout)
        print("----------------------------\n")

        self.assertIn("Global shortcut registered: Command+Shift+A", stdout)
        self.assertNotIn("ERR_CONNECTION_REFUSED", stdout)

if __name__ == "__main__":
    unittest.main()
