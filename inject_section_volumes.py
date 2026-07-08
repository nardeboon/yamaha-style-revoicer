#!/usr/bin/env python3
"""
inject_section_volumes.py — Add CC7 (volume) events at section boundaries.

Takes a valid converted style file and injects CC7 for each channel at the start
of every section (Intro, Main A/B/C/D, Fill, Ending). Uses the channel's already-
set CC7 value from earlier in the file as the template.

Safer than modifying normalize_to_reference because it works on an already-valid
file and uses a cleaner injection strategy.
"""

import sys
import struct
import os


def vlq_encode(value):
    """Encode a variable-length quantity."""
    result = bytearray()
    result.append(value & 0x7f)
    value >>= 7
    while value > 0:
        result.insert(0, (value & 0x7f) | 0x80)
        value >>= 7
    return bytes(result)


def vlq_decode(data, pos):
    """Decode VLQ; return (value, new_pos)."""
    val = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        val = (val << 7) | (b & 0x7f)
        if not (b & 0x80):
            break
    return val, pos


def inject_section_cc7(path):
    """Add CC7 at section boundaries if missing. Modifies file in-place."""
    data = bytearray(open(path, "rb").read())

    # Find MTrk chunk
    if data[14:18] != b"MTrk":
        raise ValueError("Not a valid style file (no MTrk)")

    mtrk_size = struct.unpack_from(">I", data, 18)[0]
    mtrk_body = bytes(data[22:22 + mtrk_size])

    # First pass: find sections and collect CC7 values
    sections = []  # [(section_name, byte_pos_in_mtrk), ...]
    cc7_by_ch = {}  # ch -> last CC7 value seen
    pos = 0

    while pos < len(mtrk_body):
        delta_start = pos
        while pos < len(mtrk_body) and (mtrk_body[pos] & 0x80):
            pos += 1
        pos += 1

        if pos >= len(mtrk_body):
            break

        ev = mtrk_body[pos]
        pos += 1

        if ev == 0xFF:  # meta event
            mtype = mtrk_body[pos]
            pos += 1
            ln, pos = vlq_decode(mtrk_body, pos)
            data_start = pos
            pos += ln

            if mtype == 0x06:  # section marker
                sections.append((mtrk_body[data_start:pos - ln].decode('latin1', 'ignore').strip('\x00'), delta_start))
        elif ev in (0xF0, 0xF7):  # sysex
            ln, pos = vlq_decode(mtrk_body, pos)
            pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:  # CC
                cc, val = mtrk_body[pos], mtrk_body[pos + 1]
                pos += 2
                if cc == 0x07:  # Main Volume
                    cc7_by_ch[ch] = val
            elif typ in (0x0C, 0x0D):
                pos += 1
            else:
                pos += 2

    # Second pass: inject CC7 at section boundaries
    # Build a new MTrk body by inserting CC7 events right after section markers
    if not sections or not cc7_by_ch:
        # Nothing to inject
        return

    out = bytearray()
    pos = 0
    section_idx = 0

    while pos < len(mtrk_body):
        delta_start = pos
        while pos < len(mtrk_body) and (mtrk_body[pos] & 0x80):
            pos += 1
        pos += 1
        delta = mtrk_body[delta_start:pos]

        if pos >= len(mtrk_body):
            break

        ev = mtrk_body[pos]
        pos += 1

        if ev == 0xFF:  # meta event
            mtype = mtrk_body[pos]
            pos += 1
            ln_start = pos
            ln, ln_pos = vlq_decode(mtrk_body, pos)
            pos = ln_pos + ln

            # output the meta event
            out += delta + bytes([ev, mtype]) + mtrk_body[ln_start:pos]

            # if this was a section marker, inject CC7 for all channels after it
            if mtype == 0x06 and section_idx < len(sections):
                section_name = sections[section_idx][0]
                section_idx += 1

                # inject CC7 for all channels that have a value (delta time = 0)
                for ch in sorted(cc7_by_ch.keys()):
                    cc7_val = cc7_by_ch[ch]
                    out += bytes([0x00, 0xB0 | ch, 0x07, cc7_val])
        elif ev in (0xF0, 0xF7):  # sysex
            ln_start = pos
            ln, ln_pos = vlq_decode(mtrk_body, pos)
            pos = ln_pos + ln
            out += delta + bytes([ev]) + mtrk_body[ln_start:pos]
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:  # CC
                cc, val = mtrk_body[pos], mtrk_body[pos + 1]
                pos += 2
                if cc == 0x07:  # Main Volume
                    cc7_by_ch[ch] = val
                out += delta + bytes([ev, cc, val])
            elif typ in (0x0C, 0x0D):
                out += delta + bytes([ev, mtrk_body[pos]])
                pos += 1
            else:
                out += delta + bytes([ev]) + mtrk_body[pos:pos + 2]
                pos += 2

    # Write back: replace MTrk
    new_mtrk = b"MTrk" + struct.pack(">I", len(out)) + bytes(out)
    new_data = data[:14] + new_mtrk + data[22 + mtrk_size:]
    open(path, "wb").write(new_data)


def main():
    import glob
    files = glob.glob("Iranian-Combined-CVP805/*.sty")
    print(f"Processing {len(files)} files...")
    for f in files:
        try:
            inject_section_cc7(f)
        except Exception as e:
            print(f"  ERROR {os.path.basename(f)}: {e}")
    print("Done")


if __name__ == "__main__":
    main()
