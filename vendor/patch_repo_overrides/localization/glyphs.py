"""Locale-specific glyph allocation and runtime-font patching."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont

from .script import read_entries
from .unt_lz import compress, decompress


FONT_TIM_OFFSET = 0x003A2D68
FONT_TIM_SIZE = 0x20220
FONT_PIXEL_OFFSET = 0x220
FONT_PIXEL_SIZE = 0x20000
RAW_FONT_PIXEL_OFFSET = 0x007BA440
PACKED_FONT_ENTRY = 0x03A
RENDERER_MAX_GLYPH = 0x03E0
CONTROL_GLYPHS = {0x00FD, 0x00FE, 0x00FF}

LOWERCASE_GLYPHS = (
    0x0017, 0x0031, 0x003A, 0x0040, 0x0048, 0x004A, 0x004B,
    0x004D, 0x004F, 0x0055, 0x005F, 0x0060, 0x0062, 0x0063,
    0x0067, 0x0068, 0x0069, 0x006B, 0x006D, 0x006E, 0x006F,
    0x0070, 0x0071, 0x0074, 0x0075, 0x0076,
)

# Reuse the canonical English cells whenever a target string contains ASCII.
# This keeps all non-story English fallback text readable in an in-progress
# localization and reserves its complete ordinary-character inventory.
BASE_CHAR_TO_GLYPH = {
    **{chr(ord("a") + index): glyph for index, glyph in enumerate(LOWERCASE_GLYPHS)},
    "A": 0x00BE,
    "B": 0x014C,
    "C": 0x0128,
    "D": 0x00BF,
    "E": 0x00B6,
    "F": 0x014D,
    "J": 0x014F,
    "K": 0x0192,
    "O": 0x00BB,
    "P": 0x019B,
    "Q": 0x01A7,
    "U": 0x01D2,
    "V": 0x00BD,
    "X": 0x01FD,
    "Z": 0x0209,
    " ": 0x007D,
    "I": 0x0081,
    "L": 0x0082,
    "M": 0x0148,
    "N": 0x0086,
    "G": 0x0088,
    "T": 0x008D,
    "W": 0x008E,
    "S": 0x0090,
    "H": 0x0091,
    "R": 0x0099,
    "Y": 0x009A,
    ",": 0x00A1,
    ".": 0x00A2,
    "-": 0x00A4,
    "!": 0x00A6,
    "?": 0x00A7,
    ":": 0x00BC,
    "'": 0x031B,
    "♥": 0x00B4,
    "♪": 0x00B5,
    **{str(value): 0x00A8 + value for value in range(10)},
}


class GlyphError(ValueError):
    pass


def load_language(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema",
        "locale",
        "name",
        "output_stem",
        "data_preparer",
        "required_characters",
        "compact_glyph_limit",
    }
    if set(document) != required or document["schema"] != 1:
        raise GlyphError(f"language file must define exactly {sorted(required)}")
    for key in ("locale", "name", "output_stem", "data_preparer", "required_characters"):
        if not isinstance(document[key], str) or not document[key]:
            raise GlyphError(f"language field {key!r} must be a nonempty string")
    if not str(document["output_stem"]).isascii():
        raise GlyphError("output_stem must be ASCII")
    try:
        preparer = str(document["data_preparer"]).encode("ascii")
    except UnicodeEncodeError as exc:
        raise GlyphError("data_preparer must be ASCII ISO metadata") from exc
    if len(preparer) > 128:
        raise GlyphError("data_preparer exceeds the 128-byte ISO field")
    limit = document["compact_glyph_limit"]
    if not isinstance(limit, int) or not 0 <= limit <= 700:
        raise GlyphError("compact_glyph_limit must be an integer from 0 through 700")
    return document


def _font_tim(prog: bytes) -> bytes:
    tim = prog[FONT_TIM_OFFSET : FONT_TIM_OFFSET + FONT_TIM_SIZE]
    if len(tim) != FONT_TIM_SIZE or tim[:8] != b"\x10\0\0\0\x08\0\0\0":
        raise GlyphError("PROG.UNT does not contain the expected runtime font TIM")
    return tim


def _cell_bytes(tim: bytes, glyph_id: int) -> bytes:
    x, y = glyph_xy(glyph_id)
    row_bytes = 1024 // 2
    output = bytearray()
    for row in range(y, y + 16):
        start = FONT_PIXEL_OFFSET + row * row_bytes + x // 2
        output.extend(tim[start : start + 8])
    return bytes(output)


def glyph_xy(glyph_id: int) -> tuple[int, int]:
    if not 0 <= glyph_id <= 0x03FF:
        raise GlyphError(f"glyph ID 0x{glyph_id:04X} is outside the atlas")
    bank, local = divmod(glyph_id, 0x100)
    return bank * 256 + (local % 16) * 16, (local // 16) * 16


def occupied_english_cells(source_prog: bytes, english_prog: bytes) -> set[int]:
    source = _font_tim(source_prog)
    english = _font_tim(english_prog)
    changed = {
        glyph_id
        for glyph_id in range(RENDERER_MAX_GLYPH + 1)
        if _cell_bytes(source, glyph_id) != _cell_bytes(english, glyph_id)
    }
    return changed | set(BASE_CHAR_TO_GLYPH.values()) | CONTROL_GLYPHS | {0}


def _translation_lines(values: Iterable[str]) -> list[str]:
    return [
        line
        for value in values
        for page in value.split("\f")
        for line in page.split("\n")
        if line
    ]


def choose_compact_tokens(lines: Iterable[str], limit: int) -> list[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        counts.update(line[index : index + 2] for index in range(len(line) - 1))
    useful = [pair for pair, count in counts.items() if len(pair) == 2 and count >= 2]
    return sorted(useful, key=lambda pair: (-counts[pair], pair))[:limit]


def allocate_glyphs(
    source_prog: bytes,
    english_prog: bytes,
    translations: Iterable[str],
    language: Mapping[str, object],
    compact_translations: Iterable[str] | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, object]]:
    values = [value for value in translations if value]
    text = "".join(values) + str(language["required_characters"])
    characters = sorted(set(text) - {"\n", "\r", "\f"})
    occupied = occupied_english_cells(source_prog, english_prog)
    available = [
        glyph_id
        for glyph_id in range(1, RENDERER_MAX_GLYPH + 1)
        if glyph_id not in occupied
    ]
    charmap = dict(BASE_CHAR_TO_GLYPH)
    new_characters = [char for char in characters if char not in charmap]
    if len(new_characters) > len(available):
        raise GlyphError(
            f"locale needs {len(new_characters)} new characters but only {len(available)} cells are free"
        )
    for char, glyph_id in zip(new_characters, available):
        charmap[char] = glyph_id
    del available[: len(new_characters)]

    compact_values = (
        [value for value in compact_translations if value]
        if compact_translations is not None
        else values
    )
    tokens = choose_compact_tokens(
        _translation_lines(compact_values), int(language["compact_glyph_limit"])
    )
    if len(tokens) > len(available):
        raise GlyphError(
            f"locale needs {len(tokens)} compact cells but only {len(available)} remain"
        )
    compact = dict(zip(tokens, available))
    report = {
        "schema": 1,
        "locale": language["locale"],
        "renderer_max_glyph": f"0x{RENDERER_MAX_GLYPH:03X}",
        "english_reserved_cells": len(occupied),
        "new_character_cells": len(new_characters),
        "compact_cells": len(compact),
        "characters": [
            {"text": char, "glyph": f"0x{charmap[char]:03X}"}
            for char in characters
        ],
        "compact_tokens": [
            {"text": token, "glyph": f"0x{glyph_id:03X}"}
            for token, glyph_id in compact.items()
        ],
    }
    return charmap, compact, report

REPO_ROOT = Path(__file__).resolve().parent.parent


def _font_path() -> Path:
    candidates = (
        REPO_ROOT.parent / "fonts" / "PressStart2P.ttf",
        REPO_ROOT / "fonts" / "PressStart2P.ttf",
        Path("/home/samvel/dddd/fonts/PressStart2P.ttf"),
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSansCondensed-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"),
        Path("/usr/share/fonts/liberation/LiberationSans-Bold.ttf"),
    )
    for path in candidates:
        if path.is_file():
            return path
    raise GlyphError("no Cyrillic-capable DejaVu/Liberation Sans font was found")


def _render_mask(text: str) -> Image.Image:
    canvas = Image.new("L", (16, 16), 0)
    draw = ImageDraw.Draw(canvas)
    path = _font_path()
    font = ImageFont.truetype(str(path), 11)
    bbox = draw.textbbox((0, 12), text, font=font, anchor="ls")
    w = bbox[2] - bbox[0]
    if w <= 15:
        x = max(0, (16 - w) // 2)
        draw.text((x, 12), text, font=font, anchor="ls", fill=255)
        return canvas
    for size in range(10, 6, -1):
        candidate = ImageFont.truetype(str(path), size)
        candidate_box = draw.textbbox((0, 12), text, font=candidate, anchor="ls")
        width = candidate_box[2] - candidate_box[0]
        if width <= 15:
            x = max(0, (16 - width) // 2)
            draw.text((x, 12), text, font=candidate, anchor="ls", fill=255)
            return canvas
    raise GlyphError(f"cannot fit glyph {text!r} in a 16x16 cell")

def _set_pixel(tim: bytearray, x: int, y: int, value: int) -> None:
    offset = FONT_PIXEL_OFFSET + y * (1024 // 2) + x // 2
    if x & 1:
        tim[offset] = (tim[offset] & 0x0F) | ((value & 0x0F) << 4)
    else:
        tim[offset] = (tim[offset] & 0xF0) | (value & 0x0F)


def _draw_cell(tim: bytearray, glyph_id: int, text: str) -> None:
    x, y = glyph_xy(glyph_id)
    mask = _render_mask(text)
    pixels = mask.load()
    for py in range(16):
        for px in range(16):
            _set_pixel(tim, x + px, y + py, 3 if pixels[px, py] >= 80 else 0)


# 16x16 composite location tiles for World Map HUD (replaces English tiles from gourry-hacks)
STACKED_MAP_GLYPHS: dict[int, tuple[str, str]] = {
    0x02BC: ("ЛЕЙК", "ВУД"),       # LAKE/WOOD
    0x0296: ("БАРК", "ЛЕНД"),      # BARK/LAND
    0x028B: ("РЕГ", ""),           # AR
    0x029C: ("ИОН", ""),           # EA (together "РЕГИОН" instead of "AR EA")
    0x02A5: ("ФРИ", "ГРАНТ"),      # FREE/GROUND
    0x0289: ("ГРАМ", "СТОК"),      # GRAM/STOCK
    0x02B6: ("ТУР", "СИТИ"),       # TOUL/CITY
    0x02B7: ("САМ", "БУРГ"),       # SUN/BURG
    0x02C0: ("СЕЙ", "РУН"),        # SEY/RUUN
    0x02C1: ("КЬЮ", "ЗАК"),        # KUZ/ACK
    0x02C7: ("МАРК", "УЭЛЛС"),     # MARK/WELLS
    0x02D3: ("ЛЕЗА", "РИАМ"),      # LEZ/ARIAM
}


def _draw_stacked_cell(tim: bytearray, glyph_id: int, top_text: str, bot_text: str) -> None:
    gx, gy = glyph_xy(glyph_id)
    canvas = Image.new("L", (16, 16), 0)
    draw = ImageDraw.Draw(canvas)
    fpath = _font_path()
    font_5 = ImageFont.truetype(str(fpath), 5)
    font_6 = ImageFont.truetype(str(fpath), 6)

    if top_text and not bot_text:
        bb = draw.textbbox((0, 0), top_text, font=font_6)
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        x = max(0, (16 - w) // 2)
        y = max(0, (16 - h) // 2)
        draw.text((x, y), top_text, font=font_6, fill=255)
    else:
        if top_text:
            f = font_5 if len(top_text) > 3 else font_6
            bb = draw.textbbox((0, 0), top_text, font=f)
            w = bb[2] - bb[0]
            x = max(0, (16 - w) // 2)
            draw.text((x, 0), top_text, font=f, fill=255)
        if bot_text:
            f = font_5 if len(bot_text) > 3 else font_6
            bb = draw.textbbox((0, 0), bot_text, font=f)
            w = bb[2] - bb[0]
            x = max(0, (16 - w) // 2)
            draw.text((x, 8), bot_text, font=f, fill=255)

    pixels = canvas.load()
    for py in range(16):
        for px in range(16):
            _set_pixel(tim, gx + px, gy + py, 3 if pixels[px, py] >= 80 else 0)

# 2-letter ligature glyphs for fitting full names in fixed 16-byte world map slots
LIGATURE_MAP_GLYPHS: dict[int, tuple[str, str]] = {
    0x028A: ("Н", "Д"),  # НД in single 16x16 cell for БАРКЛЕ[НД]
    0x028C: ("Н", "Т"),  # НТ in single 16x16 cell for ФРИГРА[НТ]
    0x028D: ("О", "К"),  # ОК in single 16x16 cell for ГРАМСТ[ОК]
}


def _draw_ligature_cell(tim: bytearray, glyph_id: int, c1: str, c2: str) -> None:
    gx, gy = glyph_xy(glyph_id)
    canvas = Image.new("L", (16, 16), 0)
    draw = ImageDraw.Draw(canvas)
    fpath = _font_path()
    font_7 = ImageFont.truetype(str(fpath), 7)
    draw.text((0, 3), c1, font=font_7, fill=255)
    draw.text((8, 3), c2, font=font_7, fill=255)
    pixels = canvas.load()
    for py in range(16):
        for px in range(16):
            _set_pixel(tim, gx + px, gy + py, 3 if pixels[px, py] >= 80 else 0)

def _tim_image(tim: bytes) -> Image.Image:
    palette: list[tuple[int, int, int, int]] = []
    for index in range(16):
        raw = int.from_bytes(tim[20 + index * 2 : 22 + index * 2], "little")
        palette.append(
            (
                (raw & 0x1F) * 255 // 31,
                ((raw >> 5) & 0x1F) * 255 // 31,
                ((raw >> 10) & 0x1F) * 255 // 31,
                0 if raw == 0 else 255,
            )
        )
    image = Image.new("RGBA", (1024, 256))
    pixels = image.load()
    payload = tim[FONT_PIXEL_OFFSET:]
    for y in range(256):
        row = payload[y * 512 : (y + 1) * 512]
        for byte_index, value in enumerate(row):
            pixels[byte_index * 2, y] = palette[value & 0x0F]
            pixels[byte_index * 2 + 1, y] = palette[value >> 4]
    return image


def _glyph_contact(
    tim: bytes,
    entries: list[tuple[str, int]],
    output: Path,
) -> None:
    if not entries:
        return
    atlas = _tim_image(tim)
    columns = 8
    tile_width = 80
    tile_height = 88
    rows = (len(entries) + columns - 1) // columns
    contact = Image.new("RGB", (columns * tile_width, rows * tile_height), (32, 32, 32))
    draw = ImageDraw.Draw(contact)
    label_font = ImageFont.truetype(str(_font_path()), 13)
    for index, (text, glyph_id) in enumerate(entries):
        column, row = index % columns, index // columns
        left = column * tile_width
        top = row * tile_height
        x, y = glyph_xy(glyph_id)
        cell = atlas.crop((x, y, x + 16, y + 16)).resize(
            (64, 64), Image.Resampling.NEAREST
        )
        contact.paste(cell.convert("RGB"), (left + 8, top + 2))
        label = f"{text}  {glyph_id:03X}"
        box = draw.textbbox((0, 0), label, font=label_font)
        draw.text(
            (left + (tile_width - (box[2] - box[0])) // 2, top + 68),
            label,
            font=label_font,
            fill=(240, 240, 240),
        )
    contact.save(output)


def patch_runtime_font(
    prog: bytes,
    charmap: Mapping[str, int],
    compact: Mapping[str, int],
    build_dir: Path,
) -> tuple[bytes, dict[str, object]]:
    original_tim = _font_tim(prog)
    localized_tim = bytearray(original_tim)
    new_character_map = {
        char: glyph
        for char, glyph in charmap.items()
        if char not in BASE_CHAR_TO_GLYPH
    }
    for text, glyph_id in new_character_map.items():
        _draw_cell(localized_tim, glyph_id, text)

    atlas_path: Path | None = None
    candidate_roots = (REPO_ROOT, REPO_ROOT.parent, Path.cwd())
    for base in candidate_roots:
        cur = base.resolve()
        while True:
            target = cur / "compact_font_atlas_raw.png"
            if target.is_file():
                atlas_path = target
                break
            if cur.parent == cur:
                break
            cur = cur.parent
        if atlas_path is not None:
            break

    if atlas_path is not None and atlas_path.is_file():
        with Image.open(atlas_path) as atlas_im:
            atlas_rgba = atlas_im.convert("RGBA")
            atlas_px = atlas_rgba.load()
            for idx, (text, glyph_id) in enumerate(compact.items()):
                col = (idx % 16) * 16
                row = (idx // 16) * 16
                if row + 16 > atlas_rgba.height or col + 16 > atlas_rgba.width:
                    _draw_cell(localized_tim, glyph_id, text)
                    continue
                x, y = glyph_xy(glyph_id)
                for py in range(16):
                    for px in range(16):
                        r, g, b, a = atlas_px[col + px, row + py]
                        is_lit = a > 30 and (r > 40 or g > 40 or b > 40)
                        _set_pixel(localized_tim, x + px, y + py, 3 if is_lit else 0)
    else:
        for text, glyph_id in compact.items():
            _draw_cell(localized_tim, glyph_id, text)
    for glyph_id, (top, bot) in STACKED_MAP_GLYPHS.items():
        _draw_stacked_cell(localized_tim, glyph_id, top, bot)
    for glyph_id, (c1, c2) in LIGATURE_MAP_GLYPHS.items():
        _draw_ligature_cell(localized_tim, glyph_id, c1, c2)

    changed = [
        index
        for index, (before, after) in enumerate(zip(original_tim, localized_tim))
        if before != after
    ]
    result = bytearray(prog)
    result[FONT_TIM_OFFSET : FONT_TIM_OFFSET + FONT_TIM_SIZE] = localized_tim
    raw_end = RAW_FONT_PIXEL_OFFSET + FONT_PIXEL_SIZE
    if raw_end > len(result):
        raise GlyphError("raw runtime-font copy is truncated")
    for index in changed:
        if index >= FONT_PIXEL_OFFSET:
            result[RAW_FONT_PIXEL_OFFSET + index - FONT_PIXEL_OFFSET] = localized_tim[index]

    entries = read_entries(prog)
    packed_entry = entries[PACKED_FONT_ENTRY]
    packed_source = packed_entry.extract(prog)
    decoded, _consumed = decompress(packed_source)
    if decoded != original_tim:
        raise GlyphError("packed and direct English runtime fonts differ")
    packed = compress(bytes(localized_tim))
    if len(packed) > packed_entry.size:
        raise GlyphError(
            f"localized packed font is 0x{len(packed):X}; capacity is 0x{packed_entry.size:X}"
        )
    result[packed_entry.offset : packed_entry.offset + packed_entry.size] = packed.ljust(
        packed_entry.size, b"\0"
    )

    build_dir.mkdir(parents=True, exist_ok=True)
    _tim_image(bytes(localized_tim)).save(build_dir / "runtime_font.png")
    _glyph_contact(
        bytes(localized_tim),
        [*new_character_map.items(), *compact.items()],
        build_dir / "locale_glyphs.png",
    )
    report = {
        "new_character_cells": len(new_character_map),
        "compact_cells": len(compact),
        "changed_font_bytes": len(changed),
        "packed_size": len(packed),
        "packed_capacity": packed_entry.size,
    }
    return bytes(result), report
