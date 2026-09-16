#!/usr/bin/env python3
"""Synchronize DuckStation savestates with patched PROG.UNT Entry 3.

DuckStation savestates (.sav) store freeze-frame snapshots of PS1 2MB RAM.
When a user saves while inside a town/shop, Entry 3 is already loaded into RAM
at address 0x8004E5B0. Loading that savestate restores the old in-RAM dialogue
strings (e.g. obsolete charmap 'ЩФР ПХИПР?') even after the CD-ROM image is patched,
because the game only re-reads Entry 3 from disc when entering town from the world map.

This tool:
1. Reads the patched Entry 3 from localization-output/ru/slayers_royal_ru.bin.
2. Backs up all SLPS-01363_*.sav files to .bak.
3. For each savestate:
   - Locates the zstd emulator state stream (second zstd magic 0x28 0xB5 0x2F 0xFD, or first if single-stream).
   - Decompresses the payload using zstd.
   - Finds Entry 3 in the decompressed RAM image (e.g. at 0x50012 or 0x80012).
   - Replaces the Entry 3 bytes with the patched Entry 3 from the disc image.
   - Recompresses with zstd and writes back the updated .sav file.
4. Verifies that the old mojibake dialogue bytes are completely gone and the new
   authoritative Cyrillic bytes ('Что нужно?') are present.
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patch_repo.localization.disc import USER_DATA_SIZE, read_extent
from tools.patch_town_services import (
    ENTRY3_LBA,
    ENTRY3_SIZE,
    RAM_BASE,
    decode_string,
)
from patch_repo.localization import sr_charmap
from patch_repo.localization.glyphs import BASE_CHAR_TO_GLYPH
from tools.patch_inspection import (
    DEFAULT_ROOM_NAMES,
    HDR_ROOM_NAME_PTR,
    encode_string,
    load_charmap,
    load_room_names,
)

DEFAULT_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SAVESTATES_DIR = Path(os.path.expanduser("~/.local/share/duckstation/savestates"))

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
OLD_GREETING_BYTES = bytes.fromhex("a1d9 2100 3e00 3900")  # "<D9A1>ЩФР..." (mojibake)
NEW_GREETING_BYTES = bytes.fromhex("a1d9 1f00 3c00 3700")  # "<D9A1>Что..." (authoritative)
GREETING_OFFSET_ENTRY3 = 0x030F88
LEGACY_SHOP_HUD_OFFSET = 0x017F48


def find_zstd_magic_offsets(data: bytes) -> list[int]:
    """Find all zstd frame start offsets in binary blob."""
    offsets = []
    idx = 0
    while True:
        pos = data.find(ZSTD_MAGIC, idx)
        if pos == -1:
            break
        offsets.append(pos)
        idx = pos + 1
    return offsets


def decompress_zstd(compressed: bytes) -> bytes:
    """Decompress zstd stream using CLI zstd or zstandard library."""
    res = subprocess.run(
        ["zstd", "-d"],
        input=compressed,
        capture_output=True,
        check=True,
    )
    return res.stdout


def compress_zstd(uncompressed: bytes, level: int = 3) -> bytes:
    """Compress payload using CLI zstd."""
    res = subprocess.run(
        ["zstd", f"-{level}"],
        input=uncompressed,
        capture_output=True,
        check=True,
    )
    return res.stdout


def find_entry3_in_payload(decompressed: bytes, entry3_header: bytes) -> int | None:
    """Find the byte offset where Entry 3 begins in the decompressed RAM payload."""
    # 1. Search by 16-byte Entry 3 header table
    hpos = decompressed.find(entry3_header)
    if hpos != -1:
        return hpos

    # 2. Search by old greeting bytes
    old_pos = decompressed.find(OLD_GREETING_BYTES)
    if old_pos != -1 and old_pos >= GREETING_OFFSET_ENTRY3:
        return old_pos - GREETING_OFFSET_ENTRY3

    # 3. Search by new greeting bytes
    new_pos = decompressed.find(NEW_GREETING_BYTES)
    if new_pos != -1 and new_pos >= GREETING_OFFSET_ENTRY3:
        return new_pos - GREETING_OFFSET_ENTRY3

    return None
def build_room_lookup_to_ru(room_names_doc: dict[str, Any]) -> dict[str, str]:
    """Build mapping from any known room name (JP or EN) to Russian translated name."""
    lookup: dict[str, str] = {}
    for e_key, e_val in room_names_doc.items():
        if isinstance(e_val, dict):
            ru = e_val.get("name_ru") or e_val.get("russian") or e_val.get("ru")
            en = e_val.get("name_en")
            jp = e_val.get("name_jp")
            if ru:
                if en:
                    lookup[en] = ru
                if jp:
                    lookup[jp] = ru
    return lookup


def sync_room_names_in_payload(
    decomp: bytearray,
    room_lookup: dict[str, str],
    cm: dict[str, int],
) -> list[dict[str, Any]]:
    """Identify and update any active room entries in emulator RAM payload to Russian names."""
    updates: list[dict[str, Any]] = []
    pattern = bytes.fromhex("00000000 00000000 0020")
    pos = 0
    jp_cm = sr_charmap.build_charmap()
    glyph_to_char = {v: k for k, v in BASE_CHAR_TO_GLYPH.items()}
    ROOM_RAM_BASE = 0x00200000

    while True:
        p = decomp.find(pattern, pos)
        if p == -1:
            break
        if p + 64 <= len(decomp):
            p3c = struct.unpack_from(">I", decomp, p + HDR_ROOM_NAME_PTR)[0]
            p08 = struct.unpack_from(">I", decomp, p + 0x08)[0]
            if 0x00200000 <= p3c <= 0x00205000 and 0x00200000 <= p08 <= 0x00205000:
                rn_off = p + (p3c - ROOM_RAM_BASE)
                words: list[int] = []
                c = rn_off
                while c + 2 <= len(decomp):
                    w = struct.unpack_from(">H", decomp, c)[0]
                    c += 2
                    if w == 0x00FF:
                        break
                    words.append(w)
                txt_en = "".join(glyph_to_char.get(w, f"[{hex(w)}]") for w in words)
                txt_jp = "".join(jp_cm.get(w, f"[{hex(w)}]") for w in words)
                ru_text = room_lookup.get(txt_en) or room_lookup.get(txt_jp)
                if ru_text:
                    enc = encode_string(ru_text, cm)
                    rel_3c = p3c - ROOM_RAM_BASE
                    rel_08 = p08 - ROOM_RAM_BASE
                    if len(enc) <= (rel_08 - rel_3c):
                        decomp[rn_off : rn_off + len(enc)] = enc
                        decomp[rn_off + len(enc) : p + rel_08] = b"\x00" * (rel_08 - rel_3c - len(enc))
                        loc = "in-place"
                    else:
                        target_off = 0x0F00
                        decomp[p + target_off : p + target_off + len(enc)] = enc
                        struct.pack_into(">I", decomp, p + HDR_ROOM_NAME_PTR, ROOM_RAM_BASE + target_off)
                        loc = f"relocated@{hex(target_off)}"
                    updates.append({
                        "pos": hex(p),
                        "old_en": txt_en,
                        "new_ru": ru_text,
                        "loc": loc,
                    })
        pos = p + 1
    return updates


def sync_single_savestate(
    sav_path: Path,
    entry3_disc: bytes,
    dry_run: bool = False,
    backup: bool = True,
) -> dict[str, Any]:
    """Synchronize a single DuckStation .sav file with patched Entry 3."""
    result: dict[str, Any] = {
        "path": str(sav_path),
        "name": sav_path.name,
        "status": "skipped",
        "entry3_found": False,
        "entry3_offset": None,
        "had_old_greeting": False,
        "has_new_greeting": False,
    }

    data = sav_path.read_bytes()
    magics = find_zstd_magic_offsets(data)
    if not magics:
        result["error"] = "No zstd streams found"
        return result

    # In DuckStation savestates:
    # If 2+ magics: stream 1 is screenshot (277..magics[1]), stream 2 is state (magics[1]..EOF)
    # If 1 magic: stream 1 is the full state with screenshot inside (277..EOF)
    stream_offset = magics[1] if len(magics) >= 2 else magics[0]
    stream_data = data[stream_offset:]

    try:
        decomp = bytearray(decompress_zstd(stream_data))
    except Exception as e:
        result["error"] = f"Decompression failed: {e}"
        return result

    entry3_header = entry3_disc[:16]
    entry3_start = find_entry3_in_payload(decomp, entry3_header)
    
    # Also synchronize room names
    cm = load_charmap()
    rn_doc = load_room_names()
    room_lookup = build_room_lookup_to_ru(rn_doc)
    room_updates = sync_room_names_in_payload(decomp, room_lookup, cm)
    result["room_updates"] = room_updates

    if entry3_start is None and not room_updates:
        result["status"] = "not_loaded"
        result["message"] = "Neither Entry 3 nor active room in RAM"
        return result
    if entry3_start is not None:
        result["entry3_found"] = True
        result["entry3_offset"] = hex(entry3_start)
        greeting_pos = entry3_start + GREETING_OFFSET_ENTRY3

        had_old = decomp[greeting_pos : greeting_pos + len(OLD_GREETING_BYTES)] == OLD_GREETING_BYTES
        result["had_old_greeting"] = had_old

        # Replace Entry 3 in RAM
        decomp[entry3_start : entry3_start + ENTRY3_SIZE] = entry3_disc

        has_new = decomp[greeting_pos : greeting_pos + len(NEW_GREETING_BYTES)] == NEW_GREETING_BYTES
        result["has_new_greeting"] = has_new

        # Check that old mojibake is eliminated
        assert OLD_GREETING_BYTES not in decomp, f"Old greeting still present in {sav_path.name}!"
    else:
        result["entry3_found"] = False
    if not dry_run:
        # Create backup if requested and .bak doesn't exist
        if backup:
            bak_path = sav_path.with_suffix(".sav.bak")
            if not bak_path.is_file():
                shutil.copy2(sav_path, bak_path)
                result["backup_created"] = str(bak_path)

        # Recompress state stream
        recompressed = compress_zstd(bytes(decomp), level=3)
        updated_sav = data[:stream_offset] + recompressed
        sav_path.write_bytes(updated_sav)
        result["status"] = "updated"
        result["new_size"] = len(updated_sav)
    else:
        result["status"] = "dry_run"

    return result


def verify_savestates(
    savestates_dir: Path,
    entry3_disc: bytes,
) -> list[dict[str, Any]]:
    """Verify that all savestates in directory contain correct dialogue bytes and no mojibake."""
    reports = []
    entry3_header = entry3_disc[:16]

    for p in sorted(savestates_dir.glob("SLPS-01363_*.sav")):
        rep: dict[str, Any] = {"name": p.name, "valid": False}
        data = p.read_bytes()
        magics = find_zstd_magic_offsets(data)
        if not magics:
            rep["error"] = "No zstd magic found"
            reports.append(rep)
            continue

        stream_offset = magics[1] if len(magics) >= 2 else magics[0]
        decomp = decompress_zstd(data[stream_offset:])
        entry3_start = find_entry3_in_payload(decomp, entry3_header)

        if entry3_start is not None:
            greeting_pos = entry3_start + GREETING_OFFSET_ENTRY3
            old_present = OLD_GREETING_BYTES in decomp
            new_present = decomp[greeting_pos : greeting_pos + len(NEW_GREETING_BYTES)] == NEW_GREETING_BYTES
            greeting_text = decode_string(decomp[greeting_pos : greeting_pos + 24])

            # Check buy_suggest_weapon (<00BF> at start of line 2)
            ptr_suggest = struct.unpack("<I", decomp[entry3_start + 0x031F24 : entry3_start + 0x031F28])[0]
            rel_suggest = ptr_suggest - RAM_BASE
            suggest_raw = decomp[entry3_start + rel_suggest : entry3_start + rel_suggest + 80]
            suggest_words = [struct.unpack_from("<H", suggest_raw, i)[0] for i in range(0, len(suggest_raw), 2)]
            first_nl = suggest_words.index(0x00FE) if 0x00FE in suggest_words else -1
            has_bf_line2 = (first_nl != -1 and first_nl + 1 < len(suggest_words) and suggest_words[first_nl + 1] == 0x00BF)
            suggest_text = decode_string(suggest_raw)

            # Check Table 0x030A20 items (sample items)
            sample_items = []
            table0_start = entry3_start + 0x030A20
            for idx, exp_name in [(0, "Лина"), (7, "Ф.Атк"), (32, "Меч Света"), (36, "Длинный меч"), (47, "Короткий меч")]:
                p_off = table0_start + idx * 4
                ptr_val = struct.unpack("<I", decomp[p_off : p_off + 4])[0]
                rel_item = ptr_val - RAM_BASE
                it_text = decode_string(decomp[entry3_start + rel_item : entry3_start + rel_item + 48])
                sample_items.append((idx, it_text, it_text == exp_name))

            all_items_ok = all(ok for _, _, ok in sample_items)

            # Check that legacy Japanese HUD is neutralized (jr $ra; nop)
            hud_mips = decomp[entry3_start + LEGACY_SHOP_HUD_OFFSET : entry3_start + LEGACY_SHOP_HUD_OFFSET + 8]
            hud_neutralized = (hud_mips == bytes.fromhex("0800e00300000000"))

            rep["entry3_loaded"] = True
            rep["entry3_offset"] = hex(entry3_start)
            rep["old_mojibake_present"] = old_present
            rep["new_greeting_present"] = new_present
            rep["greeting_text"] = greeting_text
            rep["suggest_text"] = suggest_text
            rep["has_bf_line2"] = has_bf_line2
            rep["sample_items"] = sample_items
            rep["hud_neutralized"] = hud_neutralized
            rep["valid"] = (not old_present) and new_present and has_bf_line2 and all_items_ok and hud_neutralized
        else:
            rep["entry3_loaded"] = False
            rep["valid"] = True  # Not in town, Entry 3 will load cleanly from disc

        reports.append(rep)
    return reports


def sync_all_savestates(
    bin_path: Path | str = DEFAULT_BIN,
    savestates_dir: Path | str = DEFAULT_SAVESTATES_DIR,
    dry_run: bool = False,
    backup: bool = True,
) -> list[dict[str, Any]]:
    """Synchronize all DuckStation savestates with patched Entry 3."""
    bp = Path(bin_path)
    if not bp.is_file():
        raise FileNotFoundError(f"Patched disc image not found: {bp}")

    sd = Path(savestates_dir)
    if not sd.is_dir():
        raise FileNotFoundError(f"Savestates directory not found: {sd}")

    # Read patched Entry 3 directly from disc image
    entry3_disc = read_extent(bp, ENTRY3_LBA, ENTRY3_SIZE)

    sav_files = sorted(sd.glob("SLPS-01363_*.sav"))
    if not sav_files:
        print(f"[*] No SLPS-01363 savestate files found in {sd}")
        return []

    reports = []
    for sav_path in sav_files:
        rep = sync_single_savestate(sav_path, entry3_disc, dry_run=dry_run, backup=backup)
        reports.append(rep)

    return reports


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize DuckStation savestates with patched PROG.UNT Entry 3 (Slayers Royal PS1)"
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_BIN,
        help=f"Patched PS1 disc image (default: {DEFAULT_BIN})",
    )
    parser.add_argument(
        "--savestates-dir",
        type=Path,
        default=DEFAULT_SAVESTATES_DIR,
        help=f"DuckStation savestates directory (default: {DEFAULT_SAVESTATES_DIR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate synchronization without modifying savestates",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating .bak backup copies before patching",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify savestates without modifying",
    )

    args = parser.parse_args()

    entry3_disc = read_extent(args.bin, ENTRY3_LBA, ENTRY3_SIZE)

    if args.verify:
        print(f"[*] Verifying savestates in {args.savestates_dir}...")
        v_reps = verify_savestates(args.savestates_dir, entry3_disc)
        all_ok = True
        for r in v_reps:
            status_str = "[OK]" if r.get("valid") else "[FAIL]"
            if r.get("entry3_loaded"):
                print(f"  {status_str} {r['name']}: Entry 3 @ {r['entry3_offset']}, greeting: {r.get('greeting_text')!r}")
            else:
                print(f"  {status_str} {r['name']}: Entry 3 not loaded (saved outside town)")
            if not r.get("valid"):
                all_ok = False

        if all_ok:
            print("[✓] All savestates VERIFIED! Zero mojibake detected.")
            return 0
        else:
            print("[X] Verification failed: some savestates still contain old mojibake.")
            return 1

    mode_str = "DRY-RUN simulation" if args.dry_run else "updating savestates"
    print(f"[*] Synchronizing DuckStation savestates ({mode_str}) in {args.savestates_dir}...")
    reports = sync_all_savestates(
        bin_path=args.bin,
        savestates_dir=args.savestates_dir,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    updated_count = 0
    for r in reports:
        if r.get("status") in ("updated", "dry_run"):
            had_str = " (had old mojibake)" if r.get("had_old_greeting") else ""
            print(f"  [✓] {r['name']}: Entry 3 patched at {r['entry3_offset']}{had_str}")
            updated_count += 1
        elif r.get("status") == "entry3_not_loaded":
            print(f"  [-] {r['name']}: {r['message']}")
        else:
            print(f"  [!] {r['name']}: {r.get('error', r.get('status'))}")

    print(f"\n[✓] Synchronization finished! Patched {updated_count} savestate(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
