# Yamaha OR-700 → CVP-805 Style Revoicer

Convert Yamaha **PSR-OR700** preset styles (`.STY` / `.PRS`) so they play
correctly on a Yamaha **Clavinova CVP-805**.

## The problem

The PSR-OR700 is an *oriental arranger*: its styles use ethnic **drum kits**
(Iranian, Arabic, Khaligi, Turkish) and ethnic **voices** (Tar, Nay, Sorna,
Oud…). The CVP-805 is a Western instrument and does **not** have most of those
sounds at the same MIDI addresses. Load an OR-700 style on a CVP-805 unchanged
and the drum track often comes out as **sound effects**, and lead voices play
the wrong instrument.

This tool rewrites the style files so that:

- each ethnic **drum kit** points at the closest real CVP-805 kit, **and** its
  individual drum notes are remapped so each hit (Tombak, Daf, Darbuka, …)
  lands on the nearest CVP-805 equivalent;
- ethnic **melodic voices** are handled sensibly (mostly via the CVP-805's own
  GM fallback, with a few explicit overrides such as Oud).

147 preset styles across four categories (Iranian, Arabic & Maghrebi, Khaligi,
Turkish & Greek) are converted.

## How it works

A Yamaha style file is **SFF1** format: a standard MIDI file (`MThd` + one
`MTrk`) followed by Yamaha chunks (`CASM`, `OTSc`, …). Only the `MTrk` is
edited. The `MTrk` tag sits at byte offset **14**.

A voice or kit is selected by three MIDI messages on a channel:

```
Bank Select MSB (CC0)  +  Bank Select LSB (CC32)  +  Program Change
```

so every sound is identified by the triple **`MSB-LSB-PC`**.

Two Yamaha facts the code depends on:

1. **PC numbering.** Data-list PC numbers are 1-based (1–128); the byte inside
   the file is 0-based (0–127). All JSON tables are keyed by the **0-based file
   value** (data-list number − 1). See [`DATA_REFERENCE.md`](DATA_REFERENCE.md).
2. **Bank meaning.** MSB **127** is the drum-kit bank; MSB **126** is the
   SFX / ethnic bank. So `126-0-0` is *“SFX Kit 1” = sound effects*, **not** a
   drum kit. This is why a kit remap must rewrite the **Bank Select**, not just
   the Program Change — otherwise a kit that falls back to Standard Kit
   (`127-0-0`) would keep `MSB=126` and play sound effects. (This was the main
   bug the tool was built to fix.)

The converter (`revoice.py`) parses the MTrk event stream and, per channel:

- **drum channels** (MIDI 9 & 10): rewrite the full `MSB-LSB-PC` to the target
  kit and remap each drum note;
- **melodic channels**: rewrite bank + PC only for voices with an explicit
  override, otherwise leave them for the keyboard's GM fallback.

## Data files

All lookup tables were extracted directly from the official Yamaha Data List
PDFs (PSR-OR700 and CVP-809/CVP-805) and are keyed by `MSB-LSB-PC` (0-based):

| File | Contents |
|------|----------|
| `OR700_VOICE_TABLE.json`, `CVP805_VOICE_TABLE.json` | voice name per address |
| `OR700_DRUMKIT_TABLE.json`, `CVP805_DRUMKIT_TABLE.json` | drum-kit name per address |
| `KIT_NOTE_ASSIGNMENTS.json` | note-by-note instrument names for each kit |
| `NOTE_MAPS.json` | per-kit target + note remap (source note → target note) |
| `MELODIC_VOICE_MAP.json` | explicit melodic voice overrides |

The CVP-805 drum-kit table is validated against the *Drum/Key Assignment List*
per-model checkmark, so kits present only on the CVP-809 are excluded.

## Usage

```bash
python revoice.py                 # all files in the Iranian folder
python revoice.py 5 Iranian       # first 5 Iranian files
python revoice.py 999 ALL         # every file in every category folder
```

Input:  `OR700-Preset-Styles/<Category>/*.STY|*.PRS`
Output: `OR700-Preset-Styles-CVP805/<Category>/*_CVP805_V1.STY|.PRS`
plus a `*_CVP805_V1_REPORT.md` per file documenting every change.

The converter itself needs only the **Python 3.8+ standard library**.

## Reverse-engineering tools (for adapting to other keyboards)

Two helper scripts make it practical to target a new keyboard:

| Tool | Purpose |
|------|---------|
| `inspect_style.py <file>` | Dump every drum kit + melodic voice a style file uses (as `MSB-LSB-PC`, named if tables are present). Run this first to see what maps you need. Stdlib only. |
| `extract_tables.py` | Rebuild the `*_VOICE_TABLE.json` / `*_DRUMKIT_TABLE.json` from a keyboard's Data List PDF, including the drum-kit per-model checkmark logic. Requires `pdfplumber`. |

`extract_tables.py` is **PDF-specific** — the page ranges and column x-positions
are tuned for the OR-700 and CVP-809/805 PDFs and must be re-inspected/adjusted
for another model (see the comments at the top of the file). It is included as a
worked, documented example of the extraction so you don't have to start from
scratch.

```bash
pip install pdfplumber          # only needed for extract_tables.py
python extract_tables.py        # regenerate the voice/kit tables from the PDFs
python inspect_style.py OR700-Preset-Styles/Iranian/6-8Dance.bt3.S983.STY
```

## Kit remapping summary

| OR-700 kit | → CVP-805 target | Notes |
|-----------|------------------|-------|
| IranianKit `126-0-38` | Turkish Kit `126-0-67` | Tombak/Zarb→Darbuka, Daf→Bendir/Tef, Dohol→Davul |
| ArabicKit 1 `126-0-36` | Arabic Kit `126-0-35` | name-direct |
| KhaligiKit `126-0-37` | Arabic Kit `126-0-35` | Gulf percussion → Arabic |
| ArabicMixKit `126-0-64` | Standard Kit `127-0-0` | drum-set + Latin → GM positions |
| KhaligiMixKit `126-0-65` | Standard Kit `127-0-0` | drum-set + Latin → GM positions |
| IranianMixKit `126-0-66` | Standard Kit `127-0-0` | drum-set + Latin → GM positions |
| Standard/Room/Rock/Dance/PopLatin | (unchanged) | already present on both keyboards |

## Adapting this to other Yamaha keyboards

**This project is not specific to the OR-700 → CVP-805 pair.** The same approach
converts styles between *any* two Yamaha arrangers/Clavinovas (Genos, Tyros,
PSR-S/SX, PSR-A, CVP…). The engine in `revoice.py` is generic — it only knows
about `MSB-LSB-PC` addresses, Bank Select, and note remapping. Everything
instrument-specific lives in the JSON data files.

To retarget it to a different source/destination keyboard:

1. **Extract the lookup tables** for your two keyboards from their official
   *Data List* PDFs — the Voice List and the Drum/Key Assignment List — into the
   same `MSB-LSB-PC` (0-based) JSON format used here
   (`*_VOICE_TABLE.json`, `*_DRUMKIT_TABLE.json`, `KIT_NOTE_ASSIGNMENTS.json`).
   Remember the data list prints PC 1-based; subtract 1.
2. **Decide kit targets and note maps** (`NOTE_MAPS.json`): for each source kit
   the destination lacks, pick the nearest destination kit and map its notes by
   instrument family + playing technique.
3. **Add any melodic overrides** (`MELODIC_VOICE_MAP.json`) where the
   destination has a clearly better voice than its automatic GM fallback.
4. Point the folder/category names in `revoice.py` at your files.

The binary-editing core (SFF parsing, the Bank-Select rewrite, per-channel note
remapping) stays exactly the same. **Feel free to fork and adapt it for your own
keyboards** — the hard part (getting the byte-level style editing right) is done.

## Limitations

- The note maps are built from instrument-name/technique matching, **not**
  verified against audio. They are far better than a blind kit swap, but a
  musician's ear can refine specific choices.
- The "Mix" kits are drum-set + ethnic hybrids. Their drum-set backbone maps
  cleanly to GM Standard Kit; their *ethnic* hits are **approximated** to GM
  congas/toms/tambourine because Standard Kit has no goblet/frame drums.
- The CVP-805 Data List is shared with the CVP-809. Kit presence is taken from
  the per-model checkmarks; the ethnic kits (Turkish confirmed) should ideally
  be confirmed on the actual CVP-805 hardware.
- One anomaly (`62-0-5`, an undefined MSB-62 bank present in a few source files)
  is safely mapped to Standard Kit.
