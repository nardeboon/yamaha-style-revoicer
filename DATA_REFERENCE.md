# Yamaha OR-700 → CVP-805 Conversion — Data Reference

**Last updated:** 2026-07-03
**Status:** Data layer rebuilt from official Yamaha Data List PDFs and verified.

---

## Source PDFs
- `psror700_en_de_fr_dl_a0.pdf` — PSR-OR700 Data List
- `cvp809_en_dl_c0.pdf` — CVP-809/CVP-805 Data List (shared document; CVP-805 columns/checkmarks used)

## Key convention (IMPORTANT)
Yamaha PDFs print **PC# as 1-based (1–128)**. The actual **byte inside a `.STY` file is 0-based (0–127)**.
All table keys are stored as **0-based MIDI** = `PDF PC# − 1`, so they match the raw style-file bytes.

> To find a JSON entry in the PDF, **add 1** to the last number.
> e.g. JSON `126-0-35 Arabic Kit` = PDF `126-0-36`.
> Verified: Standard Kit 1 = JSON `127-0-0` = PDF `127-0-1` = MIDI 0.

Exception: in `KIT_NOTE_ASSIGNMENTS.json`, the **inner note keys are raw MIDI note numbers** (the "Note#" column = the note byte in the file), not offset.

---

## The 5 authoritative data files
| File | Entries | Source |
|------|---------|--------|
| `OR700_VOICE_TABLE.json` | 1120 voices | OR700 PDF Voice List pp.1–10 |
| `CVP805_VOICE_TABLE.json` | 2159 voices | CVP PDF Voice List pp.16–32 |
| `OR700_DRUMKIT_TABLE.json` | 22 kits | OR700 PDF |
| `CVP805_DRUMKIT_TABLE.json` | 47 kits | CVP PDF **Drum/Key Assignment List pp.39–52**, validated by CVP-805 checkmark glyph (U+F081 = present, U+2013 = absent) |
| `KIT_NOTE_ASSIGNMENTS.json` | 6 kits | Drum/Key Assignment Lists (note-by-note) |

809-only kits (Bass Drum Kit, Afro Cuban Kit, Brazilian Kit, 80s Pop/R&B, all `MSB=…-8-…` variants) are **correctly excluded** from the CVP-805 table.

---

## Drum kits actually used across the 26 style files
(Arabic&Maghrebi 16, Iranian 5, Turkish&Greek 5)

| Kit (MIDI) | # files | OR-700 name | On CVP-805? | Action |
|-----------|--------:|-------------|-------------|--------|
| 126-0-36 | 20 | ArabicKit 1 | no | **remap → Arabic Kit (126-0-35)** |
| 126-0-64 | 18 | ArabicMixKit | no | **remap** (fusion kit; target TBD) |
| 127-0-27 | 6 | DanceKit | **yes** (Dance Kit) | no change |
| 126-0-38 | 4 | IranianKit | no | **remap → Turkish Kit (126-0-67)** |
| 127-0-0 | 2 | StandardKit1 | **yes** | no change |
| 127-0-8 | 1 | RoomKit | **yes** (Room Kit) | no change |
| 126-0-66 | 1 | IranianMixKit | no | **remap** (fusion kit; target TBD) |
| 62-0-5 | 1 | (anomaly, not a real drum bank) | no | fallback → Standard Kit |

Kits present on **both** keyboards (Dance/Standard/Room) need **no** editing.

---

## Note assignments extracted (`KIT_NOTE_ASSIGNMENTS.json`)

**Source kits (OR-700):**
- `IranianKit` 126-0-38 — Daf, Neghareh, Kurdish/Lurish Dohol, Tombak, Zarb, Dayereh (43 notes)
- `ArabicKit1` 126-0-36 — Zarb, Tombak, Neghareh, Daholla, Tablah, Katem, Merwas, Tar (72 notes)
- `ArabicMixKit` 126-0-64 — Congas, electronic drums, Side Stick (fusion, 72 notes)
- `IranianMixKit` 126-0-66 — Bongo, Conga, Floor Tom, Hi-Hat (fusion, 72 notes)

**Target kits (CVP-805):**
- `TurkishKit` 126-0-67 — Asma/Koltuk Davul, Bendir, Zil, Tef, Darbuka, Bongo (72 notes)
- `ArabicKit` 126-0-35 — Nakarazan, Hager, Cabasa, Bongo (61 notes)

---

## Note maps (`NOTE_MAPS.json`) — DONE for the two main ethnic kits
Built by instrument-family + playing-technique matching from `KIT_NOTE_ASSIGNMENTS.json`.
The processor loads this file; source notes not listed pass through unchanged.

- **IranianKit 126-0-38 → Turkish Kit 126-0-67** (41 notes): Tombak/Zarb→Darbuka,
  Daf→Bendir/Tef, Dayereh→Tef, Neghareh→Bass Darbuka, Dohol→Asma/Koltuk Davul.
- **ArabicKit1 126-0-36 → Arabic Kit 126-0-35** (70 notes): mostly name-direct
  (Katem→Katem, Tablah→Tabla, Riq→Riq, Sagat→Sagat, Tabel→Tabel, Daholla→Duhulla);
  Zagrouda vocal notes 34/35 deliberately never targeted.

Verified on 6-8Dance: ch9 Tombak/Zarb notes remap into the Darbuka range; ch10
RoomKit stays byte-identical; melodic channels untouched.

## Melodic voice map (`MELODIC_VOICE_MAP.json`)
OR-700 ethnic panel voices are not at the same CVP-805 address; the CVP-805 auto-falls-
back to the GM voice at that PC, which Yamaha designed to be a related instrument
(Nay/Kawala→Shakuhachi, Sorna/Mizmar/Argoul→Shanai, Watariyat→Strings, Santoor→Dulcimer,
Kamanche→Violin, **Tar→Banjo** kept on purpose, Kanoun→Koto, Saz/Bouzouki→Steel Guitar).
Only voices where the CVP-805 has a clearly better match get an explicit remap:
- **Oriental Oud 0-113-105 → real Oud 0-98-105** (instead of the Banjo fallback).

The processor rewrites Bank Select MSB/LSB + PC bytes for mapped melodic voices only;
everything else passes through.

## Critical: Bank Select must be rewritten, not just PC
MSB 126 is Yamaha's **SFX/ethnic bank**; MSB 127 is the standard drum-kit bank.
`126-0-0` = "SFX Kit 1" = **sound effects**, NOT a drum kit. When a source kit
remaps to a different bank (e.g. KhaligiKit 126-0-37 -> Standard Kit **127**-0-0),
the processor must rewrite Bank Select MSB+LSB **and** PC. Changing only the PC
left MSB=126 and produced `126-0-0` = sound effects on the keyboard. Fixed:
drum remap now rewrites the full MSB-LSB-PC address (same mechanism as melodic).

## Full kit coverage (all 6 remapped source kits)
| Source kit | Target | Notes |
|-----------|--------|-------|
| IranianKit 126-0-38 | Turkish Kit 126-0-67 | Tombak/Zarb→Darbuka etc. (**confirmed working on user's 805**) |
| ArabicKit1 126-0-36 | Arabic Kit 126-0-35 | name-direct |
| KhaligiKit 126-0-37 | Arabic Kit 126-0-35 | Gulf percussion→Arabic |
| ArabicMixKit 126-0-64 | Standard Kit 127-0-0 | fusion → GM positions |
| KhaligiMixKit 126-0-65 | Standard Kit 127-0-0 | fusion → GM positions |
| IranianMixKit 126-0-66 | Standard Kit 127-0-0 | fusion → GM positions |

Mix kits are drum-set + ethnic hybrids; the drum-set backbone maps to GM Standard
Kit, ethnic hits are **approximated** to GM congas/toms/tambourine (lossy but audible).
All 40 Iranian outputs verified: **no drum channel on an SFX slot**.

## Open items
1. **Hardware confirmation** on Arabic Kit (Turkish already confirmed by user).
2. Mix-kit ethnic hits are GM approximations — could be refined by ear.
3. Processor scans only the Iranian folder; Arabic/Turkish&Greek folders (also
   using ArabicKit1/KhaligiKit + the Oud melodic remap) still to be wired in.
4. `62-0-5` anomaly (1 file) — not a real kit, falls back to Standard.
