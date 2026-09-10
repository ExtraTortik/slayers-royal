#!/usr/bin/env python3
"""Patch town services, shop menus, and currency display for Slayers Royal (PS1).

This tool:
1. Reads Russian translations from translations/town_services_ru.json.
2. Patches PROG.UNT Entry 3 (LBA 229219, 296 sectors, RAM base 0x8004E5B0):
   - Tavern Food Menu ("СЫТНЫЙ ОБЕД", "ПЕРЕКУС", status messages).
   - Inn Lodging Menu ("ОТДЫХ ДО НОЧИ", "СОН ДО УТРА", Lina lines, 8-cue rejection scene).
   - Currency display: Neutralizes 'X' suffix at MIPS 0x0221F8 and sets coin headers.
   - Town system icons & help texts (EXIT, BUY, SELL, MOVE, INN, EAT, SETUP, SAVE, LOAD, ENTER).
   - Shop menus, prompts, and merchant negotiation dialogues.
3. Recalculates pointer tables dynamically in RAM:
   - Tavern pointer table at 0x02D524..0x02D52C.
   - Inn pointer table at 0x02DFD4..0x02DFDC.
   - System icons pointer table at 0x030F40..0x030F64.
   - Shop dialogue pointer tables at 0x031F14..0x031FDC and 0x0322B0..0x0322F0.
4. Renders and injects 4bpp composite currency tiles in PROG.UNT 0x03A:
   - 0x0242 / 0x0244: СЕР / ЕБРО ("СЕРЕБРО")
   - 0x024A / 0x024B: ЗОЛ / ОТО ("ЗОЛОТО")
   - 0x0254 / 0x0259: МЕД / Ь ("МЕДЬ")
   Updates both FONT_TIM_OFFSET and RAW_FONT_PIXEL_OFFSET.
5. Injects modified sectors into disc with Mode 2 Form 1 EDC/ECC repair.
6. Supports --dry-run, --verify, and --bin modes.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any, Mapping

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from patch_repo.localization.disc import (
    RAW_SECTOR_SIZE,
    USER_DATA_OFFSET,
    USER_DATA_SIZE,
    CdChecksums,
    read_extent,
    replace_extent_in_place,
)
from patch_repo.localization.glyphs import (
    FONT_PIXEL_OFFSET,
    FONT_PIXEL_SIZE,
    FONT_TIM_OFFSET,
    FONT_TIM_SIZE,
    RAW_FONT_PIXEL_OFFSET,
    glyph_xy,
)
try:
    from patch_repo.localization import unt_lz
except ImportError:
    from localization import unt_lz
from tools.patch_inspection import DEFAULT_CHARMAP

# Default paths
DEFAULT_CATALOG = REPO_ROOT / "translations" / "town_services_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"

# PROG.UNT and Entry 3 layout constants
PROG_LBA = 229020
ENTRY3_INDEX = 3
ENTRY3_LBA = 229219
ENTRY3_SECTORS = 296
ENTRY3_SIZE = ENTRY3_SECTORS * USER_DATA_SIZE  # 606,208 bytes
RAM_BASE = 0x8004E5B0


# Entry 0x03A (compressed runtime font TIM in PROG.UNT)
ENTRY_03A_INDEX = 0x03A
ENTRY_03A_SECTOR = 3061
ENTRY_03A_LBA = PROG_LBA + ENTRY_03A_SECTOR  # 232081
ENTRY_03A_SECTORS = 27
ENTRY_03A_SIZE = ENTRY_03A_SECTORS * USER_DATA_SIZE  # 55,296 bytes

# MIPS Menu Typography offsets in Entry 3
TAVERN_BOX_WIDTH_OFFSET = 0x017094   # addiu $v0, $zero, width  (2402XXXX)
TAVERN_BOX_X_OFFSET = 0x017088       # addiu $v0, $zero, x_off  (2402XXXX)
INN_BOX_WIDTH_OFFSET = 0x022880      # addiu $v1, $zero, width  (2403XXXX)
INN_BOX_X_OFFSET = 0x022874          # addiu $v1, $zero, x_off  (2403XXXX)
# MIPS Currency Suffix offsets in Entry 3
TAVERN_PRICE_SUFFIX_OFFSET = 0x0180B0 # addiu $v0, $zero, 0x007D (2402007D)
INN_PRICE_SUFFIX_OFFSET = 0x0221F8    # addiu $v0, $zero, 0x007D (2402007D)
# Control codes in Slayers Royal 16-bit script
DELIMITER = 0x00FF
CHAR_NEWLINE = 0x00FE
CHAR_PAGE_CONTINUE = 0x00FD

# Dynamic allocation start for strings relocated from original slots
DYNAMIC_ALLOC_START = 0x0327E0
DYNAMIC_ALLOC_LIMIT = 0x094000  # End of Entry 3 (397KB free space)

# 4bpp bitmap font glyph templates for 16x16 currency tiles (7px high, rows 4..10)
BITMAPS_4PX: dict[str, list[str]] = {
    "С": [".###", "#...", "#...", "#...", "#...", "#...", ".###"],
    "Е": ["####", "#...", "#...", "###.", "#...", "#...", "####"],
    "Р": ["###.", "#..#", "#..#", "###.", "#...", "#...", "#..."],
    "Б": ["####", "#...", "#...", "###.", "#..#", "#..#", "###."],
    "О": [".##.", "#..#", "#..#", "#..#", "#..#", "#..#", ".##."],
    "З": ["###.", "...#", "...#", ".##.", "...#", "...#", "###."],
    "Л": [".###", "#..#", "#..#", "#..#", "#..#", "#..#", "#..#"],
    "Т": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "М": ["#...#", "##.##", "#.#.#", "#...#", "#...#", "#...#", "#...#"],
    "Д": [".###.", ".#.#.", ".#.#.", ".#.#.", ".#.#.", "#####", "#...#"],
    "Ь": ["#...", "#...", "#...", "###.", "#..#", "#..#", "###."],
}

# 3-pixel wide compact font for 4-letter tile ("ЕБРО")
BITMAPS_3PX: dict[str, list[str]] = {
    "Е": ["###", "#..", "##.", "#..", "#..", "#..", "###"],
    "Б": ["###", "#..", "##.", "#.#", "#.#", "#.#", "##."],
    "Р": ["##.", "#.#", "#.#", "##.", "#..", "#..", "#.."],
    "О": ["###", "#.#", "#.#", "#.#", "#.#", "#.#", "###"],
}

# Currency glyph specification: glyph ID -> (characters, compact_flag)
CURRENCY_TILES_SPEC: dict[int, tuple[list[str], bool]] = {
    0x0242: (["С", "Е", "Р"], False),       # СЕР
    0x0244: (["Е", "Б", "Р", "О"], True),   # ЕБРО
    0x024A: (["З", "О", "Л"], False),       # ЗОЛ
    0x024B: (["О", "Т", "О"], False),       # ОТО
    0x0254: (["М", "Е", "Д"], False),       # МЕД
    0x0259: (["Ь"], False),                  # Ь
}

# Default layout for Russian currency composite tiles (pad_left per glyph)
DEFAULT_CURRENCY_TILES_LAYOUT: dict[int, dict[str, Any]] = {
    0x0242: {"pad_left": 1},
    0x0244: {"pad_left": 0},
    0x024A: {"pad_left": 2},
    0x024B: {"pad_left": 0},
    0x0254: {"pad_left": 0},
    0x0259: {"pad_left": 1},
}


def load_catalog(path: Path | str | None = None) -> dict[str, Any]:
    """Load town services translations JSON catalog."""
    p = Path(path) if path is not None else DEFAULT_CATALOG
    if not p.is_file():
        raise FileNotFoundError(f"Catalog file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def encode_string(
    text: str,
    charmap: Mapping[str, int] | None = None,
    terminator: int | None = DELIMITER,
    speaker_hex: str | int | None = None,
) -> bytes:
    """Encode a Unicode string into Slayers Royal 16-bit little-endian words.

    Supports:
    - speaker_hex prefix (e.g. '0x9101')
    - <XXXX> 4-hex word escapes (e.g. '<910B>', '<0001>')
    - \\n or newline character -> CHAR_NEWLINE (0x00FE)
    - \\p, \\f, or page break -> CHAR_PAGE_CONTINUE (0x00FD)
    - Unicode characters via charmap (DEFAULT_CHARMAP)
    - Optional terminator (default 0x00FF)
    """
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    words: list[int] = []

    if speaker_hex is not None:
        spk_val = int(speaker_hex, 16) if isinstance(speaker_hex, str) else int(speaker_hex)
        words.append(spk_val)

    i = 0
    n = len(text)
    while i < n:
        if text[i] == "<" and i + 5 < n and text[i + 5] == ">":
            hex_part = text[i + 1 : i + 5]
            try:
                words.append(int(hex_part, 16))
                i += 6
                continue
            except ValueError:
                pass

        if text[i : i + 2] == "\\n":
            words.append(CHAR_NEWLINE)
            i += 2
            continue
        if text[i : i + 2] == "\\p":
            words.append(CHAR_PAGE_CONTINUE)
            i += 2
            continue

        ch = text[i]
        if ch == "\n":
            words.append(CHAR_NEWLINE)
        elif ch in ("\f", "\r"):
            if ch == "\f":
                words.append(CHAR_PAGE_CONTINUE)
        elif ch in cm:
            words.append(cm[ch])
        else:
            raise KeyError(
                f"Character {ch!r} (U+{ord(ch):04X}) not found in charmap"
            )
        i += 1

    if terminator is not None:
        words.append(terminator)

    return struct.pack(f"<{len(words)}H", *words)


def encode_rejection_scene(
    cues: list[dict[str, Any]],
    charmap: Mapping[str, int] | None = None,
    max_bytes: int = 328,
) -> bytes:
    """Encode the 8-cue inn rejection dialogue stream into 16-bit words."""
    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    all_words: list[int] = []

    for idx, cue in enumerate(cues):
        spk_str = cue.get("speaker_hex") or cue.get("speaker") or "0x9101"
        spk_val = int(spk_str, 16) if isinstance(spk_str, str) else int(spk_str)
        all_words.append(spk_val)

        text = cue.get("ru") or cue.get("text") or ""
        i = 0
        n = len(text)
        while i < n:
            if text[i : i + 2] == "\\n":
                all_words.append(CHAR_NEWLINE)
                i += 2
                continue
            ch = text[i]
            if ch == "\n":
                all_words.append(CHAR_NEWLINE)
            elif ch in cm:
                all_words.append(cm[ch])
            else:
                raise KeyError(f"Character {ch!r} (U+{ord(ch):04X}) missing in charmap")
            i += 1

        delim = DELIMITER if idx == len(cues) - 1 else CHAR_PAGE_CONTINUE
        all_words.append(delim)

    raw = struct.pack(f"<{len(all_words)}H", *all_words)
    if len(raw) > max_bytes:
        raise ValueError(
            f"Rejection scene ({len(raw)} bytes) exceeds maximum budget of {max_bytes} bytes"
        )

    # Pad with 0x0000 up to max_bytes
    padded = raw + b"\x00" * (max_bytes - len(raw))
    return padded


def render_currency_tiles(
    layout_cfg: dict[str | int, Any] | None = None,
) -> dict[int, list[str]]:
    """Render 16x16 ASCII pixel art for all 6 Russian currency composite tiles.

    Returns dict mapping glyph ID to list of 16 string rows (16 characters each,
    '#' = foreground pixel, '.' = transparent).
    """
    if layout_cfg is None:
        try:
            cat = load_catalog()
            layout_cfg = cat.get("currency_tiles_layout") or cat.get("currency_config", {}).get("currency_tiles_layout")
        except Exception:
            layout_cfg = None

    tiles: dict[int, list[str]] = {}

    for gid, (letters, compact) in CURRENCY_TILES_SPEC.items():
        lines = [""] * 7
        for i, ch in enumerate(letters):
            bm = (BITMAPS_3PX if compact else BITMAPS_4PX)[ch]
            for r in range(7):
                if i > 0:
                    lines[r] += "."
                lines[r] += bm[r]

        tile_spec: dict[str, Any] = {}
        if isinstance(layout_cfg, dict):
            if gid in layout_cfg:
                tile_spec = layout_cfg[gid]
            elif f"0x{gid:04X}" in layout_cfg:
                tile_spec = layout_cfg[f"0x{gid:04X}"]
            elif f"0x{gid:04x}" in layout_cfg:
                tile_spec = layout_cfg[f"0x{gid:04x}"]
            elif f"0x{gid:X}" in layout_cfg:
                tile_spec = layout_cfg[f"0x{gid:X}"]
            elif f"0x{gid:x}" in layout_cfg:
                tile_spec = layout_cfg[f"0x{gid:x}"]
        if not tile_spec:
            tile_spec = DEFAULT_CURRENCY_TILES_LAYOUT.get(gid, {})

        out: list[str] = []
        for _ in range(4):
            out.append("." * 16)
        for r in range(7):
            w = len(lines[r])
            pad_l = tile_spec.get("pad_left")
            if pad_l is None:
                pad_l = max(0, (16 - w) // 2)
            pad_r = max(0, 16 - w - pad_l)
            out.append("." * pad_l + lines[r] + "." * pad_r)
        while len(out) < 16:
            out.append("." * 16)

        tiles[gid] = [row[:16] for row in out]

    return tiles


def set_font_pixel(buf: bytearray, x: int, y: int, val: int) -> None:
    """Set a 4bpp pixel value at (x, y) in font TIM buffer."""
    bo = FONT_PIXEL_OFFSET + y * 512 + x // 2
    if x & 1:
        buf[bo] = (buf[bo] & 0x0F) | ((val & 0x0F) << 4)
    else:
        buf[bo] = (buf[bo] & 0xF0) | (val & 0x0F)


def get_font_pixel(buf: bytearray | bytes, x: int, y: int) -> int:
    """Get a 4bpp pixel value at (x, y) from font TIM buffer."""
    bo = FONT_PIXEL_OFFSET + y * 512 + x // 2
    if x & 1:
        return (buf[bo] >> 4) & 0x0F
    else:
        return buf[bo] & 0x0F


_set_pixel = set_font_pixel
_get_pixel = get_font_pixel


def patch_entry_03a_currency_tiles(
    bin_path: Path | str,
    layout_cfg: dict[str | int, Any] | None = None,
) -> int:
    """Patch Russian currency composite tiles into compressed Entry 0x03A.
    Reads 27 sectors at PROG_LBA + 3061 (LBA 232081), decompresses with unt_lz.decompress,
    injects the 6 composite currency tiles (0x0242, 0x0244, 0x024A, 0x024B, 0x0254, 0x0259),
    recompresses with unt_lz.compress, pads to 27 sectors, and writes back to LBA 232081
    with replace_extent_in_place (Mode 2 Form 1 EDC/ECC repair).

    Returns the number of patched currency glyphs.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    extent = bytearray(read_extent(p, ENTRY_03A_LBA, ENTRY_03A_SIZE))
    decomp_bytes, _ = unt_lz.decompress(extent)
    tim = bytearray(decomp_bytes)

    tiles = render_currency_tiles(layout_cfg)
    for gid, rows in tiles.items():
        gx, gy = glyph_xy(gid)
        for py in range(16):
            row_str = rows[py]
            for px in range(16):
                val = 3 if row_str[px] == "#" else 0
                set_font_pixel(tim, gx + px, gy + py, val)

    compressed = unt_lz.compress(bytes(tim))
    if len(compressed) > ENTRY_03A_SIZE:
        raise ValueError(
            f"Compressed Entry 0x03A size ({len(compressed)} B) exceeds budget of "
            f"{ENTRY_03A_SIZE} B ({ENTRY_03A_SECTORS} sectors)"
        )

    packed = compressed.ljust(ENTRY_03A_SIZE, b"\x00")
    replace_extent_in_place(p, ENTRY_03A_LBA, packed)
    return len(tiles)

def patch_font_currency_tiles(
    bin_path: Path | str,
    layout_cfg: dict[str | int, Any] | None = None,
) -> int:
    """Patch Russian currency composite tiles into PROG.UNT runtime font TIM.

    Updates both FONT_TIM_OFFSET and RAW_FONT_PIXEL_OFFSET with EDC/ECC recalculation.
    Returns the number of patched currency glyphs.
    """
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    # 1. Read Font TIM from PROG.UNT
    sec_num = FONT_TIM_OFFSET // USER_DATA_SIZE
    sec_off = FONT_TIM_OFFSET % USER_DATA_SIZE
    num_secs = (sec_off + FONT_TIM_SIZE + USER_DATA_SIZE - 1) // USER_DATA_SIZE

    extent = bytearray(read_extent(p, PROG_LBA + sec_num, num_secs * USER_DATA_SIZE))
    tim = bytearray(extent[sec_off : sec_off + FONT_TIM_SIZE])

    changed_offsets: list[int] = []
    tiles = render_currency_tiles(layout_cfg)

    for gid, rows in tiles.items():
        gx, gy = glyph_xy(gid)
        for py in range(16):
            row_str = rows[py]
            for px in range(16):
                val = 3 if row_str[px] == "#" else 0
                bo = FONT_PIXEL_OFFSET + (gy + py) * 512 + (gx + px) // 2
                changed_offsets.append(bo)
                set_font_pixel(tim, gx + px, gy + py, val)

    extent[sec_off : sec_off + FONT_TIM_SIZE] = tim
    replace_extent_in_place(p, PROG_LBA + sec_num, bytes(extent))

    # 2. Update raw font pixel copy at RAW_FONT_PIXEL_OFFSET
    raw_sec_num = RAW_FONT_PIXEL_OFFSET // USER_DATA_SIZE
    raw_sec_off = RAW_FONT_PIXEL_OFFSET % USER_DATA_SIZE
    raw_num_secs = (raw_sec_off + FONT_PIXEL_SIZE + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    raw_extent = bytearray(read_extent(p, PROG_LBA + raw_sec_num, raw_num_secs * USER_DATA_SIZE))

    for bo in set(changed_offsets):
        target = raw_sec_off + (bo - FONT_PIXEL_OFFSET)
        raw_extent[target] = tim[bo]

    replace_extent_in_place(p, PROG_LBA + raw_sec_num, bytes(raw_extent))
    return len(tiles)


def patch_menu_typography(
    entry3_buf: bytearray,
    typography_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Patch tavern and inn menu box geometry in Entry 3 MIPS code.

    Offsets:
      - 0x017094: Tavern box width  (addiu $v0, $zero, width)    -> 2402XXXX
      - 0x017088: Tavern box X off  (addiu $v0, $zero, x_offset) -> 2402XXXX
      - 0x022880: Inn box width     (addiu $v1, $zero, width)    -> 2403XXXX
      - 0x022874: Inn box X off     (addiu $v1, $zero, x_offset) -> 2403XXXX
    """
    report: dict[str, Any] = {"modified_offsets": []}

    def _encode_addiu(reg: int, imm: int) -> bytes:
        return struct.pack("<hH", imm, 0x2400 | reg)

    if "tavern_box_width" in typography_cfg:
        width = int(typography_cfg["tavern_box_width"])
        entry3_buf[TAVERN_BOX_WIDTH_OFFSET : TAVERN_BOX_WIDTH_OFFSET + 4] = _encode_addiu(2, width)
        report["modified_offsets"].append(f"0x{TAVERN_BOX_WIDTH_OFFSET:06X}")
        report["tavern_box_width"] = width

    if "tavern_box_x_offset" in typography_cfg:
        x_off = int(typography_cfg["tavern_box_x_offset"])
        entry3_buf[TAVERN_BOX_X_OFFSET : TAVERN_BOX_X_OFFSET + 4] = _encode_addiu(2, x_off)
        report["modified_offsets"].append(f"0x{TAVERN_BOX_X_OFFSET:06X}")
        report["tavern_box_x_offset"] = x_off

    if "inn_box_width" in typography_cfg:
        width = int(typography_cfg["inn_box_width"])
        entry3_buf[INN_BOX_WIDTH_OFFSET : INN_BOX_WIDTH_OFFSET + 4] = _encode_addiu(3, width)
        report["modified_offsets"].append(f"0x{INN_BOX_WIDTH_OFFSET:06X}")
        report["inn_box_width"] = width

    if "inn_box_x_offset" in typography_cfg:
        x_off = int(typography_cfg["inn_box_x_offset"])
        entry3_buf[INN_BOX_X_OFFSET : INN_BOX_X_OFFSET + 4] = _encode_addiu(3, x_off)
        report["modified_offsets"].append(f"0x{INN_BOX_X_OFFSET:06X}")
        report["inn_box_x_offset"] = x_off

    return report

def patch_entry3_buffer(
    entry3_buf: bytearray,
    catalog: dict[str, Any],
    charmap: Mapping[str, int] | None = None,
) -> tuple[bytearray, dict[str, Any]]:
    """Patch PROG.UNT Entry 3 user data in-place in memory.

    Recalculates all RAM pointers dynamically: RAM_address = 0x8004E5B0 + offset.
    Returns (patched_buf, report_dict).
    """
    if len(entry3_buf) != ENTRY3_SIZE:
        raise ValueError(
            f"Entry 3 buffer must be exactly {ENTRY3_SIZE} bytes (got {len(entry3_buf)})"
        )

    cm = charmap if charmap is not None else DEFAULT_CHARMAP
    buf = bytearray(entry3_buf)
    dyn_alloc = DYNAMIC_ALLOC_START
    report: dict[str, Any] = {
        "modified_offsets": [],
        "pointer_updates": {},
        "string_allocations": {},
    }

    # 1. Neutralize MIPS currency suffix instructions at 0x0180B0 (tavern) and 0x0221F8 (inn/shops)
    curr_cfg = catalog.get("currency_config", {})
    suffix_offsets = {TAVERN_PRICE_SUFFIX_OFFSET, INN_PRICE_SUFFIX_OFFSET}
    if "suffix_patches" in curr_cfg:
        for sp_item in curr_cfg["suffix_patches"].values():
            suffix_offsets.add(int(sp_item["offset_hex"], 16))
    if "mips_suffix_patches" in curr_cfg:
        msp = curr_cfg["mips_suffix_patches"]
        if isinstance(msp, dict):
            for sp_item in msp.values():
                suffix_offsets.add(int(sp_item["offset_hex"], 16))
        elif isinstance(msp, list):
            for sp_item in msp:
                suffix_offsets.add(int(sp_item["offset_hex"] if isinstance(sp_item, dict) else sp_item, 16))
    if "mips_suffix_patch" in curr_cfg:
        suffix_offsets.add(int(curr_cfg["mips_suffix_patch"].get("offset_hex", "0x0221F8"), 16))

    for s_off in sorted(suffix_offsets):
        # li $v0, 0x007D (' ' space in Slayers Royal charmap) -> MIPS little-endian: 7D 00 02 24
        buf[s_off : s_off + 4] = bytes.fromhex("7d000224")
        report["modified_offsets"].append(f"0x{s_off:06X}")
    # 2. Patch Currency Headers at 0x00BC8, 0x00BD0, 0x00BD8
    headers = curr_cfg.get("headers", {})
    for cur_key, cur_data in headers.items():
        hdr_off = int(cur_data["offset_hex"], 16)
        tiles = [int(x, 16) for x in cur_data["composite_tiles"]]
        hdr_payload = struct.pack("<3H", tiles[0], tiles[1], DELIMITER)
        buf[hdr_off : hdr_off + 6] = hdr_payload
        report["modified_offsets"].append(f"0x{hdr_off:06X}")

    # 3. Patch Tavern Food Menu & Statuses
    t_cfg = catalog.get("tavern_services", {})
    # Option 1: Full Meal
    fm_text = t_cfg["full_meal"]["ru"]
    fm_bytes = encode_string(fm_text, cm)
    fm_off = int(t_cfg["full_meal"]["offset_hex"], 16)
    fm_max = t_cfg["full_meal"].get("max_bytes", len(fm_bytes))
    if len(fm_bytes) > fm_max:
        raise ValueError(f"full_meal ({len(fm_bytes)}B) exceeds budget of {fm_max}B")
    padded_fm = fm_bytes + b"\x00" * (fm_max - len(fm_bytes))
    buf[fm_off : fm_off + fm_max] = padded_fm
    fm_ptr_off = int(t_cfg["full_meal"]["pointer_offset_hex"], 16)
    fm_ptr_val = RAM_BASE + fm_off
    buf[fm_ptr_off : fm_ptr_off + 4] = struct.pack("<I", fm_ptr_val)
    report["pointer_updates"][f"0x{fm_ptr_off:06X}"] = f"0x{fm_ptr_val:08X}"
    report["string_allocations"]["full_meal"] = (fm_off, len(fm_bytes))

    # Option 2: Snack
    sn_text = t_cfg["snack"]["ru"]
    sn_bytes = encode_string(sn_text, cm)
    # If full meal took > 20 bytes (0x14), snack must relocate to 0x02D510
    sn_off = int(t_cfg["snack"].get("offset_hex", "0x02D510"), 16)
    buf[sn_off : sn_off + len(sn_bytes)] = sn_bytes
    sn_ptr_off = int(t_cfg["snack"]["pointer_offset_hex"], 16)
    sn_ptr_val = RAM_BASE + sn_off
    buf[sn_ptr_off : sn_ptr_off + 4] = struct.pack("<I", sn_ptr_val)
    report["pointer_updates"][f"0x{sn_ptr_off:06X}"] = f"0x{sn_ptr_val:08X}"
    report["string_allocations"]["snack"] = (sn_off, len(sn_bytes))

    # Tavern Status 1: Insufficient money
    nm_cfg = t_cfg["status_no_money"]
    nm_bytes = encode_string(
        nm_cfg["ru"], cm, speaker_hex=nm_cfg.get("speaker_code_hex")
    )
    nm_off = int(nm_cfg["offset_hex"], 16)
    nm_max = nm_cfg["max_bytes"]
    if len(nm_bytes) > nm_max:
        raise ValueError(f"status_no_money ({len(nm_bytes)}B) exceeds budget of {nm_max}B")
    padded_nm = nm_bytes + b"\x00" * (nm_max - len(nm_bytes))
    buf[nm_off : nm_off + nm_max] = padded_nm
    report["string_allocations"]["status_no_money"] = (nm_off, len(nm_bytes))

    # Tavern Status 2: Already ate
    ja_cfg = t_cfg["status_just_ate"]
    ja_bytes = encode_string(
        ja_cfg["ru"], cm, speaker_hex=ja_cfg.get("speaker_code_hex")
    )
    ja_off = int(ja_cfg["offset_hex"], 16)
    ja_max = ja_cfg["max_bytes"]
    if len(ja_bytes) > ja_max:
        raise ValueError(f"status_just_ate ({len(ja_bytes)}B) exceeds budget of {ja_max}B")
    padded_ja = ja_bytes + b"\x00" * (ja_max - len(ja_bytes))
    buf[ja_off : ja_off + ja_max] = padded_ja
    report["string_allocations"]["status_just_ate"] = (ja_off, len(ja_bytes))

    # 4. Patch Inn Lodging Menu & Dialogue
    i_cfg = catalog.get("inn_services", {})
    # Inn Option 1: Rest until night
    rn_bytes = encode_string(i_cfg["rest_night"]["ru"], cm)
    rn_off = int(i_cfg["rest_night"]["offset_hex"], 16)
    buf[rn_off : rn_off + len(rn_bytes)] = rn_bytes
    rn_ptr_off = int(i_cfg["rest_night"]["pointer_offset_hex"], 16)
    rn_ptr_val = RAM_BASE + rn_off
    buf[rn_ptr_off : rn_ptr_off + 4] = struct.pack("<I", rn_ptr_val)
    report["pointer_updates"][f"0x{rn_ptr_off:06X}"] = f"0x{rn_ptr_val:08X}"
    report["string_allocations"]["rest_night"] = (rn_off, len(rn_bytes))

    # Inn Option 2: Sleep until morning
    sm_bytes = encode_string(i_cfg["sleep_morning"]["ru"], cm)
    sm_off = int(i_cfg["sleep_morning"]["offset_hex"], 16)
    buf[sm_off : sm_off + len(sm_bytes)] = sm_bytes
    sm_ptr_off = int(i_cfg["sleep_morning"]["pointer_offset_hex"], 16)
    sm_ptr_val = RAM_BASE + sm_off
    buf[sm_ptr_off : sm_ptr_off + 4] = struct.pack("<I", sm_ptr_val)
    report["pointer_updates"][f"0x{sm_ptr_off:06X}"] = f"0x{sm_ptr_val:08X}"
    report["string_allocations"]["sleep_morning"] = (sm_off, len(sm_bytes))

    # Inn Lina Line 1 (rest night)
    drn_cfg = i_cfg["dialogue_rest_night"]
    drn_bytes = encode_string(drn_cfg["ru"], cm)
    drn_off = int(drn_cfg["offset_hex"], 16)
    drn_max = drn_cfg["max_bytes"]
    if len(drn_bytes) > drn_max:
        raise ValueError(f"dialogue_rest_night ({len(drn_bytes)}B) exceeds budget of {drn_max}B")
    padded_drn = drn_bytes + b"\x00" * (drn_max - len(drn_bytes))
    buf[drn_off : drn_off + drn_max] = padded_drn
    report["string_allocations"]["dialogue_rest_night"] = (drn_off, len(drn_bytes))

    # Inn Lina Line 2 (sleep morning)
    dsm_cfg = i_cfg["dialogue_sleep_morning"]
    dsm_bytes = encode_string(dsm_cfg["ru"], cm)
    dsm_off = int(dsm_cfg["offset_hex"], 16)
    dsm_max = dsm_cfg["max_bytes"]
    if len(dsm_bytes) > dsm_max:
        raise ValueError(f"dialogue_sleep_morning ({len(dsm_bytes)}B) exceeds budget of {dsm_max}B")
    padded_dsm = dsm_bytes + b"\x00" * (dsm_max - len(dsm_bytes))
    buf[dsm_off : dsm_off + dsm_max] = padded_dsm
    report["string_allocations"]["dialogue_sleep_morning"] = (dsm_off, len(dsm_bytes))

    # Inn Rejection Scene
    rej_cfg = i_cfg["rejection_scene"]
    rej_bytes = encode_rejection_scene(rej_cfg["dialogue_cues"], cm, rej_cfg["max_bytes"])
    rej_off = int(rej_cfg["offset_hex"], 16)
    buf[rej_off : rej_off + len(rej_bytes)] = rej_bytes
    report["string_allocations"]["rejection_scene"] = (rej_off, len(rej_bytes))

    # 5. Patch Town System Icons & Help Texts (0x030BD8..0x030F20)
    sys_cfg = catalog.get("town_system_icons", {})
    pack_region = sys_cfg.get("pack_region", {})
    pack_start = int(pack_region.get("start_offset_hex", "0x030BD8"), 16)
    pack_limit = int(pack_region.get("end_offset_hex", "0x030F20"), 16)

    cur_pack_off = pack_start
    icons = sys_cfg.get("icons", {})
    for icon_name, icon_data in icons.items():
        text_raw = encode_string(icon_data["ru"], cm)
        if cur_pack_off % 2 != 0:
            cur_pack_off += 1
        slot_start = cur_pack_off
        cur_pack_off += len(text_raw)
        if cur_pack_off > pack_limit:
            raise ValueError(
                f"System icon '{icon_name}' overflows pack region: "
                f"offset 0x{cur_pack_off:06X} > limit 0x{pack_limit:06X}"
            )
        buf[slot_start:cur_pack_off] = text_raw

        ptr_off = int(icon_data["ptr_hex"], 16)
        ptr_val = RAM_BASE + slot_start
        buf[ptr_off : ptr_off + 4] = struct.pack("<I", ptr_val)
        report["pointer_updates"][f"0x{ptr_off:06X}"] = f"0x{ptr_val:08X}"
        report["string_allocations"][f"icon_{icon_name}"] = (slot_start, len(text_raw))

    # 6. Patch Shop Menus, Prompts, and Merchant Dialogues
    shop_cfg = catalog.get("shop_dialogue", {})
    for item_name, s_data in shop_cfg.items():
        text_raw = encode_string(s_data["ru"], cm)
        max_b = s_data.get("max_bytes", len(text_raw))
        base_off = int(s_data["offset_hex"], 16)

        if len(text_raw) <= max_b:
            actual_off = base_off
            padded = text_raw + b"\x00" * (max_b - len(text_raw))
            buf[actual_off : actual_off + max_b] = padded
        else:
            # Allocate dynamically into free space pool
            if dyn_alloc % 2 != 0:
                dyn_alloc += 1
            actual_off = dyn_alloc
            dyn_alloc += len(text_raw)
            if dyn_alloc > DYNAMIC_ALLOC_LIMIT:
                raise ValueError(
                    f"Dynamic allocation overflow: 0x{dyn_alloc:06X} > 0x{DYNAMIC_ALLOC_LIMIT:06X}"
                )
            buf[actual_off:dyn_alloc] = text_raw

        # Update all 32-bit pointers referencing this string
        if "pointer_offsets_hex" in s_data:
            ptr_val = RAM_BASE + actual_off
            for p_hex in s_data["pointer_offsets_hex"]:
                p_off = int(p_hex, 16)
                buf[p_off : p_off + 4] = struct.pack("<I", ptr_val)
                report["pointer_updates"][f"0x{p_off:06X}"] = f"0x{ptr_val:08X}"

        report["string_allocations"][item_name] = (actual_off, len(text_raw))


    # 7. Patch Menu Typography (Tavern and Inn box width and X offset)
    typo_cfg = catalog.get("menu_typography")
    if typo_cfg:
        typo_report = patch_menu_typography(buf, typo_cfg)
        report["menu_typography"] = typo_report
        report["modified_offsets"].extend(typo_report.get("modified_offsets", []))
    return buf, report


def patch_town_services(
    bin_path: Path | str,
    catalog_path: Path | str | None = None,
    dry_run: bool = False,
    patch_font: bool = True,
) -> dict[str, Any]:
    """Patch town services, menus, and currency in disc image."""
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    catalog = load_catalog(catalog_path)

    # 1. Read Entry 3 from disc
    entry3_orig = read_extent(p, ENTRY3_LBA, ENTRY3_SIZE)
    patched_entry3, report = patch_entry3_buffer(bytearray(entry3_orig), catalog)

    diff_bytes = sum(1 for a, b in zip(entry3_orig, patched_entry3) if a != b)
    report["diff_bytes"] = diff_bytes
    report["dry_run"] = dry_run

    if not dry_run:
        # Write modified Entry 3 with Mode 2 Form 1 EDC/ECC repair
        replace_extent_in_place(p, ENTRY3_LBA, bytes(patched_entry3))

        # Patch Font TIM currency tiles and Entry 0x03A compressed tiles
        if patch_font:
            layout_cfg = catalog.get("currency_tiles_layout") or catalog.get("currency_config", {}).get("currency_tiles_layout")
            patched_03a = patch_entry_03a_currency_tiles(p, layout_cfg=layout_cfg)
            patched_glyphs = patch_font_currency_tiles(p, layout_cfg=layout_cfg)
            report["patched_03a_glyphs"] = patched_03a
            report["patched_glyphs"] = patched_glyphs
    return report


def verify_town_services(
    bin_path: Path | str,
    catalog_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify binary integrity, pointers, strings, and EDC/ECC on disc image."""
    p = Path(bin_path)
    if not p.is_file():
        raise FileNotFoundError(f"BIN image not found: {p}")

    catalog = load_catalog(catalog_path)
    entry3 = read_extent(p, ENTRY3_LBA, ENTRY3_SIZE)

    # 1. Verify MIPS currency suffix neutralization (0x0180B0 tavern, 0x0221F8 inn/shops)
    suffix_offsets = {TAVERN_PRICE_SUFFIX_OFFSET, INN_PRICE_SUFFIX_OFFSET}
    curr_cfg = catalog.get("currency_config", {})
    if "suffix_patches" in curr_cfg:
        for sp_item in curr_cfg["suffix_patches"].values():
            suffix_offsets.add(int(sp_item["offset_hex"], 16))
    if "mips_suffix_patches" in curr_cfg:
        msp = curr_cfg["mips_suffix_patches"]
        if isinstance(msp, dict):
            for sp_item in msp.values():
                suffix_offsets.add(int(sp_item["offset_hex"], 16))
        elif isinstance(msp, list):
            for sp_item in msp:
                suffix_offsets.add(int(sp_item["offset_hex"] if isinstance(sp_item, dict) else sp_item, 16))
    if "mips_suffix_patch" in curr_cfg:
        suffix_offsets.add(int(curr_cfg["mips_suffix_patch"].get("offset_hex", "0x0221F8"), 16))

    expected_mips = bytes.fromhex("7d000224")  # li $v0, 0x007D
    for s_off in sorted(suffix_offsets):
        mips_bytes = entry3[s_off : s_off + 4]
        if mips_bytes != expected_mips:
            raise AssertionError(
                f"MIPS currency suffix at 0x{s_off:06X} mismatch: "
                f"found {mips_bytes.hex()}, expected {expected_mips.hex()}"
            )
    # 2. Verify Tavern pointers
    t_cfg = catalog["tavern_services"]
    fm_ptr_off = int(t_cfg["full_meal"]["pointer_offset_hex"], 16)
    sn_ptr_off = int(t_cfg["snack"]["pointer_offset_hex"], 16)
    fm_ptr = struct.unpack("<I", entry3[fm_ptr_off : fm_ptr_off + 4])[0]
    sn_ptr = struct.unpack("<I", entry3[sn_ptr_off : sn_ptr_off + 4])[0]
    expected_fm_ptr = RAM_BASE + int(t_cfg["full_meal"]["offset_hex"], 16)
    expected_sn_ptr = RAM_BASE + int(t_cfg["snack"]["offset_hex"], 16)
    assert fm_ptr == expected_fm_ptr, f"Full meal ptr mismatch: 0x{fm_ptr:08X} != 0x{expected_fm_ptr:08X}"
    assert sn_ptr == expected_sn_ptr, f"Snack ptr mismatch: 0x{sn_ptr:08X} != 0x{expected_sn_ptr:08X}"

    # 3. Verify Inn pointers
    i_cfg = catalog["inn_services"]
    rn_ptr_off = int(i_cfg["rest_night"]["pointer_offset_hex"], 16)
    sm_ptr_off = int(i_cfg["sleep_morning"]["pointer_offset_hex"], 16)
    rn_ptr = struct.unpack("<I", entry3[rn_ptr_off : rn_ptr_off + 4])[0]
    sm_ptr = struct.unpack("<I", entry3[sm_ptr_off : sm_ptr_off + 4])[0]
    expected_rn_ptr = RAM_BASE + int(i_cfg["rest_night"]["offset_hex"], 16)
    expected_sm_ptr = RAM_BASE + int(i_cfg["sleep_morning"]["offset_hex"], 16)
    assert rn_ptr == expected_rn_ptr, f"Rest night ptr mismatch: 0x{rn_ptr:08X} != 0x{expected_rn_ptr:08X}"
    assert sm_ptr == expected_sm_ptr, f"Sleep morning ptr mismatch: 0x{sm_ptr:08X} != 0x{expected_sm_ptr:08X}"

    # 4. Verify System Icons pointers
    sys_cfg = catalog["town_system_icons"]
    for icon_name, icon_data in sys_cfg["icons"].items():
        ptr_off = int(icon_data["ptr_hex"], 16)
        ptr_val = struct.unpack("<I", entry3[ptr_off : ptr_off + 4])[0]
        rel_off = ptr_val - RAM_BASE
        assert 0x030BD8 <= rel_off <= 0x030F20, (
            f"System icon '{icon_name}' pointer out of bounds: 0x{ptr_val:08X} (rel 0x{rel_off:06X})"
        )


    # 5. Verify Menu Typography MIPS instructions
    if "menu_typography" in catalog:
        typo_cfg = catalog["menu_typography"]

        def _encode_addiu(reg: int, imm: int) -> bytes:
            return struct.pack("<hH", imm, 0x2400 | reg)

        if "tavern_box_width" in typo_cfg:
            expected = _encode_addiu(2, int(typo_cfg["tavern_box_width"]))
            actual = entry3[TAVERN_BOX_WIDTH_OFFSET : TAVERN_BOX_WIDTH_OFFSET + 4]
            assert actual == expected, (
                f"Tavern box width MIPS at 0x{TAVERN_BOX_WIDTH_OFFSET:06X} mismatch: "
                f"found {actual.hex()}, expected {expected.hex()}"
            )
        if "tavern_box_x_offset" in typo_cfg:
            expected = _encode_addiu(2, int(typo_cfg["tavern_box_x_offset"]))
            actual = entry3[TAVERN_BOX_X_OFFSET : TAVERN_BOX_X_OFFSET + 4]
            assert actual == expected, (
                f"Tavern box X offset MIPS at 0x{TAVERN_BOX_X_OFFSET:06X} mismatch: "
                f"found {actual.hex()}, expected {expected.hex()}"
            )
        if "inn_box_width" in typo_cfg:
            expected = _encode_addiu(3, int(typo_cfg["inn_box_width"]))
            actual = entry3[INN_BOX_WIDTH_OFFSET : INN_BOX_WIDTH_OFFSET + 4]
            assert actual == expected, (
                f"Inn box width MIPS at 0x{INN_BOX_WIDTH_OFFSET:06X} mismatch: "
                f"found {actual.hex()}, expected {expected.hex()}"
            )
        if "inn_box_x_offset" in typo_cfg:
            expected = _encode_addiu(3, int(typo_cfg["inn_box_x_offset"]))
            actual = entry3[INN_BOX_X_OFFSET : INN_BOX_X_OFFSET + 4]
            assert actual == expected, (
                f"Inn box X offset MIPS at 0x{INN_BOX_X_OFFSET:06X} mismatch: "
                f"found {actual.hex()}, expected {expected.hex()}"
            )
    # 6. Verify EDC/ECC checksums for all 296 sectors of Entry 3
    checksums = CdChecksums()
    verified_sectors = 0
    with p.open("rb") as f:
        for i in range(ENTRY3_SECTORS):
            lba = ENTRY3_LBA + i
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            edc_ok = sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818])
            ecc_p_ok = sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            ecc_q_ok = sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            if not (edc_ok and ecc_p_ok and ecc_q_ok):
                raise AssertionError(f"Invalid EDC/ECC checksum at LBA {lba}")
            verified_sectors += 1

    # 7. Verify Entry 0x03A decompressed currency tiles and EDC/ECC
    extent_03a = read_extent(p, ENTRY_03A_LBA, ENTRY_03A_SIZE)
    decomp_03a, _ = unt_lz.decompress(extent_03a)
    layout_cfg = catalog.get("currency_tiles_layout") or catalog.get("currency_config", {}).get("currency_tiles_layout")
    tiles = render_currency_tiles(layout_cfg)
    for gid in (0x0242, 0x0244, 0x024A, 0x024B, 0x0254, 0x0259):
        gx, gy = glyph_xy(gid)
        expected_rows = tiles[gid]
        for py in range(16):
            expected_row = expected_rows[py]
            for px in range(16):
                expected_val = 3 if expected_row[px] == "#" else 0
                actual_val = get_font_pixel(decomp_03a, gx + px, gy + py)
                assert actual_val == expected_val, (
                    f"Entry 0x03A glyph 0x{gid:04X} pixel mismatch at ({px}, {py}): "
                    f"expected {expected_val}, got {actual_val}"
                )

    verified_03a_sectors = 0
    with p.open("rb") as f:
        for i in range(ENTRY_03A_SECTORS):
            lba = ENTRY_03A_LBA + i
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            edc_ok = sec[0x818:0x81C] == checksums.compute_edc(sec[0x10:0x818])
            ecc_p_ok = sec[0x81C:0x8C8] == checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            ecc_q_ok = sec[0x8C8:0x930] == checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            if not (edc_ok and ecc_p_ok and ecc_q_ok):
                raise AssertionError(f"Invalid EDC/ECC checksum at LBA {lba} (Entry 0x03A)")
            verified_03a_sectors += 1

    return {
        "verified_sectors": verified_sectors,
        "entry3_sectors": ENTRY3_SECTORS,
        "verified_03a_sectors": verified_03a_sectors,
        "entry_03a_sectors": ENTRY_03A_SECTORS,
        "status": "valid",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch town services, menus, and currency display for Slayers Royal (PS1)"
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN,
        help=f"Target PS1 BIN disc image (default: {DEFAULT_TARGET_BIN})",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Town services translations catalog JSON (default: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate patching in memory without writing to disc",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify binary integrity, pointers, and EDC/ECC checksums on disc image",
    )
    parser.add_argument(
        "--no-font",
        action="store_true",
        help="Skip font tile atlas patching in 0x03A",
    )

    args = parser.parse_args()

    if args.verify:
        print(f"[*] Verifying town services on {args.bin}...")
        res = verify_town_services(args.bin, args.catalog)
        print(
            f"[✓] Verification SUCCESSFUL! Verified {res['verified_sectors']} Entry 3 sectors "
            f"and {res['verified_03a_sectors']} Entry 0x03A sectors (100% valid EDC/ECC)."
        )
        return 0

    mode_str = "DRY-RUN simulation" if args.dry_run else "disc image"
    print(f"[*] Patching town services into {mode_str} {args.bin}...")
    report = patch_town_services(
        bin_path=args.bin,
        catalog_path=args.catalog,
        dry_run=args.dry_run,
        patch_font=not args.no_font,
    )

    print(f"[✓] Successfully patched town services! Modified bytes: {report['diff_bytes']}")
    print(f"    Pointer updates applied: {len(report['pointer_updates'])}")
    print(f"    String allocations: {len(report['string_allocations'])}")
    if not args.dry_run and not args.no_font:
        print(f"    Currency composite tiles patched in font 0x03A: {report.get('patched_03a_glyphs', report.get('patched_glyphs', 0))}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
