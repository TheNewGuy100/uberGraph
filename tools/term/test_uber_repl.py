"""Tests for uber_repl.py with a fake bridge (no game needed). Run: python tools/term/test_uber_repl.py"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uber_repl as ur  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_commands(self):
        self.assertEqual(ur.parse_line("   "), ("empty",))
        self.assertEqual(ur.parse_line("help"), ("help",))
        self.assertEqual(ur.parse_line("EXIT"), ("quit",))
        self.assertEqual(ur.parse_line("health"), ("health",))
        self.assertEqual(ur.parse_line("settings"), ("settings",))

    def test_aliases_and_passthrough(self):
        self.assertEqual(ur.parse_line("cvar r.ScreenPercentage"), ("op", "cvar_get", ["r.ScreenPercentage"]))
        self.assertEqual(ur.parse_line("console stat fps"), ("op", "console_exec", ["stat", "fps"]))
        self.assertEqual(ur.parse_line("find_all PlayerController 5"), ("op", "find_all", ["PlayerController", "5"]))


class FormatTest(unittest.TestCase):
    def test_ok_result_is_indented_json(self):
        self.assertIn('"float": 100', ur.format_response({"ok": True, "result": {"float": 100}}))

    def test_error_plain_has_no_escape_characters(self):
        text = ur.format_response({"ok": False, "error": "boom"}, color=False)
        self.assertNotIn("\x1b", text)
        self.assertIn("ERROR boom", text)

    def test_disabled_error_explains_the_rule(self):
        text = ur.format_response({"ok": False, "error": "console_exec is disabled (allow_console is not true)"})
        self.assertIn("off by default", text)
        self.assertIn("--user-approved", text)


class ExecuteTest(unittest.TestCase):
    def run_line(self, line, send=None, color=False):
        send = send or (lambda op, words: {"ok": True, "result": {"op": op, "words": words}})
        return ur.execute(ur.parse_line(line), send, lambda: {"alive": True}, lambda: "{}", color)

    def test_quit_returns_none(self):
        self.assertIsNone(self.run_line("quit"))

    def test_op_goes_to_the_bridge_with_its_words(self):
        text = self.run_line("cvar r.Shadow.MaxResolution")
        self.assertIn('"op": "cvar_get"', text)
        self.assertIn("r.Shadow.MaxResolution", text)

    def test_missing_heartbeat_keeps_the_prompt_alive(self):
        def send(op, words):
            raise SystemExit("no recent heartbeat (never written): is the game running?")
        self.assertIn("no recent heartbeat", self.run_line("ping", send))

    def test_unexpected_exception_is_reported_not_raised(self):
        def send(op, words):
            raise ValueError("bad")
        self.assertIn("ValueError", self.run_line("ping", send))


class LoopTest(unittest.TestCase):
    def test_loop_runs_until_quit(self):
        lines = iter(["help", "cvar r.X", "quit"])

        class Fake:
            pass

        out = io.StringIO()
        # run() builds the bridge client from the profile; the loop itself is covered here through execute()
        seen = []
        for line in lines:
            text = ur.execute(ur.parse_line(line), lambda op, w: {"ok": True, "result": [op] + w}, lambda: {}, lambda: "{}")
            if text is None:
                break
            seen.append(text)
        self.assertEqual(len(seen), 2)
        self.assertIn("help", seen[0].lower())
        self.assertIn("cvar_get", seen[1])


if __name__ == "__main__":
    unittest.main()
