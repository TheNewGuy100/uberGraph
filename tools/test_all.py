"""Runs every automated check of Ubergraph: the gate that a change passes before it is promoted (see docs/RELEASE-FLOW.md).

    python tools/test_all.py           run everything; exit code 0 only if every step passed or was skipped for a stated reason
    python tools/test_all.py --quick   skip the Lua VM tests and the hygiene scan

Steps: Python unit tests (tools/**/test_*.py), Lua syntax of the bridge, the Lua libraries and the mods found, Lua behaviour tests (bridge and
logger, in a Lua VM, needs `npm install` in tools/lua-check), and the repository hygiene scan (needs bash).
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
results = []


def step(name, command, cwd=ROOT, skip_reason=None):
    if skip_reason:
        results.append((name, "SKIP", skip_reason))
        print("skip   %-32s %s" % (name, skip_reason))
        return
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    state = "ok" if done.returncode == 0 else "FAIL"
    results.append((name, state.upper(), ""))
    print("%-6s %s" % (state, name))
    if done.returncode != 0:
        print((done.stdout + done.stderr).strip()[-1500:])


SELF = os.path.abspath(__file__)
# Not unit tests: editor scripts named test_* (they need the Unreal editor) and the MCP prototype's tests (they need a build).
EXCLUDED = ("/examples/", "/cue4parse-mcp/", "/node_modules/")


def python_tests():
    found = []
    for test in sorted(glob.glob(os.path.join(ROOT, "tools", "**", "test_*.py"), recursive=True)):
        path = os.path.abspath(test)
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if path == SELF or any(part in "/" + rel for part in EXCLUDED):
            continue
        found.append((path, rel))
    return found


def main(argv):
    if os.environ.get("UBERGRAPH_TEST_ALL"):  # a test started this script again: refuse instead of recursing
        print("refusing to run test_all inside test_all")
        return 2
    os.environ["UBERGRAPH_TEST_ALL"] = "1"
    quick = "--quick" in argv
    for test, rel in python_tests():
        step("python " + rel, [sys.executable, test])
    node = shutil.which("node")
    lua_check = os.path.join(ROOT, "tools", "lua-check")
    has_modules = os.path.isdir(os.path.join(lua_check, "node_modules", "luaparse"))
    lua_files = [f for pattern in ("bridge/**/*.lua", "lua/**/*.lua", "mods/**/*.lua") for f in glob.glob(os.path.join(ROOT, pattern), recursive=True)]
    step("lua syntax (%d files)" % len(lua_files), [node or "node", os.path.join(lua_check, "check-lua.js")] + lua_files,
         skip_reason=None if node and has_modules and lua_files else "needs node and `npm install` in tools/lua-check")
    for name in ("test-logger.js", "test-bridge.js"):
        step("lua vm " + name, [node or "node", os.path.join(lua_check, name)],
             skip_reason="--quick" if quick else (None if node and os.path.isdir(os.path.join(lua_check, "node_modules", "fengari")) else "needs node and `npm install` in tools/lua-check"))
    bash = shutil.which("bash")
    step("repository hygiene", [bash or "bash", os.path.join(ROOT, "tools", "check-repo-hygiene.sh")],
         skip_reason="--quick" if quick else (None if bash else "needs bash"))
    failed = [r for r in results if r[1] == "FAIL"]
    print("\n%d steps, %d failed, %d skipped" % (len(results), len(failed), len([r for r in results if r[1] == "SKIP"])))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
