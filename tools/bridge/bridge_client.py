"""Client for the [uberGraph] Bridge (bridge/uber-bridge): sends one read-only request to the running game and prints the answer.

The mod folder comes from the game profile (ue4ss.dir + /Mods/[uberGraph] Bridge/io). Protocol: this client writes io/request.txt
(key=value lines), the mod answers with io/response.json and refreshes io/heartbeat.txt every second.

    python tools/bridge/bridge_client.py ping
    python tools/bridge/bridge_client.py status
    python tools/bridge/bridge_client.py find_all PlayerController [limit]
    python tools/bridge/bridge_client.py get pawn BaseEyeHeight,JumpMaxCount
    python tools/bridge/bridge_client.py describe_class /Script/Voyage.VoyageSkill [limit]     or:  describe_class object:pawn
    python tools/bridge/bridge_client.py get_array OBJECT PROPERTY [limit]
    python tools/bridge/bridge_client.py read OBJECT PROPERTY [depth] [limit]       structs, arrays, enums (OBJECT may be cdo:/Script/Mod.Class)
    python tools/bridge/bridge_client.py map_info OBJECT PROPERTY               what a MapProperty exposes (iterates nothing)
    python tools/bridge/bridge_client.py probe_methods OBJECT PROPERTY name1,name2,... [property]   which members exist (never calls them)
    python tools/bridge/bridge_client.py map_peek OBJECT PROPERTY               types of the first map entry (no values read)
    python tools/bridge/bridge_client.py load_asset /Game/Path/Asset.Asset      needs allow_load=true (see bridge_settings.py)
    python tools/bridge/bridge_client.py describe_function /Game/Dir/Pkg.Class_C:Function     parameters and flags (read-only)
    python tools/bridge/bridge_client.py watch_function start|log|stop|list [/Game/...:Function]   observe-only hook; needs allow_hooks=true
    python tools/bridge/bridge_client.py find_object /Path.Object
    python tools/bridge/bridge_client.py cvar_get r.Shadow.MaxResolution                       console variable (read-only)
    python tools/bridge/bridge_client.py console_exec stat unit                                one console command; needs allow_console=true
    python tools/bridge/bridge_client.py scan contains=TEXT [class=Class] [limit=N]
    python tools/bridge/bridge_client.py health                  heartbeat age, last operation (no request sent)
"""
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
import bridge_paths  # noqa: E402
import game_profile  # noqa: E402

BEAT_STALE_S = 5


def io_dir(profile):
    ue4ss = game_profile.get(profile, "ue4ss.dir")
    if not ue4ss:
        raise SystemExit("profile has no ue4ss.dir")
    return os.path.join(bridge_paths.mod_dir(ue4ss), "io")


def heartbeat_age(io):
    path = os.path.join(io, "heartbeat.txt")
    try:
        stamp = int(open(path, encoding="utf-8").read().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return time.time() - stamp


def health(io):
    age = heartbeat_age(io)
    last = ""
    try:
        last = open(os.path.join(io, "lastop.log"), encoding="utf-8", errors="replace").read().strip()
    except OSError:
        pass
    return {"heartbeat_age_s": None if age is None else round(age, 1), "alive": age is not None and age < BEAT_STALE_S, "last_operation": last}


def request(io, op, args=None, timeout=10.0):
    """Sends one request and returns the parsed response, or raises SystemExit with the reason it failed."""
    if not os.path.isdir(io):
        raise SystemExit("io folder not found (is the bridge installed?): " + io)
    age = heartbeat_age(io)
    if age is None or age > BEAT_STALE_S:
        raise SystemExit("no recent heartbeat (%s): is the game running with the [uberGraph] Bridge enabled?" % ("never written" if age is None else "%.0f s old" % age))
    req_id = uuid.uuid4().hex[:16]
    response_path = os.path.join(io, "response.json")
    for stale in (response_path,):
        try:
            os.remove(stale)
        except OSError:
            pass
    lines = ["id=" + req_id, "op=" + op] + ["arg.%s=%s" % (k, v) for k, v in (args or {}).items()]
    tmp = os.path.join(io, "request.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, os.path.join(io, "request.txt"))
    deadline = time.time() + timeout
    picked_up = False
    while time.time() < deadline:
        if not os.path.exists(os.path.join(io, "request.txt")):
            picked_up = True
        if os.path.exists(response_path):
            try:
                data = json.load(open(response_path, encoding="utf-8"))
            except ValueError:
                time.sleep(0.05)
                continue
            if data.get("id") == req_id:
                return data
        time.sleep(0.05)
    if not picked_up:
        raise SystemExit("request was never picked up (game paused, in a loading screen, or bridge stopped); heartbeat age %s" % heartbeat_age(io))
    raise SystemExit("request was picked up but no response came in %.0f s: the game thread may be blocked or the game crashed. Last op: %s" % (timeout, health(io)["last_operation"]))


def parse_args(op, rest):
    """The request arguments for an operation from its command-line words (shared with tools/term/uber_term.py)."""
    args = {}
    if op == "find_all":
        args = {"class": rest[0]} if rest else {}
        if len(rest) > 1:
            args["limit"] = rest[1]
    elif op == "describe_class":
        if not rest:
            raise SystemExit("usage: describe_class CLASS_PATH|object:REF [limit]")
        args = {"object": rest[0][7:]} if rest[0].startswith("object:") else {"class": rest[0]}
        if len(rest) > 1:
            args["limit"] = rest[1]
    elif op == "get_array":
        if len(rest) < 2:
            raise SystemExit("usage: get_array OBJECT PROPERTY [limit]")
        args = {"object": rest[0], "property": rest[1]}
        if len(rest) > 2:
            args["limit"] = rest[2]
    elif op == "read":
        if len(rest) < 2:
            raise SystemExit("usage: read OBJECT PROPERTY [depth] [limit]")
        args = {"object": rest[0], "property": rest[1]}
        if len(rest) > 2:
            args["depth"] = rest[2]
        if len(rest) > 3:
            args["limit"] = rest[3]
    elif op == "map_info":
        if len(rest) < 2:
            raise SystemExit("usage: map_info OBJECT PROPERTY")
        args = {"object": rest[0], "property": rest[1]}
    elif op == "probe_methods":
        if len(rest) < 3:
            raise SystemExit("usage: probe_methods OBJECT PROPERTY name1,name2,... [property]")
        args = {"object": rest[0], "property": rest[1], "names": rest[2]}
        if len(rest) > 3 and rest[3] == "property":
            args["target"] = "property"
    elif op == "map_peek":
        if len(rest) < 2:
            raise SystemExit("usage: map_peek OBJECT PROPERTY")
        args = {"object": rest[0], "property": rest[1]}
    elif op == "load_asset":
        args = {"path": rest[0]} if rest else {}
    elif op == "describe_function":
        args = {"path": rest[0]} if rest else {}
    elif op == "watch_function":
        args = {"action": rest[0] if rest else "list"}
        if len(rest) > 1:
            args["path"] = rest[1]
    elif op == "find_object":
        args = {"path": rest[0]} if rest else {}
    elif op == "cvar_get":
        args = {"name": rest[0]} if rest else {}
    elif op == "console_exec":
        args = {"command": " ".join(rest)} if rest else {}
    elif op == "scan":
        args = dict(item.split("=", 1) for item in rest if "=" in item)
    elif op == "get":
        if len(rest) < 2:
            raise SystemExit("usage: get OBJECT PROPERTY[,PROPERTY...]")
        args = {"object": rest[0], "property": rest[1]}
    return args


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    profile = game_profile.load()
    io = io_dir(profile)
    op, rest = argv[0], argv[1:]
    if op == "health":
        print(json.dumps(health(io), indent=2))
        return 0
    args = parse_args(op, rest)
    response = request(io, op, args)
    print(json.dumps(response, indent=2))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
