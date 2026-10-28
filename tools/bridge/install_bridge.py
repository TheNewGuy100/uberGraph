"""Installs, checks and removes the [uberGraph] Bridge mod for the game in the profile. Uses deploy.py, so it only writes inside
deploy.allowedPaths, backs up what it replaces, verifies hashes and can be undone.

    python tools/bridge/install_bridge.py status            what is installed (read-only)
    python tools/bridge/install_bridge.py install           dry run
    python tools/bridge/install_bridge.py install --apply   copies bridge/uber-bridge into <ue4ss>/Mods/[uberGraph] Bridge (backup + hash + log)
    python tools/bridge/install_bridge.py uninstall --apply restores the operation that installed it (deploy.py restore)

The bridge is enabled by its own enabled.txt, so mods.txt is not edited. Restart the game after installing.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
sys.path.insert(0, os.path.join(HERE, "..", "deploy"))
sys.path.insert(0, os.path.join(HERE, "..", "drift"))
import bridge_paths  # noqa: E402
import check_drift  # noqa: E402
import deploy  # noqa: E402
import game_profile  # noqa: E402

PACKAGE = bridge_paths.SOURCE


def status(profile):
    ue4ss = game_profile.get(profile, "ue4ss.dir")
    mod = bridge_paths.mod_dir(ue4ss) if ue4ss else None
    print("UE4SS folder:", ue4ss, "(found)" if ue4ss and os.path.isdir(ue4ss) else "(NOT found)")
    if not mod or not os.path.isdir(mod):
        print(bridge_paths.MOD_NAME + ": not installed")
        return
    for rel in ("Scripts/main.lua", "enabled.txt", "io"):
        print("  %-18s %s" % (rel, "present" if os.path.exists(os.path.join(mod, rel)) else "MISSING"))
    installed, packaged = os.path.join(mod, "Scripts", "main.lua"), os.path.join(PACKAGE, "Scripts", "main.lua")
    if os.path.isfile(installed):
        same = deploy.sha256(installed) == deploy.sha256(packaged)
        print("  main.lua:", "identical to the package" if same else "DIFFERENT from the package (update with install --apply)")


def main(argv):
    if not argv or argv[0] not in ("status", "install", "uninstall"):
        print(__doc__)
        return 2
    profile = game_profile.load()
    if argv[0] == "status":
        status(profile)
        return 0
    apply = "--apply" in argv
    if argv[0] == "install":
        rows = check_drift.check(profile)
        if check_drift.exit_code(rows) == 1:
            raise SystemExit("the game changed since the profile was recorded (run tools/drift/check_drift.py); nothing was copied")
        mods = os.path.join(game_profile.get(profile, "ue4ss.dir"), "Mods")
        # the folder name in the game is the name UE4SS lists, so stage a copy under that name
        stage = os.path.join(tempfile.mkdtemp(prefix="uber-bridge-"), bridge_paths.MOD_NAME)
        shutil.copytree(PACKAGE, stage)
        deploy.copy(profile, [stage], mods, apply=apply)
        shared_src = os.path.join(bridge_paths.ROOT, "lua", "shared")
        libs = [os.path.join(shared_src, name) for name in sorted(os.listdir(shared_src))] if os.path.isdir(shared_src) else []
        if libs:  # Lua libraries (require("UberGraphLog")) live in <ue4ss>/Mods/shared/
            deploy.copy(profile, libs, os.path.join(mods, "shared"), apply=apply)
        return 0
    # uninstall: undo the last operation that installed the bridge
    entries = [e for e in deploy.read_log(profile["deploy"]["backupDir"]) if any(bridge_paths.MOD_NAME in i["dest"] for i in e["items"])]
    if not entries:
        raise SystemExit("no logged installation of " + bridge_paths.MOD_NAME + " found")
    entry = entries[-1]
    print("would restore operation", entry["id"], "(%d file(s))" % len(entry["items"]))
    if apply:
        deploy.restore(profile, entry["id"], force="--force" in argv)
    else:
        print("dry run: add --apply to do it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
