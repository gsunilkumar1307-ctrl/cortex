import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.api.server import app, _tts_cache


class TestVoiceTTSAndInterrupt(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _tts_cache.clear()

    def test_tts_empty_text_returns_400(self):
        res = self.client.get("/tts?text=")
        self.assertEqual(res.status_code, 400)

        res_space = self.client.get("/tts?text=   ")
        self.assertEqual(res_space.status_code, 400)

    @patch("urllib.request.urlopen")
    def test_tts_generation_and_caching(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"MPEG_AUDIO_CHUNK_BYTES"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        # First request generates and caches
        res1 = self.client.get("/tts?text=Hello+Cortex&lang=en")
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.headers["content-type"], "audio/mpeg")
        self.assertEqual(res1.content, b"MPEG_AUDIO_CHUNK_BYTES")
        self.assertEqual(mock_urlopen.call_count, 1)

        # Second identical request serves from cache without hitting urlopen again
        res2 = self.client.get("/tts?text=Hello+Cortex&lang=en")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.content, b"MPEG_AUDIO_CHUNK_BYTES")
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("urllib.request.urlopen")
    def test_tts_strips_markdown_and_code_blocks(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"CLEAN_SPEECH_AUDIO"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        markdown_text = "**Bold heading** and `code inline` ```hidden python code``` with https://example.com URL"
        res = self.client.get(f"/tts?text={markdown_text}&lang=en")
        self.assertEqual(res.status_code, 200)

        # Inspect the URL called by urlopen to ensure code and markdown characters were stripped
        called_req = mock_urlopen.call_args[0][0]
        called_url = called_req.full_url
        self.assertNotIn("```", called_url)
        self.assertNotIn("example.com", called_url)

    @patch("urllib.request.urlopen")
    def test_tts_multilingual_language_support(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"KANNADA_AUDIO"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        res = self.client.get("/tts?text=ನಮಸ್ಕಾರ&lang=kn")
        self.assertEqual(res.status_code, 200)
        called_req = mock_urlopen.call_args[0][0]
        self.assertIn("tl=kn", called_req.full_url)


if __name__ == "__main__":
    unittest.main()
