import io
import struct
import tempfile
import wave
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.voice.transcription import (
    VoiceTranscriber,
    is_audio_silent,
    transcribe_audio_multilingual,
    transcribe_audio_placeholder,
)


def _generate_wav(duration_sec=0.5, sample_rate=16000, amplitude=1000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        num_frames = int(duration_sec * sample_rate)
        # Alternate amplitude
        frames = bytearray()
        for i in range(num_frames):
            val = amplitude if (i // 10) % 2 == 0 else -amplitude
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


class TestSiriVoiceAndTranscription(unittest.TestCase):
    def setUp(self):
        self.transcriber = VoiceTranscriber(silence_threshold=300)

    def test_silence_detection_empty_or_short(self):
        self.assertTrue(is_audio_silent(b""))
        self.assertTrue(is_audio_silent(b"too-short"))
        self.assertTrue(self.transcriber.is_silent(b""))

    def test_silence_detection_quiet_wav(self):
        quiet_wav = _generate_wav(duration_sec=0.2, amplitude=50)
        self.assertTrue(is_audio_silent(quiet_wav, threshold=300))
        self.assertTrue(self.transcriber.is_silent(quiet_wav))

    def test_silence_detection_loud_wav(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        self.assertFalse(is_audio_silent(loud_wav, threshold=300))
        self.assertFalse(self.transcriber.is_silent(loud_wav))

    def test_transcribe_silent_returns_empty(self):
        quiet_wav = _generate_wav(duration_sec=0.2, amplitude=20)
        res = self.transcriber.transcribe(quiet_wav)
        self.assertEqual(res, "")

    def test_gemini_multimodal_transcription_success(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        mock_gemini = MagicMock()
        mock_candidate = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "ಇನ್ಬಾಕ್ಸ್ ನೋಡು"  # Kannada: Look at inbox
        mock_candidate.content.parts = [mock_part]
        mock_gemini.generate_content.return_value = MagicMock(candidates=[mock_candidate])

        res = self.transcriber.transcribe(loud_wav, gemini_model=mock_gemini)
        self.assertEqual(res, "ಇನ್ಬಾಕ್ಸ್ ನೋಡು")

    def test_gemini_multimodal_silence_fallback(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        mock_gemini = MagicMock()
        mock_candidate = MagicMock()
        mock_part = MagicMock()
        mock_part.text = "SILENCE"
        mock_candidate.content.parts = [mock_part]
        mock_gemini.generate_content.return_value = MagicMock(candidates=[mock_candidate])

        with patch("speech_recognition.Recognizer") as mock_sr:
            instance = mock_sr.return_value
            instance.recognize_google.return_value = "hello cortex"
            res = self.transcriber.transcribe(loud_wav, gemini_model=mock_gemini)
            self.assertEqual(res, "hello cortex")

    def test_speech_recognition_fallback_when_gemini_fails(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        mock_gemini = MagicMock()
        mock_gemini.generate_content.side_effect = RuntimeError("API Quota exceeded")

        with patch("speech_recognition.Recognizer") as mock_sr:
            instance = mock_sr.return_value
            instance.recognize_google.return_value = "summarize my emails"
            res = self.transcriber.transcribe(loud_wav, gemini_model=mock_gemini, preferred_lang="en")
            self.assertEqual(res, "summarize my emails")

    def test_transcribe_file_success(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(loud_wav)
            tmp_path = tmp.name

        try:
            with patch("speech_recognition.Recognizer") as mock_sr:
                instance = mock_sr.return_value
                instance.recognize_google.return_value = "open terminal"
                res = self.transcriber.transcribe_file(tmp_path)
                self.assertEqual(res, "open terminal")
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_transcribe_audio_placeholder_backward_compatibility(self):
        loud_wav = _generate_wav(duration_sec=0.2, amplitude=2500)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(loud_wav)
            tmp_path = tmp.name

        try:
            with patch("speech_recognition.Recognizer") as mock_sr:
                instance = mock_sr.return_value
                instance.recognize_google.return_value = "draft mail to professor"
                res = transcribe_audio_placeholder(tmp_path)
                self.assertEqual(res, "draft mail to professor")
        finally:
            Path(tmp_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
