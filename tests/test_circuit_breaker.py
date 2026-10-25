import time
import pytest
from backend.agent.orchestrator import CortexOrchestrator
from backend.core.contracts import TaskCommand

def test_circuit_breaker_trips_on_429():
    orchestrator = CortexOrchestrator(use_gemini=True)
    assert orchestrator.gemini_cooldown_until == 0.0

    # Simulate 429 quota exception
    exc = Exception("429 ResourceExhausted: You exceeded your current quota")
    orchestrator._handle_gemini_error(exc, context="unit test")

    assert orchestrator.gemini_cooldown_until > time.time() + 200.0
    assert orchestrator._is_gemini_available() is False

def test_fast_response_when_gemini_in_cooldown():
    orchestrator = CortexOrchestrator(use_gemini=True)
    # Trip circuit breaker
    orchestrator.gemini_cooldown_until = time.time() + 300.0

    # Test an inquiry - it must resolve quickly without calling Gemini
    start_time = time.time()
    res = orchestrator.chat("what time is it?")
    duration = time.time() - start_time

    assert duration < 1.0, f"Query took too long: {duration}s"
    assert "message" in res
    assert len(res["message"]) > 0

def test_circuit_breaker_resets_after_cooldown():
    orchestrator = CortexOrchestrator(use_gemini=True)
    # Set expired cooldown
    orchestrator.gemini_cooldown_until = time.time() - 10.0
    # If use_gemini is True and API key is present, it should be available again
    if orchestrator.use_gemini:
        assert orchestrator._is_gemini_available() is True
