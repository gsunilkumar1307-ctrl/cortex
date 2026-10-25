import unittest
from backend.core.direct_answers import resolve_direct_answer, clean_search_response
from backend.agent.orchestrator import CortexOrchestrator


class TestDirectAnswers(unittest.TestCase):
    def test_world_time_usa(self):
        res = resolve_direct_answer("what is the time in USA now?")
        self.assertIsNotNone(res)
        self.assertIn("Eastern Time", res)
        self.assertIn("Pacific Time", res)
        self.assertIn("Central Time", res)
        self.assertIn("Mountain Time", res)

    def test_world_time_cities(self):
        res_india = resolve_direct_answer("what time is it in India?")
        self.assertIsNotNone(res_india)
        self.assertIn("India", res_india)

        res_london = resolve_direct_answer("what time is it in London?")
        self.assertIsNotNone(res_london)
        self.assertIn("London", res_london)

    def test_current_date(self):
        res = resolve_direct_answer("what is today's date?")
        self.assertIsNotNone(res)
        self.assertIn("Today is", res)

    def test_clean_search_response(self):
        raw = "Now That&#039;s What I Call Music! &quot;What Time Is Love?&quot; &amp; more"
        cleaned = clean_search_response(raw)
        self.assertEqual(cleaned, "Now That's What I Call Music! \"What Time Is Love?\" & more")

    def test_orchestrator_chat_resolves_direct_answer(self):
        orc = CortexOrchestrator(use_gemini=False)
        chat_res = orc.chat("what is the time in USA now?")
        self.assertEqual(chat_res["task"]["status"], "completed")
        self.assertIn("Eastern Time", chat_res["message"])
        self.assertIn("Pacific Time", chat_res["message"])


if __name__ == "__main__":
    unittest.main()
