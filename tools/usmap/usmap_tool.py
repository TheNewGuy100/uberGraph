"""Reads an UNCOMPRESSED .usmap mapping file (version 4) and answers layout questions. Read-only; never writes the mapping.

A .usmap holds, for every class and struct, the names, types and ORDER of its serialized properties, plus enums. It does not hold
functions, the class each ObjectProperty points to, default values or flags. That is enough to know what a stand-in class in the
editor would have to look like for cooked assets that use unversioned property serialization (the property index in the asset
header is the position in this list, parents first).

    python tools/usmap/usmap_tool.py show CLASS               own properties, super chain, total index count
    python tools/usmap/usmap_tool.py closure CLASS [CLASS...]  the structs, enums and classes needed by these classes
    python tools/usmap/usmap_tool.py search TEXT               class/struct/enum names containing TEXT
The mapping path comes from the game profile (mappings.path); use --usmap PATH to override.
Compressed mappings (Oodle, Brotli, Zstd) are refused: the parser fails loudly instead of guessing.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "profile"))

TYPES = ["Byte", "Bool", "Int", "Float", "Object", "Name", "Delegate", "Double", "Array", "Struct", "Str", "Text", "Interface",
         "MulticastDelegate", "WeakObject", "LazyObject", "AssetObject", "SoftObject", "UInt64", "UInt32", "UInt16", "Int64",
         "Int16", "Int8", "Map", "Set", "Enum", "FieldPath", "Optional", "Utf8Str", "AnsiStr"]


class Usmap:
    def __init__(self, path):
        b = open(path, "rb").read()
        magic, version = struct.unpack_from("<HB", b, 0)
        if magic != 0x30C4:
            raise SystemExit("not a usmap file")
        o = 3
        if version >= 1:
            has_versioning, = struct.unpack_from("<i", b, o); o += 4
            if has_versioning:
                raise SystemExit("usmap with embedded versioning is not handled by this tool")
        compression, csize, usize = struct.unpack_from("<BII", b, o); o += 9
        if compression != 0:
            raise SystemExit("compressed usmap (method %d) is not supported; use an uncompressed mapping" % compression)
        self.version = version
        self.b, self.o = b, o
        n = self.u32()
        self.names = []
        for _ in range(n):
            length = self.u16() if version >= 2 else self.u8()
            self.names.append(self.take(length).decode("utf-8", "replace"))
        self.enums = {}
        for _ in range(self.u32()):
            name = self.names[self.i32()]
            count = self.u16() if version >= 3 else self.u8()
            values = []
            for i in range(count):
                if version >= 4:
                    value = self.i64()
                    values.append((self.names[self.i32()], value))
                else:
                    values.append((self.names[self.i32()], i))
            self.enums[name] = values
        self.schemas = {}
        for _ in range(self.u32()):
            name = self.names[self.i32()]
            sup = self.i32()
            prop_count, serializable = self.u16(), self.u16()
            props = []
            for _ in range(serializable):
                index, array_size = self.u16(), self.u8()
                pname = self.names[self.i32()]
                props.append({"index": index, "name": pname, "array": array_size, "type": self.type()})
            self.schemas[name] = {"super": self.names[sup] if sup >= 0 else None, "prop_count": prop_count, "props": props}
        if self.o != len(b):
            raise SystemExit("parse ended at %d of %d bytes: unknown property type or layout; the result would be wrong" % (self.o, len(b)))

    def take(self, n):
        v = self.b[self.o:self.o + n]; self.o += n; return v

    def u8(self): return struct.unpack("<B", self.take(1))[0]
    def u16(self): return struct.unpack("<H", self.take(2))[0]
    def u32(self): return struct.unpack("<I", self.take(4))[0]
    def i32(self): return struct.unpack("<i", self.take(4))[0]
    def i64(self): return struct.unpack("<q", self.take(8))[0]

    def type(self):
        t = self.u8()
        name = TYPES[t] if t < len(TYPES) else "Unknown%d" % t
        if name == "Enum":
            inner = self.type(); return {"t": "Enum", "inner": inner, "enum": self.names[self.i32()]}
        if name == "Struct":
            return {"t": "Struct", "struct": self.names[self.i32()]}
        if name in ("Array", "Set", "Optional"):
            return {"t": name, "inner": self.type()}
        if name == "Map":
            k = self.type(); return {"t": "Map", "key": k, "value": self.type()}
        if name.startswith("Unknown"):
            raise SystemExit("unknown property type id %d at byte %d" % (t, self.o))
        return {"t": name}

    # ---- queries
    def chain(self, cls):
        out = []
        while cls:
            out.append(cls)
            cls = self.schemas.get(cls, {}).get("super")
        return out

    def refs(self, t):
        """Names of structs and enums a property type refers to."""
        out = set()
        if t["t"] == "Struct": out.add(t["struct"])
        if t["t"] == "Enum": out.add(t["enum"])
        for key in ("inner", "key", "value"):
            if key in t: out |= self.refs(t[key])
        return out


def fmt(t):
    if t["t"] == "Struct": return "Struct(%s)" % t["struct"]
    if t["t"] == "Enum": return "Enum(%s)" % t["enum"]
    if t["t"] in ("Array", "Set", "Optional"): return "%s<%s>" % (t["t"], fmt(t["inner"]))
    if t["t"] == "Map": return "Map<%s,%s>" % (fmt(t["key"]), fmt(t["value"]))
    return t["t"]


def main(argv):
    path = None
    if "--usmap" in argv:
        i = argv.index("--usmap"); path = argv[i + 1]; del argv[i:i + 2]
    if not path:
        import game_profile
        path = game_profile.get(game_profile.load(), "mappings.path")
    if not path:
        raise SystemExit("no mapping path (profile mappings.path or --usmap)")
    if len(argv) < 2:
        print(__doc__); return 2
    u = Usmap(path)
    cmd, args = argv[0], argv[1:]
    if cmd == "search":
        needle = args[0].lower()
        for name in sorted(list(u.schemas) + list(u.enums)):
            if needle in name.lower():
                print(("enum   " if name in u.enums and name not in u.schemas else "schema ") + name)
    elif cmd == "show":
        cls = args[0]
        if cls not in u.schemas: raise SystemExit("not found: " + cls)
        chain = u.chain(cls)
        print("super chain:", " < ".join(chain))
        print("total property indices (incl. parents): %d" % u.schemas[cls]["prop_count"])
        for c in reversed(chain):
            s = u.schemas.get(c)
            if s is None:
                print("  %s: (not in mapping: an engine class resolved by the editor)" % c); continue
            print("  %s: %d own" % (c, len(s["props"])))
            if c == cls:
                for p in s["props"]:
                    print("    [%3d] %s : %s%s" % (p["index"], p["name"], fmt(p["type"]), "[%d]" % p["array"] if p["array"] > 1 else ""))
    elif cmd == "closure":
        seen_schemas, seen_enums, todo = set(), set(), list(args)
        while todo:
            n = todo.pop()
            if n in u.enums: seen_enums.add(n); continue
            if n in seen_schemas: continue
            if n not in u.schemas:
                continue
            seen_schemas.add(n)
            s = u.schemas[n]
            if s["super"]: todo.append(s["super"])
            for p in s["props"]:
                todo.extend(u.refs(p["type"]))
        print("seeds:", ", ".join(args))
        print("classes/structs needed: %d (properties: %d); enums: %d" % (len(seen_schemas), sum(len(u.schemas[n]["props"]) for n in seen_schemas), len(seen_enums)))
        print("schemas:", ", ".join(sorted(seen_schemas)))
        print("enums:", ", ".join(sorted(seen_enums)))
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
