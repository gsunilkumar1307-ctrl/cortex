from __future__ import annotations

import base64
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _capture_screenshot() -> bytes:
    """Capture the full screen and return as PNG bytes."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name

    system = platform.system().lower()
    try:
        if system == "darwin":
            res = subprocess.run(["screencapture", "-x", path], capture_output=True, text=True)
            if res.returncode != 0:
                # Open Privacy & Security Settings
                try:
                    subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"])
                except Exception:
                    pass
                raise PermissionError(
                    "macOS requires Screen Recording permission to view your screen. I've opened System Settings — please toggle on VS Code or Terminal under Privacy & Security → Screen Recording, then try again."
                )
        elif system == "windows":
            script = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "Add-Type -AssemblyName System.Drawing;"
                "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
                "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
                "$g=[System.Drawing.Graphics]::FromImage($bmp);"
                "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
                f"$bmp.Save('{path}');"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
        else:
            subprocess.run(["scrot", path], check=True)

        return Path(path).read_bytes()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def analyze_screen(api_key: str, question: str = "What is on my screen right now?") -> dict[str, Any]:
    """
    Takes a screenshot and asks Gemini Vision to describe it.
    Returns dict with 'ok', 'description', and 'raw_bytes_len'.
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
    except ImportError:
        return {"ok": False, "description": "google-generativeai package not installed.", "raw_bytes_len": 0}

    try:
        png_bytes = _capture_screenshot()
    except PermissionError as pe:
        return {"ok": False, "description": str(pe), "raw_bytes_len": 0}
    except Exception as e:
        return {"ok": False, "description": f"Could not capture screen: {e}", "raw_bytes_len": 0}

    try:
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content([
            question,
            {"mime_type": "image/png", "data": base64.b64encode(png_bytes).decode()}
        ])
        description = response.text.strip()
        return {"ok": True, "description": description, "raw_bytes_len": len(png_bytes)}
    except Exception as e:
        return {"ok": False, "description": f"Vision analysis failed: {e}", "raw_bytes_len": len(png_bytes)}
