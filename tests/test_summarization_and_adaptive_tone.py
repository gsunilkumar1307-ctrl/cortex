import os
import sys
import unittest
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.agent.orchestrator import CortexOrchestrator
from backend.core.adaptive_tone import (
    ToneMode,
    detect_adaptive_tone,
    apply_tone_to_prompt,
    AdaptiveToneContext,
)


from backend.persistence import EncryptedMemoryStore


class TestSummarizationAndAdaptiveTone(unittest.TestCase):
    def setUp(self):
        self.orchestrator = CortexOrchestrator(
            memory=EncryptedMemoryStore(":memory:"),
            use_gemini=False
        )
        self.orchestrator.history = []

    def test_conversation_summarization_empty(self):
        summary = self.orchestrator._summarize_conversation_history("en")
        self.assertIn("just started", summary.lower())

    def test_conversation_summarization_with_history(self):
        self.orchestrator.history = [
            {"role": "user", "parts": ["What is quantum computing?"]},
            {"role": "model", "parts": ["Quantum computing utilizes qubits for superposition."]},
            {"role": "user", "parts": ["Can it break RSA encryption?"]},
            {"role": "model", "parts": ["Shor's algorithm theoretically can."]}
        ]
        summary = self.orchestrator._summarize_conversation_history("en")
        self.assertTrue(len(summary) > 10)
        self.assertTrue("User:" in summary or "quantum" in summary.lower() or "recap" in summary.lower())

    def test_document_summarization_text(self):
        doc_text = "Project Apollo was the third United States human spaceflight program carried out by NASA."
        summary = self.orchestrator._summarize_document(doc_text, "en")
        self.assertTrue(len(summary) > 10)
        self.assertTrue("Apollo" in summary or "Document Summary" in summary)

    def test_document_summarization_local_file(self):
        test_file = Path(__file__).resolve().parent / "test_contracts.py"
        summary = self.orchestrator._summarize_document(str(test_file), "en")
        self.assertTrue(len(summary) > 10)
        self.assertTrue("test" in summary.lower() or "document" in summary.lower())

    def test_adaptive_tone_detection(self):
        urgent = detect_adaptive_tone("I need this ASAP, hurry up!")
        self.assertEqual(urgent.mode, ToneMode.URGENT)

        concise = detect_adaptive_tone("Keep it short, just the answer.")
        self.assertEqual(concise.mode, ToneMode.CONCISE_DIRECT)

        stressed = detect_adaptive_tone("I am completely stuck and feeling overwhelmed.")
        self.assertEqual(stressed.mode, ToneMode.EMPATHETIC)

        warm = detect_adaptive_tone("Good morning, thank you so much for your help!")
        self.assertEqual(warm.mode, ToneMode.WARM_PROFESSIONAL)

    def test_apply_tone_to_prompt(self):
        base_prompt = "You are Cortex."
        tone_ctx = detect_adaptive_tone("Be concise and give me a brief reply.")
        prompt_with_tone = apply_tone_to_prompt(base_prompt, tone_ctx)
        self.assertIn("brevity", prompt_with_tone.lower())

    def test_general_question_routes_to_summary(self):
        self.orchestrator.history = [
            {"role": "user", "parts": ["Hello Cortex"]},
            {"role": "model", "parts": ["Hello friend!"]}
        ]
        answer = self.orchestrator._answer_general_question("Can you summarize our conversation?", "en")
        self.assertTrue(len(answer) > 10)
        self.assertTrue("recap" in answer.lower() or "overview" in answer.lower() or "User:" in answer)


if __name__ == "__main__":
    unittest.main()
