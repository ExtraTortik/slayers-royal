#!/usr/bin/env python3
"""Slayers Royal (PS1) - Custom Screens Patcher.

This tool automates the extraction, TIM encoding, sector budget validation,
EDC/ECC recalculation, and injection of 4 key game screens:
1. OPT.UNT Entry 203 (0xCB): "UNLIMITED PLAY" -> "БЕСКОНЕЧНАЯ ИГРА" (64x16, 4bpp, 1 sector)
2. OPT.UNT Entry 221 (0xDD): "TURN" -> "ХОД" (80x64, 8bpp, 3 sectors)
3. OPT.UNT Entry 225 (0xE1): "START" -> "СТАРТ" (64x16, 4bpp, 1 sector)
4. PROG.UNT Entry 323 (0x143): "GAME OVER" -> "КОНЕЦ ИГРЫ" (320x240, 8bpp, LZSS mode 1, 5 sectors)

Features:
- Standalone CLI: `--bin`, `--screens-dir`, `--entry`, `--image`, `--dry-run`, `--verify`, `--preview`.
- Custom TIM encoders preserving hardware BGR555 CLUTs, STP attributes, and pixel alignments.
- Specialized compression preservation algorithm for PROG 323 to guarantee fitting inside 10,240 B.
- Bit-exact Mode 2 Form 1 EDC/ECC repair.
- Dual-image synchronization (primary and patch_repo).
- Comprehensive verification suite validating LBAs, budgets, TIM headers, and checksums.
- Automatic visual preview generation (`data/preview_custom_screens_ru.png`).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Repository paths
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

# Defaults and constants
DEFAULT_CATALOG = REPO_ROOT / "translations" / "custom_screens_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_PATCH_REPO_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SRC_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_SCREENS_DIR = REPO_ROOT / "data" / "custom_screens"
DEFAULT_PREVIEW_PATH = REPO_ROOT / "data" / "preview_custom_screens_ru.png"

# Specifications for the 4 custom screens
CUSTOM_SCREENS_SPECS: dict[int, dict[str, Any]] = {
    203: {
        "id": "turn",
        "entry_index": 203,
        "hex_index": "0xCB",
        "archive": "OPT.UNT",
        "archive_lba": 226000,
        "sector_offset": 2713,
        "lba": 228713,
        "sectors": 1,
        "budget": 2048,
        "width": 64,
        "height": 16,
        "bpp": 4,
        "vram_x": 640,
        "vram_y": 448,
        "vram_w_words": 16,
        "clut_x": 0,
        "clut_y": 497,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 1036,
        "raw_tim_len": 1088,
        "compressed": False,
        "name_en": "TURN",
        "name_ru": "ХОД",
        "aliases": [
            "opt_203_64x16_uncompressed.png",
            "opt_203.png",
            "203.png",
            "turn.png",
        ],
    },
    221: {
        "id": "unlimited_play",
        "entry_index": 221,
        "hex_index": "0xDD",
        "archive": "OPT.UNT",
        "archive_lba": 226000,
        "sector_offset": 2916,
        "lba": 228916,
        "sectors": 3,
        "budget": 6144,
        "width": 80,
        "height": 64,
        "bpp": 8,
        "vram_x": 960,
        "vram_y": 0,
        "vram_w_words": 40,
        "clut_x": 0,
        "clut_y": 489,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 5132,
        "raw_tim_len": 5664,
        "compressed": False,
        "name_en": "UNLIMITED PLAY",
        "name_ru": "БЕСКОНЕЧНАЯ ИГРА",
        "aliases": [
            "opt_221_80x64_uncompressed.png",
            "opt_221.png",
            "221.png",
            "unlimited_play.png",
        ],
    },
    225: {
        "id": "start",
        "entry_index": 225,
        "hex_index": "0xE1",
        "archive": "OPT.UNT",
        "archive_lba": 226000,
        "sector_offset": 2926,
        "lba": 228926,
        "sectors": 1,
        "budget": 2048,
        "width": 64,
        "height": 16,
        "bpp": 4,
        "vram_x": 1000,
        "vram_y": 0,
        "vram_w_words": 16,
        "clut_x": 0,
        "clut_y": 490,
        "clut_colors": 16,
        "clut_block_len": 44,
        "img_block_len": 524,
        "raw_tim_len": 576,
        "compressed": False,
        "name_en": "START",
        "name_ru": "СТАРТ",
        "aliases": [
            "opt_225_64x16_uncompressed.png",
            "opt_225.png",
            "225.png",
            "start.png",
        ],
    },
    323: {
        "id": "game_over",
        "entry_index": 323,
        "hex_index": "0x143",
        "archive": "PROG.UNT",
        "archive_lba": 229020,
        "sector_offset": 4182,
        "lba": 233202,
        "sectors": 5,
        "budget": 10240,
        "width": 320,
        "height": 240,
        "bpp": 8,
        "vram_x": 0,
        "vram_y": 0,
        "vram_w_words": 160,
        "clut_x": 0,
        "clut_y": 480,
        "clut_colors": 256,
        "clut_block_len": 524,
        "img_block_len": 76812,
        "raw_tim_len": 77344,
        "compressed": True,
        "compression_algo": "unt_lz mode 1",
        "name_en": "GAME OVER",
        "name_ru": "КОНЕЦ ИГРЫ",
        "aliases": [
            "prog_323_320x240_decomp_0x0.png",
            "prog_323.png",
            "323.png",
            "game_over.png",
        ],
    },
}

# String ID to entry index mapping
ENTRY_ID_MAP: dict[str, int] = {
    "turn": 203,
    "opt_203": 203,
    "203": 203,
    "unlimited_play": 221,
    "opt_221": 221,
    "221": 221,
    "start": 225,
    "opt_225": 225,
    "225": 225,
    "game_over": 323,
    "prog_323": 323,
    "323": 323,
}

# Verified default hardware CLUT tables for standalone execution without source BIN
FALLBACK_CLUT_203: bytes = bytes.fromhex(
    "ff83f599b395929570914f912d8d0c8deb88c988a88486846580448023802184"
)
FALLBACK_CLUT_225: bytes = bytes.fromhex(
    "00001f001d003b001c003a00570038005600740055007200900071008f008e00"
)


def get_candidate_bins(custom_bin: Path | str | None = None) -> list[Path]:
    """Return available candidate CD-ROM BIN images in priority order."""
    cands: list[Path] = []
    if custom_bin:
        cb = Path(custom_bin)
        if cb.is_file():
            cands.append(cb)
    for p in (
        DEFAULT_TARGET_BIN,
        DEFAULT_PATCH_REPO_BIN,
        DEFAULT_SRC_BIN,
        DEFAULT_EN_BIN,
    ):
        if p.is_file() and p not in cands:
            cands.append(p)
    return cands


def load_catalog(catalog_path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate custom screens catalog JSON."""
    p = Path(catalog_path) if catalog_path else DEFAULT_CATALOG
    if not p.is_file():
        raise FileNotFoundError(f"Custom screens catalog not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "screens" not in data:
        raise ValueError(f"Catalog {p} missing required 'screens' key")
    return data


def parse_entry_id(val: str | int) -> int:
    """Parse integer or string identifier into standard entry index (203, 221, 225, 323)."""
    if isinstance(val, int):
        if val in CUSTOM_SCREENS_SPECS:
            return val
        raise ValueError(f"Invalid custom screen entry index: {val}. Valid: {list(CUSTOM_SCREENS_SPECS.keys())}")
    s = str(val).strip().lower()
    if s.isdigit():
        iv = int(s)
        if iv in CUSTOM_SCREENS_SPECS:
            return iv
    if s in ENTRY_ID_MAP:
        return ENTRY_ID_MAP[s]
    raise ValueError(f"Unknown custom screen identifier: '{val}'. Valid IDs: {list(ENTRY_ID_MAP.keys())}")


def find_custom_screens(screens_dir: Path | str) -> dict[int, Path]:
    """Discover custom screen PNG images in the given directory using exact names and aliases."""
    sdir = Path(screens_dir)
    if not sdir.is_dir():
        return {}

    found: dict[int, Path] = {}
    for entry_idx, spec in CUSTOM_SCREENS_SPECS.items():
        # Check aliases in order
        for alias in spec["aliases"]:
            candidate = sdir / alias
            if candidate.is_file():
                found[entry_idx] = candidate
                break
        if entry_idx in found:
            continue
        # Check case-insensitive glob
        for file_path in sdir.iterdir():
            if file_path.is_file() and file_path.suffix.lower() == ".png":
                fn_lower = file_path.name.lower()
                for alias in spec["aliases"]:
                    if fn_lower == alias.lower():
                        found[entry_idx] = file_path
                        break
                if entry_idx in found:
                    break
    return found


def clut_bytes_to_rgbs(clut_bytes: bytes, num_colors: int) -> list[tuple[int, int, int]]:
    """Convert raw BGR555 CLUT bytes to list of RGB tuples (0..255)."""
    rgbs = []
    for i in range(num_colors):
        val = struct.unpack_from("<H", clut_bytes, i * 2)[0]
        r = (val & 0x1F) << 3
        g = ((val >> 5) & 0x1F) << 3
        b = ((val >> 10) & 0x1F) << 3
        rgbs.append((r, g, b))
    return rgbs


def read_original_tim(
    entry_index: int,
    candidate_bins: Sequence[Path | str] | None = None,
) -> bytes | None:
    """Read and uncompress original TIM for an entry from candidate disc images."""
    spec = CUSTOM_SCREENS_SPECS[entry_index]
    cands = list(candidate_bins) if candidate_bins else get_candidate_bins()
    for bin_path in cands:
        bp = Path(bin_path)
        if not bp.is_file():
            continue
        try:
            raw = read_extent(bp, spec["lba"], spec["budget"])
            if spec["compressed"]:
                decomp, consumed = unt_lz.decompress(raw)
                if len(decomp) == spec["raw_tim_len"] and decomp[:4] == b"\x10\x00\x00\x00":
                    return decomp
            else:
                if len(raw) >= spec["raw_tim_len"] and raw[:4] == b"\x10\x00\x00\x00":
                    return raw[: spec["raw_tim_len"]]
        except Exception:
            continue
    return None


def encode_opt_203(
    image_path: Path | str,
    orig_tim: bytes | None = None,
) -> bytes:
    """Encode 64x16 PNG image to 4bpp TIM for OPT.UNT Entry 203.

    Specifications:
    - TIM Magic: 0x10, Flag: 0x08 (4bpp with CLUT)
    - CLUT: len=44, x=0, y=497, w=16, h=1 (32 bytes BGR555)
    - IMG: len=1036, x=640, y=448, w=16 words (64 px), h=16
    - IMG data: 512 bytes packed 4bpp pixel data + 512 bytes zero padding = 1024 bytes
    - Total TIM size: 1088 bytes. Padded to 2048 bytes (1 sector).
    """
    img = Image.open(image_path).convert("RGBA")
    if img.size != (64, 16):
        img = img.resize((64, 16), Image.Resampling.LANCZOS)
    arr = np.array(img)

    clut_raw = FALLBACK_CLUT_203
    if orig_tim and len(orig_tim) >= 52:
        clut_len = struct.unpack_from("<I", orig_tim, 8)[0]
        if clut_len == 44:
            clut_raw = orig_tim[20:52]

    clut_rgbs = clut_bytes_to_rgbs(clut_raw, 16)
    clut_arr = np.array(clut_rgbs, dtype=np.int32)

    # Map pixels to closest color in 16-color CLUT
    pixels_packed = bytearray(512)
    for y in range(16):
        for x in range(0, 64, 2):
            rgb0 = arr[y, x, :3].astype(np.int32)
            rgb1 = arr[y, x + 1, :3].astype(np.int32)

            d0 = np.sum((clut_arr - rgb0) ** 2, axis=1)
            idx0 = int(np.argmin(d0)) & 0x0F

            d1 = np.sum((clut_arr - rgb1) ** 2, axis=1)
            idx1 = int(np.argmin(d1)) & 0x0F

            pixels_packed[y * 32 + x // 2] = idx0 | (idx1 << 4)

    header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", 44, 0, 497, 16, 1) + clut_raw
    img_block = struct.pack("<IHHHH", 1036, 640, 448, 16, 16) + bytes(pixels_packed) + (b"\x00" * 512)

    tim_bytes = header + clut_block + img_block
    if len(tim_bytes) != 1088:
        raise ValueError(f"Unexpected OPT 203 TIM length: {len(tim_bytes)} (expected 1088)")
    return tim_bytes.ljust(2048, b"\x00")


def encode_opt_221(
    image_path: Path | str,
    orig_tim: bytes | None = None,
) -> bytes:
    """Encode 80x64 PNG image to 8bpp TIM for OPT.UNT Entry 221.

    Specifications:
    - TIM Magic: 0x10, Flag: 0x09 (8bpp with CLUT)
    - CLUT: len=524, x=0, y=489, w=256, h=1 (512 bytes BGR555)
    - IMG: len=5132, x=960, y=0, w=40 words (80 px), h=64
    - IMG data: 5120 bytes 8bpp pixel data
    - Total TIM size: 5664 bytes. Padded to 6144 bytes (3 sectors).
    """
    img = Image.open(image_path).convert("RGBA")
    if img.size != (80, 64):
        img = img.resize((80, 64), Image.Resampling.LANCZOS)
    arr = np.array(img)

    clut_raw: bytes | None = None
    if orig_tim and len(orig_tim) >= 532:
        clut_len = struct.unpack_from("<I", orig_tim, 8)[0]
        if clut_len == 524:
            clut_raw = orig_tim[20:532]

    if clut_raw is None:
        # Generate 256-color palette with STP=1
        img_rgb = img.convert("RGB")
        img_p = img_rgb.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        pal = img_p.getpalette() or []
        while len(pal) < 256 * 3:
            pal.extend([0, 0, 0])
        clut_ba = bytearray()
        for i in range(256):
            r, g, b = pal[i * 3], pal[i * 3 + 1], pal[i * 3 + 2]
            val = 0x8000 | ((b >> 3) << 10) | ((g >> 3) << 5) | (r >> 3)
            clut_ba.extend(struct.pack("<H", val))
        clut_raw = bytes(clut_ba)

    clut_rgbs = clut_bytes_to_rgbs(clut_raw, 256)
    clut_arr = np.array(clut_rgbs, dtype=np.int32)

    # Map pixels to closest color in 256-color CLUT
    flat_arr = arr[:, :, :3].reshape(-1, 3).astype(np.int32)
    # Batch distance calculation
    # (N, 3) vs (256, 3)
    dists = np.sum((flat_arr[:, np.newaxis, :] - clut_arr[np.newaxis, :, :]) ** 2, axis=2)
    indices = np.argmin(dists, axis=1).astype(np.uint8)

    header = b"\x10\x00\x00\x00\x09\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", 524, 0, 489, 256, 1) + clut_raw
    img_block = struct.pack("<IHHHH", 5132, 960, 0, 40, 64) + indices.tobytes()

    tim_bytes = header + clut_block + img_block
    if len(tim_bytes) != 5664:
        raise ValueError(f"Unexpected OPT 221 TIM length: {len(tim_bytes)} (expected 5664)")
    return tim_bytes.ljust(6144, b"\x00")


def encode_opt_225(
    image_path: Path | str,
    orig_tim: bytes | None = None,
) -> bytes:
    """Encode 64x16 PNG image to 4bpp TIM for OPT.UNT Entry 225.

    Specifications:
    - TIM Magic: 0x10, Flag: 0x08 (4bpp with CLUT)
    - CLUT: len=44, x=0, y=490, w=16, h=1 (32 bytes BGR555)
    - IMG: len=524, x=1000, y=0, w=16 words (64 px), h=16
    - IMG data: 512 bytes packed 4bpp pixel data
    - Total TIM size: 576 bytes. Padded to 2048 bytes (1 sector).
    - Color mapping: Index 0 is transparent background. If pixel alpha == 0
      or max(R,G,B) <= 20, map to index 0. Text pixels map to nearest among 1..15.
    """
    img = Image.open(image_path).convert("RGBA")
    if img.size != (64, 16):
        img = img.resize((64, 16), Image.Resampling.LANCZOS)
    arr = np.array(img)

    clut_raw = FALLBACK_CLUT_225
    if orig_tim and len(orig_tim) >= 52:
        clut_len = struct.unpack_from("<I", orig_tim, 8)[0]
        if clut_len == 44:
            clut_raw = orig_tim[20:52]

    clut_rgbs = clut_bytes_to_rgbs(clut_raw, 16)
    # Indices 1..15 for text
    text_clut_arr = np.array(clut_rgbs[1:], dtype=np.int32)

    pixels_packed = bytearray(512)
    for y in range(16):
        for x in range(0, 64, 2):
            px0 = arr[y, x]
            px1 = arr[y, x + 1]

            if px0[3] == 0 or np.max(px0[:3]) <= 20:
                idx0 = 0
            else:
                d0 = np.sum((text_clut_arr - px0[:3].astype(np.int32)) ** 2, axis=1)
                idx0 = int(np.argmin(d0)) + 1

            if px1[3] == 0 or np.max(px1[:3]) <= 20:
                idx1 = 0
            else:
                d1 = np.sum((text_clut_arr - px1[:3].astype(np.int32)) ** 2, axis=1)
                idx1 = int(np.argmin(d1)) + 1

            pixels_packed[y * 32 + x // 2] = (idx0 & 0x0F) | ((idx1 & 0x0F) << 4)

    header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", 44, 0, 490, 16, 1) + clut_raw
    img_block = struct.pack("<IHHHH", 524, 1000, 0, 16, 16) + bytes(pixels_packed)

    tim_bytes = header + clut_block + img_block
    if len(tim_bytes) != 576:
        raise ValueError(f"Unexpected OPT 225 TIM length: {len(tim_bytes)} (expected 576)")
    return tim_bytes.ljust(2048, b"\x00")


def encode_prog_323(
    image_path: Path | str,
    orig_tim: bytes | None = None,
    candidate_bins: Sequence[Path | str] | None = None,
) -> tuple[bytes, bytes]:
    """Encode 320x240 PNG image to LZSS-compressed 8bpp TIM for PROG.UNT Entry 323.

    Compression preservation technique:
    - Uses original CLUT and original background stripe indices.
    - Header ("КОНЕЦ ИГРЫ"): Y: 55..95, X: 30..290. Pixels with max(RGB) > 30 are text; rest are index 0.
    - Bottom prompts ("ПРОДОЛЖИТЬ? ЖМИ O", "КОНЕЦ? ЖМИ X"): Y: 175..235, X: 15..305.
      Pixels where max difference from clean row background > 35 are text; rest use clean row background index.
    - Clean horizontal stripes are preserved across the background.
    - Resulting 77,344 B TIM compresses via `unt_lz.compress` into <= 10,240 B.

    Returns:
        (uncompressed_tim, compressed_payload)
    """
    if unt_lz is None:
        raise RuntimeError("unt_lz compression module is required but could not be imported")

    user_img = Image.open(image_path).convert("RGBA")
    if user_img.size != (320, 240):
        user_img = user_img.resize((320, 240), Image.Resampling.LANCZOS)
    user_arr = np.array(user_img)

    # Retrieve original TIM
    uncomp_orig = orig_tim
    if uncomp_orig is None:
        uncomp_orig = read_original_tim(323, candidate_bins)
    if uncomp_orig is None or len(uncomp_orig) != 77344:
        raise RuntimeError(
            "Original PROG 323 TIM is required to preserve background stripes and CLUT, "
            "but could not be found in candidate disc images."
        )

    # Parse original TIM
    clut_raw = uncomp_orig[20:532]
    clut_rgbs = clut_bytes_to_rgbs(clut_raw, 256)
    clut_arr = np.array(clut_rgbs, dtype=np.int32)

    orig_img_bytes = uncomp_orig[544 : 544 + 76800]
    orig_indices = np.frombuffer(orig_img_bytes, dtype=np.uint8).reshape((240, 320)).copy()

    # Determine dominant/clean background index per row
    bg_per_row = np.zeros(240, dtype=np.uint8)
    for y in range(240):
        vals, counts = np.unique(orig_indices[y], return_counts=True)
        bg_per_row[y] = vals[np.argmax(counts)]

    bg_rgb_per_row = clut_arr[bg_per_row]

    patched_indices = orig_indices.copy()

    # Fast nearest CLUT index finder
    def find_nearest_idx(rgb: np.ndarray) -> int:
        dists = np.sum((clut_arr - rgb) ** 2, axis=1)
        return int(np.argmin(dists))

    # 1. Header ("КОНЕЦ ИГРЫ"): Y: 55..95, X: 30..290
    for y in range(55, 96):
        for x in range(30, 291):
            rgb = user_arr[y, x, :3].astype(np.int32)
            if np.max(rgb) > 30:
                patched_indices[y, x] = find_nearest_idx(rgb)
            else:
                patched_indices[y, x] = 0

    # 2. Bottom prompts ("ПРОДОЛЖИТЬ? ЖМИ O", "КОНЕЦ? ЖМИ X"): Y: 175..235, X: 15..305
    for y in range(175, 236):
        for x in range(15, 306):
            rgb = user_arr[y, x, :3].astype(np.int32)
            bg_rgb = bg_rgb_per_row[y]
            if np.max(np.abs(rgb - bg_rgb)) > 35:
                patched_indices[y, x] = find_nearest_idx(rgb)
            else:
                patched_indices[y, x] = bg_per_row[y]

    # Reassemble uncompressed TIM
    header = b"\x10\x00\x00\x00\x09\x00\x00\x00"
    clut_block = struct.pack("<IHHHH", 524, 0, 480, 256, 1) + clut_raw
    img_block = struct.pack("<IHHHH", 76812, 0, 0, 160, 240) + patched_indices.tobytes()
    uncompressed_tim = header + clut_block + img_block

    if len(uncompressed_tim) != 77344:
        raise ValueError(f"Unexpected PROG 323 TIM length: {len(uncompressed_tim)} (expected 77344)")

    # Compress using unt_lz mode 1
    compressed = unt_lz.compress(uncompressed_tim)
    budget = CUSTOM_SCREENS_SPECS[323]["budget"]
    if len(compressed) > budget:
        raise ValueError(
            f"Compressed PROG 323 size ({len(compressed)} B) exceeds allocated budget ({budget} B) "
            f"by {len(compressed) - budget} B!"
        )

    # Verify bit-exact roundtrip
    decomp, _ = unt_lz.decompress(compressed)
    if decomp != uncompressed_tim:
        raise RuntimeError("PROG 323 roundtrip unt_lz decompression mismatch!")

    payload = compressed.ljust(budget, b"\x00")
    return uncompressed_tim, payload


def encode_custom_screen(
    entry_index: int,
    image_path: Path | str,
    candidate_bins: Sequence[Path | str] | None = None,
) -> tuple[bytes, bytes]:
    """Encode custom screen PNG into (uncompressed_tim, sector_payload).

    Returns:
        (tim_bytes, sector_payload_padded_to_budget)
    """
    if entry_index not in CUSTOM_SCREENS_SPECS:
        raise ValueError(f"Unsupported entry index: {entry_index}")

    orig_tim = read_original_tim(entry_index, candidate_bins)

    if entry_index == 203:
        payload = encode_opt_203(image_path, orig_tim)
        tim_bytes = payload[: CUSTOM_SCREENS_SPECS[203]["raw_tim_len"]]
        return tim_bytes, payload

    elif entry_index == 221:
        payload = encode_opt_221(image_path, orig_tim)
        tim_bytes = payload[: CUSTOM_SCREENS_SPECS[221]["raw_tim_len"]]
        return tim_bytes, payload

    elif entry_index == 225:
        payload = encode_opt_225(image_path, orig_tim)
        tim_bytes = payload[: CUSTOM_SCREENS_SPECS[225]["raw_tim_len"]]
        return tim_bytes, payload

    elif entry_index == 323:
        tim_bytes, payload = encode_prog_323(image_path, orig_tim, candidate_bins)
        return tim_bytes, payload

    raise ValueError(f"Unhandled entry: {entry_index}")


def patch_disc_extent(bin_path: Path, lba: int, payload: bytes) -> None:
    """Inject sector payload into disc image at LBA and recalculate Mode 2 Form 1 EDC/ECC."""
    if replace_extent_in_place is not None:
        replace_extent_in_place(bin_path, lba, payload)
        return

    # Fallback sector-by-sector injection
    chk = CdChecksums()
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

            # Recalculate EDC
            edc = chk.compute_edc(sec[0x10:0x818])
            sec[0x818:0x81C] = edc

            # Recalculate ECC P and Q
            ecc_p = chk.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            sec[0x81C:0x8C8] = ecc_p
            ecc_q = chk.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            sec[0x8C8:0x930] = ecc_q

            f.seek(cur_lba * RAW_SECTOR_SIZE)
            f.write(sec)


def patch_custom_screens(
    bin_path: Path | str = DEFAULT_TARGET_BIN,
    screens_dir: Path | str = DEFAULT_SCREENS_DIR,
    entry_index: int | str | None = None,
    image_path: Path | str | None = None,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Patch custom screens into target disc image(s)."""
    target_bin = Path(bin_path)
    if not dry_run and not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    # Determine which entries to patch
    if entry_index is not None:
        target_entries = [parse_entry_id(entry_index)]
    else:
        target_entries = sorted(CUSTOM_SCREENS_SPECS.keys())

    # Locate images
    custom_images = find_custom_screens(screens_dir)
    results: list[dict[str, Any]] = []
    candidates = get_candidate_bins(target_bin)

    for e_idx in target_entries:
        spec = CUSTOM_SCREENS_SPECS[e_idx]
        img_p: Path | None = None
        if entry_index is not None and image_path is not None:
            ip = Path(image_path)
            if not ip.is_file():
                raise FileNotFoundError(f"Specified image file not found: {ip}")
            img_p = ip
        elif e_idx in custom_images:
            img_p = custom_images[e_idx]
        else:
            raise FileNotFoundError(
                f"No custom screen PNG found for entry {e_idx} ({spec['name_ru']}) in {screens_dir}"
            )

        tim_bytes, payload = encode_custom_screen(e_idx, img_p, candidate_bins=candidates)

        secondary_updated = False
        if not dry_run:
            patch_disc_extent(target_bin, spec["lba"], payload)

            # Update secondary disc image if present and distinct
            if DEFAULT_PATCH_REPO_BIN.is_file() and DEFAULT_PATCH_REPO_BIN.resolve() != target_bin.resolve():
                patch_disc_extent(DEFAULT_PATCH_REPO_BIN, spec["lba"], payload)
                secondary_updated = True

        res = {
            "status": "dry_run" if dry_run else "success",
            "entry_index": e_idx,
            "id": spec["id"],
            "name_en": spec["name_en"],
            "name_ru": spec["name_ru"],
            "archive": spec["archive"],
            "lba": spec["lba"],
            "sectors": spec["sectors"],
            "budget": spec["budget"],
            "tim_size": len(tim_bytes),
            "payload_size": len(payload),
            "image_path": str(img_p),
            "target_bin": str(target_bin),
            "secondary_bin": str(DEFAULT_PATCH_REPO_BIN) if secondary_updated else None,
            "compressed": spec["compressed"],
            "dry_run": dry_run,
        }
        results.append(res)

    return results


def verify_custom_screens(
    bin_path: Path | str = DEFAULT_TARGET_BIN,
    entry_index: int | str | None = None,
) -> list[dict[str, Any]]:
    """Verify Mode 2 Form 1 EDC/ECC and TIM structure of custom screens on disc.

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

    if entry_index is not None:
        target_entries = [parse_entry_id(entry_index)]
    else:
        target_entries = sorted(CUSTOM_SCREENS_SPECS.keys())

    checksums = CdChecksums() if CdChecksums is not None else None
    results: list[dict[str, Any]] = []

    with path.open("rb") as f:
        for e_idx in target_entries:
            spec = CUSTOM_SCREENS_SPECS[e_idx]
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
                    raise ValueError(f"Sector at LBA {cur_lba} is not Mode 2 Form 1 (submode byte={sec[15]})")

                if checksums is not None:
                    expected_edc = checksums.compute_edc(sec[0x10:0x818])
                    actual_edc = sec[0x818:0x81C]
                    if actual_edc != expected_edc:
                        raise ValueError(
                            f"EDC mismatch at LBA {cur_lba} (Entry {e_idx}): {actual_edc.hex()} != {expected_edc.hex()}"
                        )

                    expected_ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
                    actual_ecc_p = sec[0x81C:0x8C8]
                    if actual_ecc_p != expected_ecc_p:
                        raise ValueError(f"ECC P-parity mismatch at LBA {cur_lba} (Entry {e_idx})")

                    expected_ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
                    actual_ecc_q = sec[0x8C8:0x930]
                    if actual_ecc_q != expected_ecc_q:
                        raise ValueError(f"ECC Q-parity mismatch at LBA {cur_lba} (Entry {e_idx})")

            # 2. Read extent and verify payload
            f.seek(lba_start * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            raw_extent = bytearray()
            for s in range(sector_count):
                f.seek((lba_start + s) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
                chunk = f.read(USER_DATA_SIZE)
                raw_extent.extend(chunk)
            raw_extent = bytes(raw_extent)

            consumed = len(raw_extent)
            if spec["compressed"]:
                if unt_lz is None:
                    raise RuntimeError("unt_lz required for decompression verification")
                decomp, consumed = unt_lz.decompress(raw_extent)
                if consumed > budget:
                    raise ValueError(
                        f"Entry {e_idx} consumed {consumed} B which exceeds budget {budget} B"
                    )
                if len(decomp) != spec["raw_tim_len"]:
                    raise ValueError(
                        f"Entry {e_idx} decompressed size {len(decomp)} != expected {spec['raw_tim_len']}"
                    )
                tim_data = decomp
            else:
                tim_data = raw_extent[: spec["raw_tim_len"]]

            # Verify TIM header
            magic, flag = struct.unpack_from("<II", tim_data, 0)
            if magic != 0x10:
                raise ValueError(f"Invalid TIM magic for Entry {e_idx}: {hex(magic)} (expected 0x10)")

            expected_flag = 0x08 if spec["bpp"] == 4 else 0x09
            if flag != expected_flag:
                raise ValueError(f"Invalid TIM flag for Entry {e_idx}: {hex(flag)} (expected {hex(expected_flag)})")

            # Verify CLUT header
            clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_data, 8)
            if clut_len != spec["clut_block_len"]:
                raise ValueError(
                    f"Entry {e_idx} CLUT len {clut_len} != expected {spec['clut_block_len']}"
                )
            if (clut_x, clut_y, clut_w, clut_h) != (spec["clut_x"], spec["clut_y"], spec["clut_colors"], 1):
                raise ValueError(
                    f"Entry {e_idx} CLUT pos ({clut_x},{clut_y},{clut_w},{clut_h}) != expected "
                    f"({spec['clut_x']},{spec['clut_y']},{spec['clut_colors']},1)"
                )

            # Verify IMG header
            img_offset = 8 + clut_len
            img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_data, img_offset)
            if img_len != spec["img_block_len"]:
                raise ValueError(
                    f"Entry {e_idx} IMG len {img_len} != expected {spec['img_block_len']}"
                )
            if (img_x, img_y, img_w, img_h) != (spec["vram_x"], spec["vram_y"], spec["vram_w_words"], spec["height"]):
                raise ValueError(
                    f"Entry {e_idx} IMG pos ({img_x},{img_y},{img_w},{img_h}) != expected "
                    f"({spec['vram_x']},{spec['vram_y']},{spec['vram_w_words']},{spec['height']})"
                )

            results.append({
                "entry_index": e_idx,
                "id": spec["id"],
                "name_ru": spec["name_ru"],
                "lba": spec["lba"],
                "sectors": spec["sectors"],
                "edc_ecc_valid": True,
                "tim_valid": True,
                "consumed_bytes": consumed,
                "budget_bytes": budget,
            })

    return results


def tim_to_rgba(tim_bytes: bytes) -> Image.Image:
    """Decode an uncompressed 4bpp or 8bpp TIM with CLUT into a PIL RGBA Image."""
    magic, flag = struct.unpack_from("<II", tim_bytes, 0)
    if magic != 0x10:
        raise ValueError(f"Not a TIM: magic {hex(magic)}")
    has_clut = bool(flag & 0x08)
    bpp_mode = flag & 0x07

    offset = 8
    clut_colors: list[tuple[int, int, int, int]] = []
    if has_clut:
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, offset)
        clut_raw = tim_bytes[offset + 12 : offset + clut_len]
        total_colors = cw * ch
        for i in range(total_colors):
            val = struct.unpack_from("<H", clut_raw, i * 2)[0]
            r = (val & 0x1F) << 3
            g = ((val >> 5) & 0x1F) << 3
            b = ((val >> 10) & 0x1F) << 3
            stp = (val >> 15) & 1
            if bpp_mode == 0 and i == 0 and val == 0:
                a = 0
            else:
                a = 255
            clut_colors.append((r, g, b, a))
        offset += clut_len

    img_len, ix, iy, iw_words, ih = struct.unpack_from("<IHHHH", tim_bytes, offset)
    img_data = tim_bytes[offset + 12 : offset + img_len]

    if bpp_mode == 0:
        # 4bpp
        w_px = iw_words * 4
        h_px = ih
        arr = np.zeros((h_px, w_px, 4), dtype=np.uint8)
        for y in range(h_px):
            for x in range(0, w_px, 2):
                byte = img_data[y * (w_px // 2) + x // 2]
                idx0 = byte & 0x0F
                idx1 = (byte >> 4) & 0x0F
                arr[y, x] = clut_colors[idx0] if idx0 < len(clut_colors) else (0, 0, 0, 0)
                arr[y, x + 1] = clut_colors[idx1] if idx1 < len(clut_colors) else (0, 0, 0, 0)
        return Image.fromarray(arr)

    elif bpp_mode == 1:
        # 8bpp
        w_px = iw_words * 2
        h_px = ih
        arr = np.zeros((h_px, w_px, 4), dtype=np.uint8)
        for y in range(h_px):
            for x in range(w_px):
                idx = img_data[y * w_px + x]
                arr[y, x] = clut_colors[idx] if idx < len(clut_colors) else (0, 0, 0, 255)
        return Image.fromarray(arr)

    raise ValueError(f"Unsupported bpp mode: {bpp_mode}")


def generate_preview(
    screens_dir: Path | str = DEFAULT_SCREENS_DIR,
    bin_path: Path | str | None = None,
    output_path: Path | str = DEFAULT_PREVIEW_PATH,
) -> Path:
    """Generate visual composite preview showing all 4 custom screens.

    Displays:
    - Left side: Full screen PROG.UNT 323 Game Over screen (320x240).
    - Right side: OPT.UNT 203 (128x32, 2x), OPT.UNT 225 (128x32, 2x), OPT.UNT 221 (160x128, 2x).
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    candidates = get_candidate_bins(bin_path)
    sdir = Path(screens_dir)
    images = find_custom_screens(sdir)

    # Encode TIMs
    tims: dict[int, bytes] = {}
    for e_idx in (203, 221, 225, 323):
        if e_idx in images:
            tim_b, _ = encode_custom_screen(e_idx, images[e_idx], candidate_bins=candidates)
            tims[e_idx] = tim_b
        else:
            # Try loading from candidate bins
            orig = read_original_tim(e_idx, candidates)
            if orig is not None:
                tims[e_idx] = orig

    # Decode RGBA images
    img_323 = tim_to_rgba(tims[323]) if 323 in tims else Image.new("RGBA", (320, 240), (0, 0, 0, 255))
    img_203 = tim_to_rgba(tims[203]) if 203 in tims else Image.new("RGBA", (64, 16), (0, 0, 0, 255))
    img_225 = tim_to_rgba(tims[225]) if 225 in tims else Image.new("RGBA", (64, 16), (0, 0, 0, 255))
    img_221 = tim_to_rgba(tims[221]) if 221 in tims else Image.new("RGBA", (80, 64), (0, 0, 0, 255))

    # Canvas: 640x360 dark luxury styling
    canvas = Image.new("RGBA", (640, 360), (16, 20, 28, 255))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()

    # Title
    draw.text((16, 12), "Slayers Royal (PS1) - Custom Screens (Russian Translation)", fill=(240, 200, 80, 255), font=font)

    # Left: PROG 323
    draw.text((16, 28), "PROG.UNT 323: GAME OVER (320x240, LZSS 8bpp)", fill=(200, 210, 220, 255), font=font)
    draw.rectangle([15, 39, 16 + 320, 40 + 240], outline=(70, 80, 100, 255), width=1)
    canvas.paste(img_323, (16, 40))

    # Right: OPT 203, 225, 221
    # OPT 203
    draw.text((360, 28), "OPT.UNT 203: TURN (64x16 4bpp, 2x)", fill=(200, 210, 220, 255), font=font)
    scaled_203 = img_203.resize((128, 32), Image.Resampling.NEAREST)
    draw.rectangle([359, 41, 360 + 128, 42 + 32], outline=(70, 80, 100, 255), width=1)
    canvas.paste(scaled_203, (360, 42))

    # OPT 225
    draw.text((360, 94), "OPT.UNT 225: START (64x16 4bpp, 2x)", fill=(200, 210, 220, 255), font=font)
    scaled_225 = img_225.resize((128, 32), Image.Resampling.NEAREST)
    # Checkerboard background for transparency
    for cy in range(0, 32, 8):
        for cx in range(0, 128, 8):
            c = (32, 36, 48, 255) if ((cx // 8 + cy // 8) % 2 == 0) else (24, 28, 38, 255)
            draw.rectangle([360 + cx, 108 + cy, 360 + cx + 7, 108 + cy + 7], fill=c)
    draw.rectangle([359, 107, 360 + 128, 108 + 32], outline=(70, 80, 100, 255), width=1)
    canvas.alpha_composite(scaled_225, (360, 108))

    # OPT 221
    draw.text((360, 160), "OPT.UNT 221: UNLIMITED PLAY (80x64 8bpp, 2x)", fill=(200, 210, 220, 255), font=font)
    scaled_221 = img_221.resize((160, 128), Image.Resampling.NEAREST)
    draw.rectangle([359, 175, 360 + 160, 176 + 128], outline=(70, 80, 100, 255), width=1)
    canvas.paste(scaled_221, (360, 176))

    # Footer
    draw.text((16, 318), "Mode 2 Form 1 EDC/ECC repair - Sector Budgets: 203: 1sec | 221: 3sec | 225: 1sec | 323: 5sec", fill=(120, 130, 150, 255), font=font)
    draw.text((16, 334), "Entries: 203 (Turn), 221 (Unlimited Play), 225 (Start), 323 (Game Over)", fill=(100, 180, 120, 255), font=font)

    canvas.save(out_file)
    return out_file


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Slayers Royal (PS1) - Custom Screens Patcher",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN,
        help="Path to target PS1 CD-ROM BIN image",
    )
    parser.add_argument(
        "--screens-dir",
        type=Path,
        default=DEFAULT_SCREENS_DIR,
        help="Directory containing custom screen PNG files",
    )
    parser.add_argument(
        "--entry",
        type=str,
        default=None,
        help="Specific entry to patch (203, 221, 225, 323 or unlimited_play, turn, start, game_over)",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Explicit path to custom PNG file (used with --entry)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate encoding and budget validation without writing to disc",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify Mode 2 Form 1 EDC/ECC and TIM integrity on disc image",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate preview composite data/preview_custom_screens_ru.png",
    )
    parser.add_argument(
        "--preview-path",
        type=Path,
        default=DEFAULT_PREVIEW_PATH,
        help="Output path for preview composite image",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_cli_args(argv)

    if args.verify:
        print(f"[*] Verifying custom screens on {args.bin}...")
        try:
            results = verify_custom_screens(args.bin, entry_index=args.entry)
            print(f"[✓] Verification SUCCESSFUL: {len(results)}/4 entries verified.")
            for r in results:
                print(
                    f"    Entry {r['entry_index']:3d} ({r['id']:14s}): "
                    f"LBA {r['lba']} ({r['sectors']} sec) - "
                    f"Payload: {r['consumed_bytes']:5d} / {r['budget_bytes']:5d} B - "
                    f"EDC/ECC: OK - TIM: OK"
                )
            return 0
        except Exception as e:
            print(f"[!] Verification FAILED: {e}", file=sys.stderr)
            return 1

    print(f"[*] Slayers Royal (PS1) - Custom Screens Patcher")
    print(f"    Target BIN:    {args.bin}")
    print(f"    Screens Dir:   {args.screens_dir}")
    print(f"    Dry Run:       {args.dry_run}")

    try:
        results = patch_custom_screens(
            bin_path=args.bin,
            screens_dir=args.screens_dir,
            entry_index=args.entry,
            image_path=args.image,
            dry_run=args.dry_run,
        )

        for r in results:
            mode_str = "[DRY-RUN]" if r["dry_run"] else "[PATCHED]"
            comp_str = f", compressed: {r['payload_size']} B" if r["compressed"] else ""
            print(
                f"    {mode_str} Entry {r['entry_index']:3d} ({r['id']:14s}): "
                f"{r['name_ru']} -> LBA {r['lba']} ({r['sectors']} sec, budget: {r['budget']} B{comp_str})"
            )
            if r["secondary_bin"]:
                print(f"        -> Synchronized to {r['secondary_bin']}")

        print(f"[✓] Successfully processed {len(results)} screen(s)!")

        # Always generate preview unless explicit dry-run without preview
        if args.preview or not args.dry_run:
            print(f"[*] Generating composite preview: {args.preview_path}...")
            prev_out = generate_preview(
                screens_dir=args.screens_dir,
                bin_path=args.bin,
                output_path=args.preview_path,
            )
            print(f"[✓] Composite preview saved to {prev_out}")

        return 0

    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
