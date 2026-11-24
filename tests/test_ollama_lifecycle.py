import os
import time
import pytest
from unittest.mock import patch, MagicMock
from backend.agent.ollama_client import (
    OllamaLifecycleManager,
    LocalAIStatus,
    get_ollama_lifecycle,
)
from backend.agent.orchestrator import CortexOrchestrator


class TestOllamaLifecycle:
    def test_status_states_match_specification(self):
        """Verify the exact truthful status strings specified in the requirements."""
        assert LocalAIStatus.STARTING == "Starting Local AI…"
        assert LocalAIStatus.CONNECTING == "Connecting to Ollama…"
        assert LocalAIStatus.LOADING_MODEL == "Loading model…"
        assert LocalAIStatus.READY == "Local AI Ready"
        assert LocalAIStatus.UNAVAILABLE == "Local AI Unavailable"

    def test_detects_already_running_ollama(self):
        """If service is running and model exists, immediately marks ready without duplicate launch."""
        mgr = OllamaLifecycleManager(model_name="qwen3.5:9b")
        with patch.object(mgr, "is_service_running", return_value=True), \
             patch.object(mgr, "verify_model_available", return_value=(True, "Model verified.")), \
             patch("subprocess.Popen") as mock_popen:
            ready = mgr.ensure_ready(max_wait_seconds=2.0)
            assert ready is True
            assert mgr.is_ready() is True
            assert mgr.get_status()["status"] == LocalAIStatus.READY
            assert mock_popen.call_count == 0  # No duplicate process spawned

    def test_missing_model_produces_truthful_actionable_error(self):
        """Missing model marks unavailable without auto-downloading and provides actionable error."""
        mgr = OllamaLifecycleManager(model_name="nonexistent:model")
        with patch.object(mgr, "is_service_running", return_value=True), \
             patch.object(mgr, "verify_model_available", return_value=(False, "Model 'nonexistent:model' not found locally. To download it, run: ollama pull nonexistent:model")):
            ready = mgr.ensure_ready(max_wait_seconds=2.0)
            assert ready is False
            assert mgr.is_ready() is False
            status = mgr.get_status()
            assert status["status"] == LocalAIStatus.UNAVAILABLE
            assert "ollama pull nonexistent:model" in status["error"]

    def test_starts_ollama_when_not_running(self):
        """If Ollama is not running, starts it using existing binary, polls health, and verifies model."""
        mgr = OllamaLifecycleManager(model_name="qwen3.5:9b")
        # First check False, then becomes True
        poll_responses = [False, False, True]
        def fake_is_running(timeout=1.0):
            if poll_responses:
                return poll_responses.pop(0)
            return True

        with patch.object(mgr, "is_service_running", side_effect=fake_is_running), \
             patch.object(mgr, "is_process_running", return_value=False), \
             patch.object(mgr, "find_ollama_binary", return_value="/usr/local/bin/ollama"), \
             patch.object(mgr, "verify_model_available", return_value=(True, "Model verified.")), \
             patch("subprocess.Popen") as mock_popen:
            ready = mgr.ensure_ready(max_wait_seconds=5.0)
            assert ready is True
            assert mgr.is_ready() is True
            assert mock_popen.call_count == 1
            args, kwargs = mock_popen.call_args
            assert args[0] == ["/usr/local/bin/ollama", "serve"]

    def test_no_duplicate_spawn_if_process_already_starting(self):
        """If process is already running in OS table, do not spawn another Popen."""
        mgr = OllamaLifecycleManager(model_name="qwen3.5:9b")
        with patch.object(mgr, "is_service_running", side_effect=[False, True]), \
             patch.object(mgr, "is_process_running", return_value=True), \
             patch.object(mgr, "verify_model_available", return_value=(True, "Model verified.")), \
             patch("subprocess.Popen") as mock_popen:
            ready = mgr.ensure_ready(max_wait_seconds=5.0)
            assert ready is True
            assert mock_popen.call_count == 0

    def test_temporary_connection_drop_recovery(self):
        """Connection failure transitions to UNAVAILABLE and safe recovery has cooldown against restart loops."""
        mgr = OllamaLifecycleManager(model_name="qwen3.5:9b")
        mgr._ready = True
        mgr._status = LocalAIStatus.READY

        with patch.object(mgr, "start_background") as mock_bg:
            mgr.handle_connection_failure(Exception("Connection refused"))
            assert mgr.is_ready() is False
            assert mgr.get_status()["status"] == LocalAIStatus.UNAVAILABLE
            assert mock_bg.call_count == 1

            # Immediate second failure during cooldown does NOT spawn runaway recovery
            mgr.handle_connection_failure(Exception("Connection refused again"))
            assert mock_bg.call_count == 1  # Still 1, cooldown active!


class TestOllamaAPIIntegration:
    def setup_method(self):
        from starlette.testclient import TestClient
        from backend.api.server import app, orchestrator
        self.client = TestClient(app)
        self.orchestrator = orchestrator

    def test_health_and_llm_status_endpoints_unauthenticated(self):
        """Health and LLM status endpoints must be publicly accessible to frontend during startup."""
        resp_health = self.client.get("/health")
        assert resp_health.status_code == 200
        data_health = resp_health.json()
        assert data_health["ok"] is True
        assert "llm" in data_health
        assert "status" in data_health["llm"]

        resp_status = self.client.get("/api/llm/status")
        assert resp_status.status_code == 200
        data_status = resp_status.json()
        assert "status" in data_status
        assert "ready" in data_status
        assert "model" in data_status

    def test_chat_blocked_with_503_when_local_ai_not_ready(self):
        """Chat must not falsely succeed when Local AI is unavailable."""
        with patch.object(self.orchestrator.ollama_lifecycle, "is_ready", return_value=False), \
             patch.object(self.orchestrator.ollama_lifecycle, "get_status", return_value={
                 "status": LocalAIStatus.UNAVAILABLE,
                 "ready": False,
                 "model": "qwen3.5:9b",
                 "endpoint": "http://127.0.0.1:11434",
                 "error": "Model 'qwen3.5:9b' not found locally.",
             }):
            # Set auth token or test with session header
            from backend.core.auth import get_or_create_session_secret
            token = get_or_create_session_secret()
            headers = {"X-Cortex-Session": token}

            resp = self.client.post("/chat", json={"message": "hello"}, headers=headers)
            assert resp.status_code == 503
            assert "Local AI not ready" in resp.json()["detail"]
            assert "Model 'qwen3.5:9b' not found locally" in resp.json()["detail"]

