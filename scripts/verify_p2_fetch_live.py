#!/usr/bin/env python3
"""
Live macOS Acceptance Test for Phase P2: Web Content Retrieval / Fetch MCP Integration.

Validates:
1. Live subprocess spawn of official `uvx mcp-server-fetch`.
2. MCP initialize & tool discovery via stdio JSON-RPC.
3. Real live HTTP retrieval and Markdown conversion of https://httpbin.org/html.
4. Live SSRF pre-flight rejection of loopback URL http://127.0.0.1:8765.
5. End-to-end CortexOrchestrator routing and execution of natural language commands.
6. Offline/cooldown resilience with deterministic markdown delivery.
"""

import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities.device_actions import DeviceAutomation
from backend.core.contracts import TaskCommand, TaskStatus, command_from_intent
from backend.mcp.client import MCPClient
from backend.mcp.config import get_fetch_server_config
from backend.mcp.fetch_adapter import MCPFetchToolAdapter
from backend.mcp.fetch_policy import FetchSecurityPolicy
from backend.mcp.manager import MCPServerManager
from backend.mcp.models import MCPToolResult
from backend.mcp.registry import MCPRegistryBridge


def run_live_acceptance():
    print("=" * 80)
    print(" CORTEX AGENT — PHASE P2 LIVE macOS ACCEPTANCE VERIFICATION")
    print("=" * 80)

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 1: Server Configuration & Lifecycle
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 1] Validating Fetch Server Config & UVX Availability...")
    cfg = get_fetch_server_config()
    print(f"  ✓ Server name: {cfg.name}")
    print(f"  ✓ Command: {cfg.command} {' '.join(cfg.args)}")
    print(f"  ✓ Timeout: {cfg.timeout_seconds}s")
    assert cfg.name == "fetch"

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 2: Live MCP Server Process Launch & Tool Discovery
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 2] Spawning Live MCP Fetch Process & Discovering Tools...")
    config_file = Path(__file__).resolve().parent.parent / "config" / "mcp_servers.json"
    manager = MCPServerManager(config_file)
    manager.start_server("fetch", timeout=20.0)
    srv = manager._servers.get("fetch")
    client = srv.client
    pid = client.process.process.pid if client.process and client.process.process else "active"
    print(f"  ✓ Process started with PID: {pid}")
    assert client.process.is_alive

    tools = manager.get_tool_definitions("fetch")
    print(f"  ✓ Discovered {len(tools)} tool(s): {[t.name for t in tools]}")
    fetch_tool = next((t for t in tools if t.name == "fetch"), None)
    assert fetch_tool is not None, "Tool 'fetch' was not discovered from mcp-server-fetch"
    print(f"  ✓ Tool schema: {list(fetch_tool.input_schema.get('properties', {}).keys())}")

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 3: Live Public Web Retrieval & Markdown Conversion
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 3] Live Retrieval of https://httpbin.org/html via MCP...")
    t0 = time.time()
    res: MCPToolResult = manager.call_tool("fetch", "fetch", {"url": "https://httpbin.org/html"}, timeout=15.0)
    elapsed = time.time() - t0
    assert not res.is_error, f"Fetch failed: {res.get_text_content()}"
    content = res.get_text_content()
    print(f"  ✓ Retrieved {len(content)} characters in {elapsed:.2f}s")
    print(f"  ✓ Content excerpt:\n{content[:200]}...")
    assert "Herman Melville" in content or "Moby Dick" in content or "heading" in content.lower()

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 4: Live SSRF Security Policy Rejection
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 4] Testing Live SSRF Protection against http://127.0.0.1:8765...")
    policy = FetchSecurityPolicy()
    ok, canon, err = policy.validate_url("http://127.0.0.1:8765/admin")
    print(f"  ✓ Validation result: is_valid={ok}, error='{err}'")
    assert ok is False
    assert "port" in err.lower() or "loopback" in err.lower() or "private" in err.lower() or "blocked" in err.lower()

    # Adapter-level enforcement
    adapter = MCPFetchToolAdapter(fetch_tool, manager, namespaced_name="mcp_fetch", policy=policy)
    exec_res = adapter.execute({"url": "http://127.0.0.1:8765/admin"})
    print(f"  ✓ Adapter execution result: ok={exec_res.ok}, error={exec_res.error}")
    assert exec_res.ok is False
    assert exec_res.error == "SecurityViolation"

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 5: BaseTool Lifecycle Verification
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 5] Validating Full BaseTool Lifecycle (Execute -> Observe -> Verify)...")
    exec_res_live = adapter.execute({"url": "https://httpbin.org/html"})
    assert exec_res_live.ok is True
    print(f"  ✓ Execute: {exec_res_live.data['character_count']} chars, title='{exec_res_live.data['title']}'")

    obs = adapter.observe({"url": "https://httpbin.org/html"}, exec_res_live)
    print(f"  ✓ Observe: target='{obs.target}', length={obs.state_data['length']}")
    assert obs.state_data["ok"] is True

    verif = adapter.verify({"url": "https://httpbin.org/html"}, obs, exec_res_live)
    print(f"  ✓ Verify: verified={verif.verified}, evidence='{verif.evidence}'")
    assert verif.verified is True

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 6: Natural Language Intent Routing (Search vs Fetch vs Browser)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 6] Validating Intent Routing Precision...")
    
    # 1. Search (discovery)
    cmd1 = command_from_intent("search for latest Python 3.12 release date")
    print(f"  ✓ 'search for...' -> {cmd1.value}")
    assert cmd1 == TaskCommand.WEB_SEARCH

    # 2. Browser navigation
    cmd2 = command_from_intent("open https://example.com in Safari")
    print(f"  ✓ 'open ... in Safari' -> {cmd2.value}")
    assert cmd2 == TaskCommand.OPEN_URL

    # 3. Web content fetch
    cmd3 = command_from_intent("read this webpage https://httpbin.org/html")
    print(f"  ✓ 'read this webpage...' -> {cmd3.value}")
    assert cmd3 == TaskCommand.FETCH_WEB_CONTENT

    # 4. Multi-URL comparison
    cmd4 = command_from_intent("compare https://python.org and https://rust-lang.org")
    print(f"  ✓ 'compare https://... and https://...' -> {cmd4.value}")
    assert cmd4 == TaskCommand.FETCH_WEB_CONTENT

    # ─────────────────────────────────────────────────────────────────────────
    # SCENARIO 7: Live End-to-End Orchestrator Execution
    # ─────────────────────────────────────────────────────────────────────────
    print("\n[Scenario 7] Live End-to-End Orchestrator Execution (Deterministic / Model-Outage Resilience)...")
    auto = DeviceAutomation(dry_run=True)
    orch = CortexOrchestrator(automation=auto, use_gemini=False)
    orch.ensure_mcp_tools()

    chat_res = orch.chat("Read this webpage https://httpbin.org/html")
    print(f"  ✓ Task ID: {chat_res['task']['id']}")
    print(f"  ✓ Task Status: {chat_res['task']['status']}")
    assert chat_res["task"]["status"] in (TaskStatus.COMPLETED.value, "completed")
    print(f"  ✓ Orchestrator response preview:\n{chat_res['message'][:250]}...")
    assert "httpbin.org" in chat_res["message"] or "Herman Melville" in chat_res["message"]

    # Stop server
    manager.stop_all()
    print("\n  ✓ Live MCP Server stopped successfully.")

    print("\n" + "=" * 80)
    print(" ALL SCENARIOS PASSED — LIVE ACCEPTANCE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_live_acceptance()
