"""Run Python inside the open Unreal Editor through PythonScriptPlugin remote execution.

Prerequisites: PythonScriptPlugin enabled and Project Settings > Plugins > Python > Remote Execution on
(see docs/UE-EDITOR-AUTOMATION.md). The editor must be open; loopback multicast 239.0.0.1:6766 is used.

Usage:
    python ue_remote.py --file script.py        run a script file (multi-statement)
    python ue_remote.py "print(1+1)"           run one statement
Engine root: UE_ENGINE_ROOT, else engine.root of the game profile (profiles/*.local.json), else a placeholder that fails with a clear message
"""
import argparse
import os
import sys
import time

def _engine_root():
    # Order: UE_ENGINE_ROOT, then the game profile (profiles/<id>.local.json, see docs/GAME-PROFILES.md), then the old default.
    if os.environ.get("UE_ENGINE_ROOT"):
        return os.environ["UE_ENGINE_ROOT"]
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "profile"))
        import game_profile
        return game_profile.get(game_profile.load(), "engine.root") or DEFAULT_ROOT
    except (Exception, SystemExit):
        return DEFAULT_ROOT


DEFAULT_ROOT = r"<set UE_ENGINE_ROOT or engine.root in the game profile>"
engine = _engine_root()
sys.path.insert(0, os.path.join(engine, "Engine", "Plugins", "Experimental", "PythonScriptPlugin", "Content", "Python"))
import remote_execution as rx  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("statement", nargs="?")
parser.add_argument("--file")
parser.add_argument("--timeout", type=float, default=8.0)
args = parser.parse_args()

if args.file:
    path = os.path.abspath(args.file)
    code, mode = "exec(open(r'%s', encoding='utf-8').read())" % os.path.abspath(args.file), rx.MODE_EXEC_FILE
elif args.statement:
    code, mode = args.statement, rx.MODE_EXEC_STATEMENT
else:
    parser.error("give a statement or --file")

remote = rx.RemoteExecution()
remote.start()
deadline = time.time() + args.timeout
node = None
while time.time() < deadline and not node:
    nodes = remote.remote_nodes
    node = nodes[0] if nodes else None
    time.sleep(0.3)
if not node:
    print("No editor found: is remote execution enabled?")
    remote.stop()
    sys.exit(2)
remote.open_command_connection(node)
result = remote.run_command(code, exec_mode=mode, unattended=True)
print("success:", result.get("success"))
for line in result.get("output", []):
    print("[%s] %s" % (line.get("type"), line.get("output")))
if not result.get("success"):
    print(str(result.get("result"))[:2000])
remote.close_command_connection()
remote.stop()
sys.exit(0 if result.get("success") else 1)
