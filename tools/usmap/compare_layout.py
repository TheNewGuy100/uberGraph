"""Compares editor layouts (tools/ue-editor/examples/dump_layouts.py) with the game's usmap, struct by struct. Read-only.

    python tools/usmap/compare_layout.py LAYOUTS.json [--usmap PATH]

For every struct in the editor dump's super chains that also exists in the mapping it reports one of:
  SAME      the mapping's property list equals the editor's (names, types, order) once editor-only and transient-only extras are ignored
  DIFFERENT the first difference is printed (this means cooked data of that struct would be read wrongly)
  ABSENT    the struct is not in the mapping (not used by the game's serialized data, or named differently)
A DIFFERENT result for an engine class is the risk this check exists for (game engine 5.8.1 versus editor 5.8.4).
Type notation: usmap_tool.fmt. Byte properties with an enum are compared as Byte because the mapping does not record the enum.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "profile"))
import usmap_tool  # noqa: E402


def norm_editor(t):
    """Editor-side type text in the mapping's notation. Differences that do not change the serialized bytes are folded:
    TEnumAsByte (editor: a byte property with an enum) is exported by the mapping as an enum property; both are compared as Enum(Name), and sparse multicast
    delegates are exported as plain multicast delegates."""
    import re
    t = re.sub(r"Byte\(Enum ([A-Za-z0-9_]+)\)", r"Enum(\g<1>)", t)  # also inside Array<>, Map<,> ...
    return t.replace("MulticastSparseDelegate", "MulticastDelegate")


def norm_mapping(t):
    if t["t"] == "Enum":
        return "Enum(%s)" % t["enum"]
    return usmap_tool.fmt(t)


def mapping_props(u, name):
    # names are compared case-insensitively: the game's Rotator exports "pitch" where the editor has "Pitch"; unversioned
    # serialization uses the position, not the name
    return [(p["name"].lower(), norm_mapping(p["type"]), p["array"]) for p in u.schemas[name]["props"]]


def editor_props(entry):
    return [(p["name"].lower(), norm_editor(p["type"]), p["array"]) for p in entry["props"] if not p["editor_only"]]


def compare(u, name, entry):
    if name not in u.schemas:
        return "ABSENT", ""
    m, e = mapping_props(u, name), editor_props(entry)
    e_names = [x[0] for x in e]
    # the mapping lists only serialized properties; transient ones may be missing from it
    e_ser = [x for x in e if x in m or x[0] in {y[0] for y in m}]
    for i, (a, b) in enumerate(zip(m, e_ser)):
        if a != b:
            return "DIFFERENT", "position %d: mapping %s, editor %s" % (i, a, b)
    if len(m) != len(e_ser):
        return "DIFFERENT", "mapping has %d properties, editor has %d matching; mapping tail %s, editor tail %s" % (len(m), len(e_ser), m[len(e_ser):][:3], e_ser[len(m):][:3])
    return "SAME", "%d properties" % len(m)


def main(argv):
    path = None
    if "--usmap" in argv:
        i = argv.index("--usmap"); path = argv[i + 1]; del argv[i:i + 2]
    if not argv:
        print(__doc__); return 2
    if not path:
        import game_profile
        path = game_profile.get(game_profile.load(), "mappings.path")
    u = usmap_tool.Usmap(path)
    data = json.load(open(argv[0], encoding="utf-8"))
    print("editor:", data.get("engine"))
    seen, counts = set(), {"SAME": 0, "DIFFERENT": 0, "ABSENT": 0}
    for layout in data["layouts"]:
        if not layout.get("found"):
            print("NOT FOUND IN EDITOR:", layout.get("requested")); continue
        for name, entry in layout["structs"].items():
            if name in seen:
                continue
            seen.add(name)
            status, detail = compare(u, name, entry)
            counts[status] += 1
            print("%-9s %-34s %s" % (status, name, detail))
    print("summary:", counts)
    return 1 if counts["DIFFERENT"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
