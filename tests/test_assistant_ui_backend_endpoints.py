from __future__ import annotations

import unittest
import os
import json
from unittest.mock import patch, MagicMock

# Ensure session secret is set for test authorization
os.environ["CORTEX_SESSION_SECRET"] = "test-session-secret-for-assistant-ui"

from backend.api.server import app
from starlette.testclient import TestClient


class TestAssistantUIBackendEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.auth_headers = {
            "X-Cortex-Session": "test-session-secret-for-assistant-ui"
        }

    def test_health_check(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))

    def test_threads_crud_lifecycle(self):
        thread_id = "test-thread-uuid-1234"
        # 1. Initially create thread
        payload = {
            "id": thread_id,
            "title": "AI Agent Research",
            "messages": [
                {"role": "user", "content": "Research autonomous desktop agents"},
                {"role": "assistant", "content": "Autonomous desktop agents operate locally on macOS..."},
            ],
            "metadata": {"lang": "en"}
        }
        res = self.client.post("/threads", json=payload, headers=self.auth_headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))
        self.assertEqual(res.json().get("title"), "AI Agent Research")

        # 2. List threads
        list_res = self.client.get("/threads", headers=self.auth_headers)
        self.assertEqual(list_res.status_code, 200)
        threads = list_res.json().get("threads", [])
        matched = [t for t in threads if t["id"] == thread_id]
        self.assertTrue(len(matched) > 0)
        self.assertEqual(matched[0]["title"], "AI Agent Research")
        self.assertEqual(matched[0]["messageCount"], 2)

        # 3. Get thread details
        get_res = self.client.get(f"/threads/{thread_id}", headers=self.auth_headers)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["thread"]["title"], "AI Agent Research")
        self.assertEqual(len(get_res.json()["thread"]["messages"]), 2)

        # 4. Rename thread
        rename_res = self.client.patch(f"/threads/{thread_id}", json={"title": "Updated Agent Research"}, headers=self.auth_headers)
        self.assertEqual(rename_res.status_code, 200)
        self.assertEqual(rename_res.json()["title"], "Updated Agent Research")

        # 5. Delete thread
        del_res = self.client.delete(f"/threads/{thread_id}", headers=self.auth_headers)
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json().get("ok"))

        # 6. Verify 404 after deletion
        get_after = self.client.get(f"/threads/{thread_id}", headers=self.auth_headers)
        self.assertEqual(get_after.status_code, 404)

    def test_chat_stream_sse_endpoint(self):
        with patch("backend.api.server.orchestrator.chat") as mock_chat:
            mock_chat.return_value = {
                "message": "Here is a streamed explanation of machine learning.",
                "task": {
                    "id": "mock-task-1",
                    "status": "completed",
                    "intent": "general_knowledge",
                    "language": "en"
                }
            }

            resp = self.client.post(
                "/chat/stream",
                json={"message": "Explain machine learning", "source": "text"},
                headers=self.auth_headers,
            )
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/event-stream", resp.headers.get("content-type", ""))

            content = resp.text
            self.assertIn("event: start", content)
            self.assertIn("event: text_delta", content)
            self.assertIn("event: task_update", content)
            self.assertIn("event: done", content)
            self.assertIn("streamed explanation", content)


if __name__ == "__main__":
    unittest.main()

