"""
test_phase6_language.py — Phase 6 Language Detection & Multilingual Response Tests

Tests:
  1. Native-script Unicode detection (Kannada, Hindi, Tamil, Telugu)
  2. Romanized keyword detection (mixed Indian-English text)
  3. Pure English → en
  4. LanguageCode enum helper methods
  5. language_instruction() returns the right snippet per language
  6. Orchestrator tags Task.language correctly (no Gemini)
  7. Gemini response path passes the lang_code (mocked)
  8. Email commands still work normally when in non-English mode
"""
from __future__ import annotations

import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── bootstrap Python path ─────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "shared-sdk", "python"))
sys.path.insert(0, os.path.join(_ROOT, "cloud-brain", "app"))
sys.path.insert(0, os.path.join(_ROOT, "automation-engine"))
sys.path.insert(0, os.path.join(_ROOT, "memory-service", "python"))
sys.path.insert(0, os.path.join(_ROOT, "memory-service"))

from language_detector import (
    detect_language,
    detect_language_fast,
    language_instruction,
)
from cortex_sdk import LanguageCode


# ─────────────────────────────────────────────────────────────────────────────
# 1. Native-script Unicode detection
# ─────────────────────────────────────────────────────────────────────────────
class TestNativeScriptDetection(unittest.TestCase):
    """Unicode block heuristic should instantly identify Indic scripts."""

    def test_kannada_native(self):
        # ಮೇಲ್ ಚೆಕ್ ಮಾಡಿ
        text = "\u0CAE\u0CC7\u0CB2\u0CCD \u0C9A\u0CC6\u0C95\u0CCD \u0CAE\u0CBE\u0CA1\u0CBF"
        self.assertEqual(detect_language_fast(text), "kn")

    def test_hindi_native(self):
        # मेल चेक करो
        text = "\u092E\u0947\u0932 \u091A\u0947\u0915 \u0915\u0930\u094B"
        self.assertEqual(detect_language_fast(text), "hi")

    def test_tamil_native(self):
        # மெயில் பாரு
        text = "\u0BAE\u0BC6\u0BAF\u0BBF\u0BB2\u0BCD \u0BAA\u0BBE\u0BB0\u0BC1"
        self.assertEqual(detect_language_fast(text), "ta")

    def test_telugu_native(self):
        # మెయిల్ చెక్ చేయి
        text = "\u0C2E\u0C46\u0C2F\u0C3F\u0C32\u0C4D \u0C1A\u0C46\u0C15\u0C4D \u0C1A\u0C47\u0C2F\u0C3F"
        self.assertEqual(detect_language_fast(text), "te")

    def test_english_returns_en(self):
        self.assertEqual(detect_language_fast("Open Safari browser"), "en")

    def test_empty_returns_en(self):
        self.assertEqual(detect_language_fast(""), "en")

    def test_whitespace_returns_en(self):
        self.assertEqual(detect_language_fast("   "), "en")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Romanized keyword detection (transliterated Indian languages)
# ─────────────────────────────────────────────────────────────────────────────
class TestRomanizedDetection(unittest.TestCase):
    """Romanized Indic keywords must be detected without native characters."""

    def test_romanized_kannada_mail(self):
        self.assertEqual(detect_language_fast("mail check maadu"), "kn")

    def test_romanized_kannada_general(self):
        self.assertEqual(detect_language_fast("enu maadu"), "kn")

    def test_romanized_hindi_mail(self):
        self.assertEqual(detect_language_fast("inbox dekho aur mail bhejo"), "hi")

    def test_romanized_hindi_general(self):
        self.assertEqual(detect_language_fast("kya hain yeh"), "hi")

    def test_romanized_tamil_mail(self):
        self.assertEqual(detect_language_fast("mail anuppu pannunga"), "ta")

    def test_romanized_tamil_general(self):
        self.assertEqual(detect_language_fast("romba nalla iruku"), "ta")

    def test_romanized_telugu_mail(self):
        self.assertEqual(detect_language_fast("mail cheyyi"), "te")

    def test_romanized_telugu_general(self):
        self.assertEqual(detect_language_fast("cheppu ela cheyandi"), "te")


# ─────────────────────────────────────────────────────────────────────────────
# 3. LanguageCode enum helpers
# ─────────────────────────────────────────────────────────────────────────────
class TestLanguageCodeEnum(unittest.TestCase):
    def test_from_string_valid(self):
        self.assertEqual(LanguageCode.from_string("kn"), LanguageCode.KANNADA)
        self.assertEqual(LanguageCode.from_string("hi"), LanguageCode.HINDI)
        self.assertEqual(LanguageCode.from_string("ta"), LanguageCode.TAMIL)
        self.assertEqual(LanguageCode.from_string("te"), LanguageCode.TELUGU)
        self.assertEqual(LanguageCode.from_string("en"), LanguageCode.ENGLISH)

    def test_from_string_invalid_returns_auto(self):
        self.assertEqual(LanguageCode.from_string("zz"), LanguageCode.AUTO)
        self.assertEqual(LanguageCode.from_string(""), LanguageCode.AUTO)

    def test_display_names_present(self):
        for lang in LanguageCode:
            # display_name should always be a non-empty string
            self.assertIsInstance(lang.display_name, str)
            self.assertTrue(len(lang.display_name) > 0)

    def test_auto_display_name(self):
        self.assertEqual(LanguageCode.AUTO.display_name, "Auto-detect")


# ─────────────────────────────────────────────────────────────────────────────
# 4. language_instruction() helper
# ─────────────────────────────────────────────────────────────────────────────
class TestLanguageInstruction(unittest.TestCase):
    def test_english_instruction_is_empty(self):
        self.assertEqual(language_instruction("en"), "")

    def test_kannada_instruction_non_empty(self):
        instr = language_instruction("kn")
        self.assertTrue(len(instr) > 10)
        self.assertIn("Kannada", instr)

    def test_hindi_instruction_non_empty(self):
        instr = language_instruction("hi")
        self.assertIn("Hindi", instr)

    def test_tamil_instruction_non_empty(self):
        instr = language_instruction("ta")
        self.assertIn("Tamil", instr)

    def test_telugu_instruction_non_empty(self):
        instr = language_instruction("te")
        self.assertIn("Telugu", instr)

    def test_unknown_code_returns_empty_string(self):
        self.assertEqual(language_instruction("xx"), "")


# ─────────────────────────────────────────────────────────────────────────────
# 5. detect_language() with mocked Gemini (Gemini path)
# ─────────────────────────────────────────────────────────────────────────────
class TestDetectLanguageWithGemini(unittest.TestCase):
    def test_gemini_called_for_ambiguous_english(self):
        """When heuristic returns 'en', Gemini should be attempted if available."""
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "kn"
        mock_model.generate_content.return_value = mock_resp

        result = detect_language("open my email", gemini_model=mock_model)
        # Gemini returned kn → should trust it
        self.assertEqual(result, "kn")
        mock_model.generate_content.assert_called_once()

    def test_gemini_returns_invalid_falls_back_to_en(self):
        """If Gemini returns garbage, fall back to heuristic result (en)."""
        mock_model = MagicMock()
        mock_resp = MagicMock()
        mock_resp.text = "UNKNOWN_LANG"
        mock_model.generate_content.return_value = mock_resp

        result = detect_language("open my email", gemini_model=mock_model)
        self.assertEqual(result, "en")

    def test_gemini_exception_falls_back_to_en(self):
        """If Gemini raises, gracefully fall back to heuristic."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("API error")

        result = detect_language("open my email", gemini_model=mock_model)
        self.assertEqual(result, "en")

    def test_native_script_skips_gemini(self):
        """Native script detected instantly — Gemini should NOT be called."""
        mock_model = MagicMock()
        # Kannada native: ಮೇಲ್ ಚೆಕ್
        text = "\u0CAE\u0CC7\u0CB2\u0CCD \u0C9A\u0CC6\u0C95\u0CCD"
        result = detect_language(text, gemini_model=mock_model)
        self.assertEqual(result, "kn")
        mock_model.generate_content.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Orchestrator tags Task.language correctly (no Gemini)
# ─────────────────────────────────────────────────────────────────────────────
class TestOrchestratorLanguageTagging(unittest.TestCase):
    def _make_orch(self):
        from orchestrator import CortexOrchestrator
        from cortex_automation import DeviceAutomation
        from cortex_memory import EncryptedMemoryStore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(tmp.name) / "mem.sqlite3"))
        return CortexOrchestrator(
            automation=DeviceAutomation(dry_run=True),
            memory=memory,
            use_gemini=False,
        )

    def test_english_task_tagged_en(self):
        orch = self._make_orch()
        result = orch.chat("open Safari")
        lang = result["task"]["language"]
        self.assertEqual(lang, "en")

    def test_kannada_romanized_task_tagged_kn(self):
        orch = self._make_orch()
        result = orch.chat("mail check maadu")
        lang = result["task"]["language"]
        self.assertEqual(lang, "kn")

    def test_hindi_romanized_task_tagged_hi(self):
        orch = self._make_orch()
        result = orch.chat("inbox dekho")
        lang = result["task"]["language"]
        self.assertEqual(lang, "hi")

    def test_tamil_romanized_task_tagged_ta(self):
        orch = self._make_orch()
        result = orch.chat("mail anuppu pannunga")
        lang = result["task"]["language"]
        self.assertEqual(lang, "ta")

    def test_telugu_romanized_task_tagged_te(self):
        orch = self._make_orch()
        result = orch.chat("mail cheyyi")
        lang = result["task"]["language"]
        self.assertEqual(lang, "te")

    def test_language_event_logged_for_non_english(self):
        """Non-English inputs should generate a language_detected audit event."""
        orch = self._make_orch()
        result = orch.chat("mail check maadu")
        audit_types = [e["type"] for e in result["task"]["auditTrail"]]
        self.assertIn("language_detected", audit_types)

    def test_no_language_event_for_english(self):
        """English inputs should NOT generate a language_detected audit event."""
        orch = self._make_orch()
        result = orch.chat("open Safari")
        audit_types = [e["type"] for e in result["task"]["auditTrail"]]
        self.assertNotIn("language_detected", audit_types)


class TestMultilingualResponses(unittest.TestCase):
    """Verify that Cortex produces authentic, native-language responses across Indic languages."""

    def _make_orch(self):
        from orchestrator import CortexOrchestrator
        from cortex_automation import DeviceAutomation
        from cortex_memory import EncryptedMemoryStore
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        memory = EncryptedMemoryStore(str(Path(tmp.name) / "mem.sqlite3"))
        return CortexOrchestrator(
            automation=DeviceAutomation(dry_run=True),
            memory=memory,
            use_gemini=False,
        )

    def test_kannada_greeting_response(self):
        orch = self._make_orch()
        res = orch.chat("ನಮಸ್ಕಾರ")
        self.assertIn("ಕಾರ್ಟೆಕ್ಸ್", res["message"])
        self.assertIn("ಸಹಾಯಕ", res["message"])

    def test_hindi_greeting_response(self):
        orch = self._make_orch()
        res = orch.chat("नमस्ते")
        self.assertIn("Cortex", res["message"])
        self.assertIn("असिस्टेंट", res["message"])

    def test_tamil_greeting_response(self):
        orch = self._make_orch()
        res = orch.chat("வணக்கம்")
        self.assertIn("வணக்கம்", res["message"])

    def test_telugu_greeting_response(self):
        orch = self._make_orch()
        res = orch.chat("నమస్కారం")
        self.assertIn("నమస్కారం", res["message"])

    def test_indic_identity_questions(self):
        orch = self._make_orch()
        res_kn = orch.chat("ನೀವು ಯಾರು?")
        self.assertIn("ಕಾರ್ಟೆಕ್ಸ್", res_kn["message"])
        res_hi = orch.chat("आप कौन हैं?")
        self.assertIn("Cortex", res_hi["message"])

    def test_indic_factual_knowledge_offline(self):
        orch = self._make_orch()
        res_hi = orch.chat("भारत की राजधानी क्या है?")
        self.assertIn("नई दिल्ली", res_hi["message"])
        res_kn = orch.chat("ಭಾರತದ ರಾಜಧಾನಿ ಯಾವುದು?")
        self.assertIn("ದೆಹಲಿ", res_kn["message"])

    def test_indic_open_app_response(self):
        orch = self._make_orch()
        res_kn = orch.chat("ಕ್ಯಾಲ್ಕುಲೇಟರ್ ತೆರೆ")
        self.assertEqual(res_kn["task"]["command"], "open_app")
        self.assertIn("ತೆರೆಯಲಾಗಿದೆ", res_kn["message"])

        res_hi = orch.chat("कैलकुलेटर खोलो")
        self.assertEqual(res_hi["task"]["command"], "open_app")
        self.assertIn("खोल दिया गया है", res_hi["message"])

    def test_indic_multi_turn_email_flow(self):
        orch = self._make_orch()
        # Turn 1: Bare email command
        res1 = orch.chat("ಇಮೇಲ್ ಕಳುಹಿಸು")
        self.assertEqual(res1["task"]["status"], "need_info")
        self.assertIn("ನೀವು ಯಾರಿಗೆ ಇಮೇಲ್ ಕಳುಹಿಸಲು ಬಯಸುತ್ತೀರಿ?", res1["message"])

        # Turn 2: Recipient
        res2 = orch.chat("ರಾಹುಲ್")
        self.assertIn("ರಾಹುಲ್ ಅವರಿಗೆ ಯಾವ ಸಂದೇಶವನ್ನು ಕಳುಹಿಸಬೇಕು?", res2["message"])

        # Turn 3: Content / Body
        res3 = orch.chat("ಪ್ರಾಜೆಕ್ಟ್ ಸಿದ್ಧವಾಗಿದೆ")
        self.assertIn("ಇಮೇಲ್ ಡ್ರಾಫ್ಟ್ ಸಿದ್ಧವಾಗಿದೆ", res3["message"])
        self.assertIn("ಕಳುಹಿಸುವುದೇ?", res3["message"])

        # Turn 4: Confirmation
        res4 = orch.chat("ಕಳುಹಿಸು")
        self.assertEqual(res4["task"]["status"], "completed")
        self.assertIn("ರಾಹುಲ್ ಅವರಿಗೆ ಇಮೇಲ್ ಕಳುಹಿಸಲಾಗಿದೆ.", res4["message"])


if __name__ == "__main__":
    unittest.main()
