"""
Verification of 20 consecutive live conversational requests to Cortex
Running purely on local Ollama qwen3.5:9b with zero cloud fallback.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ["CORTEX_ALLOW_LIVE_OLLAMA"] = "1"
os.environ["OLLAMA_TIMEOUT"] = "60"

from backend.agent.orchestrator import CortexOrchestrator

questions = [
    "What is artificial intelligence in one sentence?",
    "What is a CLI?",
    "Name three colors of the rainbow.",
    "What is Python used for?",
    "What is 15 plus 27?",
    "What is the capital of Karnataka?",
    "Explain what an API is in simple terms.",
    "What is the difference between RAM and storage?",
    "What does HTTP stand for?",
    "Name two renewable energy sources.",
    "What is an operating system?",
    "What is open source software?",
    "Why do computers use binary?",
    "What is a database?",
    "What is the function of a CPU?",
    "What is cloud computing?",
    "What is markdown?",
    "What is git?",
    "What is a terminal emulator?",
    "Summarize what Cortex is.",
]

def main():
    print(f"Starting 20 consecutive live requests against local Ollama qwen3.5:9b...\n")
    orch = CortexOrchestrator(dry_run=True)
    assert orch.model_provider == "ollama"
    assert orch.model_name == "qwen3.5:9b"

    latencies = []
    for i, q in enumerate(questions, 1):
        t0 = time.time()
        res = orch.chat(q)
        dt = (time.time() - t0) * 1000
        latencies.append(dt)
        msg = res.get("message", "")
        
        assert len(msg) > 0, f"Req {i}: Empty message"
        assert "Cortex's local AI engine is unavailable" not in msg, f"Req {i}: AI engine unavailable error!"
        assert "<think>" not in msg, f"Req {i}: <think> tag leaked"
        assert "</think>" not in msg, f"Req {i}: </think> tag leaked"
        assert "gemini" not in msg.lower(), f"Req {i}: Gemini referenced"
        
        snippet = msg.replace("\n", " ")[:70]
        print(f"[{i:02d}/20] ({dt:.0f}ms) Q: {q} -> A: {snippet}...")

    avg_lat = sum(latencies) / len(latencies)
    print(f"\nSUCCESS: All 20/20 consecutive requests passed!")
    print(f"Min latency: {min(latencies):.0f}ms | Max: {max(latencies):.0f}ms | Avg: {avg_lat:.0f}ms")

if __name__ == "__main__":
    main()
