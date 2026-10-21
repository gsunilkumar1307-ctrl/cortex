#!/usr/bin/env python3
"""Shim forwarding to scripts/verify_mail_live.py."""
import runpy
from pathlib import Path

if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / "verify_mail_live.py"
    runpy.run_path(str(script_path), run_name="__main__")
