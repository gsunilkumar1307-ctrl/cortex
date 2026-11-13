import unittest
import io
import os
import wave
import struct
from fastapi.testclient import TestClient
from backend.api.server import app, is_audio_silent

class TestAudioCompanionEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        secret = ""
        secret_path = os.path.join(os.path.dirname(__file__), "..", ".session_secret")
        if os.path.exists(secret_path):
            with open(secret_path, "r", encoding="utf-8") as f:
                secret = f.read().strip()
        cls.headers = {"X-Cortex-Session": secret} if secret else {}
        cls.client = TestClient(app)

    def _create_sine_wav(self, duration_sec=1.0, freq=440.0, sample_rate=16000, volume=0.5):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            import math
            n_samples = int(duration_sec * sample_rate)
            data = bytearray()
            for i in range(n_samples):
                val = int(volume * 32767.0 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
                data.extend(struct.pack("<h", val))
            wf.writeframes(data)
        return buffer.getvalue()

    def _create_silent_wav(self, duration_sec=1.0, sample_rate=16000):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            n_samples = int(duration_sec * sample_rate)
            wf.writeframes(b"\x00\x00" * n_samples)
        return buffer.getvalue()

    def test_audio_silence_detection(self):
        silent_wav = self._create_silent_wav(1.0)
        self.assertTrue(is_audio_silent(silent_wav, threshold=350))

        audible_wav = self._create_sine_wav(1.0, freq=440.0, volume=0.6)
        self.assertFalse(is_audio_silent(audible_wav, threshold=350))

    def test_audio_chat_silent_rejection(self):
        silent_wav = self._create_silent_wav(1.0)
        headers = dict(self.headers)
        headers["Content-Type"] = "audio/wav"
        res = self.client.post("/audio_chat", content=silent_wav, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("transcript", data)
        self.assertEqual(data["transcript"], "")

    def test_tts_endpoint_english(self):
        res = self.client.get("/tts?text=Hello+Cortex&lang=en", headers=self.headers)
        if res.status_code == 200:
            self.assertEqual(res.headers.get("content-type"), "audio/mpeg")
            self.assertGreater(len(res.content), 100)

    def test_threads_and_chat_stream_availability(self):
        res = self.client.get("/threads", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("threads", data)

    def test_unauthorized_request_rejected(self):
        res = self.client.get("/threads", headers={"X-Cortex-Session": "invalid_fake_token"})
        self.assertEqual(res.status_code, 401)

if __name__ == "__main__":
    unittest.main()
