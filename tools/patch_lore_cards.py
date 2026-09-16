#!/usr/bin/env python3
"""Render, encode, and inject Russian character lore cards and banners into Slayers Royal PS1 archives.

This tool:
1. Renders localized card descriptions and title banners using Pillow.
2. Converts PIL RGBA images into PlayStation 1 4bpp TIM images with grayscale CLUTs.
3. Compresses card overlays with LZ mode 1 (via unt_lz.py) and verifies sector limits.
4. Injects compressed overlays into PROG.UNT and uncompressed banners into OPT.UNT.
5. Supports patching standalone UNT archives or disc images (.bin) with Mode 2 Form 1 EDC/ECC repair.
"""

from __future__ import annotations

import argparse
import base64
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Add patch_repo to sys.path for unt_lz and disc utilities
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from localization.unt_lz import LZ_MODE, compress, decompress
except ImportError:
    # Minimal fallback decompress/compress if patch_repo is unavailable
    LZ_MODE = 1

    def compress(data: bytes) -> bytes:
        raise RuntimeError("localization.unt_lz module not available for compression")

    def decompress(data: bytes) -> tuple[bytes, int]:
        raise RuntimeError("localization.unt_lz module not available for decompression")

try:
    from localization.disc import CdChecksums, replace_extent_in_place
except ImportError:
    CdChecksums = None
    replace_extent_in_place = None


USER_SIZE = 2048
RAW_SECTOR_SIZE = 2352
USER_OFFSET = 24

OVERLAY_WIDTH = 320
OVERLAY_HEIGHT = 224
BANNER_WIDTH = 160
BANNER_HEIGHT = 32

# Standard 16-color grayscale CLUT words (BGR555) for PROG.UNT text overlays
# Index 0: 0x0000 (Transparent)
# Index 1: 0x7FFF (Pure white text core, 248, 248, 248)
# Index 2..14: Descending grayscale outline and antialiasing (232 down to 32)
# Index 15: 0x0842 (Dark shadow / black outline, 16, 16, 16)
PROG_CLUT_WORDS = [
    0x0000, 0x7FFF, 0x77BD, 0x6F7B, 0x6739, 0x5EF7, 0x56B5, 0x4E73,
    0x4210, 0x39CE, 0x318C, 0x294A, 0x2108, 0x18C6, 0x1084, 0x0842,
]

# Standard 16-color grayscale CLUT words (BGR555) for OPT.UNT banners
# Index 0: 0x0000 (Transparent)
# Index 1: 0x0842 (Dark shadow / black outline, 16, 16, 16)
# Index 2..13: Ascending grayscale levels (32 up to 216)
# Index 14: 0x77BD (Bright text core, 232, 232, 232)
# Index 15: 0x0842 (Dark shadow, 16, 16, 16)
OPT_CLUT_WORDS = [
    0x0000, 0x0842, 0x1084, 0x18C6, 0x2108, 0x294A, 0x318C, 0x39CE,
    0x3DEF, 0x4631, 0x4E73, 0x56B5, 0x5EF7, 0x6F7B, 0x77BD, 0x0842,
]

COMBINED_8BPP_ENTRIES = {37, 38, 41}
SPLIT_CARD_ENTRIES = {32, 34, 36, 40, 43, 45, 47, 49, 51, 53}

DEFAULT_PROG_SPECS: dict[int, dict[str, Any]] = {
    32: {"id": "lina", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    34: {"id": "gourry", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    36: {"id": "naga", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    37: {"id": "map_controls", "sectors": 18, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "combined_8bpp", "bpp": 8},
    38: {"id": "spell_traits", "sectors": 23, "vram_x": 320, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "combined_8bpp", "bpp": 8},
    40: {"id": "rezarium_legend", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    41: {"id": "campaign_guide", "sectors": 21, "vram_x": 320, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "combined_8bpp", "bpp": 8},
    43: {"id": "necklace", "sectors": 5, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    45: {"id": "zelgadis", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    47: {"id": "amelia", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    49: {"id": "sylphiel", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    51: {"id": "rezarium_magic", "sectors": 7, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
    53: {"id": "galef", "sectors": 6, "vram_x": 0, "vram_y": 0, "clut_x": 0, "clut_y": 480, "type": "split_card", "bpp": 4},
}

DEFAULT_OPT_SPECS: dict[int, dict[str, Any]] = {
    182: {"id": "lina", "sectors": 2, "vram_x": 576, "vram_y": 296, "clut_x": 0, "clut_y": 507},
    183: {"id": "gourry", "sectors": 2, "vram_x": 576, "vram_y": 328, "clut_x": 0, "clut_y": 507},
    184: {"id": "naga", "sectors": 2, "vram_x": 576, "vram_y": 360, "clut_x": 0, "clut_y": 507},
    185: {"id": "map_controls", "sectors": 2, "vram_x": 576, "vram_y": 392, "clut_x": 0, "clut_y": 507},
    186: {"id": "spell_traits", "sectors": 2, "vram_x": 384, "vram_y": 351, "clut_x": 0, "clut_y": 507},
    187: {"id": "rezarium_legend", "sectors": 2, "vram_x": 384, "vram_y": 383, "clut_x": 0, "clut_y": 507},
    188: {"id": "campaign_guide", "sectors": 2, "vram_x": 384, "vram_y": 415, "clut_x": 0, "clut_y": 507},
    189: {"id": "necklace", "sectors": 2, "vram_x": 384, "vram_y": 447, "clut_x": 0, "clut_y": 507},
    190: {"id": "zelgadis", "sectors": 2, "vram_x": 656, "vram_y": 296, "clut_x": 0, "clut_y": 507},
    191: {"id": "amelia", "sectors": 2, "vram_x": 656, "vram_y": 328, "clut_x": 0, "clut_y": 507},
    192: {"id": "sylphiel", "sectors": 2, "vram_x": 656, "vram_y": 360, "clut_x": 0, "clut_y": 507},
    193: {"id": "rezarium_magic", "sectors": 2, "vram_x": 656, "vram_y": 392, "clut_x": 0, "clut_y": 507},
}

COMBINED_CARD_CLUTS: dict[int, str] = {
    37: "/3+lFMYYCCEpJWstrTXOORBCMUZzTrVW914YYzlne2/yAJsB6BQJGUsdKhkJFSoVxhSlECkdCBnnFEodxhApGWsdCBVKGecQSRlJHSgZ5hAHFSgdpAzmFMUQBxknGQYV5hjFFKQQBhmDDOUUxBCjDBJPBRnkFMMQggzlGMQUACKjEMIQgQzDFKIQQEagUmIMghCiFGEMoDXgPcEwgCxgKEAkICAAGAAgDXJLXX1eAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIA=",
    38: "5Iz//3vvOef33rXWc84xxu+9rbVrrSmlCKHnnMaYpZQAgOCMx4RkrMC515Izjq+JK4Wuqfa0sqhunEuU7KSgzUzdCs3IwIa0SrlGmuSVopFgkcqtELoOvs7BAIAAgACAAIAAgACAAICg0kDG4L2gtcGwgKxgqECkIKAAoACYAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIBrnUudSp1KmUmdKpkpnUmZKpUpmSidCZkomQmVCJknmQiVB5nolAeVBpnnlAaV5pgFmeeQ5pTlmMaU5pDllMaQxZTklMWQxJSlkMSQw5SkkMOQwpSkjKOQwpCilKOMopCDjIKQgoyBjGKMYYwAgACAAIAAgACAAIAAgACAAIA=",
    41: "5Iz//733e+855/fetdZzzhDCzrmMsUqpCKHGmISQQogAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIAAgACAAIBrnUudSp1KmUmdKpkpnUmZKpUpmSidCZkomQmVCJknmQiVB5nolAeVBpnnlAaV5pgFmeeQ5pTlmMaU5pDllMaQxZTklMWQxJSlkMSQw5SkkMOQwpSkjKOQwpCilKOMopCDjIKQgoyBjGKMYYwAgACAAIAAgACAAIAAgACAAIA=",
}

DEFAULT_FONT_SEARCH = {
    "bold": [
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ],
    "regular": [
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ],
}
FONT_SEARCH_PATHS = DEFAULT_FONT_SEARCH


@dataclass
class ArchiveEntry:
    index: int
    start_sector: int
    sector_count: int

    @property
    def offset(self) -> int:
        return self.start_sector * USER_SIZE

    @property
    def size(self) -> int:
        return self.sector_count * USER_SIZE


@dataclass
class CardPatchResult:
    card_id: str
    prog_entry: int
    prog_size: int
    prog_compressed_size: int
    prog_budget: int
    prog_margin: int
    opt_entry: int | None = None
    opt_size: int | None = None
    opt_budget: int | None = None


def find_font_path(style: str = "regular", custom_path: str | Path | None = None) -> Path | None:
    if custom_path is not None:
        p = Path(custom_path)
        if p.exists():
            return p
    for candidate in DEFAULT_FONT_SEARCH.get(style, []):
        p = Path(candidate)
        if p.exists():
            return p
    return None


def get_font(
    style: str = "regular",
    size: int = 12,
    custom_path: str | Path | None = None,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = find_font_path(style, custom_path)
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            pass
    return ImageFont.load_default()

def wrap_card_description(desc: str, width: int = 44) -> list[str]:
    """Automatically wrap a card description into lines fitting the PS1 screen (~40-45 chars per line)."""
    import textwrap
    paragraphs = desc.split("\n\n")
    all_lines: list[str] = []
    for p in paragraphs:
        cleaned = p.replace("\n", " ").strip()
        if not cleaned:
            continue
        wrapped = textwrap.wrap(cleaned, width=width, break_long_words=False)
        all_lines.extend(wrapped)
    return all_lines


def resolve_cards_json_path(custom_path: Path | str | None = None) -> Path:
    """Resolve lore cards JSON path, prioritizing translations/ over data/."""
    if custom_path is not None:
        p = Path(custom_path)
        if p.exists():
            return p
    trans_path = REPO_ROOT / "translations" / "lore_cards_ru.json"
    if trans_path.exists():
        return trans_path
    return REPO_ROOT / "data" / "lore_cards_ru.json"


def load_lore_cards_data(json_path: Path | str) -> list[dict[str, Any]]:
    """Load lore cards dataset from JSON file (supporting both bare list and dict with 'cards' key)."""
    p = Path(json_path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "cards" in data:
        cards = data["cards"]
    elif isinstance(data, list):
        cards = data
    else:
        raise ValueError(f"Unrecognized lore cards format in {json_path}")

    # Process auto-wrapping if lines is empty or omitted
    for card in cards:
        lines = card.get("lines")
        if (lines is None or len(lines) == 0) and card.get("description"):
            card["lines"] = wrap_card_description(card["description"])
    return cards


def sync_lore_cards_file(src_path: Path, dst_path: Path) -> None:
    """Keep secondary lore_cards_ru.json synchronized with master translation file."""
    try:
        if src_path.resolve() == dst_path.resolve():
            return
        content = src_path.read_text(encoding="utf-8")
        if not dst_path.exists() or dst_path.read_text(encoding="utf-8") != content:
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"Warning: failed to sync {dst_path}: {e}", file=sys.stderr)


def update_data_previews(
    cards_data: list[dict[str, Any]],
    data_dir: Path | str | None = None,
    font_bold_path: str | Path | None = None,
    font_reg_path: str | Path | None = None,
) -> None:
    """Regenerate lore card and banner preview images in data/ directory."""
    if data_dir is None:
        data_dir = REPO_ROOT / "data"
    d = Path(data_dir)
    d.mkdir(parents=True, exist_ok=True)

    cards_by_id = {c["id"]: c for c in cards_data}
    from tools.inspect_lore_card import tim_to_rgba

    # 1. Combined 8bpp card previews
    for pe, filename in [(37, "preview_card_37_ru.png"), (38, "preview_card_38_ru.png"), (41, "preview_card_41_ru.png")]:
        card = next((c for c in cards_data if c["prog_entry"] == pe), None)
        if card:
            tim_bytes = render_combined_card_8bpp(card, font_bold_path=font_bold_path, font_reg_path=font_reg_path)
            im = tim_to_rgba(tim_bytes, transparent_zero=False)
            if im:
                im.save(d / filename)

    # 2. Banner 185 preview
    card_37 = next((c for c in cards_data if c["prog_entry"] == 37), None)
    banner_text = card_37.get("banner_opt", "УПРАВЛЕНИЕ") if card_37 else "УПРАВЛЕНИЕ"
    im_banner = render_banner(banner_text, font_bold_path=font_bold_path)
    im_banner.save(d / "preview_banner_185_ru.png")

    # 3. Naga card overlay and composite preview
    naga_card = cards_by_id.get("naga")
    if naga_card:
        im_naga_text = render_lore_card_text(naga_card, font_bold_path=font_bold_path, font_reg_path=font_reg_path)
        im_naga_text.save(d / "preview_naga_card.png")
        orig_comp_path = d / "preview_naga_card_composite.png"
        try:
            cand_bins = [
                REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
                REPO_ROOT / "downloads" / "sr.bin",
                REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
            ]
            for cb in cand_bins:
                if cb.exists():
                    pvd = read_sector(cb, 16)
                    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
                    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
                    root_dir = parse_iso_dir(cb, root_lba, root_size)
                    prog_bytes = read_extent(cb, *root_dir["PROG.UNT"])
                    prog_idx = read_unt_index(prog_bytes)
                    art_e = prog_idx[35]
                    art_raw = prog_bytes[art_e.offset : art_e.offset + art_e.size]
                    art_dec, _ = decompress(art_raw)
                    bg_art = tim_to_rgba(art_dec, transparent_zero=False)
                    if bg_art:
                        comp = bg_art.convert("RGBA")
                        comp.alpha_composite(im_naga_text)
                        comp.save(orig_comp_path)
                        break
        except Exception:
            pass


def render_lore_card_text(
    card_data: dict[str, Any],
    font_bold_path: str | Path | None = None,
    font_reg_path: str | Path | None = None,
) -> Image.Image:
    """Render a 320x224 RGBA text overlay for a character lore card.

    Layout specifications:
    - Title Main ('[С] Нага Белая Змея'): at (16, 16), bold ~15pt, white with 1px black outline.
    - Title Sub ('(Нага Змеюка)'): at (24, 34), regular ~12pt, white with 1px black outline.
    - Body lines: starting at (16, 60), 16px line spacing, regular ~12pt, white with 1px black shadow (+1, +1).
    """
    im = Image.new("RGBA", (OVERLAY_WIDTH, OVERLAY_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    f_bold = get_font("bold", 15, font_bold_path)
    f_reg = get_font("regular", 12, font_reg_path)

    # Title Main: top-left at (16, 16), bold ~15pt, white with 1px black outline
    title_main = card_data.get("title_main", "")
    if title_main:
        draw.text(
            (16, 16),
            title_main,
            font=f_bold,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

    # Title Sub: below title at (24, 34), regular ~12pt, white with 1px black outline
    title_sub = card_data.get("title_sub", "")
    if title_sub:
        draw.text(
            (24, 34),
            title_sub,
            font=f_reg,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

    # Body lines: starting at (16, 60), line spacing ~16px, ~12pt font, white with 1px black shadow (+1, +1)
    lines = card_data.get("lines")
    if (lines is None or len(lines) == 0) and card_data.get("description"):
        lines = wrap_card_description(card_data["description"])
    elif lines is None:
        lines = []
    y = 60
    for line in lines:
        if line:
            # Shadow at +1, +1
            draw.text((16 + 1, y + 1), line, font=f_reg, fill=(0, 0, 0, 255))
            # Main white text
            draw.text((16, y), line, font=f_reg, fill=(255, 255, 255, 255))
        y += 16

    return im


def render_banner(
    text: str,
    font_bold_path: str | Path | None = None,
) -> Image.Image:
    """Render a 160x32 RGBA title banner plate for OPT.UNT.

    Layout specifications:
    - Text: banner_opt centered, white bold font with 1px black shadow.
    - Resolution: 160x32 pixels.
    """
    im = Image.new("RGBA", (BANNER_WIDTH, BANNER_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    font_size = 14
    f_banner = get_font("bold", font_size, font_bold_path)

    # Auto-fit font size to stay within ~150px width and ~26px height
    bbox = draw.textbbox((0, 0), text, font=f_banner)
    text_w = bbox[2] - bbox[0]
    while text_w > 150 and font_size > 8:
        font_size -= 1
        f_banner = get_font("bold", font_size, font_bold_path)
        bbox = draw.textbbox((0, 0), text, font=f_banner)
        text_w = bbox[2] - bbox[0]

    text_h = bbox[3] - bbox[1]
    x = (BANNER_WIDTH - text_w) // 2 - bbox[0]
    y = (BANNER_HEIGHT - text_h) // 2 - bbox[1]

    # Draw shadow at (+1, +1)
    draw.text((x + 1, y + 1), text, font=f_banner, fill=(0, 0, 0, 255))
    # Draw main text in white
    draw.text((x, y), text, font=f_banner, fill=(255, 255, 255, 255))

    return im


def rgba_to_4bpp_indices(
    im: Image.Image,
    clut_words: list[int],
    alpha_threshold: int = 64,
) -> bytes:
    """Convert an RGBA PIL image to packed 4bpp pixel data indexed against clut_words.

    - Index 0 is reserved for transparent pixels (alpha < alpha_threshold).
    - Opaque pixels are mapped to the palette entry (1..15) with the closest luminance.
    - Output bytes pack 2 pixels per byte: low nibble = even pixel, high nibble = odd pixel.
    """
    im_rgba = im.convert("RGBA")
    w, h = im_rgba.size
    pixels = np.array(im_rgba)
    r = pixels[:, :, 0].astype(np.float32)
    g = pixels[:, :, 1].astype(np.float32)
    b = pixels[:, :, 2].astype(np.float32)
    a = pixels[:, :, 3]

    # Compute luminance of source pixels
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    # Compute luminance of palette entries 1..15
    palette_lums = []
    for word in clut_words[1:16]:
        pr = ((word & 0x1F) << 3)
        pg = (((word >> 5) & 0x1F) << 3)
        pb = (((word >> 10) & 0x1F) << 3)
        plum = 0.299 * pr + 0.587 * pg + 0.114 * pb
        palette_lums.append(plum)
    levels = np.array(palette_lums, dtype=np.float32)

    indices = np.zeros((h, w), dtype=np.uint8)
    opaque_mask = a >= alpha_threshold

    if np.any(opaque_mask):
        lum_opaque = lum[opaque_mask]
        diffs = np.abs(levels[:, None] - lum_opaque[None, :])
        best_level_idx = np.argmin(diffs, axis=0)  # 0..14
        indices[opaque_mask] = best_level_idx + 1

    # Pack 4bpp: low nibble = even pixel, high nibble = odd pixel
    flat = indices.flatten()
    low = flat[0::2]
    high = flat[1::2]
    packed = (high << 4) | low
    return bytes(packed)


def build_tim_4bpp(
    packed_pixels: bytes,
    width: int,
    height: int,
    clut_words: list[int],
    vram_x: int = 0,
    vram_y: int = 0,
    clut_x: int = 0,
    clut_y: int = 480,
) -> bytes:
    """Construct a PlayStation 1 4bpp TIM binary file with CLUT and pixel data."""
    if len(clut_words) != 16:
        raise ValueError(f"CLUT must contain exactly 16 color halfwords, got {len(clut_words)}")
    if len(packed_pixels) != (width * height) // 2:
        raise ValueError(
            f"packed_pixels size ({len(packed_pixels)}) does not match dimensions {width}x{height}"
        )

    tim = bytearray()
    # TIM Header: magic 0x10, flag 0x08 (pmode=0 for 4bpp, has_clut=1)
    tim.extend(b"\x10\x00\x00\x00\x08\x00\x00\x00")

    # CLUT Block: 12 bytes header + 32 bytes color entries = 44 bytes
    clut_len = 44
    clut_w = 16  # 16 colors
    clut_h = 1   # 1 palette
    tim.extend(clut_len.to_bytes(4, "little"))
    tim.extend(clut_x.to_bytes(2, "little"))
    tim.extend(clut_y.to_bytes(2, "little"))
    tim.extend(clut_w.to_bytes(2, "little"))
    tim.extend(clut_h.to_bytes(2, "little"))
    for word in clut_words:
        tim.extend(word.to_bytes(2, "little"))

    # Image Block: 12 bytes header + pixel data
    img_len = 12 + len(packed_pixels)
    img_w = width // 4  # 16-bit words per scanline for 4bpp
    img_h = height
    tim.extend(img_len.to_bytes(4, "little"))
    tim.extend(vram_x.to_bytes(2, "little"))
    tim.extend(vram_y.to_bytes(2, "little"))
    tim.extend(img_w.to_bytes(2, "little"))
    tim.extend(img_h.to_bytes(2, "little"))
    tim.extend(packed_pixels)

    return bytes(tim)


def image_to_tim_4bpp(
    im: Image.Image,
    clut_words: list[int] | None = None,
    vram_x: int = 0,
    vram_y: int = 0,
    clut_x: int = 0,
    clut_y: int = 480,
    alpha_threshold: int = 64,
) -> bytes:
    """Convert an arbitrary PIL image to a 4bpp TIM binary."""
    palette = clut_words if clut_words is not None else PROG_CLUT_WORDS
    packed = rgba_to_4bpp_indices(im, palette, alpha_threshold=alpha_threshold)
    return build_tim_4bpp(
        packed,
        im.width,
        im.height,
        palette,
        vram_x=vram_x,
        vram_y=vram_y,
        clut_x=clut_x,
        clut_y=clut_y,
    )

def rgb_to_bgr555(r: int, g: int, b: int, stp: int = 0) -> int:
    """Convert 8-bit RGB color components to PlayStation 1 BGR555 halfword."""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    return r5 | (g5 << 5) | (b5 << 10) | ((stp & 1) << 15)


def build_tim_8bpp(
    pixel_indices: bytes,
    width: int,
    height: int,
    clut_words: list[int],
    vram_x: int = 320,
    vram_y: int = 0,
    clut_x: int = 0,
    clut_y: int = 480,
) -> bytes:
    """Construct a PlayStation 1 8bpp TIM binary file with CLUT and pixel data."""
    if len(clut_words) != 256:
        raise ValueError(f"CLUT must contain exactly 256 color halfwords, got {len(clut_words)}")
    if len(pixel_indices) != width * height:
        raise ValueError(
            f"pixel_indices size ({len(pixel_indices)}) does not match dimensions {width}x{height}"
        )

    tim = bytearray()
    # TIM Header: magic 0x10, flag 0x09 (pmode=1 for 8bpp, has_clut=1)
    tim.extend(b"\x10\x00\x00\x00\x09\x00\x00\x00")

    # CLUT Block: 12 bytes header + 512 bytes color entries = 524 bytes
    clut_len = 524
    clut_w = 256
    clut_h = 1
    tim.extend(clut_len.to_bytes(4, "little"))
    tim.extend(clut_x.to_bytes(2, "little"))
    tim.extend(clut_y.to_bytes(2, "little"))
    tim.extend(clut_w.to_bytes(2, "little"))
    tim.extend(clut_h.to_bytes(2, "little"))
    for word in clut_words:
        tim.extend(word.to_bytes(2, "little"))

    # Image Block: 12 bytes header + pixel data (width // 2 16-bit words per scanline)
    img_len = 12 + len(pixel_indices)
    img_w = width // 2  # 160 halfwords = 320 pixels for 8bpp
    img_h = height
    tim.extend(img_len.to_bytes(4, "little"))
    tim.extend(vram_x.to_bytes(2, "little"))
    tim.extend(vram_y.to_bytes(2, "little"))
    tim.extend(img_w.to_bytes(2, "little"))
    tim.extend(img_h.to_bytes(2, "little"))
    tim.extend(pixel_indices)

    return bytes(tim)


def extract_clut_from_disc(pe: int, repo_root: Path) -> list[int]:
    """Fallback: extract original CLUT from disc image."""
    for cand in [repo_root / "downloads" / "sr.bin", repo_root / "build" / "en_patched" / "sr_patched.bin"]:
        if cand.exists():
            pvd = read_sector(cand, 16)
            root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
            root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
            root_dir = parse_iso_dir(cand, root_lba, root_size)
            prog_bytes = read_extent(cand, *root_dir["PROG.UNT"])
            prog_idx = read_unt_index(prog_bytes)
            raw = prog_bytes[prog_idx[pe].offset : prog_idx[pe].offset + prog_idx[pe].size]
            dec, _ = decompress(raw)
            clut_bytes = dec[20:532]
            return [int.from_bytes(clut_bytes[i * 2 : i * 2 + 2], "little") for i in range(256)]
    raise FileNotFoundError(f"Cannot find CLUT for entry {pe} in data/ or disc images")


def extract_background_from_disc(pe: int, repo_root: Path) -> Image.Image:
    """Fallback: extract clean background image from disc image."""
    for cand in [repo_root / "downloads" / "sr.bin", repo_root / "build" / "en_patched" / "sr_patched.bin"]:
        if cand.exists():
            pvd = read_sector(cand, 16)
            root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
            root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
            root_dir = parse_iso_dir(cand, root_lba, root_size)
            prog_bytes = read_extent(cand, *root_dir["PROG.UNT"])
            prog_idx = read_unt_index(prog_bytes)
            raw = prog_bytes[prog_idx[pe].offset : prog_idx[pe].offset + prog_idx[pe].size]
            dec, _ = decompress(raw)
            return Image.new("RGBA", (OVERLAY_WIDTH, OVERLAY_HEIGHT), (0, 0, 0, 255))
    raise FileNotFoundError(f"Cannot find background image for entry {pe} in data/ or disc images")


def get_combined_card_assets(pe: int) -> tuple[Image.Image, list[int]]:
    """Retrieve clean background image and 256-word CLUT for combined 8bpp cards (37, 38, 41)."""
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = repo_root / "data"

    # 1. Load CLUT
    if pe in COMBINED_CARD_CLUTS:
        clut_bytes = base64.b64decode(COMBINED_CARD_CLUTS[pe])
        clut_words = [int.from_bytes(clut_bytes[i * 2 : i * 2 + 2], "little") for i in range(256)]
    elif (data_dir / f"lore_card_clut_{pe}.bin").exists():
        clut_bytes = (data_dir / f"lore_card_clut_{pe}.bin").read_bytes()
        clut_words = [int.from_bytes(clut_bytes[i * 2 : i * 2 + 2], "little") for i in range(256)]
    else:
        clut_words = extract_clut_from_disc(pe, repo_root)

    # 2. Load background image
    if pe == 37:
        bg_path = data_dir / "lore_card_37_bg.png"
    else:
        bg_path = data_dir / "lore_card_parchment_bg.png"

    if bg_path.exists():
        bg_im = Image.open(bg_path).convert("RGBA")
    else:
        bg_im = extract_background_from_disc(pe, repo_root)

    return bg_im, clut_words


def render_combined_card_8bpp(
    card_data: dict[str, Any],
    font_bold_path: str | Path | None = None,
    font_reg_path: str | Path | None = None,
) -> bytes:
    """Render a combined 8bpp lore card (entries 37, 38, 41) directly as an 8bpp TIM."""
    pe = card_data["prog_entry"]
    spec = DEFAULT_PROG_SPECS.get(pe, {})
    vram_x = spec.get("vram_x", 0 if pe == 37 else 320)
    vram_y = spec.get("vram_y", 0)
    clut_x = spec.get("clut_x", 0)
    clut_y = spec.get("clut_y", 480)

    bg_im, clut_words = get_combined_card_assets(pe)

    # Convert CLUT to RGB numpy array for color mapping
    clut_rgb = []
    for w in clut_words:
        r = (w & 0x1F) << 3
        g = ((w >> 5) & 0x1F) << 3
        b = ((w >> 10) & 0x1F) << 3
        clut_rgb.append((r, g, b))
    clut_arr = np.array(clut_rgb, dtype=np.int32)

    if pe == 37:
        # Card 37: Map & Controller diagram
        im = bg_im.copy()
        draw = ImageDraw.Draw(im)
        f_bold = get_font("bold", 15, font_bold_path)
        f_reg = get_font("regular", 12, font_reg_path)
        f_small_bold = get_font("bold", 10, font_bold_path)
        f_body = get_font("regular", 11, font_reg_path)

        # Title
        title_main = card_data.get("title_main", "[К] Карта местности")
        draw.text(
            (16, 16),
            title_main,
            font=f_bold,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )
        title_sub = card_data.get("title_sub", "(Управление на карте)")
        draw.text(
            (24, 34),
            title_sub,
            font=f_reg,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

        # Controller diagram labels
        draw.text(
            (160, 67),
            "ВЫБРАТЬ / ОСМОТРЕТЬ",
            font=f_small_bold,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )

        draw.text(
            (160, 91),
            "ПОКАЗАТЬ / СКРЫТЬ",
            font=f_small_bold,
            fill=(255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )
        # Lower description lines
        lines = card_data.get("lines")
        if (lines is None or len(lines) == 0) and card_data.get("description"):
            lines = wrap_card_description(card_data["description"])
        elif lines is None:
            lines = []
        y = 134
        for line in lines:
            if line:
                draw.text((19 + 1, y + 1), line, font=f_body, fill=(0, 0, 0, 255))
                draw.text((19, y), line, font=f_body, fill=(255, 255, 255, 255))
            y += 12

        arr_im = np.array(im)[:, :, :3]
        arr_bg = np.array(bg_im)[:, :, :3]
        is_diff = np.any(arr_im != arr_bg, axis=-1)

        bg_clut = clut_arr[16:]
        text_clut = clut_arr[0:16]
        final_pixels = np.zeros((OVERLAY_HEIGHT, OVERLAY_WIDTH), dtype=np.uint8)

        # Map background to indices 16..255
        for r in range(OVERLAY_HEIGHT):
            row_px = arr_bg[r, :, None, :].astype(np.int32)
            dists = np.sum((row_px - bg_clut[None, :, :])**2, axis=-1)
            final_pixels[r, :] = np.argmin(dists, axis=-1) + 16

        # Map text to indices 0..15
        text_rgb = arr_im[is_diff].astype(np.int32)
        dists_text = np.sum((text_rgb[:, None, :] - text_clut[None, :, :])**2, axis=-1)
        final_pixels[is_diff] = np.argmin(dists_text, axis=-1)

    else:
        # Entries 38 and 41: Antique parchment map background
        overlay = render_lore_card_text(
            card_data, font_bold_path=font_bold_path, font_reg_path=font_reg_path
        )
        overlay_arr = np.array(overlay)
        is_text = overlay_arr[:, :, 3] >= 64

        bg_clut = clut_arr[16:]
        text_clut = clut_arr[1:16]  # text ramp 1..15
        final_pixels = np.zeros((OVERLAY_HEIGHT, OVERLAY_WIDTH), dtype=np.uint8)

        bg_arr = np.array(bg_im)[:, :, :3]
        for r in range(OVERLAY_HEIGHT):
            row_px = bg_arr[r, :, None, :].astype(np.int32)
            dists = np.sum((row_px - bg_clut[None, :, :])**2, axis=-1)
            final_pixels[r, :] = np.argmin(dists, axis=-1) + 16

        text_rgb = overlay_arr[is_text, :3].astype(np.int32)
        dists_text = np.sum((text_rgb[:, None, :] - text_clut[None, :, :])**2, axis=-1)
        final_pixels[is_text] = np.argmin(dists_text, axis=-1) + 1

    return build_tim_8bpp(
        final_pixels.tobytes(),
        OVERLAY_WIDTH,
        OVERLAY_HEIGHT,
        clut_words,
        vram_x=vram_x,
        vram_y=vram_y,
        clut_x=clut_x,
        clut_y=clut_y,
    )


def read_unt_index(archive_bytes: bytes) -> list[ArchiveEntry]:
    """Parse UNT sector index from sector 0."""
    entries: list[ArchiveEntry] = []
    expected = 1
    for offset in range(0, USER_SIZE, 4):
        start = int.from_bytes(archive_bytes[offset : offset + 2], "little")
        count = int.from_bytes(archive_bytes[offset + 2 : offset + 4], "little")
        if start != expected or count == 0:
            break
        entries.append(ArchiveEntry(len(entries), start, count))
        expected += count
    return entries


def patch_unt_entry(
    archive_bytes: bytearray,
    entry_index: int,
    payload: bytes,
) -> tuple[int, int, int]:
    """Inject payload into a UNT entry, verifying sector limits and padding with zeros.

    Returns:
        (offset, allocated_size, payload_size)
    """
    entries = read_unt_index(archive_bytes)
    if entry_index >= len(entries):
        raise IndexError(
            f"entry {entry_index} out of range (archive has {len(entries)} entries)"
        )
    entry = entries[entry_index]
    allocated = entry.size
    if len(payload) > allocated:
        raise ValueError(
            f"entry {entry_index} payload ({len(payload)} bytes) exceeds allocated sector budget "
            f"({allocated} bytes / {entry.sector_count} sectors)"
        )
    padded = payload.ljust(allocated, b"\x00")
    archive_bytes[entry.offset : entry.offset + allocated] = padded
    return entry.offset, allocated, len(payload)


def patch_lore_cards(
    cards_data: list[dict[str, Any]],
    prog_archive: bytearray,
    opt_archive: bytearray | None = None,
    font_bold_path: str | Path | None = None,
    font_reg_path: str | Path | None = None,
) -> list[CardPatchResult]:
    """Render, encode, and patch lore cards into PROG.UNT and OPT.UNT in memory."""
    results: list[CardPatchResult] = []

    for card in cards_data:
        if (card.get("lines") is None or len(card.get("lines", [])) == 0) and card.get("description"):
            card["lines"] = wrap_card_description(card["description"])
        cid = card["id"]
        pe = card["prog_entry"]

        # Determine PROG VRAM / CLUT coordinates
        spec_p = DEFAULT_PROG_SPECS.get(pe, {})
        vram_x_p = spec_p.get("vram_x", 0)
        vram_y_p = spec_p.get("vram_y", 0)
        clut_x_p = spec_p.get("clut_x", 0)
        clut_y_p = spec_p.get("clut_y", 480)

        # 1. Render and encode card image
        if pe in COMBINED_8BPP_ENTRIES:
            tim_p = render_combined_card_8bpp(
                card, font_bold_path=font_bold_path, font_reg_path=font_reg_path
            )
        else:
            im_overlay = render_lore_card_text(
                card, font_bold_path=font_bold_path, font_reg_path=font_reg_path
            )
            tim_p = image_to_tim_4bpp(
                im_overlay,
                clut_words=PROG_CLUT_WORDS,
                vram_x=vram_x_p,
                vram_y=vram_y_p,
                clut_x=clut_x_p,
                clut_y=clut_y_p,
            )
        # 2. Compress with LZ mode 1
        comp_p = compress(tim_p)

        # 3. Patch into PROG.UNT
        _, alloc_p, payload_len_p = patch_unt_entry(prog_archive, pe, comp_p)
        margin_p = alloc_p - payload_len_p

        # 4. Handle OPT banner if present
        oe = card.get("opt_entry")
        banner_text = card.get("banner_opt")
        opt_size = None
        opt_budget = None

        if oe is not None and banner_text and opt_archive is not None:
            spec_o = DEFAULT_OPT_SPECS.get(oe, {})
            vram_x_o = spec_o.get("vram_x", 576)
            vram_y_o = spec_o.get("vram_y", 296)
            clut_x_o = spec_o.get("clut_x", 0)
            clut_y_o = spec_o.get("clut_y", 507)

            im_banner = render_banner(banner_text, font_bold_path=font_bold_path)
            tim_o = image_to_tim_4bpp(
                im_banner,
                clut_words=OPT_CLUT_WORDS,
                vram_x=vram_x_o,
                vram_y=vram_y_o,
                clut_x=clut_x_o,
                clut_y=clut_y_o,
            )
            # OPT banners are stored uncompressed
            _, alloc_o, payload_len_o = patch_unt_entry(opt_archive, oe, tim_o)
            opt_size = payload_len_o
            opt_budget = alloc_o

        results.append(
            CardPatchResult(
                card_id=cid,
                prog_entry=pe,
                prog_size=len(tim_p),
                prog_compressed_size=payload_len_p,
                prog_budget=alloc_p,
                prog_margin=margin_p,
                opt_entry=oe,
                opt_size=opt_size,
                opt_budget=opt_budget,
            )
        )

    return results


def read_sector(disc_path: Path, lba: int) -> bytes:
    with disc_path.open("rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + USER_OFFSET)
        return f.read(USER_SIZE)


def read_extent(disc_path: Path, lba: int, size: int) -> bytes:
    sectors = (size + USER_SIZE - 1) // USER_SIZE
    with disc_path.open("rb") as f:
        buf = bytearray()
        for s in range(sectors):
            f.seek((lba + s) * RAW_SECTOR_SIZE + USER_OFFSET)
            buf.extend(f.read(USER_SIZE))
        return bytes(buf[:size])


def parse_iso_dir(disc_path: Path, lba: int, size: int) -> dict[str, tuple[int, int]]:
    data = read_extent(disc_path, lba, size)
    pos = 0
    records: dict[str, tuple[int, int]] = {}
    while pos < size:
        length = data[pos]
        if length == 0:
            pos = ((pos // USER_SIZE) + 1) * USER_SIZE
            continue
        record = data[pos : pos + length]
        extent_lba = struct.unpack_from("<I", record, 2)[0]
        extent_size = struct.unpack_from("<I", record, 10)[0]
        name_len = record[32]
        name = record[33 : 33 + name_len].decode("ascii", errors="replace")
        records[name.split(";")[0]] = (extent_lba, extent_size)
        pos += length
    return records


def patch_disc_image(
    disc_path: Path,
    cards_data: list[dict[str, Any]],
    font_bold_path: str | Path | None = None,
    font_reg_path: str | Path | None = None,
) -> list[CardPatchResult]:
    """Patch PROG.UNT and OPT.UNT directly within a PS1 CD-ROM BIN image."""
    if replace_extent_in_place is None:
        raise RuntimeError("CdChecksums/replace_extent_in_place from localization.disc is required")

    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)

    if "PROG.UNT" not in root_dir or "OPT.UNT" not in root_dir:
        raise ValueError(f"PROG.UNT or OPT.UNT not found in ISO root directory of {disc_path}")

    prog_lba, prog_size = root_dir["PROG.UNT"]
    opt_lba, opt_size = root_dir["OPT.UNT"]

    prog_archive = bytearray(read_extent(disc_path, prog_lba, prog_size))
    opt_archive = bytearray(read_extent(disc_path, opt_lba, opt_size))

    results = patch_lore_cards(
        cards_data,
        prog_archive,
        opt_archive,
        font_bold_path=font_bold_path,
        font_reg_path=font_reg_path,
    )

    # Write patched archives back to disc image with Mode 2 Form 1 EDC/ECC repair
    replace_extent_in_place(disc_path, prog_lba, bytes(prog_archive))
    replace_extent_in_place(disc_path, opt_lba, bytes(opt_archive))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch Russian character lore cards into Slayers Royal archives"
    )
    parser.add_argument(
        "--json",
        "--cards",
        dest="json",
        type=Path,
        default=None,
        help="Path to lore cards JSON file (default: translations/lore_cards_ru.json)",
    )
    parser.add_argument(
        "--update-previews",
        action="store_true",
        help="Regenerate preview PNGs in data/ directory",
    )
    parser.add_argument(
        "--bin",
        "--disc",
        dest="bin",
        type=Path,
        default=None,
        help="Path to target PS1 BIN image to patch in place",
    )
    parser.add_argument(
        "--prog",
        type=Path,
        default=None,
        help="Path to standalone PROG.UNT archive",
    )
    parser.add_argument(
        "--opt",
        type=Path,
        default=None,
        help="Path to standalone OPT.UNT archive",
    )
    parser.add_argument(
        "--card",
        type=str,
        default="all",
        help="Target card ID to patch or 'all' (default: all)",
    )
    parser.add_argument(
        "--dump-images",
        type=Path,
        default=None,
        help="Directory to dump rendered PNG overlays and banners",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render, encode, and verify sector budgets without modifying files",
    )
    parser.add_argument(
        "--font-bold",
        type=Path,
        default=None,
        help="Path to custom bold TTF font",
    )
    parser.add_argument(
        "--font-regular",
        type=Path,
        default=None,
        help="Path to custom regular TTF font",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    json_path = resolve_cards_json_path(args.json)
    if not json_path.exists():
        print(f"Error: JSON dataset {json_path} not found.", file=sys.stderr)
        return 1

    cards_data = load_lore_cards_data(json_path)

    # Synchronize secondary dataset if master translation was loaded
    trans_default = REPO_ROOT / "translations" / "lore_cards_ru.json"
    data_default = REPO_ROOT / "data" / "lore_cards_ru.json"
    if json_path.resolve() == trans_default.resolve():
        sync_lore_cards_file(trans_default, data_default)
    elif json_path.resolve() == data_default.resolve() and not trans_default.exists():
        sync_lore_cards_file(data_default, trans_default)
    if args.card.lower() != "all":
        cards_data = [c for c in cards_data if c["id"] == args.card.lower()]
        if not cards_data:
            print(f"Error: Card '{args.card}' not found in dataset.", file=sys.stderr)
            return 1

    # Dump images if requested
    if args.dump_images:
        args.dump_images.mkdir(parents=True, exist_ok=True)
        for card in cards_data:
            cid = card["id"]
            pe = card["prog_entry"]
            if pe in COMBINED_8BPP_ENTRIES:
                tim_bytes = render_combined_card_8bpp(
                    card, font_bold_path=args.font_bold, font_reg_path=args.font_regular
                )
                from tools.inspect_lore_card import tim_to_rgba
                im_card = tim_to_rgba(tim_bytes, transparent_zero=False)
                if im_card:
                    im_card.save(args.dump_images / f"{cid}_combined.png")
            else:
                im_text = render_lore_card_text(
                    card, font_bold_path=args.font_bold, font_reg_path=args.font_regular
                )
                im_text.save(args.dump_images / f"{cid}_overlay.png")
            if card.get("banner_opt"):
                im_banner = render_banner(
                    card["banner_opt"], font_bold_path=args.font_bold
                )
                im_banner.save(args.dump_images / f"{cid}_banner.png")
        print(f"Rendered PNGs dumped to {args.dump_images}")
    if args.update_previews:
        update_data_previews(
            cards_data,
            font_bold_path=args.font_bold,
            font_reg_path=args.font_regular,
        )
        print("Updated preview images in data/")

    # Dry-run verification
    if args.dry_run or (not args.bin and not args.prog):
        print("=== Lore Card Injection Budget Analysis (Dry-Run) ===")
        print(
            f"{'ID':<16} {'PROG':<5} {'Sec':<4} {'Budget':<8} {'Compressed':<11} {'Margin':<8} {'OPT':<5} {'Banner'}"
        )
        print("-" * 75)
        for card in cards_data:
            pe = card["prog_entry"]
            spec_p = DEFAULT_PROG_SPECS.get(pe, {"sectors": 6, "vram_x": 0, "vram_y": 0})
            if pe in COMBINED_8BPP_ENTRIES:
                tim_p = render_combined_card_8bpp(
                    card, font_bold_path=args.font_bold, font_reg_path=args.font_regular
                )
            else:
                im_text = render_lore_card_text(
                    card, font_bold_path=args.font_bold, font_reg_path=args.font_regular
                )
                tim_p = image_to_tim_4bpp(
                    im_text,
                    clut_words=PROG_CLUT_WORDS,
                    vram_x=spec_p.get("vram_x", 0),
                    vram_y=spec_p.get("vram_y", 0),
                    clut_x=spec_p.get("clut_x", 0),
                    clut_y=spec_p.get("clut_y", 480),
                )
            comp_p = compress(tim_p)
            budget = spec_p.get("sectors", 6) * USER_SIZE
            margin = budget - len(comp_p)
            status = f"+{margin}B" if margin >= 0 else f"OVERFLOW ({margin}B)"

            oe_str = str(card.get("opt_entry") or "-")
            banner_str = card.get("banner_opt") or "-"
            print(
                f"{card['id']:<16} {pe:<5} {spec_p.get('sectors', 6):<4} {budget:<8} "
                f"{len(comp_p):<11} {status:<8} {oe_str:<5} {banner_str}"
            )
        print("Dry run completed successfully.")
        return 0

    if args.bin:
        print(f"Patching disc image: {args.bin}")
        results = patch_disc_image(
            args.bin,
            cards_data,
            font_bold_path=args.font_bold,
            font_reg_path=args.font_regular,
        )
        if args.verbose:
            print("--- Patch Details ---")
            for r in results:
                opt_info = f", OPT entry {r.opt_entry}: {r.opt_size}/{r.opt_budget}B" if r.opt_entry is not None else ""
                print(f"  [{r.card_id}] PROG entry {r.prog_entry}: {r.prog_compressed_size}/{r.prog_budget}B (margin: {r.prog_margin}B){opt_info}")
        update_data_previews(
            cards_data,
            font_bold_path=args.font_bold,
            font_reg_path=args.font_regular,
        )
        print(f"Successfully patched {len(results)} cards into {args.bin}.")
        return 0


    if args.prog:
        print(f"Patching standalone archives: PROG={args.prog}, OPT={args.opt}")
        prog_bytes = bytearray(args.prog.read_bytes())
        opt_bytes = bytearray(args.opt.read_bytes()) if args.opt and args.opt.exists() else None
        results = patch_lore_cards(
            cards_data,
            prog_bytes,
            opt_bytes,
            font_bold_path=args.font_bold,
            font_reg_path=args.font_regular,
        )
        args.prog.write_bytes(prog_bytes)
        if args.opt and opt_bytes:
            args.opt.write_bytes(opt_bytes)
        print(f"Successfully patched {len(results)} cards into {args.prog}.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
