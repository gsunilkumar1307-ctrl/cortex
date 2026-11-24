import time
import pytest
from unittest.mock import MagicMock, patch
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import (
    Task,
    TaskCommand,
    TaskStatus,
    RiskLevel,
    command_from_intent,
    WhatsAppDraft,
)


def test_code_generation_intent_routes_to_ask_question():
    """Ensure programming queries do NOT trigger literal TYPE_TEXT keystrokes."""
    queries = [
        "Write python code to calculate Fibonacci numbers",
        "Write a python script to parse CSV files",
        "Generate python code for merge sort",
        "Write a function to reverse a string",
        "Create a script to backup files",
        "Write an algorithm for binary search",
        "Python code to scrape a web page",
    ]
    for q in queries:
        cmd = command_from_intent(q)
        assert cmd == TaskCommand.ASK_QUESTION, f"Failed for '{q}': got {cmd}"


def test_literal_typing_commands_preserve_type_text():
    """Ensure genuine device automation typing commands still map to TYPE_TEXT."""
    queries = [
        "type text Hello World",
        "type exactly sudo apt-get update",
        "enter text John Doe",
        "type Hello World",
    ]
    for q in queries:
        cmd = command_from_intent(q)
        assert cmd == TaskCommand.TYPE_TEXT, f"Failed for '{q}': got {cmd}"


def test_quota_429_trips_circuit_breaker_and_distinguishes_daily_limit():
    """Verify daily free_tier 20 limit sets daily quota state and parses retry_delay."""
    orchestrator = CortexOrchestrator(use_gemini=False)
    assert orchestrator.gemini_quota_exhausted is False

    # Simulate Google API daily quota error
    err_msg = (
        "429 ResourceExhausted: Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests, "
        "limit: 20, model: gemini-3.6-flash, retry_delay { seconds: 4648 }"
    )
    orchestrator._handle_gemini_error(Exception(err_msg), context="test")

    assert orchestrator.gemini_quota_exhausted is True
    assert orchestrator.gemini_retry_delay == 4648.0
    assert orchestrator.gemini_cooldown_until > time.time() + 4000.0
    assert orchestrator._is_gemini_available() is False


def test_temporary_rpm_limit_cooldown():
    """Verify transient RPM/TPM rate limit sets short cooldown."""
    orchestrator = CortexOrchestrator(use_gemini=False)
    err_msg = "429 Too Many Requests: Rate limit exceeded (15 requests per minute). retry_delay { seconds: 12 }"
    orchestrator._handle_gemini_error(Exception(err_msg), context="test")

    assert orchestrator.gemini_quota_exhausted is False
    assert orchestrator.gemini_retry_delay == 12.0
    assert orchestrator.gemini_cooldown_until <= time.time() + 15.0


def test_model_unavailable_pauses_task_no_fake_completion():
    """Ensure tasks requiring AI reasoning transition to PAUSED_MODEL_UNAVAILABLE, never COMPLETED."""
    orchestrator = CortexOrchestrator(use_gemini=True, dry_run=True)
    # Put Gemini in cooldown
    orchestrator.gemini_cooldown_until = time.time() + 3600.0
    assert orchestrator._is_gemini_available() is False

    task = Task(
        intent="Write python code to calculate Fibonacci numbers",
        command=TaskCommand.ASK_QUESTION,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
    )
    orchestrator.tasks[task.id] = task

    orchestrator._execute(task)

    assert task.status == TaskStatus.PAUSED_MODEL_UNAVAILABLE
    assert task.status != TaskStatus.COMPLETED
    assert "cooling down" in task.result or "unavailable" in task.result.lower()


def test_chat_returns_paused_state_when_model_in_cooldown():
    """Verify chat() returns paused message and does not save fake model response to history."""
    orchestrator = CortexOrchestrator(use_gemini=True, dry_run=True)
    orchestrator.gemini_cooldown_until = time.time() + 3600.0
    initial_history_len = len(orchestrator.history)

    res = orchestrator.chat("Write python code for bubble sort")

    assert "task" in res
    assert res["task"]["status"] == TaskStatus.PAUSED_MODEL_UNAVAILABLE.value
    # Ensure history was not polluted with a fake completed turn
    assert len(orchestrator.history) == initial_history_len


def test_resume_paused_tasks_re_executes_when_model_restored():
    """Verify resume_paused_tasks re-executes paused tasks once the model is restored."""
    orchestrator = CortexOrchestrator(use_gemini=True, dry_run=True)
    # Start in cooldown
    orchestrator.gemini_cooldown_until = time.time() + 3600.0

    task = Task(
        intent="Write python code to calculate Fibonacci numbers",
        command=TaskCommand.ASK_QUESTION,
        risk_level=RiskLevel.LOW,
        requires_approval=False,
    )
    orchestrator.tasks[task.id] = task
    orchestrator._execute(task)
    assert task.status == TaskStatus.PAUSED_MODEL_UNAVAILABLE

    # Cooldown expires
    orchestrator.gemini_cooldown_until = time.time() - 10.0
    assert orchestrator._is_gemini_available() is True

    with patch.object(orchestrator, "_answer_general_question", return_value="def fib(n): return n if n <= 1 else fib(n-1) + fib(n-2)"):
        resumed = orchestrator.resume_paused_tasks()
        assert task.id in resumed
        assert task.status == TaskStatus.COMPLETED
        assert "def fib(n)" in task.result


def test_whatsapp_intent_and_contact_parsing():
    """Verify WhatsApp contact and body parsing handles prefixes and preambles cleanly."""
    orchestrator = CortexOrchestrator(use_gemini=False, dry_run=True)

    # 1. "Send a message on WhatsApp to Alex saying hello"
    cmd = command_from_intent("Send a message on WhatsApp to Alex saying hello")
    assert cmd == TaskCommand.SEND_MESSAGE
    p1 = orchestrator._extract_params(cmd, "Send a message on WhatsApp to Alex saying hello")
    assert p1["recipient"] == "Alex"
    assert p1["body"] == "hello"
    assert p1.get("channel") == "whatsapp"

    # 2. "WhatsApp mom saying happy birthday"
    cmd2 = command_from_intent("WhatsApp mom saying happy birthday")
    assert cmd2 == TaskCommand.SEND_MESSAGE
    p2 = orchestrator._extract_params(cmd2, "WhatsApp mom saying happy birthday")
    assert p2["recipient"] == "mom"
    assert p2["body"] == "happy birthday"
    assert p2.get("channel") == "whatsapp"

    # 3. "Send message via WhatsApp to Rahul saying let's meet at 5pm"
    cmd3 = command_from_intent("Send message via WhatsApp to Rahul saying let's meet at 5pm")
    assert cmd3 == TaskCommand.SEND_MESSAGE
    p3 = orchestrator._extract_params(cmd3, "Send message via WhatsApp to Rahul saying let's meet at 5pm")
    assert p3["recipient"] == "Rahul"
    assert p3["body"] == "let's meet at 5pm"


def test_whatsapp_single_use_approval_hash_protection():
    """Verify single-use cryptographic approval hash invalidation and replay protection."""
    orchestrator = CortexOrchestrator(use_gemini=False, dry_run=True)

    draft = WhatsAppDraft(
        recipient="Alex",
        phone="+1234567890",
        body="Hello Alex",
        contact_id="c1",
        contact_source="saved_contacts",
    )
    draft.approval_hash = draft.compute_hash()

    task = Task(
        intent="Send a WhatsApp message to Alex saying Hello Alex",
        command=TaskCommand.SEND_MESSAGE,
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
        params={
            "channel": "whatsapp",
            "recipient": "Alex",
            "contact_name": "Alex",
            "phone": "+1234567890",
            "body": "Hello Alex",
            "approval_hash": draft.approval_hash,
        },
    )
    task.status = TaskStatus.WAITING_APPROVAL
    orchestrator.tasks[task.id] = task

    # 1. Rejecting approval invalidates the approval_hash
    orchestrator.approve(task.id, approved=False)
    assert task.status in (TaskStatus.CANCELED, TaskStatus.CANCELLED)
    assert task.params.get("approval_hash") is None

    # 2. Replay rejection on already processed task
    replay_res = orchestrator.approve(task.id, approved=True, approval_hash=draft.approval_hash)
    assert "replayed" in replay_res.get("error", "").lower() or "canceled" in replay_res.get("error", "").lower()
