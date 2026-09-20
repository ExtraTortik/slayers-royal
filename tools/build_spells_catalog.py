#!/usr/bin/env python3
"""Build combat font templates and spell translation catalog for Slayers Royal (PS1).

Outputs:
- data/combat_font_template.png: 16x16 tile canvas (528x96 px, 33 cols x 6 rows)
- data/combat_font_reference_grid.png: Enlarged visual guide with tile grid and labels
- translations/spells_ru.json: Full catalog of all 119 spells/options (entries 325..443)
"""

from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import read_extent
from localization.sr_charmap import build_charmap
from tools.patch_combat_font import (
    CANONICAL_ASCII_GLYPHS,
    CYRILLIC_UPPER,
    CYRILLIC_LOWER,
    CYR_UPPER_WIDTHS,
    CYR_LOWER_WIDTHS,
    get_hw_tile_2bpp,
    render_cyrillic_glyph_2bpp,
    find_press_start_font,
    unpack_combat_font,
    tile_image_to_2bpp,
    is_tile_empty,
    import_combat_font_template,
)
from tools.generate_combat_dialogues_ru import COMPLETE_EN_DIGRAPHS
from tools.patch_inspection import read_sector, parse_iso_dir, read_unt_index

# 4-level shading palette
COLOR_TRANSPARENT = (0, 0, 0, 0)
COLOR_BLACK = (0, 0, 0, 255)
COLOR_GREY = (128, 128, 128, 255)
COLOR_WHITE = (255, 255, 255, 255)

PALETTE_2BPP = {
    0: COLOR_TRANSPARENT,
    1: COLOR_BLACK,
    2: COLOR_GREY,
    3: COLOR_WHITE,
}

ROW0_CHARS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456")
ROW1_CHARS = ['7', '8', '9', '.', ',', '!', '?', ':', '-', '/', '+', '%', '(', ')', '"', "'"]
EXTRA_PUNCT_MAP = {
    ';': 0x0005,
    '=': 0x0006,
    '*': 0x0003,
    '♥': 0x00B4,
    '♪': 0x00B5,
    '★': 0x0256,
}

CYR_UPPER_CHARS = list(CYRILLIC_UPPER)
CYR_LOWER_CHARS = list(CYRILLIC_LOWER)

# Additional English digraphs and codes
EN_DIGRAPHS = dict(COMPLETE_EN_DIGRAPHS)
EN_DIGRAPHS[0x0377] = "is"
EN_DIGRAPHS[0x0256] = "★"

# Clean Japanese charmap
JP_CHARMAP_CLEAN = dict(build_charmap())
JP_CHARMAP_CLEAN[0x00B8] = "・"
JP_CHARMAP_CLEAN[0x0256] = "★"
JP_CHARMAP_CLEAN[0x033A] = "態"
JP_CHARMAP_CLEAN[0x0371] = "術"
JP_CHARMAP_CLEAN[0x03D6] = " [N]"
JP_CHARMAP_CLEAN[0x03D7] = " [E]"
JP_CHARMAP_CLEAN[0x03D8] = " [S]"

GLYPH_TO_ASCII = {v: k for k, v in CANONICAL_ASCII_GLYPHS.items()}


def tile_2bpp_to_image(tile_bytes: bytes) -> Image.Image:
    """Convert 64-byte 2BPP tile into 16x16 RGBA Image."""
    im = Image.new("RGBA", (16, 16), COLOR_TRANSPARENT)
    pix = im.load()
    for y in range(16):
        for x_byte in range(4):
            b = tile_bytes[y * 4 + x_byte]
            pix[x_byte * 4 + 0, y] = PALETTE_2BPP[b & 3]
            pix[x_byte * 4 + 1, y] = PALETTE_2BPP[(b >> 2) & 3]
            pix[x_byte * 4 + 2, y] = PALETTE_2BPP[(b >> 4) & 3]
            pix[x_byte * 4 + 3, y] = PALETTE_2BPP[(b >> 6) & 3]
    return im


def make_blank_slot_with_border() -> Image.Image:
    """Create a 16x16 blank slot with 1px light guide border (#808080)."""
    im = Image.new("RGBA", (16, 16), COLOR_TRANSPARENT)
    pix = im.load()
    for x in range(16):
        pix[x, 0] = COLOR_GREY
        pix[x, 15] = COLOR_GREY
    for y in range(16):
        pix[0, y] = COLOR_GREY
        pix[15, y] = COLOR_GREY
    return im


CYR_UPPER_TO_EN = {
    "А": "A", "Б": "B", "В": "B", "Г": "L", "Д": "D", "Е": "E", "Ё": "E",
    "Ж": "X", "З": "3", "И": "N", "Й": "N", "К": "K", "Л": "A", "М": "M",
    "Н": "H", "О": "O", "П": "P", "Р": "P", "С": "C", "Т": "T", "У": "Y",
    "Ф": "O", "Х": "X", "Ц": "U", "Ч": "4", "Ш": "W", "Щ": "W", "Ъ": "B",
    "Ы": "B", "Ь": "B", "Э": "C", "Ю": "O", "Я": "R",
}

CYR_LOWER_TO_EN = {
    "а": "a", "б": "b", "в": "b", "г": "r", "д": "d", "е": "e", "ё": "e",
    "ж": "x", "з": "3", "и": "u", "й": "u", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "n", "р": "p", "с": "c", "т": "t", "у": "y",
    "ф": "o", "х": "x", "ц": "u", "ч": "4", "ш": "w", "щ": "w", "ъ": "b",
    "ы": "b", "ь": "b", "э": "c", "ю": "o", "я": "r",
}


def make_label_tile(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Create a 16x16 tile containing a crisp, readable text label badge."""
    im = Image.new("RGBA", (16, 16), COLOR_TRANSPARENT)
    for i in range(16):
        im.putpixel((i, 0), COLOR_GREY)
        im.putpixel((i, 15), COLOR_GREY)
        im.putpixel((0, i), COLOR_GREY)
        im.putpixel((15, i), COLOR_GREY)

    d = ImageDraw.Draw(im)
    bb = d.textbbox((0, 0), text, font=font)
    w = bb[2] - bb[0]
    h = bb[3] - bb[1]
    x = (16 - w) // 2 - bb[0]
    y = (16 - h) // 2 - bb[1]

    # 1px outline in black
    d.text((x + 1, y), text, font=font, fill=COLOR_BLACK)
    d.text((x - 1, y), text, font=font, fill=COLOR_BLACK)
    d.text((x, y + 1), text, font=font, fill=COLOR_BLACK)
    d.text((x, y - 1), text, font=font, fill=COLOR_BLACK)
    # White core
    d.text((x, y), text, font=font, fill=COLOR_WHITE)
    return im


def make_guide_tile(
    width: int,
    height: int,
    y_start: int = 2,
    x_start: int = 1,
) -> tuple[Image.Image, set[tuple[int, int]]]:
    """Create a 16x16 tile with outer border, guide corners, baseline, and transparent drawing interior."""
    im = Image.new("RGBA", (16, 16), COLOR_TRANSPARENT)
    guide_pixels = set()

    def set_guide(x: int, y: int) -> None:
        if 0 <= x < 16 and 0 <= y < 16:
            im.putpixel((x, y), COLOR_GREY)
            guide_pixels.add((x, y))

    # Outer cell border
    for i in range(16):
        set_guide(i, 0)
        set_guide(i, 15)
        set_guide(0, i)
        set_guide(15, i)

    x1 = x_start
    x2 = x_start + width - 1
    y1 = y_start
    y2 = y_start + height - 1

    arm_x = min(3, width // 2)
    arm_y = min(3, height // 2)

    # Corner brackets (subtle guide corners)
    for dx in range(arm_x):
        set_guide(x1 + dx, y1)
        set_guide(x2 - dx, y1)
        set_guide(x1 + dx, y2)
        set_guide(x2 - dx, y2)

    for dy in range(arm_y):
        set_guide(x1, y1 + dy)
        set_guide(x2, y1 + dy)
        set_guide(x1, y2 - dy)
        set_guide(x2, y2 - dy)

    # Baseline marker at Y=14
    for x in range(1, 15):
        if x % 2 == 0:
            set_guide(x, y2)

    return im, guide_pixels


def build_combat_font_template(
    decomp_142: bytes,
    font_path: Path,
    output_path: Path,
) -> tuple[Image.Image, dict[tuple[int, int], str]]:
    """Generate 528x96 RGBA PNG template (33 cols x 6 rows of 16x16 tiles).

    Layout:
    - Row 0: Latin reference letters A-Z and digits 0-6 (33 characters)
    - Row 1: English reference numbers and punctuation (33 characters)
    - Row 2: Russian uppercase labels (А..Я, 33 columns)
    - Row 3: Russian uppercase drawing tiles (empty drawing cells with guide markings)
    - Row 4: Russian lowercase labels (а..я, 33 columns)
    - Row 5: Russian lowercase drawing tiles (empty drawing cells with Small Caps guide markings)
    """
    COLS = 33
    ROWS = 6
    canvas = Image.new("RGBA", (COLS * 16, ROWS * 16), COLOR_TRANSPARENT)
    tile_labels: dict[tuple[int, int], str] = {}
    blank_tile = make_blank_slot_with_border()

    font_label = ImageFont.truetype(str(font_path), 8)

    # Pre-extract authentic glyphs
    authentic_glyphs: dict[str, Image.Image] = {}
    for ch, code in CANONICAL_ASCII_GLYPHS.items():
        authentic_glyphs[ch] = tile_2bpp_to_image(get_hw_tile_2bpp(decomp_142, code))

    for sym, code in EXTRA_PUNCT_MAP.items():
        authentic_glyphs[sym] = tile_2bpp_to_image(get_hw_tile_2bpp(decomp_142, code))

    # Row 0: Latin reference letters A-Z and digits 0-6 (33 characters)
    for col, ch in enumerate(ROW0_CHARS):
        img = authentic_glyphs.get(ch) or blank_tile
        canvas.paste(img, (col * 16, 0 * 16))
        tile_labels[(0, col)] = ch

    # Row 1: English reference numbers and punctuation: 7 8 9 . , ! ? : - / + % ( ) " '
    for col, ch in enumerate(ROW1_CHARS):
        img = authentic_glyphs.get(ch) or blank_tile
        canvas.paste(img, (col * 16, 1 * 16))
        tile_labels[(1, col)] = ch

    # Additional punctuation/symbols in Row 1 (Col 16..21) + blank slots (Col 22..32)
    extra_syms = [";", "=", "*", "♥", "♪", "★"]
    for idx, sym in enumerate(extra_syms):
        col = len(ROW1_CHARS) + idx
        img = authentic_glyphs.get(sym) or blank_tile
        canvas.paste(img, (col * 16, 1 * 16))
        tile_labels[(1, col)] = sym

    for col in range(len(ROW1_CHARS) + len(extra_syms), COLS):
        canvas.paste(blank_tile, (col * 16, 1 * 16))
        tile_labels[(1, col)] = " "

    # Row 2: Russian uppercase labels (all 33 letters: А..Я)
    for col, ch in enumerate(CYR_UPPER_CHARS):
        lbl = make_label_tile(ch, font_label)
        canvas.paste(lbl, (col * 16, 2 * 16))
        tile_labels[(2, col)] = ch

    # Row 3: Russian uppercase drawing tiles (all 33 letters: А..Я)
    for col, ch in enumerate(CYR_UPPER_CHARS):
        w = CYR_UPPER_WIDTHS.get(ch, 8)
        guide_tile, _ = make_guide_tile(width=w, height=13, y_start=2, x_start=1)
        canvas.paste(guide_tile, (col * 16, 3 * 16))
        tile_labels[(3, col)] = ch

    # Row 4: Russian lowercase labels (all 33 letters: а..я)
    for col, ch in enumerate(CYR_LOWER_CHARS):
        lbl = make_label_tile(ch, font_label)
        canvas.paste(lbl, (col * 16, 4 * 16))
        tile_labels[(4, col)] = ch

    # Row 5: Russian lowercase drawing tiles (all 33 letters: а..я)
    for col, ch in enumerate(CYR_LOWER_CHARS):
        w = CYR_LOWER_WIDTHS.get(ch, 8)
        guide_tile, _ = make_guide_tile(width=w, height=10, y_start=5, x_start=1)
        canvas.paste(guide_tile, (col * 16, 5 * 16))
        tile_labels[(5, col)] = ch

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "PNG")
    print(f"Saved {output_path} ({canvas.size[0]}x{canvas.size[1]})")
    return canvas, tile_labels


def build_combat_font_reference_grid(
    template: Image.Image,
    tile_labels: dict[tuple[int, int], str],
    output_path: Path,
    authentic_glyphs: dict[str, Image.Image] | None = None,
) -> Image.Image:
    """Generate high-contrast, annotated reference grid visual guide with side-by-side comparison."""
    SCALE = 4
    TILE_SIZE = 16 * SCALE  # 64 px
    CARD_W = 162
    CARD_H = 136
    CELL_PAD = 6
    CELL_W = CARD_W + CELL_PAD
    CELL_H = CARD_H + CELL_PAD

    COLS = 33
    ROWS = 6
    HEADER_H = 88
    SIDE_W = 160

    TOTAL_W = SIDE_W + COLS * CELL_W + 20
    TOTAL_H = HEADER_H + ROWS * CELL_H + 20

    img = Image.new("RGBA", (TOTAL_W, TOTAL_H), (20, 24, 34, 255))
    draw = ImageDraw.Draw(img)

    font_file = find_press_start_font()
    try:
        font_large = ImageFont.truetype(str(font_file), 13)
        font_mid = ImageFont.truetype(str(font_file), 10)
        font_small = ImageFont.truetype(str(font_file), 8)
        font_tiny = ImageFont.truetype(str(font_file), 6)
    except Exception:
        font_large = font_mid = font_small = font_tiny = ImageFont.load_default()

    if authentic_glyphs is None:
        try:
            decomp = unpack_combat_font()
            authentic_glyphs = {}
            for ch, code in CANONICAL_ASCII_GLYPHS.items():
                authentic_glyphs[ch] = tile_2bpp_to_image(get_hw_tile_2bpp(decomp, code))
            for sym, code in EXTRA_PUNCT_MAP.items():
                authentic_glyphs[sym] = tile_2bpp_to_image(get_hw_tile_2bpp(decomp, code))
        except Exception:
            authentic_glyphs = {}

    # 1. Main Title & Spec Banner
    draw.text(
        (20, 12),
        "SLAYERS ROYAL (PS1) - COMBAT FONT 16x16 PIXEL ART REFERENCE & DRAWING GUIDE (ENTRY 0x142)",
        fill=(255, 215, 0, 255),
        font=font_large,
    )
    draw.text(
        (20, 34),
        "2BPP Palette: [0] Transparent (checker) | [1] Black outline #000000 | [2] Grey guide #808080 | [3] White core #FFFFFF",
        fill=(170, 190, 220, 255),
        font=font_mid,
    )
    draw.text(
        (20, 56),
        "Upper: Height 13px (Y:2..14, Base:14) | Standard 8px (X:1..8) | Wide 10px (X:1..10) | Narrow 6px (X:1..6) || "
        "Lower: Small Caps Height 10px (Y:5..14, Base:14) | Std 8px | Wide 10px",
        fill=(140, 220, 170, 255),
        font=font_small,
    )

    # Side headers
    row_headers = [
        ("ROW 0", "Latin Reference\nLetters A-Z, 0-6\n(Authentic PS1)"),
        ("ROW 1", "Digits 7-9 &\nPunctuation\n(Authentic PS1)"),
        ("ROW 2", "Cyrillic Upper\nText Labels\n(А-Я, Col 00-32)"),
        ("ROW 3", "Cyrillic Upper\nDrawing Cells &\nEN Ref Comparison"),
        ("ROW 4", "Cyrillic Lower\nText Labels\n(а-я, Col 00-32)"),
        ("ROW 5", "Cyrillic Lower\nDrawing Cells &\nEN Ref Comparison"),
    ]

    for r_idx, (r_title, r_desc) in enumerate(row_headers):
        ry = HEADER_H + r_idx * CELL_H
        draw.rectangle(
            [10, ry + 4, SIDE_W - 10, ry + CARD_H - 4],
            fill=(28, 34, 48, 255),
            outline=(50, 70, 100, 255),
            width=1,
        )
        draw.text((16, ry + 12), r_title, fill=(255, 230, 100, 255), font=font_mid)
        y_off = ry + 36
        for line in r_desc.split("\n"):
            draw.text((16, y_off), line, fill=(180, 200, 220, 255), font=font_small)
            y_off += 16

    # Checkerboard pattern for 64x64
    checker = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (32, 38, 52, 255))
    ch_draw = ImageDraw.Draw(checker)
    sq = 8
    for cy in range(0, TILE_SIZE, sq):
        for cx in range(0, TILE_SIZE, sq):
            if ((cx // sq) + (cy // sq)) % 2 == 1:
                ch_draw.rectangle([cx, cy, cx + sq - 1, cy + sq - 1], fill=(44, 52, 70, 255))

    for r in range(ROWS):
        for c in range(COLS):
            cx = SIDE_W + c * CELL_W
            cy = HEADER_H + r * CELL_H

            # Card background
            draw.rectangle(
                [cx, cy, cx + CARD_W, cy + CARD_H],
                fill=(24, 28, 40, 255),
                outline=(45, 55, 75, 255),
                width=1,
            )

            lbl = tile_labels.get((r, c), "")
            tx = cx + 18
            ty = cy + 34

            if r in (3, 5):
                # Cyrillic drawing cell with side-by-side English comparison
                is_upper = (r == 3)
                ch = CYRILLIC_UPPER[c] if is_upper else CYRILLIC_LOWER[c]
                w = CYR_UPPER_WIDTHS.get(ch, 8) if is_upper else CYR_LOWER_WIDTHS.get(ch, 8)
                y1 = 2 if is_upper else 5
                y2 = 14
                en_ref = CYR_UPPER_TO_EN.get(ch) if is_upper else CYR_LOWER_TO_EN.get(ch)

                # Header banner
                draw.rectangle([cx + 1, cy + 1, cx + CARD_W - 1, cy + 22], fill=(34, 42, 60, 255))
                draw.text((cx + 6, cy + 5), f"'{ch}'", fill=(255, 255, 255, 255), font=font_small)
                draw.text((cx + 36, cy + 6), f"{w}px", fill=(255, 215, 0, 255), font=font_tiny)
                draw.text((cx + CARD_W - 36, cy + 6), f"C{c:02d}", fill=(120, 170, 230, 255), font=font_tiny)

                # Y ruler (Left of Cyrillic tile)
                draw.text((cx + 2, ty + y1 * 4 - 3), f"{y1:02d}", fill=(100, 230, 100, 255), font=font_tiny)
                draw.text((cx + 2, ty + y2 * 4 - 3), "14", fill=(255, 120, 120, 255), font=font_tiny)

                # X ruler (Top of Cyrillic tile)
                draw.text((tx + 1 * 4, ty - 9), "1", fill=(100, 230, 100, 255), font=font_tiny)
                draw.text((tx + w * 4 - 2, ty - 9), str(w), fill=(100, 230, 100, 255), font=font_tiny)

                # Paste Cyrillic drawing tile
                img.paste(checker, (tx, ty))
                tile_raw = template.crop((c * 16, r * 16, (c + 1) * 16, (r + 1) * 16))
                tile_scaled = tile_raw.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.NEAREST)
                img.paste(tile_scaled, (tx, ty), tile_scaled)
                draw.rectangle([tx - 1, ty - 1, tx + TILE_SIZE, ty + TILE_SIZE], outline=(70, 95, 135, 255), width=1)

                # Right side: English Reference Tile
                tx_en = tx + TILE_SIZE + 8
                draw.text((tx_en + 6, ty - 9), f"REF '{en_ref}'", fill=(180, 200, 240, 255), font=font_tiny)
                img.paste(checker, (tx_en, ty))
                if en_ref and en_ref in authentic_glyphs:
                    en_im = authentic_glyphs[en_ref].resize((TILE_SIZE, TILE_SIZE), Image.Resampling.NEAREST)
                    img.paste(en_im, (tx_en, ty), en_im)
                draw.rectangle([tx_en - 1, ty - 1, tx_en + TILE_SIZE, ty + TILE_SIZE], outline=(90, 120, 160, 255), width=1)

                # Footer
                draw.text((cx + 6, cy + CARD_H - 14), f"X:1..{w} Y:{y1}..14 | Base:14", fill=(160, 185, 215, 255), font=font_tiny)

            elif r in (2, 4):
                # Label row card
                draw.rectangle([cx + 1, cy + 1, cx + CARD_W - 1, cy + 22], fill=(30, 38, 54, 255))
                draw.text((cx + 6, cy + 5), f"LABEL '{lbl}'", fill=(255, 255, 255, 255), font=font_small)
                draw.text((cx + CARD_W - 36, cy + 6), f"C{c:02d}", fill=(120, 170, 230, 255), font=font_tiny)

                img.paste(checker, (tx, ty))
                tile_raw = template.crop((c * 16, r * 16, (c + 1) * 16, (r + 1) * 16))
                tile_scaled = tile_raw.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.NEAREST)
                img.paste(tile_scaled, (tx, ty), tile_scaled)
                draw.rectangle([tx - 1, ty - 1, tx + TILE_SIZE, ty + TILE_SIZE], outline=(60, 80, 115, 255), width=1)

                # Right metadata
                draw.text((tx + TILE_SIZE + 10, ty + 12), "TEXT LABEL", fill=(200, 220, 240, 255), font=font_tiny)
                draw.text((tx + TILE_SIZE + 10, ty + 28), f"U+{ord(lbl):04X}", fill=(150, 180, 210, 255), font=font_tiny)
                draw.text((tx + TILE_SIZE + 10, ty + 44), f"#{c+1} of 33", fill=(120, 160, 200, 255), font=font_tiny)

                draw.text((cx + 6, cy + CARD_H - 14), f"Header for Column {c:02d}", fill=(130, 150, 175, 255), font=font_tiny)

            else:
                # Authentic English reference row 0 or 1
                draw.rectangle([cx + 1, cy + 1, cx + CARD_W - 1, cy + 22], fill=(30, 38, 54, 255))
                draw.text((cx + 6, cy + 5), f"'{lbl}'" if lbl != " " else "BLANK", fill=(255, 255, 255, 255) if lbl != " " else (130, 140, 160, 255), font=font_small)
                draw.text((cx + CARD_W - 36, cy + 6), f"C{c:02d}", fill=(120, 170, 230, 255), font=font_tiny)

                img.paste(checker, (tx, ty))
                tile_raw = template.crop((c * 16, r * 16, (c + 1) * 16, (r + 1) * 16))
                tile_scaled = tile_raw.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.NEAREST)
                img.paste(tile_scaled, (tx, ty), tile_scaled)
                draw.rectangle([tx - 1, ty - 1, tx + TILE_SIZE, ty + TILE_SIZE], outline=(70, 95, 135, 255), width=1)

                # Right metadata
                hex_code = CANONICAL_ASCII_GLYPHS.get(lbl) or EXTRA_PUNCT_MAP.get(lbl)
                draw.text((tx + TILE_SIZE + 10, ty + 12), "AUTHENTIC", fill=(200, 240, 180, 255), font=font_tiny)
                if hex_code:
                    draw.text((tx + TILE_SIZE + 10, ty + 28), f"0x{hex_code:04X}", fill=(150, 210, 180, 255), font=font_tiny)
                    draw.text((tx + TILE_SIZE + 10, ty + 44), f"ASC: {ord(lbl[0])}", fill=(130, 180, 210, 255), font=font_tiny)

                draw.text((cx + 6, cy + CARD_H - 14), f"R{r}:C{c:02d} PS1 Tile", fill=(130, 150, 175, 255), font=font_tiny)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")
    print(f"Saved {output_path} ({img.size[0]}x{img.size[1]})")
    return img


def decode_en_text(words: list[int]) -> str:
    """Decode English text from 16-bit word stream using CANONICAL_ASCII_GLYPHS and digraphs."""
    res = []
    for w in words:
        if w == 0x00FF:
            break
        elif w == 0x00FD:
            res.append("<PAGE>")
        elif w == 0x00FE:
            res.append("\n")
        elif w == 0x00A3:
            res.append('"')
        elif w == 0x0000:
            continue
        elif w in EN_DIGRAPHS:
            res.append(EN_DIGRAPHS[w])
        elif w in GLYPH_TO_ASCII:
            res.append(GLYPH_TO_ASCII[w])
        else:
            res.append(f"[{hex(w)}]")
    return "".join(res)


def decode_jp_text(words: list[int]) -> str:
    """Decode Japanese text from 16-bit word stream using JP_CHARMAP_CLEAN."""
    res = []
    for w in words:
        if w == 0x00FF:
            break
        elif w == 0x00FD:
            res.append("<PAGE>")
        elif w == 0x00FE:
            res.append("\n")
        elif w == 0x00A3:
            res.append('"')
        elif w == 0x0000:
            continue
        elif w in JP_CHARMAP_CLEAN:
            res.append(JP_CHARMAP_CLEAN[w])
        elif w in GLYPH_TO_ASCII:
            res.append(GLYPH_TO_ASCII[w])
        else:
            res.append(f"[{hex(w)}]")
    return "".join(res)


def parse_spell_entry(text: str) -> tuple[str, list[str]]:
    """Split decoded text into spell title and description pages."""
    if '""' in text:
        parts = text.split('""', 1)
        title = parts[0].strip()
        body = parts[1].strip()
    else:
        lines = text.strip().split("\n", 1)
        if len(lines) > 1 and ("★" in lines[0] or lines[0].isupper() or len(lines[0]) < 25):
            title = lines[0].strip()
            body = lines[1].strip()
        else:
            title = text.strip()
            body = ""

    if body:
        pages = [p.strip() for p in body.split("<PAGE>")]
    else:
        pages = []
    return title, pages


# Full 119-entry Russian translations catalog
RUSSIAN_SPELL_TRANSLATIONS: dict[int, dict[str, Any]] = {
    325: {
        "title_ru": "СПРАВКА ПО МАГИИ",
        "pages_ru": []
    },
    326: {
        "title_ru": "Холи Блесс",
        "pages_ru": [
            "Очищает нежить,\nвключая призраков.",
            "Действует на всю нежить\nна карте боя."
        ]
    },
    327: {
        "title_ru": "Вис Фаранк",
        "pages_ru": [
            "Наполняет кулаки мага силой,\nповышая силу атаки.\nЭффективно против мазоку.",
            "Действует только\nна самого заклинателя."
        ]
    },
    328: {
        "title_ru": "Дилл Бранд",
        "pages_ru": [
            "Вздымает землю вверх\nвокруг заклинателя.",
            "Поражает всех в радиусе\n4 клеток, и врагов,\nи союзников."
        ]
    },
    329: {
        "title_ru": "Даг Хаут",
        "pages_ru": [
            "Превращает землю в шипы,\nпронзающие противника.",
            "Поражает всех в радиусе\n4 клеток, и врагов,\nи союзников."
        ]
    },
    330: {
        "title_ru": "Дим Винд",
        "pages_ru": [
            "Призывает яростный ветер,\nсдувающий противников.",
            "Сдувает всех в радиусе\n4 клеток, и врагов,\nи союзников."
        ]
    },
    331: {
        "title_ru": "Слипинг (Нага)",
        "pages_ru": [
            "Особая версия заклинания сна\nот госпожи Наги.",
            "Усыпляет заклинателя\nи всех в радиусе 4 клеток."
        ]
    },
    332: {
        "title_ru": "Драгу Слейв",
        "pages_ru": [
            "Сильнейшая чёрная магия.",
            "Наносит огромный урон\nвсем целям в зоне взрыва."
        ]
    },
    333: {
        "title_ru": "Драгу Слейв (Усил.)",
        "pages_ru": [
            "Усиленная версия\nДрагу Слейва.",
            "Наносит колоссальный урон\nвсем целям в зоне взрыва."
        ]
    },
    334: {
        "title_ru": "Флейр Эрроу (Нага)",
        "pages_ru": [
            "Создаёт огненные стрелы.\nВерсия от Наги.",
            "Атакует на 3 клетки вперёд.\nБьёт и врагов, и своих."
        ]
    },
    335: {
        "title_ru": "Фриз Эрроу (Нага)",
        "pages_ru": [
            "Создаёт ледяные стрелы.\nВерсия от Наги.",
            "Атакует на 3 клетки вперёд.\nБьёт и врагов, и своих."
        ]
    },
    336: {
        "title_ru": "Бласт Эш",
        "pages_ru": [
            "Обращает противника в прах\nодним точным ударом.",
            "Атакует в выбранном\nнаправлении."
        ]
    },
    337: {
        "title_ru": "Дайнаст Брес (Сильфиль)",
        "pages_ru": [
            "Чёрная магия, эффективная\nпротив мазоку.",
            "Атакует всех на линии\nв выбранном направлении."
        ]
    },
    338: {
        "title_ru": "Флейр Лэнс",
        "pages_ru": [
            "Усиленная версия\nФлейр Эрроу.",
            "Атакует в выбранном\nнаправлении."
        ]
    },
    339: {
        "title_ru": "Айсикл Лэнс",
        "pages_ru": [
            "Усиленная версия\nФриз Эрроу.",
            "Атакует в выбранном\nнаправлении."
        ]
    },
    340: {
        "title_ru": "Брам Гаш",
        "pages_ru": [
            "Выпускает ветряную стрелу,\nвзрывающуюся при попадании.",
            "Атакует в выбранном\nнаправлении."
        ]
    },
    341: {
        "title_ru": "Мега Бранд",
        "pages_ru": [
            "Вздымает землю вверх.\nМощнее Дилл Бранда.",
            "Атакует в выбранном\nнаправлении."
        ]
    },
    342: {
        "title_ru": "Дим Винд (Сильфиль)",
        "pages_ru": [
            "Направленная версия\nДим Винда.",
            "Сдувает всех на линии\nв выбранном направлении."
        ]
    },
    343: {
        "title_ru": "Астрал Вайн",
        "pages_ru": [
            "Зачаровывает оружие магией\nи повышает атаку. Эффективно\nпротив мазоку.",
            "Действует на оружие\nвыбранного союзника."
        ]
    },
    344: {
        "title_ru": "Зелас Брид",
        "pages_ru": [
            "Чёрная магия, эффективная\nпротив мазоку.",
            "Проходит сквозь цели,\nпоражая только выбранную."
        ]
    },
    345: {
        "title_ru": "Эльмекия Лэнс",
        "pages_ru": [
            "Астральная магия духа.\nЭффективно против мазоку.",
            "Поражает выбранную цель."
        ]
    },
    346: {
        "title_ru": "Брам Блейзер",
        "pages_ru": [
            "Магия духа, эффективная\nпротив мазоку.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    347: {
        "title_ru": "Бёрст Рондо",
        "pages_ru": [
            "Запускает множество сфер света\nв сторону врага.",
            "Поражает выбранного врага,\nзадевая тех, кто на пути."
        ]
    },
    348: {
        "title_ru": "Резоррекшн (Усил.)",
        "pages_ru": [
            "Полностью восстанавливает силы\nцели на расстоянии.",
            "Действует только\nна выбранную цель."
        ]
    },
    349: {
        "title_ru": "Бомб Сприд",
        "pages_ru": [
            "Вызывает взрыв в выбранной\nточке поля боя.",
            "Поражает только\nвыбранную цель."
        ]
    },
    350: {
        "title_ru": "Дам Брасс",
        "pages_ru": [
            "Ударная магия духа.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    351: {
        "title_ru": "Драгу Слейв (Кристалл)",
        "pages_ru": [
            "Сконцентрированная версия\nДрагу Слейва.",
            "Поражает выбранную цель."
        ]
    },
    352: {
        "title_ru": "Гоз Ву Роу",
        "pages_ru": [
            "Магия духа, эффективная\nпротив мазоку.",
            "Поражает выбранную цель."
        ]
    },
    353: {
        "title_ru": "Ра Тильт",
        "pages_ru": [
            "Сильнейшее боевое\nзаклинание магии духа.",
            "Бьёт прямо по цели.\nОстальные цели не страдают."
        ]
    },
    354: {
        "title_ru": "Флейр Эрроу",
        "pages_ru": [
            "Создаёт огненную стрелу и\nмечет её во врага.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    355: {
        "title_ru": "Клей Бом",
        "pages_ru": [
            "Создаёт свет под врагом,\nа затем взрывает его.",
            "Бьёт прямо по цели.\nОстальные цели не страдают."
        ]
    },
    356: {
        "title_ru": "Фриз Эрроу",
        "pages_ru": [
            "Создаёт ледяную стрелу и\nмечет её во врага.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    357: {
        "title_ru": "Фриз Брид",
        "pages_ru": [
            "Швыряет ледяную сферу\nво врага.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    358: {
        "title_ru": "Брам Фанг",
        "pages_ru": [
            "Рассекает противника клинком\nиз сжатого ветра.",
            "Бьёт прямо по цели.\nОстальные цели не страдают."
        ]
    },
    359: {
        "title_ru": "Рекавери",
        "pages_ru": [
            "Восстанавливает здоровье\nвыбранному союзнику."
        ]
    },
    360: {
        "title_ru": "Дайнаст Брес",
        "pages_ru": [
            "Чёрная магия, эффективная\nпротив мазоку.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    361: {
        "title_ru": "Демона Кристал",
        "pages_ru": [
            "Замораживает противника.",
            "Поражает выбранную цель,\nзадевая тех, кто на пути."
        ]
    },
    362: {
        "title_ru": "Моно Вольт",
        "pages_ru": [
            "Удар молнией, способный\nпарализовать цель.",
            "Бьёт прямо по цели.\nОстальные цели не страдают."
        ]
    },
    363: {
        "title_ru": "Лайтинг",
        "pages_ru": []
    },
    364: {
        "title_ru": "Рагна Блейд",
        "pages_ru": [
            "Создаёт грозный тёмный клинок\nв руках заклинателя.",
            "Атакует только соседнюю\nклетку."
        ]
    },
    365: {
        "title_ru": "Диг Вольт",
        "pages_ru": [
            "Усиленный Моно Вольт.\nМожет парализовать цель.",
            "Атакует только соседнюю\nклетку."
        ]
    },
    366: {
        "title_ru": "Дим Винд (Кристалл)",
        "pages_ru": [
            "Версия Дим Винда радиусом\nв 1 клетку.",
            "Действует только на соседнюю\nклетку."
        ]
    },
    367: {
        "title_ru": "Лайтинг",
        "pages_ru": []
    },
    368: {
        "title_ru": "Слипинг",
        "pages_ru": [
            "Усыпляет стоящего рядом\nпротивника."
        ]
    },
    369: {
        "title_ru": "Резоррекшн",
        "pages_ru": [
            "Полностью восстанавливает силы\nсоседнего союзника."
        ]
    },
    370: {
        "title_ru": "Диклиари",
        "pages_ru": [
            "Исцеляет от обморока, сна и\nпохожих недугов.",
            "Действует только на соседнюю\nклетку."
        ]
    },
    371: {
        "title_ru": "Бёрст Флейр",
        "pages_ru": [
            "Сильнейшая магия огня.\nНе действует на мазоку.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    372: {
        "title_ru": "Файербол",
        "pages_ru": [
            "Разит пламенем справедливости\nи твёрдой веры.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    373: {
        "title_ru": "Бласт Бом",
        "pages_ru": [
            "Мощнейшая версия\nБёрст Рондо.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    374: {
        "title_ru": "Бомб Сприд B",
        "pages_ru": [
            "Взрывает выбранную клетку.",
            "Поражает область вокруг точки,\nне задевая союзников."
        ]
    },
    375: {
        "title_ru": "Дам Брасс B",
        "pages_ru": [
            "Широкозонная версия\nДам Брасса.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    376: {
        "title_ru": "Дайнаст Брес B",
        "pages_ru": [
            "Широкозонная версия\nДайнаст Бреса.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    377: {
        "title_ru": "Ра Тильт B",
        "pages_ru": [
            "Широкозонная версия\nРа Тильта.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    378: {
        "title_ru": "Файербол",
        "pages_ru": [
            "Швыряет огненный шар\nво врагов.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Бойцы между заклинателем\nи целью могут пострадать."
        ]
    },
    379: {
        "title_ru": "Аэро Бом",
        "pages_ru": [
            "Взрывает сферу сжатого воздуха.",
            "Поражает выбранную клетку и\nобласть вокруг неё.",
            "Задевает тех, кто оказался\nв радиусе взрыва."
        ]
    },
    380: {
        "title_ru": "Дилл Бранд B",
        "pages_ru": [
            "Дилл Бранд, направленный\nв выбранную точку.",
            "Поражает саму клетку и\nобласть вокруг неё."
        ]
    },
    381: {
        "title_ru": "Даг Хаут B",
        "pages_ru": [
            "Даг Хаут, направленный\nв выбранную точку.",
            "Поражает саму клетку и\nобласть вокруг неё."
        ]
    },
    382: {
        "title_ru": "Рекавери B",
        "pages_ru": [
            "Массовая версия заклинания\nРекавери.",
            "Исцеляет выбранную клетку и\nсоюзников вокруг неё."
        ]
    },
    383: {
        "title_ru": "СТАРТ",
        "pages_ru": [
            "Начать атаку.",
            "Бойцы выполняют отданные\nприказы.",
            "Поставьте бой на паузу,\nчтобы изменить приказы.",
            "Выберите авто-настройку,\nчтобы бойцы действовали сами."
        ]
    },
    384: {
        "title_ru": "НАСТРОЙКИ",
        "pages_ru": [
            "ИЗМЕНИТЬ НАСТРОЙКИ ИГРЫ."
        ]
    },
    385: {
        "title_ru": "НАСТРОЙКА АТАКИ",
        "pages_ru": [
            "Задать способ атаки\nи цель."
        ]
    },
    386: {
        "title_ru": "НАСТРОЙКА КОНТРАТАКИ",
        "pages_ru": [
            "Задать действие бойца\nпри нападении врага."
        ]
    },
    387: {
        "title_ru": "НАСТРОЙКА ЗАКЛИНАНИЙ",
        "pages_ru": [
            "Выбрать заклинание\nдля применения."
        ]
    },
    388: {
        "title_ru": "АТАКА",
        "pages_ru": [
            "Атаковать врага, пока он\nили нападающий не падет."
        ]
    },
    389: {
        "title_ru": "УДАР",
        "pages_ru": [
            "Бить врага, пока он\nили нападающий не падет."
        ]
    },
    390: {
        "title_ru": "ТАРАН",
        "pages_ru": [
            "Оттолкнуть врага ударом тела."
        ]
    },
    391: {
        "title_ru": "ДВИЖЕНИЕ",
        "pages_ru": [
            "Перейти в выбранную точку\nи остановиться.",
            "Выберите бойца, чтобы следовать\nза ним."
        ]
    },
    392: {
        "title_ru": "ТАПОЧКА",
        "pages_ru": [
            "Атаковать врага тапочкой."
        ]
    },
    393: {
        "title_ru": "СМЕХ",
        "pages_ru": [
            "Высмеять вражескую атаку.",
            "Снижает урон и может остановить\nдальнейшие нападения."
        ]
    },
    394: {
        "title_ru": "ОТВЕТ",
        "pages_ru": [
            "Контратаковать врага при нападении."
        ]
    },
    395: {
        "title_ru": "ОТВЕТНЫЙ УДАР",
        "pages_ru": [
            "Ударить в ответ на вражескую атаку."
        ]
    },
    396: {
        "title_ru": "УКЛОНЕНИЕ",
        "pages_ru": [
            "Контратака невозможна, но атаки\nи магия врага мажут."
        ]
    },
    397: {
        "title_ru": "ПОБЕГ",
        "pages_ru": [
            "Позволяет уйти от большинства атак.",
            "Контратака отключена."
        ]
    },
    398: {
        "title_ru": "ТЕРПЕТЬ",
        "pages_ru": [
            "Выдержать удар, снизив урон."
        ]
    },
    399: {
        "title_ru": "ЗАЩИТА",
        "pages_ru": [
            "Блокирует большинство ударов оружием."
        ]
    },
    400: {
        "title_ru": "БАРЬЕР",
        "pages_ru": [
            "Защитная магия против вражеских чар.",
            "Не блокирует сверхмощные\nили особые заклинания."
        ]
    },
    401: {
        "title_ru": "КАСТ",
        "pages_ru": [
            "Начать чтение заклинания."
        ]
    },
    402: {
        "title_ru": "ОТМЕНА",
        "pages_ru": [
            "Прервать чтение заклинания."
        ]
    },
    403: {
        "title_ru": "МАГИЯ",
        "pages_ru": [
            "Использовать магию."
        ]
    },
    404: {
        "title_ru": "АВТО-НАСТРОЙКА",
        "pages_ru": [
            "Позволяет бойцу действовать\nавтоматически."
        ]
    },
    405: {
        "title_ru": "АТАКУЮЩИЙ",
        "pages_ru": [
            "Авто-режим с упором на победу\nнад врагами.",
            "Этот режим активен\nпри начале боя."
        ]
    },
    406: {
        "title_ru": "ЗАЩИТНЫЙ",
        "pages_ru": [
            "Авто-режим с упором на поддержку\nсоюзников."
        ]
    },
    407: {
        "title_ru": "АВТО",
        "pages_ru": [
            "Боец сам выбирает свои действия.",
            "Некоторые характеры делают\nповедение непредсказуемым.",
            "Рекомендуется сначала\nсохраниться."
        ]
    },
    408: {
        "title_ru": "РУЧНОЙ (ЛИСЕЛЛИ)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    409: {
        "title_ru": "РУЧНОЙ (ЛИНА)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    410: {
        "title_ru": "РУЧНОЙ (ГАУРИ)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    411: {
        "title_ru": "РУЧНОЙ (ЗЕЛГАДИС)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    412: {
        "title_ru": "РУЧНОЙ (АМЕЛИЯ)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    413: {
        "title_ru": "РУЧНОЙ (СИЛЬФИЛЬ)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    414: {
        "title_ru": "РУЧНОЙ (НАГА)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    415: {
        "title_ru": "РУЧНОЙ (ЛАРК)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    416: {
        "title_ru": "РУЧНОЙ (ДИОН)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    417: {
        "title_ru": "РУЧНОЙ (ЗОДД)",
        "pages_ru": [
            "Отключает авто-режим для\nпрямого управления."
        ]
    },
    418: {
        "title_ru": "СОХРАНЕНИЕ",
        "pages_ru": [
            "СОХРАНИТЬ ИГРУ.",
            "НЕ ВЫКЛЮЧАЙТЕ ПИТАНИЕ."
        ]
    },
    419: {
        "title_ru": "ЗАГРУЗКА",
        "pages_ru": [
            "ЗАГРУЗИТЬ ДАННЫЕ.",
            "НЕСОХРАНЁННЫЙ ПРОГРЕСС\nБУДЕТ ПОТЕРЯН."
        ]
    },
    420: {
        "title_ru": "★★ АНИМАЦИЯ ★★",
        "pages_ru": [
            "АНИМАЦИЯ БОЯ: ВКЛ"
        ]
    },
    421: {
        "title_ru": "★★ АНИМАЦИЯ ★★",
        "pages_ru": [
            "АНИМАЦИЯ БОЯ: ВЫКЛ"
        ]
    },
    422: {
        "title_ru": "★★ ТЕКСТ БОЯ ★★",
        "pages_ru": [
            "ДИАЛОГИ В БОЮ\nВКЛ"
        ]
    },
    423: {
        "title_ru": "★★ ТЕКСТ БОЯ ★★",
        "pages_ru": [
            "ДИАЛОГИ В БОЮ\nВЫКЛ"
        ]
    },
    424: {
        "title_ru": "★★★ СЕТКА ★★★",
        "pages_ru": [
            "ЛИНИИ СЕТКИ КАРТЫ\nВКЛ"
        ]
    },
    425: {
        "title_ru": "★★★ СЕТКА ★★★",
        "pages_ru": [
            "ЛИНИИ СЕТКИ КАРТЫ\nВЫКЛ"
        ]
    },
    426: {
        "title_ru": "★★★ ЗВУК ★★★",
        "pages_ru": [
            "МУЗЫКА ВКЛ"
        ]
    },
    427: {
        "title_ru": "★★★ ЗВУК ★★★",
        "pages_ru": [
            "МУЗЫКА ВЫКЛ"
        ]
    },
    428: {
        "title_ru": "★★★ ЭФФЕКТЫ ★★★",
        "pages_ru": [
            "ЗВУКОВЫЕ ЭФФЕКТЫ ВКЛ"
        ]
    },
    429: {
        "title_ru": "★★★ ЭФФЕКТЫ ★★★",
        "pages_ru": [
            "ЗВУКОВЫЕ ЭФФЕКТЫ ВЫКЛ"
        ]
    },
    430: {
        "title_ru": "★★ НАВИГАЦИЯ ★★",
        "pages_ru": [
            "ПОДСКАЗКИ НАВИГАЦИИ\nВКЛ"
        ]
    },
    431: {
        "title_ru": "★★ НАВИГАЦИЯ ★★",
        "pages_ru": [
            "ПОДСКАЗКИ НАВИГАЦИИ\nВЫКЛ"
        ]
    },
    432: {
        "title_ru": "★★ ТОЧКИ-ПОДСКАЗКИ ★★",
        "pages_ru": [
            "ПОКАЗЫВАТЬ АКТИВНЫЕ ТОЧКИ"
        ]
    },
    433: {
        "title_ru": "★★ ТОЧКИ-ПОДСКАЗКИ ★★",
        "pages_ru": [
            "СКРЫВАТЬ АКТИВНЫЕ ТОЧКИ"
        ]
    },
    434: {
        "title_ru": "★★ СКОРОСТЬ ТЕКСТА ★★",
        "pages_ru": [
            "ВЫВОД ПО СТРОКАМ:\nБЫСТРО"
        ]
    },
    435: {
        "title_ru": "★★ СКОРОСТЬ ТЕКСТА ★★",
        "pages_ru": [
            "ВЫВОД ПО БУКВАМ:\nМЕДЛЕННО"
        ]
    },
    436: {
        "title_ru": "★★ НАВИГАЦИЯ ★★",
        "pages_ru": [
            "ПОДСКАЗКИ НАВИГАЦИИ\nВКЛ"
        ]
    },
    437: {
        "title_ru": "★★ НАВИГАЦИЯ ★★",
        "pages_ru": [
            "ПОДСКАЗКИ НАВИГАЦИИ\nВЫКЛ"
        ]
    },
    438: {
        "title_ru": "ГОЛОСОВЫЕ КОММЕНТАРИИ",
        "pages_ru": [
            "НАЖМИТЕ КРУГ ДЛЯ ОТМЕНЫ"
        ]
    },
    439: {
        "title_ru": "ГОЛОСОВЫЕ КОММЕНТАРИИ",
        "pages_ru": [
            "НАЖМИТЕ КРЕСТ ДЛЯ ОТМЕНЫ"
        ]
    },
    440: {
        "title_ru": "★★ ТОЧКИ-ПОДСКАЗКИ ★★",
        "pages_ru": [
            "ПОКАЗЫВАТЬ АКТИВНЫЕ ТОЧКИ"
        ]
    },
    441: {
        "title_ru": "★★ ТОЧКИ-ПОДСКАЗКИ ★★",
        "pages_ru": [
            "СКРЫВАТЬ АКТИВНЫЕ ТОЧКИ"
        ]
    },
    442: {
        "title_ru": "★★★ ЗВУК ★★★",
        "pages_ru": [
            "ВЫХОД: СТЕРЕО\nВЫБРАНО"
        ]
    },
    443: {
        "title_ru": "★★★ ЗВУК ★★★",
        "pages_ru": [
            "ВЫХОД: МОНО\nВЫБРАНО"
        ]
    },
}


def build_spells_catalog(
    en_bin: Path,
    jp_bin: Path,
    output_json: Path,
) -> list[dict[str, Any]]:
    """Extract and decode all 119 entries and save structured JSON."""
    pvd_en = read_sector(en_bin, 16)
    root_lba_en = struct.unpack_from("<I", pvd_en, 156 + 2)[0]
    root_size_en = struct.unpack_from("<I", pvd_en, 156 + 10)[0]
    root_dir_en = parse_iso_dir(en_bin, root_lba_en, root_size_en)
    prog_lba_en, _ = root_dir_en["PROG.UNT"]
    sec0_en = read_extent(en_bin, prog_lba_en, 2048)
    entries_en = read_unt_index(sec0_en)

    entries_jp = None
    prog_lba_jp = None
    if jp_bin.is_file():
        pvd_jp = read_sector(jp_bin, 16)
        root_lba_jp = struct.unpack_from("<I", pvd_jp, 156 + 2)[0]
        root_size_jp = struct.unpack_from("<I", pvd_jp, 156 + 10)[0]
        root_dir_jp = parse_iso_dir(jp_bin, root_lba_jp, root_size_jp)
        prog_lba_jp, _ = root_dir_jp["PROG.UNT"]
        sec0_jp = read_extent(jp_bin, prog_lba_jp, 2048)
        entries_jp = read_unt_index(sec0_jp)

    catalog: list[dict[str, Any]] = []

    for idx in range(325, 444):
        e_en = entries_en[idx]
        data_en = read_extent(en_bin, prog_lba_en + e_en.start_sector, e_en.size)
        words_en = list(struct.unpack(f"<{len(data_en)//2}H", data_en))
        txt_en = decode_en_text(words_en)
        title_en, pages_en = parse_spell_entry(txt_en)

        title_jp = ""
        pages_jp: list[str] = []
        if entries_jp is not None and prog_lba_jp is not None:
            e_jp = entries_jp[idx]
            data_jp = read_extent(jp_bin, prog_lba_jp + e_jp.start_sector, e_jp.size)
            words_jp = list(struct.unpack(f"<{len(data_jp)//2}H", data_jp))
            txt_jp = decode_jp_text(words_jp)
            title_jp, pages_jp = parse_spell_entry(txt_jp)

        ru_info = RUSSIAN_SPELL_TRANSLATIONS.get(idx, {})
        title_ru = ru_info.get("title_ru", title_en)
        pages_ru = ru_info.get("pages_ru", pages_en)

        item = {
            "entry_index": idx,
            "entry_hex": f"0x{idx:03X}",
            "title_en": title_en,
            "title_ru": title_ru,
            "name_en": title_en,
            "name_ru": title_ru,
            "title_jp": title_jp,
            "desc_en": "\n\n".join(pages_en),
            "desc_ru": "\n\n".join(pages_ru),
            "pages_en": pages_en,
            "pages_ru": pages_ru,
        }
        catalog.append(item)

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {output_json} with {len(catalog)} entries")
    return catalog


def main() -> None:
    en_bin = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
    jp_bin = REPO_ROOT / "downloads" / "sr.bin"
    font_path = find_press_start_font()

    template_png = REPO_ROOT / "data" / "combat_font_template.png"
    reference_png = REPO_ROOT / "data" / "combat_font_reference_grid.png"
    spells_json = REPO_ROOT / "translations" / "spells_ru.json"

    print("Unpacking combat font TIM...")
    decomp_142 = unpack_combat_font(en_bin if en_bin.is_file() else None)

    print("Generating combat font template...")
    template, tile_labels = build_combat_font_template(decomp_142, font_path, template_png)

    print("Generating reference grid visual guide...")
    build_combat_font_reference_grid(template, tile_labels, reference_png)

    print("Extracting spells catalog...")
    build_spells_catalog(en_bin, jp_bin, spells_json)

    print("All tasks completed successfully!")


if __name__ == "__main__":
    main()
