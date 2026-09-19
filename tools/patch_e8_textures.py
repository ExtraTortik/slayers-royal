#!/usr/bin/env python3
"""Patcher and validator for Overworld HUD texture atlas in PROG.UNT Entry 8.

Location:
  Archive: PROG.UNT (LBA 229020)
  Entry: Entry 8 (sector 1506 in PROG.UNT, LBA 230526, 250 sectors = 512,000 bytes)
  Decimal byte offset in Entry 8: 74,380 (0x1228C)
  Sector offset: 74380 // 2048 = 36 sectors (offset in sector = 652)
  Disc LBA: 229020 + 1506 + 36 = 230562
  Span: 33 sectors (LBA 230562..230594 inclusive)

TIM format:
  Uncompressed 8bpp TIM of exactly 66,080 bytes:
    - Magic 0x00000010, Flags 0x00000009 (8bpp with CLUT)
    - CLUT block: len=524, cx=0, cy=0, cw=256, ch=1, 256 BGR555 colors
    - Image block: len=65548, dx=896, dy=0, w_words=128, h_px=256, 65,536 pixel bytes
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "patch_repo") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from localization import unt_lz
    from localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        read_extent,
        replace_extent_in_place,
    )
except ImportError:
    from patch_repo.localization import unt_lz
    from patch_repo.localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        USER_DATA_OFFSET,
        USER_DATA_SIZE,
        read_extent,
        replace_extent_in_place,
    )

# PS1 Disc layout constants
PROG_LBA = 229020
ENTRY_8_SECTOR_OFFSET = 1506
ENTRY_8_LBA = PROG_LBA + ENTRY_8_SECTOR_OFFSET  # 230526
ENTRY_8_SECTOR_COUNT = 250
ENTRY_8_BYTE_OFFSET = 74380  # 0x1228C

TIM_SECTOR_OFFSET = ENTRY_8_BYTE_OFFSET // USER_DATA_SIZE  # 36
TIM_IN_SECTOR_OFFSET = ENTRY_8_BYTE_OFFSET % USER_DATA_SIZE  # 652
TIM_START_LBA = ENTRY_8_LBA + TIM_SECTOR_OFFSET  # 230562
TIM_SECTOR_COUNT = 33  # Spans 33 sectors (LBA 230562..230594)
TIM_END_LBA = TIM_START_LBA + TIM_SECTOR_COUNT - 1  # 230594

TOTAL_EXTENT_BYTES = TIM_SECTOR_COUNT * USER_DATA_SIZE  # 67,584 bytes
# BASYOG.UNT Entry 160 layout constants (In-Town / In-Room HUD atlas)
BASYOG_LBA = 233328
ENTRY_160_OFFSET = 6024
ENTRY_160_SECTOR_OFFSET = 6024
ENTRY_160_LBA = BASYOG_LBA + ENTRY_160_OFFSET  # 239352
ENTRY_160_SECTORS = 7
ENTRY_160_BUDGET = ENTRY_160_SECTORS * USER_DATA_SIZE  # 14,336 bytes

# DATE Log Widget dimensions and geometry
DATE_WIDGET_WIDTH = 56
DATE_WIDGET_HEIGHT = 40
DATE_WIDGET_SRC_BOX = (80, 80, 80 + DATE_WIDGET_WIDTH, 80 + DATE_WIDGET_HEIGHT)  # (80, 80, 136, 120)
DATE_WIDGET_DST_X = 176
DATE_WIDGET_DST_Y = 32
DATE_WIDGET_DST_POS = (DATE_WIDGET_DST_X, DATE_WIDGET_DST_Y)

FALLBACK_ENTRY_160_CLUT = bytes.fromhex(
    "0c020000000000000001010000004288638c849008a14aa9adb5efbd52cab5d6"
    "f7de7bef1f800e994584898867840c998888cc8cf4b179bed3adc9905099aa88"
    "338d8984a88c9891ee88148190a50c95f7a5ec8c97915fdb99c2d5a12e95b49d"
    "3ba6939972952f910e8dcb88ed88dfba3d9adb8998c214b250916f9959a69fe3"
    "b0a56e9d4c9975b6b08d7dcfe88c33967ccfd7ba3b8f5ba79da7d79e538a94ca"
    "29a19ce731be18d7adadc694ffbfffaf6b85bd87c68050a38c9ae891458908c2"
    "89b552ff11f7d0ee99ff71d68fe6f5ea07ed29b96bfde7e863d421ac00c0c7e0"
    "6ce911f2d7feffc95bb19fb9b79813841fa59f942084ffff9fb91fa59f942184"
    "4288849000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000"
)

FALLBACK_ENTRY_8_CLUT = bytes.fromhex(
    "00004288638c8490e79c08a14aa9adb531c652ca94d2f7de18e30b800e994584"
    "89886784d3ad5099aa88338d89849891ee880c95f7a5ec8c5fdb99c2d5a12e95"
    "b49d939972952f910e8dcb887fdf50919fe36e9d65800d817181c980d58175b6"
    "7dcf78827ccf1b833b8f538adf83ffc7ffbf7b93738a6b85bd87c680619c61a4"
    "61ac62a4cee96bd908c5a5b421acc7e032fe6ce911f2d7fe1fda5fb99f985890"
    "31882184ffff0000218442888490000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)

# TIM Geometry constants
TIM_WIDTH = 256
TIM_HEIGHT = 256
CLUT_BLOCK_SIZE = 524
CLUT_COLORS = 256
IMAGE_HEADER_SIZE = 12
IMAGE_BLOCK_SIZE = IMAGE_HEADER_SIZE + (TIM_WIDTH * TIM_HEIGHT)  # 65548
PIXEL_DATA_SIZE = TIM_WIDTH * TIM_HEIGHT  # 65536
UNCOMPRESSED_TIM_SIZE = 8 + CLUT_BLOCK_SIZE + IMAGE_BLOCK_SIZE  # 66080

# Default paths
DEFAULT_PRIMARY_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SECONDARY_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_CUSTOM_HUD_DIR = REPO_ROOT / "data" / "custom_hud_textures"
DEFAULT_PREVIEW_PNG = REPO_ROOT / "data" / "preview_e8_74380.png"
DEFAULT_TEXUPLOAD_PNG = REPO_ROOT / "texupload-P8-64A26A6A54DEBDE7-66A1C455B1C22E08-128x256-0-16-256x225-P0-85.png"


def find_candidate_image(
    custom_image: Path | str | None = None,
    custom_dir: Path | str | None = None,
) -> Path | None:
    """Find the custom HUD PNG to inject based on configuration and search hierarchy."""
    if custom_image is not None:
        p = Path(custom_image)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Specified image file not found: {custom_image}")

    hud_dir = Path(custom_dir) if custom_dir is not None else DEFAULT_CUSTOM_HUD_DIR

    # 1. Look for standard names in custom_hud_textures directory
    if hud_dir.is_dir():
        for name in ("e8_74380.png", "preview_e8_74380.png"):
            cand = hud_dir / name
            if cand.is_file():
                return cand

        # Any other PNG in custom_hud_textures directory
        pngs = sorted(hud_dir.glob("*.png")) + sorted(hud_dir.glob("*.PNG"))
        if pngs:
            return pngs[0]

    # 2. DuckStation dump fallback in root directory is deprecated/removed
    # to avoid accidentally picking up unaligned/shifted files.
    return None


def image_to_e8_tim(img_source: Path | str | Image.Image) -> bytes:
    """Convert paletted or RGBA PNG to exact 66,080-byte 8bpp TIM.

    Handles:
    - Mode 'P' (paletted): extracts palette, fits into 256x256 canvas (padding extra height with 0),
      and constructs 256-color BGR555 CLUT preserving canonical CLUT when matching.
    - Mode 'RGB' / 'RGBA': If 256x256 atlas based on canonical Entry 8, preserves canonical CLUT
      and existing sprite indices, mapping only the DATE widget.
      Otherwise quantizes to at most 256 colors with transparency support.
    """
    if isinstance(img_source, (str, Path)):
        src_path = Path(img_source)
        if not src_path.is_file():
            raise FileNotFoundError(f"Source image not found: {src_path}")
        img = Image.open(src_path)
    else:
        img = img_source

    canonical_clut_bytes = extract_canonical_e8_clut()
    canonical_clut_words = [
        struct.unpack_from("<H", canonical_clut_bytes, i * 2)[0] for i in range(CLUT_COLORS)
    ]

    if img.mode == "P":
        pal = list(img.getpalette() or [])
        trans_idx = img.info.get("transparency")
        if isinstance(trans_idx, (bytes, bytearray)) and len(trans_idx) > 0:
            trans_idx = trans_idx[0]
        elif not isinstance(trans_idx, int):
            trans_idx = None

        # Verify 1:1 canvas alignment for 256x256 images
        if img.size == (TIM_WIDTH, TIM_HEIGHT):
            canvas = img.copy()
        else:
            canvas = Image.new("P", (TIM_WIDTH, TIM_HEIGHT), 0)
            canvas.putpalette(pal)
            canvas.paste(img, (0, 0))
        pixel_bytes = np.array(canvas, dtype=np.uint8).tobytes()

        # Build CLUT entries
        pal_len = len(pal) // 3
        while len(pal) < CLUT_COLORS * 3:
            pal.extend([0, 0, 0])

        clut_words: list[int] = []
        for i in range(CLUT_COLORS):
            r5 = (pal[i * 3] >> 3) & 0x1F
            g5 = (pal[i * 3 + 1] >> 3) & 0x1F
            b5 = (pal[i * 3 + 2] >> 3) & 0x1F

            if trans_idx is not None and i == trans_idx:
                word = 0x0000
            elif r5 == 0 and g5 == 0 and b5 == 0:
                word = 0x0000
            else:
                word = 0x8000 | (b5 << 10) | (g5 << 5) | r5
            clut_words.append(word)
    else:
        # RGB or RGBA mode
        # Verify 1:1 canvas alignment for 256x256 images
        if img.size == (TIM_WIDTH, TIM_HEIGHT):
            canvas = img.convert("RGBA")
        else:
            canvas = Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))
            canvas.paste(img.convert("RGBA"), (0, 0))

        # Check if source is based on canonical Entry 8 atlas
        base_tim = extract_entry_8_tim()
        is_canonical_atlas = False
        if base_tim is not None and len(base_tim) == UNCOMPRESSED_TIM_SIZE:
            base_pixels = np.frombuffer(base_tim[544:], dtype=np.uint8).reshape((TIM_HEIGHT, TIM_WIDTH)).copy()
            arr = np.array(canvas)
            can_rgb: list[tuple[int, int, int] | None] = []
            for w in canonical_clut_words:
                if w == 0:
                    can_rgb.append(None)
                else:
                    can_rgb.append((((w & 0x1F) << 3), (((w >> 5) & 0x1F) << 3), (((w >> 10) & 0x1F) << 3)))

            matches = 0
            samples = [(80, 20), (60, 60), (50, 200), (20, 100), (10, 150), (100, 16)]
            for sx, sy in samples:
                b_idx = base_pixels[sy, sx]
                c_pix = arr[sy, sx]
                if b_idx == 0 and c_pix[3] < 128:
                    matches += 1
                elif b_idx != 0 and c_pix[3] >= 128 and can_rgb[b_idx] is not None:
                    if max(abs(int(c_pix[c]) - int(can_rgb[b_idx][c])) for c in range(3)) <= 12:
                        matches += 1
            if matches == len(samples):
                is_canonical_atlas = True

        if is_canonical_atlas and base_tim is not None:
            # Preserve canonical CLUT and all existing sprites outside widget box
            clut_words = list(canonical_clut_words)
            base_pixels = np.frombuffer(base_tim[544:], dtype=np.uint8).reshape((TIM_HEIGHT, TIM_WIDTH)).copy()
            arr = np.array(canvas)

            color_cache: dict[tuple[int, int, int], int] = {}
            def map_color(rgb: tuple[int, int, int]) -> int:
                if rgb in color_cache:
                    return color_cache[rgb]
                r, g, b = rgb
                best_idx = 0
                best_dist = float("inf")
                for idx, c in enumerate(can_rgb):
                    if c is not None:
                        dist = (r - c[0]) ** 2 + (g - c[1]) ** 2 + (b - c[2]) ** 2
                        if dist < best_dist:
                            best_dist = dist
                            best_idx = idx
                            if dist == 0:
                                break
                color_cache[rgb] = best_idx
                return best_idx

            bx0, by0, bx1, by1 = DATE_WIDGET_SRC_BOX
            for y in range(by0, by1):
                for x in range(bx0, bx1):
                    a = arr[y, x, 3]
                    if a < 128:
                        base_pixels[y, x] = 0
                    else:
                        base_pixels[y, x] = map_color((int(arr[y, x, 0]), int(arr[y, x, 1]), int(arr[y, x, 2])))
            pixel_bytes = base_pixels.tobytes()
        else:
            # Synthetic / general RGBA image fallback (used by unit tests)
            arr = np.array(canvas)
            alpha = arr[:, :, 3]
            has_trans = np.any(alpha < 128)

            if has_trans:
                opaque_mask = alpha >= 128
                rgb_canvas = canvas.convert("RGB")
                img_p = rgb_canvas.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
                pal = img_p.getpalette() or []
                while len(pal) < 255 * 3:
                    pal.extend([0, 0, 0])

                p_arr = np.array(img_p, dtype=np.uint8)
                mapped = np.zeros((TIM_WIDTH, TIM_HEIGHT), dtype=np.uint8)
                mapped[opaque_mask] = p_arr[opaque_mask] + 1

                clut_words = [0x0000]
                for i in range(255):
                    r5 = (pal[i * 3] >> 3) & 0x1F
                    g5 = (pal[i * 3 + 1] >> 3) & 0x1F
                    b5 = (pal[i * 3 + 2] >> 3) & 0x1F
                    word = 0x8000 | (b5 << 10) | (g5 << 5) | r5
                    clut_words.append(word)

                pixel_bytes = mapped.tobytes()
            else:
                img_p = canvas.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)
                pal = img_p.getpalette() or []
                while len(pal) < 256 * 3:
                    pal.extend([0, 0, 0])

                clut_words = []
                for i in range(CLUT_COLORS):
                    r5 = (pal[i * 3] >> 3) & 0x1F
                    g5 = (pal[i * 3 + 1] >> 3) & 0x1F
                    b5 = (pal[i * 3 + 2] >> 3) & 0x1F
                    word = 0x8000 | (b5 << 10) | (g5 << 5) | r5
                    clut_words.append(word)

                pixel_bytes = np.array(img_p, dtype=np.uint8).tobytes()

    if len(pixel_bytes) != PIXEL_DATA_SIZE:
        raise ValueError(
            f"Pixel data size {len(pixel_bytes)} does not match {PIXEL_DATA_SIZE}"
        )
    if len(clut_words) != CLUT_COLORS:
        raise ValueError(f"CLUT word count {len(clut_words)} does not match {CLUT_COLORS}")

    # Build TIM binary
    tim_header = struct.pack("<II", 0x10, 0x09)
    clut_block = struct.pack("<IHHHH", CLUT_BLOCK_SIZE, 0, 0, 256, 1) + struct.pack(
        "<256H", *clut_words
    )
    image_header = struct.pack("<IHHHH", IMAGE_BLOCK_SIZE, 896, 0, 128, 256)
    tim_bytes = tim_header + clut_block + image_header + pixel_bytes

    if len(tim_bytes) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(
            f"Generated TIM size {len(tim_bytes)} does not match expected {UNCOMPRESSED_TIM_SIZE}"
        )
    return tim_bytes


def e8_tim_to_image(tim_bytes: bytes) -> Image.Image:
    """Decode 66,080-byte 8bpp TIM binary into 256x256 RGBA Image."""
    if len(tim_bytes) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(
            f"Invalid TIM size: {len(tim_bytes)} bytes (expected {UNCOMPRESSED_TIM_SIZE})"
        )

    magic, flags = struct.unpack_from("<II", tim_bytes, 0)
    if magic != 0x10 or flags != 0x09:
        raise ValueError(f"Invalid TIM header: magic=0x{magic:08X}, flags=0x{flags:08X}")

    clut_words = [struct.unpack_from("<H", tim_bytes, 20 + i * 2)[0] for i in range(256)]
    pixel_data = np.frombuffer(tim_bytes[544 : 544 + PIXEL_DATA_SIZE], dtype=np.uint8).reshape(
        (TIM_HEIGHT, TIM_WIDTH)
    )

    rgba = np.zeros((TIM_HEIGHT, TIM_WIDTH, 4), dtype=np.uint8)
    for y in range(TIM_HEIGHT):
        for x in range(TIM_WIDTH):
            idx = pixel_data[y, x]
            w = clut_words[idx]
            if w == 0:
                rgba[y, x] = [0, 0, 0, 0]
            else:
                r = (w & 0x1F) << 3
                g = ((w >> 5) & 0x1F) << 3
                b = ((w >> 10) & 0x1F) << 3
                rgba[y, x] = [r, g, b, 255]

    return Image.fromarray(rgba, "RGBA")


def get_candidate_bins(target_bin: Path | str | None = None) -> list[Path]:
    """List potential candidate disc images to source original Entry 160."""
    candidates: list[Path] = []
    if target_bin is not None:
        p = Path(target_bin)
        if p.is_file():
            candidates.append(p)
    for p in (
        REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
        REPO_ROOT / "downloads" / "sr.bin",
        DEFAULT_SECONDARY_BIN,
        DEFAULT_PRIMARY_BIN,
    ):
        if p.is_file() and p not in candidates:
            candidates.append(p)
    return candidates


def extract_entry_160_tim(candidate_bins: Sequence[Path | str] | None = None) -> bytes:
    """Extract original decompressed 66,080-byte 8bpp TIM from candidate disc images."""
    candidates = list(candidate_bins) if candidate_bins else get_candidate_bins()
    for cand in candidates:
        p = Path(cand)
        if not p.is_file():
            continue
        try:
            if p.stat().st_size < (ENTRY_160_LBA + ENTRY_160_SECTORS) * RAW_SECTOR_SIZE:
                continue
            raw = read_extent(p, ENTRY_160_LBA, ENTRY_160_BUDGET)
            decomp, consumed = unt_lz.decompress(raw)
            if len(decomp) == UNCOMPRESSED_TIM_SIZE and decomp[:8] == b"\x10\x00\x00\x00\x09\x00\x00\x00":
                return decomp
        except Exception:
            continue

    # Fallback to constructing synthetic Entry 160 TIM with canonical CLUT
    tim_header = b"\x10\x00\x00\x00\x09\x00\x00\x00"
    img_header = struct.pack("<IHHHH", IMAGE_HEADER_SIZE + PIXEL_DATA_SIZE, 896, 0, TIM_WIDTH // 2, TIM_HEIGHT)
    return tim_header + FALLBACK_ENTRY_160_CLUT + img_header + bytes(PIXEL_DATA_SIZE)


def extract_entry_8_tim(candidate_bins: Sequence[Path | str] | None = None) -> bytes | None:
    """Extract original decompressed 66,080-byte 8bpp TIM from candidate disc images."""
    candidates = list(candidate_bins) if candidate_bins else get_candidate_bins()
    for cand in candidates:
        p = Path(cand)
        if not p.is_file():
            continue
        try:
            if p.stat().st_size < (TIM_START_LBA + TIM_SECTOR_COUNT) * RAW_SECTOR_SIZE:
                continue
            extent = read_extent(p, TIM_START_LBA, TOTAL_EXTENT_BYTES)
            tim = extent[TIM_IN_SECTOR_OFFSET : TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE]
            if len(tim) == UNCOMPRESSED_TIM_SIZE and tim[:8] == b"\x10\x00\x00\x00\x09\x00\x00\x00":
                return tim
        except Exception:
            continue
    return None


def extract_canonical_e8_clut(candidate_bins: Sequence[Path | str] | None = None) -> bytes:
    """Extract canonical 512-byte Entry 8 CLUT from candidate disc images or fallback."""
    tim = extract_entry_8_tim(candidate_bins)
    if tim is not None and len(tim) == UNCOMPRESSED_TIM_SIZE:
        clut = tim[20 : 20 + CLUT_BLOCK_SIZE - 12]
        if len(clut) == CLUT_COLORS * 2:
            return clut
    return FALLBACK_ENTRY_8_CLUT


def patch_basyog_entry_160_tim(
    orig_tim: bytes,
    custom_hud_source: Path | str | Image.Image,
) -> tuple[bytes, bytes]:
    """Patch the 56x40 DATE widget from custom HUD texture into Entry 160 TIM.

    Args:
        orig_tim: Original decompressed 66,080-byte TIM.
        custom_hud_source: Path to custom HUD PNG or PIL Image.

    Returns:
        tuple of (patched_uncompressed_tim, compressed_lzss_bytes).
    """
    if len(orig_tim) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(f"Invalid orig_tim size {len(orig_tim)}, expected {UNCOMPRESSED_TIM_SIZE}")

    if isinstance(custom_hud_source, (str, Path)):
        src_path = Path(custom_hud_source)
        if not src_path.is_file():
            raise FileNotFoundError(f"Custom HUD texture not found: {src_path}")
        hud_img = Image.open(src_path).convert("RGBA")
    elif isinstance(custom_hud_source, Image.Image):
        hud_img = custom_hud_source.convert("RGBA")
    else:
        raise TypeError(f"Unsupported custom_hud_source type: {type(custom_hud_source)}")
    if hud_img.width < DATE_WIDGET_SRC_BOX[2] or hud_img.height < DATE_WIDGET_SRC_BOX[3]:
        raise ValueError(
            f"Image dimensions {hud_img.size} too small to contain DATE widget bounding box {DATE_WIDGET_SRC_BOX}"
        )

    # Crop 56x40 DATE widget at (80, 80, 136, 120)
    widget = hud_img.crop(DATE_WIDGET_SRC_BOX)
    if widget.size != (DATE_WIDGET_WIDTH, DATE_WIDGET_HEIGHT):
        raise ValueError(f"Invalid widget size {widget.size}, expected ({DATE_WIDGET_WIDTH}, {DATE_WIDGET_HEIGHT})")

    # Extract 256-color CLUT from orig_tim (offset 20: 256 16-bit BGR555 words)
    clut_words = [struct.unpack_from("<H", orig_tim, 20 + i * 2)[0] for i in range(256)]
    clut_palette: list[tuple[int, int, int]] = []
    for w in clut_words:
        r = (w & 0x1F) << 3
        g = ((w >> 5) & 0x1F) << 3
        b = ((w >> 10) & 0x1F) << 3
        clut_palette.append((r, g, b))

    color_cache: dict[tuple[int, int, int], int] = {}

    def map_color(rgb: tuple[int, int, int]) -> int:
        if rgb in color_cache:
            return color_cache[rgb]
        r, g, b = rgb
        best_idx = 0
        best_dist = float("inf")
        for idx, (cr, cg, cb) in enumerate(clut_palette):
            dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = idx
                if dist == 0:
                    break
        color_cache[rgb] = best_idx
        return best_idx

    pixels = bytearray(orig_tim[8 + CLUT_BLOCK_SIZE + IMAGE_HEADER_SIZE :])
    widget_arr = np.array(widget)

    for y in range(DATE_WIDGET_HEIGHT):
        for x in range(DATE_WIDGET_WIDTH):
            r, g, b, a = widget_arr[y, x]
            if a < 128:
                idx = 0
            else:
                idx = map_color((int(r), int(g), int(b)))
            pixels[(DATE_WIDGET_DST_Y + y) * TIM_WIDTH + (DATE_WIDGET_DST_X + x)] = idx

    header = orig_tim[: 8 + CLUT_BLOCK_SIZE + IMAGE_HEADER_SIZE]
    new_tim = header + bytes(pixels)

    if len(new_tim) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(f"Assembled TIM size {len(new_tim)} does not match {UNCOMPRESSED_TIM_SIZE}")

    compressed = unt_lz.compress(new_tim)
    if len(compressed) > ENTRY_160_BUDGET:
        raise ValueError(
            f"Compressed BASYOG Entry 160 ({len(compressed)} B) exceeds 7-sector budget ({ENTRY_160_BUDGET} B)"
        )

    return new_tim, compressed


def patch_basyog_160(
    bin_path: Path | str,
    image_path: Path | str | None = None,
    dry_run: bool = False,
    update_secondary: bool = True,
) -> dict[str, Any]:
    """Patch BASYOG.UNT Entry 160 with DATE widget from custom HUD texture."""
    target_bin = Path(bin_path)
    if not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    resolved_image = find_candidate_image(image_path)
    if resolved_image is None:
        return {
            "status": "skipped",
            "reason": "No custom HUD texture candidate image found",
            "bin_path": str(target_bin),
        }

    orig_tim = extract_entry_160_tim([target_bin])
    new_tim, compressed = patch_basyog_entry_160_tim(orig_tim, resolved_image)

    payload = compressed.ljust(ENTRY_160_BUDGET, b"\x00")
    secondary_updated = False

    if not dry_run:
        replace_extent_in_place(target_bin, ENTRY_160_LBA, payload)
        if update_secondary and DEFAULT_SECONDARY_BIN.is_file():
            if DEFAULT_SECONDARY_BIN.resolve() != target_bin.resolve():
                replace_extent_in_place(DEFAULT_SECONDARY_BIN, ENTRY_160_LBA, payload)
                secondary_updated = True

    return {
        "status": "dry_run" if dry_run else "success",
        "image_path": str(resolved_image),
        "bin_path": str(target_bin),
        "secondary_bin_path": str(DEFAULT_SECONDARY_BIN) if secondary_updated else None,
        "lba": ENTRY_160_LBA,
        "end_lba": ENTRY_160_LBA + ENTRY_160_SECTORS - 1,
        "sectors": ENTRY_160_SECTORS,
        "tim_size": len(new_tim),
        "compressed_size": len(compressed),
        "budget": ENTRY_160_BUDGET,
        "margin": ENTRY_160_BUDGET - len(compressed),
        "dry_run": dry_run,
    }


def verify_basyog_160(bin_path: Path | str) -> dict[str, Any]:
    """Verify Mode 2 Form 1 EDC/ECC and TIM integrity of BASYOG.UNT Entry 160.

    Validates:
    1. Complete 7 sectors readable at LBA 239352..239358.
    2. Mode 2 Form 1 EDC and ECC P/Q checksums 100% valid on all 7 sectors.
    3. Valid unt_lz decompression consuming <= 14,336 bytes.
    4. Valid 8bpp TIM: exactly 66,080 bytes, 256x256 image, 256-color CLUT.
    """
    path = Path(bin_path)
    if not path.is_file():
        raise FileNotFoundError(f"Disc image not found: {bin_path}")

    checksums = CdChecksums()
    with path.open("rb") as f:
        for s in range(ENTRY_160_SECTORS):
            lba = ENTRY_160_LBA + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            if len(sec) != RAW_SECTOR_SIZE:
                raise ValueError(f"Incomplete sector at LBA {lba}: read {len(sec)} bytes")
            if sec[15] != 2:
                raise ValueError(f"Sector at LBA {lba} is not Mode 2 (mode byte={sec[15]})")

            edc = checksums.compute_edc(sec[0x10:0x818])
            if sec[0x818:0x81C] != edc:
                raise ValueError(f"EDC checksum mismatch at LBA {lba}")

            ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            if sec[0x81C:0x8C8] != ecc_p:
                raise ValueError(f"ECC P-parity mismatch at LBA {lba}")

            ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            if sec[0x8C8:0x930] != ecc_q:
                raise ValueError(f"ECC Q-parity mismatch at LBA {lba}")

    extent = read_extent(path, ENTRY_160_LBA, ENTRY_160_BUDGET)
    decomp, consumed = unt_lz.decompress(extent)

    if consumed > ENTRY_160_BUDGET:
        raise ValueError(f"Consumed bytes {consumed} exceeds budget {ENTRY_160_BUDGET}")
    if len(decomp) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(f"Decompressed TIM size {len(decomp)} != {UNCOMPRESSED_TIM_SIZE}")

    magic, flags = struct.unpack_from("<II", decomp, 0)
    if magic != 0x10 or flags != 0x09:
        raise ValueError(f"Invalid TIM header: magic=0x{magic:08X}, flags=0x{flags:08X}")

    clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", decomp, 8)
    if clut_len != CLUT_BLOCK_SIZE or clut_w != 256 or clut_h != 1:
        raise ValueError(f"Invalid CLUT header: len={clut_len}, w={clut_w}, h={clut_h}")

    img_offset = 8 + clut_len
    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", decomp, img_offset)
    if img_len != IMAGE_BLOCK_SIZE or img_w != TIM_WIDTH // 2 or img_h != TIM_HEIGHT:
        raise ValueError(f"Invalid Image header: len={img_len}, w={img_w}, h={img_h}")

    return {
        "status": "ok",
        "bin_path": str(path),
        "lba": ENTRY_160_LBA,
        "end_lba": ENTRY_160_LBA + ENTRY_160_SECTORS - 1,
        "sectors": ENTRY_160_SECTORS,
        "edc_ecc_valid": True,
        "edc_ecc_verified_sectors": ENTRY_160_SECTORS,
        "compressed_size": consumed,
        "budget": ENTRY_160_BUDGET,
        "margin": ENTRY_160_BUDGET - consumed,
        "decompressed_size": len(decomp),
        "clut_info": {"len": clut_len, "x": clut_x, "y": clut_y, "w": clut_w, "h": clut_h, "cw": clut_w, "ch": clut_h},
        "image_info": {"len": img_len, "x": img_x, "y": img_y, "w": img_w, "h": img_h},
    }

def verify_e8_textures(bin_path: Path | str) -> dict[str, Any]:
    """Verify Mode 2 Form 1 EDC/ECC and TIM integrity of Entry 8 offset 74,380.

    Validates:
    1. Complete 33 sectors readable at LBA 230562..230594.
    2. Mode 2 Form 1 EDC and ECC P/Q checksums 100% valid on all 33 sectors.
    3. Valid 8bpp TIM at byte offset 652 within sector 36.
    4. Exact dimensions: 256x256 pixels, 256-color CLUT, dx=896, dy=0, cx=0, cy=0.
    """
    path = Path(bin_path)
    if not path.is_file():
        raise FileNotFoundError(f"Disc image not found: {bin_path}")

    checksums = CdChecksums()
    with path.open("rb") as f:
        for s in range(TIM_SECTOR_COUNT):
            lba = TIM_START_LBA + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            if len(sec) != RAW_SECTOR_SIZE:
                raise ValueError(f"Incomplete sector at LBA {lba}: read {len(sec)} bytes")
            if sec[15] != 2:
                raise ValueError(f"Sector at LBA {lba} is not Mode 2 (mode byte={sec[15]})")

            edc = checksums.compute_edc(sec[0x10:0x818])
            if sec[0x818:0x81C] != edc:
                raise ValueError(
                    f"EDC checksum mismatch at LBA {lba} (expected {sec[0x818:0x81C].hex()}, computed {edc.hex()})"
                )

            ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            if sec[0x81C:0x8C8] != ecc_p:
                raise ValueError(f"ECC P-parity mismatch at LBA {lba}")

            ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            if sec[0x8C8:0x930] != ecc_q:
                raise ValueError(f"ECC Q-parity mismatch at LBA {lba}")

    extent = read_extent(path, TIM_START_LBA, TOTAL_EXTENT_BYTES)
    tim = extent[TIM_IN_SECTOR_OFFSET : TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE]

    if len(tim) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(
            f"Extracted TIM size {len(tim)} does not match expected {UNCOMPRESSED_TIM_SIZE}"
        )

    magic, flags = struct.unpack_from("<II", tim, 0)
    if magic != 0x10 or flags != 0x09:
        raise ValueError(f"Invalid TIM header: magic=0x{magic:08X}, flags=0x{flags:08X}")

    clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim, 8)
    if (
        clut_len != CLUT_BLOCK_SIZE
        or clut_x != 0
        or clut_y != 0
        or clut_w != 256
        or clut_h != 1
    ):
        raise ValueError(
            f"Invalid CLUT header: len={clut_len}, x={clut_x}, y={clut_y}, w={clut_w}, h={clut_h}"
        )

    img_offset = 8 + clut_len
    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim, img_offset)
    if (
        img_len != IMAGE_BLOCK_SIZE
        or img_x != 896
        or img_y != 0
        or img_w != TIM_WIDTH // 2
        or img_h != TIM_HEIGHT
    ):
        raise ValueError(
            f"Invalid Image header: len={img_len}, x={img_x}, y={img_y}, w={img_w}, h={img_h}"
        )

    res = {
        "status": "ok",
        "bin_path": str(path),
        "lba": TIM_START_LBA,
        "end_lba": TIM_END_LBA,
        "sectors": TIM_SECTOR_COUNT,
        "edc_ecc_valid": True,
        "edc_ecc_verified_sectors": TIM_SECTOR_COUNT,
        "tim_size": len(tim),
        "clut_info": {"len": clut_len, "x": clut_x, "y": clut_y, "w": clut_w, "h": clut_h, "cw": clut_w, "ch": clut_h},
        "image_info": {"len": img_len, "x": img_x, "y": img_y, "w": img_w, "h": img_h},
    }

    if path.stat().st_size >= (ENTRY_160_LBA + ENTRY_160_SECTORS) * RAW_SECTOR_SIZE:
        basyog_res = verify_basyog_160(path)
        res["basyog_160"] = basyog_res

    return res


def dump_e8_texture(bin_path: Path | str, dump_dir: Path | str) -> list[Path]:
    """Dump HUD texture atlas from disc image to PNG and raw TIM."""
    path = Path(bin_path)
    out_dir = Path(dump_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    extent = read_extent(path, TIM_START_LBA, TOTAL_EXTENT_BYTES)
    tim = extent[TIM_IN_SECTOR_OFFSET : TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE]

    img = e8_tim_to_image(tim)

    png_path = out_dir / "e8_74380.png"
    tim_path = out_dir / "e8_74380.tim"

    img.save(png_path)
    tim_path.write_bytes(tim)

    return [png_path, tim_path]


def patch_e8_textures(
    bin_path: Path | str,
    image_path: Path | str | None = None,
    dry_run: bool = False,
    update_secondary: bool = True,
    update_preview: bool = True,
    patch_basyog: bool = True,
    sync_savestates: bool = True,
) -> dict[str, Any]:
    """Inject custom PNG texture atlas into PROG.UNT Entry 8 and BASYOG.UNT Entry 160."""
    target_bin = Path(bin_path)
    if not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    resolved_image = find_candidate_image(image_path)
    if resolved_image is None:
        return {
            "status": "skipped",
            "reason": "No custom HUD texture candidate image found",
            "bin_path": str(target_bin),
        }

    tim_bytes = image_to_e8_tim(resolved_image)

    secondary_updated = False
    if not dry_run:
        # Read the complete 33-sector extent (67,584 bytes)
        extent = bytearray(read_extent(target_bin, TIM_START_LBA, TOTAL_EXTENT_BYTES))

        # Replace the 66,080 bytes of TIM starting at byte offset 652
        extent[TIM_IN_SECTOR_OFFSET : TIM_IN_SECTOR_OFFSET + UNCOMPRESSED_TIM_SIZE] = tim_bytes

        # Write back to primary disc with 100% valid Mode 2 Form 1 EDC/ECC repair
        replace_extent_in_place(target_bin, TIM_START_LBA, bytes(extent))

        # Update secondary disc image if requested and present
        if update_secondary and DEFAULT_SECONDARY_BIN.is_file():
            if DEFAULT_SECONDARY_BIN.resolve() != target_bin.resolve():
                replace_extent_in_place(DEFAULT_SECONDARY_BIN, TIM_START_LBA, bytes(extent))
                secondary_updated = True

        # Update preview PNG if requested
        if update_preview:
            try:
                DEFAULT_PREVIEW_PNG.parent.mkdir(parents=True, exist_ok=True)
                preview_img = e8_tim_to_image(tim_bytes)
                preview_img.save(DEFAULT_PREVIEW_PNG)
            except Exception as exc:
                print(f"Warning: Failed to update preview PNG {DEFAULT_PREVIEW_PNG}: {exc}", file=sys.stderr)

    # Patch BASYOG.UNT Entry 160 (Town & Room HUD texture atlas)
    basyog_result = None
    if patch_basyog and target_bin.stat().st_size >= (ENTRY_160_LBA + ENTRY_160_SECTORS) * RAW_SECTOR_SIZE:
        basyog_result = patch_basyog_160(
            bin_path=target_bin,
            image_path=resolved_image,
            dry_run=dry_run,
            update_secondary=update_secondary,
        )

    # Synchronize DuckStation savestates VRAM
    savestate_reports: list[dict[str, Any]] = []
    if not dry_run and sync_savestates:
        try:
            from tools.sync_savestates import sync_all_hud_savestates
            savestate_reports = sync_all_hud_savestates(bin_path=target_bin)
        except Exception as exc:
            print(f"Warning: Savestate synchronization skipped or failed: {exc}", file=sys.stderr)

    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "image_path": str(resolved_image),
        "bin_path": str(target_bin),
        "secondary_bin_path": str(DEFAULT_SECONDARY_BIN) if secondary_updated else None,
        "lba": TIM_START_LBA,
        "end_lba": TIM_END_LBA,
        "sectors": TIM_SECTOR_COUNT,
        "tim_size": len(tim_bytes),
        "dry_run": dry_run,
    }
    if basyog_result is not None:
        result["basyog_160"] = basyog_result
    if savestate_reports:
        result["savestates"] = savestate_reports
    return result

def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch and validate Overworld HUD texture atlas (PROG.UNT Entry 8, 74,380) for Slayers Royal (PS1)."
    )
    default_bin = DEFAULT_PRIMARY_BIN if DEFAULT_PRIMARY_BIN.is_file() else DEFAULT_SECONDARY_BIN
    parser.add_argument(
        "--bin",
        type=Path,
        default=default_bin,
        help=f"Path to target PS1 CD-ROM BIN image (default: {default_bin})",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help="Path to custom PNG image to inject (defaults to checking data/custom_hud_textures/)",
    )
    parser.add_argument(
        "--dump-dir",
        type=Path,
        default=None,
        help="Dump current HUD texture from disc as PNG and TIM to the specified directory",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify Mode 2 Form 1 EDC/ECC and TIM integrity on target disc",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate encoding and patching without writing to disc",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Do not update data/preview_e8_74380.png after patching",
    )
    parser.add_argument(
        "--no-basyog",
        action="store_true",
        help="Do not patch BASYOG.UNT Entry 160",
    )
    parser.add_argument(
        "--no-savestates",
        action="store_true",
        help="Do not synchronize DuckStation savestates",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dump_dir is not None:
        print(f"[*] Dumping Overworld HUD texture from {args.bin} to {args.dump_dir}...")
        try:
            dumped = dump_e8_texture(args.bin, args.dump_dir)
            for p in dumped:
                print(f"  - Dumped: {p}")
            print(f"[✓] Successfully dumped {len(dumped)} files.")
            return 0
        except Exception as exc:
            print(f"[!] Dump failed: {exc}", file=sys.stderr)
            return 1

    if args.verify:
        print(f"[*] Verifying Overworld HUD texture atlas on {args.bin}...")
        try:
            result = verify_e8_textures(args.bin)
            print(f"[✓] Verification SUCCESSFUL for PROG.UNT Entry 8 offset 74,380:")
            print(f"  - Target image:      {result['bin_path']}")
            print(f"  - Disc LBA range:    {result['lba']}..{result['end_lba']} ({result['sectors']} sectors)")
            print(f"  - Mode 2 Form 1:     100% valid EDC/ECC on all {result['edc_ecc_verified_sectors']} sectors")
            print(f"  - TIM binary size:   {result['tim_size']} bytes (256x256 8bpp)")
            print(f"  - CLUT properties:   len={result['clut_info']['len']}, cx={result['clut_info']['x']}, cy={result['clut_info']['y']}, cw={result['clut_info']['w']}, ch={result['clut_info']['h']}")
            print(f"  - Image properties:  len={result['image_info']['len']}, dx={result['image_info']['x']}, dy={result['image_info']['y']}, w={result['image_info']['w']} words, h={result['image_info']['h']}")
            if "basyog_160" in result and result["basyog_160"].get("status") == "ok":
                b = result["basyog_160"]
                print(f"[✓] Verification SUCCESSFUL for BASYOG.UNT Entry 160 (LBA {b['lba']}..{b['end_lba']}):")
                print(f"  - Mode 2 Form 1:     100% valid EDC/ECC on all {b['edc_ecc_verified_sectors']} sectors")
                print(f"  - Compressed stream: {b['compressed_size']:,} bytes (budget: {b['budget']:,} bytes, margin: {b['margin']:,} bytes)")
                print(f"  - TIM binary size:   {b['decompressed_size']:,} bytes (256x256 8bpp)")
            return 0
        except Exception as exc:
            print(f"[!] Verification FAILED: {exc}", file=sys.stderr)
            return 1

    # Patch mode
    print(f"[*] Patching Overworld HUD texture atlas in {args.bin}...")
    try:
        result = patch_e8_textures(
            bin_path=args.bin,
            image_path=args.image,
            dry_run=args.dry_run,
            update_preview=not args.no_preview,
            patch_basyog=not args.no_basyog,
            sync_savestates=not args.no_savestates,
        )
        if result["status"] == "skipped":
            print(f"[-] Patch skipped: {result['reason']}")
            return 0

        mode_str = "DRY RUN" if result.get("dry_run") else "SUCCESS"
        print(f"[{mode_str}] Successfully patched Overworld HUD texture atlas (PROG.UNT Entry 8):")
        print(f"  - Source image:      {result['image_path']}")
        print(f"  - Target image:      {result['bin_path']}")
        if result.get("secondary_bin_path"):
            print(f"  - Secondary image:   {result['secondary_bin_path']}")
        print(f"  - Disc LBA range:    {result['lba']}..{result['end_lba']} ({result['sectors']} sectors)")
        print(f"  - TIM binary size:   {result['tim_size']} bytes")
        if "basyog_160" in result and result["basyog_160"].get("status") in ("success", "dry_run"):
            b = result["basyog_160"]
            print(f"[{mode_str}] Successfully patched In-Town / In-Room HUD atlas (BASYOG.UNT Entry 160):")
            print(f"  - Disc LBA range:    {b['lba']}..{b['end_lba']} ({b['sectors']} sectors)")
            print(f"  - Compressed stream: {b['compressed_size']:,} bytes (budget: {b['budget']:,} bytes, margin: {b['margin']:,} bytes)")
        if result.get("savestates"):
            synced_count = sum(1 for s in result["savestates"] if s.get("hud_vram_updated"))
            print(f"  - Savestates synced: {synced_count} active DuckStation savestate(s) updated with new HUD VRAM")
        return 0
    except Exception as exc:
        print(f"[!] Patch FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
