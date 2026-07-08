#!/usr/bin/env python3
"""
extract_tables.py — Build the MSB-LSB-PC lookup tables from Yamaha Data List PDFs.

This is the reverse-engineering tool. It reproduces how the JSON tables in this
repo were produced, and is the starting point for adapting the converter to a
different pair of keyboards.

WHAT IT PRODUCES
    <PREFIX>_VOICE_TABLE.json     name per "MSB-LSB-PC"  (from the Voice List)
    <PREFIX>_DRUMKIT_TABLE.json   name per "MSB-LSB-PC"  (from the Drum/Key
                                  Assignment List, filtered by per-model checkmark)

CONVENTIONS
    * Data-list PC numbers are 1-based (1-128); style files store 0-based (0-127).
      Every key here is stored 0-based, i.e. printed number - 1.
    * Drum-kit bank MSB is 126 (SFX/ethnic) or 127 (standard). Voices use MSB 0/8/104.

IMPORTANT — THIS IS PDF-SPECIFIC
    PDF layouts differ per model. The page ranges and the column x-position bands
    below are tuned for the PSR-OR700 and CVP-809/805 Data Lists. To use another
    keyboard's PDF you MUST re-inspect it (pdfplumber page.extract_words() with
    x0 positions) and adjust PAGES and the x-bands. Treat the values below as a
    worked example, not universal constants.

REQUIRES  pip install pdfplumber
USAGE     python extract_tables.py
"""

import re
import json
import pdfplumber

# ---------------------------------------------------------------- configuration
# Each entry: prefix, pdf path, voice-list page range, drum-assignment page range.
# Page numbers are 0-based pdfplumber indices (not the printed page numbers).
SOURCES = {
    "OR700": {
        "pdf": "psror700_en_de_fr_dl_a0.pdf",
        "voice_pages": range(1, 11),      # Voice List pages
        "voice_columns": 2,               # two voice columns per page
        # The OR-700 lists its ethnic kits inside the Voice List (type "SFX Kit"),
        # so we mine kits from the same voice pages by name.
        "kit_from_voice_list": True,
    },
    "CVP805": {
        "pdf": "cvp809_en_dl_c0.pdf",
        "voice_pages": range(16, 33),     # CVP-805 voice pages + shared XG/GM pages
        "voice_columns": 2,
        # The CVP has a proper Drum/Key Assignment List with a per-model checkmark
        # row; we read kit presence for THIS model from that checkmark.
        "kit_from_voice_list": False,
        "assign_pages": range(39, 53),
        "model_label": "CVP-805",         # which checkmark column means "present"
        "present_glyph": 0xF081,          # the checkmark glyph; en-dash U+2013 = absent
    },
}

TYPE_TOKENS = {"Regular", "Live!", "Cool!", "Sweet!", "Natural!", "S.Art!", "MegaVoice",
               "Mega", "Voice", "SFX", "Kit", "Drums", "Organ", "Flutes!", "Flutes", "Drum"}
# Category labels that the PDF's column layout can glue to a name; stripped from
# the start of a parsed name. NOTE: "SFX" is intentionally NOT here — "SFX Kit 1"
# is a genuine kit name, not a leaked category prefix.
CATEGORY_PREFIXES = ["Perc & Drum", "World Perc Kits", "Drum Kits", "Drum Kit",
                     "Organ Flutes", "Flute & Woodwind", "Piano"]


def _clean(name):
    """Strip a leaked category label that the PDF's column layout glued to a name."""
    for c in CATEGORY_PREFIXES:
        if name.startswith(c + " "):
            name = name[len(c) + 1:]
    # "SFX" is part of a real name ("SFX Kit 1") but also a category label that can
    # leak in front of another SFX kit ("SFX New SFX Kit 1"). Drop a leading "SFX "
    # only when "SFX" also appears later in the name (i.e. it was the leaked label).
    if name.startswith("SFX ") and "SFX" in name[4:]:
        name = name[4:]
    return name.strip()


def _is_int(s):
    return bool(re.fullmatch(r"\d{1,3}", s))


def _parse_entry(tokens):
    """
    Turn one row-cell's tokens into (name, msb, lsb, prg).
    Layout is: <name words...> MSB LSB PRG <voice-type words...>.
    We strip trailing type words, then the last three ints are MSB/LSB/PRG.
    """
    toks = [t for t in tokens if t != "|"]
    end = len(toks)
    while end > 0 and not _is_int(toks[end - 1]):   # drop trailing type words
        end -= 1
    if end < 3:
        return None
    try:
        prg, lsb, msb = int(toks[end - 1]), int(toks[end - 2]), int(toks[end - 3])
    except (ValueError, IndexError):
        return None
    if not (0 <= msb <= 127 and 0 <= lsb <= 127 and 1 <= prg <= 128):
        return None
    name = _clean(" ".join(toks[:end - 3]))
    if not name or any(h in name for h in ("Category", "Voice Name", "MSB", "PRG", "P C")):
        return None
    return name, msb, lsb, prg


def _rows(page):
    """Group a page's words into rows keyed by rounded vertical position."""
    rows = {}
    for w in page.extract_words():
        rows.setdefault(round(w["top"] / 2) * 2, []).append((w["x0"], w["text"]))
    return [sorted(rows[k]) for k in sorted(rows)]


def extract_voices(pdf, pages, ncols):
    """Parse the Voice List into {'MSB-LSB-PC' (0-based): name}. Also returns kits
    it finds by name (used for OR-700-style lists that embed ethnic kits)."""
    table, kits = {}, {}
    for pnum in pages:
        page = pdf.pages[pnum]
        width = page.width
        for line in _rows(page):
            # split the row into N side-by-side columns by x position
            cols = [[] for _ in range(ncols)]
            for x, t in line:
                cols[min(int(x / (width / ncols)), ncols - 1)].append(t)
            for c in cols:
                parsed = _parse_entry(c)
                if not parsed:
                    continue
                name, msb, lsb, prg = parsed
                key = f"{msb}-{lsb}-{prg - 1}"          # 0-based
                table[key] = name
                if msb in (126, 127) and ("Kit" in name or "Drum" in name):
                    kits[key] = name
    return table, kits


def extract_kits_from_assignment(pdf, pages, model_label, present_glyph):
    """
    Parse the Drum/Key Assignment List. Each page lists several kits as columns,
    with a per-model row of checkmarks. We keep a kit only if THIS model's row has
    the checkmark glyph at that kit's column (an en-dash means the model lacks it).
    """
    kits = {}
    for pnum in pages:
        page = pdf.pages[pnum]
        words = page.extract_words()
        # kit column anchors: address tokens like "126-0-68"
        addr = [w for w in words if w["text"].count("-") >= 2 and w["text"].split("-")[0].isdigit()]
        if not addr:
            continue
        # kit names sit on the "Voice Name" row
        name_top = next((w["top"] for w in words if w["text"] == "Name"), None)
        names = {}
        for w in words:
            if name_top and abs(w["top"] - name_top) < 3 and w["text"] not in ("Voice", "Name"):
                names.setdefault(round(w["x0"]), w["text"])
        # checkmark x-positions in this model's row
        top = next((w["top"] for w in words if w["text"] == model_label), None)
        if top is None:
            continue
        checks = [c["x0"] for c in page.chars
                  if abs(c["top"] - top) < 3 and ord(c["text"][0]) == present_glyph]
        for w in sorted(addr, key=lambda w: w["x0"]):
            lo, hi = w["x0"] - 30, w["x0"] + 70
            if not any(lo <= x <= hi for x in checks):
                continue                                # dash = kit not on this model
            name = _clean(" ".join(t for x, t in sorted(names.items()) if lo <= x <= hi))
            msb, lsb, prg = (int(x) for x in w["text"].split("-"))
            kits[f"{msb}-{lsb}-{prg - 1}"] = name
    return kits


def main():
    for prefix, cfg in SOURCES.items():
        pdf = pdfplumber.open(cfg["pdf"])
        voices, embedded_kits = extract_voices(pdf, cfg["voice_pages"], cfg["voice_columns"])
        if cfg["kit_from_voice_list"]:
            kits = embedded_kits
        else:
            kits = extract_kits_from_assignment(
                pdf, cfg["assign_pages"], cfg["model_label"], cfg["present_glyph"])

        convention = ("KEYS ARE 0-BASED MIDI (data-list PC# minus 1), matching the raw PC "
                      "byte inside .STY style files. To find an entry in the PDF, add 1 to "
                      "the last number. Verified: Standard Kit 1 = 127-0-0 = data-list 127-0-1.")
        for fn, data in ((f"{prefix}_VOICE_TABLE.json", voices),
                         (f"{prefix}_DRUMKIT_TABLE.json", kits)):
            out = {"_convention": convention, **data}   # keep the note as the first key
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=0, ensure_ascii=False)
            print(f"wrote {fn}: {len(data)} entries")


if __name__ == "__main__":
    main()
