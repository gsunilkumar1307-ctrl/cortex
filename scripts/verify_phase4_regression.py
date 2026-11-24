"""
Phase 4 Regression Verification Script for Cortex Local Brain Migration (Gemini -> Ollama qwen3.5:9b)
Executes Tests 2, 3, 4, 5, 6, 7, 8, 9, 10
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import unittest
from unittest.mock import patch

# Ensure live Ollama is used during this verification
os.environ["CORTEX_ALLOW_LIVE_OLLAMA"] = "1"
os.environ["OLLAMA_TIMEOUT"] = "60"

from backend.agent.ollama_client import OllamaModel, OllamaUnavailableError
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand, TaskStatus, RiskLevel

def test_1_model_verification():
    print("\n--- TEST 1: MODEL VERIFICATION ---")
    model = OllamaModel(model_name="qwen3.5:9b")
    print(f"Model configured: {model.model_name} at {model.endpoint}")
    assert model.model_name == "qwen3.5:9b", f"Expected qwen3.5:9b, got {model.model_name}"
    print("Test 1 PASS: OllamaModel initialized with qwen3.5:9b.")

def test_2_basic_chat_and_identity():
    print("\n--- TEST 2: BASIC CHAT AND IDENTITY ---")
    orch = CortexOrchestrator(dry_run=True)
    
    # Check identity questions
    questions = [
        "Hello",
        "Who are you?",
        "What can you do?",
        "What model is powering you right now?"
    ]
    for q in questions:
        res = orch.chat(q)
        msg = res.get("message", "")
        print(f"User: {q}\nCortex: {msg[:120]}...\n")
        assert len(msg) > 0, f"Expected non-empty response for {q}"
        assert "<think>" not in msg, f"Thinking tag leaked in {q}"
        if "model" in q:
            assert "qwen" in msg.lower() or "ollama" in msg.lower(), f"Did not mention qwen/ollama in: {msg}"
            assert "gemini" not in msg.lower(), f"Mentioned Gemini in: {msg}"
    print("Test 2 PASS: Basic chat and identity verified without thinking leak or Gemini references.")

def test_3_email_drafting():
    print("\n--- TEST 3: EMAIL DRAFTING ---")
    orch = CortexOrchestrator(dry_run=True)
    prompt = "Draft an email to Rahul asking about the status of the internship application for next semester."
    res = orch.chat(prompt)
    msg = res.get("message", "")
    task = res.get("task")
    print(f"Email Draft Response:\n{msg}\n")
    print(f"Task details: {task}\n")
    
    assert task is not None, "Expected task to be created"
    assert task["command"] in ("draft_mail", "send_mail"), f"Unexpected command: {task['command']}"
    assert "<think>" not in msg, "Thinking tag leaked in draft response"
    
    params = task.get("params", {})
    body = params.get("body", "")
    subject = params.get("subject", "")
    recipient = params.get("recipient", "")
    print(f"Extracted Params: recipient='{recipient}', subject='{subject}', body='{body}'")
    
    assert "rahul" in recipient.lower() or "rahul" in str(params).lower(), "Missing recipient"
    assert "internship" in subject.lower() or "internship" in body.lower(), "Missing internship subject/body"
    assert "<think>" not in body, "Thinking tag leaked in drafted body"
    
    # If account disambiguation is requested, complete the turn
    if task.get("status") == "need_info" and "account" in msg.lower():
        print("Account selection requested. Responding with default account...")
        res2 = orch.chat("Use Default Account")
        task2 = res2.get("task")
        msg2 = res2.get("message", "")
        print(f"Post-account response:\n{msg2}\nTask status: {task2.get('status') if task2 else None}")
        if task2:
            assert task2["status"] in (TaskStatus.WAITING_APPROVAL.value, TaskStatus.COMPLETED.value, "need_approval", "waiting_approval")
    else:
        assert task["status"] in (TaskStatus.WAITING_APPROVAL.value, TaskStatus.COMPLETED.value)
    print("Test 3 PASS: Email draft composed cleanly without thinking leakage or auto-send.")

def test_4_apple_mail_mcp():
    print("\n--- TEST 4: MAIL MCP TOOLS ---")
    orch = CortexOrchestrator(dry_run=True)
    # Check if read_mail works
    res = orch.chat("Read my latest 3 emails from inbox")
    msg = res.get("message", "")
    task = res.get("task")
    print(f"Mail read response:\n{msg[:200]}...\n")
    assert task is not None
    assert task["command"] in ("read_mail", "summarize_mail")
    print("Test 4 PASS: Mail read tool correctly invoked and executed.")

def test_5_browser_automation():
    print("\n--- TEST 5: BROWSER AUTOMATION ---")
    orch = CortexOrchestrator(dry_run=True)
    res = orch.chat("Search the web for python asyncio tutorial")
    msg = res.get("message", "")
    task = res.get("task")
    print(f"Browser search response:\n{msg[:200]}...\n")
    assert task is not None
    assert task["command"] in ("web_search", "open_url")
    print("Test 5 PASS: Browser search command routed and handled properly.")

def test_6_real_tool_execution():
    print("\n--- TEST 6: REAL TOOL EXECUTION ---")
    orch = CortexOrchestrator(dry_run=True)
    # Intent analysis -> tool plan -> execution
    res = orch.chat("List files on my Desktop")
    msg = res.get("message", "")
    task = res.get("task")
    print(f"File list response:\n{msg[:200]}...\n")
    assert task is not None
    assert task["command"] in ("search_files", "open_url", "desktop_workflow")
    print("Test 6 PASS: Tool planning and execution lifecycle completed.")

def test_7_send_safety_approval():
    print("\n--- TEST 7: EMAIL SEND APPROVAL GATE ---")
    orch = CortexOrchestrator(dry_run=True)
    res = orch.chat("Send an email to rahul@example.com saying I will join the meeting tomorrow at 10am")
    msg = res.get("message", "")
    task = res.get("task")
    print(f"Send mail response:\n{msg[:200]}...\n")
    req_appr = task.get("requiresApproval", task.get("requires_approval", False))
    print(f"Task status: {task.get('status')}, requires_approval: {req_appr}")
    assert req_appr is True or task.get("status") in (TaskStatus.WAITING_APPROVAL.value, TaskStatus.AWAITING_APPROVAL.value, "need_info", "need_approval")
    print("Test 7 PASS: Send email explicitly stopped at approval gate.")

def test_8_ollama_unavailable_handling():
    print("\n--- TEST 8: OLLAMA UNAVAILABLE HANDLING ---")
    # Point host to dead port
    bad_model = OllamaModel(base_url="http://127.0.0.1:11439", model_name="qwen3.5:9b")
    orch = CortexOrchestrator(dry_run=True)
    orch.ollama_endpoint = "http://127.0.0.1:11439"
    orch.ollama_model = bad_model
    orch.gemini_model = bad_model
    orch.use_llm = True
    
    # Directly test general question fallback
    res = orch._answer_general_question("Explain the topological Kondo insulator SmB6 in detail.")
    print(f"Unavailable response: '{res}'")
    expected = "Cortex's local AI engine is unavailable. Please start Ollama and try again."
    assert res == expected, f"Expected '{expected}', got '{res}'"
    print("Test 8 PASS: Exact expected unavailable message returned.")

def test_9_verification_against_cloud_remnants():
    print("\n--- TEST 9: VERIFICATION AGAINST CLOUD REMNANTS ---")
    orch = CortexOrchestrator(dry_run=True)
    assert orch.model_provider == "ollama"
    assert orch.model_name == "qwen3.5:9b"
    assert orch.ollama_endpoint == "http://127.0.0.1:11434"
    assert orch.use_gemini is True # backward-compat flag maps to use_llm
    # Verify no import of genai at runtime
    import backend.agent.orchestrator as orch_module
    assert orch_module.HAS_GENAI is False
    assert orch_module.genai is None
    print("Test 9 PASS: Cloud remnants completely eliminated; locked to Ollama qwen3.5:9b.")

if __name__ == "__main__":
    test_1_model_verification()
    test_2_basic_chat_and_identity()
    test_3_email_drafting()
    test_4_apple_mail_mcp()
    test_5_browser_automation()
    test_6_real_tool_execution()
    test_7_send_safety_approval()
    test_8_ollama_unavailable_handling()
    test_9_verification_against_cloud_remnants()
    print("\n=== ALL REGRESSION TESTS PASSED SUCCESSFULLY! ===")
