import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.capabilities import classify_command
from backend.core.contracts import RiskLevel, TaskCommand


class SafetyTests(unittest.TestCase):
    def test_shutdown_requires_approval(self):
        risk, approval, reason = classify_command(TaskCommand.SHUTDOWN, "shutdown")
        self.assertEqual(risk, RiskLevel.HIGH)
        self.assertTrue(approval)
        self.assertIsNotNone(reason)

    def test_payment_is_blocked(self):
        risk, approval, reason = classify_command(TaskCommand.OPEN_APP, "buy this with payment")
        self.assertEqual(risk, RiskLevel.BLOCKED)
        self.assertFalse(approval)
        self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()
