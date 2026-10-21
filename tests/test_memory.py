import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "memory-service"))

from cortex_memory import EncryptedMemoryStore


class MemoryTests(unittest.TestCase):
    def test_memory_roundtrip_is_encrypted(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "memory.sqlite3"
            store = EncryptedMemoryStore(str(db_path))
            store.put("one", "task", {"secret": "value"})

            self.assertEqual(store.get("one"), {"secret": "value"})
            self.assertNotIn(b"value", db_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
