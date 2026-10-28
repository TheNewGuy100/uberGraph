"""Build drift check: does the installed game still match the profile? (docs/GAME-PROFILES.md, step 3)

Compares, without changing anything:
  - the Steam build id (appmanifest_<steamAppId>.acf next to the install) with game.buildId,
  - the SHA-256 of the executable with game.exe.sha256,
  - the sizes of the original containers in game.containers.dir with game.containers.sizes (sizes, not hashes: one is 16 GB),
  - the SHA-256 of the mapping file with mappings.sha256.
A value missing from the profile is reported as NO BASELINE, not as a pass. Our own z*_P containers are ignored.
    python tools/drift/check_drift.py [profile-id]            exit 0 = no drift, 1 = drift, 2 = nothing could be compared
    python tools/drift/check_drift.py [profile-id] --record   writes missing baselines into profiles/<id>.local.json
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
import game_profile  # noqa: E402

OK, DRIFT, NOBASE, MISSING = "OK", "DRIFT", "NO BASELINE", "MISSING"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def steam_build_id(install_root, app_id):
    """buildid from steamapps/appmanifest_<id>.acf, or None."""
    manifest = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(install_root))), "appmanifest_%s.acf" % app_id)
    if not os.path.isfile(manifest):
        return None
    m = re.search(r'"buildid"\s+"(\d+)"', open(manifest, encoding="utf-8", errors="replace").read())
    return int(m.group(1)) if m else None


def original_container_sizes(directory):
    out = {}
    for name in sorted(os.listdir(directory)):
        full = os.path.join(directory, name)
        if os.path.isfile(full) and not re.match(r"^z.*_P\.", name, re.IGNORECASE):
            out[name] = os.path.getsize(full)
    return out


def check(profile):
    """Returns a list of (status, what, expected, actual)."""
    g = game_profile.get
    rows = []
    root, app_id = g(profile, "game.installRoot"), g(profile, "game.steamAppId")
    expected_build = g(profile, "game.buildId")
    actual_build = steam_build_id(root, app_id) if root and app_id else None
    if actual_build is None:
        rows.append((MISSING, "Steam build id", expected_build, "appmanifest not found"))
    else:
        rows.append((OK if actual_build == expected_build else DRIFT, "Steam build id", expected_build, actual_build))

    exe, exe_hash = g(profile, "game.exe.path"), g(profile, "game.exe.sha256")
    if not exe or not os.path.isfile(exe):
        rows.append((MISSING, "executable", exe_hash, "file not found"))
    else:
        actual = sha256(exe)
        rows.append((NOBASE if not exe_hash else OK if actual == exe_hash.upper() else DRIFT, "executable sha256", exe_hash, actual))

    cdir, expected_sizes = g(profile, "game.containers.dir"), g(profile, "game.containers.sizes")
    if not cdir or not os.path.isdir(cdir):
        rows.append((MISSING, "containers dir", cdir, "not found"))
    else:
        actual_sizes = original_container_sizes(cdir)
        if not expected_sizes:
            rows.append((NOBASE, "container sizes", None, "%d files" % len(actual_sizes)))
        else:
            for name in sorted(set(expected_sizes) | set(actual_sizes)):
                e, a = expected_sizes.get(name), actual_sizes.get(name)
                rows.append((OK if e == a else DRIFT, "container " + name, e, a if a is not None else "absent"))

    mp, mp_hash = g(profile, "mappings.path"), g(profile, "mappings.sha256")
    if not mp or not os.path.isfile(mp):
        rows.append((MISSING, "mapping file", mp_hash, "file not found"))
    else:
        actual = sha256(mp)
        rows.append((NOBASE if not mp_hash else OK if actual == mp_hash.upper() else DRIFT, "mapping sha256", mp_hash, actual))
    return rows


def exit_code(rows):
    if any(r[0] == DRIFT for r in rows):
        return 1
    if not any(r[0] == OK for r in rows):
        return 2
    return 0


def record(profile):
    """Fills only baselines that are missing (never overwrites a value that drifted). Returns what was recorded."""
    path = profile["_source"]
    if not path.endswith(".local.json"):
        raise SystemExit("refusing to edit a tracked example profile; record into a .local.json profile")
    data = json.load(open(path, encoding="utf-8"))
    done = []
    g = game_profile.get
    exe = g(profile, "game.exe.path")
    if exe and os.path.isfile(exe) and not g(profile, "game.exe.sha256"):
        data["game"]["exe"]["sha256"] = sha256(exe); done.append("game.exe.sha256")
    cdir = g(profile, "game.containers.dir")
    if cdir and os.path.isdir(cdir) and not g(profile, "game.containers.sizes"):
        data["game"]["containers"]["sizes"] = original_container_sizes(cdir); done.append("game.containers.sizes")
    mp = g(profile, "mappings.path")
    if mp and os.path.isfile(mp) and not g(profile, "mappings.sha256"):
        data["mappings"]["sha256"] = sha256(mp); done.append("mappings.sha256")
    if done:
        json.dump(data, open(path, "w", encoding="utf-8"), indent=2)
    return done


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    profile = game_profile.load(args[0] if args else None)
    if "--record" in argv:
        print("recorded:", ", ".join(record(profile)) or "nothing (all baselines present)")
        profile = game_profile.load(args[0] if args else None)
    rows = check(profile)
    for status, what, expected, actual in rows:
        print("%-11s %-34s expected=%s actual=%s" % (status, what, expected, actual))
    code = exit_code(rows)
    print({0: "RESULT: no drift", 1: "RESULT: DRIFT - re-verify probes, mappings and addresses before trusting old results", 2: "RESULT: nothing could be compared"}[code])
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
