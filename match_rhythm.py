#!/usr/bin/env python3
"""
match_rhythm.py — Detect a style's rhythm family from its percussion and match it
to the most similar OR-700 preset.

Used by convert_psr_iranian.py to pick a genre-appropriate OTS for amateur styles
whose *name* gives no genre (personal names like REZA, MANSOOR...). Instead of the
name, it reads the beat: time signature, tempo, and the drum-onset pattern of the
Main A section, and finds the nearest OR-700 style.

A rhythm "fingerprint" is:
    (numerator, denominator, tempo, onset-histogram)
The histogram is drum onsets within a bar, quantized into BINS positions and split
into 3 pitch bands (low = kick, mid = snare/tom, high = hats/percussion), L2-norm.
Similarity is cosine of the histograms, with a penalty for a different time signature
and for a large tempo gap — so a 6/8 style never matches a 4/4 one.

Run standalone to see the match each amateur style would get:
    python match_rhythm.py
"""

import os
import glob
import math
import struct

from convert_psr_iranian import casm_roles, style_name, clean_name, DRUM_ROLES, SRC_FOLDERS

BINS = 24
# OR-700 styles to match against (all have OTS). Iranian folder + a couple of
# Arabic/Turkish anchors so those families can be matched too.
REFERENCE_GLOBS = [
    os.path.join("OR700-Preset-Styles", "Iranian", "*.prs"),
    os.path.join("OR700-Preset-Styles", "Arabic&Maghrebi", "Baladi.S967.prs"),
    os.path.join("OR700-Preset-Styles", "Turkish&Greek", "Ciftetelli.S958.prs"),
]


def fingerprint(path):
    """Return (num, den, bpm, histogram) for a style's Main A drums, or None."""
    d = open(path, "rb").read()
    if d[14:18] != b"MTrk":
        return None
    div = struct.unpack_from(">H", d, 12)[0]
    size = struct.unpack_from(">I", d, 18)[0]
    mt = d[22:22 + size]
    drum = {c for c, r in casm_roles(path).items() if r in DRUM_ROLES}

    num, den, bpm = 4, 4, 120
    section = None
    onsets = []                      # (abs_tick, pitch) in Main A
    pos = tick = 0
    while pos < len(mt):
        dt = 0
        while pos < len(mt) and (mt[pos] & 0x80):
            dt = (dt << 7) | (mt[pos] & 0x7f); pos += 1
        dt = (dt << 7) | (mt[pos] & 0x7f); pos += 1
        tick += dt
        ev = mt[pos]; pos += 1
        if ev == 0xFF:
            mtype = mt[pos]; pos += 1; ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            if mtype == 0x58:
                num, den = mt[pos], 2 ** mt[pos + 1]
            elif mtype == 0x51:
                bpm = round(6e7 / ((mt[pos] << 16) | (mt[pos + 1] << 8) | mt[pos + 2]))
            elif mtype == 0x06:
                section = mt[pos:pos + ln].decode("latin1", "ignore")
            pos += ln
        elif ev in (0xF0, 0xF7):
            ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x09:
                if ch in drum and mt[pos + 1] > 0 and section == "Main A":
                    onsets.append((tick, mt[pos]))
                pos += 2
            elif typ in (0x0B, 0x08, 0x0E):
                pos += 2
            elif typ in (0x0C, 0x0D):
                pos += 1
            else:
                pos += 2

    bar = div * (4 / den) * num
    vec = [0.0] * (3 * BINS)
    for t, p in onsets:
        b = int((t % bar) / bar * BINS) % BINS
        band = 0 if p <= 37 else (1 if p <= 50 else 2)   # kick / snare-tom / hats-perc
        vec[band * BINS + b] += 1
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return num, den, bpm, [x / norm for x in vec]


def similarity(a, b):
    """Rhythm similarity between two fingerprints (higher = closer)."""
    (na, da, ta, va), (nb, db, tb, vb) = a, b
    cos = sum(x * y for x, y in zip(va, vb))
    if (na, da) != (nb, db):
        cos -= 0.4                                   # different meter -> strong penalty
    cos -= min(0.3, abs(ta - tb) / 200.0)            # tempo gap penalty
    return cos


def build_reference_index(base):
    """Fingerprint every reference OR-700 style that has drums + an OTSc."""
    index = {}
    for pat in REFERENCE_GLOBS:
        for f in glob.glob(os.path.join(base, pat)):
            if b"OTSc" not in open(f, "rb").read():
                continue
            fp = fingerprint(f)
            if fp and any(fp[3]):
                index[f] = fp
    return index


def best_match(base, style_path, index=None):
    """Return the reference style path whose rhythm is closest to style_path."""
    tops = best_matches(base, style_path, index, n=1)
    return tops[0] if tops else None


def best_matches(base, style_path, index=None, n=3):
    """Return the n reference style paths whose rhythm is closest (best first)."""
    index = index or build_reference_index(base)
    fp = fingerprint(style_path)
    if not fp or not any(fp[3]):
        return []
    ranked = sorted(index, key=lambda ref: similarity(fp, index[ref]), reverse=True)
    return ranked[:n]


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    index = build_reference_index(base)
    print(f"Reference styles: {len(index)}\n")
    for folder in SRC_FOLDERS:
        for f in sorted(glob.glob(os.path.join(base, folder, "*.sty"))):
            ref = best_match(base, f, index)
            print(f"  {clean_name(style_name(f) or '?'):22} -> "
                  f"{os.path.basename(ref).split('.')[0] if ref else '(no drums)'}")


if __name__ == "__main__":
    main()
