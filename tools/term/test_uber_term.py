"""Tests for uber_term.py on made-up log lines and temporary files only. Run: python tools/term/test_uber_term.py"""
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uber_term as ut  # noqa: E402

STAMP = "[2026-10-28 00:10:56.1912600]"


class ClassifyTest(unittest.TestCase):
    def test_bridge_line(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] bridge: v0.1.3 ready")
        self.assertEqual((e["component"], e["section"], e["level"], e["text"]), ("bridge", "", "info", "v0.1.3 ready"))
        self.assertEqual(e["time"], "2026-10-28 00:10:56")

    def test_probes_section_and_level_word(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] Probes/chest: WARN no pawn (is a save loaded?)")
        self.assertEqual((e["component"], e["section"], e["level"], e["text"]), ("probes", "chest", "warn", "no pawn (is a save loaded?)"))

    def test_error_word_and_hints(self):
        self.assertEqual(ut.classify(STAMP + " [Lua] [uberGraph] bridge: ERROR boom")["level"], "error")
        self.assertEqual(ut.classify(STAMP + " [Lua] [Foo] attempt to call a nil value")["level"], "error")
        self.assertEqual(ut.classify(STAMP + " Access violation reading 0x10")["level"], "fatal")

    def test_property_dump_lines_are_not_errors(self):
        self.assertEqual(ut.classify(STAMP + " FArchiveState::ArIsError = 0x29")["level"], "info")

    def test_other_lua_mod_and_ue4ss_internal(self):
        self.assertEqual(ut.classify(STAMP + " [Lua] [VaultProbe] loaded")["component"], "other")
        self.assertEqual(ut.classify(STAMP + " [Lua] plain print")["component"], "lua")
        self.assertEqual(ut.classify(STAMP + " Starting mods")["component"], "ue4ss")

    def test_continuation_line(self):
        self.assertEqual(ut.classify("\t...\\Scripts\\main.lua:33: in function")["kind"], "cont")

    def test_plain_info_has_no_level_word_in_text(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] Probes: ready. Build. Bridge. Play.")
        self.assertEqual((e["component"], e["level"], e["text"]), ("probes", "info", "ready. Build. Bridge. Play."))


class NamedModTest(unittest.TestCase):
    def test_other_mod_keeps_its_name(self):
        e = ut.classify(STAMP + " [Lua] [RecipimaxXL] loaded; Num3 unlocks")
        self.assertEqual((e["component"], e["section"], e["text"]), ("other", "RecipimaxXL", "loaded; Num3 unlocks"))
        self.assertIn("RecipimaxXL", ut.paint(e, False))


class WrapTest(unittest.TestCase):
    def test_long_line_wraps_with_hanging_indent(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] bridge: " + "word " * 40)
        lines = ut.paint(e, False, 80).split("\n")
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(l.startswith(" " * (9 + ut.TAG_WIDTH + 1)) for l in lines[1:]))
        self.assertTrue(all(len(l) <= 80 for l in lines))


class PaintTest(unittest.TestCase):
    def test_no_color_has_no_escape_characters(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] Probes/chest: WARN no pawn")
        line = ut.paint(e, False)
        self.assertNotIn("\x1b", line)
        self.assertIn("WARN", line)
        self.assertIn("Probes/chest", line)

    def test_color_wraps_and_resets(self):
        e = ut.classify(STAMP + " [Lua] [uberGraph] bridge: ERROR boom")
        line = ut.paint(e, True)
        self.assertIn("\x1b[1;31m", line)
        self.assertTrue(line.endswith(ut.RESET))


class FilterTest(unittest.TestCase):
    def feed(self, flt, lines):
        return [ut.classify(STAMP + " " + l) if not l.startswith("\t") else ut.classify(l) for l in lines], [flt(ut.classify(STAMP + " " + l) if not l.startswith("\t") else ut.classify(l)) for l in lines]

    def test_only_component_and_continuation_follows(self):
        flt = ut.Filter({"probes"}, "info", "")
        lines = ["[Lua] [uberGraph] Probes: a", "\ttrace of a", "[Lua] [uberGraph] bridge: b", "\ttrace of b"]
        _, verdicts = self.feed(flt, lines)
        self.assertEqual(verdicts, [True, True, False, False])

    def test_level_and_grep(self):
        flt = ut.Filter(set(), "warn", "pawn")
        _, verdicts = self.feed(flt, ["[Lua] [uberGraph] Probes: info pawn", "[Lua] [uberGraph] Probes: WARN no pawn", "[Lua] [uberGraph] Probes: WARN other"])
        self.assertEqual(verdicts, [False, True, False])


class FollowTest(unittest.TestCase):
    def test_once_prints_classified_entries_without_escapes_when_no_color(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "UE4SS.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(STAMP + " [Lua] [uberGraph] bridge: ready\n" + STAMP + " [Lua] [uberGraph] Probes/level: WARN low\n\ttrace line\n")
            out = io.StringIO()
            ut.follow(path, True, True, ut.Filter(set(), "info", ""), False, out=out)
            text = out.getvalue()
            self.assertIn("bridge", text)
            self.assertIn("WARN low", text)
            self.assertIn("trace line", text)
            self.assertNotIn("\x1b", text)

    def test_truncated_log_is_reported_and_read_again(self):
        with tempfile.TemporaryDirectory() as t:
            path = os.path.join(t, "UE4SS.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(STAMP + " [Lua] [uberGraph] bridge: first run line that is long enough to be bigger later\n")
            out = io.StringIO()
            calls = {"n": 0}

            def stop():
                calls["n"] += 1
                if calls["n"] == 2:  # the game restarted: shorter file
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(STAMP + " [Lua] [uberGraph] bridge: new\n")
                return calls["n"] > 3

            ut.follow(path, True, False, ut.Filter(set(), "info", ""), False, out=out, poll=0.01, stop=stop)
            text = out.getvalue()
            self.assertIn("log restarted", text)
            self.assertIn("new", text)


if __name__ == "__main__":
    unittest.main()
