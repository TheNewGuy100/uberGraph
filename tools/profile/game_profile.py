"""Loads a game profile (see docs/GAME-PROFILES.md).

Lookup order for the profile id: argument, environment UE_PROFILE, the only profile found.
For each id the file profiles/<id>.local.json (ignored by git, real paths) wins over profiles/<id>.example.json.
Values that still look like placeholders (<...>) are reported as missing instead of being used.
Usage: from game_profile import load, get;  p = load();  root = get(p, "engine.root")
       python tools/profile/game_profile.py [id] [dotted.key]   prints the profile or one value
"""
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROFILES = os.path.join(ROOT, "profiles")


def _ids():
    names = set()
    for f in os.listdir(PROFILES) if os.path.isdir(PROFILES) else []:
        for suffix in (".local.json", ".example.json"):
            if f.endswith(suffix):
                names.add(f[: -len(suffix)])
    return sorted(names)


def load(profile_id=None):
    profile_id = profile_id or os.environ.get("UE_PROFILE")
    if not profile_id:
        ids = _ids()
        if len(ids) != 1:
            raise SystemExit("choose a profile (UE_PROFILE or argument); found: %s" % (", ".join(ids) or "none"))
        profile_id = ids[0]
    for suffix in (".local.json", ".example.json"):
        path = os.path.join(PROFILES, profile_id + suffix)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            data["_source"] = path
            return data
    raise SystemExit("profile not found: " + profile_id)


def get(profile, dotted, default=None):
    """Returns the value at 'a.b.c', or default when missing, null or still a <placeholder>."""
    value = profile
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    if value is None or (isinstance(value, str) and "<" in value and ">" in value):
        return default
    return value


if __name__ == "__main__":
    prof = load(sys.argv[1] if len(sys.argv) > 1 and "." not in sys.argv[1] else None)
    key = sys.argv[-1] if len(sys.argv) > 1 and "." in sys.argv[-1] else None
    if key:
        value = get(prof, key)
        print("" if value is None else (json.dumps(value) if isinstance(value, (dict, list)) else value))
        sys.exit(0 if value is not None else 1)
    print(json.dumps(prof, indent=2))
