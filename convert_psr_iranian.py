#!/usr/bin/env python3
"""
convert_psr_iranian.py — Convert the older GM/XG PSR Iranian styles (Iranian1 +
Iranian2 folders) to the CVP-805 and organize them into ONE combined output
folder renamed by each style's real (embedded) name.

These amateur styles differ from the OR-700 presets in a crucial way: many use a
NON-STANDARD channel layout. A Yamaha style's CASM section maps each MTrk channel
to an accompaniment ROLE (Rhythm1/2 = drums, Bass, Chord1/2, Pad, Phrase1/2), and
these makers often remapped them (e.g. the main drums on MIDI ch16, not ch10).

So this converter reads the CASM per file and uses the REAL roles to:
  * force to a drum kit only the channels whose role is Rhythm1/Rhythm2,
  * upgrade GM/XG voices on the melodic-role channels to CVP-805 panel voices,
  * normalize each channel's volume toward a professional per-ROLE reference
    (learned from the OR-700 presets), proportionally (preserving the mix).

Run:  python convert_psr_iranian.py
"""

import os
import re
import glob
import struct
import json
from collections import Counter, defaultdict

from revoice import StyleRevoicer

SRC_FOLDERS = ["Iranian1", "Iranian2"]

# GM program -> CVP-805 panel voice upgrade (natural/faithful set), for the
# melodic-role channels. All targets verified present on the CVP-805.
GM_UPGRADE = {
    0: "108-0-0",   2: "108-0-0",   4: "104-7-4",   5: "104-1-5",
    16: "0-111-16", 24: "0-115-24", 25: "0-117-25", 26: "0-115-26",
    27: "0-112-27", 28: "0-119-28", 33: "0-114-33", 34: "0-112-34",
    35: "0-112-35", 36: "0-112-36", 39: "0-112-39", 48: "8-1-48",
    49: "8-32-49",  50: "0-112-50", 61: "104-8-61", 65: "0-112-65",
    66: "0-116-66", 81: "0-118-81",
}

# Professional volume reference per style ROLE, learned from the OR-700 presets
# (median CC7), nudged for Iranian pop/dance (drums/bass/melody forward, chords/
# pad back). Amateur styles slam everything to 127; we scale each channel
# proportionally toward its role target (preserving the maker's relative mix).
REF_ROLE = {
    "Rhythm1": 66, "Rhythm2": 62, "Bass": 60, "Chord1": 50,
    "Chord2": 54, "Pad": 48, "Phrase1": 66, "Phrase2": 62,
}
# Fallback role by channel index for the standard layout (destination convention:
# ch9=Rhythm1, ch10=Rhythm2, ch11=Bass ...), used when a channel has no CASM entry.
STANDARD_ROLE = {8: "Rhythm1", 9: "Rhythm2", 10: "Bass", 11: "Chord1",
                 12: "Chord2", 13: "Pad", 14: "Phrase1", 15: "Phrase2"}
DRUM_ROLES = ("Rhythm1", "Rhythm2")
PRO_VEL_MEDIAN = 71   # OR-700 median note velocity; amateur styles run ~99
OUT_FOLDER = "Iranian-Combined-CVP805"


def casm_roles(path):
    """Parse the CASM section -> {MTrk source channel index: role name}. Falls back
    to the standard layout for channels the CASM doesn't list."""
    d = open(path, "rb").read()
    ci = d.find(b"CASM")
    roles = dict(STANDARD_ROLE)
    if ci >= 0:
        casm = d[ci:]; i = 0
        while True:
            i = casm.find(b"Ctab", i)
            if i < 0:
                break
            sz = struct.unpack_from(">I", casm, i + 4)[0]
            body = casm[i + 8:i + 8 + sz]
            src, dst = body[0], body[9]
            # The DESTINATION channel is the reliable role indicator (it always
            # follows the standard convention ch9=Rhythm1 ... ch16=Phrase2); the
            # 8-char name is often a custom label ("DRUMS00", "GUIT27", "Bass Maj").
            role = STANDARD_ROLE.get(dst)
            if role:
                roles[src] = role
            i += 8 + sz
    return roles


def read_mtrk(path):
    data = open(path, "rb").read()
    size = struct.unpack_from(">I", data, 18)[0]
    return data[22:22 + size]


def iter_events(mtrk):
    """Yield ('pc', ch, msb, lsb, pc) and ('name', text) as we walk the track."""
    st = {c: {"msb": 0, "lsb": 0} for c in range(16)}
    pos = 0
    name_done = False
    while pos < len(mtrk):
        while pos < len(mtrk) and (mtrk[pos] & 0x80):
            pos += 1
        pos += 1
        if pos >= len(mtrk):
            break
        ev = mtrk[pos]; pos += 1
        if ev == 0xFF:
            mt = mtrk[pos]; pos += 1
            ln = 0
            while pos < len(mtrk) and (mtrk[pos] & 0x80):
                ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            txt = mtrk[pos:pos + ln]; pos += ln
            if mt == 0x03 and not name_done:
                name_done = True
                yield ("name", txt.decode("latin1", "ignore").split("\x00")[0].strip())
        elif ev in (0xF0, 0xF7):
            ln = 0
            while pos < len(mtrk) and (mtrk[pos] & 0x80):
                ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mtrk[pos] & 0x7f); pos += 1
            pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:
                cc, v = mtrk[pos], mtrk[pos + 1]; pos += 2
                if cc == 0x00: st[ch]["msb"] = v
                elif cc == 0x20: st[ch]["lsb"] = v
            elif typ == 0x0C:
                pc = mtrk[pos]; pos += 1
                yield ("pc", ch, st[ch]["msb"], st[ch]["lsb"], pc)
            elif typ == 0x0D:
                pos += 1
            else:
                pos += 2


def style_name(path):
    for e in iter_events(read_mtrk(path)):
        if e[0] == "name":
            return e[1]
    return None


def clean_name(raw):
    """Turn an embedded style name into a tidy filename."""
    s = raw.split("\x00")[0]
    s = re.sub(r"\.(sty|STY)$", "", s)          # drop .STY
    s = re.sub(r"\.[sS]\d+$", "", s)            # drop .sNNN voice-number suffix
    s = re.sub(r"[_`^]+", " ", s)               # padding chars -> space
    s = re.sub(r"\s+", " ", s).strip(" -,.%`^")
    s = re.sub(r'[\\/:*?"<>|]', "", s)          # illegal filename chars
    return s or "Untitled"


def build_voice_map(upgrade):
    """For every melodic voice address used across the two folders, map it to the
    given upgrade table if its program has one (keyed by full MSB-LSB-PC tuple)."""
    vm = {}
    for folder in SRC_FOLDERS:
        for f in glob.glob(os.path.join(folder, "*.sty")):
            for e in iter_events(read_mtrk(f)):
                if e[0] != "pc":
                    continue
                _, ch, msb, lsb, pc = e
                if msb in (126, 127):           # drum-kit banks: never upgrade
                    continue
                if pc in upgrade:
                    tgt = tuple(int(x) for x in upgrade[pc].split("-"))
                    if (msb, lsb, pc) != tgt:
                        vm[(msb, lsb, pc)] = tgt
    return vm


def _walk(mt):
    """Yield (kind, pos, ch, a, b) for each event in an MTrk body; kind is
    'cc'/'note'/'other'. pos is the index of the event's first data byte."""
    pos = 0
    while pos < len(mt):
        while pos < len(mt) and (mt[pos] & 0x80):
            pos += 1
        pos += 1
        if pos >= len(mt):
            break
        ev = mt[pos]; pos += 1
        if ev == 0xFF:
            pos += 1; ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1; pos += ln
        elif ev in (0xF0, 0xF7):
            ln = 0
            while pos < len(mt) and (mt[pos] & 0x80):
                ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (mt[pos] & 0x7f); pos += 1; pos += ln
        else:
            typ, ch = (ev >> 4) & 0xF, ev & 0xF
            if typ == 0x0B:
                yield ("cc", pos, ch, mt[pos], mt[pos + 1]); pos += 2
            elif typ == 0x09:
                yield ("note", pos, ch, mt[pos], mt[pos + 1]); pos += 2
            elif typ in (0x08, 0x0E):
                pos += 2
            elif typ in (0x0C, 0x0D):
                pos += 1
            else:
                pos += 2


def normalize_to_reference(path, role_of):
    """Scale each channel's Main Volume (CC7) proportionally toward the pro target
    for its CASM ROLE. If a channel plays notes but never sets CC7, inject one.
    role_of maps channel index -> role name."""
    data = bytearray(open(path, "rb").read())
    size = struct.unpack_from(">I", data, 18)[0]
    body = bytes(data[22:22 + size])

    def target(ch):
        # roled channels -> their pro reference; un-roled channels (the dead ch1-8
        # setup data some makers leave, no notes) -> a modest default so nothing
        # sits at 100+ in the mixer.
        return REF_ROLE.get(role_of.get(ch, ""), 64)

    # pass 1: per channel CC7 distribution + whether it plays notes; collect all velocities
    cc7_by_ch, has_note, has_cc7, allvel = {}, set(), set(), []
    for kind, pos, ch, a, b in _walk(body):
        if kind == "cc" and a == 0x07:
            if ch not in cc7_by_ch:
                cc7_by_ch[ch] = []
            cc7_by_ch[ch].append(b)
            has_cc7.add(ch)
        elif kind == "note" and b > 0:
            has_note.add(ch)
            allvel.append(b)

    # Velocity: amateurs hit ~40% harder than the pros. Scale this style's
    # velocities toward the OR-700 median (PRO_VEL_MEDIAN), proportionally so the
    # intra-style dynamics (Intro soft ... Main D full) are preserved. Only reduce.
    vel_scale = 1.0
    if allvel:
        med = sorted(allvel)[len(allvel) // 2]
        vel_scale = max(0.55, min(1.0, PRO_VEL_MEDIAN / med))

    # compute scale factor per channel: target / median(cc7). Channels that never set
    # CC7 get a neutral scale (1.0). This ensures the typical level hits the target.
    scale_by_ch = {}
    for ch, vals in cc7_by_ch.items():
        med = sorted(vals)[len(vals) // 2]
        if med > 0:
            tgt = target(ch)
            scale_by_ch[ch] = tgt / med

    # pass 2: rewrite. Scale existing CC7 to hit the role target; inject where missing.
    out = bytearray()
    injected = set()
    pos = 0
    while pos < len(body):
        d0 = pos
        while pos < len(body) and (body[pos] & 0x80):
            pos += 1
        pos += 1
        delta = body[d0:pos]
        ev = body[pos]; pos += 1
        typ, ch = (ev >> 4) & 0xF, ev & 0xF
        if ev == 0xFF or ev in (0xF0, 0xF7):
            ln = 0; ls = pos
            if ev == 0xFF:
                pos += 1
            while pos < len(body) and (body[pos] & 0x80):
                ln = (ln << 7) | (body[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (body[pos] & 0x7f); pos += 1
            out += delta + bytes([ev]) + body[ls:pos] + body[pos:pos + ln]; pos += ln
        elif typ == 0x0B:                                   # control change
            cc, val = body[pos], body[pos + 1]; pos += 2
            if cc == 0x07 and scale_by_ch.get(ch):
                val = max(1, min(127, round(val * scale_by_ch[ch])))
            out += delta + bytes([ev, cc, val])
        elif typ == 0x09:                                   # note on
            n, v = body[pos], body[pos + 1]; pos += 2
            if v > 0:
                v = max(1, min(127, round(v * vel_scale)))   # tame velocity to pro level
            tgt = target(ch)
            if tgt and ch in has_note and ch not in has_cc7 and ch not in injected:
                out += delta + bytes([0xB0 | ch, 0x07, tgt])   # inject role volume
                out += bytes([0x00, ev, n, v])                 # note with delta 0
                injected.add(ch)
            else:
                out += delta + bytes([ev, n, v])
        elif typ in (0x08, 0x0E):
            out += delta + bytes([ev, body[pos], body[pos + 1]]); pos += 2
        elif typ in (0x0C, 0x0D):
            out += delta + bytes([ev, body[pos]]); pos += 1
        else:
            out += delta + bytes([ev])

    new = bytearray(data[:18]) + struct.pack(">I", len(out)) + out + data[22 + size:]
    open(path, "wb").write(new)


# --- musical refinement: swap genre-inappropriate voices + fix odd drum notes ---
ELECTRIC_BASS = (0, 114, 33)      # for non-bass voices sitting on the Bass part
MELODY_STRINGS = (8, 32, 49)      # Concert Strings, for OrchestraHit/Atmosphere leads
ACCORDION = (0, 116, 21)          # for the unresolved 0-127-22 (harmonica/accordion slot)


def _voice_swap(role, msb, lsb, pc):
    """Return a replacement (msb,lsb,pc) for a genre-inappropriate voice, or None."""
    if (msb, lsb, pc) == (0, 127, 22):               # unresolved -> Accordion
        return ACCORDION
    if role == "Bass" and not (24 <= pc <= 39):      # not a guitar/bass on the bass part
        return ELECTRIC_BASS                         # (guitars 24-31 and basses 32-39 kept)
    if role in ("Phrase1", "Phrase2") and pc in (55, 99, 100):  # OrchestraHit / Atmosphere lead
        return MELODY_STRINGS
    return None


def refine(path, role_of):
    """Second pass: swap odd voices (role-aware) and remap drum note 83 (Jingle Bells)
    to 54 (Tambourine) so the daf/frame-drum jingle part sounds right."""
    data = bytearray(open(path, "rb").read())
    size = struct.unpack_from(">I", data, 18)[0]
    body = bytes(data[22:22 + size])
    drum_ch = {c for c, r in role_of.items() if r in DRUM_ROLES}

    out = bytearray()
    bank = {c: {"msb": 0, "lsb": 0, "moff": None, "loff": None} for c in range(16)}
    pos = 0
    while pos < len(body):
        d0 = pos
        while pos < len(body) and (body[pos] & 0x80):
            pos += 1
        pos += 1
        delta = body[d0:pos]
        ev = body[pos]; pos += 1
        typ, ch = (ev >> 4) & 0xF, ev & 0xF
        if ev == 0xFF or ev in (0xF0, 0xF7):
            ln = 0; ls = pos
            if ev == 0xFF:
                pos += 1
            while pos < len(body) and (body[pos] & 0x80):
                ln = (ln << 7) | (body[pos] & 0x7f); pos += 1
            ln = (ln << 7) | (body[pos] & 0x7f); pos += 1
            out += delta + bytes([ev]) + body[ls:pos] + body[pos:pos + ln]; pos += ln
        elif typ == 0x0B:                                    # control change (track bank)
            cc, val = body[pos], body[pos + 1]; pos += 2
            out += delta + bytes([ev, cc, val])
            if cc == 0x00:
                bank[ch]["msb"] = val; bank[ch]["moff"] = len(out) - 1
            elif cc == 0x20:
                bank[ch]["lsb"] = val; bank[ch]["loff"] = len(out) - 1
        elif typ == 0x0C:                                    # program change (maybe swap voice)
            pc = body[pos]; pos += 1
            swap = None if ch in drum_ch else _voice_swap(role_of.get(ch, ""), bank[ch]["msb"], bank[ch]["lsb"], pc)
            if swap:
                nm, nl, npc = swap
                if bank[ch]["moff"] is not None and bank[ch]["loff"] is not None:
                    out[bank[ch]["moff"]] = nm; out[bank[ch]["loff"]] = nl
                    out += delta + bytes([ev, npc])
                else:                                        # inject a bank select
                    out += delta + bytes([0xB0 | ch, 0x00, nm, 0x00, 0xB0 | ch, 0x20, nl,
                                          0x00, ev, npc])
                bank[ch]["msb"], bank[ch]["lsb"] = nm, nl
            else:
                out += delta + bytes([ev, pc])
            bank[ch]["moff"] = bank[ch]["loff"] = None
        elif typ in (0x09, 0x08):                            # note on/off (fix note 83 on drums)
            n, v = body[pos], body[pos + 1]; pos += 2
            if ch in drum_ch and n == 83:
                n = 54                                       # Jingle Bells -> Tambourine
            out += delta + bytes([ev, n, v])
        elif typ == 0x0E:
            out += delta + bytes([ev, body[pos], body[pos + 1]]); pos += 2
        elif typ == 0x0D:
            out += delta + bytes([ev, body[pos]]); pos += 1
        else:
            out += delta + bytes([ev])

    new = bytearray(data[:18]) + struct.pack(">I", len(out)) + out + data[22 + size:]
    open(path, "wb").write(new)


# One Touch Settings: the amateur styles have none. Copy the OTSc chunk from a
# GENRE-MATCHED OR-700 preset. Matching is by name keyword (precise) else by
# rhythm; within a genre we ROTATE through all available OR-700 presets so styles
# of the same genre don't all get an identical OTS. The OR-700 OTS carry no tempo
# events, so they don't disturb each style's own tempo.

# Classify an OR-700 style (by its filename stem) into a genre label.
def genre_of(stem):
    n = re.sub(r"[^a-z0-9]", "", stem.lower())
    for kw, label in [
        ("modernbandari", "Bandari"), ("bandari", "Bandari"), ("afghan", "Afghani"),
        ("azari", "Azari"), ("azeri", "Azari"), ("kermanshah", "Kermanshahi"),
        ("kurdish", "Kurdish"), ("club", "Club"), ("beat", "Beat"), ("elec", "Elec"),
        ("raghsmodern", "Raghs"), ("raghs", "Raghs"), ("iranidance", "Dance"),
        ("moderntehrani", "Tehrani"), ("tehrani", "Tehrani"), ("lori", "Lori"),
        ("gilaki", "Gilaki"), ("khorasani", "Khorasani"), ("lezgi", "Lezgi"),
        ("reng", "Reng"), ("avaaz", "Avaaz"), ("asouri", "Asouri"),
        ("farangi", "Farangi"), ("traditional", "Traditional"), ("baladi", "Arabic"),
        ("ciftetelli", "Turkish"), ("68", "6-8"),
    ]:
        if kw in n:
            return label
    return "Iranian"


# Amateur-name keyword -> genre label (for the precise name match).
NAME_GENRE = [
    ("modernbandari", "Bandari"), ("bandari", "Bandari"), ("bandar", "Bandari"),
    ("banari", "Bandari"), ("banear", "Bandari"), ("bastaki", "Bandari"),
    ("afghan", "Afghani"), ("kordi", "Kurdish"), ("kordy", "Kurdish"),
    ("kurdish", "Kurdish"), ("kord", "Kurdish"), ("chopi", "Kurdish"),
    ("araby", "Arabic"), ("arabic", "Arabic"), ("arab", "Arabic"),
    ("azari", "Azari"), ("azeri", "Azari"), ("torki", "Turkish"), ("turki", "Turkish"),
    ("tehran", "Tehrani"), ("tooshmal", "Lori"), ("lori", "Lori"), ("lory", "Lori"),
    ("gilaki", "Gilaki"), ("kermanshah", "Kermanshahi"), ("khorasan", "Khorasani"),
    ("gheri", "6-8"), ("6-8", "6-8"), ("6.8", "6-8"), ("6,8", "6-8"), ("6x8", "6-8"),
    ("68", "6-8"),
]

_otsc_cache = {}
_rr = Counter()          # round-robin counters for OTS variety


def _otsc(path):
    if path not in _otsc_cache:
        d = open(path, "rb").read()
        i = d.find(b"OTSc")
        _otsc_cache[path] = d[i:i + 8 + struct.unpack_from(">I", d, i + 4)[0]] if i >= 0 else None
    return _otsc_cache[path]


def build_ots_by_genre(base):
    """{genre label: [OR-700 style paths that have an OTSc]}."""
    by = defaultdict(list)
    for pat in (("Iranian", "*.prs"), ("Iranian", "*.STY"),
                ("Arabic&Maghrebi", "*.prs"), ("Turkish&Greek", "*.prs")):
        for f in sorted(glob.glob(os.path.join(base, "OR700-Preset-Styles", *pat))):
            if _otsc(f):
                by[genre_of(os.path.basename(f).split(".")[0])].append(f)
    return by


def match_ots(base, style_nm, style_path, rhythm_index, ots_by_genre):
    """Return (otsc_bytes, genre_label, method).

    Determine the genre (by name keyword, else by nearest-rhythm OR-700 style),
    then ROTATE among that genre's OR-700 presets for variety. The genre tag
    always matches the chosen OTS, so it stays accurate.
    """
    n = re.sub(r"[^a-z0-9]", "", (style_nm or "").lower())
    genre, how = None, "default"
    for kw, label in NAME_GENRE:                       # 1) precise name genre
        if re.sub(r"[^a-z0-9]", "", kw) in n and ots_by_genre.get(label):
            genre, how = label, "name"
            break
    if genre is None:                                  # 2) genre of nearest rhythm match
        import match_rhythm
        ref = match_rhythm.best_match(base, style_path, rhythm_index)
        if ref:
            g = genre_of(os.path.basename(ref).split(".")[0])
            if ots_by_genre.get(g):
                genre, how = g, "rhythm"
    if genre is None:                                  # 3) fallback
        genre = "Dance" if ots_by_genre.get("Dance") else next(iter(ots_by_genre))
    refs = ots_by_genre[genre]
    ref = refs[_rr[genre] % len(refs)]; _rr[genre] += 1   # rotate within the genre
    return _otsc(ref), genre, how


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(base, OUT_FOLDER)
    os.makedirs(out_dir, exist_ok=True)
    voice_map = build_voice_map(GM_UPGRADE)
    import match_rhythm
    rhythm_index = match_rhythm.build_reference_index(base)     # for name-less styles
    ots_by_genre = build_ots_by_genre(base)                    # {genre: [OR-700 presets]}
    print(f"Converting -> {OUT_FOLDER}/  (CASM roles, per-role volume, genre in "
          f"filename, rotated genre-matched OTS)\n")

    used_names = {}
    ots_method = Counter()
    genre_count = Counter()
    total = remapped = 0
    for folder in SRC_FOLDERS:
        for f in sorted(glob.glob(os.path.join(folder, "*.sty"))):
            fname = os.path.basename(f)
            roles = casm_roles(f)                            # MTrk channel -> role
            drum_ch = {ch for ch, r in roles.items() if r in DRUM_ROLES}
            if drum_ch != {8, 9}:
                remapped += 1

            proc = StyleRevoicer(base, category=folder)
            proc.styles_path = os.path.join(base, folder)
            proc.output_dir = out_dir
            proc.voice_map.update(voice_map)
            proc.drum_channels = drum_ch                     # <- real drum channels for THIS file

            name = clean_name(style_name(f) or os.path.splitext(fname)[0])
            # OTS + detected genre (chosen before naming so we can tag the filename)
            otsc, genre, how = match_ots(base, name, f, rhythm_index, ots_by_genre)
            ots_method[how] += 1; genre_count[genre] += 1
            labeled = f"{name} [{genre}]"
            k = used_names.get(labeled.lower(), 0) + 1
            used_names[labeled.lower()] = k
            out_name = labeled if k == 1 else f"{labeled} ({k})"

            if not proc.process_file(fname):
                continue
            stem = os.path.splitext(fname)[0]
            default = os.path.join(out_dir, stem + "_CVP805_V1.sty")
            report = os.path.join(out_dir, stem + "_CVP805_V1_REPORT.md")
            final = os.path.join(out_dir, out_name + ".sty")
            if os.path.exists(default):
                os.replace(default, final)
                normalize_to_reference(final, roles)         # per-role volume
                refine(final, roles)                         # genre voice/note fixes
                if otsc:
                    with open(final, "ab") as fh:
                        fh.write(otsc)
            if os.path.exists(report):
                os.replace(report, os.path.join(out_dir, out_name + "_REPORT.md"))
            total += 1
    print(f"\nDone: {total} styles -> {OUT_FOLDER}/  ({remapped} had a non-standard "
          f"channel layout handled via CASM).")
    print(f"\nOTS match method: {dict(ots_method)}")
    print("Detected genre -> count:")
    for g, c in genre_count.most_common():
        print(f"  {g:14} {c}")
    # how many distinct OTS presets were actually used (variety check)
    print(f"\ndistinct OR-700 OTS presets used: {len(set().union(*ots_by_genre.values()))} available")


if __name__ == "__main__":
    main()
