# PSR Iranian styles → CVP-805 (`convert_psr_iranian.py`)

A second pipeline, separate from the OR-700 work, for **user-made PSR Iranian
styles** (the `Iranian1/` + `Iranian2/` folders, 96 SFF1 GM/XG styles). Output
goes to a single folder **`Iranian-Combined-CVP805/`**, renamed by each style's
real embedded name.

These amateur styles are messy in ways the OR-700 presets are not, so the
converter does several genre-aware passes.

## 1. CASM-aware channel roles (critical)
Many of these styles (43 of 96) have a **non-standard channel layout**. A Yamaha
style's CASM section maps each MTrk channel to a role (Rhythm1/2 = drums, Bass,
Chord1/2, Pad, Phrase1/2); these makers remapped them (e.g. the main drums on
MIDI ch16, not ch10). The converter reads the CASM **destination channel** (which
always follows the standard role convention) to get the true role of every
channel — never assuming ch9/ch10 = drums.

## 2. Voices
- GM/XG voices on melodic-role channels are upgraded to CVP-805 panel voices
  (CFX piano, Classical/Concert strings, Symphony brass, dynamic guitars, …).
- Drum-role channels are forced to a real drum kit only if they carry a melodic
  voice; existing kits are kept.

## 3. Volume — normalized to a professional per-ROLE reference
Amateur styles slam every channel to 127. Reference CC7 per role was learned from
the OR-700 presets (same genres), nudged for Iranian pop/dance:
`Rhythm1 66, Rhythm2 62, Bass 60, Chord1 50, Chord2 54, Pad 48, Phrase1 66,
Phrase2 62`. Each channel's CC7 is scaled **proportionally** toward its role
target (preserving the maker's relative mix); a volume is injected where a
channel plays but never set one; dead ch1-8 setup data (no notes) is capped.
Result: highest volume anywhere is 66, nothing sits at 100+.

Velocity is also tamed: the amateurs hit ~40% harder than the pros (median note
velocity 99 vs the OR-700's 71). Each style's velocities are scaled per-style
toward the pro median (proportionally, so Intro-soft ... Main-D-full dynamics are
kept), fixing the "too loud in Main B/C" sections.

## 4. Genre refinement (`refine()`)
A final musical pass fixes genre-inappropriate choices:
- unresolved voice `0-127-22` → **Accordion** (0-116-21);
- non-bass voices sitting on the **Bass** part (strings / lead / EP / piano) →
  **Electric Bass** (guitars are kept — guitar basslines are legitimate);
- **OrchestraHit / Atmosphere** used as a lead melody → **Concert Strings**;
- drum note **83** (which plays "Jingle Bells" on Western kits — the daf/frame-
  drum jingle part) → note **54 (Tambourine)**.


## 5. Genre tag + genre-matched OTS (rotated)
Each output filename gets its **detected genre** appended, e.g. `Bandari-1 [Bandari]`,
`ALI R3 [6-8]`, `AFGHANI [Afghani]`. The genre is found by name keyword (precise)
else by the nearest-rhythm OR-700 match (`match_rhythm.py`).

The amateur styles have **no OTS** (0/96); the converter appends the OTSc chunk
from an OR-700 preset of that genre. When a genre has several OR-700 presets
(e.g. 6-8 has 5, Bandari has 3, Raghs has several) it **rotates** through them so
styles of the same genre don't all get an identical OTS. The genre tag always
matches the chosen OTS. OR-700 OTS carry no tempo events, so pressing OTS doesn't
change the style's tempo; voices fall back to the CVP-805's related GM voice.

Distribution (96 styles): 37 matched by name, 59 by rhythm; genres span Club,
6-8, Raghs, Bandari, Turkish, Arabic, Asouri, Kurdish, Azari, Lori, Avaaz, Afghani.


## Verify (reproducible)
Run `python analyze.py` to re-check any output folder: chunk integrity, OTS
presence, melodic-voice-on-drum, loud channels, drum-note range, velocity level,
tempo range, and per-role volume medians.

## Verified
- 96/96 output files valid (MTrk + CASM + OTSc chunks parse cleanly); tempo byte-identical to source (never touched) and
  within the OR-700 professional range (55–190 BPM) with no outliers;
- drums confirmed on the real (CASM) channels; 0 melodic voices left on a drum
  channel; every role's median volume matches its reference.

## Known edge case
`AMER06 8` (source 084) genuinely had a melodic Nylon-Guitar riff on a real drum
channel; the rule forces it to a drum kit, so that riff plays as percussion.
