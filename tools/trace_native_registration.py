"""Read-only PE string/pointer/RIP-relative triage; candidates are not proven functions."""
import argparse
import bisect
import datetime
import hashlib
import json
import re
import struct
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("exe", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("terms", nargs="+")
    args = ap.parse_args()
    data = args.exe.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise SystemExit("not a PE")
    machine, count = struct.unpack_from("<HH", data, pe + 4)
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    if machine != 0x8664 or struct.unpack_from("<H", data, opt)[0] != 0x20B:
        raise SystemExit("requires x64 PE32+")
    base = struct.unpack_from("<Q", data, opt + 24)[0]
    sections = []
    for i in range(count):
        at = opt + opt_size + 40 * i
        name = data[at:at + 8].split(b"\0")[0].decode("ascii")
        size, rva, raw_size, raw = struct.unpack_from("<IIII", data, at + 8)
        flags = struct.unpack_from("<I", data, at + 36)[0]
        sections.append(dict(name=name, size=size, rva=rva, raw_size=raw_size, raw=raw, executable=bool(flags & 0x20000000)))

    def va_of(off):
        for s in sections:
            if s["raw"] <= off < s["raw"] + s["raw_size"]:
                return base + s["rva"] + off - s["raw"]
        return None

    def raw_of(va):
        for s in sections:
            off = va - base - s["rva"]
            if 0 <= off < s["raw_size"]:
                return s["raw"] + off
        return None

    pdata = next(s for s in sections if s["name"] == ".pdata")
    ranges = sorted(r for at in range(pdata["raw"], pdata["raw"] + pdata["raw_size"] - 11, 12)
                    if (r := struct.unpack_from("<III", data, at))[0] < r[1])
    starts = [r[0] for r in ranges]

    def containing(va):
        if va is None:
            return None
        index = bisect.bisect_right(starts, va - base) - 1
        if index >= 0:
            start, end, _ = ranges[index]
            if start <= va - base < end:
                return {"start": hex(base + start), "end_exclusive": hex(base + end)}
        return None

    hits = []
    for term in args.terms:
        for encoding in ("ascii", "utf-16le"):
            needle = (term + "\0").encode(encoding)
            pos = 0
            while (off := data.find(needle, pos)) >= 0:
                pos = off + 1
                va = va_of(off)
                if va is not None:
                    hits.append(dict(term=term, encoding=encoding, file_offset=hex(off), va=hex(va), pointers=[], rip_candidates=[]))
    by_va = {int(h["va"], 16): h for h in hits}
    for va, hit in by_va.items():
        pos = 0
        needle = struct.pack("<Q", va)
        while (off := data.find(needle, pos)) >= 0:
            pos = off + 1
            neighbors = []
            for at in range(max(0, off - 16), min(len(data) - 7, off + 32), 8):
                value = struct.unpack_from("<Q", data, at)[0]
                neighbors.append(dict(at=hex(va_of(at) or 0), value=hex(value), function_range=containing(value)))
            hit["pointers"].append(dict(file_offset=hex(off), va=hex(va_of(off) or 0), neighbors=neighbors))
    # Limited common x64 RIP-relative LEA/MOV forms. Confirm with a real disassembler.
    for s in sections:
        if not s["executable"]:
            continue
        chunk = data[s["raw"]:s["raw"] + s["raw_size"]]
        for m in re.finditer(rb"[\x48-\x4f][\x8d\x8b][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....", chunk, re.DOTALL):
            off = s["raw"] + m.start()
            va = va_of(off)
            target = va + 7 + struct.unpack_from("<i", data, off + 3)[0]
            if target in by_va:
                by_va[target]["rip_candidates"].append(dict(va=hex(va), bytes=data[off:off + 7].hex(), function_range=containing(va)))
    out = dict(timestamp=datetime.datetime.now().isoformat(), target=dict(path=str(args.exe), bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), architecture="x86-64", image_base=hex(base)), sections=sections, hits=hits,
               limitations=["Byte-pattern candidates require disassembly confirmation.", "Pointer adjacency is not proof of table semantics.", ".pdata entries are unwind ranges, not guaranteed complete semantic function bodies."])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
