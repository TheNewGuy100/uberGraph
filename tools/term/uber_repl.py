"""Prompt of the Ubergraph terminal: type bridge commands while the log scrolls (python tools/term/uber_term.py --repl).

    help                          this list
    ping | status | health        the bridge's own state (health reads the heartbeat, sends nothing)
    cvar NAME                     read a console variable (cvar_get)
    console COMMAND...            one allow-listed console command (console_exec; the bridge refuses it unless allow_console is on)
    OP [words...]                 any other bridge operation with the words of tools/bridge/bridge_client.py, e.g.
                                  find_all PlayerController 5 | describe_class /Script/Voyage.VoyageSkill 5 | get pawn BaseEyeHeight
    settings                      shows the bridge settings (read-only; changing a risky option stays with tools/bridge/bridge_settings.py,
                                  which needs the operator's own words)
    quit | exit                   leave

The risky operations (load_asset, watch_function, console_exec) are refused by the bridge itself while their option is off; this prompt
never turns an option on.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bridge"))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))

ALIASES = {"cvar": "cvar_get", "console": "console_exec"}
RISKY = {"load_asset", "watch_function", "console_exec"}
HELP = __doc__.strip()


def parse_line(line):
    """Returns ('empty',) | ('help',) | ('quit',) | ('settings',) | ('health',) | ('op', op, words)."""
    words = line.strip().split()
    if not words:
        return ("empty",)
    head = words[0].lower()
    if head in ("help", "?"):
        return ("help",)
    if head in ("quit", "exit"):
        return ("quit",)
    if head in ("settings", "health"):
        return (head,)
    op = ALIASES.get(head, head)
    return ("op", op, words[1:])


def format_response(response, color=False):
    """Text for one bridge response: the result as indented JSON, or the error."""
    red, reset = ("\x1b[1;31m", "\x1b[0m") if color else ("", "")
    if response.get("ok"):
        return json.dumps(response.get("result"), indent=2, ensure_ascii=False)
    error = str(response.get("error", "unknown error"))
    text = red + "ERROR " + error + reset
    if "disabled" in error:
        text += "\n  risky option, off by default: it is turned on only with the operator's words (tools/bridge/bridge_settings.py set <key> true --user-approved \"...\")"
    return text


def execute(parsed, send, health, settings, color=False):
    """Runs one parsed command and returns the text to print (None to quit). send(op, rest) -> response dict."""
    kind = parsed[0]
    if kind == "empty":
        return ""
    if kind == "quit":
        return None
    if kind == "help":
        return HELP
    if kind == "health":
        return json.dumps(health(), indent=2)
    if kind == "settings":
        return settings()
    _, op, words = parsed
    try:
        return format_response(send(op, words), color)
    except SystemExit as exc:  # bridge_client reports usage problems and a missing heartbeat this way
        return ("\x1b[1;31m" if color else "") + str(exc) + ("\x1b[0m" if color else "")
    except Exception as exc:  # keep the prompt alive
        return "ERROR %s: %s" % (type(exc).__name__, exc)


def run(profile, color, out=sys.stdout, read=input):
    import bridge_client
    import bridge_settings

    io = bridge_client.io_dir(profile)

    def send(op, words):
        return bridge_client.request(io, op, bridge_client.parse_args(op, words))

    def settings():
        values = bridge_settings.read(bridge_settings.settings_path(profile))
        return json.dumps(values, indent=2)

    out.write("type 'help' for the commands, 'quit' to leave\n")
    while True:
        try:
            line = read("uber> ")
        except (EOFError, KeyboardInterrupt):
            break
        text = execute(parse_line(line), send, lambda: bridge_client.health(io), settings, color)
        if text is None:
            break
        if text:
            out.write(text + "\n")
            out.flush()
