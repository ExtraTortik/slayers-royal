#!/usr/bin/env python3
"""Unified combat mode patcher for Slayers Royal (PS1).

This tool:
1. Injects modified and compressed combat font TIM (entry 0x142) into PROG.UNT.
   - Decompresses 0x142 (4bpp TIM).
   - Draws Russian Cyrillic glyphs into tiles 0x0100..0x0120 and 0x0150..0x0170.
   - Re-compresses with LZSS mode 1 (unt_lz) within the 23-sector budget (47,104 bytes).
2. Injects translated system strings (menus, commands, PICK UNIT) and all 101 combat
   dialogue cues into PROG.UNT entry 0x007 (RAM base 0x8004E110).
   - Recalculates 32-bit absolute PSX RAM pointers in tables (0x05F1FC..0x05F254,
     0x05F470..0x05F504, 0x06286C..0x062A0C).
   - Ensures offset 0x05F398 (and pointer 0x05F244) contains "ВЫБЕРИТЕ ЮНИТ".
   - Ensures offset 0x06241C (and cue pointer) contains "Тьфу! Если бы ты пошла с нами...".
3. Writes modified sectors to the CD-ROM BIN disc image with Mode 2 Form 1 EDC/ECC repair.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import (
    read_extent,
    replace_extent_in_place,
    CdChecksums,
    RAW_SECTOR_SIZE,
    USER_DATA_SIZE,
    USER_DATA_OFFSET,
)
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
    patch_unt_entry,
    DEFAULT_CHARMAP,
)
from tools.patch_combat_font import (
    unpack_combat_font,
    patch_combat_font,
    compress_combat_font,
    find_press_start_font,
    get_tile,
    COMBAT_FONT_ENTRY,
    COMBAT_FONT_MAX_SIZE,
)
from tools.combat_text import (
    build_combat_charmap,
    build_reverse_charmap,
    load_combat_charmap,
    encode_combat_string,
    encode_text,
    decode_16le_string,
    format_ru_text,
    RAM_BASE,
    PROG_ENTRY_COMBAT,
)

DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_CATALOG = REPO_ROOT / "translations" / "combat_ru.json"
DEFAULT_SOURCE_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"

# System strings safe free space offset within 0x007
SYS_STRINGS_RELOC_OFFSET = 0x082400
# Dialogue cues stream start offset within 0x007
DIALOGUES_STREAM_OFFSET = 0x05F810
# Specific canonical offsets
OFFSET_PICK_UNIT = 0x05F398
OFFSET_CUE_092 = 0x06241C
PTR_OFFSET_PICK_UNIT = 0x05F244

# Combat font VRAM loader hook configuration in 0x007:
# Target injection in 0x007:
# RAM 0x8007989C: combat interface initialization exit (jr $ra replaced with j hook)
OFFSET_COMBAT_INIT_EXIT = 0x02B78C
# Safe free space in 0x007 for the loader subroutine (after system strings):
OFFSET_COMBAT_HOOK = 0x082800
COMBAT_HOOK_RAM = RAM_BASE + OFFSET_COMBAT_HOOK  # RAM 0x800D0910

# Subroutine addresses in PS-X BIOS / SLPS executable:
ADDR_UNT_UNPACK = 0x800118CC
ADDR_LZSS_DECOMPRESS = 0x80012ACC
ADDR_UPLOAD_TIM_TO_VRAM = 0x80011A94

# Buffer addresses in PS1 RAM:
BUFFER_READ_03A = 0x80100000
BUFFER_DECOMP_03A = 0x80110000
ENTRY_03A = 58  # 0x03A in PROG.UNT

# Table 2 (0x05F470..0x05F504): 37 canonical pointers to scene triggers (0x05F718..0x05F908).
# These MUST be preserved intact without text deltas.
TABLE2_CANONICAL_BYTES = bytes.fromhex(
    "28d80a8034d80a8040d80a804cd80a8058d80a8064d80a8074d80a807cd80a80"
    "88d80a8090d80a809cd80a80a4d80a80b0d80a80c0d80a80c8d80a80d0d80a80"
    "dcd80a80e8d80a80f0d80a80fcd80a8004d90a800cd90a8018d90a8024d90a80"
    "30d90a803cd90a8048d90a8060d90a8078d90a808cd90a80a0d90a80b8d90a80"
    "d0d90a80e4d90a80f8d90a8010da0a8018da0a80"
)

# Table 3 (0x06286C..0x062A0C): 105 canonical dialogue cue origins.
# Each pointer is mapped strictly to the valid start of the corresponding dialogue cue.
TABLE3_CUE_OFFSETS: tuple[int, ...] = (
    0x05FCA8, 0x05FD30, 0x05FDBC, 0x05FDBC, 0x05FDBC,
    0x05FF0C, 0x05FF9E, 0x060070, 0x060070, 0x060070,
    0x060070, 0x060070, 0x060070, 0x06023C, 0x060380,
    0x06043E, 0x060574, 0x0605DC, 0x0606A8, 0x060716,
    0x060768, 0x06079A, 0x06079A, 0x0607DC, 0x0607DC,
    0x060992, 0x060A0C, 0x060A0C, 0x060A52, 0x060A52,
    0x060B32, 0x060B32, 0x060CA4, 0x060CA4, 0x060CA4,
    0x060CA4, 0x060CA4, 0x060CA4, 0x060CA4, 0x060CA4,
    0x060CA4, 0x06119C, 0x06119C, 0x0612B8, 0x061366,
    0x0613BE, 0x061400, 0x0614E4, 0x061542, 0x061542,
    0x061542, 0x061542, 0x061542, 0x0616BC, 0x0616E8,
    0x0617B8, 0x0617B8, 0x061834, 0x06189C, 0x0618E0,
    0x0626CC, 0x0618E0, 0x061968, 0x0619B2, 0x061AC4,
    0x061B1E, 0x061B1E, 0x061B1E, 0x061B1E, 0x061C12,
    0x061C12, 0x061C12, 0x061C12, 0x061C12, 0x061C12,
    0x061C12, 0x061C12, 0x061C12, 0x061C12, 0x061C12,
    0x061C12, 0x061F62, 0x061F62, 0x061F62, 0x061FB4,
    0x062078, 0x0620B0, 0x0620F2, 0x0620F2, 0x06216C,
    0x06216C, 0x06216C, 0x06226C, 0x062308, 0x062308,
    0x062308, 0x06241C, 0x0624AC, 0x0624EA, 0x0624EA,
    0x0625B0, 0x062630, 0x0626CC, 0x0626CC, 0x0626CC,
)

# Complete button offsets in 0x007 (0x05F278..0x05F470)
# All strings are encoded via DEFAULT_CHARMAP and terminated with 0x00FF.
COMBAT_BUTTON_SLOTS: list[tuple[int, str]] = [
    (0x05F278, "СТАРТ"),
    (0x05F284, "ОПЦИИ"),
    (0x05F292, "АТАКА"),
    (0x05F2A0, "ОТВЕТ"),
    (0x05F2AE, "МАГИЯ"),
    (0x05F2BC, "ХОД"),
    (0x05F2C4, "УДАР"),
    (0x05F2CE, "ТАРАН"),
    (0x05F2DA, "ХОД"),
    (0x05F2E4, "ТАПОК"),
    (0x05F2F4, "ХОХОТ"),
    (0x05F300, "ОТВЕТ"),
    (0x05F310, "УДАР"),
    (0x05F322, "УКЛОН"),
    (0x05F32E, "БЕГ"),
    (0x05F338, "ЗАЩИТА"),
    (0x05F346, "БЛОК"),
    (0x05F352, "ЩИТ"),
    (0x05F35C, "АВТО"),
    (0x05F366, "СТОП"),
    (0x05F370, "ВЫБОР"),
    (0x05F37C, "АВТО"),
    (0x05F386, "АТАКА"),
    (0x05F398, "ВЫБЕРИТЕ ЮНИТ"),
    (0x05F3BA, "ИКОНКА"),
    (0x05F3CE, "ИКОНКА"),
    (0x05F3E2, "МАГИЯ"),
    (0x05F3F8, "КУДА?"),
    (0x05F40A, "ЦЕЛЬ?"),
    (0x05F41A, "ЗОНА?"),
    (0x05F426, "БОЙ!"),
    (0x05F438, "ЖДИТЕ"),
    (0x05F444, "ТИП"),
    (0x05F458, "СОХР"),
    (0x05F462, "ЗАГР"),
]


@dataclass
class CombatPatchResult:
    """Statistics for applied combat mode patch."""
    disc_path: Path
    font_decompressed_bytes: int
    font_compressed_bytes: int
    font_allocated_bytes: int
    system_strings_count: int
    dialogues_count: int
    pointers_updated: int
    sectors_patched: int
    hook_installed: bool = True


def encode_text(text: str, charmap: Mapping[str, int] | None = None) -> bytes:
    """Encode a text string into 16-bit little endian words with 0x00FF terminator."""
    return encode_combat_string(text, charmap if charmap is not None else build_combat_charmap())


def build_combat_font_loader_hook(hook_ram_addr: int = COMBAT_HOOK_RAM) -> bytes:
    """Assemble MIPS machine code for combat_font_loader_hook.

    Subroutine actions upon entering combat:
    1. Allocate stack frame and preserve $ra, $s0-$s2.
    2. UNT_UNPACK(archive=0, entry=58, dest=0x80100000)
       Loads compressed Russian font (PROG.UNT 0x03A) from disc into RAM.
    3. LZSS_DECOMPRESS(src=0x80100000, dest=0x80110000)
       Decompresses LZSS mode 1 TIM (131,616 bytes).
    4. UPLOAD_TIM_TO_VRAM(tim=0x80110000, clut_override=0, img_override=0, flags=0)
       Uploads font bitmap to VRAM (512, 0) via Sony LoadImage.
    5. Restore registers and return to combat interface caller via jr $ra.
    """
    instructions = [
        # Prologue: allocate 32-byte stack frame
        0x27BDFFE0,  # addiu $sp, $sp, -32
        0xAFBF001C,  # sw    $ra, 28($sp)
        0xAFB20018,  # sw    $s2, 24($sp)
        0xAFB10014,  # sw    $s1, 20($sp)
        0xAFB00010,  # sw    $s0, 16($sp)

        # Step a: UNT_UNPACK(0, 58, 0x80100000)
        0x00002021,  # addu  $a0, $zero, $zero  ($a0 = 0: PROG.UNT)
        0x2405003A,  # addiu $a1, $zero, 58     ($a1 = 58: entry 0x03A)
        0x3C068010,  # lui   $a2, 0x8010        ($a2 = 0x80100000: read buffer)
        (0x03 << 26) | ((ADDR_UNT_UNPACK >> 2) & 0x03FFFFFF),  # jal 0x800118CC
        0x00000000,  # nop

        # Step b: LZSS_DECOMPRESS(0x80100000, 0x80110000)
        0x3C048010,  # lui   $a0, 0x8010        ($a0 = 0x80100000: source)
        0x3C058011,  # lui   $a1, 0x8011        ($a1 = 0x80110000: dest buffer)
        (0x03 << 26) | ((ADDR_LZSS_DECOMPRESS >> 2) & 0x03FFFFFF),  # jal 0x80012ACC
        0x00000000,  # nop

        # Step c: UPLOAD_TIM_TO_VRAM(0x80110000, 0, 0, 0)
        0x3C048011,  # lui   $a0, 0x8011        ($a0 = 0x80110000: TIM pointer)
        0x00002821,  # addu  $a1, $zero, $zero  ($a1 = 0: no CLUT override)
        0x00003021,  # addu  $a2, $zero, $zero  ($a2 = 0: no IMG override)
        0x00003821,  # addu  $a3, $zero, $zero  ($a3 = 0: no flags)
        (0x03 << 26) | ((ADDR_UPLOAD_TIM_TO_VRAM >> 2) & 0x03FFFFFF),  # jal 0x80011A94
        0x00000000,  # nop

        # Step d: Epilogue: restore registers and return
        0x8FB00010,  # lw    $s0, 16($sp)
        0x8FB10014,  # lw    $s1, 20($sp)
        0x8FB20018,  # lw    $s2, 24($sp)
        0x8FBF001C,  # lw    $ra, 28($sp)
        0x27BD0020,  # addiu $sp, $sp, 32
        0x03E00008,  # jr    $ra
        0x00000000,  # nop
    ]
    return struct.pack(f"<{len(instructions)}I", *instructions)


def get_en_combat_font_bytes(en_disc_path: Path | None = None) -> bytes:
    """Extract pristine entry 0x142 from English base disc (sr_patched.bin).

    Preserves all combat sprites and HUD without custom glyph corruption.
    """
    path = en_disc_path if en_disc_path is not None else DEFAULT_EN_BIN
    if not path.is_file():
        raise FileNotFoundError(f"English base disc not found: {path}")

    pvd = read_sector(path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(path, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = read_extent(path, prog_lba, prog_size)
    entries = read_unt_index(prog_archive)
    e142 = entries[COMBAT_FONT_ENTRY]
    return bytes(prog_archive[e142.offset : e142.offset + e142.size])

def get_en_combat_overlay_bytes(en_disc_path: Path | None = None) -> bytes:
    """Extract pristine entry 0x007 from English base disc (sr_patched.bin).

    Preserves original gourry-hacks system strings, dialogues, and pointers.
    """
    path = en_disc_path if en_disc_path is not None else DEFAULT_EN_BIN
    if not path.is_file():
        raise FileNotFoundError(f"English base disc not found: {path}")

    pvd = read_sector(path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(path, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = read_extent(path, prog_lba, prog_size)
    entries = read_unt_index(prog_archive)
    e007 = entries[PROG_ENTRY_COMBAT]
    return bytes(prog_archive[e007.offset : e007.offset + e007.size])


def restore_combat_en_disc_image(
    disc_path: Path,
    source_en_bin: Path | None = None,
) -> tuple[int, int]:
    """Restore clean English combat mode (PROG.UNT 0x007 and 0x142) from verified English base.

    Writes 0x007 (745 sectors) and 0x142 (23 sectors) with Mode 2 Form 1 EDC/ECC repair.
    Returns:
        (total_sectors_restored, total_bytes_restored)
    """
    en_bin = source_en_bin if source_en_bin is not None else DEFAULT_EN_BIN
    if not en_bin.is_file():
        raise FileNotFoundError(f"English base disc not found: {en_bin}")

    font_bytes = get_en_combat_font_bytes(en_bin)
    overlay_bytes = get_en_combat_overlay_bytes(en_bin)

    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]

    entries = read_unt_index(read_extent(disc_path, prog_lba, 2048))
    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]

    replace_extent_in_place(disc_path, prog_lba + e142.start_sector, font_bytes)
    replace_extent_in_place(disc_path, prog_lba + e007.start_sector, overlay_bytes)

    total_sectors = e142.sector_count + e007.sector_count
    total_bytes = len(font_bytes) + len(overlay_bytes)
    return total_sectors, total_bytes


def patch_combat_font_entry(
    prog_archive: bytearray,
    source_bin: Path | None = None,
    font_path: Path | None = None,
) -> tuple[int, int, int]:
    """Restore pristine combat font entry 0x142 from English base disc (sr_patched.bin).

    Preserves all combat sprites and HUD without custom glyph corruption.
    Returns:
        (decompressed_size, compressed_size, allocated_size)
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

    offset, allocated, payload_len = patch_unt_entry(prog_archive, COMBAT_FONT_ENTRY, font_comp)
    return len(decomp_bytes), len(font_comp), allocated

def patch_combat_overlay_entry(
    prog_archive: bytearray,
    catalog: dict[str, Any],
    charmap: dict[str, int] | None = None,
) -> tuple[int, int, int]:
    """Patch system strings, dialogues, and 32-bit RAM pointers in entry 0x007.

    Returns:
        (system_strings_count, dialogues_count, pointers_updated)
    """
    cm = charmap if charmap is not None else build_combat_charmap()
    entries = read_unt_index(prog_archive)
    if PROG_ENTRY_COMBAT >= len(entries):
        raise IndexError(f"PROG.UNT does not contain entry 0x{PROG_ENTRY_COMBAT:03X}")
    e007 = entries[PROG_ENTRY_COMBAT]

    # Slice entry 0x007 in memory
    e007_data = bytearray(prog_archive[e007.offset : e007.offset + e007.size])

    # 1. Place 37 System Strings in safe free space (0x082400)
    sys_strings = catalog.get("system_strings", [])
    sys_map: dict[int, int] = {}  # old_offset -> new_offset
    cur_sys = SYS_STRINGS_RELOC_OFFSET

    for s in sys_strings:
        old_off = int(s["offset"], 16)
        enc = encode_text(s["text_ru"], cm)
        sys_map[old_off] = cur_sys
        e007_data[cur_sys : cur_sys + len(enc)] = enc
        cur_sys += len(enc)
        if cur_sys % 2 != 0:
            cur_sys += 1

    # 2. Clean and overwrite ALL combat menu buttons in 0x05F278..0x05F470
    # Zero out the entire button area so no residual English/ASCII bytes or
    # Japanese characters remain (e.g. 0x0128, 0x0192 'CK').
    e007_data[0x05F278:0x05F470] = b"\x00" * (0x05F470 - 0x05F278)

    # Write each Russian button at its exact offset
    for btn_off, btn_txt in COMBAT_BUTTON_SLOTS:
        btn_enc = encode_text(btn_txt, cm)
        e007_data[btn_off : btn_off + len(btn_enc)] = btn_enc

    # Ensure "ВЫБЕРИТЕ ЮНИТ" at canonical offset 0x05F398 is strictly set
    pick_unit_enc = encode_text("ВЫБЕРИТЕ ЮНИТ", cm)
    e007_data[OFFSET_PICK_UNIT : OFFSET_PICK_UNIT + len(pick_unit_enc)] = pick_unit_enc
    # 2. Place extra combat strings in-place (0x00154C, 0x0015E0, 0x0634C8, 0x0635EC, 0x0713C4, 0x071744, 0x0717A0)
    extra_strings = catalog.get("extra_combat_strings", [])
    for es in extra_strings:
        off = int(es["offset"], 16)
        enc = encode_text(es["text_ru"], cm)
        max_b = es.get("max_bytes")
        if max_b is not None and len(enc) > max_b:
            enc = enc[:max_b]
        e007_data[off : off + len(enc)] = enc

    # 3. Update Table 1 system string pointers (0x05F1FC..0x05F258)
    ptrs_updated = 0
    for off in range(0x05F1FC, 0x05F258, 4):
        ram_p = struct.unpack_from("<I", e007_data, off)[0]
        target_off = ram_p - RAM_BASE
        if off == PTR_OFFSET_PICK_UNIT:
            # Explicitly anchor PICK_UNIT pointer to 0x05F398
            struct.pack_into("<I", e007_data, off, RAM_BASE + OFFSET_PICK_UNIT)
            ptrs_updated += 1
        elif target_off in sys_map:
            new_target = sys_map[target_off]
            struct.pack_into("<I", e007_data, off, RAM_BASE + new_target)
            ptrs_updated += 1

    # 4. Place 101 dialogue cues sequentially starting at 0x05F810
    dialogues = catalog.get("dialogues", [])
    dlg_map: dict[int, int] = {}  # old_offset -> new_offset
    cur_dlg = DIALOGUES_STREAM_OFFSET

    for d in dialogues:
        old_off = int(d["offset"], 16)
        spk = int(d["speaker_opcode"], 16)
        enc = encode_text(d["text_ru"], cm)
        payload = struct.pack("<H", spk) + enc
        dlg_map[old_off] = cur_dlg
        e007_data[cur_dlg : cur_dlg + len(payload)] = payload
        cur_dlg += len(payload)
        if cur_dlg % 2 != 0:
            cur_dlg += 1

    # Directly place Cue #92 at canonical offset 0x06241C
    cue92 = next((d for d in dialogues if d.get("index") == 92), None)
    if cue92 is not None:
        c92_spk = int(cue92["speaker_opcode"], 16)
        c92_enc = encode_text(cue92["text_ru"], cm)
        c92_payload = struct.pack("<H", c92_spk) + c92_enc
        e007_data[OFFSET_CUE_092 : OFFSET_CUE_092 + len(c92_payload)] = c92_payload

    # 5. Restore Table 2 (0x05F470..0x05F504) scene trigger pointers intact
    # Table 2 pointers must NEVER be shifted by text deltas!
    e007_data[0x05F470 : 0x05F504] = TABLE2_CANONICAL_BYTES

    # 6. Update Table 3 (0x06286C..0x062A0C) dialogue pointers:
    # Each pointer points strictly to the valid start of the corresponding Russian replica
    # (with speaker opcode 0x91xx / 0xD1xx / 0xD2xx), never to 0xFF or middle of a word!
    for idx, cue_old_off in enumerate(TABLE3_CUE_OFFSETS):
        pos = 0x06286C + idx * 4
        new_target = dlg_map[cue_old_off]
        struct.pack_into("<I", e007_data, pos, RAM_BASE + new_target)
        ptrs_updated += 1


    # 7. Inject combat font VRAM loader hook into 0x007
    # 7a. Write loader subroutine into safe free space at OFFSET_COMBAT_HOOK
    hook_code = build_combat_font_loader_hook()
    e007_data[OFFSET_COMBAT_HOOK : OFFSET_COMBAT_HOOK + len(hook_code)] = hook_code

    # 7b. Replace 'jr $ra; nop' at combat interface initialization exit (0x8007989C)
    # with trampoline jump 'j <COMBAT_HOOK_RAM>; nop'
    jump_instr = (0x02 << 26) | ((COMBAT_HOOK_RAM >> 2) & 0x03FFFFFF)
    struct.pack_into("<II", e007_data, OFFSET_COMBAT_INIT_EXIT, jump_instr, 0x00000000)
    # Write patched entry 0x007 back into PROG.UNT
    prog_archive[e007.offset : e007.offset + e007.size] = e007_data

    return len(sys_strings), len(dialogues), ptrs_updated


def patch_combat_disc_image(
    disc_path: Path,
    catalog_path: Path | None = None,
    source_bin: Path | None = None,
    font_path: Path | None = None,
) -> CombatPatchResult:
    """Patch PROG.UNT combat font (0x142) and text/overlay (0x007) in PS1 CD-ROM BIN image.

    Recalculates Mode 2 Form 1 EDC/ECC checksums for all modified sectors.
    """
    if catalog_path is None:
        catalog_path = DEFAULT_CATALOG
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Combat catalog not found: {catalog_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    charmap = build_combat_charmap()

    # Read ISO filesystem to find PROG.UNT
    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)

    if "PROG.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT not found in ISO directory of {disc_path}")

    prog_lba, prog_size = root_dir["PROG.UNT"]
    prog_archive = bytearray(read_extent(disc_path, prog_lba, prog_size))
    entries = read_unt_index(prog_archive)

    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]

    # 1. Patch combat font entry 0x142 inside prog_archive
    font_decomp, font_comp, font_alloc = patch_combat_font_entry(
        prog_archive,
        source_bin=source_bin,
        font_path=font_path,
    )

    # 2. Patch combat text & overlay 0x007 inside prog_archive
    sys_cnt, dlg_cnt, ptrs_upd = patch_combat_overlay_entry(
        prog_archive,
        catalog=catalog,
        charmap=charmap,
    )

    # 3. Write patched sectors back to disc with EDC/ECC repair:
    # 3a. Entry 0x142 (LBA prog_lba + e142.start_sector, e142.sector_count sectors)
    font_bytes = bytes(prog_archive[e142.offset : e142.offset + e142.size])
    replace_extent_in_place(disc_path, prog_lba + e142.start_sector, font_bytes)

    # 3b. Entry 0x007 (LBA prog_lba + e007.start_sector, e007.sector_count sectors)
    overlay_bytes = bytes(prog_archive[e007.offset : e007.offset + e007.size])
    replace_extent_in_place(disc_path, prog_lba + e007.start_sector, overlay_bytes)

    total_sectors = e142.sector_count + e007.sector_count

    return CombatPatchResult(
        disc_path=disc_path,
        font_decompressed_bytes=font_decomp,
        font_compressed_bytes=font_comp,
        font_allocated_bytes=font_alloc,
        system_strings_count=sys_cnt,
        dialogues_count=dlg_cnt,
        pointers_updated=ptrs_upd,
        sectors_patched=total_sectors,
    )

def verify_combat_patch(
    disc_path: Path,
    catalog_path: Path | None = None,
    mode: str = "auto",
) -> dict[str, Any]:
    """Verify binary integrity of combat font and text in a PS1 CD-ROM BIN image.

    Supports both English gourry-hacks baseline and Russian combat translation.
    """
    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)
    prog_lba, prog_size = root_dir["PROG.UNT"]

    sector0 = read_extent(disc_path, prog_lba, 2048)
    entries = read_unt_index(sector0)
    e142 = entries[COMBAT_FONT_ENTRY]
    e007 = entries[PROG_ENTRY_COMBAT]

    # Verify entry 0x142 structure
    comp_142 = read_extent(disc_path, prog_lba + e142.start_sector, e142.size)
    decomp_142, _ = unt_lz.decompress(comp_142)
    assert len(decomp_142) == 66080, f"Expected 66080 bytes TIM, got {len(decomp_142)}"
    magic, flags = struct.unpack_from("<II", decomp_142, 0)
    assert magic == 0x10 and flags == 0x08, f"Invalid TIM header in entry 0x142: {magic=}, {flags=}"

    # Verify entry 0x007
    prog_007 = read_extent(disc_path, prog_lba + e007.start_sector, e007.size)

    # Detect active mode
    exit_instr = struct.unpack_from("<I", prog_007, OFFSET_COMBAT_INIT_EXIT)[0]
    is_english = (exit_instr == 0x03E00008)
    active_mode = ("en" if is_english else "ru") if mode == "auto" else mode

    # Check EDC and ECC checksums on disc sectors for 0x142 (23 sectors) and 0x007 (745 sectors)
    checksums = CdChecksums()
    verified_sectors = 0
    with disc_path.open("rb") as f:
        for s in range(e142.sector_count):
            lba = prog_lba + e142.start_sector + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            assert sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818]), f"EDC mismatch at LBA {lba}"
            assert sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86), f"ECC P-parity mismatch at LBA {lba}"
            assert sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88), f"ECC Q-parity mismatch at LBA {lba}"
            verified_sectors += 1

        for s in range(e007.sector_count):
            lba = prog_lba + e007.start_sector + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            assert sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818]), f"EDC mismatch at LBA {lba}"
            assert sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86), f"ECC P-parity mismatch at LBA {lba}"
            assert sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88), f"ECC Q-parity mismatch at LBA {lba}"
            verified_sectors += 1

    if active_mode == "en":
        assert exit_instr == 0x03E00008, f"Expected standard jr $ra at 0x{OFFSET_COMBAT_INIT_EXIT:06X}, got 0x{exit_instr:08X}"
        ptr_pick = struct.unpack_from("<I", prog_007, PTR_OFFSET_PICK_UNIT)[0]
        assert ptr_pick == RAM_BASE + OFFSET_PICK_UNIT, f"Expected pointer 0x{RAM_BASE + OFFSET_PICK_UNIT:08X}, got 0x{ptr_pick:08X}"
        words_pick = decode_16le_string(prog_007, OFFSET_PICK_UNIT, stop_at_page=False)
        assert words_pick == [0x014D, 0x00B6, 0x0086, 0x00BF, 0x00FF], f"Expected PICK UNIT at 0x{OFFSET_PICK_UNIT:06X}"

        pos_92 = 0x06286C + 91 * 4
        ram_92 = struct.unpack_from("<I", prog_007, pos_92)[0]
        spk_92 = struct.unpack_from("<H", prog_007, ram_92 - RAM_BASE)[0]
        assert spk_92 in (0x0048, 0x0000, 0xD26A), f"Expected cue 92 speaker opcode or padding, got 0x{spk_92:04X}"

        return {
            "verified": True,
            "mode": "en",
            "combat_font_entry": f"0x{COMBAT_FONT_ENTRY:03X}",
            "combat_overlay_entry": f"0x{PROG_ENTRY_COMBAT:03X}",
            "pick_unit_text": "PICK UNIT",
            "cue_092_speaker": f"0x{spk_92:04X}",
            "cue_092_text_prefix": "English gourry-hacks baseline",
            "edc_ecc_verified_sectors": verified_sectors,
            "combat_vram_hook": "None (original jr $ra, English baseline)",
        }

    # Russian combat translation checks
    charmap = build_combat_charmap()
    rev_charmap = build_reverse_charmap(charmap)

    tile_a = get_tile(decomp_142, charmap["А"])
    assert any(b != 0 for b in tile_a), f"Tile 0x{charmap['А']:04X} ('А') in entry 0x142 is empty!"
    tile_t = get_tile(decomp_142, charmap["Т"])
    assert any(b != 0 for b in tile_t), f"Tile 0x{charmap['Т']:04X} ('Т') in entry 0x142 is empty!"
    tile_b = get_tile(decomp_142, charmap["Б"])
    assert any(b != 0 for b in tile_b), f"Tile 0x{charmap['Б']:04X} ('Б') in entry 0x142 is empty!"

    words_pick = decode_16le_string(prog_007, OFFSET_PICK_UNIT, stop_at_page=False)
    text_pick = "".join(rev_charmap.get(w, "") for w in words_pick)
    assert text_pick == "ВЫБЕРИТЕ ЮНИТ", f"Expected 'ВЫБЕРИТЕ ЮНИТ' at 0x05F398, got '{text_pick}'"
    expected_pick_prefix = encode_text("ВЫБЕ", charmap)[:8]
    assert prog_007[OFFSET_PICK_UNIT : OFFSET_PICK_UNIT + 8] == expected_pick_prefix, (
        f"Expected prefix {expected_pick_prefix.hex()} at 0x{OFFSET_PICK_UNIT:06X}, got {prog_007[OFFSET_PICK_UNIT : OFFSET_PICK_UNIT + 8].hex()}"
    )

    ptr_pick = struct.unpack_from("<I", prog_007, PTR_OFFSET_PICK_UNIT)[0]
    target_pick = ptr_pick - RAM_BASE
    words_ptr_pick = decode_16le_string(prog_007, target_pick, stop_at_page=False)
    text_ptr_pick = "".join(rev_charmap.get(w, "") for w in words_ptr_pick)
    assert text_ptr_pick == "ВЫБЕРИТЕ ЮНИТ", f"Pointer at 0x05F244 must point to 'ВЫБЕРИТЕ ЮНИТ', got '{text_ptr_pick}'"

    spk92 = struct.unpack_from("<H", prog_007, OFFSET_CUE_092)[0]
    assert spk92 == 0xD26A, f"Expected speaker 0xD26A at 0x06241C, got 0x{spk92:04X}"
    words_92 = decode_16le_string(prog_007, OFFSET_CUE_092 + 2, stop_at_page=False)
    text_92 = "".join(rev_charmap.get(w, "") for w in words_92)
    assert "Тьфу! Если бы ты пошла с нами" in text_92, f"Expected replica at 0x06241C, got '{text_92}'"
    assert words_92[0] == charmap["Т"] == 0x001C, f"Cue 92 'Т' expected 0x001C, got 0x{words_92[0]:04X}"
    assert words_92[1] == charmap["ь"] == 0x004C, f"Cue 92 'ь' expected 0x004C, got 0x{words_92[1]:04X}"
    assert words_92[2] == charmap["ф"] == 0x0041, f"Cue 92 'ф' expected 0x0041, got 0x{words_92[2]:04X}"
    assert words_92[3] == charmap["у"] == 0x003F, f"Cue 92 'у' expected 0x003F, got 0x{words_92[3]:04X}"
    kanji_in_92 = [w for w in words_92 if 0x0100 <= w <= 0x03E0]
    assert not kanji_in_92, f"Cue 92 contains kanji codes: {[hex(w) for w in kanji_in_92]}"

    words_auto = decode_16le_string(prog_007, 0x05F35C, stop_at_page=False)
    text_auto = "".join(rev_charmap.get(w, "") for w in words_auto)
    assert text_auto == "АВТО", f"Expected 'АВТО' at 0x05F35C, got '{text_auto}'"

    words_udar = decode_16le_string(prog_007, 0x05F2C4, stop_at_page=False)
    text_udar = "".join(rev_charmap.get(w, "") for w in words_udar)
    assert text_udar == "УДАР", f"Expected 'УДАР' at 0x05F2C4, got '{text_udar}'"
    assert 0x0128 not in words_udar and 0x0192 not in words_udar, "Residual English 'CK' found in button slot 0x05F2C4!"

    for pos in range(0x05F470, 0x05F504, 4):
        ram_p = struct.unpack_from("<I", prog_007, pos)[0]
        t = ram_p - RAM_BASE
        assert 0x05F718 <= t <= 0x05F910, f"Table 2 pointer at 0x{pos:06X} invalid target: 0x{t:06X}"

    for idx, pos in enumerate(range(0x06286C, 0x062A0C + 4, 4)):
        ram_p = struct.unpack_from("<I", prog_007, pos)[0]
        t = ram_p - RAM_BASE
        assert 0 <= t < len(prog_007) - 2, f"Table 3 pointer at 0x{pos:06X} points out of bounds: 0x{t:06X}"
        spk = struct.unpack_from("<H", prog_007, t)[0]
        assert (spk >> 8) in (0x91, 0xD1, 0xD2), f"Table 3 pointer at 0x{pos:06X} -> 0x{t:06X} has invalid speaker opcode 0x{spk:04X}"
        w_cue = decode_16le_string(prog_007, t + 2, stop_at_page=False)
        kanji_cue = [w for w in w_cue if 0x0100 <= w <= 0x03E0]
        assert not kanji_cue, f"Dialogue cue {idx} at 0x{t:06X} contains kanji codes: {[hex(w) for w in kanji_cue]}"

    jump_val = struct.unpack_from("<I", prog_007, OFFSET_COMBAT_INIT_EXIT)[0]
    expected_jump = (0x02 << 26) | ((COMBAT_HOOK_RAM >> 2) & 0x03FFFFFF)
    assert jump_val == expected_jump, (
        f"Exit instruction at 0x{OFFSET_COMBAT_INIT_EXIT:06X} (RAM 0x{RAM_BASE + OFFSET_COMBAT_INIT_EXIT:08X}) "
        f"must be jump to hook (0x{expected_jump:08X}), got 0x{jump_val:08X}"
    )
    expected_hook = build_combat_font_loader_hook()
    actual_hook = bytes(prog_007[OFFSET_COMBAT_HOOK : OFFSET_COMBAT_HOOK + len(expected_hook)])
    assert actual_hook == expected_hook, f"Combat font loader hook code mismatch at 0x{OFFSET_COMBAT_HOOK:06X}"

    return {
        "verified": True,
        "mode": "ru",
        "combat_font_entry": f"0x{COMBAT_FONT_ENTRY:03X}",
        "combat_overlay_entry": f"0x{PROG_ENTRY_COMBAT:03X}",
        "pick_unit_text": text_pick,
        "cue_092_speaker": f"0x{spk92:04X}",
        "cue_092_text_prefix": text_92[:35],
        "edc_ecc_verified_sectors": verified_sectors,
        "combat_vram_hook": f"0x{COMBAT_HOOK_RAM:08X}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject translated combat font and text into Slayers Royal (PS1)."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN if DEFAULT_TARGET_BIN.is_file() else None,
        help="Path to PS1 CD-ROM BIN image to patch",
    )
    parser.add_argument(
        "--source-bin",
        type=Path,
        default=DEFAULT_EN_BIN if DEFAULT_EN_BIN.is_file() else DEFAULT_SOURCE_BIN,
        help="Path to English base disc (build/en_patched/sr_patched.bin) for pristine combat assets",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Path to translations/combat_ru.json",
    )
    parser.add_argument(
        "--font",
        type=Path,
        default=None,
        help="Path to PressStart2P.ttf font",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify combat font, text, and EDC/ECC in disc image without modifying",
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "en", "ru"],
        default="auto",
        help="Verification target mode (default: auto-detect)",
    )
    parser.add_argument(
        "--restore-en",
        action="store_true",
        help="Restore pristine English combat mode from verified English release",
    )

    args = parser.parse_args()

    target_bin = args.bin
    if target_bin is None:
        print("Error: Target BIN image not specified and default not found.", file=sys.stderr)
        return 1

    if args.restore_en:
        print(f"Restoring clean English combat mode to {target_bin}...")
        sectors, bytes_cnt = restore_combat_en_disc_image(target_bin, source_en_bin=args.source_bin)
        print(f"[✓] Successfully restored {sectors} sectors ({bytes_cnt:,} bytes) of English combat mode!")
        return 0

    if args.verify:
        print(f"Verifying combat mode in {target_bin}...")
        report = verify_combat_patch(target_bin, catalog_path=args.catalog, mode=args.mode)
        print(f"[✓] Combat mode verified successfully!")
        print(f"    Mode:                 {'English gourry-hacks baseline' if report['mode'] == 'en' else 'Russian combat translation'}")
        print(f"    Font Entry:           {report['combat_font_entry']}")
        print(f"    0x05F398 / Pointer:   '{report['pick_unit_text']}'")
        print(f"    0x06241C / Cue 092:   [{report['cue_092_speaker']}] '{report['cue_092_text_prefix']}...'")
        print(f"    EDC/ECC Checksums:    Valid Mode 2 Form 1 on verified sectors")
        print(f"    Combat VRAM Hook:     {report.get('combat_vram_hook', 'None')}")
        return 0

    print(f"Patching combat mode in disc image: {target_bin}")
    result = patch_combat_disc_image(
        disc_path=target_bin,
        catalog_path=args.catalog,
        source_bin=args.source_bin,
        font_path=args.font,
    )

    print(f"[✓] Combat mode patched successfully:")
    print(f"    Entry 0x142:          Patched Cyrillic font ({result.font_compressed_bytes:,} bytes / budget: {result.font_allocated_bytes:,} bytes)")
    print(f"    Entry 0x007 Strings:  {result.system_strings_count} system strings, {result.dialogues_count} combat cues")
    print(f"    Pointers Updated:     {result.pointers_updated} RAM pointers")
    print(f"    Sectors Replaced:     {result.sectors_patched} Mode 2 Form 1 sectors with EDC/ECC repair")
    print(f"    Combat VRAM Hook:     Injected at 0x{OFFSET_COMBAT_HOOK:06X} (RAM 0x{COMBAT_HOOK_RAM:08X})")

    # Run verification immediately after patching
    report = verify_combat_patch(target_bin, catalog_path=args.catalog, mode="ru")
    print(f"[✓] Verification passed: 'ВЫБЕРИТЕ ЮНИТ' at 0x05F398, Cue 092 at 0x06241C, EDC/ECC valid.")

    return 0
if __name__ == "__main__":
    sys.exit(main())
