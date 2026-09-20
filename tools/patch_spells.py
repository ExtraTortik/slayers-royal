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

# Original 8-bit spell selection menu bytes from PROG.UNT Entry 0x007
# (0x06F2CC..0x06F4D8).  The in-battle spell list renderer is hard-wired to
# the original Japanese/Latin 8-bit font tile set and cannot display Cyrillic.
# These are the verified-clean English bytes that produce readable spell names
# (BURST RONDO, FLARE ARROW, etc.) in the selection menu.
ENTRY_007_CLEAN_SPELL_MENU_BYTES = bytes.fromhex(
    "070d0a151724101013225f05002c0c0903080a0a5f012c290312065f07001211"
    "0308040b5f1408291024040e080c061a032c062a1b231304030f00062a1b2313"
    "04195f5f050a1c1f1c2e141a050f0404161f1c2e141a5f5f010a0010115f0010"
    "075f5f5f03321d11172d0011071b5f5f050a000f1f232804080208020a045f23"
    "28045f5f010f000b5f061d070b0406005f012c2903210b5f1408291b0010112c"
    "0a5f13080c045f5f16040a1d170f08030425040908005f2328045f5f010f000b"
    "5f012316040f5f5f1e0f10115f2e290d2d2f0f2d02302a19010d0b011b2b0803"
    "03000b5f010f1d10030f00062a1b231304185f5f060d165f13312e120f005f11"
    "080a115f050a000f1f1c2e14020a0015170d0b01052d04161f1c2e14050f0404"
    "1604170f08035f5f012c0b5f05000c060f04020d13040f1503150c1d11172d00"
    "11075f5f03042627180f3311000a5f5f0b2a0d5f130d0a110a08060711080c06"
    "0f000627172303040308065f130d0a1103210b5f140829180a08060711080c06"
    "100a04040e080c060f042f0f2d02302a0308020a04000f151e0f10115f05232d"
    "05080f0401000a0a5f5f5f5f010a1d11170d0b01010d0b015f102b0803175f5f"
    "03000b170f1d101703321d11172d001107175f5f0f005f11080a111705080f04"
    "01000a0a5f5f5f5f00040f0d170d0b0103080a0a5f010f0029175f5f03122007"
    "001211172d020d13040f1517"
)
assert len(ENTRY_007_CLEAN_SPELL_MENU_BYTES) == ENTRY_007_SPELL_MENU_SIZE

# Russian 8-bit spell selection menu bytes for PROG.UNT Entry 0x007
# (0x06F2CC..0x06F4D8). Encoded in 26 Cyrillic 8x10 font tiles.
ENTRY_007_RU_SPELL_MENU_BYTES = bytes.fromhex(
    "03011112135f110f0e060f150c070a115f1911110f14150c070a115f0c190e12"
    "15020711030f0c03011112135f150c070a11030c0212135f030f0d0302061102"
    "05145f120c070a0406110205145f120c00141102050e025f030c070a065f5f5f"
    "5f5f5f5f5f5f5f5f120c09105f0e150c070a1100195f0e1511090800195f0e06"
    "02051602141306090d04090e06030c0212131917020a12090b0c5f0c190e1203"
    "11020d0502170d0705025f0311020e0608070c02125f031109060311020d5f03"
    "0c070a08030f0d035f121011090606020d031102120b0c070a030f0d15110908"
    "5f1911110f14151109085f031109060311020d5f15020e0506020a0e02121306"
    "070d0f0e02060905040f0c130219110f5f030f0d03025f5f5f5f5f5f5f5f5f5f"
    "5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f160f0c09"
    "0003040912001506090c0c000306020a0e001206090d001202121311020c190c"
    "180d070b110708001406110205000b050f0800041411021311070b020407110d"
    "0f0e0f00040c020a13000206090d000b0c020a130003120c0910090e05110708"
    "0f111106090b0c09021115020711030f0c0600030600165f5f5f5f5f5f5f5f5f"
    "5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f5f"
    "030f0d0300120306020d00035f0306020a0e0212135f03110200135f0311070b"
    "02045f035f5f5f5f5f5f5f5f"
)
assert len(ENTRY_007_RU_SPELL_MENU_BYTES) == ENTRY_007_SPELL_MENU_SIZE

ENTRY_007_RU_POINTER_BYTES = bytes.fromhex(
    "000000007cd80b8087d80b8092d80b809cd80b80a3d80b80aed80b80b9d80b80"
    "c4d80b80ced80b80e4d80b80ead80b80f3d80b80fbd80b8002d90b8009d90b80"
    "10d90b801bd90b8022d90b802cd90b8036d90b8040d90b804ad90b8051d90b80"
    "58d90b8062d90b806bd90b8074d90b807bd90b8081d90b8088d90b80b8d90b80"
    "bed90b80c3d90b80c9d90b80cfd90b80d4d90b80dad90b80e0d90b80e5d90b80"
    "ebd90b80f1d90b80f4d90b80fbd90b8001da0b8007da0b800cda0b8012da0b80"
    "19da0b801fda0b8026da0b802dda0b8030da0b805cda0b8063da0b806ada0b80"
    "73da0b8079da0b8088da0b80"
)
ENTRY_007_POINTER_TABLE_START = 0x06F4D8
ENTRY_007_POINTER_TABLE_SIZE = len(ENTRY_007_RU_POINTER_BYTES)  # 236 bytes
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


def patch_spell_menu_in_entry_007(
    e7_data: bytearray,
    clean_bytes: bytes | None = None,
    pointer_bytes: bytes | None = None,
) -> bytearray:
    """Write Russian spell selection menu and pointer table into Entry 0x007."""
    if not isinstance(e7_data, bytearray):
        e7_data = bytearray(e7_data)

    # Verify MIPS init exit invariant
    mips_code = struct.unpack_from("<II", e7_data, OFFSET_MIPS_INIT_EXIT)
    if mips_code != (0x03E00008, 0x00000000):
        raise ValueError(
            f"MIPS exit instruction at 0x{OFFSET_MIPS_INIT_EXIT:06X} corrupted: "
            f"0x{mips_code[0]:08X}, 0x{mips_code[1]:08X}"
        )

    payload = clean_bytes if clean_bytes is not None else ENTRY_007_RU_SPELL_MENU_BYTES
    ptrs = pointer_bytes if pointer_bytes is not None else (ENTRY_007_RU_POINTER_BYTES if clean_bytes is None else None)

    if len(payload) != ENTRY_007_SPELL_MENU_SIZE:
        raise ValueError(f"Spell menu payload size mismatch: {len(payload)} != {ENTRY_007_SPELL_MENU_SIZE}")

    e7_data[ENTRY_007_SPELL_MENU_START : ENTRY_007_SPELL_MENU_START + ENTRY_007_SPELL_MENU_SIZE] = payload
    if ptrs is not None:
        e7_data[ENTRY_007_POINTER_TABLE_START : ENTRY_007_POINTER_TABLE_START + len(ptrs)] = ptrs

    # Re-verify MIPS exit invariant
    mips_post = struct.unpack_from("<II", e7_data, OFFSET_MIPS_INIT_EXIT)
    if mips_post != (0x03E00008, 0x00000000):
        raise ValueError("MIPS exit instruction was corrupted during spell menu injection!")

    return e7_data


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
        "entry_007_menu_valid": 0,
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

    # Verify Entry 0x007 spell menu (0x06F2CC..0x06F4D8) matches clean baseline
    menu_bytes = bytes(e7_bytes[ENTRY_007_SPELL_MENU_START : ENTRY_007_SPELL_MENU_START + ENTRY_007_SPELL_MENU_SIZE])
    if menu_bytes == ENTRY_007_RU_SPELL_MENU_BYTES or menu_bytes == ENTRY_007_CLEAN_SPELL_MENU_BYTES:
        results["entry_007_menu_valid"] = sum(len(ids) for ids in SECTION_SPELL_IDS)
    else:
        results["errors"].append(
            f"Entry 0x007 spell menu at 0x{ENTRY_007_SPELL_MENU_START:06X} is corrupted: "
            f"does not match Russian translation or clean baseline"
        )
    return results


def patch_spells(
    bin_path: Path,
    catalog_path: Path | None = None,
    output_bin: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Encode and patch all 119 spells and Entry 0x007 spell menu into target disc image."""
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

    # 2. Ensure Entry 0x007 in-battle spell selection menu (0x06F2CC..0x06F4D8) is Russian
    prog_lba_e7, e7_start, e7_count = get_prog_unt_entry_extent(work_bin, ENTRY_COMBAT_DATA)
    orig_e7 = bytearray(read_extent(work_bin, prog_lba_e7 + e7_start, e7_count * 2048))
    current_menu_bytes = bytes(orig_e7[ENTRY_007_SPELL_MENU_START : ENTRY_007_SPELL_MENU_START + ENTRY_007_SPELL_MENU_SIZE])
    current_ptrs = bytes(orig_e7[ENTRY_007_POINTER_TABLE_START : ENTRY_007_POINTER_TABLE_START + ENTRY_007_POINTER_TABLE_SIZE])
    need_e7_write = (current_menu_bytes != ENTRY_007_RU_SPELL_MENU_BYTES or current_ptrs != ENTRY_007_RU_POINTER_BYTES)
    if not need_e7_write and not dry_run:
        # Verify EDC/ECC across all 745 sectors of Entry 0x007
        checksums = CdChecksums()
        with work_bin.open("rb") as f:
            for sec_i in range(e7_count):
                f.seek((prog_lba_e7 + e7_start + sec_i) * RAW_SECTOR_SIZE)
                raw_sec = f.read(RAW_SECTOR_SIZE)
                if (checksums.compute_edc(raw_sec[0x10:0x818]) != raw_sec[0x818:0x81C] or
                    checksums.compute_ecc(raw_sec[0x10:], 86, 24, 2, 86) != raw_sec[0x81C:0x8C8] or
                    checksums.compute_ecc(raw_sec[0x10:], 52, 43, 86, 88) != raw_sec[0x8C8:0x930]):
                    need_e7_write = True
                    break

    if need_e7_write:
        patched_e7 = patch_spell_menu_in_entry_007(orig_e7)
        if not dry_run:
            replace_extent_in_place(work_bin, prog_lba_e7 + e7_start, bytes(patched_e7))

    # 3. Ensure Entry 0x142 combat font contains 8x10 Cyrillic glyphs for spell menu
    prog_lba_e142, e142_start, e142_count = get_prog_unt_entry_extent(work_bin, ENTRY_COMBAT_FONT)
    e142_raw = read_extent(work_bin, prog_lba_e142 + e142_start, e142_count * 2048)
    tim_dec, _ = unt_lz.decompress(e142_raw)
    from tools.patch_spell_names import patch_tim_with_cyrillic
    patched_tim = patch_tim_with_cyrillic(tim_dec)
    if patched_tim != tim_dec:
        comp_tim = unt_lz.compress(bytes(patched_tim)).ljust(e142_count * 2048, b"\x00")
        if not dry_run:
            replace_extent_in_place(work_bin, prog_lba_e142 + e142_start, comp_tim)

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
        "menu_spells_patched": sum(len(ids) for ids in SECTION_SPELL_IDS),
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
            print(f"Spell menu valid (E7): {results['entry_007_menu_valid']}/57")
            if results["errors"]:
                print(f"Verification FAILED with {len(results['errors'])} errors:")
                for err in results["errors"][:10]:
                    print(f"  - {err}")
                if len(results["errors"]) > 10:
                    print(f"  ... and {len(results['errors']) - 10} more errors")
                return 1
            print("100% OK: All 119 spell entries, Entry 0x007 spell menu and EDC/ECC verified successfully.")
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
        print(f"Successfully processed {res['menu_spells_patched']} in-battle spell menu names in Entry 0x007.")
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
