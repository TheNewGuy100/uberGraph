"""Read-only x64 displacement candidates and unwind-chain bounds. Confirm with disassembly."""
import argparse
import bisect
import datetime
import json
import re
import struct
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("exe", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--displacement", type=lambda v: int(v, 0))
    ap.add_argument("--address", action="append", default=[], type=lambda v: int(v, 0))
    args = ap.parse_args()
    b = args.exe.read_bytes()
    pe = struct.unpack_from("<I", b, 60)[0]
    opt = pe + 24
    base = struct.unpack_from("<Q", b, opt + 24)[0]
    size = struct.unpack_from("<H", b, pe + 20)[0]
    sections = []
    for i in range(struct.unpack_from("<H", b, pe + 6)[0]):
        a = opt + size + i * 40
        vs, rv, rs, rp = struct.unpack_from("<IIII", b, a + 8)
        sections.append((b[a:a + 8].split(b"\0")[0], rv, rs, rp, vs))

    def raw(rva):
        for _, rv, rs, rp, _ in sections:
            if rv <= rva < rv + rs:
                return rp + rva - rv
        raise ValueError("RVA not file-backed")

    pd = next(s for s in sections if s[0] == b".pdata")
    ranges = sorted(r for a in range(pd[3], pd[3] + pd[4] - 11, 12)
                    if (r := struct.unpack_from("<III", b, a))[0] < r[1])
    starts = [r[0] for r in ranges]

    def unwind(va):
        index = bisect.bisect_right(starts, va - base) - 1
        record = ranges[index] if index >= 0 and va - base < ranges[index][1] else None
        chain = []
        for _ in range(16):
            if record is None:
                break
            st, en, uw = record
            at = raw(uw)
            flags, count = b[at] >> 3, b[at + 2]
            chain.append(dict(start=hex(base + st), end_exclusive=hex(base + en), flags=flags))
            if not flags & 4:
                break
            record = struct.unpack_from("<III", b, at + ((4 + 2 * count + 3) & ~3))
        return chain

    hits = []
    if args.displacement is not None:
        for name, rv, rs, rp, _ in sections:
            if name != b".text":
                continue
            # Limited REX + LEA/MOV, mod=10, non-SIB base, disp32 forms.
            for m in re.finditer(rb"[\x48-\x4f][\x8d\x8b\x89][\x80-\xbf]....", b[rp:rp + rs], re.S):
                if m.group()[2] & 7 == 4:
                    continue
                if struct.unpack_from("<i", m.group(), 3)[0] == args.displacement:
                    va = base + rv + m.start()
                    hits.append(dict(va=hex(va), bytes=m.group().hex(), unwind_chain=unwind(va)))
    addresses = []
    for address in args.address:
        chain = unwind(address)
        related = []
        if chain:
            root = int(chain[-1]["start"], 16)
            for start, end, _ in ranges:
                candidate = base + start
                if root <= candidate < root + 0x10000:
                    candidate_chain = unwind(candidate)
                    if candidate_chain and candidate_chain[-1]["start"] == hex(root):
                        related.append(dict(start=hex(candidate), end_exclusive=hex(base + end)))
        addresses.append(dict(va=hex(address), unwind_chain=chain, related_chunks_within_64k=related))
    result = dict(timestamp=datetime.datetime.now().isoformat(), displacement=args.displacement, candidates=hits,
                  addresses=addresses,
                  limitations=["Limited byte patterns, not exhaustive disassembly or proof of field identity.",
                               "Unwind chains identify chunks; full function body may include additional ranges."])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
