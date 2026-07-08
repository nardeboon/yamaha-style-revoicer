#!/usr/bin/env python3
"""
analyze.py — Reproducible verification/diagnostics for the converted styles.

Consolidates the checks that were previously run ad-hoc: chunk integrity, drum
channels vs CASM roles, per-role volume, velocity level, drum-note range, and OTS
presence. Run it after a conversion to confirm the output is healthy.

Usage:
    python analyze.py                       # analyze Iranian-Combined-CVP805/
    python analyze.py <folder>              # analyze another output folder
"""

import os
import sys
import glob
import struct
import statistics
from collections import Counter, defaultdict

# reuse the CASM role parser + reference tables from the PSR converter
from convert_psr_iranian import (casm_roles, clean_name, style_name, REF_ROLE,
                                  DRUM_ROLES, SRC_FOLDERS, PRO_VEL_MEDIAN)


def _events(path):
    """Walk an MTrk body yielding ('cc'|'note'|'pc', ch, a, b). Also returns the
    tempo (BPM) and whether chunks are structurally sound."""
    d = open(path, "rb").read()
    if d[14:18] != b"MTrk":
        return None
    size = struct.unpack_from(">I", d, 18)[0]
    mt = d[22:22 + size]
    st = {c: {"m": 0, "l": 0} for c in range(16)}
    out, bpm = [], None
    pos = 0
    while pos < len(mt):
        while pos < len(mt) and (mt[pos] & 0x80):
            pos += 1
        pos += 1
        if pos >= len(mt):
            break
        ev = mt[pos]; pos += 1
        if ev == 0xFF:
            mtype = mt[pos]; pos += 1; ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            if mtype == 0x51 and bpm is None:
                bpm = round(6e7 / ((mt[pos] << 16) | (mt[pos + 1] << 8) | mt[pos + 2]))
            pos += ln
        elif ev in (0xF0, 0xF7):
            ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1; pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:
                cc, v = mt[pos], mt[pos + 1]; pos += 2
                if cc == 0x00: st[ch]["m"] = v
                elif cc == 0x20: st[ch]["l"] = v
                out.append(("cc", ch, cc, v))
            elif typ == 0x0C:
                out.append(("pc", ch, st[ch]["m"], mt[pos])); pos += 1
            elif typ == 0x09:
                out.append(("note", ch, mt[pos], mt[pos + 1])); pos += 2
            elif typ in (0x08, 0x0E):
                pos += 2
            elif typ == 0x0D:
                pos += 1
            else:
                pos += 2
    return out, bpm


def _chunk_ok(path):
    """True if MThd/MTrk/CASM/(OTSc) chunk sizes are internally consistent."""
    d = open(path, "rb").read()
    if d[14:18] != b"MTrk":
        return False, []
    pos = 8 + struct.unpack_from(">I", d, 4)[0]
    tags = []
    while pos + 8 <= len(d):
        tag = d[pos:pos + 4]
        if not all(32 <= b < 127 for b in tag):
            return False, tags
        sz = struct.unpack_from(">I", d, pos + 4)[0]
        tags.append(tag.decode()); pos += 8 + sz
    return pos == len(d), tags


def _src_map(base):
    """Map each output filename back to its source style (for CASM roles)."""
    used, m = {}, {}
    for folder in SRC_FOLDERS:
        for f in sorted(glob.glob(os.path.join(base, folder, "*.sty"))):
            nm = clean_name(style_name(f) or "?")
            n = used.get(nm.lower(), 0) + 1; used[nm.lower()] = n
            m[nm if n == 1 else f"{nm} ({n})"] = f
    return m


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    folder = sys.argv[1] if len(sys.argv) > 1 else "Iranian-Combined-CVP805"
    files = sorted(glob.glob(os.path.join(base, folder, "*.sty")))
    src_map = _src_map(base)
    print(f"Analyzing {len(files)} files in {folder}/\n")

    bad_chunk, has_ots, vol_by_role = 0, 0, defaultdict(list)
    loud_notroled, melodic_on_drum, allvel, tempos = [], [], [], []
    drum_note_oor = 0
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        # extract style name (before [Genre] tag if present)
        if '[' in stem:
            stem = stem[:stem.rfind('[')].strip()
        roles = casm_roles(src_map[stem]) if stem in src_map else {}
        ok, tags = _chunk_ok(f)
        if not ok:
            bad_chunk += 1
        if "OTSc" in tags:
            has_ots += 1
        ev, bpm = _events(f)
        if bpm:
            tempos.append(bpm)
        drum_ch = {c for c, r in roles.items() if r in DRUM_ROLES}
        for kind, ch, a, b in ev:
            role = roles.get(ch, "")
            if kind == "cc" and a == 0x07 and role in REF_ROLE:
                vol_by_role[role].append(b)
            elif kind == "cc" and a == 0x07 and b > 70:
                loud_notroled.append((os.path.basename(f), ch + 1, b))
            elif kind == "pc" and ch in drum_ch and a not in (126, 127):
                melodic_on_drum.append((os.path.basename(f), ch + 1))
            elif kind == "note" and b > 0:
                allvel.append(b)
                if ch in drum_ch and not (13 <= a <= 84):
                    drum_note_oor += 1

    print(f"chunk integrity : {len(files) - bad_chunk}/{len(files)} valid ; OTS present: {has_ots}")
    print(f"melodic voice on a real drum channel : {len(melodic_on_drum)} "
          f"{melodic_on_drum[:3]}")
    print(f"CC7 > 70 on a non-role channel       : {len(loud_notroled)}")
    print(f"drum notes outside kit range (13-84) : {drum_note_oor}")
    if allvel:
        print(f"velocity median : {int(statistics.median(allvel))} (pro ref {PRO_VEL_MEDIAN})")
    if tempos:
        print(f"tempo range     : {min(tempos)}-{max(tempos)} BPM (median {int(statistics.median(tempos))})")
    print("\nvolume median per role (target in parens):")
    for role in ("Rhythm1", "Rhythm2", "Bass", "Chord1", "Chord2", "Pad", "Phrase1", "Phrase2"):
        v = vol_by_role.get(role)
        if v:
            print(f"  {role:8}: {int(statistics.median(v)):>3} (ref {REF_ROLE[role]})")


if __name__ == "__main__":
    main()
