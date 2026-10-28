"""Copies mod files into a game folder with a backup, a hash check and a log, only inside the paths the game profile allows.

Reads the profile (docs/GAME-PROFILES.md): deploy.allowedPaths and deploy.backupDir. Nothing outside allowedPaths is ever written.
A pattern ending in "/" allows any file below a matching directory; "*" does not cross "/". Placeholders (<...>) make the profile
unusable on purpose.

    python tools/deploy/deploy.py copy SRC [SRC ...] --to DEST          dry run: prints what would happen
    python tools/deploy/deploy.py copy SRC [SRC ...] --to DEST --apply   does it (add --check-drift to stop when the game build changed)
    python tools/deploy/deploy.py restore [--id ID] [--force]            undoes an operation (default: the last one)
    python tools/deploy/deploy.py log                                    lists the operations

A directory SRC is copied recursively into DEST/<name of SRC>. A file SRC goes to DEST (a file path) or into DEST (a directory).
Each operation is recorded in <backupDir>/deploy-log.jsonl with the SHA-256 of every file before and after; replaced files are
saved under <backupDir>/deploy/<id>/. restore refuses when a file changed after our copy unless --force.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def norm(path):
    return os.path.abspath(path).replace("\\", "/").rstrip("/").lower() if os.name == "nt" else os.path.abspath(path).rstrip("/")


def _glob_to_regex(pattern):
    out = []
    for ch in pattern:
        out.append("[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch))
    return re.compile("^" + "".join(out) + "$")


def is_allowed(dest, patterns):
    """True when dest (a file path) matches one allowed pattern. Directory patterns end with '/'."""
    dest = norm(dest)
    for raw in patterns:
        if "<" in raw and ">" in raw:
            raise SystemExit("profile deploy.allowedPaths still has a placeholder: " + raw)
        pattern = raw.replace("\\", "/")
        if os.name == "nt":
            pattern = pattern.lower()
        if pattern.endswith("/"):
            base = _glob_to_regex(pattern.rstrip("/"))
            parent = dest
            while True:
                parent = parent.rsplit("/", 1)[0] if "/" in parent else ""
                if not parent:
                    break
                if base.match(parent):
                    return True
        elif _glob_to_regex(pattern).match(dest):
            return True
    return False


def plan_copy(sources, to):
    """Returns [(src_file, dest_file)] without touching the disk."""
    pairs = []
    for src in sources:
        if not os.path.exists(src):
            raise SystemExit("source not found: " + src)
        if os.path.isdir(src):
            base = os.path.join(to, os.path.basename(os.path.abspath(src)))
            for root, _dirs, files in os.walk(src):
                for name in files:
                    full = os.path.join(root, name)
                    pairs.append((full, os.path.join(base, os.path.relpath(full, src))))
        else:
            dest = os.path.join(to, os.path.basename(src)) if (os.path.isdir(to) or to.endswith(("/", "\\"))) else to
            pairs.append((src, dest))
    return pairs


def _log_path(backup_dir):
    return os.path.join(backup_dir, "deploy-log.jsonl")


def read_log(backup_dir):
    path = _log_path(backup_dir)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def copy(profile, sources, to, apply=False, out=print):
    patterns = (profile.get("deploy") or {}).get("allowedPaths") or []
    backup_dir = (profile.get("deploy") or {}).get("backupDir")
    if not patterns or not backup_dir or "<" in str(backup_dir):
        raise SystemExit("profile has no usable deploy.allowedPaths / deploy.backupDir")
    pairs = plan_copy(sources, to)
    refused = [dest for _src, dest in pairs if not is_allowed(dest, patterns)]
    if refused:
        for dest in refused:
            out("REFUSED (not in deploy.allowedPaths): " + dest)
        raise SystemExit("nothing was copied")
    op_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    taken = {e["id"] for e in read_log(backup_dir)}
    suffix = 1
    base_id = op_id
    while op_id in taken:  # two operations in the same second (seen on 2026-10-27) must not share an id or a backup folder
        suffix += 1
        op_id = "%s-%d" % (base_id, suffix)
    items = []
    for src, dest in pairs:
        src_hash = sha256(src)
        existed = os.path.isfile(dest)
        before = sha256(dest) if existed else None
        action = "unchanged" if before == src_hash else ("replace" if existed else "create")
        out("%-9s %s  (sha256 %s)" % (action, dest, src_hash[:12]))
        items.append({"src": os.path.abspath(src), "dest": os.path.abspath(dest), "action": action,
                      "sha256_before": before, "sha256_after": src_hash, "backup": None})
    if not apply:
        out("dry run: nothing written. Add --apply to do it.")
        return None
    os.makedirs(os.path.join(backup_dir, "deploy", op_id), exist_ok=True)
    for index, item in enumerate(items):
        if item["action"] == "unchanged":
            continue
        if item["action"] == "replace":
            backup = os.path.join(backup_dir, "deploy", op_id, "%03d-%s" % (index, os.path.basename(item["dest"])))
            shutil.copy2(item["dest"], backup)
            if sha256(backup) != item["sha256_before"]:
                raise SystemExit("backup hash mismatch for " + item["dest"] + "; stopped before overwriting")
            item["backup"] = backup
        os.makedirs(os.path.dirname(item["dest"]), exist_ok=True)
        shutil.copy2(item["src"], item["dest"])
        if sha256(item["dest"]) != item["sha256_after"]:
            raise SystemExit("copy verification failed for " + item["dest"])
    with open(_log_path(backup_dir), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": op_id, "time": datetime.datetime.now().isoformat(timespec="seconds"), "items": items}) + "\n")
    out("done: %d file(s), operation id %s" % (sum(1 for i in items if i["action"] != "unchanged"), op_id))
    return op_id


def restore(profile, op_id=None, force=False, out=print):
    backup_dir = (profile.get("deploy") or {}).get("backupDir")
    patterns = (profile.get("deploy") or {}).get("allowedPaths") or []
    entries = read_log(backup_dir) if backup_dir else []
    if not entries:
        raise SystemExit("no deploy log found")
    entry = next((e for e in entries if e["id"] == op_id), None) if op_id else entries[-1]
    if entry is None:
        raise SystemExit("operation not found: " + str(op_id))
    for item in entry["items"]:
        if item["action"] == "unchanged":
            continue
        dest = item["dest"]
        if not is_allowed(dest, patterns):
            raise SystemExit("REFUSED (not in deploy.allowedPaths): " + dest)
        if os.path.isfile(dest) and sha256(dest) != item["sha256_after"] and not force:
            raise SystemExit("%s changed after our copy; use --force to overwrite or remove it" % dest)
    for item in entry["items"]:
        if item["action"] == "unchanged":
            continue
        dest = item["dest"]
        if item["action"] == "create":
            if os.path.isfile(dest):
                os.remove(dest)
            out("removed  " + dest)
        else:
            if sha256(item["backup"]) != item["sha256_before"]:
                raise SystemExit("backup is corrupt: " + item["backup"])
            shutil.copy2(item["backup"], dest)
            out("restored " + dest)
    out("restored operation " + entry["id"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("copy")
    c.add_argument("sources", nargs="+")
    c.add_argument("--to", required=True)
    c.add_argument("--apply", action="store_true")
    c.add_argument("--check-drift", action="store_true", help="abort when the installed game no longer matches the profile")
    r = sub.add_parser("restore")
    r.add_argument("--id")
    r.add_argument("--force", action="store_true")
    sub.add_parser("log")
    ap.add_argument("--profile")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "profile"))
    import game_profile
    profile = game_profile.load(args.profile)
    if args.cmd == "copy":
        if args.check_drift:
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "drift"))
            import check_drift
            rows = check_drift.check(profile)
            if check_drift.exit_code(rows) == 1:
                for status, what, expected, actual in rows:
                    if status == check_drift.DRIFT:
                        print("DRIFT %s: expected %s, actual %s" % (what, expected, actual))
                raise SystemExit("the game changed since the profile was recorded; nothing was copied")
        copy(profile, args.sources, args.to, args.apply)
    elif args.cmd == "restore":
        restore(profile, args.id, args.force)
    else:
        for e in read_log((profile.get("deploy") or {}).get("backupDir", "")):
            print(e["id"], e["time"], len(e["items"]), "file(s)")


if __name__ == "__main__":
    main()
