# -*- coding: utf-8 -*-
"""core/font_builder.py — Генератор тайловых шрифтов VRAM и кодовых таблиц (Charmap) для PS1.

Предоставляет:
1. Рендеринг TrueType (TTF/OTF) шрифтов в фиксированные тайлы (например, 16x16, 12x12, 8x8).
2. Построение двусторонней таблицы перекодировки (Unicode <-> Hex Code).
3. Экспорт тайлов в форматы:
   - 2bpp (2 бита/пиксель, 64 байта на тайл 16x16, как в боевом движке Slayers Royal).
   - 4bpp (4 бита/пиксель, 128 байт на тайл 16x16, стандартный TIM PS1).
   - 1-битная маска монохрома.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence
from PIL import Image, ImageDraw, ImageFont


def render_glyph_tile(
    char: str,
    font_path: Path | str,
    font_size: int,
    tile_w: int = 16,
    tile_h: int = 16,
    offset_x: int = 0,
    offset_y: int = 0
) -> Image.Image:
    """Отрисовка одного символа по центру тайла заданного размера."""
    img = Image.new("L", (tile_w, tile_h), 0)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), font_size)

    # Вычисляем габариты символа
    bbox = font.getbbox(char)
    char_w = bbox[2] - bbox[0]
    char_h = bbox[3] - bbox[1]

    # Центрирование с учётом пользовательского смещения
    x = (tile_w - char_w) // 2 + offset_x - bbox[0]
    y = (tile_h - char_h) // 2 + offset_y - bbox[1]

    draw.text((x, y), char, font=font, fill=255)
    return img


def pack_tile_2bpp(tile_img: Image.Image) -> bytes:
    """Упаковка тайла 16x16 (градации серого) в 2BPP (4 пикселя на байт, всего 64 байта)."""
    w, h = tile_img.size
    buf = bytearray()
    for y in range(h):
        for x_chunk in range(0, w, 4):
            val = 0
            for px in range(4):
                lum = tile_img.getpixel((x_chunk + px, y))
                # 4 уровня градации: 00 (фон), 01 (тень), 10 (тело), 11 (яркий блик)
                if lum < 64:
                    lvl = 0
                elif lum < 128:
                    lvl = 1
                elif lum < 192:
                    lvl = 2
                else:
                    lvl = 3
                val |= (lvl << (px * 2))
            buf.append(val)
    return bytes(buf)


def pack_tile_4bpp(tile_img: Image.Image, color_index: int = 15) -> bytes:
    """Упаковка тайла 16x16 в 4BPP (2 пикселя на байт, всего 128 байт)."""
    w, h = tile_img.size
    buf = bytearray()
    for y in range(h):
        for x in range(0, w, 2):
            p0 = tile_img.getpixel((x, y))
            p1 = tile_img.getpixel((x + 1, y))
            c0 = color_index if p0 > 128 else 0
            c1 = color_index if p1 > 128 else 0
            buf.append(c0 | (c1 << 4))
    return bytes(buf)


def build_font_atlas(
    chars: Sequence[str],
    font_path: Path | str,
    font_size: int,
    start_code: int = 0x0001,
    tile_w: int = 16,
    tile_h: int = 16,
    columns: int = 16
) -> tuple[Image.Image, dict[str, int]]:
    """Построение полного атласа шрифта и генерация таблицы charmap.json."""
    total = len(chars)
    rows = (total + columns - 1) // columns
    atlas_w = columns * tile_w
    atlas_h = rows * tile_h

    atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    charmap: dict[str, int] = {}

    for idx, ch in enumerate(chars):
        code = start_code + idx
        charmap[ch] = code

        col = idx % columns
        row = idx // columns
        gx = col * tile_w
        gy = row * tile_h

        glyph_tile = render_glyph_tile(ch, font_path, font_size, tile_w, tile_h)
        atlas_img.paste(glyph_tile.convert("RGBA"), (gx, gy))

    return atlas_img, charmap
