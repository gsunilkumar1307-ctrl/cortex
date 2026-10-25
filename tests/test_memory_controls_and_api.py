import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from backend.persistence.encrypted_store import EncryptedMemoryStore
from backend.agent.orchestrator import CortexOrchestrator
from backend.capabilities import DeviceAutomation
from backend.api.server import app, orchestrator


class TestMemoryControlsAndAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "test-memory.sqlite3")
        self.store = EncryptedMemoryStore(self.db_path)
        self.client = TestClient(app)

    def test_store_put_get_update_delete(self):
        # 1. Put
        self.store.put("user_role", "preference", {"title": "Software Architect"})
        item = self.store.get("user_role")
        self.assertEqual(item, {"title": "Software Architect"})

        # 2. Update
        updated = self.store.update("user_role", {"title": "Principal Architect"})
        self.assertTrue(updated)
        item2 = self.store.get("user_role")
        self.assertEqual(item2, {"title": "Principal Architect"})

        # 3. List
        all_items = self.store.list()
        self.assertEqual(len(all_items), 1)
        self.assertEqual(all_items[0]["id"], "user_role")

        # 4. Delete
        deleted = self.store.delete("user_role")
        self.assertTrue(deleted)
        self.assertIsNone(self.store.get("user_role"))

        # Delete non-existent
        self.assertFalse(self.store.delete("non_existent"))

    def test_store_clear_all_and_filtered(self):
        self.store.put("pref1", "preference", {"val": 1})
        self.store.put("pref2", "preference", {"val": 2})
        self.store.put("fact1", "fact", {"val": 3})

        self.assertEqual(len(self.store.list()), 3)

        # Clear only facts
        cleared_facts = self.store.clear(kind="fact")
        self.assertEqual(cleared_facts, 1)
        self.assertEqual(len(self.store.list()), 2)

        # Clear remaining
        cleared_all = self.store.clear()
        self.assertEqual(cleared_all, 2)
        self.assertEqual(len(self.store.list()), 0)

    def test_api_memory_crud_endpoints(self):
        # POST /memory
        res = self.client.post("/memory", json={
            "id": "email_signoff",
            "kind": "preference",
            "payload": {"text": "Best regards,\nSunil"}
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))

        # GET /memory
        res_get = self.client.get("/memory")
        self.assertEqual(res_get.status_code, 200)
        items = res_get.json().get("items", [])
        self.assertTrue(any(i["id"] == "email_signoff" for i in items))

        # DELETE /memory/{id}
        res_del = self.client.delete("/memory/email_signoff")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json().get("ok"))

        # DELETE 404 for deleted memory
        res_del_404 = self.client.delete("/memory/email_signoff")
        self.assertEqual(res_del_404.status_code, 404)

    def test_api_session_clear_endpoint(self):
        res = self.client.post("/session/clear")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json().get("ok"))


if __name__ == "__main__":
    unittest.main()
