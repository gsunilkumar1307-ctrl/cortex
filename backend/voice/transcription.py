from __future__ import annotations

import io
import os
import sys
import wave
from pathlib import Path
from typing import Any, Optional

try:
    import speech_recognition as sr
except ImportError:
    sr = None


def is_audio_silent(wav_bytes: bytes, threshold: int = 350) -> bool:
    """Checks whether the WAV audio has sufficient energy to contain human speech."""
    if not wav_bytes or len(wav_bytes) < 44:
        return True
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            if not frames:
                return True
            try:
                import audioop
                rms = audioop.rms(frames, wf.getsampwidth())
                return rms < threshold
            except Exception:
                # If audioop is unavailable in future Python versions, calculate RMS manually
                import struct
                sampwidth = wf.getsampwidth()
                if sampwidth == 2:
                    count = len(frames) // 2
                    if count == 0:
                        return True
                    shorts = struct.unpack(f"<{count}h", frames)
                    sum_sq = sum(s * s for s in shorts)
                    rms = int((sum_sq / count) ** 0.5)
                    return rms < threshold
                return False
    except Exception:
        return False


class VoiceTranscriber:
    """
    Multilingual voice transcription engine for Cortex.
    Supports Kannada, Hindi, Tamil, Telugu, English, and code-mixed speech.
    Uses Gemini Multimodal Audio STT when available, with resilient Google
    SpeechRecognition fallback and energy-based silence suppression.
    """

    LANGUAGE_BCP_MAP = {
        "kn": "kn-IN",
        "hi": "hi-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "en": "en-US",
    }

    def __init__(self, silence_threshold: int = 350) -> None:
        self.silence_threshold = silence_threshold

    def is_silent(self, audio_bytes: bytes) -> bool:
        return is_audio_silent(audio_bytes, threshold=self.silence_threshold)

    def transcribe(
        self,
        audio_bytes: bytes,
        gemini_model: Any = None,
        preferred_lang: Optional[str] = None,
    ) -> str:
        """
        Transcribe audio bytes.
        Returns the recognized text string, or empty string if silent/unintelligible.
        """
        if not audio_bytes or len(audio_bytes) < 200:
            return ""

        if self.is_silent(audio_bytes):
            return ""

        # 1. Try Gemini Multimodal STT
        if gemini_model is not None:
            try:
                part = {
                    "mime_type": "audio/wav",
                    "data": audio_bytes,
                }
                prompt = (
                    "Listen carefully to this voice recording and transcribe the speech verbatim.\n"
                    "RULES:\n"
                    "- Output ONLY the exact spoken words in their spoken language script (Kannada script for Kannada, "
                    "Devanagari for Hindi, Tamil script for Tamil, Telugu script for Telugu, or English for English).\n"
                    "- If the user mixed languages (e.g. Kanglish or Hinglish), capture their spoken words accurately.\n"
                    "- If the recording is completely silent or background noise with no speech, reply with SILENCE.\n"
                    "- Do NOT output any quotation marks, markdown, preamble, or timestamps."
                )
                resp = gemini_model.generate_content([prompt, part])
                raw_text = ""
                if resp and getattr(resp, "candidates", None):
                    for cand in resp.candidates:
                        if cand.content and cand.content.parts:
                            for p in cand.content.parts:
                                if hasattr(p, "text") and p.text:
                                    raw_text += p.text
                raw_text = raw_text.strip().strip('"\'')
                if raw_text and raw_text.upper() != "SILENCE":
                    return raw_text
            except Exception as e:
                print(f"[cortex voice] Gemini transcription error: {e}", file=sys.stderr)

        # 2. Resilient fallback to SpeechRecognition
        if sr is not None:
            lang_code = self.LANGUAGE_BCP_MAP.get((preferred_lang or "").lower().strip(), "en-US")
            try:
                r = sr.Recognizer()
                with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
                    audio = r.record(source)

                # Try target language first if specified and non-English
                if lang_code != "en-US":
                    try:
                        res = r.recognize_google(audio, language=lang_code).strip()
                        if res:
                            return res
                    except Exception:
                        pass

                # Fallback to English (or auto recognition)
                return r.recognize_google(audio, language="en-US").strip()
            except sr.UnknownValueError:
                return ""
            except Exception as e:
                print(f"[cortex voice] Speech recognition error: {e}", file=sys.stderr)
                return ""

        return ""

    def transcribe_file(
        self,
        audio_path: str | Path,
        gemini_model: Any = None,
        preferred_lang: Optional[str] = None,
    ) -> str:
        """Transcribe an audio file on disk."""
        path = Path(audio_path)
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        audio_bytes = path.read_bytes()
        return self.transcribe(audio_bytes, gemini_model=gemini_model, preferred_lang=preferred_lang)


_default_transcriber = VoiceTranscriber()


def transcribe_audio_multilingual(
    audio_bytes: bytes,
    gemini_model: Any = None,
    preferred_lang: Optional[str] = None,
) -> str:
    """Convenience function for transcribing audio bytes."""
    return _default_transcriber.transcribe(
        audio_bytes=audio_bytes,
        gemini_model=gemini_model,
        preferred_lang=preferred_lang,
    )


def transcribe_audio_placeholder(audio_path: str) -> str:
    """Backward compatibility facade for transcribe_audio_placeholder."""
    p = Path(audio_path)
    if not p.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    return _default_transcriber.transcribe_file(p)
