"""Ubergraph terminal: follows the UE4SS log of the game in the profile and shows it classified and coloured.

The colour lives only here, on the screen of whoever looks. The log file stays plain text (no escape characters), so it can still be read with
grep, and the in-game console (a proportional-font GUI that does not interpret ANSI) is not touched.

    python tools/term/uber_term.py                       follow the log from now on (waits for the game)
    python tools/term/uber_term.py --from-start          show what is already in the log first, then follow
    python tools/term/uber_term.py --once                print the whole log classified and exit (also for a file: --log PATH)
    python tools/term/uber_term.py --only bridge,probes  only these components (bridge, probes, lua, ue4ss, other)
    python tools/term/uber_term.py --level warn          only WARN and above (info < warn < error < fatal)
    python tools/term/uber_term.py --grep TEXT           only entries containing TEXT (case-insensitive)
    python tools/term/uber_term.py --no-color            plain text (also when the output is not a terminal)

Line format read: "[2026-10-28 00:10:56.1912600] [Lua] [uberGraph] Probes/chest: WARN no pawn". Continuation lines (stack traces, tabs, text
without a timestamp) belong to the entry before them. Classification rules live in classify(), one place, tested in test_uber_term.py.
"""
import argparse
import ctypes
import os
import re
import shutil
import sys
import textwrap
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))

LEVELS = {"info": 0, "warn": 1, "error": 2, "fatal": 3}
ENTRY = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\] (.*)$")
LUA_TAG = re.compile(r"^\[Lua\] (.*)$", re.S)
UBER = re.compile(r"^\[uberGraph\] (Bridge|bridge|Probes|probes)(?:/([\w\-]+))?:? ?(.*)$", re.S)
LEVEL_WORD = re.compile(r"^(INFO|WARN|WARNING|ERROR|FATAL)\b[: ]?(.*)$", re.S)
FATAL_HINTS = ("access violation", "fatal error", "unhandled exception", "exception_access_violation", "crash")
ERROR_HINTS = re.compile(r"\b(error|failed|unfinished string|attempt to)\b", re.I)
DUMP_FIELD = re.compile(r"= 0x[0-9a-fA-F]+\s*$")  # property dumps such as "FArchiveState::ArIsError = 0x29" are not errors
WARN_HINTS = ("warning", "could not", "not found", "deprecated")

RESET = "\x1b[0m"
STYLE = {
    "bridge": "\x1b[36m",    # cyan
    "probes": "\x1b[35m",    # magenta
    "lua": "\x1b[37m",       # white
    "other": "\x1b[37m",
    "ue4ss": "\x1b[90m",     # grey
    "warn": "\x1b[33m",      # yellow
    "error": "\x1b[1;31m",   # bold red
    "fatal": "\x1b[1;37;41m",
    "time": "\x1b[90m",
    "dim": "\x1b[2m",
}

BANNER = r"""
██    ██ ██████  ███████ ██████   ██████  ██████   █████  ██████  ██   ██
██    ██ ██   ██ ██      ██   ██ ██       ██   ██ ██   ██ ██   ██ ██   ██
██    ██ ██████  █████   ██████  ██   ███ ██████  ███████ ██████  ███████
██    ██ ██   ██ ██      ██   ██ ██    ██ ██   ██ ██   ██ ██      ██   ██
 ██████  ██████  ███████ ██   ██  ██████  ██   ██ ██   ██ ██      ██   ██
""".strip("\n")
SLOGAN = "Build. Bridge. Play."
TAG_WIDTH = 24


def classify(line):
    """Returns (kind, component, section, level, text, time) for one log line. kind is 'entry' or 'cont' (a continuation line, no timestamp)."""
    stripped = line.rstrip("\r\n")
    m = ENTRY.match(stripped)
    if not m:
        return {"kind": "cont", "text": stripped}
    stamp, rest = m.group(1), m.group(2)
    component, section, level, text = "ue4ss", "", "info", rest
    lua = LUA_TAG.match(rest)
    if lua:
        component, text = "lua", lua.group(1)
        u = UBER.match(text)
        if u:
            component, section, text = u.group(1).lower(), u.group(2) or "", u.group(3)
        else:
            named = re.match(r"^\[([\w\- ]+)\] ?(.*)$", text, re.S)
            if named:
                component, section, text = "other", named.group(1), named.group(2)
    w = LEVEL_WORD.match(text)
    if w:
        level = "warn" if w.group(1) in ("WARN", "WARNING") else w.group(1).lower()
        text = w.group(2)
    else:
        low = text.lower()
        if any(h in low for h in FATAL_HINTS):
            level = "fatal"
        elif ERROR_HINTS.search(text) and not DUMP_FIELD.search(text):
            level = "error"
        elif any(h in low for h in WARN_HINTS):
            level = "warn"
    return {"kind": "entry", "time": stamp, "component": component, "section": section, "level": level, "text": text}


def paint(entry, color, width=0):
    """One display (possibly wrapped, with a hanging indent) string for a classified entry. width 0 means no wrapping."""
    if entry["kind"] == "cont":
        return (STYLE["dim"] + entry["text"] + RESET) if color else entry["text"]
    if entry["component"] == "other":
        tag = entry["section"] or "other"
    else:
        tag = {"bridge": "bridge", "probes": "Probes"}.get(entry["component"], entry["component"])
        if entry["section"]:
            tag += "/" + entry["section"]
    if len(tag) > TAG_WIDTH:
        tag = tag[: TAG_WIDTH - 1] + "~"
    body = entry["text"]
    mark = "" if (color or entry["level"] == "info") else entry["level"].upper() + " "
    indent = 9 + TAG_WIDTH + 1
    if width and width > indent + 20:
        body = ("\n" + " " * indent).join(textwrap.wrap(mark + body, width - indent - 1) or [""])
    elif mark:
        body = mark + body
    if not color:
        return "%s %-*s %s" % (entry["time"][11:], TAG_WIDTH, tag, body)
    style = STYLE[entry["level"]] if entry["level"] != "info" else STYLE.get(entry["component"], "")
    return STYLE["time"] + entry["time"][11:] + RESET + " " + STYLE.get(entry["component"], "") + ("%-*s" % (TAG_WIDTH, tag)) + RESET + " " + style + body + RESET


def keep(entry, only, level, needle):
    if entry["kind"] != "entry":
        return None  # decided by the entry before it
    if only and entry["component"] not in only:
        return False
    if LEVELS[entry["level"]] < LEVELS[level]:
        return False
    if needle and needle not in entry["text"].lower():
        return False
    return True


def enable_ansi():
    """Windows 10+: turn on virtual terminal processing for stdout (a no-op elsewhere)."""
    if os.name != "nt":
        return True
    try:
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


def log_path(profile):
    import game_profile
    ue4ss = game_profile.get(profile, "ue4ss.dir")
    if not ue4ss:
        raise SystemExit("profile has no ue4ss.dir")
    return os.path.join(ue4ss, "UE4SS.log")


class Filter:
    """Applies keep() and carries the decision over to continuation lines."""

    def __init__(self, only, level, needle):
        self.only, self.level, self.needle = only, level, needle
        self.last = True

    def __call__(self, entry):
        verdict = keep(entry, self.only, self.level, self.needle)
        if verdict is None:
            return self.last
        self.last = verdict
        return verdict


def follow(path, from_start, once, flt, color, out=sys.stdout, poll=0.3, stop=lambda: False, width=0):
    """Reads the log; reopens it when the game recreates it (the file shrinks), waits while it does not exist."""
    position = 0 if (from_start or once) else None
    inode_size = -1
    while not stop():
        try:
            size = os.path.getsize(path)
        except OSError:
            if once:
                raise SystemExit("log not found: " + path)
            time.sleep(poll)
            continue
        if position is None:
            position = size
        if size < position:  # the game restarted and truncated the log
            out.write((STYLE["dim"] + "--- log restarted ---" + RESET if color else "--- log restarted ---") + "\n")
            position = 0
        if size > position:
            with open(path, "rb") as handle:
                handle.seek(position)
                chunk = handle.read(size - position)
            text = chunk.decode("utf-8", errors="replace")
            if not text.endswith("\n") and not once:
                cut = text.rfind("\n")
                text = text[: cut + 1] if cut >= 0 else ""
            position += len(text.encode("utf-8", errors="replace"))
            for line in text.splitlines():
                entry = classify(line)
                if flt(entry):
                    out.write(paint(entry, color, width) + "\n")
            out.flush()
        if once:
            return
        time.sleep(poll)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Ubergraph terminal: follows UE4SS.log, classified and coloured.")
    ap.add_argument("--log", help="log file (default: the UE4SS.log of the game profile)")
    ap.add_argument("--from-start", action="store_true", help="show the existing log first")
    ap.add_argument("--once", action="store_true", help="print the whole log and exit")
    ap.add_argument("--only", default="", help="comma list of components: bridge, probes, lua, other, ue4ss")
    ap.add_argument("--level", default="info", choices=sorted(LEVELS, key=LEVELS.get))
    ap.add_argument("--grep", default="", help="only entries containing this text")
    ap.add_argument("--no-color", action="store_true")
    ap.add_argument("--no-banner", action="store_true")
    ap.add_argument("--repl", action="store_true", help="also open a prompt that sends commands to the bridge (see uber_repl.py)")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    color = not args.no_color and sys.stdout.isatty() and enable_ansi()
    path = args.log
    if not path:
        import game_profile
        path = log_path(game_profile.load())
    if not args.no_banner and not args.once:
        print((STYLE["bridge"] if color else "") + BANNER + (RESET if color else ""))
        print((STYLE["probes"] if color else "") + SLOGAN + (RESET if color else "") + "   following " + path + "\n")
    only = {p.strip().lower() for p in args.only.split(",") if p.strip()}
    flt = Filter(only, args.level, args.grep.lower())
    if args.repl:
        import threading
        import game_profile
        import uber_repl
        width = shutil.get_terminal_size((120, 30)).columns
        threading.Thread(target=follow, args=(path, args.from_start, False, flt, color), kwargs={"width": width}, daemon=True).start()
        uber_repl.run(game_profile.load(), color)
        return 0
    try:
        follow(path, args.from_start, args.once, flt, color, width=shutil.get_terminal_size((120, 30)).columns if sys.stdout.isatty() else 0)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
