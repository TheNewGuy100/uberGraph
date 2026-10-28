"""Tests for check_drift.py on temporary files only. Run: python tools/drift/test_drift.py"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_drift as cd  # noqa: E402


class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.root = os.path.join(t, "steamapps", "common", "Game")
        self.paks = os.path.join(self.root, "Content", "Paks")
        os.makedirs(self.paks)
        self.exe = os.path.join(self.root, "game.exe")
        open(self.exe, "wb").write(b"exe-v1")
        open(os.path.join(self.paks, "a.ucas"), "wb").write(b"12345")
        open(os.path.join(self.paks, "zMine_P.pak"), "wb").write(b"ours")
        open(os.path.join(t, "steamapps", "appmanifest_42.acf"), "w").write('"AppState"\n{\n\t"buildid"\t\t"100"\n}\n')
        self.mapping = os.path.join(t, "m.usmap")
        open(self.mapping, "wb").write(b"map")
        self.profile = {"game": {"steamAppId": 42, "buildId": 100, "installRoot": self.root,
                                 "exe": {"path": self.exe, "sha256": cd.sha256(self.exe)},
                                 "containers": {"dir": self.paks, "sizes": {"a.ucas": 5}}},
                        "mappings": {"path": self.mapping, "sha256": cd.sha256(self.mapping)}}

    def tearDown(self):
        self.tmp.cleanup()

    def statuses(self):
        return {r[1]: r[0] for r in cd.check(self.profile)}

    def test_no_drift(self):
        rows = cd.check(self.profile)
        self.assertTrue(all(r[0] == cd.OK for r in rows), rows)
        self.assertEqual(cd.exit_code(rows), 0)

    def test_our_containers_are_ignored(self):
        self.assertNotIn("container zMine_P.pak", self.statuses())

    def test_build_id_change(self):
        self.profile["game"]["buildId"] = 99
        self.assertEqual(self.statuses()["Steam build id"], cd.DRIFT)

    def test_exe_change(self):
        open(self.exe, "wb").write(b"exe-v2")
        s = self.statuses()
        self.assertEqual(s["executable sha256"], cd.DRIFT)
        self.assertEqual(cd.exit_code(cd.check(self.profile)), 1)

    def test_container_size_change_and_new_file(self):
        open(os.path.join(self.paks, "a.ucas"), "wb").write(b"123456")
        open(os.path.join(self.paks, "new.ucas"), "wb").write(b"x")
        s = self.statuses()
        self.assertEqual(s["container a.ucas"], cd.DRIFT)
        self.assertEqual(s["container new.ucas"], cd.DRIFT)

    def test_missing_baseline_is_not_a_pass(self):
        self.profile["game"]["exe"]["sha256"] = None
        self.profile["mappings"]["sha256"] = None
        s = self.statuses()
        self.assertEqual(s["executable sha256"], cd.NOBASE)
        self.assertEqual(s["mapping sha256"], cd.NOBASE)

    def test_nothing_comparable_exits_2(self):
        rows = cd.check({"game": {"steamAppId": 42}})
        self.assertEqual(cd.exit_code(rows), 2)

    def test_record_refuses_example_profile(self):
        with self.assertRaises(SystemExit):
            cd.record({"_source": "profiles/x.example.json"})

    def test_record_fills_only_missing(self):
        path = os.path.join(self.tmp.name, "p.local.json")
        data = {"game": {"exe": {"path": self.exe, "sha256": "KEEP"}, "containers": {"dir": self.paks}}, "mappings": {"path": self.mapping, "sha256": None}}
        json.dump(data, open(path, "w"))
        profile = dict(data, _source=path)
        done = cd.record(profile)
        saved = json.load(open(path))
        self.assertEqual(saved["game"]["exe"]["sha256"], "KEEP")
        self.assertIn("game.containers.sizes", done)
        self.assertIn("mappings.sha256", done)


if __name__ == "__main__":
    unittest.main(verbosity=2)
