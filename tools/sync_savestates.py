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
    decode_string as decode_inspection_string,
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


PROG_LBA = 229020
SEC1606_LBA = PROG_LBA + 1606  # 230626
SEC1607_LBA = PROG_LBA + 1607  # 230627
SEC1606_RAM_BASE = 0x800805B0
SEC1607_RAM_BASE = 0x80080DB0
SEC1606_RAM_OFFSET = 0x0805B0
SEC1607_RAM_OFFSET = 0x080DB0
ENTRY_160_LBA = 239352
ENTRY_160_BUDGET = 14336
DATE_WIDGET_X = 176
DATE_WIDGET_Y = 32
DATE_WIDGET_WIDTH = 56
DATE_WIDGET_HEIGHT = 40
VRAM_SCANLINE_BYTES = 2048

FALLBACK_OLD_DATE_WIDGET_ROWS: list[bytes] = [
    bytes.fromhex("00001e1e1e1e1e1e1e1e1e1e0e0e0e0e0e0e0e1b1b1b1b1b1b1b1b1b1b0e1b0e1b0e1b0e1b0e1b1e1e1e1e1e1b0e0e1b1e1e1e1e1e1e0000"),
    bytes.fromhex("001b1e1b1e0e0e0e0e0e0e1b1e1b0e0e0e0e0e1a1a0e0e0e0e0e0e0e1e0e0e0e0e0e0e0e1e1b1e1b1e1e1a1a1a1a1a1a1b1e1b1e1b1e1b00"),
    bytes.fromhex("1b1a1a1d1d0e3f3f3f3f0e0e1e0e0e3f3f3f0e0e1e0e3f3f3f3f3f0e1d0e3f3f3f3f3f0e1d1d1d1d1a1e1e1e1e1e1a1a1d1d1d1d1d1d1b1b"),
    bytes.fromhex("1e1e1e1e1e0e3f0e0e0e3f0e1d0e3f0e0e0e3f0e1a0e0e0e3f0e0e0e1e0e3f0e0e0e0e0e1a1d1d1d1d1d1d1a1a1e1e1e1e1e1e1e1e1a1d1d"),
    bytes.fromhex("1a1a1a1a1e0e3f0e0e0e3f0e1b0e3f0e0e0e3f0e1a1a1a0e3f0e1a1a1a0e3f3f3f3f0e1b1b1b1b1b1b1a1a1a1a1a1a1a1a1a1a1e1b1b1b1b"),
    bytes.fromhex("1a1a1a1a1a0e3f0e0e0e3f0e1a0e3f3f3f3f3f0e1b1b1b0e3f0e1b1b1b0e3f0e0e0e0e0e1a1a1a1e1b1b1b1b1b1b1b1b1b1e1e1a1a1a1a1a"),
    bytes.fromhex("1b1b1b1b1b0e3f3f3f3f0e0e1e0e3f0e0e0e3f0e1e1e1e0e3f0e1e1b1b0e3f3f3f3f3f0e1b1b1e1e1e1e1e1e1e1e1e1b1b1b1b1b1b1b1b1b"),
    bytes.fromhex("001e1e1e1e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e1b1b0e0e0e1e1e1e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e1b1b1e1e1e1e1e1e1e1e1e00"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b1b1b1b0e1b1b1b0e1b0e0e0e0e0e0e0e0e0e0e1b1b1b1b1b1b1b1b1b0e1b0e0e0e0e0e0e0e0e0e1b0e1b1b0000"),
    bytes.fromhex("0000000e0e0e0e0e0e0e0e747474747474747474747474747474747474747474747474747474747474747474740e0e0e0e0e0e0e0e000000"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e0e0e1b1e1e1e1e1e1e0000"),
    bytes.fromhex("001b1e1b1e1b1e1b1e1b1e7410101010101010101010101010101010101010101010101010101010101010100e1a1a1a1b1e1b1e1b1e1b00"),
    bytes.fromhex("1b1a1a1d1d1d1d1d1d1a1a7410101010101010101010101010101010101010101010101010101010101010100e1e1a1a1d1d1d1d1d1d1b1b"),
    bytes.fromhex("1e1e1e1e1e1e1e1a1d1d1d7410101010101010101010101010101010101010101010101010101010101010100e1e1e1e1e1e1e1e1e1a1d1d"),
    bytes.fromhex("1a1a1a1a1e1e1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e1a1a1a1a1a1a1e1b1b1b1b"),
    bytes.fromhex("1a1a1a1a1a1a1a1a1a1a1a7410101010101010101010101010101010101010101010101010101010101010100e1b1b1b1b1e1e1a1a1a1a1a"),
    bytes.fromhex("1b1b1b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e1e1e1b1b1b1b1b1b1b1b1b"),
    bytes.fromhex("001e1e1e1e1e1e1e1b0e0e7410101010101010101010101010101010101010101010101010101010101010100e1b1e1e1e1e1e1e1e1e1e00"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e0e0e0e0e0e1b0e1b1b0000"),
    bytes.fromhex("0000000e0e0e0e0e0e0e0e7410101010101010101010101010101010101010101010101010101010101010100e0e0e0e0e0e0e0e0e000000"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e0e0e1b1e1e1e1e1e1e0000"),
    bytes.fromhex("001b1e1b1e1b1e1b1e1b1e7410101010101010101010101010101010101010101010101010101010101010100e1a1a1a1b1e1b1e1b1e1b00"),
    bytes.fromhex("1b1a1a1d1d1d1d1d1d1a1a7410101010101010101010101010101010101010101010101010101010101010100e1e1a1a1d1d1d1d1d1d1b1b"),
    bytes.fromhex("1e1e1e1e1e1e1e1a1d1d1d7410101010101010101010101010101010101010101010101010101010101010100e1e1e1e1e1e1e1e1e1a1d1d"),
    bytes.fromhex("1a1a1a1a1e1e1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e1a1a1a1a1a1a1e1b1b1b1b"),
    bytes.fromhex("1a1a1a1a1a1a1a1a1a1a1a7410101010101010101010101010101010101010101010101010101010101010100e1b1b1b1b1e1e1a1a1a1a1a"),
    bytes.fromhex("1b1b1b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e1e1e1b1b1b1b1b1b1b1b1b"),
    bytes.fromhex("001e1e1e1e1e1e1e1b0e0e7410101010101010101010101010101010101010101010101010101010101010100e1b1e1e1e1e1e1e1e1e1e00"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b7410101010101010101010101010101010101010101010101010101010101010100e0e0e0e0e0e1b0e1b1b0000"),
    bytes.fromhex("0000000e0e0e0e0e0e0e0e740e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e000000"),
    bytes.fromhex("00001e1e1e1e1e1e1e1e1e1e0e0e0e0e0e0e0e1b1b1b1b1b1b1b1b1b1b0e1b0e1b0e1b0e1b0e1b1e1e1e1e1e1b0e0e1b1e1e1e1e1e1e0000"),
    bytes.fromhex("001b1e1b1e1b1e1b1e1b1e1b1e1b1a1a1a1a1a1a1a1a1a1a1a1a1a1b1e1b1e1b1e1b1e1b1e1b1e1b1e1e1a1a1a1a1a1a1b1e1b1e1b1e1b00"),
    bytes.fromhex("1b1a1a1d1d1d1d1d1d1a1a1e1e1e1e1e1e1e1e1e1e1e1a1a1a1d1d1d1d1d1d1d1d1d1d1d1d1d1d1d1a1e1e1e1e1e1a1a1d1d1d1d1d1d1b1b"),
    bytes.fromhex("1e1e1e1e1e1e1e1a1d1d1d1d1d1d1d1d1d1d1d1a1a1e1e1e1e1e1e1e1e1e1e1e1e1e1e1a1a1d1d1d1d1d1d1a1a1e1e1e1e1e1e1e1e1a1d1d"),
    bytes.fromhex("1a1a1a1a1e1e1b1b1b1b1b1b1b1b1b1b1b1b1e1e1a1a1a1a1a1a1a1a1a1a1a1a1a1a1b1b1b1b1b1b1b1a1a1a1a1a1a1a1a1a1a1e1b1b1b1b"),
    bytes.fromhex("1a1a1a1a1a1a1a1a1a1a1a1a1a1a1e1e1e1b1b1b1b1b1b1b1b1b1b1b1b1e1b1e1e1a1a1a1a1a1a1e1b1b1b1b1b1b1b1b1b1e1e1a1a1a1a1a"),
    bytes.fromhex("1b1b1b1b1b1b1b1b1b1b1b1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1e1b1b1b1b1b1b1b1b1b1b1b1e1e1e1e1e1e1e1e1e1b1b1b1b1b1b1b1b1b"),
    bytes.fromhex("001e1e1e1e1e1e1e1b0e0e0e0e0e0e0e0e0e0e0e0e1b1b1e1b1e1e1e1e1e1e1e1e1e1b1b0e0e0e0e0e0e0e0e1b1b1e1e1e1e1e1e1e1e1e00"),
    bytes.fromhex("00001b1b1b1b1b1b1b1b1b1b1b1b0e1b1b1b0e1b0e0e0e0e0e0e0e0e0e0e1b1b1b1b1b1b1b1b1b0e1b0e0e0e0e0e0e0e0e0e1b0e1b1b0000"),
    bytes.fromhex("0000000e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e0e000000"),
]

def extract_date_widget_rows_from_tim(tim_bytes: bytes) -> list[bytes]:
    """Extract 40 rows of 56 bytes for DATE widget at (176, 32) from 256x256 8bpp TIM."""
    rows = []
    for y in range(DATE_WIDGET_HEIGHT):
        offset = 544 + (DATE_WIDGET_Y + y) * 256 + DATE_WIDGET_X
        rows.append(tim_bytes[offset : offset + DATE_WIDGET_WIDTH])
    return rows


def get_hud_widget_rows(bin_path: Path | str = DEFAULT_BIN) -> tuple[list[bytes], list[bytes]]:
    """Return (old_widget_rows, new_widget_rows) for Entry 160 DATE widget."""
    bp = Path(bin_path)
    new_rows: list[bytes] = []
    old_rows: list[bytes] = list(FALLBACK_OLD_DATE_WIDGET_ROWS)

    try:
        from localization import unt_lz
    except ImportError:
        from patch_repo.localization import unt_lz

    # Extract new widget rows from bin_path if available
    if bp.is_file() and bp.stat().st_size >= (ENTRY_160_LBA + 7) * 2352:
        try:
            raw = read_extent(bp, ENTRY_160_LBA, ENTRY_160_BUDGET)
            decomp, _ = unt_lz.decompress(raw)
            if len(decomp) == 66080:
                new_rows = extract_date_widget_rows_from_tim(decomp)
        except Exception:
            pass

    # Try candidate pristine discs for old_rows
    for cand in (
        REPO_ROOT / "downloads" / "sr.bin",
        REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
    ):
        if cand.is_file() and cand.stat().st_size >= (ENTRY_160_LBA + 7) * 2352:
            try:
                raw = read_extent(cand, ENTRY_160_LBA, ENTRY_160_BUDGET)
                decomp, _ = unt_lz.decompress(raw)
                if len(decomp) == 66080:
                    old_rows = extract_date_widget_rows_from_tim(decomp)
                    break
            except Exception:
                continue

    return old_rows, new_rows


def sync_hud_vram_in_payload(
    decomp: bytearray,
    old_rows: list[bytes],
    new_rows: list[bytes],
) -> bool:
    """Find and replace 56x40 DATE widget rows in DuckStation VRAM payload.

    Verifies that all 40 rows match with VRAM scanline stride 2048 bytes before replacing.
    """
    if not old_rows or not new_rows or len(old_rows) != len(new_rows):
        return False

    first_row = old_rows[0]
    pos = decomp.find(first_row)
    while pos != -1:
        if all(
            decomp[pos + y * VRAM_SCANLINE_BYTES : pos + y * VRAM_SCANLINE_BYTES + len(old_rows[y])] == old_rows[y]
            for y in range(len(old_rows))
        ):
            for y in range(len(new_rows)):
                r = new_rows[y]
                decomp[pos + y * VRAM_SCANLINE_BYTES : pos + y * VRAM_SCANLINE_BYTES + len(r)] = r
            return True
        pos = decomp.find(first_row, pos + 1)
    return False


def sync_all_hud_savestates(
    bin_path: Path | str = DEFAULT_BIN,
    savestates_dir: Path | str = DEFAULT_SAVESTATES_DIR,
    dry_run: bool = False,
    backup: bool = True,
) -> list[dict[str, Any]]:
    """Synchronize Entry 160 DATE widget in VRAM across all DuckStation savestates."""
    sd = Path(savestates_dir)
    if not sd.is_dir():
        return []

    old_rows, new_rows = get_hud_widget_rows(bin_path)
    if not new_rows:
        return []

    reports = []
    sav_files = sorted(sd.glob("SLPS-01363_*.sav"))
    for sav_path in sav_files:
        data = sav_path.read_bytes()
        magics = find_zstd_magic_offsets(data)
        if not magics:
            continue
        stream_offset = magics[1] if len(magics) >= 2 else magics[0]
        try:
            decomp = bytearray(decompress_zstd(data[stream_offset:]))
        except Exception:
            continue

        updated = sync_hud_vram_in_payload(decomp, old_rows, new_rows)
        rep: dict[str, Any] = {
            "path": str(sav_path),
            "name": sav_path.name,
            "hud_vram_updated": updated,
        }
        if updated and not dry_run:
            if backup:
                bak_path = sav_path.with_suffix(".sav.bak")
                if not bak_path.is_file():
                    shutil.copy2(sav_path, bak_path)
            recompressed = compress_zstd(bytes(decomp), level=3)
            sav_path.write_bytes(data[:stream_offset] + recompressed)
            rep["status"] = "updated"
        elif updated and dry_run:
            rep["status"] = "dry_run"
        else:
            rep["status"] = "already_synced_or_absent"
        reports.append(rep)

    return reports

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


def find_ram_offset(decompressed: bytes, entry3_header: bytes | None = None) -> int | None:
    """Find the byte offset where PS1 2MB RAM (0x80000000) begins in the decompressed savestate payload."""
    sys_pos = decompressed.find(b"\x06\x00\x00\x00System")
    if sys_pos != -1 and sys_pos + 0x1A62 + 0x200000 <= len(decompressed):
        return sys_pos + 0x1A62

    if entry3_header:
        e3_pos = find_entry3_in_payload(decompressed, entry3_header)
        if e3_pos is not None and e3_pos >= 0x04E5B0:
            return e3_pos - 0x04E5B0

    if 0x1A62 + 0x200000 <= len(decompressed):
        return 0x1A62

    return None


def is_world_map_in_payload(decomp: bytes, ram_offset: int) -> bool:
    """Check if Sector 1606 / World Map is currently loaded in RAM."""
    sec1606_start = ram_offset + SEC1606_RAM_OFFSET
    if sec1606_start + USER_DATA_SIZE > len(decomp):
        return False

    # Check 1: Encoded "ЛЕЙК" at 0x150 (Russian banner for Lakewood)
    if decomp[sec1606_start + 0x150 : sec1606_start + 0x158] == b"\x12\x00\x0c\x00\x10\x00\x11\x00":
        return True

    # Check 2: Pointer table at 0x0388 (RAM 0x80080938) pointing to Sector 1606 (0x80080700)
    ptr_val = struct.unpack_from("<I", decomp, sec1606_start + 0x0388)[0]
    if ptr_val == 0x80080700 or (0x800805B0 <= ptr_val < 0x80080DB0):
        return True

    return False
def build_room_lookup_to_ru(room_names_doc: dict[str, Any]) -> dict[str, str]:
    """Build mapping from any known room name (JP, EN, or legacy RU) to canonical Russian name."""
    lookup: dict[str, str] = {}
    for e_key, e_val in room_names_doc.items():
        if isinstance(e_val, dict):
            ru = e_val.get("name_ru") or e_val.get("russian") or e_val.get("ru")
            en = e_val.get("name_en")
            jp = e_val.get("name_jp")
            if ru:
                lookup[ru] = ru
                if en:
                    lookup[en] = ru
                if jp:
                    lookup[jp] = ru
    # Also handle previous long Russian translations that needed shortening
    legacy_ru_shorten = {
        'З. ЛЕС БАРКЛЕНДА': 'З.БАРКЛЕНД',
        'В. ЛЕС БАРКЛЕНДА': 'В.БАРКЛЕНД',
        'Ю. ЛЕС БАРКЛЕНДА': 'Ю.БАРКЛЕНД',
        'С. ЛЕС ИЗЕЛЬСЕНА': 'С.ИЗЕЛЬСЕН',
        'ГРАНИЦА РАЛЬТИГА': 'ГР.РАЛЬТИГ',
        'ГРАНИЦА СЕЙРУНА': 'ГР.СЕЙРУН',
        'С. ЛЕС КЬЮЗАКА': 'С. КЬЮЗАК',
        'ЗАКОУЛКИ СОНИИ': 'ОБХОД',
        'ЗАМОК ЛЕЗАРИАМ': 'ЛЕЗАРИАМ',
        'СТАРЫЙ ОСОБНЯК': 'ОСОБНЯК',
        'ЛОГОВО ГАЛЕФА': 'ДОМ ГАЛЕФА',
        'ЗАПАД КЬЮЗАКА': 'З. КЬЮЗАК',
        'КОРИДОР ЗАМКА': 'КОРИДОР',
        'ГИЛЬДИЯ МАГОВ': 'ГИЛЬДИЯ',
        'ТЁМНЫЙ ОТЕЛЬ': 'НОЧЛЕЖКА',
        'СОКРОВИЩНИЦА': 'СОКРОВИЩА',
        'В. ГРАМСТОК': 'В.ГРАМСТОК',
        'ТРАКТ СОНИИ': 'ТРАКТ',
        'С. ТУР-СИТИ': 'С.ТУР-СИТИ',
        'КАНАЛИЗАЦИЯ': 'КОЛЛЕКТОР',
        'ГЛАВНЫЙ ЗАЛ': 'ЗАЛ',
    }
    lookup.update(legacy_ru_shorten)
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
    rev_cm = {v: k for k, v in cm.items()}
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
                txt_ru = decode_inspection_string(words, rev_cm)
                ru_text = room_lookup.get(txt_en) or room_lookup.get(txt_jp) or room_lookup.get(txt_ru)
                if ru_text and ru_text != txt_ru:
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
    entry3_disc: bytes | None = None,
    dry_run: bool = False,
    backup: bool = True,
    sec1606_disc: bytes | None = None,
    sec1607_disc: bytes | None = None,
    bin_path: Path | str = DEFAULT_BIN,
    old_widget_rows: list[bytes] | None = None,
    new_widget_rows: list[bytes] | None = None,
) -> dict[str, Any]:
    """Synchronize a single DuckStation .sav file with patched Entry 3, World Map, and HUD VRAM."""
    result: dict[str, Any] = {
        "path": str(sav_path),
        "name": sav_path.name,
        "status": "skipped",
        "entry3_found": False,
        "entry3_offset": None,
        "had_old_greeting": False,
        "has_new_greeting": False,
        "sec1606_updated": False,
        "hud_vram_updated": False,
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

    bp = Path(bin_path)
    if entry3_disc is None and bp.is_file():
        entry3_disc = read_extent(bp, ENTRY3_LBA, ENTRY3_SIZE)
    if sec1606_disc is None and bp.is_file():
        sec1606_disc = read_extent(bp, SEC1606_LBA, USER_DATA_SIZE)
    if sec1607_disc is None and bp.is_file():
        sec1607_disc = read_extent(bp, SEC1607_LBA, USER_DATA_SIZE)

    entry3_header = entry3_disc[:16] if entry3_disc else None
    entry3_start = find_entry3_in_payload(decomp, entry3_header) if entry3_header else None

    # Locate RAM in savestate payload
    ram_offset = find_ram_offset(decomp, entry3_header)

    # Also synchronize room names
    cm = load_charmap()
    rn_doc = load_room_names()
    room_lookup = build_room_lookup_to_ru(rn_doc)
    room_updates = sync_room_names_in_payload(decomp, room_lookup, cm)
    result["room_updates"] = room_updates

    # Synchronize Sector 1606 and Sector 1607 (World Map) if present in RAM
    sec1606_updated = False
    if ram_offset is not None and sec1606_disc is not None and sec1607_disc is not None:
        if is_world_map_in_payload(decomp, ram_offset):
            sec1606_start = ram_offset + SEC1606_RAM_OFFSET
            sec1607_start = ram_offset + SEC1607_RAM_OFFSET
            decomp[sec1606_start : sec1606_start + USER_DATA_SIZE] = sec1606_disc
            decomp[sec1607_start : sec1607_start + USER_DATA_SIZE] = sec1607_disc
            sec1606_updated = True
            result["sec1606_offset"] = hex(sec1606_start)
            result["sec1607_offset"] = hex(sec1607_start)
    result["sec1606_updated"] = sec1606_updated

    # Synchronize HUD DATE widget in VRAM if widget rows are provided
    hud_vram_updated = False
    if old_widget_rows and new_widget_rows:
        hud_vram_updated = sync_hud_vram_in_payload(decomp, old_widget_rows, new_widget_rows)
    result["hud_vram_updated"] = hud_vram_updated

    if entry3_start is None and not room_updates and not sec1606_updated and not hud_vram_updated:
        result["status"] = "not_loaded"
        result["message"] = "Neither Entry 3, active room, World Map, nor HUD VRAM in RAM/VRAM"
        return result
    if entry3_start is not None and entry3_disc is not None:
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


sync_savestate = sync_single_savestate


def verify_savestates(
    savestates_dir: Path,
    entry3_disc: bytes | None = None,
    sec1606_disc: bytes | None = None,
    sec1607_disc: bytes | None = None,
    bin_path: Path | str = DEFAULT_BIN,
) -> list[dict[str, Any]]:
    """Verify that all savestates in directory contain correct dialogue bytes and world map data."""
    reports = []
    bp = Path(bin_path)
    if entry3_disc is None and bp.is_file():
        entry3_disc = read_extent(bp, ENTRY3_LBA, ENTRY3_SIZE)
    if sec1606_disc is None and bp.is_file():
        sec1606_disc = read_extent(bp, SEC1606_LBA, USER_DATA_SIZE)
    if sec1607_disc is None and bp.is_file():
        sec1607_disc = read_extent(bp, SEC1607_LBA, USER_DATA_SIZE)

    entry3_header = entry3_disc[:16] if entry3_disc else None

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
        entry3_start = find_entry3_in_payload(decomp, entry3_header) if entry3_header else None

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
            for idx, exp_names in [
                (0, ("Лина",)),
                (7, ("Ф.Атк",)),
                (32, ("Меч Света", "МечСвета")),
                (36, ("Длинный меч", "Длин.меч")),
                (47, ("Короткий меч", "Кор.меч")),
            ]:
                p_off = table0_start + idx * 4
                ptr_val = struct.unpack("<I", decomp[p_off : p_off + 4])[0]
                rel_item = ptr_val - RAM_BASE
                it_text = decode_string(decomp[entry3_start + rel_item : entry3_start + rel_item + 48])
                sample_items.append((idx, it_text, it_text in exp_names))

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
            roff = find_ram_offset(decomp, entry3_header)
            if roff is not None and is_world_map_in_payload(decomp, roff):
                rep["world_map_loaded"] = True
                sec1606_ram = roff + SEC1606_RAM_OFFSET
                sec1607_ram = roff + SEC1607_RAM_OFFSET
                rep["sec1606_offset"] = hex(sec1606_ram)
                rep["sec1607_offset"] = hex(sec1607_ram)
                sec1606_ok = (decomp[sec1606_ram : sec1606_ram + USER_DATA_SIZE] == sec1606_disc) if sec1606_disc else True
                sec1607_ok = (decomp[sec1607_ram : sec1607_ram + USER_DATA_SIZE] == sec1607_disc) if sec1607_disc else True
                rep["sec1606_match"] = sec1606_ok
                rep["sec1607_match"] = sec1607_ok
                rep["valid"] = sec1606_ok and sec1607_ok
            else:
                rep["world_map_loaded"] = False
                rep["valid"] = True  # Not in town or world map, will load cleanly from disc

        reports.append(rep)
    return reports


def sync_all_savestates(
    bin_path: Path | str = DEFAULT_BIN,
    savestates_dir: Path | str = DEFAULT_SAVESTATES_DIR,
    dry_run: bool = False,
    backup: bool = True,
) -> list[dict[str, Any]]:
    """Synchronize all DuckStation savestates with patched Entry 3 and World Map."""
    bp = Path(bin_path)
    if not bp.is_file():
        raise FileNotFoundError(f"Patched disc image not found: {bp}")

    sd = Path(savestates_dir)
    if not sd.is_dir():
        raise FileNotFoundError(f"Savestates directory not found: {sd}")

    # Read patched extents directly from disc image
    entry3_disc = read_extent(bp, ENTRY3_LBA, ENTRY3_SIZE)
    sec1606_disc = read_extent(bp, SEC1606_LBA, USER_DATA_SIZE)
    sec1607_disc = read_extent(bp, SEC1607_LBA, USER_DATA_SIZE)
    old_widget_rows, new_widget_rows = get_hud_widget_rows(bp)

    sav_files = sorted(sd.glob("SLPS-01363_*.sav"))
    if not sav_files:
        print(f"[*] No SLPS-01363 savestate files found in {sd}")
        return []

    reports = []
    for sav_path in sav_files:
        rep = sync_single_savestate(
            sav_path,
            entry3_disc=entry3_disc,
            dry_run=dry_run,
            backup=backup,
            sec1606_disc=sec1606_disc,
            sec1607_disc=sec1607_disc,
            bin_path=bp,
            old_widget_rows=old_widget_rows,
            new_widget_rows=new_widget_rows,
        )
        reports.append(rep)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize DuckStation savestates with patched PROG.UNT Entry 3 and World Map (Slayers Royal PS1)"
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
    sec1606_disc = read_extent(args.bin, SEC1606_LBA, USER_DATA_SIZE)
    sec1607_disc = read_extent(args.bin, SEC1607_LBA, USER_DATA_SIZE)

    if args.verify:
        print(f"[*] Verifying savestates in {args.savestates_dir}...")
        v_reps = verify_savestates(
            args.savestates_dir,
            entry3_disc=entry3_disc,
            sec1606_disc=sec1606_disc,
            sec1607_disc=sec1607_disc,
            bin_path=args.bin,
        )
        all_ok = True
        for r in v_reps:
            status_str = "[OK]" if r.get("valid") else "[FAIL]"
            if r.get("entry3_loaded"):
                print(f"  {status_str} {r['name']}: Entry 3 @ {r['entry3_offset']}, greeting: {r.get('greeting_text')!r}")
            elif r.get("world_map_loaded"):
                m_str = "in sync with disc" if r.get("sec1606_match") and r.get("sec1607_match") else "out of sync with disc"
                print(f"  {status_str} {r['name']}: World Map (Sectors 1606 & 1607) {m_str} @ {r.get('sec1606_offset')}")
            else:
                print(f"  {status_str} {r['name']}: Neither Entry 3 nor World Map loaded")
            if not r.get("valid"):
                all_ok = False

        if all_ok:
            print("[✓] All savestates VERIFIED! Zero mojibake detected.")
            return 0
        else:
            print("[X] Verification failed: some savestates still contain old mojibake or out-of-sync sectors.")
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
            if r.get("entry3_found"):
                print(f"  [✓] {r['name']}: Entry 3 patched at {r['entry3_offset']}{had_str}")
            if r.get("sec1606_updated"):
                print(f"  [✓] {r['name']}: World Map (Sectors 1606 & 1607) patched at {r.get('sec1606_offset')}")
            if r.get("room_updates"):
                print(f"  [✓] {r['name']}: Room names patched ({len(r['room_updates'])} updates)")
            updated_count += 1
            if r.get("hud_vram_updated"):
                print(f"  [✓] {r['name']}: HUD DATE widget VRAM synchronized")
        elif r.get("status") in ("not_loaded", "entry3_not_loaded"):
            print(f"  [-] {r['name']}: {r.get('message')}")
        else:
            print(f"  [!] {r['name']}: {r.get('error', r.get('status'))}")

    print(f"\n[✓] Synchronization finished! Patched {updated_count} savestate(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
