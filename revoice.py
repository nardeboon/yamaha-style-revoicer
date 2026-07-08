#!/usr/bin/env python3
"""
revoice.py — Convert Yamaha OR-700 preset styles to play correctly on a CVP-805.

WHY THIS EXISTS
---------------
The Yamaha PSR-OR700 is an "oriental" arranger with ethnic drum kits (Iranian,
Arabic, Khaligi, Turkish) and ethnic melodic voices (Tar, Nay, Sorna, Oud...).
The Clavinova CVP-805 is a Western instrument that does not have most of those
sounds at the same MIDI addresses. Loading an OR-700 style on a CVP-805 as-is
therefore plays the wrong drum kit (often *sound effects*) and wrong voices.

This tool rewrites the binary style files so their drum channels and (a few)
melodic channels point at the closest real CVP-805 sounds, and remaps the
individual drum notes so each ethnic hit lands on the nearest CVP-805 hit.

NOT LIMITED TO OR-700 -> CVP-805
--------------------------------
The engine below is generic: it only understands MSB-LSB-PC addresses, Bank
Select and note remapping. All instrument-specific knowledge lives in the JSON
data files. To convert between any other pair of Yamaha keyboards (Genos, Tyros,
PSR-S/SX, PSR-A, CVP...), extract that pair's Voice List / Drum-Key Assignment
tables into the same JSON format and adjust NOTE_MAPS.json / MELODIC_VOICE_MAP.json.
The byte-level style editing stays identical. See README.md ("Adapting this to
other Yamaha keyboards"). Contributions/forks for other keyboards are welcome.

HOW A YAMAHA STYLE FILE IS LAID OUT
-----------------------------------
A .STY / .PRS file is Standard Style File Format (SFF1): a standard MIDI file
(MThd + one MTrk) followed by Yamaha-specific chunks (CASM, OTSc, ...). We only
touch the MTrk chunk. Its byte layout from the start of the file is:

    MThd (4) | size (4) | header data (6) | MTrk (4) | size (4) | events...
    \_________________ 14 bytes _________________/   ^ MTrk tag starts at 14

A voice/kit is selected by three MIDI messages on a channel, in order:
    Bank Select MSB  = Control Change 0   (CC0)
    Bank Select LSB  = Control Change 32  (CC32)
    Program Change   (the "PC")
We identify every voice/kit by the triple "MSB-LSB-PC".

TWO IMPORTANT YAMAHA FACTS THIS CODE RELIES ON
----------------------------------------------
1. Data-list PC numbers are 1-based (1-128); the byte inside the style file is
   0-based (0-127). All JSON tables here are keyed by the 0-based file value,
   i.e. data-list number minus 1. (See DATA_REFERENCE.md.)
2. Bank MSB 127 is the *drum-kit* bank; MSB 126 is the *SFX / ethnic* bank.
   So 126-0-0 = "SFX Kit 1" = sound effects, NOT a drum kit. This is why a kit
   remap must rewrite the Bank Select too — changing only the Program Change
   would leave MSB=126 and play sound effects on the keyboard.

DATA FILES (all extracted from the official Yamaha Data List PDFs)
------------------------------------------------------------------
    OR700_VOICE_TABLE.json     / CVP805_VOICE_TABLE.json    voice name per MSB-LSB-PC
    OR700_DRUMKIT_TABLE.json   / CVP805_DRUMKIT_TABLE.json  kit name per MSB-LSB-PC
    NOTE_MAPS.json             per-kit note remap + target kit
    MELODIC_VOICE_MAP.json     explicit melodic voice overrides
    KIT_NOTE_ASSIGNMENTS.json  note-by-note instrument names (reference)

USAGE
-----
    python revoice.py [num_files] [category|ALL]

    python revoice.py            # all files in the Iranian folder
    python revoice.py 5 Iranian  # first 5 Iranian files
    python revoice.py 999 ALL    # every file in every category folder
"""

import os
import json
import struct
from collections import Counter, defaultdict
from datetime import datetime

# MIDI channels that carry drum kits in a Yamaha style (0-based: 8 = MIDI ch 9,
# 9 = MIDI ch 10). Everything else is treated as a melodic channel.
DRUM_CHANNELS = (8, 9)

# The four style categories shipped by the OR-700, each a sub-folder.
CATEGORIES = ["Iranian", "Arabic&Maghrebi", "Khaligi", "Turkish&Greek"]


class StyleRevoicer:
    """Reads OR-700 style files, rewrites their drum/voice bytes for the CVP-805."""

    def __init__(self, base_path, category="Iranian"):
        self.base_path = base_path
        self.category = category
        self.styles_path = os.path.join(base_path, "OR700-Preset-Styles", category)
        self.output_dir = os.path.join(base_path, "OR700-Preset-Styles-CVP805", category)
        os.makedirs(self.output_dir, exist_ok=True)

        # Which MIDI channel indices carry drum kits. Default is the standard Yamaha
        # layout (9 & 10). Amateur styles can remap channels via the CASM section, so
        # a caller may override this per file (see convert_psr_iranian.py).
        self.drum_channels = set(DRUM_CHANNELS)

        # Load the authoritative lookup tables. All keys are "MSB-LSB-PC" with a
        # 0-based PC (the value actually stored in the style file). A "_convention"
        # key documents this inside each file; it is never a real MSB-LSB-PC key.
        def _load(name):
            with open(os.path.join(base_path, name), "r", encoding="utf-8") as f:
                return json.load(f)

        self.or700_voices = _load("OR700_VOICE_TABLE.json")
        self.cvp805_voices = _load("CVP805_VOICE_TABLE.json")
        self.or700_kits = _load("OR700_DRUMKIT_TABLE.json")
        self.cvp805_kits = _load("CVP805_DRUMKIT_TABLE.json")
        # Drum note maps: {source kit "MSB-LSB-PC": {"target": "...", "notes": {...}}}
        self.note_maps = _load("NOTE_MAPS.json")
        # Melodic voice overrides: {(msb,lsb,pc): (msb',lsb',pc')}, non-drum channels only.
        self.voice_map = {}
        for k, v in _load("MELODIC_VOICE_MAP.json").items():
            if k == "_convention":
                continue
            self.voice_map[tuple(int(x) for x in k.split("-"))] = tuple(int(x) for x in v.split("-"))

    # ------------------------------------------------------------------ helpers

    def get_voice_name(self, msb, lsb, pc, source="or700"):
        """Human-readable voice name for a full MSB-LSB-PC address."""
        table = self.or700_voices if source == "or700" else self.cvp805_voices
        return table.get(f"{msb}-{lsb}-{pc}", f"(unnamed {msb}-{lsb}-{pc} - XG/GM default)")

    @staticmethod
    def write_vlq(value):
        """Encode an integer as a MIDI Variable-Length Quantity (used for delta times)."""
        out = [value & 0x7f]
        value >>= 7
        while value:
            out.insert(0, 0x80 | (value & 0x7f))
            value >>= 7
        return bytes(out)

    # ------------------------------------------------------------- kit decision

    def get_kit_mapping(self, msb, lsb, pc):
        """
        Decide the CVP-805 target for one OR-700 drum kit.

        Returns a dict with the source/target kit names, the target "MSB-LSB-PC"
        address, and a note map (may be empty). Three cases, in priority order:
          1. The exact kit already exists on the CVP-805 -> leave it unchanged.
          2. We have an explicit note map for it -> use that target + notes.
          3. Unknown kit -> fall back to Standard Kit 1 (a real 127-bank drum kit,
             never the SFX bank).
        """
        kit_key = f"{msb}-{lsb}-{pc}"
        src_name = self.or700_kits.get(kit_key, "Unknown Kit")

        if kit_key in self.cvp805_kits:
            return {"or700_kit": src_name, "cvp805_kit": self.cvp805_kits[kit_key],
                    "target_key": kit_key, "note_map": {},
                    "reason": "Identical kit exists on CVP-805 - no change"}

        if kit_key in self.note_maps:
            entry = self.note_maps[kit_key]
            tkey = entry["target"]
            return {"or700_kit": src_name, "cvp805_kit": self.cvp805_kits.get(tkey, tkey),
                    "target_key": tkey, "note_map": {int(k): v for k, v in entry["notes"].items()},
                    "reason": "Nearest ethnic match (note-mapped)"}

        return {"or700_kit": src_name, "cvp805_kit": self.cvp805_kits.get("127-0-0", "Standard Kit 1"),
                "target_key": "127-0-0", "note_map": {},
                "reason": "No CVP-805 match - fell back to Standard Kit 1"}

    # ------------------------------------------------------------- MIDI scanning

    def extract_midi_data(self, sty_path):
        """
        Light scan of a style file to inventory what voices/kits it uses.

        This is used only for the human-readable report, so it is a simple
        forward byte scan (not a full event parser). It tracks the running Bank
        Select per channel and records every Program Change. The actual editing
        is done by remap_miditrack(), which is a proper event parser.

        Returns: (programs, drum_kits, raw_bytes)
          programs  : {channel: Counter({(msb,lsb,pc): count})}
          drum_kits : [{'msb','lsb','pc','channel'}] for drum channels only
        """
        try:
            with open(sty_path, "rb") as f:
                data = f.read()

            programs = defaultdict(Counter)
            drum_kits = []
            # Bank Select is per-channel state, so track all 16 channels separately.
            channel_state = {ch: {"msb": 0, "lsb": 0} for ch in range(16)}

            i = 0
            while i < len(data) - 2:
                byte = data[i]

                # Control Change 0xB0-0xBF: capture Bank Select MSB (CC0) / LSB (CC32).
                if 0xb0 <= byte <= 0xbf and i + 2 < len(data):
                    channel = byte & 0x0f
                    if data[i + 1] == 0x00:      # CC0  = Bank Select MSB
                        channel_state[channel]["msb"] = data[i + 2]
                        i += 3
                        continue
                    if data[i + 1] == 0x20:      # CC32 = Bank Select LSB
                        channel_state[channel]["lsb"] = data[i + 2]
                        i += 3
                        continue

                # Program Change 0xC0-0xCF. The data byte must be a valid 0-127 MIDI
                # value; a value >127 means we mis-hit a data byte (this crude scanner
                # has no event boundaries) so we skip it to avoid phantom kits.
                if 0xc0 <= byte <= 0xcf and i + 1 < len(data) and data[i + 1] < 128:
                    channel = byte & 0x0f
                    program = data[i + 1]
                    addr = (channel_state[channel]["msb"], channel_state[channel]["lsb"], program)
                    programs[channel][addr] += 1
                    if channel in self.drum_channels:
                        drum_kits.append({"pc": program, "channel": channel,
                                          "msb": channel_state[channel]["msb"],
                                          "lsb": channel_state[channel]["lsb"]})
                    i += 2
                else:
                    i += 1

            return dict(programs), drum_kits, data
        except Exception as e:
            print(f"  ERROR extracting: {e}")
            return {}, [], None

    # --------------------------------------------------------------- MIDI editing

    def remap_miditrack(self, mtrk_data, target_by_ch, note_map_by_ch=None):
        """
        Proper MIDI event parser that rewrites the MTrk chunk.

        Two kinds of edit, applied per channel:
          * Drum channels (8/9): rewrite the FULL bank address (MSB+LSB+PC) to the
            target kit, and remap individual drum notes. Rewriting the whole
            address (not just the PC) is essential — otherwise a fallback to
            Standard Kit 127-0-0 would leave MSB=126 and select 126-0-0 = the SFX
            (sound-effects) kit.
          * Melodic channels: if a voice has an explicit override, rewrite its
            bank + PC; otherwise leave it (the CVP-805 falls back to the GM voice).

        Because Bank Select (CC0/CC32) is emitted *before* the Program Change, we
        remember the byte offset of each channel's last MSB/LSB value in the output
        buffer, then patch those bytes retroactively when the PC arrives.

        Returns: (new_mtrk_bytes, pc_changes, note_changes, note_stats, voice_changes)
        """
        if note_map_by_ch is None:
            note_map_by_ch = {}

        # mtrk_data is the full chunk: "MTrk"(4) + size(4) + events. Copy the 8-byte
        # header verbatim and parse events starting at byte 8. (Earlier code started
        # at 4, i.e. inside the size field, which usually round-tripped but could
        # silently desync and skip a channel on some files.)
        output = bytearray(mtrk_data[:8])
        pos = 8
        pc_changes = note_changes = voice_changes = 0
        note_stats = {n: 0 for nm in note_map_by_ch.values() for n in nm}

        # Per-channel bank state + where its value bytes live in `output`, so a
        # later Program Change can patch them. msb_off/lsb_off index into `output`.
        bank = {ch: {"msb": 0, "lsb": 0, "msb_off": None, "lsb_off": None} for ch in range(16)}

        while pos < len(mtrk_data):
            # --- read the VLQ delta time and copy it through unchanged ---
            delta = 0
            while pos < len(mtrk_data):
                b = mtrk_data[pos]
                pos += 1
                delta = (delta << 7) | (b & 0x7f)
                if not (b & 0x80):
                    break
            if pos >= len(mtrk_data):
                break
            output.extend(self.write_vlq(delta))

            evt_type = mtrk_data[pos]
            pos += 1

            if evt_type == 0xff:                       # Meta event: copy verbatim
                output.append(evt_type)
                output.append(mtrk_data[pos])          # meta type
                pos += 1
                length = 0
                while pos < len(mtrk_data):
                    b = mtrk_data[pos]
                    pos += 1
                    length = (length << 7) | (b & 0x7f)
                    if not (b & 0x80):
                        break
                output.extend(self.write_vlq(length))
                output.extend(mtrk_data[pos:pos + length])
                pos += length

            elif evt_type in (0xf0, 0xf7):             # SysEx: copy verbatim
                output.append(evt_type)
                length = 0
                while pos < len(mtrk_data):
                    b = mtrk_data[pos]
                    pos += 1
                    length = (length << 7) | (b & 0x7f)
                    if not (b & 0x80):
                        break
                output.extend(self.write_vlq(length))
                output.extend(mtrk_data[pos:pos + length])
                pos += length

            else:                                      # MIDI channel voice message
                status = evt_type
                ch = status & 0x0f
                msg_type = (status >> 4) & 0x0f
                output.append(status)

                if msg_type == 0x09:                   # Note On -> remap the note number
                    note, velocity = mtrk_data[pos], mtrk_data[pos + 1]
                    nmap = note_map_by_ch.get(ch, {})
                    if note in nmap:
                        output.append(nmap[note])
                        note_stats[note] = note_stats.get(note, 0) + 1
                        note_changes += 1
                    else:
                        output.append(note)
                    output.append(velocity)
                    pos += 2

                elif msg_type == 0x08:                 # Note Off -> same remap as Note On
                    note, velocity = mtrk_data[pos], mtrk_data[pos + 1]
                    output.append(note_map_by_ch.get(ch, {}).get(note, note))
                    output.append(velocity)
                    pos += 2

                elif msg_type == 0x0b:                 # Control Change
                    cc_num, cc_val = mtrk_data[pos], mtrk_data[pos + 1]
                    output.append(cc_num)
                    output.append(cc_val)
                    # Remember where Bank Select value bytes landed so a later PC can patch them.
                    if cc_num == 0x00:
                        bank[ch]["msb"] = cc_val
                        bank[ch]["msb_off"] = len(output) - 1
                    elif cc_num == 0x20:
                        bank[ch]["lsb"] = cc_val
                        bank[ch]["lsb_off"] = len(output) - 1
                    pos += 2

                elif msg_type == 0x0c:                 # Program Change
                    old_pc = mtrk_data[pos]
                    if ch in self.drum_channels:
                        # Drum kit: rewrite the whole MSB-LSB-PC address to the target.
                        tgt = target_by_ch.get(ch, {}).get(old_pc)
                        # Safety net: a rhythm channel must never carry a melodic voice.
                        # If this program change wasn't pre-detected but the current bank
                        # is melodic (MSB not 126/127), force it to Standard Kit so it
                        # can't play as a piano/guitar (covers PCs the pre-scan missed,
                        # e.g. in Intro/Ending sections).
                        if tgt is None and bank[ch]["msb"] not in (126, 127):
                            tgt = (127, 0, 0)
                        if tgt:
                            tmsb, tlsb, tpc = tgt
                            changed = (bank[ch]["msb"], bank[ch]["lsb"], old_pc) != (tmsb, tlsb, tpc)
                            if bank[ch]["msb_off"] is not None and bank[ch]["lsb_off"] is not None:
                                # a bank select precedes this PC in the same section: patch it
                                output[bank[ch]["msb_off"]] = tmsb
                                output[bank[ch]["lsb_off"]] = tlsb
                                output.append(tpc)
                            else:
                                # no bank select to patch -> INJECT one before the PC.
                                # output currently ends with [delta][PC status]; drop the
                                # status and re-emit CC0+CC32 (using the PC's delta) then PC.
                                output.pop()
                                cc = 0xB0 | ch
                                output += bytes([cc, 0x00, tmsb])         # CC0 = MSB (PC's delta)
                                output += bytes([0x00, cc, 0x20, tlsb])   # delta0, CC32 = LSB
                                output += bytes([0x00, 0xC0 | ch, tpc])   # delta0, Program Change
                            bank[ch]["msb"], bank[ch]["lsb"] = tmsb, tlsb
                            if changed:
                                pc_changes += 1
                        else:
                            output.append(old_pc)
                        # reset per-section bank tracking so the next PC finds its own bank
                        bank[ch]["msb_off"] = bank[ch]["lsb_off"] = None
                    else:
                        # Melodic voice: rewrite bank + PC only if we have an override.
                        src = (bank[ch]["msb"], bank[ch]["lsb"], old_pc)
                        if src in self.voice_map:
                            nmsb, nlsb, npc = self.voice_map[src]
                            if bank[ch]["msb_off"] is not None:
                                output[bank[ch]["msb_off"]] = nmsb
                            if bank[ch]["lsb_off"] is not None:
                                output[bank[ch]["lsb_off"]] = nlsb
                            output.append(npc)
                            voice_changes += 1
                        else:
                            output.append(old_pc)
                    pos += 1

                elif msg_type == 0x0e:                 # Pitch Bend (2 data bytes)
                    output.append(mtrk_data[pos])
                    output.append(mtrk_data[pos + 1])
                    pos += 2

                elif msg_type == 0x0d:                 # Channel Aftertouch (1 data byte)
                    output.append(mtrk_data[pos])
                    pos += 1

        # Write the correct MTrk size into the header (bytes 4-8) so the returned
        # chunk is self-consistent even when injection changed the event length.
        output[4:8] = struct.pack(">I", len(output) - 8)
        return bytes(output), pc_changes, note_changes, note_stats, voice_changes

    def edit_style_file(self, sty_path, output_path, drum_kits):
        """Load a style file, rewrite its MTrk, and write the converted copy."""
        print("  Reading and editing binary file...")
        with open(sty_path, "rb") as f:
            data = bytearray(f.read())

        # Build the per-channel edit plan. The target carries the FULL address so
        # the Bank Select is rewritten too (see class/module notes on the SFX bug).
        target_by_ch = {}    # {channel: {old_pc: (tmsb, tlsb, tpc)}}
        note_map_by_ch = {}  # {channel: {old_note: new_note}}
        for kit in drum_kits:
            ch = kit.get("channel", 9)
            or_pc = kit["pc"]
            mapping = self.get_kit_mapping(kit["msb"], kit["lsb"], or_pc)
            tmsb, tlsb, tpc = (int(x) for x in mapping["target_key"].split("-"))
            target_by_ch.setdefault(ch, {})[or_pc] = (tmsb, tlsb, tpc)
            if mapping["note_map"]:
                note_map_by_ch.setdefault(ch, {}).update(mapping["note_map"])
            src = f"{kit['msb']}-{kit['lsb']}-{or_pc}"
            change = "no change" if src == mapping["target_key"] else f"{src} -> {mapping['target_key']}"
            print(f"    ch{ch + 1}: {mapping['or700_kit']} -> {mapping['cvp805_kit']} ({change})")
            if mapping["note_map"]:
                print(f"          note remap: {mapping['note_map']}")

        # The MTrk tag sits at byte 14 (MThd 4 + size 4 + 6 bytes of header data).
        mtrk_offset = 14
        if data[mtrk_offset:mtrk_offset + 4] != b"MTrk":
            print(f"  ERROR: MTrk not at expected offset {mtrk_offset}")
            return False
        mtrk_size = struct.unpack_from(">I", data, mtrk_offset + 4)[0]
        mtrk_data = bytes(data[mtrk_offset:mtrk_offset + 8 + mtrk_size])

        remapped_mtrk, pc_changes, note_changes, note_stats, voice_changes = self.remap_miditrack(
            mtrk_data, target_by_ch, note_map_by_ch)
        print(f"    PC changes: {pc_changes}, Note changes: {note_changes}, Voice changes: {voice_changes}")
        for note, count in sorted(note_stats.items()):
            if count:
                print(f"      Note {note}: {count} events remapped")

        # Splice the new MTrk (which already carries a correct size header) back in,
        # keeping the header before it and the trailing CASM/OTSc chunks after it.
        if len(remapped_mtrk) != len(mtrk_data):
            print(f"  MTrk size changed: {mtrk_size} -> {len(remapped_mtrk) - 8}")
        data = bytearray(data[:14]) + remapped_mtrk + data[mtrk_offset + 8 + mtrk_size:]

        with open(output_path, "wb") as f:
            f.write(data)
        return True

    # ------------------------------------------------------------------ reporting

    def create_report(self, filename, programs, drum_kits):
        """Write a Markdown report next to the converted file documenting every change."""
        stem = os.path.splitext(filename)[0]
        report_path = os.path.join(self.output_dir, stem + "_CVP805_V1_REPORT.md")

        report = (f"# Remapping Report: {filename}\n\n"
                  f"**Processed:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                  f"**Status:** V1 (binary edited)\n\n## Drum Kits Remapped\n\n")
        for kit in drum_kits:
            mapping = self.get_kit_mapping(kit["msb"], kit["lsb"], kit["pc"])
            ch = kit.get("channel", 9) + 1
            note = f" | note remap: {mapping['note_map']}" if mapping["note_map"] else ""
            report += (f"- Ch{ch}: **{mapping['or700_kit']}** ({kit['msb']}-{kit['lsb']}-{kit['pc']}) "
                       f"-> **{mapping['cvp805_kit']}** ({mapping['target_key']}) — "
                       f"{mapping['reason']}{note}\n")

        report += "\n## Melodic Voices (named from OR-700 data list)\n\n"
        for channel in sorted(c for c in programs if c not in self.drum_channels):
            if not programs[channel]:
                continue
            report += f"### Channel {channel + 1}\n"
            for (msb, lsb, pc), count in sorted(programs[channel].items(), key=lambda x: -x[1]):
                # A drum-bank (MSB 126/127) can appear on a melodic channel; label it as such.
                if msb in (126, 127):
                    kit = (self.cvp805_kits.get(f"{msb}-{lsb}-{pc}")
                           or self.or700_kits.get(f"{msb}-{lsb}-{pc}", "drum kit"))
                    report += f"- [drum-bank on this channel] {kit} ({msb}-{lsb}-{pc}) x{count}\n"
                    continue
                name = self.get_voice_name(msb, lsb, pc, "or700")
                on_cvp = self.cvp805_voices.get(f"{msb}-{lsb}-{pc}")
                status = "same on CVP-805" if on_cvp else f"not on CVP-805 -> GM fallback (PC {pc})"
                report += f"- {name}  ({msb}-{lsb}-{pc}) x{count}  [{status}]\n"
            report += "\n"

        report += ("## Summary\n\n"
                   "- Drum channels remapped per the table above; unlisted melodic voices "
                   "rely on the CVP-805 GM fallback.\n- **Ready for testing:** load on CVP-805.\n")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        return report_path

    # ------------------------------------------------------------------ driver

    def process_file(self, filename):
        """Convert one style file and write its report. Returns a result dict or None."""
        sty_path = os.path.join(self.styles_path, filename)
        if not os.path.exists(sty_path):
            print("  ERROR: File not found")
            return None

        print(f"\nProcessing: {filename}")
        print("-" * 70)
        programs, drum_kits, _ = self.extract_midi_data(sty_path)
        if not programs and not drum_kits:
            print("  WARNING: No MIDI data found")
            return None
        print(f"  Drum kits: {len(drum_kits)}, "
              f"Melodic channels: {len([c for c in programs if c not in self.drum_channels])}")

        # Output keeps the original extension (.STY or .PRS) with a _CVP805_V1 suffix.
        stem, ext = os.path.splitext(filename)
        output_path = os.path.join(self.output_dir, f"{stem}_CVP805_V1{ext}")
        if not self.edit_style_file(sty_path, output_path, drum_kits):
            print("  ERROR: Failed to edit file")
            return None
        self.create_report(filename, programs, drum_kits)
        print(f"  Output: {os.path.basename(output_path)}")
        return {"filename": filename, "status": "OK"}

    def run(self, num_files=999):
        """Convert up to num_files style files in this category folder."""
        print("\n" + "=" * 80)
        print(f"STYLE REVOICER  OR-700 -> CVP-805  [{self.category}]")
        print("=" * 80)
        all_files = sorted(f for f in os.listdir(self.styles_path)
                           if f.upper().endswith((".STY", ".PRS")))
        print(f"Style files (.STY + .PRS): {len(all_files)}\n")

        results = [r for f in all_files[:num_files] if (r := self.process_file(f))]
        print("\n" + "=" * 80)
        print(f"COMPLETED: {len(results)}/{min(num_files, len(all_files))} files converted")
        print("=" * 80 + "\n")
        return results


def main():
    import sys
    base_path = os.path.dirname(os.path.abspath(__file__))
    num_files = int(sys.argv[1]) if len(sys.argv) > 1 else 999
    category = sys.argv[2] if len(sys.argv) > 2 else "Iranian"

    categories = CATEGORIES if category.upper() == "ALL" else [category]
    for cat in categories:
        StyleRevoicer(base_path, category=cat).run(num_files=num_files)


if __name__ == "__main__":
    main()
