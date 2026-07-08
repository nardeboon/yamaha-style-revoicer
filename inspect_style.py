#!/usr/bin/env python3
"""
inspect_style.py — Reverse-engineering helper: show what a Yamaha style file uses.

Given a .STY / .PRS file, prints every drum kit and melodic voice it selects
(as MSB-LSB-PC addresses, with names if the lookup tables are present). This is
the first thing to run when adapting the converter to a new keyboard: it tells
you which source kits/voices you need to build maps for.

Usage:
    python inspect_style.py <path-to-style-file>
"""

import os
import sys
import json
import struct


def load_table(name):
    """Load a MSB-LSB-PC lookup table if it exists next to this script (optional)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def parse_program_changes(path):
    """
    Proper MTrk event parser. Returns a list of (channel, msb, lsb, pc) for every
    Program Change in the file, tracking the running Bank Select per channel.

    (This is the same event-walking logic the converter uses, minus the editing.)
    """
    data = open(path, "rb").read()
    if data[14:18] != b"MTrk":
        raise ValueError("Not an SFF style file (no MTrk at offset 14)")
    size = struct.unpack_from(">I", data, 18)[0]
    mtrk = data[22:22 + size]

    state = {ch: {"msb": 0, "lsb": 0} for ch in range(16)}
    events = []
    pos = 0
    while pos < len(mtrk):
        while pos < len(mtrk) and (mtrk[pos] & 0x80):   # skip VLQ delta
            pos += 1
        pos += 1
        if pos >= len(mtrk):
            break
        ev = mtrk[pos]
        pos += 1
        if ev == 0xFF:                                  # meta: skip type + length + data
            pos += 1
            ln = 0
            while pos < len(mtrk) and (mtrk[pos] & 0x80):
                ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            pos += ln
        elif ev in (0xF0, 0xF7):                        # sysex: skip length + data
            ln = 0
            while pos < len(mtrk) and (mtrk[pos] & 0x80):
                ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:                             # control change (bank select)
                cc, val = mtrk[pos], mtrk[pos + 1]; pos += 2
                if cc == 0x00:
                    state[ch]["msb"] = val
                elif cc == 0x20:
                    state[ch]["lsb"] = val
            elif typ == 0x0C:                           # program change
                pc = mtrk[pos]; pos += 1
                events.append((ch, state[ch]["msb"], state[ch]["lsb"], pc))
            elif typ == 0x0D:                           # channel aftertouch (1 byte)
                pos += 1
            else:                                       # note on/off, cc, pitch bend (2 bytes)
                pos += 2
    return events


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]

    or_voices = load_table("OR700_VOICE_TABLE.json")
    or_kits = load_table("OR700_DRUMKIT_TABLE.json")

    events = parse_program_changes(path)
    print(f"\n{os.path.basename(path)} — {len(events)} program changes\n")

    seen = set()
    for ch, msb, lsb, pc in events:
        key = (ch, msb, lsb, pc)
        if key in seen:
            continue
        seen.add(key)
        addr = f"{msb}-{lsb}-{pc}"
        is_drum = ch in (8, 9)
        table = or_kits if is_drum else or_voices
        name = table.get(addr, "?")
        tag = "DRUM" if is_drum else "    "
        print(f"  ch{ch + 1:<2} {tag}  {addr:12}  {name}")
    print()


if __name__ == "__main__":
    main()
