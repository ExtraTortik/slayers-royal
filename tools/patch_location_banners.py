#!/usr/bin/env python3
"""Slayers Royal (PS1) - BASYOG.UNT Entry 466 Location Banners Patcher.

Entry 466 (LBA 240133..240140, 8 sectors = 16,384 bytes compressed budget)
contains the visual location banners displayed when entering town areas and
buildings in Slayers Royal.

Uncompressed format:
- PlayStation 1 4bpp TIM image (magic 0x10, flag 0x08)
- 16-color CLUT at VRAM (0, 480)
- 256x224 pixels (64 words x 224 lines) at VRAM (0, 0)
- Total uncompressed size: 28,736 bytes (8 header + 44 CLUT + 12 image header + 28,672 pixel data)

This tool patches the English location banners with Cyrillic translations:
  - "MAIN ST"      -> "ГЛАВНАЯ УЛ."
  - "PLAZA"        -> "ПЛОЩАДЬ"
  - "BACK ST"      -> "ЗАКОУЛКИ"
  - "TAVERN"       -> "ТАВЕРНА"
  - "INN"          -> "ГОСТИНИЦА"
  - "BAR"          -> "БАР"
  - "ARMORY"       -> "ОРУЖЕЙНАЯ"
  - "CHURCH"       -> "ЦЕРКОВЬ"
  - "OUTSKIRTS"    -> "ОКРАИНА"
  - "LEAVE TOWN"   -> "ВЫХОД"
  - "LARK'S HOUSE" -> "ДОМ ЛАРКА"
  - "ROYAL PALACE" -> "ДВОРЕЦ"
  - "MAYOR'S HOUSE"-> "ДОМ МЭРА"
  - "MAGE GUILD"   -> "ГИЛЬДИЯ МАГОВ"
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont
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
ENTRY_466_LBA = 240133
ENTRY_466_SECTOR_COUNT = 8
SECTOR_USER_SIZE = 2048
ENTRY_466_BUDGET_BYTES = ENTRY_466_SECTOR_COUNT * SECTOR_USER_SIZE  # 16,384 bytes
UNCOMPRESSED_TIM_SIZE = 28736  # 8 + 44 + 12 + 28,672 bytes

TIM_WIDTH = 256
TIM_HEIGHT = 224
TIM_HEADER = b"\x10\x00\x00\x00\x08\x00\x00\x00"
DEFAULT_TRANSLATIONS = REPO_ROOT / "translations" / "location_banners_ru.json"


def load_banner_translations(path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """Load banner translations and typography specs from JSON catalog with fallback to defaults."""
    target_path = Path(path) if path else DEFAULT_TRANSLATIONS
    res: dict[str, dict[str, Any]] = {
        k: {
            "text_ru": v,
            "font_size": "auto",
            "align": "center",
            "offset_x": 0,
            "offset_y": 0,
        }
        for k, v in BANNER_TRANSLATIONS.items()
    }
    if not target_path.is_file():
        return res
    try:
        doc = json.loads(target_path.read_text(encoding="utf-8"))
        banners_dict = doc.get("banners", doc)
        for key, val in banners_dict.items():
            if isinstance(val, dict):
                text = str(val.get("text_ru", BANNER_TRANSLATIONS.get(key, ""))).strip()
                fs = val.get("font_size", "auto")
                al = str(val.get("align", "center")).strip().lower()
                ox = int(val.get("offset_x", 0))
                oy = int(val.get("offset_y", 0))
                res[key] = {
                    "text_ru": text,
                    "font_size": fs,
                    "align": al,
                    "offset_x": ox,
                    "offset_y": oy,
                }
            elif isinstance(val, str):
                res[key] = {
                    "text_ru": val.strip(),
                    "font_size": "auto",
                    "align": "center",
                    "offset_x": 0,
                    "offset_y": 0,
                }
    except Exception as exc:
        print(f"Warning: Failed to parse {target_path} ({exc}), using defaults", file=sys.stderr)
    return res

# Original 16-color CLUT halfwords from Entry 466
LOCATION_BANNER_CLUT: list[int] = [
    0x0000, 0x4400, 0x3480, 0x40A0,
    0x2940, 0x4501, 0x1DE1, 0x1662,
    0x5183, 0x59C4, 0x6225, 0x76A7,
    0x7F69, 0x7FEC, 0x7FFF, 0x7FFF,
]

# Build RGBA representation of the CLUT entries
CLUT_RGBA: list[tuple[int, int, int, int]] = []
for _word in LOCATION_BANNER_CLUT:
    _r = (_word & 0x1F) << 3
    _g = ((_word >> 5) & 0x1F) << 3
    _b = ((_word >> 10) & 0x1F) << 3
    _a = 0 if _word == 0 else 255
    CLUT_RGBA.append((_r, _g, _b, _a))

# Text rendering palette assignments:
# Index 0: Transparent background
# Index 1: Dark outline (0x4400)
# Index 13: Bright cyan core (0x7FEC)
# Index 14: White core (0x7FFF)
OUTLINE_COLOR_RGBA = CLUT_RGBA[1]
CORE_COLOR_RGBA = CLUT_RGBA[13]

BANNER_TRANSLATIONS: dict[str, str] = {
    "MAIN ST": "ГЛАВНАЯ",
    "PLAZA": "ПЛОЩАДЬ",
    "BACK ST": "ЗАКОУЛКИ",
    "TAVERN": "ТАВЕРНА",
    "INN": "ОТЕЛЬ",
    "BAR": "БАР",
    "ARMORY": "ОРУЖЕЙНАЯ",
    "CHURCH": "ЦЕРКОВЬ",
    "CLIFF": "УТЁС",
    "TEMPLE": "ХРАМ",
    "OUTSKIRTS": "ОКРАИНА",
    "LEAVE TOWN": "ПОКИНУТЬ ГОРОД",
    "ELDER'S HOUSE": "СТАРОСТА",
    "LARK'S HOUSE": "ДОМ ЛАРКА",
    "ROYAL PALACE": "ДВОРЕЦ",
    "MAYOR'S HOUSE": "ДОМ МЭРА",
    "MAGE GUILD": "ГИЛЬДИЯ",
    "PORT STALL": "ПРИСТАНЬ",
    "ROYAL LIBRARY": "БИБЛИОТЕКА",
    "MAGIC CLINIC": "ЛЕЧЕБНИЦА",
    "MARKET": "РЫНОК",
    "ITEM SHOP": "ЛАВКА",
    "MOUNTAIN CAVE": "ПЕЩЕРА",
}

# Layout specifications: (banner_key, translation_key, clear_bbox(x0, y0, x1, y1), draw_pos(x, y))
BANNER_LAYOUT: list[tuple[str, str, tuple[int, int, int, int], tuple[int, int]]] = [
    # Band 0 (Row 0): Y=0..24
    # MAIN ST sprite window is ~70px wide; "ГЛАВНАЯ" is 56px wide, perfectly centered without cutoff
    ("MAIN ST", "MAIN ST", (0, 0, 85, 24), (8, 6)),
    ("PLAZA", "PLAZA", (86, 0, 165, 24), (96, 6)),
    ("MAGE GUILD", "MAGE GUILD", (166, 0, 255, 24), (175, 6)),

    # Band 1 (Row 1): Y=24..48
    # BAR is at X=10..60. Clear up to X=74 to prevent bleeding into BAR's sprite window!
    ("BAR", "BAR", (0, 24, 74, 48), (22, 31)),
    # ARMORY starts at X=75
    ("ARMORY", "ARMORY", (75, 24, 155, 48), (78, 31)),
    # PORT STALL at X=156..255
    ("PORT STALL", "PORT STALL", (156, 24, 255, 48), (165, 31)),

    # Band 2 (Row 2): Y=48..72
    ("BACK ST", "BACK ST", (0, 48, 85, 72), (6, 55)),
    ("CHURCH", "CHURCH", (86, 48, 185, 72), (105, 55)),
    ("CLIFF", "CLIFF", (186, 48, 255, 72), (210, 55)),

    # Band 3 (Row 3): Y=72..96
    ("TAVERN", "TAVERN", (0, 72, 60, 96), (4, 79)),
    ("TEMPLE", "TEMPLE", (50, 72, 94, 96), (54, 79)),
    # LEAVE TOWN window is X=98..189 (91px wide).
    # "ПОКИНУТЬ ГОРОД" is 85px wide at font 6. Centered at X=101, Y=80!
    ("LEAVE TOWN", "LEAVE TOWN", (95, 72, 195, 96), (101, 80)),

    # Band 4 (Row 4): Y=96..120
    ("ELDER'S HOUSE", "ELDER'S HOUSE", (0, 96, 95, 120), (6, 103)),
    ("LARK'S HOUSE", "LARK'S HOUSE", (96, 96, 220, 120), (115, 103)),

    # Band 5 (Row 5): Y=120..144
    ("ROYAL LIBRARY", "ROYAL LIBRARY", (0, 120, 120, 144), (6, 127)),
    ("MAGIC CLINIC", "MAGIC CLINIC", (121, 120, 245, 144), (132, 127)),

    # Band 6 (Row 6): Y=144..168
    ("MARKET", "MARKET", (0, 144, 48, 168), (4, 151)),
    ("OUTSKIRTS", "OUTSKIRTS", (49, 144, 220, 168), (60, 151)),

    # Band 7 (Row 7): Y=168..192
    # INN is located at Band 7 (Y=168..192, X=0..82) in the original sheet!
    ("INN", "INN", (0, 168, 82, 192), (6, 175)),
    ("MAYOR'S HOUSE", "MAYOR'S HOUSE", (83, 168, 220, 192), (96, 175)),

    # Band 8 (Row 8): Y=192..216
    ("ITEM SHOP", "ITEM SHOP", (0, 192, 72, 216), (6, 199)),
    ("MOUNTAIN CAVE", "MOUNTAIN CAVE", (73, 192, 180, 216), (86, 199)),
]


def find_font_path(custom_path: Path | str | None = None) -> Path:
    """Locate PressStart2P.ttf font file."""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Custom font not found: {custom_path}")

    candidates = [
        REPO_ROOT / "fonts" / "PressStart2P.ttf",
        REPO_ROOT / "patch_repo" / "fonts" / "PressStart2P.ttf",
        Path("fonts/PressStart2P.ttf"),
    ]
    for c in candidates:
        if c.is_file():
            return c.resolve()
    raise FileNotFoundError("PressStart2P.ttf not found in repository.")


def get_base_image() -> Image.Image:
    """Retrieve base reference template (256x224 RGBA)."""
    en_preview = REPO_ROOT / "data" / "preview_basyog_466_en.png"
    if en_preview.is_file():
        return Image.open(en_preview).convert("RGBA")

    # Fallback to pristine disc images if preview_basyog_466_en.png is missing
    candidates = [
        REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
        REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "downloads" / "sr.bin",
    ]
    for disc_path in candidates:
        if disc_path.is_file():
            try:
                raw = read_extent(disc_path, ENTRY_466_LBA, ENTRY_466_BUDGET_BYTES)
                decomp, _ = unt_lz.decompress(raw)
                if len(decomp) == UNCOMPRESSED_TIM_SIZE:
                    return tim_to_image_4bpp(decomp)
            except Exception:
                pass

    # Create empty transparent canvas
    return Image.new("RGBA", (TIM_WIDTH, TIM_HEIGHT), (0, 0, 0, 0))

def render_cyrillic_banners(
    base_img: Image.Image,
    font_path: Path | str | None = None,
    translations: dict[str, Any] | None = None,
) -> Image.Image:
    """Render Cyrillic location banners onto base image template with auto-sizing and custom typography."""
    fpath = find_font_path(font_path)
    fonts = {sz: ImageFont.truetype(str(fpath), sz) for sz in (8, 7, 6, 5, 4)}
    trans_map = translations or load_banner_translations()
    patched_img = base_img.copy().convert("RGBA")
    draw = ImageDraw.Draw(patched_img)

    for banner_key, trans_key, (cx0, cy0, cx1, cy1), (dx, dy) in BANNER_LAYOUT:
        spec = trans_map.get(trans_key)
        if not spec:
            continue
        if isinstance(spec, str):
            spec = {"text_ru": spec, "font_size": "auto", "align": "center", "offset_x": 0, "offset_y": 0}

        text = spec.get("text_ru", "")
        if not text:
            continue

        box_w = cx1 - cx0
        box_h = cy1 - cy0
        req_fs = spec.get("font_size", "auto")
        align = spec.get("align", "center")
        off_x = int(spec.get("offset_x", 0))
        off_y = int(spec.get("offset_y", 0))

        # 1. Clear target bounding box (transparent)
        draw.rectangle([cx0, cy0, cx1, cy1], fill=(0, 0, 0, 0))

        # 2. Determine font size: explicit size or auto-sizing
        if isinstance(req_fs, int) and req_fs in fonts:
            chosen_font = fonts[req_fs]
            bb = draw.textbbox((0, 0), text, font=chosen_font)
            tw = bb[2] - bb[0]
            th = bb[3] - bb[1]
        else:
            # Auto-size (8 -> 7 -> 6 -> 5 -> 4)
            max_sz = 6 if banner_key == "LEAVE TOWN" else 8
            for sz in (8, 7, 6, 5, 4):
                if sz > max_sz:
                    continue
                f = fonts[sz]
                bb = draw.textbbox((0, 0), text, font=f)
                cand_w = bb[2] - bb[0]
                cand_h = bb[3] - bb[1]
                if cand_w <= box_w - 4:
                    chosen_font = f
                    tw = cand_w
                    th = cand_h
                    break
            else:
                chosen_font = fonts[4]
                bb = draw.textbbox((0, 0), text, font=chosen_font)
                tw = bb[2] - bb[0]
                th = bb[3] - bb[1]

        # 3. Calculate position with alignment and manual offsets
        if align == "left":
            base_x = cx0 + 2
        elif align == "right":
            base_x = cx1 - tw - 2
        else:  # center
            base_x = cx0 + max(2, (box_w - tw) // 2)

        base_y = cy0 + max(2, (box_h - th) // 2) - 1

        draw_x = base_x + off_x
        draw_y = base_y + off_y

        # 4. Draw 1px 8-way dark outline
        for ox, oy in [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]:
            draw.text((draw_x + ox, draw_y + oy), text, font=chosen_font, fill=OUTLINE_COLOR_RGBA)

        # 5. Draw bright cyan text core
        draw.text((draw_x, draw_y), text, font=chosen_font, fill=CORE_COLOR_RGBA)
    return patched_img


def image_to_4bpp_indices(
    img: Image.Image,
    clut_rgba: list[tuple[int, int, int, int]] | None = None,
    alpha_threshold: int = 32,
) -> bytes:
    """Map RGBA PIL image to packed 4bpp pixel bytes using the 16-color CLUT."""
    palette = clut_rgba or CLUT_RGBA
    w, h = img.size
    arr = np.array(img.convert("RGBA"))

    indices = np.zeros((h, w), dtype=np.uint8)
    alpha = arr[:, :, 3]
    opaque = alpha > alpha_threshold

    pal_rgb = np.array([c[:3] for c in palette[1:16]], dtype=np.float32)

    if np.any(opaque):
        px_rgb = arr[opaque, :3].astype(np.float32)
        diff = px_rgb[:, None, :] - pal_rgb[None, :, :]
        dist_sq = np.sum(diff ** 2, axis=2)
        best = np.argmin(dist_sq, axis=1) + 1  # 1..15
        indices[opaque] = best

    # Pack 4bpp: low nibble = even x, high nibble = odd x
    packed = bytearray((w * h) // 2)
    for y in range(h):
        for x in range(0, w, 2):
            low = indices[y, x] & 0x0F
            high = indices[y, x + 1] & 0x0F
            packed[y * (w // 2) + (x // 2)] = (high << 4) | low

    return bytes(packed)


def build_tim_4bpp(
    pixel_bytes: bytes,
    clut_words: list[int] | None = None,
    width: int = TIM_WIDTH,
    height: int = TIM_HEIGHT,
) -> bytes:
    """Construct PlayStation 1 4bpp TIM binary with header, CLUT, and image block."""
    palette = clut_words or LOCATION_BANNER_CLUT
    if len(palette) != 16:
        raise ValueError(f"CLUT must contain exactly 16 words, got {len(palette)}")

    expected_pixels = (width * height) // 2
    if len(pixel_bytes) != expected_pixels:
        raise ValueError(f"pixel_bytes len {len(pixel_bytes)} does not match {width}x{height} 4bpp")

    tim = bytearray()
    # TIM Header (8 bytes): magic 0x10, flag 0x08
    tim.extend(TIM_HEADER)

    # CLUT Block (44 bytes): length (4) + pos (4) + size (4) + 16 words (32)
    clut_len = 44
    clut_x, clut_y, clut_w, clut_h = 0, 480, 16, 1
    tim.extend(struct.pack("<IHHHH", clut_len, clut_x, clut_y, clut_w, clut_h))
    for cw in palette:
        tim.extend(struct.pack("<H", cw))

    # Image Block: length (4) + pos (4) + size (4) + pixel data
    img_len = 12 + len(pixel_bytes)
    img_x, img_y, img_w, img_h = 0, 0, width // 4, height
    tim.extend(struct.pack("<IHHHH", img_len, img_x, img_y, img_w, img_h))
    tim.extend(pixel_bytes)

    if len(tim) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(f"Unexpected TIM size {len(tim)} (expected {UNCOMPRESSED_TIM_SIZE})")

    return bytes(tim)


def tim_to_image_4bpp(tim_bytes: bytes) -> Image.Image:
    """Decode a 4bpp TIM binary file into an RGBA PIL Image."""
    if len(tim_bytes) < 64:
        raise ValueError("TIM data too short")
    if tim_bytes[:8] != TIM_HEADER:
        raise ValueError("Invalid TIM header")

    clut_len = struct.unpack_from("<I", tim_bytes, 8)[0]
    num_colors = (clut_len - 12) // 2
    clut = [struct.unpack_from("<H", tim_bytes, 20 + i * 2)[0] for i in range(num_colors)]

    rgba_pal: list[tuple[int, int, int, int]] = []
    for i, w in enumerate(clut):
        r = (w & 0x1F) << 3
        g = ((w >> 5) & 0x1F) << 3
        b = ((w >> 10) & 0x1F) << 3
        a = 0 if (i == 0 or w == 0) else 255
        rgba_pal.append((r, g, b, a))

    img_offset = 8 + clut_len
    _, _, _, img_w_words, img_h = struct.unpack_from("<IHHHH", tim_bytes, img_offset)
    width = img_w_words * 4
    height = img_h
    pixel_data = tim_bytes[img_offset + 12 : img_offset + 12 + (width * height) // 2]

    out_arr = np.zeros((height, width, 4), dtype=np.uint8)
    for y in range(height):
        for x in range(0, width, 2):
            b = pixel_data[y * (width // 2) + (x // 2)]
            c_low = rgba_pal[b & 0x0F]
            c_high = rgba_pal[(b >> 4) & 0x0F]
            out_arr[y, x] = c_low
            out_arr[y, x + 1] = c_high

    return Image.fromarray(out_arr, "RGBA")


def compress_entry_466(tim_bytes: bytes, mode: int = 1) -> bytes:
    """Compress TIM binary using unt_lz and pad to sector-aligned 8 sectors.

    Args:
        tim_bytes: Uncompressed 28,736-byte TIM data.
        mode: LZ compression mode (1 = Slayers Royal standard).

    Returns:
        16,384 bytes sector-padded compressed payload ready for disc injection.
    """
    if len(tim_bytes) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(f"Invalid uncompressed TIM size {len(tim_bytes)} (must be {UNCOMPRESSED_TIM_SIZE})")

    try:
        compressed = unt_lz.compress(tim_bytes, mode=mode)
    except TypeError:
        compressed = unt_lz.compress(tim_bytes)

    if len(compressed) > ENTRY_466_BUDGET_BYTES:
        raise ValueError(
            f"Compressed Entry 466 size ({len(compressed)} bytes) exceeds budget of "
            f"{ENTRY_466_BUDGET_BYTES} bytes (8 sectors)"
        )

    # Pad with 0x00 to complete 8 sectors (16,384 bytes) for replace_extent_in_place
    return compressed.ljust(ENTRY_466_BUDGET_BYTES, b"\x00")


def generate_patched_entry_466(
    base_image: Image.Image | None = None,
    font_path: Path | str | None = None,
    preview_out: Path | str | None = None,
    translations_path: Path | str | None = None,
) -> tuple[bytes, bytes]:
    """Generate uncompressed TIM and compressed 16KB disc payload."""
    img = base_image or get_base_image()
    trans = load_banner_translations(translations_path)
    patched_img = render_cyrillic_banners(img, font_path=font_path, translations=trans)
    if preview_out:
        p_out = Path(preview_out)
        p_out.parent.mkdir(parents=True, exist_ok=True)
        patched_img.save(p_out)

    packed_pixels = image_to_4bpp_indices(patched_img)
    tim_data = build_tim_4bpp(packed_pixels)
    compressed_payload = compress_entry_466(tim_data)
    return tim_data, compressed_payload


def patch_location_banners_disc(
    disc_path: Path | str,
    font_path: Path | str | None = None,
    preview_out: Path | str | None = None,
    translations_path: Path | str | None = None,
) -> tuple[int, int]:
    """Patch Entry 466 directly in PS1 CD-ROM BIN disc image.

    Returns:
        (uncompressed_size, compressed_size)
    """
    target = Path(disc_path)
    if not target.is_file():
        raise FileNotFoundError(f"Target disc image not found: {disc_path}")

    tim_data, compressed_payload = generate_patched_entry_466(
        font_path=font_path,
        preview_out=preview_out,
        translations_path=translations_path,
    )
    if len(compressed_payload) != ENTRY_466_BUDGET_BYTES:
        raise ValueError(
            f"Payload size {len(compressed_payload)} must be exactly {ENTRY_466_BUDGET_BYTES} bytes"
        )

    replace_extent_in_place(target, ENTRY_466_LBA, compressed_payload)
    return len(tim_data), len(compressed_payload)


# Alias for backwards compatibility with tests
patch_disc_image = patch_location_banners_disc


def verify_disc_image(disc_path: Path | str) -> bool:
    """Verify Entry 466 at LBA 240133 in PS1 BIN disc image.

    Validates:
    - 8 sectors readable at LBA 240133
    - Slayers Royal LZ decompression produces 28,736 bytes
    - TIM header is 10 00 00 00 08 00 00 00
    - CLUT block matches 16-color location banner palette
    - Image block dimensions are 256x224
    - Cyrillic banner content presence
    """

    target = Path(disc_path)
    if not target.is_file():
        raise FileNotFoundError(f"Target disc image not found: {disc_path}")

    extent_bytes = read_extent(target, ENTRY_466_LBA, ENTRY_466_BUDGET_BYTES)
    if len(extent_bytes) != ENTRY_466_BUDGET_BYTES:
        print(f"[VERIFY FAILED] Read {len(extent_bytes)} bytes, expected {ENTRY_466_BUDGET_BYTES}")
        return False

    try:
        decompressed, bytes_consumed = unt_lz.decompress(extent_bytes)
    except Exception as exc:
        print(f"[VERIFY FAILED] LZ Decompression failed: {exc}")
        return False

    if len(decompressed) != UNCOMPRESSED_TIM_SIZE:
        print(f"[VERIFY FAILED] Decompressed size {len(decompressed)} != {UNCOMPRESSED_TIM_SIZE}")
        return False

    if decompressed[:8] != TIM_HEADER:
        print(f"[VERIFY FAILED] Invalid TIM header: {decompressed[:8].hex()}")
        return False

    # Check CLUT
    clut_len = struct.unpack_from("<I", decompressed, 8)[0]
    if clut_len != 44:
        print(f"[VERIFY FAILED] Invalid CLUT len: {clut_len}")
        return False
    clut_words = [struct.unpack_from("<H", decompressed, 20 + i * 2)[0] for i in range(16)]
    if clut_words != LOCATION_BANNER_CLUT:
        print(f"[VERIFY FAILED] CLUT words do not match expected palette")
        return False

    # Check image block
    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", decompressed, 8 + clut_len)
    if (img_w * 4, img_h) != (TIM_WIDTH, TIM_HEIGHT):
        print(f"[VERIFY FAILED] Dimensions {img_w*4}x{img_h} != {TIM_WIDTH}x{TIM_HEIGHT}")
        return False

    # Check Cyrillic banners presence
    # Check that known pixel coords for 'БАР' at (22, 31) are rendered with cyan core (index 13)
    pixel_offset = 8 + clut_len + 12
    pixel_data = decompressed[pixel_offset:]

    def get_index(x: int, y: int) -> int:
        byte = pixel_data[y * (TIM_WIDTH // 2) + (x // 2)]
        return (byte >> 4) & 0x0F if (x % 2 != 0) else (byte & 0x0F)

    # In 'БАР', check character pixels in range x=20..48, y=28..38
    bar_indices = [get_index(x, y) for y in range(28, 38) for x in range(20, 48)]
    if not any(idx in (13, 14, 15) for idx in bar_indices):
        print("[VERIFY FAILED] Cyrillic banner 'БАР' not found in Entry 466")
        return False

    # Check 'ПЛОЩАДЬ' at Band 0 (x=96..160, y=5..15)
    plaza_indices = [get_index(x, y) for y in range(5, 15) for x in range(96, 160)]
    if not any(idx in (13, 14, 15) for idx in plaza_indices):
        print("[VERIFY FAILED] Cyrillic banner 'ПЛОЩАДЬ' not found in Entry 466")
        return False

    print(f"[VERIFY OK] BASYOG.UNT Entry 466 (LBA {ENTRY_466_LBA}..{ENTRY_466_LBA+7}):")
    print(f"  - Compressed stream: {bytes_consumed:,} bytes (budget: {ENTRY_466_BUDGET_BYTES:,} bytes)")
    print(f"  - Decompressed TIM: {len(decompressed):,} bytes (256x224 4bpp, 16-color CLUT)")
    print(f"  - Cyrillic location banners validated successfully.")
    return True


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch visual location banners in BASYOG.UNT Entry 466 (PS1)."
    )
    default_bin = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if not default_bin.is_file():
        fallback_bin = REPO_ROOT / "downloads" / "sr.bin"
        if fallback_bin.is_file():
            default_bin = fallback_bin

    parser.add_argument(
        "--bin",
        type=Path,
        default=default_bin,
        help=f"Path to PS1 disc BIN image (default: {default_bin})",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify Entry 466 in disc image without modifying",
    )
    parser.add_argument(
        "--font",
        type=Path,
        default=None,
        help="Path to PressStart2P.ttf font file",
    )
    parser.add_argument(
        "--preview-out",
        type=Path,
        default=REPO_ROOT / "data" / "preview_basyog_466_ru.png",
        help="Path to save rendered preview image",
    )
    parser.add_argument(
        "--dump-tim",
        type=Path,
        default=None,
        help="Export patched uncompressed TIM file to path",
    )
    parser.add_argument(
        "--translations",
        "--catalog",
        dest="translations",
        type=Path,
        default=DEFAULT_TRANSLATIONS,
        help=f"Path to translations JSON catalog (default: {DEFAULT_TRANSLATIONS})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.verify:
        if not args.bin.is_file():
            print(f"Error: Disc image not found: {args.bin}", file=sys.stderr)
            return 1
        ok = verify_disc_image(args.bin)
        return 0 if ok else 1

    # Patch mode
    print(f"Generating Cyrillic location banners for Entry 466...")
    tim_data, compressed_payload = generate_patched_entry_466(
        font_path=args.font,
        preview_out=args.preview_out,
        translations_path=args.translations,
    )
    print(f"Uncompressed TIM: {len(tim_data):,} bytes")
    print(f"Compressed size: {len(compressed_payload.rstrip(b'\x00')):,} bytes (budget: {ENTRY_466_BUDGET_BYTES:,} bytes)")

    if args.dump_tim:
        args.dump_tim.parent.mkdir(parents=True, exist_ok=True)
        args.dump_tim.write_bytes(tim_data)
        print(f"Dumped TIM to {args.dump_tim}")

    if args.preview_out:
        print(f"Saved preview image to {args.preview_out}")

    # Inject into disc
    if not args.bin.is_file():
        print(f"Warning: Disc image not found at {args.bin}. Created assets only.", file=sys.stderr)
        return 0

    print(f"Injecting into disc {args.bin} at LBA {ENTRY_466_LBA}..{ENTRY_466_LBA+7}...")
    replace_extent_in_place(args.bin, ENTRY_466_LBA, compressed_payload)

    # Also update secondary copy if present
    alt_bin = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if alt_bin.is_file() and alt_bin.resolve() != args.bin.resolve():
        try:
            replace_extent_in_place(alt_bin, ENTRY_466_LBA, compressed_payload)
            print(f"Also injected into secondary disc: {alt_bin}")
        except Exception as e:
            print(f"Warning: Could not update {alt_bin}: {e}", file=sys.stderr)

    # Verify after injection
    ok = verify_disc_image(args.bin)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
