"""Tests for deploy.py using temporary folders only (never touches a game). Run: python tools/deploy/test_deploy.py"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deploy  # noqa: E402


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name.replace("\\", "/")
        self.game, self.src, self.backup = t + "/game", t + "/src", t + "/backups"
        self.profile = {"deploy": {"backupDir": self.backup, "allowedPaths": [
            self.game + "/Content/Paks/z*_P.*", self.game + "/ue4ss/Mods/Mine*/"]}}
        self.log = []

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, text):
        self.log.append(text)

    def test_allowed_pattern_rules(self):
        p = self.profile["deploy"]["allowedPaths"]
        self.assertTrue(deploy.is_allowed(self.game + "/Content/Paks/zMy_P.pak", p))
        self.assertFalse(deploy.is_allowed(self.game + "/Content/Paks/pakchunk0.pak", p))
        self.assertFalse(deploy.is_allowed(self.game + "/Content/Paks/sub/zMy_P.pak", p), "'*' must not cross '/'")
        self.assertTrue(deploy.is_allowed(self.game + "/ue4ss/Mods/MineA/Scripts/main.lua", p))
        self.assertFalse(deploy.is_allowed(self.game + "/ue4ss/Mods/Other/Scripts/main.lua", p))
        self.assertFalse(deploy.is_allowed(self.game + "/ue4ss/Mods/MineA/../Other/x.lua", p), "'..' must be resolved first")

    def test_placeholder_profile_is_refused(self):
        with self.assertRaises(SystemExit):
            deploy.is_allowed("/x/y", ["<GAME>/Paks/z*_P.*"])

    def test_dry_run_writes_nothing(self):
        write(self.src + "/zMy_P.pak", "new")
        deploy.copy(self.profile, [self.src + "/zMy_P.pak"], self.game + "/Content/Paks/", apply=False, out=self.out)
        self.assertFalse(os.path.exists(self.game + "/Content/Paks/zMy_P.pak"))
        self.assertFalse(os.path.exists(self.backup))

    def test_refuses_outside_allowed_and_copies_nothing(self):
        write(self.src + "/pakchunk0.pak", "evil")
        write(self.src + "/zMy_P.pak", "ok")
        with self.assertRaises(SystemExit):
            deploy.copy(self.profile, [self.src + "/zMy_P.pak", self.src + "/pakchunk0.pak"], self.game + "/Content/Paks/", True, self.out)
        self.assertFalse(os.path.exists(self.game + "/Content/Paks/zMy_P.pak"), "all-or-nothing")

    def test_replace_backup_verify_and_restore(self):
        dest = self.game + "/Content/Paks/zMy_P.pak"
        write(dest, "old")
        write(self.src + "/zMy_P.pak", "new")
        op = deploy.copy(self.profile, [self.src + "/zMy_P.pak"], self.game + "/Content/Paks/", True, self.out)
        self.assertEqual(read(dest), "new")
        deploy.restore(self.profile, op, False, self.out)
        self.assertEqual(read(dest), "old")

    def test_create_then_restore_removes_file(self):
        write(self.src + "/zMy_P.pak", "new")
        op = deploy.copy(self.profile, [self.src + "/zMy_P.pak"], self.game + "/Content/Paks/", True, self.out)
        deploy.restore(self.profile, op, False, self.out)
        self.assertFalse(os.path.exists(self.game + "/Content/Paks/zMy_P.pak"))

    def test_restore_refuses_after_later_change(self):
        dest = self.game + "/Content/Paks/zMy_P.pak"
        write(self.src + "/zMy_P.pak", "new")
        op = deploy.copy(self.profile, [self.src + "/zMy_P.pak"], self.game + "/Content/Paks/", True, self.out)
        write(dest, "changed by someone else")
        with self.assertRaises(SystemExit):
            deploy.restore(self.profile, op, False, self.out)
        self.assertEqual(read(dest), "changed by someone else")
        deploy.restore(self.profile, op, True, self.out)

    def test_directory_copy(self):
        write(self.src + "/MineA/Scripts/main.lua", "print(1)")
        write(self.src + "/MineA/enabled.txt", "")
        deploy.copy(self.profile, [self.src + "/MineA"], self.game + "/ue4ss/Mods", True, self.out)
        self.assertEqual(read(self.game + "/ue4ss/Mods/MineA/Scripts/main.lua"), "print(1)")

    def test_unchanged_file_is_not_touched(self):
        write(self.game + "/Content/Paks/zMy_P.pak", "same")
        write(self.src + "/zMy_P.pak", "same")
        op = deploy.copy(self.profile, [self.src + "/zMy_P.pak"], self.game + "/Content/Paks/", True, self.out)
        self.assertTrue(any(line.startswith("unchanged") for line in self.log))
        self.assertEqual(len(deploy.read_log(self.backup)[-1]["items"]), 1)
        self.assertIsNotNone(op)


if __name__ == "__main__":
    unittest.main(verbosity=2)
