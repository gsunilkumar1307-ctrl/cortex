import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared-sdk" / "python"))

from cortex_sdk import TaskCommand, command_from_intent


class ContractTests(unittest.TestCase):
    def test_command_detection(self):
        self.assertEqual(command_from_intent("open calculator"), TaskCommand.OPEN_APP)
        self.assertEqual(command_from_intent("close calculator"), TaskCommand.CLOSE_APP)
        self.assertEqual(command_from_intent("quit Notes"), TaskCommand.CLOSE_APP)
        self.assertEqual(command_from_intent("switch to Notes"), TaskCommand.FOCUS_APP)
        self.assertEqual(command_from_intent("type hello"), TaskCommand.TYPE_TEXT)
        self.assertEqual(command_from_intent("press command s"), TaskCommand.KEYSTROKE)
        self.assertEqual(command_from_intent("choose New from File menu in Notes"), TaskCommand.MENU_ITEM)
        self.assertEqual(command_from_intent("write note buy milk"), TaskCommand.WRITE_NOTE)
        self.assertEqual(command_from_intent("send message to Sam saying hello"), TaskCommand.SEND_MESSAGE)
        self.assertEqual(command_from_intent("calculate 2 plus 2"), TaskCommand.CALCULATE)
        self.assertEqual(command_from_intent("what is 9 times 8"), TaskCommand.CALCULATE)
        self.assertEqual(command_from_intent("take a screenshot"), TaskCommand.SCREENSHOT)
        self.assertEqual(command_from_intent("restart my computer"), TaskCommand.RESTART)
        self.assertEqual(command_from_intent("read clipboard"), TaskCommand.CLIPBOARD_READ)


if __name__ == "__main__":
    unittest.main()
