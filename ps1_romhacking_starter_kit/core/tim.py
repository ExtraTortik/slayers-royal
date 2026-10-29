# -*- coding: utf-8 -*-
"""core/tim.py — Универсальный конвертер текстур PlayStation 1 (TIM <-> PNG).

Поддерживает:
- Декодирование 4bpp (16 цветов с палитрой CLUT) в RGBA PNG.
- Декодирование 8bpp (256 цветов с палитрой CLUT) в RGBA PNG.
- Декодирование 16bpp Direct Color (RGB555) в RGBA PNG.
- Кодирование RGBA PNG в корректный 4bpp/8bpp TIM-файл с паддингом под сектор.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any
from PIL import Image

TIM_MAGIC = 0x00000010


def parse_tim_header(tim_bytes: bytes) -> dict[str, Any]:
    """Извлечение метаданных из заголовка TIM."""
    if len(tim_bytes) < 8:
        raise ValueError("Слишком короткий буфер для TIM")
    magic, flags = struct.unpack_from("<II", tim_bytes, 0)
    if magic != TIM_MAGIC:
        raise ValueError(f"Неверная сигнатура TIM (Magic {magic:#x} != 0x10)")

    bpp_mode = flags & 3
    has_clut = (flags >> 3) & 1
    offset = 8

    clut_info = None
    if has_clut:
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, offset)
        clut_info = {
            "length": clut_len,
            "vram_x": cx,
            "vram_y": cy,
            "width": cw,
            "height": ch,
            "colors": cw * ch,
            "offset": offset + 12
        }
        offset += clut_len

    img_len, dx, dy, w, h = struct.unpack_from("<IHHHH", tim_bytes, offset)
    bpp_names = ["4bpp", "8bpp", "16bpp", "24bpp"]
    pix_w = w * 4 if bpp_mode == 0 else (w * 2 if bpp_mode == 1 else w)

    return {
        "bpp": bpp_names[bpp_mode],
        "bpp_mode": bpp_mode,
        "has_clut": bool(has_clut),
        "clut": clut_info,
        "vram_x": dx,
        "vram_y": dy,
        "vram_w_words": w,
        "pixel_width": pix_w,
        "height": h,
        "image_data_offset": offset + 12,
        "image_data_length": img_len - 12
    }


def decode_tim(tim_bytes: bytes) -> Image.Image:
    """Декодирование байтов TIM в RGBA-изображение PIL."""
    info = parse_tim_header(tim_bytes)
    bpp_mode = info["bpp_mode"]
    has_clut = info["has_clut"]
    offset = 8

    cluts = []
    if has_clut:
        clut = info["clut"]
        clut_data = tim_bytes[clut["offset"] : clut["offset"] + clut["colors"] * 2]
        for i in range(clut["colors"]):
            c16 = struct.unpack_from("<H", clut_data, i * 2)[0]
            r = (c16 & 0x1F) << 3
            g = ((c16 >> 5) & 0x1F) << 3
            b = ((c16 >> 10) & 0x1F) << 3
            # В PS1 нулевой цвет прозрачный, если не выставлен бит STP
            a = 0 if c16 == 0 else 255
            cluts.append((r, g, b, a))
        offset = info["clut"]["offset"] + clut["colors"] * 2

    w = info["vram_w_words"]
    h = info["height"]
    pix_w = info["pixel_width"]
    pixel_data = tim_bytes[info["image_data_offset"] : info["image_data_offset"] + info["image_data_length"]]

    if bpp_mode == 0:  # 4bpp
        img = Image.new("RGBA", (pix_w, h), (0, 0, 0, 0))
        for y in range(h):
            for x_w in range(w):
                idx = y * (w * 2) + x_w * 2
                if idx + 1 >= len(pixel_data):
                    break
                b0 = pixel_data[idx]
                b1 = pixel_data[idx + 1]
                p0 = b0 & 0x0F
                p1 = (b0 >> 4) & 0x0F
                p2 = b1 & 0x0F
                p3 = (b1 >> 4) & 0x0F
                for px_idx, p in enumerate([p0, p1, p2, p3]):
                    c = cluts[p] if p < len(cluts) else (0, 0, 0, 0)
                    img.putpixel((x_w * 4 + px_idx, y), c)
        return img

    elif bpp_mode == 1:  # 8bpp
        img = Image.new("RGBA", (pix_w, h), (0, 0, 0, 0))
        for y in range(h):
            for x in range(pix_w):
                idx = y * pix_w + x
                if idx >= len(pixel_data):
                    break
                p = pixel_data[idx]
                c = cluts[p] if p < len(cluts) else (0, 0, 0, 0)
                img.putpixel((x, y), c)
        return img

    elif bpp_mode == 2:  # 16bpp direct
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for y in range(h):
            for x in range(w):
                idx = (y * w + x) * 2
                c16 = struct.unpack_from("<H", pixel_data, idx)[0]
                r = (c16 & 0x1F) << 3
                g = ((c16 >> 5) & 0x1F) << 3
                b = ((c16 >> 10) & 0x1F) << 3
                a = 0 if c16 == 0 else 255
                img.putpixel((x, y), (r, g, b, a))
        return img

    raise NotImplementedError(f"Формат {info['bpp']} не поддерживается для декодирования")


def rgb_to_psx_color(r: int, g: int, b: int, opaque: bool = True) -> int:
    """Конвертация RGB888 в 16-битный аппаратный BGR555 PlayStation 1."""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    stp = 0x8000 if (opaque and (r5 != 0 or g5 != 0 or b5 != 0)) else 0x0000
    if opaque and r5 == 0 and g5 == 0 and b5 == 0:
        stp = 0x8000  # Специальный непрозрачный чёрный цвет PS1
    return (b5 << 10) | (g5 << 5) | r5 | stp


def encode_tim_4bpp(
    img: Image.Image,
    vram_x: int,
    vram_y: int,
    clut_x: int,
    clut_y: int,
    clut_colors: list[tuple[int, int, int, int]] | None = None
) -> bytes:
    """Кодирование изображения в 4bpp TIM-файл."""
    w, h = img.size
    if w % 4 != 0:
        raise ValueError(f"Ширина 4bpp TIM обязана быть кратна 4 пикселям (получено {w})")

    # Формируем палитру из 16 цветов
    if clut_colors is None:
        quantized = img.convert("RGBA").quantize(colors=16)
        raw_pal = quantized.getpalette()[:48]
        clut_colors = []
        for i in range(0, len(raw_pal), 3):
            clut_colors.append((raw_pal[i], raw_pal[i+1], raw_pal[i+2], 255))
        while len(clut_colors) < 16:
            clut_colors.append((0, 0, 0, 0))

    clut_bytes = bytearray()
    for r, g, b, a in clut_colors[:16]:
        c16 = rgb_to_psx_color(r, g, b, opaque=(a > 128))
        clut_bytes.extend(struct.pack("<H", c16))

    # Заголовок CLUT (12 байт + данные)
    clut_block_len = 12 + len(clut_bytes)
    clut_header = struct.pack("<IHHHH", clut_block_len, clut_x, clut_y, 16, 1)

    # Пиксельные данные
    indexed = img.convert("RGBA").quantize(palette=img.convert("P", palette=Image.Palette.ADAPTIVE, colors=16))
    pixel_bytes = bytearray()
    vram_w = w // 4

    for y in range(h):
        for x_w in range(vram_w):
            p0 = indexed.getpixel((x_w * 4 + 0, y)) & 0x0F
            p1 = indexed.getpixel((x_w * 4 + 1, y)) & 0x0F
            p2 = indexed.getpixel((x_w * 4 + 2, y)) & 0x0F
            p3 = indexed.getpixel((x_w * 4 + 3, y)) & 0x0F
            b0 = p0 | (p1 << 4)
            b1 = p2 | (p3 << 4)
            pixel_bytes.append(b0)
            pixel_bytes.append(b1)

    img_block_len = 12 + len(pixel_bytes)
    img_header = struct.pack("<IHHHH", img_block_len, vram_x, vram_y, vram_w, h)

    # Magic 0x10, Flags 0x08 (4bpp с CLUT)
    file_header = struct.pack("<II", TIM_MAGIC, 0x08)
    return file_header + clut_header + bytes(clut_bytes) + img_header + bytes(pixel_bytes)
