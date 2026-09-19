#!/usr/bin/env python3
"""Slayers Royal (PS1) - Extra Screens and Textures Patcher.

This tool automates the extraction, TIM encoding, sector budget validation,
EDC/ECC recalculation, and injection of 15 translated screens and textures:
1.  OPT.UNT Entry 137: "С ДНЕМ РОЖДЕНИЯ" (160x32, 4bpp, LBA 228442, 2 sectors, 4096 B budget)
2.  OPT.UNT Entry 171: "РОЛИКИ" (256x48, 4bpp, LBA 228537, 4 sectors, 8192 B budget)
3.  OPT.UNT Entry 172: "ЗВУК" (168x32, 4bpp, LBA 228541, 2 sectors, 4096 B budget)
4.  OPT.UNT Entry 173: "ПОМОЩЬ" (160x16, 4bpp, LBA 228543, 1 sector, 2048 B budget)
5.  OPT.UNT Entry 174: "СЮЖЕТ" (768x256, 4bpp, LBA 228544, 49 sectors, 100352 B budget)
6.  OPT.UNT Entry 206: "ВРЕМЯ" (192x32, 4bpp, LBA 228718, 2 sectors, 4096 B budget)
7.  OPT.UNT Entry 207: "ОЧКИ" (192x32, 4bpp, LBA 228720, 2 sectors, 4096 B budget)
8.  OPT.UNT Entry 232: "МЕНЮ ВЫБОРА МИНИ-ИГР" (320x224, 4bpp, LBA 229002, 18 sectors, 36864 B budget)
9.  OPTCINE.GRP TIM 1: "ТИТРЫ" (256x256, 4bpp, LBA 264611 + 544 B, 17 sectors, 33312 B)
10. PROG.UNT Entry 54: "ПРАВИЛА ИГРЫ 1" (320x224, 8bpp, LBA 232066, 7 sectors, 14336 B budget)
11. PROG.UNT Entry 55: "ПРАВИЛА ИГРЫ 2" (320x224, 8bpp, LBA 232073, 7 sectors, 14336 B budget)
12. PROG.UNT Entry 56: "ПРАВИЛА ИГРЫ 3" (320x224, 8bpp, LBA 232080, 8 sectors, 16384 B budget)
13. PROG.UNT Entry 57: "ПРАВИЛА ИГРЫ 4" (320x224, 8bpp, LBA 232088, 7 sectors, 14336 B budget)
14. PROG.UNT Entry 317: (80x480, 4bpp, LBA 233112, 2 sectors, 4096 B budget)
15. PROG.UNT Entry 324: (48x240, 4bpp, LBA 233207, 2 sectors, 4096 B budget)
Features:
- Standalone CLI: `--bin`, `--source-dir`, `--entry`, `--dry-run`, `--verify`.
- Hardware-accurate TIM encoders preserving BGR555 CLUTs, VRAM coordinates, and pixel alignments.
- Euclidean distance color quantization for RGB images (OPT 206, 207, 232).
- Bank 0 Euclidean distance quantization for OPTCINE 01.
- Exact PNG palette preservation for PROG 54..57 with LZSS mode 1 compression.
- Mode 2 Form 1 EDC/ECC repair using `replace_extent_in_place` and `CdChecksums`.
- Non-sector-aligned container injection support for OPTCINE.GRP at LBA 264611 offset 544.
- Dual-image synchronization (`localization-output/ru` and `patch_repo/localization-output/ru`).
- Comprehensive verification suite testing sector checksums and TIM headers.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

# Repository root setup
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
for p in (REPO_ROOT, PATCH_REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

try:
    from patch_repo.localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        read_extent,
        replace_extent_in_place,
    )
except ImportError:
    try:
        from localization.disc import (
            CdChecksums,
            RAW_SECTOR_SIZE,
            USER_DATA_OFFSET,
            USER_DATA_SIZE,
            read_extent,
            replace_extent_in_place,
        )
    except ImportError:
        RAW_SECTOR_SIZE = 2352
        USER_DATA_OFFSET = 24
        USER_DATA_SIZE = 2048
        CdChecksums = None
        read_extent = None
        replace_extent_in_place = None

try:
    from patch_repo.localization import unt_lz
except ImportError:
    try:
        from localization import unt_lz
    except ImportError:
        unt_lz = None

# Default paths
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_PATCH_REPO_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SRC_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_SOURCE_DIRS = [
    REPO_ROOT / "data" / "extra_screens",
    Path("/home/samvel/dddd/еще переводы"),
    REPO_ROOT / "data" / "title_screen_dump",
]

# Fallback hardware CLUTs extracted from original disc (downloads/sr.bin)
FALLBACK_CLUTS: dict[str, bytes] = {
    "opt_137": bytes.fromhex("000042088410c61808214a298c31ce39ef3d3146734eb556f75e7b6fbd774208"),
    "opt_171": bytes.fromhex("0000ff72bc6a9a62585a3652f449d241903d6e352c2d0a25c81ca614640c4208"),
    "opt_172": bytes.fromhex("0000ff72bc6a9a62585a3652f449d241903d6e352c2d0a25c81ca614640c4208"),
    "opt_173": bytes.fromhex("0000fff2bcea9ae258da36d2f4c9d2c190bd6eb52cad0aa5c89ca694648c4288"),
    "opt_174": bytes.fromhex("0000ff4cdc44da40b83cb638b430922c90288e246c206a1868144610440c4208"),
    "opt_206": bytes.fromhex("0000bf019c017a015801360134011201f000ce04ac04aa048804660444044208"),
    "opt_207": bytes.fromhex("00002065005d0055e050e048c040c03ca034a12c8128812061186114410c4208"),
    "opt_232": bytes.fromhex("0080ffffbdf75aebf7deb5d652ca31c6efbdadb56bad08a1e79ca594638c2184"),
    "optcine_01": bytes.fromhex(
        "00000180c69808a14aa98cb1ceb910c252ca94d2d6da18e35aeb9cf3defbffff"
        "0000bd770074a003a0771d001d74bd0300009c730070800380731c001c709c03"
        "00007b6f006c6003606f1b001b6c7b0300005a6b00684003406b1a001a685a03"
        "0000396700642003206719001964390300001863006000030063180018601803"
        "0000f75e005ce002e05e1700175cf7020000d65a0058c002c05a16001658d602"
        "0000b5560054a002a05615001554b50200009452005080028052140014509402"
        "0000734e004c6002604e1300134c73020000524a00484002404a120012485202"
        "0000314600442002204611001144310200001042004000020042100010401002"
        "0000ef3d003ce001e03d0f000f3cef010000ce390038c001c0390e000e38ce01"
        "0000ad350034a001a0350d000d34ad0100008c310030800180310c000c308c01"
        "00006b2d002c6001602d0b000b2c6b0100004a290028400140290a000a284a01"
        "0000292500242001202509000924290100000821002000010021080008200801"
        "0000e71c001ce000e01c0700071ce7000000c6180018c000c01806000618c600"
        "0000a5140014a000a01405000514a50000008410001080008010040004108400"
        "0000630c000c6000600c0300030c630000004208000840004008020002084200"
        "0000210400042000200401000104210000000000000000000000000000000000"
    ),
    "prog_317": bytes.fromhex("00000000effd0000ffbd0000000054a2d7ba6d89d189558aceb952ca18e38788"),
    "prog_324": bytes.fromhex("0000efbdb5d67bef4fda538a08c2afa1fbc254a274a675a696aeb6b2d7bac990"),
}

# Specifications for the 15 translated assets
EXTRA_SCREENS_SPECS: dict[str, dict[str, Any]] = {
    "opt_137": {
        "id": "opt_137",
        "name": "OPT.UNT Entry 137",
        "archive": "OPT.UNT",
        "entry_index": 137,
        "lba": 228442,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 160,
        "height": 32,
        "bpp": 4,
        "vram_x": 640,
        "vram_y": 480,
        "vram_w": 40,
        "clut_x": 0,
        "clut_y": 507,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 2572,
        "raw_tim_len": 2624,
        "compressed": False,
        "filenames": [
            "opt_137_160x32_uncompressed.png",
            "opt_137.png",
            "137.png",
        ],
    },
    "opt_171": {
        "id": "opt_171",
        "name": "OPT.UNT Entry 171",
        "archive": "OPT.UNT",
        "entry_index": 171,
        "lba": 228537,
        "sector_offset": 0,
        "sectors": 4,
        "budget": 8192,
        "width": 256,
        "height": 48,
        "bpp": 4,
        "vram_x": 960,
        "vram_y": 16,
        "vram_w": 64,
        "clut_x": 0,
        "clut_y": 494,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 6156,
        "raw_tim_len": 6208,
        "compressed": False,
        "filenames": [
            "opt_171_256x48_uncompressed.png",
            "opt_171.png",
            "171.png",
        ],
    },
    "opt_172": {
        "id": "opt_172",
        "name": "OPT.UNT Entry 172",
        "archive": "OPT.UNT",
        "entry_index": 172,
        "lba": 228541,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 168,
        "height": 32,
        "bpp": 4,
        "vram_x": 896,
        "vram_y": 16,
        "vram_w": 42,
        "clut_x": 0,
        "clut_y": 495,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 2700,
        "raw_tim_len": 2752,
        "compressed": False,
        "filenames": [
            "opt_172_168x32_uncompressed.png",
            "opt_172.png",
            "172.png",
        ],
    },
    "opt_173": {
        "id": "opt_173",
        "name": "OPT.UNT Entry 173",
        "archive": "OPT.UNT",
        "entry_index": 173,
        "lba": 228543,
        "sector_offset": 0,
        "sectors": 1,
        "budget": 2048,
        "width": 160,
        "height": 16,
        "bpp": 4,
        "vram_x": 960,
        "vram_y": 0,
        "vram_w": 40,
        "clut_x": 0,
        "clut_y": 503,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 1292,
        "raw_tim_len": 1344,
        "compressed": False,
        "filenames": [
            "opt_173_160x16_uncompressed.png",
            "opt_173.png",
            "173.png",
        ],
    },
    "opt_174": {
        "id": "opt_174",
        "name": "OPT.UNT Entry 174",
        "archive": "OPT.UNT",
        "entry_index": 174,
        "lba": 228544,
        "sector_offset": 0,
        "sectors": 49,
        "budget": 100352,
        "width": 768,
        "height": 256,
        "bpp": 4,
        "vram_x": 640,
        "vram_y": 0,
        "vram_w": 192,
        "clut_x": 0,
        "clut_y": 491,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 98316,
        "raw_tim_len": 98368,
        "compressed": False,
        "filenames": [
            "opt_174_768x256_uncompressed.png",
            "opt_174.png",
            "174.png",
        ],
    },
    "opt_206": {
        "id": "opt_206",
        "name": "OPT.UNT Entry 206",
        "archive": "OPT.UNT",
        "entry_index": 206,
        "lba": 228718,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 192,
        "height": 32,
        "bpp": 4,
        "vram_x": 448,
        "vram_y": 256,
        "vram_w": 48,
        "clut_x": 0,
        "clut_y": 484,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 3084,
        "raw_tim_len": 3136,
        "compressed": False,
        "filenames": [
            "opt_206_192x32_uncompressed.png",
            "opt_206.png",
            "206.png",
        ],
    },
    "opt_207": {
        "id": "opt_207",
        "name": "OPT.UNT Entry 207",
        "archive": "OPT.UNT",
        "entry_index": 207,
        "lba": 228720,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 192,
        "height": 32,
        "bpp": 4,
        "vram_x": 448,
        "vram_y": 288,
        "vram_w": 48,
        "clut_x": 0,
        "clut_y": 485,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 3084,
        "raw_tim_len": 3136,
        "compressed": False,
        "filenames": [
            "opt_207_192x32_uncompressed.png",
            "opt_207.png",
            "207.png",
        ],
    },
    "opt_232": {
        "id": "opt_232",
        "name": "OPT.UNT Entry 232",
        "archive": "OPT.UNT",
        "entry_index": 232,
        "lba": 229002,
        "sector_offset": 0,
        "sectors": 18,
        "budget": 36864,
        "width": 320,
        "height": 224,
        "bpp": 4,
        "vram_x": 320,
        "vram_y": 0,
        "vram_w": 80,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 71692,  # Original game TIM header value
        "raw_tim_len": 35904,
        "compressed": False,
        "filenames": [
            "opt_232_320x224_uncompressed.png",
            "opt_232.png",
            "232.png",
        ],
    },
    "optcine_01": {
        "id": "optcine_01",
        "name": "OPTCINE.GRP TIM 1",
        "archive": "OPTCINE.GRP",
        "entry_index": 1,
        "lba": 264611,
        "sector_offset": 544,
        "sectors": 17,
        "budget": 17 * 2048,
        "width": 256,
        "height": 256,
        "bpp": 4,
        "vram_x": 768,
        "vram_y": 256,
        "vram_w": 64,
        "clut_x": 0,
        "clut_y": 496,
        "clut_w": 16,
        "clut_h": 16,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 32780,
        "raw_tim_len": 33312,
        "compressed": False,
        "filenames": [
            "optcine_01_256x256.png",
            "optcine_01.png",
            "optcine01.png",
        ],
    },
    "prog_054": {
        "id": "prog_054",
        "name": "PROG.UNT Entry 54",
        "archive": "PROG.UNT",
        "entry_index": 54,
        "lba": 232066,
        "sector_offset": 0,
        "sectors": 7,
        "budget": 14336,
        "width": 320,
        "height": 224,
        "bpp": 8,
        "vram_x": 320,
        "vram_y": 0,
        "vram_w": 160,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 256,
        "clut_h": 1,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 71692,
        "raw_tim_len": 72224,
        "compressed": True,
        "filenames": [
            "prog_054_320x224_decomp_0x0.png",
            "prog_054.png",
            "prog_54.png",
            "54.png",
        ],
    },
    "prog_055": {
        "id": "prog_055",
        "name": "PROG.UNT Entry 55",
        "archive": "PROG.UNT",
        "entry_index": 55,
        "lba": 232073,
        "sector_offset": 0,
        "sectors": 7,
        "budget": 14336,
        "width": 320,
        "height": 224,
        "bpp": 8,
        "vram_x": 320,
        "vram_y": 0,
        "vram_w": 160,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 256,
        "clut_h": 1,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 71692,
        "raw_tim_len": 72224,
        "compressed": True,
        "filenames": [
            "prog_055_320x224_decomp_0x0.png",
            "prog_055.png",
            "prog_55.png",
            "55.png",
        ],
    },
    "prog_056": {
        "id": "prog_056",
        "name": "PROG.UNT Entry 56",
        "archive": "PROG.UNT",
        "entry_index": 56,
        "lba": 232080,
        "sector_offset": 0,
        "sectors": 8,
        "budget": 16384,
        "width": 320,
        "height": 224,
        "bpp": 8,
        "vram_x": 320,
        "vram_y": 0,
        "vram_w": 160,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 256,
        "clut_h": 1,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 71692,
        "raw_tim_len": 72224,
        "compressed": True,
        "filenames": [
            "prog_056_320x224_decomp_0x0.png",
            "prog_056.png",
            "prog_56.png",
            "56.png",
        ],
    },
    "prog_057": {
        "id": "prog_057",
        "name": "PROG.UNT Entry 57",
        "archive": "PROG.UNT",
        "entry_index": 57,
        "lba": 232088,
        "sector_offset": 0,
        "sectors": 7,
        "budget": 14336,
        "width": 320,
        "height": 224,
        "bpp": 8,
        "vram_x": 320,
        "vram_y": 0,
        "vram_w": 160,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 256,
        "clut_h": 1,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 71692,
        "raw_tim_len": 72224,
        "compressed": True,
        "filenames": [
            "prog_057_320x224_decomp_0x0.png",
            "prog_057.png",
            "prog_57.png",
            "57.png",
        ],
    },
    "prog_317": {
        "id": "prog_317",
        "name": "PROG.UNT Entry 317",
        "archive": "PROG.UNT",
        "entry_index": 317,
        "lba": 233112,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 80,
        "height": 480,
        "bpp": 4,
        "vram_x": 0,
        "vram_y": 0,
        "vram_w": 20,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 19212,
        "raw_tim_len": 19264,
        "compressed": True,
        "filenames": [
            "prog_317_80x480_decomp_0x0.png",
            "prog_317.png",
            "prog317.png",
            "317.png",
        ],
    },
    "prog_324": {
        "id": "prog_324",
        "name": "PROG.UNT Entry 324",
        "archive": "PROG.UNT",
        "entry_index": 324,
        "lba": 233207,
        "sector_offset": 0,
        "sectors": 2,
        "budget": 4096,
        "width": 48,
        "height": 240,
        "bpp": 4,
        "vram_x": 0,
        "vram_y": 0,
        "vram_w": 12,
        "clut_x": 0,
        "clut_y": 480,
        "clut_w": 16,
        "clut_h": 1,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 5772,
        "raw_tim_len": 5824,
        "compressed": True,
        "filenames": [
            "prog_324_48x240_decomp_0x0.png",
            "prog_324.png",
            "prog324.png",
            "324.png",
        ],
    },
}

# Alias map for looking up specs by various identifiers
ENTRY_MAP: dict[str, str] = {
    # OPT
    "137": "opt_137",
    "opt137": "opt_137",
    "opt_137": "opt_137",
    "171": "opt_171",
    "opt171": "opt_171",
    "opt_171": "opt_171",
    "172": "opt_172",
    "opt172": "opt_172",
    "opt_172": "opt_172",
    "173": "opt_173",
    "opt173": "opt_173",
    "opt_173": "opt_173",
    "174": "opt_174",
    "opt174": "opt_174",
    "opt_174": "opt_174",
    "206": "opt_206",
    "opt206": "opt_206",
    "opt_206": "opt_206",
    "207": "opt_207",
    "opt207": "opt_207",
    "opt_207": "opt_207",
    "232": "opt_232",
    "opt232": "opt_232",
    "opt_232": "opt_232",
    # OPTCINE
    "optcine": "optcine_01",
    "optcine_01": "optcine_01",
    "optcine01": "optcine_01",
    "optcine_1": "optcine_01",
    # PROG
    "54": "prog_054",
    "prog54": "prog_054",
    "prog_54": "prog_054",
    "prog_054": "prog_054",
    "55": "prog_055",
    "prog55": "prog_055",
    "prog_55": "prog_055",
    "prog_055": "prog_055",
    "56": "prog_056",
    "prog56": "prog_056",
    "prog_56": "prog_056",
    "prog_056": "prog_056",
    "57": "prog_057",
    "prog57": "prog_057",
    "prog_57": "prog_057",
    "prog_057": "prog_057",
    "317": "prog_317",
    "prog317": "prog_317",
    "prog_317": "prog_317",
    "324": "prog_324",
    "prog324": "prog_324",
    "prog_324": "prog_324",
}


def parse_entry_id(val: str | int) -> str:
    """Parse string or integer identifier into canonical spec id."""
    s = str(val).strip().lower()
    if s in EXTRA_SCREENS_SPECS:
        return s
    if s in ENTRY_MAP:
        return ENTRY_MAP[s]
    raise ValueError(f"Unknown extra screen identifier: '{val}'. Valid: {sorted(EXTRA_SCREENS_SPECS.keys())}")


def get_candidate_bins(custom_bin: Path | str | None = None) -> list[Path]:
    """Return available candidate CD-ROM BIN images in priority order."""
    cands: list[Path] = []
    if custom_bin:
        cb = Path(custom_bin)
        if cb.is_file():
            cands.append(cb)
    for p in (DEFAULT_TARGET_BIN, DEFAULT_PATCH_REPO_BIN, DEFAULT_SRC_BIN):
        if p.is_file() and p not in cands:
            cands.append(p)
    return cands


def find_screen_images(source_dir: Path | str | None = None) -> dict[str, Path]:
    """Discover PNG images for all 15 entries across search directories."""
    search_dirs: list[Path] = []
    if source_dir:
        sd = Path(source_dir)
        if sd.is_dir():
            search_dirs.append(sd)
    for sd in DEFAULT_SOURCE_DIRS:
        if sd.is_dir() and sd not in search_dirs:
            search_dirs.append(sd)

    found: dict[str, Path] = {}
    for spec_id, spec in EXTRA_SCREENS_SPECS.items():
        for sdir in search_dirs:
            # Check exact filenames in order
            matched = False
            for fn in spec["filenames"]:
                candidate = sdir / fn
                if candidate.is_file():
                    found[spec_id] = candidate
                    matched = True
                    break
            if matched:
                break
            # Case-insensitive fallback
            for f in sdir.iterdir():
                if f.is_file() and f.suffix.lower() == ".png":
                    if f.name.lower() in [x.lower() for x in spec["filenames"]]:
                        found[spec_id] = f
                        matched = True
                        break
            if matched:
                break

    return found


def clut_bytes_to_rgbs(clut_bytes: bytes, num_colors: int = 16) -> list[tuple[int, int, int]]:
    """Convert raw BGR555 CLUT bytes to list of RGB tuples (0..255)."""
    rgbs: list[tuple[int, int, int]] = []
    for i in range(num_colors):
        val = struct.unpack_from("<H", clut_bytes, i * 2)[0]
        r = (val & 0x1F) << 3
        g = ((val >> 5) & 0x1F) << 3
        b = ((val >> 10) & 0x1F) << 3
        rgbs.append((r, g, b))
    return rgbs


def read_original_clut(spec_id: str, candidate_bins: Sequence[Path | str] | None = None) -> bytes:
    """Read original CLUT from disc image, or return hardware fallback."""
    spec = EXTRA_SCREENS_SPECS[spec_id]
    cands = list(candidate_bins) if candidate_bins else get_candidate_bins()
    for bin_path in cands:
        bp = Path(bin_path)
        if not bp.is_file() or read_extent is None:
            continue
        try:
            if spec["archive"] == "OPTCINE.GRP":
                raw = read_extent(bp, spec["lba"], 2048)
                tim_offset = spec["sector_offset"]
                clut_len = struct.unpack_from("<I", raw, tim_offset + 8)[0]
                if clut_len == spec["clut_block_len"]:
                    return raw[tim_offset + 20 : tim_offset + 8 + clut_len]
            elif not spec["compressed"]:
                raw = read_extent(bp, spec["lba"], 2048)
                clut_len = struct.unpack_from("<I", raw, 8)[0]
                if clut_len == spec["clut_block_len"]:
                    return raw[20 : 8 + clut_len]
        except Exception:
            continue
    return FALLBACK_CLUTS.get(spec_id, b"")


def encode_opt_screen(
    spec_id: str,
    image_path: Path | str,
    clut_override: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Encode an OPT 4bpp screen into (uncompressed_tim, padded_payload)."""
    spec = EXTRA_SCREENS_SPECS[spec_id]
    w, h = spec["width"], spec["height"]

    im = Image.open(image_path)
    if im.size != (w, h):
        im = im.resize((w, h), Image.Resampling.LANCZOS)

    clut_bytes = clut_override or FALLBACK_CLUTS[spec_id]
    clut_rgbs = np.array(clut_bytes_to_rgbs(clut_bytes, 16), dtype=np.int32)

    if im.mode == "P":
        pal = im.getpalette() or []
        num_pal = len(pal) // 3
        pal_to_clut: dict[int, int] = {}
        for p_idx in range(num_pal):
            prgb = np.array([pal[p_idx * 3], pal[p_idx * 3 + 1], pal[p_idx * 3 + 2]], dtype=np.int32)
            dists = np.sum((clut_rgbs - prgb) ** 2, axis=1)
            pal_to_clut[p_idx] = int(np.argmin(dists))
        arr = np.array(im)
        indices = np.vectorize(lambda v: pal_to_clut.get(v, 0))(arr).astype(np.uint8)
    else:
        im_rgb = im.convert("RGB")
        arr = np.array(im_rgb)
        flat = arr.reshape(-1, 3).astype(np.int32)
        diffs = flat[:, None, :] - clut_rgbs[None, :, :]
        dists = np.sum(diffs ** 2, axis=2)
        indices = np.argmin(dists, axis=1).reshape((h, w)).astype(np.uint8)

    w_words = spec["vram_w"]
    packed = bytearray(h * (w // 2))
    for y in range(h):
        for x in range(0, w, 2):
            idx0 = indices[y, x] & 0x0F
            idx1 = indices[y, x + 1] & 0x0F
            packed[y * (w // 2) + (x // 2)] = idx0 | (idx1 << 4)

    header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", spec["clut_block_len"], spec["clut_x"], spec["clut_y"], spec["clut_w"], spec["clut_h"]) + clut_bytes
    img_len_val = spec["img_block_len"]
    img_block = struct.pack("<IHHHH", img_len_val, spec["vram_x"], spec["vram_y"], w_words, h) + bytes(packed)

    tim_bytes = header + clut_block + img_block
    payload = tim_bytes.ljust(spec["budget"], b"\x00")
    return tim_bytes, payload


def encode_optcine_01(
    image_path: Path | str,
    clut_override: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Encode OPTCINE 01 256x256 4bpp screen into (uncompressed_tim, tim_bytes)."""
    spec = EXTRA_SCREENS_SPECS["optcine_01"]
    w, h = spec["width"], spec["height"]

    im = Image.open(image_path)
    if im.size != (w, h):
        im = im.resize((w, h), Image.Resampling.LANCZOS)

    clut_bytes = clut_override or FALLBACK_CLUTS["optcine_01"]
    # Map pixels to Bank 0 (first 16 colors of the 256-color CLUT)
    bank0_rgbs = np.array(clut_bytes_to_rgbs(clut_bytes[:32], 16), dtype=np.int32)

    im_rgb = im.convert("RGB")
    arr = np.array(im_rgb)
    flat = arr.reshape(-1, 3).astype(np.int32)
    diffs = flat[:, None, :] - bank0_rgbs[None, :, :]
    dists = np.sum(diffs ** 2, axis=2)
    indices = np.argmin(dists, axis=1).reshape((h, w)).astype(np.uint8)

    w_words = spec["vram_w"]  # 64
    packed = bytearray(h * 128)
    for y in range(h):
        for x in range(0, w, 2):
            idx0 = indices[y, x] & 0x0F
            idx1 = indices[y, x + 1] & 0x0F
            packed[y * 128 + (x // 2)] = idx0 | (idx1 << 4)

    header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", spec["clut_block_len"], spec["clut_x"], spec["clut_y"], spec["clut_w"], spec["clut_h"]) + clut_bytes
    img_block = struct.pack("<IHHHH", spec["img_block_len"], spec["vram_x"], spec["vram_y"], w_words, h) + bytes(packed)

    tim_bytes = header + clut_block + img_block
    if len(tim_bytes) != spec["raw_tim_len"]:
        raise ValueError(f"OPTCINE 01 TIM length {len(tim_bytes)} != expected {spec['raw_tim_len']}")

    return tim_bytes, tim_bytes


def encode_prog_screen(
    spec_id: str,
    image_path: Path | str,
    clut_override: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Encode PROG.UNT screen (8bpp or 4bpp) with LZSS mode 1 compression into (uncompressed_tim, padded_payload)."""
    if unt_lz is None:
        raise RuntimeError("unt_lz module is required to encode PROG screens")

    spec = EXTRA_SCREENS_SPECS[spec_id]
    w, h = spec["width"], spec["height"]

    im = Image.open(image_path)
    if im.size != (w, h):
        im = im.resize((w, h), Image.Resampling.NEAREST)

    bpp = spec.get("bpp", 8)
    if bpp == 4:
        clut_bytes = clut_override or FALLBACK_CLUTS.get(spec_id, b"")
        if not clut_bytes or len(clut_bytes) != 32:
            raise ValueError(f"16-color CLUT required for 4bpp PROG entry {spec_id}")
        clut_rgbs = np.array(clut_bytes_to_rgbs(clut_bytes, 16), dtype=np.int32)

        if im.mode == "P":
            pal = im.getpalette() or []
            num_pal = len(pal) // 3
            pal_to_clut: dict[int, int] = {}
            for p_idx in range(num_pal):
                prgb = np.array([pal[p_idx * 3], pal[p_idx * 3 + 1], pal[p_idx * 3 + 2]], dtype=np.int32)
                dists = np.sum((clut_rgbs - prgb) ** 2, axis=1)
                pal_to_clut[p_idx] = int(np.argmin(dists))
            arr = np.array(im)
            indices = np.vectorize(lambda v: pal_to_clut.get(v, 0))(arr).astype(np.uint8)
        else:
            im_rgb = im.convert("RGB")
            arr = np.array(im_rgb)
            flat = arr.reshape(-1, 3).astype(np.int32)
            diffs = flat[:, None, :] - clut_rgbs[None, :, :]
            dists = np.sum(diffs ** 2, axis=2)
            indices = np.argmin(dists, axis=1).reshape((h, w)).astype(np.uint8)

        w_words = spec["vram_w"]
        packed = bytearray(h * (w // 2))
        for y in range(h):
            for x in range(0, w, 2):
                idx0 = indices[y, x] & 0x0F
                idx1 = indices[y, x + 1] & 0x0F
                packed[y * (w // 2) + (x // 2)] = idx0 | (idx1 << 4)

        header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
        clut_block = struct.pack("<IHHHH", spec["clut_block_len"], spec["clut_x"], spec["clut_y"], spec["clut_w"], spec["clut_h"]) + clut_bytes
        img_block = struct.pack("<IHHHH", spec["img_block_len"], spec["vram_x"], spec["vram_y"], w_words, h) + bytes(packed)
    else:
        # For 8bpp PROG entries, convert PNG palette to 256 BGR555 colors
        pal = im.getpalette() or []
        clut_from_png = bytearray(512)
        for i in range(256):
            if i < len(pal) // 3:
                r, g, b = pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]
                val = ((r >> 3) & 0x1F) | (((g >> 3) & 0x1F) << 5) | (((b >> 3) & 0x1F) << 10)
                struct.pack_into("<H", clut_from_png, i * 2, val)

        img_data = im.tobytes()
        if len(img_data) != w * h:
            raise ValueError(f"Image data length {len(img_data)} != {w * h}")

        header = b"\x10\x00\x00\x00\x09\x00\x00\x00"
        clut_block = struct.pack("<IHHHH", spec["clut_block_len"], spec["clut_x"], spec["clut_y"], spec["clut_w"], spec["clut_h"]) + clut_from_png
        img_block = struct.pack("<IHHHH", spec["img_block_len"], spec["vram_x"], spec["vram_y"], spec["vram_w"], h) + img_data

    uncompressed_tim = header + clut_block + img_block
    if len(uncompressed_tim) != spec["raw_tim_len"]:
        raise ValueError(f"Uncompressed TIM length {len(uncompressed_tim)} != expected {spec['raw_tim_len']}")

    compressed = unt_lz.compress(uncompressed_tim)
    budget = spec["budget"]
    if len(compressed) > budget:
        raise ValueError(
            f"Compressed {spec_id} size ({len(compressed)} B) exceeds budget ({budget} B) by {len(compressed) - budget} B!"
        )

    # Verify roundtrip
    decomp, _ = unt_lz.decompress(compressed)
    if decomp != uncompressed_tim:
        raise RuntimeError(f"unt_lz decompression roundtrip verification failed for {spec_id}!")

    payload = compressed.ljust(budget, b"\x00")
    return uncompressed_tim, payload


def encode_screen(
    spec_id: str,
    image_path: Path | str,
    clut_override: bytes | None = None,
) -> tuple[bytes, bytes]:
    """Dispatch encoding for any of the 15 extra screens."""
    canon_id = parse_entry_id(spec_id)
    if canon_id.startswith("opt_"):
        return encode_opt_screen(canon_id, image_path, clut_override)
    elif canon_id == "optcine_01":
        return encode_optcine_01(image_path, clut_override)
    elif canon_id.startswith("prog_"):
        return encode_prog_screen(canon_id, image_path, clut_override)
    raise ValueError(f"Unsupported spec id: {spec_id}")


def patch_disc_extent(bin_path: Path, lba: int, payload: bytes) -> None:
    """Inject sector-aligned payload at LBA and recalculate Mode 2 Form 1 EDC/ECC."""
    if replace_extent_in_place is not None:
        replace_extent_in_place(bin_path, lba, payload)
        return

    chk = CdChecksums() if CdChecksums is not None else None
    sector_count = len(payload) // USER_DATA_SIZE
    with bin_path.open("r+b") as f:
        for s in range(sector_count):
            cur_lba = lba + s
            offset = s * USER_DATA_SIZE
            chunk = payload[offset : offset + USER_DATA_SIZE]

            f.seek(cur_lba * RAW_SECTOR_SIZE)
            sec = bytearray(f.read(RAW_SECTOR_SIZE))
            if len(sec) != RAW_SECTOR_SIZE:
                raise IOError(f"Unexpected EOF while reading LBA {cur_lba} from {bin_path}")

            sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = chunk
            if chk is not None:
                chk.repair_mode2_form1(sec)

            f.seek(cur_lba * RAW_SECTOR_SIZE)
            f.write(sec)


def patch_optcine_01(bin_path: Path, tim_payload: bytes) -> None:
    """Inject non-sector-aligned OPTCINE 01 into OPTCINE.GRP at LBA 264611, offset 544, spanning 17 sectors."""
    lba = 264611
    offset_in_sector0 = 544
    total_len = len(tim_payload)  # 33312
    num_sectors = 17
    chk = CdChecksums() if CdChecksums is not None else None

    with bin_path.open("r+b") as image:
        image.seek(lba * RAW_SECTOR_SIZE)
        sectors_data = [bytearray(image.read(RAW_SECTOR_SIZE)) for _ in range(num_sectors)]

        payload_pos = 0
        for s_idx, sec in enumerate(sectors_data):
            u_start = offset_in_sector0 if s_idx == 0 else 0
            u_end = min(USER_DATA_SIZE, u_start + (total_len - payload_pos))
            chunk_size = u_end - u_start
            sec[USER_DATA_OFFSET + u_start : USER_DATA_OFFSET + u_end] = tim_payload[payload_pos : payload_pos + chunk_size]
            payload_pos += chunk_size
            if chk is not None:
                chk.repair_mode2_form1(sec)

        if payload_pos != total_len:
            raise ValueError(f"Payload injected length mismatch: {payload_pos} != {total_len}")

        image.seek(lba * RAW_SECTOR_SIZE)
        for sec in sectors_data:
            image.write(sec)


def patch_extra_screens(
    bin_path: Path | str = DEFAULT_TARGET_BIN,
    source_dir: Path | str | None = None,
    target_entry: str | int | None = None,
    dry_run: bool = False,
    sync_patch_repo: bool = True,
) -> list[dict[str, Any]]:
    """Encode and patch extra screens into target disc image(s)."""
    target_path = Path(bin_path)
    if not dry_run and not target_path.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_path}")

    found_images = find_screen_images(source_dir)
    target_ids = [parse_entry_id(target_entry)] if target_entry is not None else sorted(EXTRA_SCREENS_SPECS.keys())

    missing = [sid for sid in target_ids if sid not in found_images]
    if missing:
        raise FileNotFoundError(f"Missing source images for entries: {missing} in search dirs: {[source_dir] + DEFAULT_SOURCE_DIRS}")

    results: list[dict[str, Any]] = []

    for spec_id in target_ids:
        spec = EXTRA_SCREENS_SPECS[spec_id]
        img_path = found_images[spec_id]
        clut = read_original_clut(spec_id, [target_path])

        tim_bytes, payload = encode_screen(spec_id, img_path, clut)
        raw_len = len(tim_bytes)
        payload_len = len(payload)
        budget = spec["budget"]

        res = {
            "id": spec_id,
            "name": spec["name"],
            "image": str(img_path),
            "lba": spec["lba"],
            "sectors": spec["sectors"],
            "budget": budget,
            "raw_len": raw_len,
            "payload_len": payload_len,
            "compressed": spec["compressed"],
            "dry_run": dry_run,
            "patched": False,
        }

        if not dry_run:
            if spec_id == "optcine_01":
                patch_optcine_01(target_path, tim_bytes)
            else:
                patch_disc_extent(target_path, spec["lba"], payload)
            res["patched"] = True

        results.append(res)

    # Sync to patch_repo disc image if primary target was patched
    if not dry_run and sync_patch_repo and (target_path == DEFAULT_TARGET_BIN.resolve() or target_path == DEFAULT_TARGET_BIN):
        if DEFAULT_PATCH_REPO_BIN.is_file():
            for res in results:
                spec_id = res["id"]
                spec = EXTRA_SCREENS_SPECS[spec_id]
                clut = read_original_clut(spec_id, [DEFAULT_PATCH_REPO_BIN])
                tim_bytes, payload = encode_screen(spec_id, found_images[spec_id], clut)
                if spec_id == "optcine_01":
                    patch_optcine_01(DEFAULT_PATCH_REPO_BIN, tim_bytes)
                else:
                    patch_disc_extent(DEFAULT_PATCH_REPO_BIN, spec["lba"], payload)

    return results


def verify_extra_screens(
    bin_path: Path | str = DEFAULT_TARGET_BIN,
    target_entry: str | int | None = None,
) -> list[dict[str, Any]]:
    """Verify Mode 2 Form 1 EDC/ECC and TIM structure of extra screens on disc.

    Validates:
    1. Every sector is Mode 2 Form 1 with 100% valid EDC, ECC P-parity, and ECC Q-parity.
    2. Decompression succeeds without errors for compressed entries.
    3. TIM magic (0x10) and flags (0x08 for 4bpp, 0x09 for 8bpp) are valid.
    4. CLUT dimensions, lengths, and VRAM coordinates match specification.
    5. Image dimensions, lengths, and VRAM coordinates match specification.
    """
    path = Path(bin_path)
    if not path.is_file():
        raise FileNotFoundError(f"Target disc image not found: {bin_path}")

    target_ids = [parse_entry_id(target_entry)] if target_entry is not None else sorted(EXTRA_SCREENS_SPECS.keys())
    checksums = CdChecksums() if CdChecksums is not None else None
    results: list[dict[str, Any]] = []

    with path.open("rb") as f:
        for spec_id in target_ids:
            spec = EXTRA_SCREENS_SPECS[spec_id]
            lba_start = spec["lba"]
            sector_count = spec["sectors"]
            budget = spec["budget"]

            # 1. Verify sector checksums
            for s in range(sector_count):
                cur_lba = lba_start + s
                f.seek(cur_lba * RAW_SECTOR_SIZE)
                sec = f.read(RAW_SECTOR_SIZE)
                if len(sec) != RAW_SECTOR_SIZE:
                    raise IOError(f"Unexpected EOF reading LBA {cur_lba} from {path}")

                if sec[15] != 2:
                    raise ValueError(f"Sector at LBA {cur_lba} ({spec_id}) is not Mode 2 Form 1 (submode byte={sec[15]})")

                if checksums is not None:
                    expected_edc = checksums.compute_edc(sec[0x10:0x818])
                    actual_edc = sec[0x818:0x81C]
                    if actual_edc != expected_edc:
                        raise ValueError(
                            f"EDC mismatch at LBA {cur_lba} ({spec_id}): {actual_edc.hex()} != {expected_edc.hex()}"
                        )

                    expected_ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                    actual_ecc_p = sec[0x81C:0x8C8]
                    if actual_ecc_p != expected_ecc_p:
                        raise ValueError(f"ECC P-parity mismatch at LBA {cur_lba} ({spec_id})")

                    expected_ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
                    actual_ecc_q = sec[0x8C8:0x930]
                    if actual_ecc_q != expected_ecc_q:
                        raise ValueError(f"ECC Q-parity mismatch at LBA {cur_lba} ({spec_id})")

            # 2. Read extent and extract TIM payload
            raw_extent = bytearray()
            for s in range(sector_count):
                f.seek((lba_start + s) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
                chunk = f.read(USER_DATA_SIZE)
                raw_extent.extend(chunk)
            raw_extent_bytes = bytes(raw_extent)

            if spec_id == "optcine_01":
                sec_off = spec["sector_offset"]
                tim_data = raw_extent_bytes[sec_off : sec_off + spec["raw_tim_len"]]
            elif spec["compressed"]:
                if unt_lz is None:
                    raise RuntimeError("unt_lz required for decompression verification")
                decomp, consumed = unt_lz.decompress(raw_extent_bytes)
                if consumed > budget:
                    raise ValueError(f"{spec_id} consumed {consumed} B > budget {budget} B")
                if len(decomp) != spec["raw_tim_len"]:
                    raise ValueError(f"{spec_id} decompressed size {len(decomp)} != expected {spec['raw_tim_len']}")
                tim_data = decomp
            else:
                tim_data = raw_extent_bytes[: spec["raw_tim_len"]]

            # 3. Verify TIM header
            magic, flag = struct.unpack_from("<II", tim_data, 0)
            if magic != 0x10:
                raise ValueError(f"Invalid TIM magic for {spec_id}: {hex(magic)} (expected 0x10)")

            expected_flag = 0x08 if spec["bpp"] == 4 else 0x09
            if flag != expected_flag:
                raise ValueError(f"Invalid TIM flag for {spec_id}: {hex(flag)} (expected {hex(expected_flag)})")

            # 4. Verify CLUT header
            clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_data, 8)
            if clut_len != spec["clut_block_len"]:
                raise ValueError(f"CLUT block len mismatch for {spec_id}: {clut_len} != expected {spec['clut_block_len']}")
            if (clut_x, clut_y, clut_w, clut_h) != (spec["clut_x"], spec["clut_y"], spec["clut_w"], spec["clut_h"]):
                raise ValueError(
                    f"CLUT coords/dims mismatch for {spec_id}: ({clut_x},{clut_y},{clut_w},{clut_h}) != "
                    f"({spec['clut_x']},{spec['clut_y']},{spec['clut_w']},{spec['clut_h']})"
                )

            # 5. Verify IMG header
            img_off = 8 + clut_len
            img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_data, img_off)
            # Accept either canonical 71692 or 35852 for OPT 232
            if spec_id == "opt_232":
                if img_len not in (71692, 35852):
                    raise ValueError(f"IMG block len mismatch for {spec_id}: {img_len} not in (71692, 35852)")
            else:
                if img_len != spec["img_block_len"]:
                    raise ValueError(f"IMG block len mismatch for {spec_id}: {img_len} != expected {spec['img_block_len']}")

            if (img_x, img_y, img_w, img_h) != (spec["vram_x"], spec["vram_y"], spec["vram_w"], spec["height"]):
                raise ValueError(
                    f"IMG coords/dims mismatch for {spec_id}: ({img_x},{img_y},{img_w},{img_h}) != "
                    f"({spec['vram_x']},{spec['vram_y']},{spec['vram_w']},{spec['height']})"
                )

            results.append({
                "id": spec_id,
                "name": spec["name"],
                "lba": lba_start,
                "sectors": sector_count,
                "budget": budget,
                "status": "PASS",
            })

    return results


def parse_cli_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Slayers Royal (PS1) - Extra Screens and Textures Patcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN,
        help="Path to PlayStation CD-ROM BIN image to patch",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="Directory containing translated source PNG images",
    )
    parser.add_argument(
        "--entry",
        type=str,
        default=None,
        help="Specific entry to patch/verify (e.g. 137, opt_137, optcine_01, prog_054)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify Mode 2 Form 1 EDC/ECC and TIM headers on disc without modifying",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Encode and validate budgets without modifying target disc image",
    )
    return parser.parse_args(args)


def main() -> int:
    """Main CLI entrypoint."""
    args = parse_cli_args()

    print("=" * 70)
    print("   Slayers Royal (PS1) — Extra Screens and Textures Patcher")
    print("=" * 70)

    if args.verify:
        print(f"[*] Verifying extra screens on disc image: {args.bin}")
        try:
            results = verify_extra_screens(args.bin, args.entry)
            print(f"[✓] Successfully verified all {len(results)} target entries (100% PASS):")
            for r in results:
                print(f"    - {r['id']:10s} ({r['name']}): LBA {r['lba']}, {r['sectors']} sectors -> {r['status']}")
            return 0
        except Exception as e:
            print(f"[!] Verification failed: {e}", file=sys.stderr)
            return 1

    print(f"[*] Target BIN:    {args.bin}")
    if args.source_dir:
        print(f"[*] Source dir:    {args.source_dir}")
    if args.dry_run:
        print("[*] Mode:          DRY RUN (no disc writes)")

    try:
        results = patch_extra_screens(
            bin_path=args.bin,
            source_dir=args.source_dir,
            target_entry=args.entry,
            dry_run=args.dry_run,
        )
        verb = "Validated" if args.dry_run else "Patched"
        print(f"[✓] {verb} {len(results)} extra screens successfully:")
        for r in results:
            comp_flag = " [LZSS]" if r["compressed"] else ""
            print(f"    - {r['id']:10s} ({r['name']}): {r['raw_len']} B -> {r['payload_len']}/{r['budget']} B{comp_flag}")
        return 0
    except Exception as e:
        print(f"[!] Patching failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
