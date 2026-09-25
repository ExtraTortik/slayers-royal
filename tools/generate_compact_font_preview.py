#!/usr/bin/env python3
"""Comprehensive visual preview and raw atlas generator for Slayers Royal scene 0x03E compact glyphs.

This script:
1. Extracts the exact 220 compact tokens chosen by choose_compact_tokens for scene 0x03E
   from dialogue.po / story_dialogues_ru.json.
2. Implements a pixel-perfect condensed rasterizer for all 2-character pairs with:
   - Exact waistline and baseline alignment matching standard 11pt Press Start 2P letters
     (waistline y=4, baseline y=10, descenders y=11, cap-height y=2).
   - Guaranteed 1-pixel crisp solid strokes without subpixel blur or thresholding artifacts.
   - Open counters for letters like о, а, р, у, е, etc.
   - Proportional kerning and word-spacing for space/punctuation pairs.
3. Renders a side-by-side in-game dialogue window comparison of 3 versions:
   (A) Current TTF Downscaled (7-8pt, sunken baseline, broken stems)
   (B) Improved Pixel-Art Condensed (crisp 1px strokes, proper height & baseline)
   (C) Standard Monolithic 11pt (without compact glyphs, 1 char/tile reference)
4. Renders the complete 220-glyph atlas grid (16 columns x 14 rows) showing both 3x
   enlarged pixel art and 1x in-game scale.
5. Saves:
   - compact_font_preview.png (high-resolution comprehensive evaluation image)
   - compact_font_atlas_raw.png (raw 256x224 contiguous 16x16 tile atlas)
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Set up paths
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))

from localization.glyphs import _font_path, _render_mask, _translation_lines, choose_compact_tokens
from localization.po import read_po
from localization.script import _tokenize

# ---------------------------------------------------------------------------
# 1. Pixel-Art Glyph Bitmaps (Crisp 1px strokes, open counters, strict baseline)
# ---------------------------------------------------------------------------

GLYPHS: dict[str, dict[str, Any]] = {}


def add_glyph(char: str, pattern: list[str] | str, y_offset: int) -> None:
    if isinstance(pattern, str):
        lines = [l.strip() for l in pattern.strip().splitlines() if l.strip()]
    else:
        lines = pattern
    GLYPHS[char] = {
        "lines": lines,
        "width": max(len(l) for l in lines),
        "height": len(lines),
        "y_offset": y_offset,
    }


# Space and punctuation
add_glyph(" ", ["...."], 4)  # width 4
add_glyph(".", ["##", "##"], 9)  # 2x2, y=9..10
add_glyph(",", ["##", "##", ".#", ".#"], 8)  # y=8..11 (descender to 11)
add_glyph("!", ["##", "##", "##", "##", "##", "##", "..", "##", "##"], 2)  # y=2..10
add_glyph(
    "?",
    [
        ".####.",
        "#....#",
        ".....#",
        "...##.",
        "..##..",
        "......",
        "..##..",
        "..##..",
    ],
    2,
)  # y=2..9
add_glyph("-", ["####"], 7)  # y=7
add_glyph("—", ["######"], 7)  # y=7, 6px wide em-dash
add_glyph("…", ["##.##.##", "##.##.##"], 9)  # 8px wide, y=9..10

# Lowercase Cyrillic (waistline y=4, baseline y=10, descenders to y=11, ascenders y=1..2)
add_glyph(
    "а",
    [
        ".####.",
        "#....#",
        "#....#",
        "######",
        "#....#",
        "#....#",
        "#....#",
    ],
    4,
)

add_glyph(
    "б",
    [
        ".#####",
        ".#....",
        ".#....",
        ".####.",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        ".####.",
    ],
    2,
)  # ascender to 2, y=2..10

add_glyph(
    "в",
    [
        "#####.",
        "#...##",
        "#...##",
        "#####.",
        "#...##",
        "#...##",
        "#####.",
    ],
    4,
)

add_glyph(
    "г",
    [
        "######",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
    ],
    4,
)

add_glyph(
    "д",
    [
        "..####.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        "#######",
        "#.....#",
    ],
    4,
)  # baseline 10, descender 11

add_glyph(
    "е",
    [
        ".####.",
        "#....#",
        "#....#",
        "######",
        "#.....",
        "#.....",
        ".####.",
    ],
    4,
)

add_glyph(
    "ё",
    [
        ".#..#.",
        "......",
        ".####.",
        "#....#",
        "#....#",
        "######",
        "#.....",
        "#.....",
        ".####.",
    ],
    2,
)  # dots at 2, body 4..10

add_glyph(
    "ж",
    [
        "#..#..#",
        "#..#..#",
        ".#.##.#",
        "..###..",
        ".#.##.#",
        "#..#..#",
        "#..#..#",
    ],
    4,
)  # 7px wide

add_glyph(
    "з",
    [
        "#####.",
        "....##",
        "....##",
        "..###.",
        "....##",
        "....##",
        "#####.",
    ],
    4,
)

add_glyph(
    "и",
    [
        "#....#",
        "#...##",
        "#..#.#",
        "#.##.#",
        "##...#",
        "#....#",
        "#....#",
    ],
    4,
)

add_glyph(
    "й",
    [
        "..##..",
        "#....#",
        "......",
        "#....#",
        "#...##",
        "#..#.#",
        "#.##.#",
        "##...#",
        "#....#",
    ],
    1,
)  # accent at 1..2, body at 4..10

add_glyph(
    "к",
    [
        "#...##",
        "#..##.",
        "#.##..",
        "####..",
        "#.##..",
        "#..##.",
        "#...##",
    ],
    4,
)

add_glyph(
    "л",
    [
        "..####",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        "##...#",
    ],
    4,
)

add_glyph(
    "м",
    [
        "#.....#",
        "##...##",
        "#.#.#.#",
        "#..#..#",
        "#.....#",
        "#.....#",
        "#.....#",
    ],
    4,
)  # 7px wide

add_glyph(
    "н",
    [
        "#....#",
        "#....#",
        "#....#",
        "######",
        "#....#",
        "#....#",
        "#....#",
    ],
    4,
)

add_glyph(
    "о",
    [
        ".####.",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        ".####.",
    ],
    4,
)

add_glyph(
    "п",
    [
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
    ],
    4,
)

add_glyph(
    "р",
    [
        "######",
        "#....#",
        "#....#",
        "######",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
    ],
    4,
)  # y=4..11 (descender to 11)

add_glyph(
    "с",
    [
        ".#####",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
        "#.....",
        ".#####",
    ],
    4,
)

add_glyph(
    "т",
    [
        "######",
        "..##..",
        "..##..",
        "..##..",
        "..##..",
        "..##..",
        "..##..",
    ],
    4,
)

add_glyph(
    "у",
    [
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        ".#####",
        ".....#",
        ".....#",
        ".####.",
    ],
    4,
)  # y=4..11 (descender to 11)

add_glyph(
    "ф",
    [
        "..##..",
        ".####.",
        "#.#..#",
        "######",
        "#.#..#",
        ".####.",
        "..##..",
        "..##..",
    ],
    3,
)  # ascender 3, descender 10/11

add_glyph(
    "х",
    [
        "#....#",
        ".#..#.",
        "..##..",
        "..##..",
        "..##..",
        ".#..#.",
        "#....#",
    ],
    4,
)

add_glyph(
    "ц",
    [
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#######",
        ".....##",
    ],
    4,
)  # y=4..11

add_glyph(
    "ч",
    [
        "#....#",
        "#....#",
        "#....#",
        ".#####",
        ".....#",
        ".....#",
        ".....#",
    ],
    4,
)

add_glyph(
    "ш",
    [
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#######",
    ],
    4,
)  # 7px wide

add_glyph(
    "щ",
    [
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "########",
        "......##",
    ],
    4,
)  # 8px wide, descender to 11

add_glyph(
    "ъ",
    [
        "###...",
        "..#...",
        "..####",
        "..#..#",
        "..#..#",
        "..#..#",
        "..####",
    ],
    4,
)

add_glyph(
    "ы",
    [
        "#...##",
        "#...##",
        "####.##",
        "#..#.##",
        "#..#.##",
        "#..#.##",
        "####.##",
    ],
    4,
)  # 7px wide

add_glyph(
    "ь",
    [
        "#.....",
        "#.....",
        "######",
        "#....#",
        "#....#",
        "#....#",
        "######",
    ],
    4,
)

add_glyph(
    "э",
    [
        "#####.",
        ".....#",
        ".....#",
        "..####",
        ".....#",
        ".....#",
        "#####.",
    ],
    4,
)

add_glyph(
    "ю",
    [
        "#..###.",
        "#.#...#",
        "###...#",
        "###...#",
        "###...#",
        "#.#...#",
        "#..###.",
    ],
    4,
)  # 7px wide

add_glyph(
    "я",
    [
        ".#####",
        "#....#",
        "#....#",
        ".#####",
        "..#..#",
        ".#...#",
        "#....#",
    ],
    4,
)

# Uppercase Cyrillic (cap-height y=2, baseline y=10)
add_glyph(
    "А",
    [
        ".####.",
        "#....#",
        "#....#",
        "#....#",
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "Б",
    [
        ".######",
        ".#.....",
        ".#.....",
        ".#####.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        ".#####.",
    ],
    2,
)

add_glyph(
    "В",
    [
        "######.",
        "#....##",
        "#....##",
        "######.",
        "#....##",
        "#....##",
        "#....##",
        "#....##",
        "######.",
    ],
    2,
)

add_glyph(
    "Г",
    [
        "#######",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
    ],
    2,
)

add_glyph(
    "Д",
    [
        "..####.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        ".##..#.",
        "#######",
        "#.....#",
    ],
    2,
)

add_glyph(
    "Е",
    [
        "#######",
        "#......",
        "#......",
        "#......",
        "######.",
        "#......",
        "#......",
        "#......",
        "#######",
    ],
    2,
)

add_glyph(
    "Ё",
    [
        ".#...#.",
        ".......",
        "#######",
        "#......",
        "#......",
        "######.",
        "#......",
        "#......",
        "#######",
    ],
    1,
)

add_glyph(
    "Ж",
    [
        "#..#..#",
        "#..#..#",
        ".#.##.#",
        "..###..",
        "..###..",
        ".#.##.#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
    ],
    2,
)

add_glyph(
    "З",
    [
        "#####.",
        ".....#",
        ".....#",
        "..###.",
        ".....#",
        ".....#",
        ".....#",
        ".....#",
        "#####.",
    ],
    2,
)

add_glyph(
    "И",
    [
        "#....#",
        "#...##",
        "#..#.#",
        "#.##.#",
        "##...#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "Й",
    [
        "..##..",
        "#....#",
        "......",
        "#....#",
        "#...##",
        "#..#.#",
        "#.##.#",
        "##...#",
        "#....#",
    ],
    1,
)

add_glyph(
    "К",
    [
        "#...##",
        "#..##.",
        "#.##..",
        "####..",
        "#.##..",
        "#..##.",
        "#...##",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "Л",
    [
        "..####",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        ".##..#",
        "##...#",
    ],
    2,
)

add_glyph(
    "М",
    [
        "#.....#",
        "##...##",
        "###.###",
        "#.###.#",
        "#..#..#",
        "#.....#",
        "#.....#",
        "#.....#",
        "#.....#",
    ],
    2,
)

add_glyph(
    "Н",
    [
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "О",
    [
        ".#####.",
        "#.....#",
        "#.....#",
        "#.....#",
        "#.....#",
        "#.....#",
        "#.....#",
        "#.....#",
        ".#####.",
    ],
    2,
)

add_glyph(
    "П",
    [
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "Р",
    [
        "######.",
        "#....##",
        "#....##",
        "#....##",
        "######.",
        "#......",
        "#......",
        "#......",
        "#......",
    ],
    2,
)

add_glyph(
    "С",
    [
        ".######",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        "#......",
        ".######",
    ],
    2,
)

add_glyph(
    "Т",
    [
        "#######",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
        "...#...",
    ],
    2,
)

add_glyph(
    "У",
    [
        "#....#",
        "#....#",
        "#....#",
        ".#..#.",
        "..##..",
        "...#..",
        "...#..",
        "..#...",
        ".#....",
    ],
    2,
)

add_glyph(
    "Ф",
    [
        "..###..",
        ".#####.",
        "#.#.#.#",
        "#.#.#.#",
        "#######",
        "#.#.#.#",
        "#.#.#.#",
        ".#####.",
        "..###..",
    ],
    2,
)

add_glyph(
    "Х",
    [
        "#....#",
        ".#..#.",
        "..##..",
        "...#..",
        "..##..",
        ".#..#.",
        "#....#",
        "#....#",
        "#....#",
    ],
    2,
)

add_glyph(
    "Ц",
    [
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#....#.",
        "#######",
        ".....##",
    ],
    2,
)

add_glyph(
    "Ч",
    [
        "#....#",
        "#....#",
        "#....#",
        ".#####",
        ".....#",
        ".....#",
        ".....#",
        ".....#",
        ".....#",
    ],
    2,
)

add_glyph(
    "Ш",
    [
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#..#..#",
        "#######",
    ],
    2,
)

add_glyph(
    "Щ",
    [
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "#..#..#.",
        "########",
        "......##",
    ],
    2,
)

add_glyph(
    "Ъ",
    [
        "####..",
        "..#...",
        "..#...",
        "..####",
        "..#..#",
        "..#..#",
        "..#..#",
        "..#..#",
        "..####",
    ],
    2,
)

add_glyph(
    "Ы",
    [
        "#....##",
        "#....##",
        "#####.##",
        "#...#.##",
        "#...#.##",
        "#...#.##",
        "#...#.##",
        "#...#.##",
        "#####.##",
    ],
    2,
)

add_glyph(
    "Ь",
    [
        "#.....",
        "#.....",
        "#.....",
        "######",
        "#....#",
        "#....#",
        "#....#",
        "#....#",
        "######",
    ],
    2,
)

add_glyph(
    "Э",
    [
        ".#####.",
        "......#",
        "......#",
        "......#",
        "..#####",
        "......#",
        "......#",
        "......#",
        ".#####.",
    ],
    2,
)

add_glyph(
    "Ю",
    [
        "#..####.",
        "#.#....#",
        "#.######",
        "#.######",
        "#.######",
        "#.######",
        "#.######",
        "#.#....#",
        "#..####.",
    ],
    2,
)

add_glyph(
    "Я",
    [
        ".#####",
        "#....#",
        "#....#",
        "#....#",
        ".#####",
        "..#..#",
        ".#...#",
        "#....#",
        "#....#",
    ],
    2,
)


def render_compact(token: str) -> np.ndarray:
    """Render a 2-character compact token into a 16x16 1-bit numpy mask."""
    canvas = np.zeros((16, 16), dtype=np.uint8)
    if len(token) != 2:
        return canvas

    c1, c2 = token[0], token[1]
    g1 = GLYPHS.get(c1)
    g2 = GLYPHS.get(c2)
    if not g1 or not g2:
        return canvas

    w1, w2 = g1["width"], g2["width"]

    # Determine horizontal placement and kerning
    if c1 == " ":
        # Word space on the left, character in the right half
        x2 = 16 - w2 - 1  # e.g. w2=6 -> x2=9 (leaves x=0..8 as word space)
        x1 = 0
    elif c2 == " ":
        # Character in the left half, word space on the right
        x1 = 1  # 1px margin on left, leaves x=7..15 as word space
        x2 = 16
    elif c2 in ".,!?:;":
        # Character followed by tight punctuation
        gap = 1
        total_w = w1 + gap + w2
        x1 = max(0, (16 - total_w) // 2)
        x2 = x1 + w1 + gap
    else:
        # Standard 2-letter pair
        gap = 1
        total_w = w1 + gap + w2
        if total_w > 16:
            gap = 0
            total_w = w1 + w2
        x1 = max(0, (16 - total_w) // 2)
        x2 = x1 + w1 + gap

    # Draw character 1
    if c1 != " ":
        for r, row in enumerate(g1["lines"]):
            y = g1["y_offset"] + r
            if 0 <= y < 16:
                for c, ch in enumerate(row):
                    if ch == "#" and 0 <= x1 + c < 16:
                        canvas[y, x1 + c] = 255

    # Draw character 2
    if c2 != " ":
        for r, row in enumerate(g2["lines"]):
            y = g2["y_offset"] + r
            if 0 <= y < 16:
                for c, ch in enumerate(row):
                    if ch == "#" and 0 <= x2 + c < 16:
                        canvas[y, x2 + c] = 255

    return canvas


def apply_text_style(
    mask_im: Image.Image,
    text_color: tuple[int, int, int] = (216, 192, 144),
    shadow_color: tuple[int, int, int] = (16, 16, 16),
) -> Image.Image:
    """Apply authentic PS1 font styling: text face with 1px dark drop-shadow."""
    w, h = mask_im.size
    arr = np.array(mask_im)

    shadow_mask = np.zeros_like(arr)
    shadow_mask[1:, 1:] = arr[:-1, :-1]

    out_arr = np.zeros((h, w, 4), dtype=np.uint8)

    is_shadow = (shadow_mask > 0) & (arr == 0)
    out_arr[is_shadow] = (*shadow_color, 255)

    is_text = arr > 0
    out_arr[is_text] = (*text_color, 255)

    return Image.fromarray(out_arr, mode="RGBA")


# ---------------------------------------------------------------------------
# 2. Extract 220 Tokens and Dialogue Strings
# ---------------------------------------------------------------------------


def get_scene_03e_tokens(limit: int = 420) -> tuple[list[str], Counter[str], dict[str, str]]:
    po_path = REPO_ROOT / "patch_repo" / "localization-work" / "ru" / "dialogue.po"
    entries = read_po(po_path)
    compact_entries = [
        e.translation
        for e in entries
        if e.translation and e.context.startswith("dialogue/03E/")
    ]

    lines = _translation_lines(compact_entries)
    tokens = choose_compact_tokens(lines, limit)

    counts: Counter[str] = Counter()
    for line in lines:
        counts.update(line[index : index + 2] for index in range(len(line) - 1))

    gm_path = (
        REPO_ROOT
        / "patch_repo"
        / "localization-work"
        / "ru"
        / "build"
        / "glyph_map.json"
    )
    token_to_glyph = {}
    if gm_path.exists():
        gm = json.loads(gm_path.read_text(encoding="utf-8"))
        token_to_glyph = {item["text"]: item["glyph"] for item in gm["compact_tokens"]}

    return tokens, counts, token_to_glyph


# ---------------------------------------------------------------------------
# 3. In-Game Dialogue Box Simulator
# ---------------------------------------------------------------------------


def create_dialogue_window(
    lines_masks: list[Image.Image], speaker: str = "ЛИНА"
) -> Image.Image:
    """Build an authentic in-game PS1 dialogue window at 1x resolution (276x84 px)."""
    win_w = 276
    win_h = 84

    im = Image.new("RGBA", (win_w, win_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # PS1 metallic/beveled border
    draw.rectangle(
        [4, 6, win_w - 5, win_h - 5],
        fill=(22, 24, 30, 255),
        outline=(50, 65, 95, 255),
    )
    draw.rectangle([5, 7, win_w - 6, win_h - 6], outline=(100, 130, 180, 255))
    draw.rectangle([6, 8, win_w - 7, win_h - 7], outline=(30, 38, 55, 255))

    # Inner dark background with subtle shading
    for y in range(9, win_h - 7):
        val = 20 + (y - 9) // 7
        draw.line([(7, y), (win_w - 8, y)], fill=(val, val + 2, val + 6, 255))

    # Render lines of text
    start_x = 18
    start_y = 15
    line_spacing = 20

    for l_idx, mask in enumerate(lines_masks):
        styled = apply_text_style(
            mask, text_color=(216, 192, 144), shadow_color=(8, 8, 12)
        )
        im.alpha_composite(styled, (start_x, start_y + l_idx * line_spacing))

    # Speaker tag at top left
    if speaker:
        fpath = _font_path()
        sfont = ImageFont.truetype(str(fpath), 8)
        sbbox = draw.textbbox((0, 0), speaker, font=sfont)
        sw = sbbox[2] - sbbox[0]

        badge_x = 14
        badge_y = 1
        badge_w = sw + 12
        badge_h = 13

        draw.rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            fill=(20, 45, 90, 255),
            outline=(130, 175, 240, 255),
        )
        draw.rectangle(
            [badge_x + 1, badge_y + 1, badge_x + badge_w - 1, badge_y + badge_h - 1],
            outline=(10, 25, 55, 255),
        )
        draw.text(
            (badge_x + 6, badge_y + 2),
            speaker,
            font=sfont,
            fill=(245, 245, 255, 255),
        )

    return im


# ---------------------------------------------------------------------------
# 4. Generate compact_font_atlas_raw.png (256x224 contiguous tiles)
# ---------------------------------------------------------------------------


def generate_raw_atlas(tokens: list[str]) -> Image.Image:
    cols = 16
    rows = 27
    raw_atlas = Image.new("RGBA", (cols * 16, rows * 16), (0, 0, 0, 0))

    for idx, token in enumerate(tokens):
        col = idx % cols
        row = idx // cols
        tx = col * 16
        ty = row * 16

        mat = render_compact(token)
        mask = Image.fromarray(mat, mode="L")
        styled = apply_text_style(
            mask, text_color=(216, 192, 144), shadow_color=(16, 16, 16)
        )
        raw_atlas.alpha_composite(styled, (tx, ty))

    return raw_atlas


# ---------------------------------------------------------------------------
# 5. Build Grid Cell for Section 2
# ---------------------------------------------------------------------------


def extract_mask_from_atlas(atlas: Image.Image, idx: int) -> Image.Image:
    col = (idx % 16) * 16
    row = (idx // 16) * 16
    crop = atlas.crop((col, row, col + 16, row + 16))
    px_in = crop.load()
    mask = Image.new("L", (16, 16), 0)
    px_out = mask.load()
    for py in range(16):
        for px in range(16):
            r, g, b, a = px_in[px, py]
            if a > 30 and (r > 40 or g > 40 or b > 40):
                px_out[px, py] = 255
    return mask


def create_grid_cell(
    index: int,
    token: str,
    count: int,
    glyph_hex: str,
    cell_w: int = 104,
    cell_h: int = 104,
    atlas_mask: Image.Image | None = None,
) -> Image.Image:
    im = Image.new("RGBA", (cell_w, cell_h), (22, 24, 30, 255))
    draw = ImageDraw.Draw(im)

    # Outer cell border
    draw.rectangle([0, 0, cell_w - 1, cell_h - 1], outline=(38, 42, 54, 255))
    draw.rectangle([2, 2, cell_w - 3, cell_h - 3], fill=(16, 17, 22, 255))

    # Render token mask
    if atlas_mask is not None:
        mask = atlas_mask
    else:
        mat = render_compact(token)
        mask = Image.fromarray(mat, mode="L")
    styled_1x = apply_text_style(
        mask, text_color=(220, 200, 150), shadow_color=(8, 8, 12)
    )
    styled_3x = styled_1x.resize((48, 48), Image.Resampling.NEAREST)

    # Fonts
    f_bold = Path("/usr/share/fonts/TTF/Hack-Bold.ttf")
    f_reg = Path("/usr/share/fonts/TTF/Hack-Regular.ttf")
    font_header = ImageFont.truetype(str(f_bold), 12)
    font_sub = ImageFont.truetype(str(f_reg), 9)
    font_hex = ImageFont.truetype(str(f_bold), 8)

    # Header strip
    draw.rectangle([3, 3, cell_w - 4, 21], fill=(28, 33, 44, 255))

    idx_str = f"#{index:03d}"
    draw.text((6, 6), idx_str, font=font_sub, fill=(130, 155, 195, 255))

    tok_display = f'"{token}"' if token != " " else '"  "'
    draw.text((44, 4), tok_display, font=font_header, fill=(255, 225, 140, 255))

    # 3x preview at (8, 27)
    draw.rectangle(
        [7, 26, 7 + 48 + 1, 26 + 48 + 1],
        outline=(50, 56, 70, 255),
        fill=(12, 13, 16, 255),
    )
    im.alpha_composite(styled_3x, (8, 27))

    # 1x preview at (70, 32)
    draw.rectangle(
        [69, 31, 69 + 16 + 1, 31 + 16 + 1],
        outline=(50, 56, 70, 255),
        fill=(12, 13, 16, 255),
    )
    im.alpha_composite(styled_1x, (70, 32))
    draw.text((71, 51), "1x", font=font_sub, fill=(100, 115, 140, 255))

    # Bottom strip: glyph hex ID & frequency count
    draw.rectangle([3, 82, cell_w - 4, cell_h - 4], fill=(20, 23, 30, 255))
    draw.text((6, 88), glyph_hex, font=font_hex, fill=(160, 140, 200, 255))
    cnt_str = f"{count}x"
    cnt_w = len(cnt_str) * 6
    draw.text(
        (cell_w - cnt_w - 6, 88),
        cnt_str,
        font=font_sub,
        fill=(110, 190, 140, 255),
    )

    return im


# ---------------------------------------------------------------------------
# 6. Master Visual Preview Assembler
# ---------------------------------------------------------------------------


def generate_compact_font_preview() -> None:
    tokens, counts, token_to_glyph = get_scene_03e_tokens()

    raw_atlas_path = REPO_ROOT / "compact_font_atlas_raw.png"
    loaded_raw_atlas: Image.Image | None = None
    if raw_atlas_path.is_file():
        loaded_raw_atlas = Image.open(raw_atlas_path).convert("RGBA")
        print(f"Loaded existing custom tiles from {raw_atlas_path}")

    token_to_idx = {tok: idx for idx, tok in enumerate(tokens)}

    # Dialogue text
    dialogue_lines = ["Ну вот мы и в", "Сонии. Слушай,", "Зел, прежде чем"]

    compact_map = {
        tok: int(token_to_glyph.get(tok, "0x00"), 16) for tok in tokens
    }

    # Version A: Current TTF Downscaled
    lines_A: list[Image.Image] = []
    for line in dialogue_lines:
        toks = _tokenize(line, compact_map)
        im = Image.new("L", (15 * 16, 16), 0)
        for i, tok in enumerate(toks):
            m = _render_mask(tok)
            m_bin = Image.eval(m, lambda p: 255 if p >= 80 else 0)
            im.paste(m_bin, (i * 16, 0))
        lines_A.append(im)

    # Version B: Improved Pixel-Art Condensed
    lines_B: list[Image.Image] = []
    for line in dialogue_lines:
        toks = _tokenize(line, compact_map)
        im = Image.new("L", (15 * 16, 16), 0)
        for i, tok in enumerate(toks):
            if len(tok) == 1:
                m = _render_mask(tok)
                m_bin = Image.eval(m, lambda p: 255 if p >= 80 else 0)
                im.paste(m_bin, (i * 16, 0))
            else:
                if loaded_raw_atlas is not None and tok in token_to_idx:
                    m_bin = extract_mask_from_atlas(loaded_raw_atlas, token_to_idx[tok])
                else:
                    mat = render_compact(tok)
                    m_bin = Image.fromarray(mat, mode="L")
                im.paste(m_bin, (i * 16, 0))
        lines_B.append(im)

    # Version C: Standard Monolithic 11pt
    lines_C: list[Image.Image] = []
    for line in dialogue_lines:
        im = Image.new("L", (15 * 16, 16), 0)
        for i, ch in enumerate(line):
            if ch != " ":
                m = _render_mask(ch)
                m_bin = Image.eval(m, lambda p: 255 if p >= 80 else 0)
                im.paste(m_bin, (i * 16, 0))
        lines_C.append(im)

    win_A = create_dialogue_window(lines_A, "ЛИНА")
    win_B = create_dialogue_window(lines_B, "ЛИНА")
    win_C = create_dialogue_window(lines_C, "ЛИНА")

    # Master canvas layout
    canvas_w = 1760
    # Sections heights: Header (100) + Section 1 (510) + Section 2 (2880) + Footer (70)
    canvas_h = 3600

    master = Image.new("RGBA", (canvas_w, canvas_h), (14, 15, 18, 255))
    draw = ImageDraw.Draw(master)

    # Fonts
    f_bold = Path("/usr/share/fonts/TTF/Hack-Bold.ttf")
    f_reg = Path("/usr/share/fonts/TTF/Hack-Regular.ttf")
    f_retro = _font_path()

    font_main_title = ImageFont.truetype(str(f_retro), 15)
    font_sub_title = ImageFont.truetype(str(f_bold), 13)
    font_sec_title = ImageFont.truetype(str(f_retro), 12)
    font_sec_sub = ImageFont.truetype(str(f_bold), 11)
    font_card_title = ImageFont.truetype(str(f_bold), 13)
    font_badge = ImageFont.truetype(str(f_bold), 10)
    font_diag = ImageFont.truetype(str(f_reg), 10)
    font_diag_bold = ImageFont.truetype(str(f_bold), 10)
    font_sub = ImageFont.truetype(str(f_reg), 9)

    # -----------------------------------------------------------------------
    # Top Header Banner
    # -----------------------------------------------------------------------
    draw.rectangle([0, 0, canvas_w, 94], fill=(18, 21, 28, 255))
    draw.line([(0, 94), (canvas_w, 94)], fill=(45, 52, 70, 255), width=2)

    title_text = "SLAYERS ROYAL (PS1) — SCENE 0x03E COMPACT GLYPHS TYPOGRAPHY & PREVIEW"
    draw.text(
        (32, 16),
        title_text,
        font=font_main_title,
        fill=(255, 215, 100, 255),
    )
    sub_text = "Evaluation of 420 Scoped Compact Tokens • Dialogue Window Comparison (2x Scale) • Complete 16x27 Atlas Grid"
    draw.text((32, 42), sub_text, font=font_sub_title, fill=(180, 195, 220, 255))

    # Metadata badges
    badges = [
        ("SCENE", "0x03E (Sonia City)", (40, 70, 120), (160, 200, 255)),
        ("BUDGET", "19 Sectors (38,912 B)", (60, 40, 90), (220, 170, 255)),
        ("DTE LIMIT", "420 Tokens", (25, 75, 45), (140, 230, 170)),
        ("FONT BASE", "Press Start 2P (11pt)", (80, 60, 20), (255, 210, 120)),
        ("ADVANCE", "X += 16 px (Fixed)", (75, 30, 30), (255, 160, 160)),
    ]

    bx = 32
    by = 68
    for label, val, bg_col, text_col in badges:
        bw = len(label) * 7 + len(val) * 7 + 22
        draw.rectangle(
            [bx, by, bx + bw, by + 18], fill=bg_col, outline=(70, 80, 100, 255)
        )
        draw.text(
            (bx + 6, by + 3), label, font=font_badge, fill=(220, 220, 220, 255)
        )
        draw.text(
            (bx + len(label) * 7 + 12, by + 3),
            val,
            font=font_badge,
            fill=text_col,
        )
        bx += bw + 14

    # -----------------------------------------------------------------------
    # Section 1: In-Game Dialogue Window Comparison
    # -----------------------------------------------------------------------
    sec1_y = 112
    draw.text(
        (32, sec1_y),
        "SECTION 1: IN-GAME DIALOGUE WINDOW COMPARISON (3-LINE PS1 WINDOW @ 2X SCALE)",
        font=font_sec_title,
        fill=(140, 200, 255, 255),
    )
    draw.text(
        (32, sec1_y + 20),
        'Target Dialogue: Scene 0x03E / E19C / Cue 001 ("Ну вот мы и в / Сонии. Слушай, / Зел, прежде чем")',
        font=font_sec_sub,
        fill=(140, 155, 180, 255),
    )

    card_y = sec1_y + 44
    card_w = 548
    card_h = 340
    gap_x = 26

    # 3 Cards data
    cards_data = [
        {
            "col": 0,
            "title": "(A) CURRENT TTF DOWNSCALED",
            "badge": "DEFECTIVE: SUNKEN & BLURRY",
            "badge_col": (140, 40, 40),
            "window": win_A,
            "diags": [
                (
                    "Method:",
                    "PressStart2P downscaled to 7-8pt via FreeType",
                ),
                (
                    "Height / Waist:",
                    "Height 4-5px (lines 7..10), top 6px completely empty",
                ),
                ("Baseline:", "Sunken to y=12 anchor, severe height jumping"),
                (
                    "Strokes & Stems:",
                    "Fractional subpixels & thresholding break stems",
                ),
                ("Counters:", "Counters in о, а, р, у fill in or collapse"),
            ],
        },
        {
            "col": 1,
            "title": "(B) IMPROVED PIXEL-ART CONDENSED",
            "badge": "RECOMMENDED DTE (100% MEMORY SAFE)",
            "badge_col": (20, 110, 50),
            "window": win_B,
            "diags": [
                ("Method:", "Custom 6-7px handcrafted pixel-art glyphs"),
                (
                    "Height / Waist:",
                    "Height 7-8px, exact waistline y=4 matching 11pt",
                ),
                (
                    "Baseline:",
                    "True baseline y=10 (descenders y=11), zero jumping",
                ),
                (
                    "Strokes & Stems:",
                    "Guaranteed 1-pixel solid strokes, no anti-aliasing",
                ),
                ("Counters:", "Clean open counters in all letters (о, а, р, у)"),
            ],
        },
        {
            "col": 2,
            "title": "(C) MONOLITHIC 11PT REFERENCE",
            "badge": "STANDARD 1-CHAR/TILE (REQUIRES EDIT)",
            "badge_col": (25, 75, 120),
            "window": win_C,
            "diags": [
                ("Method:", "Standard 11pt Press Start 2P (1 char/tile)"),
                (
                    "Height / Waist:",
                    "Height 7-10px, uniform cap-height and baseline",
                ),
                (
                    "Baseline:",
                    "True baseline y=10, standard 16px tile advance",
                ),
                ("Strokes & Stems:", "Uniform retro 2-3px block strokes"),
                ("Trade-off:", "Requires condensing 334 lines in 0x03E"),
            ],
        },
    ]

    for c in cards_data:
        cx = 32 + c["col"] * (card_w + gap_x)
        # Background card
        draw.rectangle(
            [cx, card_y, cx + card_w, card_y + card_h],
            fill=(18, 20, 26, 255),
            outline=(45, 50, 65, 255),
        )

        # Card header bar
        draw.rectangle(
            [cx, card_y, cx + card_w, card_y + 30], fill=(25, 28, 38, 255)
        )
        draw.text(
            (cx + 12, card_y + 8),
            c["title"],
            font=font_card_title,
            fill=(255, 255, 255, 255),
        )

        # Status badge
        badge_w = len(c["badge"]) * 7 + 14
        draw.rectangle(
            [
                cx + card_w - badge_w - 10,
                card_y + 6,
                cx + card_w - 10,
                card_y + 24,
            ],
            fill=c["badge_col"],
            outline=(80, 90, 110, 255),
        )
        draw.text(
            (cx + card_w - badge_w - 3, card_y + 8),
            c["badge"],
            font=font_badge,
            fill=(255, 255, 255, 255),
        )

        # 2x dialogue window
        win_2x = c["window"].resize((276 * 2, 84 * 2), Image.Resampling.NEAREST)
        win_x = cx + (card_w - 276 * 2) // 2
        win_y = card_y + 38
        master.alpha_composite(win_2x, (win_x, win_y))

        # Diagnostics section
        diag_start_y = win_y + 168 + 12
        draw.rectangle(
            [cx + 8, diag_start_y - 4, cx + card_w - 8, card_y + card_h - 8],
            fill=(14, 15, 20, 255),
            outline=(35, 40, 50, 255),
        )

        dy = diag_start_y
        for label, desc in c["diags"]:
            draw.text(
                (cx + 16, dy), label, font=font_diag_bold, fill=(200, 170, 110)
            )
            draw.text(
                (cx + 120, dy), desc, font=font_diag, fill=(210, 220, 235)
            )
            dy += 19

    # Zoomed Inset Callouts Row
    zoom_y = card_y + card_h + 16
    draw.rectangle(
        [32, zoom_y, 32 + 3 * card_w + 2 * gap_x, zoom_y + 72],
        fill=(19, 22, 28, 255),
        outline=(45, 52, 68, 255),
    )

    draw.text(
        (44, zoom_y + 8),
        "4X ZOOMED PIXEL ARTIFACT INSPECTION:",
        font=font_badge,
        fill=(255, 215, 100, 255),
    )

    # Render 4x crops of tokens "во", "ни", "й,"
    # Token "во"
    mask_vo_A = Image.eval(
        _render_mask("во"), lambda p: 255 if p >= 80 else 0
    )
    if loaded_raw_atlas is not None and "во" in token_to_idx:
        mask_vo_B = extract_mask_from_atlas(loaded_raw_atlas, token_to_idx["во"])
    else:
        mask_vo_B = Image.fromarray(render_compact("во"), mode="L")
    crop_vo_A = apply_text_style(mask_vo_A).resize(
        (64, 64), Image.Resampling.NEAREST
    )
    crop_vo_B = apply_text_style(mask_vo_B).resize(
        (64, 64), Image.Resampling.NEAREST
    )

    # Token "ни"
    mask_ni_A = Image.eval(
        _render_mask("ни"), lambda p: 255 if p >= 80 else 0
    )
    if loaded_raw_atlas is not None and "ни" in token_to_idx:
        mask_ni_B = extract_mask_from_atlas(loaded_raw_atlas, token_to_idx["ни"])
    else:
        mask_ni_B = Image.fromarray(render_compact("ни"), mode="L")
    crop_ni_A = apply_text_style(mask_ni_A).resize(
        (64, 64), Image.Resampling.NEAREST
    )
    crop_ni_B = apply_text_style(mask_ni_B).resize(
        (64, 64), Image.Resampling.NEAREST
    )

    # Token "й,"
    mask_yj_A = Image.eval(
        _render_mask("й,"), lambda p: 255 if p >= 80 else 0
    )
    if loaded_raw_atlas is not None and "й," in token_to_idx:
        mask_yj_B = extract_mask_from_atlas(loaded_raw_atlas, token_to_idx["й,"])
    else:
        mask_yj_B = Image.fromarray(render_compact("й,"), mode="L")
    crop_yj_A = apply_text_style(mask_yj_A).resize(
        (64, 64), Image.Resampling.NEAREST
    )
    crop_yj_B = apply_text_style(mask_yj_B).resize(
        (64, 64), Image.Resampling.NEAREST
    )

    zx = 320
    crops = [
        ('Token "во":', crop_vo_A, crop_vo_B),
        ('Token "ни":', crop_ni_A, crop_ni_B),
        ('Token "й,":', crop_yj_A, crop_yj_B),
    ]

    for label, imA, imB in crops:
        draw.text((zx, zoom_y + 26), label, font=font_sub_title, fill=(240, 240, 240))
        # (A)
        draw.rectangle([zx + 110, zoom_y + 4, zx + 110 + 64, zoom_y + 68], outline=(120, 50, 50))
        master.alpha_composite(imA, (zx + 110, zoom_y + 4))
        draw.text((zx + 112, zoom_y + 54), "7pt (A)", font=font_sub, fill=(255, 120, 120))

        # (B)
        draw.rectangle([zx + 185, zoom_y + 4, zx + 185 + 64, zoom_y + 68], outline=(50, 120, 70))
        master.alpha_composite(imB, (zx + 185, zoom_y + 4))
        draw.text((zx + 187, zoom_y + 54), "1px (B)", font=font_sub, fill=(120, 255, 150))

        zx += 440

    # -----------------------------------------------------------------------
    # Section 2: Complete Atlas Grid of all 220 Compact Glyphs
    # -----------------------------------------------------------------------
    sec2_y = zoom_y + 96
    draw.text(
        (32, sec2_y),
        "SECTION 2: COMPLETE ATLAS GRID OF ALL 420 COMPACT GLYPHS (SCENE 0x03E)",
        font=font_sec_title,
        fill=(140, 200, 255, 255),
    )
    draw.text(
        (32, sec2_y + 20),
        "Frequency-Ordered Allocation (16 Columns x 27 Rows = 432 Cells) • Displaying 3X Zoomed Pixel Art + 1X In-Game Scale Tile",
        font=font_sec_sub,
        fill=(140, 155, 180, 255),
    )

    grid_start_y = sec2_y + 44
    cell_w = 104
    cell_h = 104
    grid_gap = 2

    for idx in range(432):
        col = idx % 16
        row = idx // 16
        gx = 32 + col * (cell_w + grid_gap)
        gy = grid_start_y + row * (cell_h + grid_gap)

        if idx < len(tokens):
            tok = tokens[idx]
            cnt = counts[tok]
            g_hex = token_to_glyph.get(tok, f"0x{0x057+idx:03X}")
            atlas_m = (
                extract_mask_from_atlas(loaded_raw_atlas, idx)
                if loaded_raw_atlas is not None and (idx // 16) * 16 + 16 <= loaded_raw_atlas.height
                else None
            )
            cell_im = create_grid_cell(
                idx, tok, cnt, g_hex, cell_w=cell_w, cell_h=cell_h, atlas_mask=atlas_m
            )
            master.alpha_composite(cell_im, (gx, gy))
        else:
            # Empty / reserved slot
            draw.rectangle(
                [gx, gy, gx + cell_w - 1, gy + cell_h - 1],
                fill=(18, 19, 24, 255),
                outline=(30, 34, 44, 255),
            )
            draw.text(
                (gx + 22, gy + 45),
                "[RESERVED]",
                font=font_sub,
                fill=(70, 80, 100, 255),
            )

    # -----------------------------------------------------------------------
    # Footer Summary Bar
    # -----------------------------------------------------------------------
    footer_y = grid_start_y + 27 * (cell_h + grid_gap) + 16
    draw.rectangle(
        [0, footer_y, canvas_w, canvas_h],
        fill=(16, 18, 24, 255),
    )
    draw.line([(0, footer_y), (canvas_w, footer_y)], fill=(45, 52, 70, 255), width=2)

    f_left = "Slayers Royal PS1 Russian Localization Project • Scoped Compact Glyphs Architecture (PROG.UNT 0x03A / 0x03E)"
    draw.text((32, footer_y + 12), f_left, font=font_sub_title, fill=(180, 190, 210, 255))

    f_right = (
        f"420 Glyphs Generated (Scene 0x03E) • Image: {canvas_w}x{canvas_h}"
    )
    draw.text((32, footer_y + 32), f_right, font=font_diag, fill=(130, 170, 140, 255))

    # Save compact_font_preview.png
    out_preview = REPO_ROOT / "compact_font_preview.png"
    master.save(out_preview)
    print(f"Generated {out_preview} ({canvas_w}x{canvas_h}) successfully!")

    # Save compact_font_atlas_raw.png
    out_raw = REPO_ROOT / "compact_font_atlas_raw.png"
    if not out_raw.exists():
        raw_im = generate_raw_atlas(tokens)
        raw_im.save(out_raw)
        print(f"Generated {out_raw} ({raw_im.size[0]}x{raw_im.size[1]}) successfully!")
    else:
        print(f"Preserving existing custom {out_raw}")


if __name__ == "__main__":
    generate_compact_font_preview()
