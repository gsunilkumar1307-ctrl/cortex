import os
import pytest

@pytest.fixture(autouse=True)
def prevent_live_inference_in_tests(monkeypatch):
    """
    Ensure unit tests never make accidental unmocked live network calls by default
    unless explicitly opted in via CORTEX_ALLOW_LIVE_OLLAMA=1 or CORTEX_ALLOW_LIVE_GEMINI=1.
    """
    if os.getenv("CORTEX_ALLOW_LIVE_OLLAMA") == "1" or os.getenv("CORTEX_ALLOW_LIVE_GEMINI") == "1":
        yield
        return

    def safe_generate(self, *args, **kwargs):
        raise Exception(
            "429 ResourceExhausted: Quota exceeded for metric: "
            "generate_content_requests, limit: 20, model: qwen3.5:9b, retry_delay { seconds: 3600 }"
        )

    try:
        from backend.agent.ollama_client import OllamaModel
        monkeypatch.setattr(OllamaModel, "generate_content", safe_generate)
    except Exception:
        pass

    try:
        import google.generativeai as genai
        monkeypatch.setattr(genai.GenerativeModel, "generate_content", safe_generate)
    except Exception:
        pass

    yield
