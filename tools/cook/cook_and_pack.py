"""Cooks packages from the editor project, converts them to an IoStore container, checks them, and optionally deploys them.

One command for the flow in docs/COOKED-ASSET-PIPELINE.md (cook, retoc to-zen, retoc verify, forbidden-reference scan, deploy):

    python tools/cook/cook_and_pack.py --container zVanillaPlusChest_P --package /Game/VanillaPlus/BP_RecipimaxXL --filter RecipimaxXL
    python tools/cook/cook_and_pack.py ... --deploy        also copies the container into the game's Paks (tools/deploy: allowed
                                                           paths, backup, hash, log, drift check)

Reads the game profile: engine.root, engine.retocVersion, editorProject, game.containers.dir, cook.retoc, cook.outDir.
--filter is retoc's asset file name filter (a substring of the asset names to include). The cook is run without a shell, so no path
mangling; it normally exits 1 because of a template GameFeatureData error but still writes the files, so success is judged by the
output files and by retoc verify. Needs commit headroom: it warns below 6 GB.
"""
import argparse
import ctypes
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for sub in ("profile", "deploy", "drift"):
    sys.path.insert(0, os.path.join(HERE, "..", sub))
import game_profile  # noqa: E402

# the authoring project and the editor tools do not exist in the game: no cooked package may reference them
FORBIDDEN = (b"/Script/ExampleProject", b"/Script/UbergraphEditorTools", b"/Script/VanillaPlusCPP", b"/Script/VanillaPlusEditorTools")


class MemoryStatus(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong), ("total_virt", ctypes.c_ulonglong),
                ("avail_virt", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]


def free_commit_gb():
    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.avail_page / (1 << 30)


def run(cmd, log_path, timeout):
    with open(log_path, "w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    return proc.returncode


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--container", required=True, help="container name, for example zVanillaPlusChest_P")
    ap.add_argument("--package", action="append", required=True, help="package to cook, for example /Game/VanillaPlus/BP_RecipimaxXL (repeatable)")
    ap.add_argument("--filter", required=True, help="retoc asset file name filter")
    ap.add_argument("--deploy", action="store_true")
    ap.add_argument("--profile")
    args = ap.parse_args(argv)

    profile = game_profile.load(args.profile)
    g = game_profile.get
    engine_root, project = g(profile, "engine.root"), g(profile, "editorProject")
    retoc, out_dir = g(profile, "cook.retoc"), g(profile, "cook.outDir")
    version = g(profile, "engine.retocVersion")
    if not all((engine_root, project, retoc, out_dir, version)):
        raise SystemExit("profile is missing engine.root, editorProject, cook.retoc, cook.outDir or engine.retocVersion")
    uproject = os.path.join(ROOT, project)
    editor_cmd = os.path.join(engine_root, "Engine", "Binaries", "Win64", "UnrealEditor-Cmd.exe")
    cooked = os.path.join(os.path.dirname(uproject), "Saved", "Cooked", "Windows")
    project_name = os.path.splitext(os.path.basename(uproject))[0]
    os.makedirs(out_dir, exist_ok=True)

    free = free_commit_gb()
    print("free commit: %.1f GB" % free)
    if free < 6:
        print("WARNING: below 6 GB of commit headroom; the cook may fail with a commit limit error (close other programs first)")

    cook_log = os.path.join(out_dir, "cook-%s.log" % args.container)
    cmd = [editor_cmd, uproject, "-run=Cook", "-TargetPlatform=Windows"] + ["-PACKAGE=" + p for p in args.package] + ["-SkipZenStore", "-unattended", "-nosplash", "-stdout"]
    print("cooking", ", ".join(args.package), "(log: %s)" % cook_log)
    code = run(cmd, cook_log, 1800)
    print("cook exit code", code, "(1 is expected from the template GameFeatureData error)")

    missing = []
    for pkg in args.package:
        rel = pkg.replace("/Game/", "Content/", 1) + ".uasset"
        if not os.path.isfile(os.path.join(cooked, project_name, rel)):
            missing.append(rel)
    if missing:
        raise SystemExit("cook produced no output for: %s (see %s)" % (", ".join(missing), cook_log))

    utoc = os.path.join(out_dir, args.container + ".utoc")
    for ext in (".utoc", ".ucas", ".pak"):
        try:
            os.remove(os.path.join(out_dir, args.container + ext))
        except OSError:
            pass
    conv_log = os.path.join(out_dir, "retoc-%s.log" % args.container)
    code = run([retoc, "to-zen", "--version", version, "--filter", args.filter, cooked, utoc], conv_log, 900)
    if code != 0 or not os.path.isfile(utoc):
        raise SystemExit("retoc to-zen failed (exit %s); see %s" % (code, conv_log))
    verify_log = os.path.join(out_dir, "retoc-verify-%s.log" % args.container)
    code = run([retoc, "verify", utoc], verify_log, 900)
    verified = "verified" in open(verify_log, encoding="utf-8", errors="replace").read().lower()
    print("retoc verify:", "verified" if verified and code == 0 else "NOT verified (see %s)" % verify_log)

    hits = []
    content = os.path.join(cooked, project_name, "Content")
    names = [n.strip().lower() for n in args.filter.split(",")]
    for folder, _dirs, files in os.walk(content):
        for f in files:
            if f.endswith((".uasset", ".uexp")) and any(n in f.lower() for n in names):
                data = open(os.path.join(folder, f), "rb").read()
                wide = data.replace(b"\x00", b"")
                for needle in FORBIDDEN:
                    if needle in data or needle in wide:
                        hits.append((f, needle.decode()))
    if hits:
        raise SystemExit("the game does not have these modules, but the cooked files reference them: %s" % hits)
    print("scan: no references to the authoring project or the editor tools modules in the selected packages")

    files = [os.path.join(out_dir, args.container + e) for e in (".utoc", ".ucas", ".pak") if os.path.isfile(os.path.join(out_dir, args.container + e))]
    for f in files:
        print("  %-40s %12d bytes" % (os.path.basename(f), os.path.getsize(f)))
    if not (verified and code == 0):
        raise SystemExit("not deploying: the container was not verified")

    paks = g(profile, "game.containers.dir")
    import deploy
    import check_drift
    rows = check_drift.check(profile)
    if check_drift.exit_code(rows) == 1:
        raise SystemExit("the game changed since the profile was recorded; not deploying")
    deploy.copy(profile, files, paks, apply=args.deploy)
    if args.deploy:
        print("deployed. Restart the game once: containers are opened at startup.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
