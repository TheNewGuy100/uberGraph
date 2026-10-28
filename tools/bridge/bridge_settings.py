"""Shows or changes the [uberGraph] Bridge settings of the game in the profile (settings.txt in the mod folder).

    python tools/bridge/bridge_settings.py show
    python tools/bridge/bridge_settings.py init      rewrite settings.txt with the risk section, keeping every value
    python tools/bridge/bridge_settings.py set allow_load true --user-approved "what the user said, in their words"
    python tools/bridge/bridge_settings.py set allow_hooks true --user-approved "..."

allow_load turns on the load_asset operation, which changes the game's in-memory state. RULE FOR AI AGENTS: before turning it on,
ask the user and explain the consequences (below); pass the user's approval text in --user-approved. The change goes through
tools/deploy (allowed paths, backup, hash, log) and is also recorded, with the approval text, in <backupDir>/bridge-settings-log.jsonl.
"""
import datetime
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
sys.path.insert(0, os.path.join(HERE, "..", "deploy"))
import deploy  # noqa: E402
import bridge_paths  # noqa: E402
import game_profile  # noqa: E402

KNOWN = {"allow_load": ("true", "false"), "allow_hooks": ("true", "false"), "allow_console": ("true", "false")}
CONSOLE_CONSEQUENCES = (
    "allow_console=true lets the bridge run one console command at a time (console_exec). Consequences: it changes the running game (a console variable, "
    "a stat overlay, a log category) until the game closes or the variable is set back; a wrong value can make the game slow, unstable or ugly. "
    "Only commands whose first word is stat, log, obj, showflag, dumpconsolecommands, listtimers or a cvar starting r. sg. t. run; no chaining; "
    "quit, open and travel commands are refused. The console's output text is not returned (the engine does not expose it to Lua); read the effect "
    "with cvar_get or the UE4SS log."
)
HOOK_CONSEQUENCES = (
    "allow_hooks=true lets the bridge place an observe-only hook on a game function (watch_function). Consequences: the hook runs inside the game "
    "every time that function is called, so a frequently called function costs performance; hooks have been a crash suspect in earlier projects "
    "(a hook on every actor was never ruled out); the hook is removed when the game closes or with watch_function stop. It records strings only and "
    "changes nothing. At most 3 watchers at a time."
)
CONSEQUENCES = (
    "allow_load=true lets the bridge load game assets by path. Consequences: the game thread can pause while the asset and its dependencies load; "
    "memory use goes up (this PC has hit its commit limit before); the asset's PostLoad logic runs; a strange asset could crash the game. "
    "Nothing is written to disk and the loaded objects are not kept by the bridge. Only /Game/ paths, one per request."
)

CONSEQUENCE_OF = {"allow_load": CONSEQUENCES, "allow_hooks": HOOK_CONSEQUENCES, "allow_console": CONSOLE_CONSEQUENCES}


def render(values):
    """The whole settings.txt: a risk section whose options carry their consequences, so whoever flips one has read them."""
    lines = [
        "# [uberGraph] Bridge settings, written by tools/bridge/bridge_settings.py. A missing file or key means OFF.",
        "#",
        "# ===================== RISKY OPERATIONS =====================",
        "# Every option below changes the running game. An AI agent must ask the user and explain the consequences",
        "# BEFORE turning one on, then use:  tools/bridge/bridge_settings.py set <key> true --user-approved \"<the user's words>\"",
        "# (the tool refuses without an approval text, applies the change through tools/deploy and logs it).",
        "# Turn an option off again when the analysis that needed it is done.",
        "#",
    ]
    for key in KNOWN:
        text = CONSEQUENCE_OF[key]
        for chunk in text.replace(". ", ".\n").split("\n"):
            lines.append("# " + chunk.strip())
        lines.append("%s=%s" % (key, values.get(key, "false")))
        lines.append("#")
    return "\n".join(lines) + "\n"


def settings_path(profile):
    ue4ss = game_profile.get(profile, "ue4ss.dir")
    if not ue4ss:
        raise SystemExit("profile has no ue4ss.dir")
    return os.path.join(bridge_paths.mod_dir(ue4ss), "settings.txt")


def read(path):
    values = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith(("#", ";")) and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def main(argv):
    profile = game_profile.load()
    path = settings_path(profile)
    if not argv or argv[0] == "show":
        print("settings file:", path, "(exists)" if os.path.isfile(path) else "(absent: every option is off)")
        print(json.dumps({k: read(path).get(k, "false (default)") for k in KNOWN}, indent=2))
        return 0
    if argv[0] == "init":
        values = read(path)
        with tempfile.TemporaryDirectory() as tmp:
            staged = os.path.join(tmp, "settings.txt")
            with open(staged, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(render(values))
            deploy.copy(profile, [staged], path, apply=True)
        print("settings.txt rewritten with the risk section; values kept:", {k: values.get(k, "false") for k in KNOWN})
        return 0
    if argv[0] != "set" or len(argv) < 3:
        print(__doc__)
        return 2
    key, value = argv[1], argv[2]
    if key not in KNOWN or value not in KNOWN[key]:
        raise SystemExit("unknown setting or value; known: " + json.dumps(KNOWN))
    approval = argv[argv.index("--user-approved") + 1] if "--user-approved" in argv and argv.index("--user-approved") + 1 < len(argv) else ""
    if value == "true":
        print(CONSEQUENCE_OF[key])
        if not approval.strip():
            raise SystemExit("refused: turning this on needs --user-approved with the user's own words (ask the user first and explain the consequences above)")
    values = read(path)
    values[key] = value
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, "settings.txt")
        with open(staged, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(values))
        deploy.copy(profile, [staged], path, apply=True)
    log = os.path.join(profile["deploy"]["backupDir"], "bridge-settings-log.jsonl")
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": datetime.datetime.now().isoformat(timespec="seconds"), "key": key, "value": value, "user_approved": approval}) + "\n")
    print("set %s=%s" % (key, value))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
