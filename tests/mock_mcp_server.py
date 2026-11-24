#!/usr/bin/env python3
"""
Minimal, hermetic local Mock MCP Server over stdio.
Used strictly for unit and integration testing of the Cortex MCP subsystem.
Requires zero external dependencies.
"""
from __future__ import annotations

import json
import sys
import time


def main() -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except Exception:
            continue

        method = req.get("method")
        req_id = req.get("id")

        # Notifications (no response required)
        if method == "notifications/initialized":
            continue
        if method == "notifications/cancelled":
            continue

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"},
                },
            }
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echoes back the input message.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"],
                            },
                        },
                        {
                            "name": "calculate_sum",
                            "description": "Adds two numbers.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "a": {"type": "number"},
                                    "b": {"type": "number"},
                                },
                                "required": ["a", "b"],
                            },
                        },
                        {
                            "name": "fail_action",
                            "description": "Simulates an MCP tool error.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "empty_action",
                            "description": "Returns empty output to test verification failure.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                        {
                            "name": "sleep_delay",
                            "description": "Sleeps to trigger client timeout.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"seconds": {"type": "number"}},
                            },
                        },
                        {
                            "name": "crash_process",
                            "description": "Immediately aborts the process.",
                            "inputSchema": {"type": "object", "properties": {}},
                        },
                    ]
                },
            }
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})

            if name == "echo":
                msg = args.get("message", "")
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Echo: {msg}"}],
                        "isError": False,
                    },
                }
            elif name == "calculate_sum":
                a = args.get("a", 0)
                b = args.get("b", 0)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": str(a + b)}],
                        "isError": False,
                    },
                }
            elif name == "fail_action":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": "Operation failed on remote mock tool."}],
                        "isError": True,
                    },
                }
            elif name == "empty_action":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [],
                        "isError": False,
                    },
                }
            elif name == "sleep_delay":
                sec = float(args.get("seconds", 2.0))
                time.sleep(sec)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Slept {sec}s"}],
                        "isError": False,
                    },
                }
            elif name == "crash_process":
                sys.exit(42)
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method/Tool not found: {name}"},
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unsupported method: {method}"},
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
