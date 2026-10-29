#!/usr/bin/env python3
"""Spell and combat options patcher for Slayers Royal (PS1).

Replaces all 119 spells and combat menu options in PROG.UNT Entries 325..443
(1 sector each, 2048 bytes) in-place with Russian translations from
translations/spells_ru.json, and recalculates Mode 2 Form 1 EDC/ECC.

Format per entry:
  encode(title_ru) + [0x00A3, 0x00A3] ("") + pages encoded with
  0x00FE (newline), 0x00FD (page break), terminated with 0x00FF and
  padded with 0x00 to 2048 bytes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
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
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
)
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
)
from tools.combat_dialogue_charmap import (
    build_combat_dialogue_charmap,
    build_reverse_charmap,
    encode_combat_dialogue_string,
    decode_combat_dialogue_string,
    COMBAT_CHARMAP,
    REVERSE_COMBAT_CHARMAP,
)

DEFAULT_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
if not DEFAULT_BIN.is_file():
    DEFAULT_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
if not DEFAULT_BIN.is_file():
    DEFAULT_BIN = REPO_ROOT / "downloads" / "sr.bin"

DEFAULT_CATALOG = REPO_ROOT / "translations" / "spells_ru.json"

SPELLS_FIRST_ENTRY = 325
SPELLS_LAST_ENTRY = 443
SPELLS_COUNT = 119
ENTRY_SECTOR_SIZE = 2048

DELIMITER_QUOTE = 0x00A3
DELIMITER_COLON = 0x00BC
OPCODE_NEWLINE = 0x00FE
OPCODE_PAGE_BREAK = 0x00FD
OPCODE_TERMINATOR = 0x00FF

ENTRY_COMBAT_DATA = 0x007
ENTRY_007_SECTORS = 745
ENTRY_007_SPELL_MENU_START = 0x06F2CC
ENTRY_007_SPELL_MENU_END = 0x06F4D8
ENTRY_007_SPELL_MENU_SIZE = 524

# Entry 0x007 spell menu diagnostics (the Russian menu is injected by
# tools/patch_spell_menu_ru.py after this tool has written the 119 help entries).
ENTRY_007_POINTER_TABLE_START = 0x06F4D8
ENTRY_007_POINTER_TABLE_SIZE = 236  # 59 pointers: NULL + 57 names + end
ENTRY_COMBAT_FONT = 0x142
# Invariant offsets in Entry 0x007
OFFSET_MIPS_INIT_EXIT = 0x02B78C
OFFSET_SYSTEM_BUTTONS_START = 0x05F278
OFFSET_SYSTEM_BUTTONS_END = 0x05F470
OFFSET_TABLE2_START = 0x05F470
OFFSET_DIALOGUES_START = 0x05F810
OFFSET_DIALOGUES_END = 0x06286A
OFFSET_TABLE3_START = 0x06286C

# 57 Spell Catalog sections in Entry 0x007
SECTION_SPELL_IDS = [
    # Section 1 (Lina): 104 bytes, offset 0x06F2CC..0x06F334
    [347, 354, 338, 372, 371, 373, 332, 333, 364],
    # Section 2 (Naga): 212 bytes, offset 0x06F334..0x06F408
    [331, 334, 335, 329, 330, 336, 339, 340, 341, 344, 346, 349, 350, 355, 356, 357, 358, 360, 361, 365, 379],
    # Section 3 (Other): 164 bytes, offset 0x06F408..0x06F4AC
    [326, 327, 328, 337, 342, 343, 345, 348, 351, 352, 353, 359, 362, 363, 366, 367, 368, 369, 370, 378, 380, 381],
    # Section 4 (Remaining): 44 bytes, offset 0x06F4AC..0x06F4D8
    [374, 375, 376, 377, 382],
]
SECTION_BUDGETS = [104, 212, 164, 44]
SECTION_OFFSETS = [0x06F2CC, 0x06F334, 0x06F408, 0x06F4AC]




def get_prog_unt_entry_extent(bin_path: Path, entry_index: int) -> tuple[int, int, int]:
    """Locate PROG.UNT entry on disc and return (prog_lba, start_sector, sector_count)."""
    pvd = read_sector(bin_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(bin_path, root_lba, root_size)
    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO root directory of {bin_path}")
    prog_lba, _ = root_dir["PROG.UNT"]
    sec0 = read_extent(bin_path, prog_lba, 2048)
    entries = read_unt_index(sec0)
    e = entries[entry_index]
    return prog_lba, e.start_sector, e.sector_count


def encode_spell(
    entry: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> bytes:
    """Encode a single spell entry into a 2048-byte sector payload.

    Format:
      encode(title_ru) + [0x00BC, 0x00FE] (':\n') + pages encoded with
      0x00FE (newline), 0x00FD (page break), terminated with 0x00FF
      and padded with 0x00 to 2048 bytes.
    """
    cm = charmap if charmap is not None else COMBAT_CHARMAP
    title = entry.get("title_ru") or entry.get("name_ru") or entry.get("title_en") or ""
    pages = entry.get("pages_ru") or []

    words: list[int] = []

    # 1. Encode title
    title_bytes = encode_combat_dialogue_string(title, cm)
    words.extend(struct.unpack(f"<{len(title_bytes)//2}H", title_bytes))

    # 2. Delimiter ':' (0x00BC) + newline (0x00FE)
    words.extend([DELIMITER_COLON, OPCODE_NEWLINE])

    # 3. Encode pages joined with 0x00FD and newlines with 0x00FE
    for p_idx, page in enumerate(pages):
        if p_idx > 0:
            words.append(OPCODE_PAGE_BREAK)
        page_bytes = encode_combat_dialogue_string(page, cm)
        words.extend(struct.unpack(f"<{len(page_bytes)//2}H", page_bytes))

    # 4. Terminator 0x00FF
    words.append(OPCODE_TERMINATOR)

    raw_data = struct.pack(f"<{len(words)}H", *words)
    if len(raw_data) > ENTRY_SECTOR_SIZE:
        raise ValueError(
            f"Spell entry {entry.get('entry_index', '?')} exceeds sector budget: "
            f"{len(raw_data)} bytes > {ENTRY_SECTOR_SIZE} bytes"
        )

    return raw_data.ljust(ENTRY_SECTOR_SIZE, b"\x00")


def decode_spell(
    data: bytes,
    reverse_charmap: Mapping[int, str] | None = None,
) -> tuple[str, list[str]]:
    """Decode a 2048-byte sector payload back to (title_ru, pages_ru)."""
    rev = reverse_charmap if reverse_charmap is not None else REVERSE_COMBAT_CHARMAP
    words = list(struct.unpack(f"<{len(data)//2}H", data))

    if OPCODE_TERMINATOR in words:
        words = words[:words.index(OPCODE_TERMINATOR)]

    # 1. New delimiter: [0x00BC, OPCODE_NEWLINE] (colon + newline)
    delims_colon = [
        i for i in range(len(words) - 1)
        if words[i] == DELIMITER_COLON and words[i + 1] == OPCODE_NEWLINE
    ]

    # 2. Legacy delimiter: [DELIMITER_QUOTE, DELIMITER_QUOTE]
    delims_quote = [
        i for i in range(len(words) - 1)
        if words[i] == DELIMITER_QUOTE and words[i + 1] == DELIMITER_QUOTE
    ]

    first_delim = None
    delim_len = 2

    if delims_colon and delims_quote:
        if delims_colon[0] < delims_quote[0]:
            first_delim = delims_colon[0]
        else:
            first_delim = delims_quote[0]
    elif delims_colon:
        first_delim = delims_colon[0]
    elif delims_quote:
        first_delim = delims_quote[0]
    elif OPCODE_NEWLINE in words:
        # 3. First newline OPCODE_NEWLINE as title separator if preceded by 0x00BC
        first_nl = words.index(OPCODE_NEWLINE)
        prefix = words[:first_nl]
        if DELIMITER_COLON in prefix:
            colon_pos = len(prefix) - 1 - prefix[::-1].index(DELIMITER_COLON)
            title_words = words[:colon_pos]
            body_words = words[first_nl + 1:]
        else:
            title_words = words
            body_words = []
    else:
        title_words = words
        body_words = []

    if first_delim is not None:
        title_words = words[:first_delim]
        body_words = words[first_delim + delim_len:]

    # Strip trailing colon from title if present
    while title_words and title_words[-1] == DELIMITER_COLON:
        title_words.pop()
    def decode_word_list(wlist: list[int]) -> str:
        txt_bytes = struct.pack(f"<{len(wlist)}H", *wlist)
        return decode_combat_dialogue_string(txt_bytes, rev)

    title = decode_word_list(title_words).rstrip(":")
    body = decode_word_list(body_words)
    pages = [p for p in body.split("\f")] if body else []

    return title, pages


def get_prog_unt_spells_extent(bin_path: Path) -> tuple[int, int, list[int]]:
    """Locate PROG.UNT and return (prog_lba, first_sector_offset, sector_offsets)."""
    pvd = read_sector(bin_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(bin_path, root_lba, root_size)
    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO root directory of {bin_path}")

    prog_lba, _ = root_dir["PROG.UNT"]
    sec0 = read_extent(bin_path, prog_lba, 2048)
    entries = read_unt_index(sec0)

    if len(entries) <= SPELLS_LAST_ENTRY:
        raise ValueError(f"PROG.UNT index has only {len(entries)} entries; need at least {SPELLS_LAST_ENTRY + 1}")

    sector_offsets: list[int] = []
    for idx in range(SPELLS_FIRST_ENTRY, SPELLS_LAST_ENTRY + 1):
        e = entries[idx]
        if e.sector_count != 1 or e.size != ENTRY_SECTOR_SIZE:
            raise ValueError(f"Spell entry {idx} sector size/count mismatch: size={e.size}, count={e.sector_count}")
        sector_offsets.append(e.start_sector)

    return prog_lba, sector_offsets[0], sector_offsets


def verify_spells_on_disc(
    bin_path: Path,
    catalog_path: Path | None = None,
) -> dict[str, Any]:
    """Verify all 119 spell entries and Entry 0x007 in-battle spell menu on disc."""
    cat_path = catalog_path or DEFAULT_CATALOG
    if not cat_path.is_file():
        raise FileNotFoundError(f"Translations catalog not found at {cat_path}")

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    entries_map = {item["entry_index"]: item for item in catalog}

    checksums = CdChecksums()
    rev = build_reverse_charmap()

    results: dict[str, Any] = {
        "entries_total": SPELLS_COUNT,
        "edc_ecc_valid": 0,
        "content_valid": 0,
        "entry_007_edc_ecc_valid": 0,
        "errors": [],
    }

    # 1. Verify Entries 325..443 (119 sectors)
    prog_lba, _, sector_offsets = get_prog_unt_spells_extent(bin_path)
    with bin_path.open("rb") as f:
        for idx in range(SPELLS_FIRST_ENTRY, SPELLS_LAST_ENTRY + 1):
            offset_idx = idx - SPELLS_FIRST_ENTRY
            sector_lba = prog_lba + sector_offsets[offset_idx]

            f.seek(sector_lba * RAW_SECTOR_SIZE)
            raw_sector = f.read(RAW_SECTOR_SIZE)
            if len(raw_sector) != RAW_SECTOR_SIZE:
                results["errors"].append(f"Entry {idx}: Incomplete sector at LBA {sector_lba}")
                continue

            # Check Mode 2 Form 1 EDC/ECC
            edc_expected = checksums.compute_edc(raw_sector[0x10:0x818])
            edc_actual = raw_sector[0x818:0x81C]
            ecc_p_expected = checksums.compute_ecc(raw_sector[0x10:], 86, 24, 2, 86)
            ecc_p_actual = raw_sector[0x81C:0x8C8]
            ecc_q_expected = checksums.compute_ecc(raw_sector[0x10:], 52, 43, 86, 88)
            ecc_q_actual = raw_sector[0x8C8:0x930]

            if (edc_expected != edc_actual or
                ecc_p_expected != ecc_p_actual or
                ecc_q_expected != ecc_q_actual):
                results["errors"].append(f"Entry {idx}: EDC/ECC checksum mismatch at LBA {sector_lba}")
            else:
                results["edc_ecc_valid"] += 1

            # Check content
            user_data = raw_sector[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE]
            dec_title, dec_pages = decode_spell(user_data, rev)

            exp_entry = entries_map.get(idx, {})
            exp_title = exp_entry.get("title_ru") or exp_entry.get("name_ru") or exp_entry.get("title_en") or ""
            exp_pages = exp_entry.get("pages_ru") or []

            if dec_title != exp_title:
                results["errors"].append(f"Entry {idx}: Title mismatch: {dec_title!r} != {exp_title!r}")
            elif dec_pages != exp_pages:
                results["errors"].append(f"Entry {idx}: Pages mismatch: {dec_pages!r} != {exp_pages!r}")
            else:
                results["content_valid"] += 1

    # 2. Verify Entry 0x007 (745 sectors)
    prog_lba, e7_start, e7_count = get_prog_unt_entry_extent(bin_path, ENTRY_COMBAT_DATA)
    e7_bytes = read_extent(bin_path, prog_lba + e7_start, e7_count * 2048)

    with bin_path.open("rb") as f:
        for sec_i in range(e7_count):
            lba = prog_lba + e7_start + sec_i
            f.seek(lba * RAW_SECTOR_SIZE)
            raw_sec = f.read(RAW_SECTOR_SIZE)
            if len(raw_sec) != RAW_SECTOR_SIZE:
                results["errors"].append(f"Entry 0x007: Incomplete sector at LBA {lba}")
                continue
            edc_exp = checksums.compute_edc(raw_sec[0x10:0x818])
            ecc_p_exp = checksums.compute_ecc(raw_sec[0x10:], 86, 24, 2, 86)
            ecc_q_exp = checksums.compute_ecc(raw_sec[0x10:], 52, 43, 86, 88)
            if (edc_exp != raw_sec[0x818:0x81C] or
                ecc_p_exp != raw_sec[0x81C:0x8C8] or
                ecc_q_exp != raw_sec[0x8C8:0x930]):
                results["errors"].append(f"Entry 0x007: EDC/ECC failure at LBA {lba}")
            else:
                results["entry_007_edc_ecc_valid"] += 1

    # Verify MIPS invariant in Entry 0x007
    mips_code = struct.unpack_from("<II", e7_bytes, OFFSET_MIPS_INIT_EXIT)
    if mips_code != (0x03E00008, 0x00000000):
        results["errors"].append(f"Entry 0x007: MIPS exit instruction corrupted: {mips_code}")

    return results


def patch_spells(
    bin_path: Path,
    catalog_path: Path | None = None,
    output_bin: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Encode and patch all 119 spell help entries into the target disc image."""
    cat_path = catalog_path or DEFAULT_CATALOG
    if not cat_path.is_file():
        raise FileNotFoundError(f"Translations catalog not found at {cat_path}")

    catalog = json.loads(cat_path.read_text(encoding="utf-8"))
    entries_map = {item["entry_index"]: item for item in catalog}

    if not bin_path.is_file():
        raise FileNotFoundError(f"Target disc image not found at {bin_path}")

    # Determine working BIN path
    work_bin = bin_path
    if output_bin is not None and output_bin != bin_path and not dry_run:
        output_bin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bin_path, output_bin)
        work_bin = output_bin

    # 1. Encode all 119 spell entries for PROG.UNT 325..443
    cm = build_combat_dialogue_charmap()
    encoded_entries: list[bytes] = []
    max_payload_size = 0

    for idx in range(SPELLS_FIRST_ENTRY, SPELLS_LAST_ENTRY + 1):
        if idx not in entries_map:
            raise KeyError(f"Entry {idx} missing from {cat_path}")
        entry = entries_map[idx]
        encoded = encode_spell(entry, cm)
        encoded_entries.append(encoded)

        words = list(struct.unpack(f"<{len(encoded)//2}H", encoded))
        used_len = (words.index(OPCODE_TERMINATOR) + 1) * 2 if OPCODE_TERMINATOR in words else len(encoded)
        if used_len > max_payload_size:
            max_payload_size = used_len

    # Font 0x142 Bank 0 is never modified (see patch_combat_font.apply_combat_font_patches).
    # The in-battle spell list itself is injected by tools/patch_spell_menu_ru.py.

    _prog_lba_e7, _e7_start, e7_count = get_prog_unt_entry_extent(work_bin, ENTRY_COMBAT_DATA)
    prog_lba, first_offset, sector_offsets = get_prog_unt_spells_extent(work_bin)
    # Check contiguity of 119 spells
    is_contiguous = all(
        sector_offsets[i] == sector_offsets[0] + i
        for i in range(len(sector_offsets))
    )

    if not dry_run:
        # Write Entries 325..443 (119 sectors) with automatic Mode 2 Form 1 EDC/ECC repair
        if is_contiguous:
            full_payload = b"".join(encoded_entries)
            replace_extent_in_place(work_bin, prog_lba + first_offset, full_payload)
        else:
            for idx, offset in enumerate(sector_offsets):
                replace_extent_in_place(work_bin, prog_lba + offset, encoded_entries[idx])
    return {
        "spells_patched": len(encoded_entries),
        "entry_007_sectors": e7_count,
        "target_bin": str(work_bin),
        "dry_run": dry_run,
        "max_payload_size": max_payload_size,
        "entry_budget": ENTRY_SECTOR_SIZE,
        "is_contiguous": is_contiguous,
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="Patch PROG.UNT spells and options 325..443 in Slayers Royal (PS1).")
    parser.add_argument("--bin", type=Path, default=DEFAULT_BIN, help="Path to input disc image")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Path to translations/spells_ru.json")
    parser.add_argument("--output-bin", type=Path, help="Path to output modified disc image")
    parser.add_argument("--dry-run", action="store_true", help="Encode and validate without writing to disc")
    parser.add_argument("--verify", action="store_true", help="Verify all 119 entries and EDC/ECC on disc")
    args = parser.parse_args()

    print(f"Target BIN: {args.bin}")
    print(f"Translations: {args.catalog}")

    if args.verify:
        print("Mode: VERIFY (Validating all 119 entries and EDC/ECC)")
        try:
            results = verify_spells_on_disc(args.bin, args.catalog)
            print(f"Entries checked:       {results['entries_total']}")
            print(f"EDC/ECC valid (325..): {results['edc_ecc_valid']}/{results['entries_total']}")
            print(f"Content valid (325..): {results['content_valid']}/{results['entries_total']}")
            print(f"EDC/ECC valid (0x007): {results['entry_007_edc_ecc_valid']}/{ENTRY_007_SECTORS}")
            if results["errors"]:
                print(f"Verification FAILED with {len(results['errors'])} errors:")
                for err in results["errors"][:10]:
                    print(f"  - {err}")
                if len(results["errors"]) > 10:
                    print(f"  ... and {len(results['errors']) - 10} more errors")
                return 1
            print("100% OK: All 119 spell entries and EDC/ECC verified successfully.")
            return 0
        except Exception as e:
            print(f"Verification error: {e}", file=sys.stderr)
            return 1

    mode_str = "DRY RUN" if args.dry_run else "APPLY PATCH"
    print(f"Mode: {mode_str}")

    try:
        res = patch_spells(
            bin_path=args.bin,
            catalog_path=args.catalog,
            output_bin=args.output_bin,
            dry_run=args.dry_run,
        )
        print(f"Successfully processed {res['spells_patched']} spell entries.")
        print(f"Max payload size: {res['max_payload_size']} bytes / {res['entry_budget']} bytes budget.")
        if not args.dry_run:
            print("Verifying EDC/ECC and written entries on disc...")
            v_res = verify_spells_on_disc(Path(res["target_bin"]), args.catalog)
            if v_res["errors"]:
                print(f"Verification after patching FAILED: {v_res['errors']}", file=sys.stderr)
                return 1
            print("EDC/ECC and content: 100% verified.")
        return 0
    except Exception as e:
        print(f"Error during patching: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
