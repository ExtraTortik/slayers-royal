#!/usr/bin/env python3
"""Combat overlay preparation for Slayers Royal (PS1): PROG.UNT entries 0x142 and 0x007.

Responsibilities (kept deliberately small; the text of entry 0x007 is owned by
``tools/patch_combat_dialogues.py`` which runs right after this tool):

1. Restore the pristine battle font entry 0x142 from the English base image
   (or keep the current one) so that the Cyrillic glyphs are always drawn on
   top of a clean atlas.
2. Write the *in-place* auxiliary strings of entry 0x007 listed under
   ``extra_combat_strings`` in ``translations/combat_ru.json`` (memory-card and
   configuration screen messages).  They are encoded with the battle font
   charmap (``tools/combat_dialogue_charmap.py``) because the whole overlay
   renders with font 0x142.
3. Rewrite the touched sectors with Mode 2 Form 1 EDC/ECC repair.

Ground truth used here (verified against the original disc):

* entry 0x007 is loaded contiguously at RAM ``0x8004E5B0``;
* the UI label pointer table lives at ``0x05F470`` (37 pointers), the dialogue
  cue table at ``0x06286C`` (105 pointers) and the spell table at ``0x06F4D8``;
  all of them resolve with that base;
* the 23 words at ``0x05F1FC`` are **not** a string table (they address 16-byte
  descriptors at ``0x05EDD8``) and must never be rewritten.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import (
    read_extent,
    replace_extent_in_place,
    CdChecksums,
)
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
    patch_unt_entry,
)
from tools.patch_combat_font import COMBAT_FONT_ENTRY
from tools.combat_text import RAM_BASE, PROG_ENTRY_COMBAT, build_combat_charmap
from tools.combat_dialogue_charmap import (
    encode_combat_dialogue_string,
    OPCODE_BLOCK_END,
)

DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_CATALOG = REPO_ROOT / "translations" / "combat_ru.json"
DEFAULT_SOURCE_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"

# Layout of entry 0x007 (offsets inside the entry).
OFFSET_DESCRIPTOR_TABLE = 0x05F1FC      # 23 pointers -> 16-byte descriptors at 0x05EDD8 (do not touch)
OFFSET_DESCRIPTOR_TABLE_END = 0x05F258
OFFSET_UI_STRINGS = 0x05F278            # 37 UI labels/prompts, packed by patch_combat_dialogues
OFFSET_UI_STRINGS_END = 0x05F470
OFFSET_UI_POINTERS = 0x05F470           # 37 pointers, base RAM_BASE
OFFSET_UI_POINTERS_END = 0x05F504
OFFSET_DIALOGUE_STREAM = 0x05F810       # 114 in-place blocks, see combat_dialogues_ru.json
OFFSET_CUE_TABLE = 0x06286C             # 105 pointers, base RAM_BASE, never rewritten
OFFSET_CUE_TABLE_END = 0x062A10
OFFSET_COMBAT_INIT_EXIT = 0x02B78C      # 'jr $ra; nop' that must stay intact
SPEAKER_OPCODE_PREFIXES = (0x91, 0xD1, 0xD2)

# Original bytes of the descriptor pointer table (identical in the Japanese and
# English releases).  Used by --verify to prove the table was never rewritten.
DESCRIPTOR_TABLE_ORIGINAL = bytes.fromhex(
    "88d30a8098d30a80a8d30a80b8d30a80c8d30a80d8d30a80e8d30a80f8d30a80"
    "08d40a8018d40a8028d40a8038d40a8048d40a8058d40a8068d40a8078d40a80"
    "88d40a8098d40a80a8d40a80b8d40a80c8d40a8010d50a804cd50a80"
)


# ---------------------------------------------------------------------------
# Original (Japanese == English release) pointer tables of entry 0x007, kept
# for analysis tools.  Both resolve with RAM_BASE = 0x8004E5B0.
# ---------------------------------------------------------------------------
# UI label pointer table 0x05F470..0x05F504 (37 pointers) as shipped.
TABLE2_CANONICAL_BYTES = bytes.fromhex(
    "28d80a8034d80a8040d80a804cd80a8058d80a8064d80a8074d80a807cd80a80"
    "88d80a8090d80a809cd80a80a4d80a80b0d80a80c0d80a80c8d80a80d0d80a80"
    "dcd80a80e8d80a80f0d80a80fcd80a8004d90a800cd90a8018d90a8024d90a80"
    "30d90a803cd90a8048d90a8060d90a8078d90a808cd90a80a0d90a80b8d90a80"
    "d0d90a80e4d90a80f8d90a8010da0a8018da0a80"
)
assert len(TABLE2_CANONICAL_BYTES) == 148

# Entry offsets targeted by the 105 dialogue cue pointers at 0x06286C..0x062A10.
TABLE3_CUE_OFFSETS: tuple[int, ...] = (
    0x05F810, 0x05F8C0, 0x05F920, 0x05F984, 0x05F9D4,
    0x05FACC, 0x05FB50, 0x05FC18, 0x05FC3C, 0x05FC70,
    0x05FCA8, 0x05FCE4, 0x05FD44, 0x05FDBC, 0x05FF0C,
    0x060070, 0x0600EC, 0x060170, 0x06023C, 0x06027C,
    0x0602DC, 0x060310, 0x060328, 0x06034C, 0x060380,
    0x0604FC, 0x060574, 0x060590, 0x0605DC, 0x060654,
    0x0606A8, 0x060768, 0x060818, 0x0608D4, 0x060908,
    0x060A0C, 0x060AC0, 0x060BB8, 0x060BF0, 0x060C34,
    0x060CA4, 0x060D1C, 0x060DC4, 0x060E58, 0x060ED4,
    0x060F50, 0x060FCC, 0x061048, 0x0610F0, 0x061148,
    0x061164, 0x061180, 0x06119C, 0x061240, 0x0612B8,
    0x061324, 0x061340, 0x06139C, 0x061400, 0x06147C,
    0x0626E4, 0x0614B4, 0x0614FC, 0x061520, 0x06162C,
    0x0616BC, 0x0616E8, 0x06170C, 0x061738, 0x0617B8,
    0x0617FC, 0x061850, 0x06189C, 0x0618C0, 0x0618E0,
    0x061900, 0x061968, 0x061998, 0x0619E4, 0x061A20,
    0x061AA0, 0x061AC4, 0x061AEC, 0x061AFC, 0x061B5C,
    0x061BFC, 0x061C28, 0x061C68, 0x061CC0, 0x061D14,
    0x061D68, 0x061DBC, 0x061DE4, 0x061E70, 0x061F00,
    0x061F50, 0x061FB4, 0x062014, 0x062078, 0x0620D4,
    0x062124, 0x0621D4, 0x06226C, 0x062308, 0x0623B4,
)
assert len(TABLE3_CUE_OFFSETS) == 105


@dataclass
class CombatPatchResult:
    """Statistics for the applied combat preparation."""

    disc_path: Path
    font_decompressed_bytes: int
    font_compressed_bytes: int
    font_allocated_bytes: int
    extra_strings_count: int
    sectors_patched: int


def encode_text(text: str, charmap: Mapping[str, int] | None = None) -> bytes:
    """Encode ``text`` for the battle overlay (font 0x142 charmap) with the block terminator."""
    cm = charmap if charmap is not None else build_combat_charmap()
    return encode_combat_dialogue_string(text, cm) + struct.pack("<H", OPCODE_BLOCK_END)


def _prog_archive(disc_path: Path) -> tuple[int, bytearray]:
    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)
    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO directory of {disc_path}")
    prog_lba, prog_size = root_dir["PROG.UNT"]
    return prog_lba, bytearray(read_extent(disc_path, prog_lba, prog_size))


def get_en_combat_font_bytes(en_disc_path: Path | None = None) -> bytes:
    """Extract pristine (compressed) entry 0x142 from the English base disc."""
    path = en_disc_path if en_disc_path is not None else DEFAULT_EN_BIN
    if not path.is_file():
        raise FileNotFoundError(f"English base disc not found: {path}")
    _, prog_archive = _prog_archive(path)
    e142 = read_unt_index(prog_archive)[COMBAT_FONT_ENTRY]
    return bytes(prog_archive[e142.offset : e142.offset + e142.size])


def get_en_combat_overlay_bytes(en_disc_path: Path | None = None) -> bytes:
    """Extract pristine entry 0x007 from the English base disc."""
    path = en_disc_path if en_disc_path is not None else DEFAULT_EN_BIN
    if not path.is_file():
        raise FileNotFoundError(f"English base disc not found: {path}")
    _, prog_archive = _prog_archive(path)
    e007 = read_unt_index(prog_archive)[PROG_ENTRY_COMBAT]
    return bytes(prog_archive[e007.offset : e007.offset + e007.size])


def restore_combat_en_disc_image(disc_path: Path, source_en_bin: Path | None = None) -> tuple[int, int]:
    """Restore clean English combat mode (entries 0x007 and 0x142) from the English base."""
    en_bin = source_en_bin if source_en_bin is not None else DEFAULT_EN_BIN
    font_bytes = get_en_combat_font_bytes(en_bin)
    overlay_bytes = get_en_combat_overlay_bytes(en_bin)
    prog_lba, prog_archive = _prog_archive(disc_path)
    entries = read_unt_index(prog_archive)
    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]
    replace_extent_in_place(disc_path, prog_lba + e142.start_sector, font_bytes)
    replace_extent_in_place(disc_path, prog_lba + e007.start_sector, overlay_bytes)
    return e142.sector_count + e007.sector_count, len(font_bytes) + len(overlay_bytes)


def patch_combat_font_entry(
    prog_archive: bytearray,
    source_bin: Path | None = None,
    font_path: Path | None = None,
) -> tuple[int, int, int]:
    """Restore pristine combat font entry 0x142 (from the English base when available).

    Returns (decompressed_size, compressed_size, allocated_size).
    """
    en_bin = DEFAULT_EN_BIN
    if source_bin is not None and "sr_patched" in source_bin.name:
        en_bin = source_bin
    elif not en_bin.is_file() and source_bin is not None:
        en_bin = source_bin

    if en_bin.is_file():
        font_comp = get_en_combat_font_bytes(en_bin)
    else:
        entries = read_unt_index(prog_archive)
        if COMBAT_FONT_ENTRY >= len(entries):
            raise IndexError(f"PROG.UNT does not contain font entry 0x{COMBAT_FONT_ENTRY:03X}")
        e142 = entries[COMBAT_FONT_ENTRY]
        font_comp = bytes(prog_archive[e142.offset : e142.offset + e142.size])
    decomp_res = unt_lz.decompress(font_comp)
    decomp_bytes = decomp_res[0] if isinstance(decomp_res, tuple) else decomp_res
    _, allocated, _ = patch_unt_entry(prog_archive, COMBAT_FONT_ENTRY, font_comp)
    return len(decomp_bytes), len(font_comp), allocated


def patch_extra_combat_strings(
    e007_data: bytearray,
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> int:
    """Write ``extra_combat_strings`` in place. Raises if a string exceeds its slot."""
    cm = charmap if charmap is not None else build_combat_charmap()
    count = 0
    for es in catalog.get("extra_combat_strings", []):
        off = int(es["offset"], 16)
        enc = encode_text(es["text_ru"], cm)
        max_b = es.get("max_bytes")
        if max_b is not None and len(enc) > max_b:
            raise ValueError(
                f"extra combat string {es['text_ru']!r} at 0x{off:06X} needs {len(enc)} bytes "
                f"but the slot holds {max_b}; shorten it (never truncate: a cut word or a "
                "missing 0x00FF terminator hangs the renderer)"
            )
        e007_data[off : off + len(enc)] = enc
        if max_b is not None:
            e007_data[off + len(enc) : off + max_b] = b"\x00" * (max_b - len(enc))
        count += 1
    return count


def patch_combat_overlay_entry(
    prog_archive: bytearray,
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> int:
    """Apply the in-place auxiliary strings to entry 0x007 inside ``prog_archive``.

    Returns the number of strings written.  Pointer tables are never touched.
    """
    entries = read_unt_index(prog_archive)
    if PROG_ENTRY_COMBAT >= len(entries):
        raise IndexError(f"PROG.UNT does not contain entry 0x{PROG_ENTRY_COMBAT:03X}")
    e007 = entries[PROG_ENTRY_COMBAT]
    e007_data = bytearray(prog_archive[e007.offset : e007.offset + e007.size])
    if struct.unpack_from("<II", e007_data, OFFSET_COMBAT_INIT_EXIT) != (0x03E00008, 0x00000000):
        raise ValueError(f"entry 0x007: 'jr $ra; nop' at 0x{OFFSET_COMBAT_INIT_EXIT:06X} is not intact")
    count = patch_extra_combat_strings(e007_data, catalog, charmap)
    prog_archive[e007.offset : e007.offset + e007.size] = e007_data
    return count


def patch_combat_disc_image(
    disc_path: Path,
    catalog_path: Path | None = None,
    source_bin: Path | None = None,
    font_path: Path | None = None,
) -> CombatPatchResult:
    """Restore font 0x142 and write the auxiliary strings of 0x007 with EDC/ECC repair."""
    if catalog_path is None:
        catalog_path = DEFAULT_CATALOG
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Combat catalog not found: {catalog_path}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    charmap = build_combat_charmap()

    prog_lba, prog_archive = _prog_archive(disc_path)
    entries = read_unt_index(prog_archive)
    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]

    font_decomp, font_comp, font_alloc = patch_combat_font_entry(prog_archive, source_bin=source_bin, font_path=font_path)
    extra_count = patch_combat_overlay_entry(prog_archive, catalog=catalog, charmap=charmap)

    replace_extent_in_place(disc_path, prog_lba + e142.start_sector, bytes(prog_archive[e142.offset : e142.offset + e142.size]))
    replace_extent_in_place(disc_path, prog_lba + e007.start_sector, bytes(prog_archive[e007.offset : e007.offset + e007.size]))

    return CombatPatchResult(
        disc_path=disc_path,
        font_decompressed_bytes=font_decomp,
        font_compressed_bytes=font_comp,
        font_allocated_bytes=font_alloc,
        extra_strings_count=extra_count,
        sectors_patched=e142.sector_count + e007.sector_count,
    )


def check_pointer_tables(e007_data: bytes) -> list[str]:
    """Structural checks shared by --verify: every pointer of 0x007 must be sane."""
    problems: list[str] = []
    if e007_data[OFFSET_DESCRIPTOR_TABLE:OFFSET_DESCRIPTOR_TABLE_END] != DESCRIPTOR_TABLE_ORIGINAL:
        problems.append("descriptor pointer table 0x05F1FC..0x05F258 was rewritten (it is not a string table)")
    for k in range(37):
        target = struct.unpack_from("<I", e007_data, OFFSET_UI_POINTERS + 4 * k)[0] - RAM_BASE
        if not (OFFSET_UI_STRINGS <= target < OFFSET_UI_STRINGS_END or 0x082400 <= target < 0x083000):
            problems.append(f"UI pointer {k} -> 0x{target:06X} is outside the UI string region")
            continue
        if target > OFFSET_UI_STRINGS and struct.unpack_from("<H", e007_data, target - 2)[0] not in (OPCODE_BLOCK_END, 0x0000):
            problems.append(f"UI pointer {k} -> 0x{target:06X} lands in the middle of a string")
    for k in range(0, OFFSET_CUE_TABLE_END - OFFSET_CUE_TABLE, 4):
        target = struct.unpack_from("<I", e007_data, OFFSET_CUE_TABLE + k)[0] - RAM_BASE
        if not (0 <= target < len(e007_data) - 2):
            problems.append(f"cue pointer {k // 4} -> 0x{target:06X} is out of range")
            continue
        opcode = struct.unpack_from("<H", e007_data, target)[0]
        if (opcode >> 8) not in SPEAKER_OPCODE_PREFIXES:
            problems.append(f"cue pointer {k // 4} -> 0x{target:06X} does not start with a speaker opcode (0x{opcode:04X})")
    if struct.unpack_from("<II", e007_data, OFFSET_COMBAT_INIT_EXIT) != (0x03E00008, 0x00000000):
        problems.append("'jr $ra; nop' at 0x02B78C is not intact")
    return problems


def verify_combat_patch(
    disc_path: Path,
    catalog_path: Path | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """Verify entries 0x142 / 0x007: pointer sanity, auxiliary strings and EDC/ECC."""
    prog_lba, prog_archive = _prog_archive(disc_path)
    entries = read_unt_index(prog_archive)
    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]
    e007_data = bytes(prog_archive[e007.offset : e007.offset + e007.size])

    problems = check_pointer_tables(e007_data)

    cat_path = catalog_path if catalog_path is not None else DEFAULT_CATALOG
    if cat_path.is_file() and mode in ("auto", "ru"):
        catalog = json.loads(cat_path.read_text(encoding="utf-8"))
        cm = build_combat_charmap()
        for es in catalog.get("extra_combat_strings", []):
            off = int(es["offset"], 16)
            enc = encode_text(es["text_ru"], cm)
            if e007_data[off : off + len(enc)] != enc:
                if mode == "ru":
                    problems.append(f"extra string {es['text_ru']!r} not found at 0x{off:06X}")
                break

    font_comp = bytes(prog_archive[e142.offset : e142.offset + e142.size])
    decomp_res = unt_lz.decompress(font_comp)
    decomp = decomp_res[0] if isinstance(decomp_res, tuple) else decomp_res

    checksums = CdChecksums()
    bad_sectors = 0
    with disc_path.open("rb") as fh:
        for lba in list(range(prog_lba + e142.start_sector, prog_lba + e142.start_sector + e142.sector_count)) + list(
            range(prog_lba + e007.start_sector, prog_lba + e007.start_sector + e007.sector_count)
        ):
            fh.seek(lba * 2352)
            sec = fh.read(2352)
            if sec[0x818:0x81C] != checksums.compute_edc(sec[0x10:0x818]):
                bad_sectors += 1
    if bad_sectors:
        problems.append(f"{bad_sectors} sectors have a stale EDC")

    result = {
        "disc": str(disc_path),
        "font_decompressed_bytes": len(decomp),
        "font_compressed_bytes": len(font_comp),
        "problems": problems,
    }
    if problems:
        raise AssertionError("combat verification failed:\n  " + "\n  ".join(problems))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare combat font 0x142 and auxiliary strings of 0x007.")
    parser.add_argument("--bin", type=Path, default=DEFAULT_TARGET_BIN if DEFAULT_TARGET_BIN.is_file() else None, help="PS1 CD-ROM BIN image to patch")
    parser.add_argument("--source-bin", type=Path, default=DEFAULT_EN_BIN if DEFAULT_EN_BIN.is_file() else DEFAULT_SOURCE_BIN, help="English base disc for pristine combat assets")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Path to translations/combat_ru.json")
    parser.add_argument("--font", type=Path, default=None, help="unused, kept for CLI compatibility")
    parser.add_argument("--verify", action="store_true", help="Verify pointer tables, strings and EDC without modifying")
    parser.add_argument("--mode", choices=["auto", "en", "ru"], default="auto", help="Verification target mode")
    parser.add_argument("--restore-en", action="store_true", help="Restore pristine English combat mode from the English release")
    args = parser.parse_args()

    target_bin = args.bin
    if target_bin is None:
        print("Error: Target BIN image not specified and default not found.", file=sys.stderr)
        return 1

    if args.restore_en:
        print(f"Restoring clean English combat mode to {target_bin}...")
        sectors, nbytes = restore_combat_en_disc_image(target_bin, args.source_bin)
        print(f"[✓] Restored {sectors} sectors ({nbytes} bytes).")
        return 0

    if args.verify:
        try:
            result = verify_combat_patch(target_bin, args.catalog, args.mode)
        except AssertionError as exc:
            print(f"[✗] {exc}", file=sys.stderr)
            return 1
        print(f"[✓] Combat verification passed: font {result['font_decompressed_bytes']} bytes decompressed, pointer tables sane, EDC valid.")
        return 0

    print(f"Preparing combat entries in {target_bin}...")
    result = patch_combat_disc_image(target_bin, args.catalog, args.source_bin, args.font)
    print(f"    Font 0x142:            {result.font_compressed_bytes:,} / {result.font_allocated_bytes:,} bytes (decompressed {result.font_decompressed_bytes:,})")
    print(f"    Extra strings:         {result.extra_strings_count} written in place")
    print(f"    Sectors Replaced:      {result.sectors_patched} Mode 2 Form 1 sectors with EDC/ECC repair")
    print("    UI labels, dialogue cues and pointer tables are handled by patch_combat_dialogues.py")
    verify_combat_patch(target_bin, args.catalog, "ru")
    print("[✓] Verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
