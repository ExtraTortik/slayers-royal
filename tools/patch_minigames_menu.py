#!/usr/bin/env python3
"""Slayers Royal (PS1) - Minigames Selection Menu Patcher.

This tool:
1. Loads human-editable catalog `translations/minigames_menu_ru.json` covering all
   17 wooden plank text elements in OPT.UNT:
   - Header plank (Entry 152, LBA 228506): "МИНИ-ИГРЫ"
   - Prompt plank 1 (Entry 153, LBA 228507): "ВЫБОР: D-PAD"
   - Prompt plank 2 (Entry 154, LBA 228508): "O: ВЫБОР   X: НАЗАД"
   - 7 Minigame planks (Entries 155..168, LBA 228509..228522, 2 lines per plank):
     - Minigame 1: Entry 159 ("ЛИНА И ГАУРИ"), Entry 160 ("ОБЕД")
     - Minigame 2: Entry 161 ("АМЕЛИЯ"), Entry 162 ("ПРЫЖОК")
     - Minigame 3: Entry 163 ("НАГА"), Entry 164 ("СМЕХ")
     - Minigame 4: Entry 165 ("СЛЕЙЕРС"), Entry 166 ("КВИЗ")
     - Minigame 5: Entry 167 ("ОТСТРЕЛ"), Entry 168 ("БАНДИТОВ")
     - Minigame 6: Entry 155 ("РЫЦАРЬ"), Entry 156 ("И МОНСТР")
     - Minigame 7: Entry 157 ("СЛОТ"), Entry 158 ("МАШИНА")
2. Reads original TIM metadata from OPT.UNT (CLUT palette, VRAM coordinates, dimensions).
3. Renders Cyrillic text masks using `fonts/PressStart2P.ttf` centered within each sprite.
4. Constructs valid 4bpp PS1 TIM files (magic 0x10, flag 0x08, CLUT, pixel data).
5. Pads each TIM to 2048 bytes (1 sector).
6. Injects into disc image `localization-output/ru/slayers_royal_ru.bin` (and patch_repo if present)
   with 100% valid Mode 2 Form 1 EDC/ECC checksum recalculation.
7. Generates composite preview `data/preview_minigames_menu_ru.png` showing all wooden planks.
8. Provides CLI with `--bin`, `--catalog`, `--verify`, `--preview`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Any, Mapping, Sequence

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

# Defaults and constants
OPT_ARCHIVE_LBA = 226000
DEFAULT_CATALOG = REPO_ROOT / "translations" / "minigames_menu_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_PATCH_REPO_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SRC_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_FONT_PATH = REPO_ROOT / "fonts" / "PressStart2P.ttf"
DEFAULT_PREVIEW_PATH = REPO_ROOT / "data" / "preview_minigames_menu_ru.png"

REQUIRED_MENU_KEYS = (
    "header",
    "nav_prompt",
    "action_prompt",
    "knight_monster_line1",
    "knight_monster_line2",
    "slot_machine_line1",
    "slot_machine_line2",
    "eating_contest_line1",
    "eating_contest_line2",
    "amelia_climb_line1",
    "amelia_climb_line2",
    "naga_laugh_line1",
    "naga_laugh_line2",
    "slayers_quiz_line1",
    "slayers_quiz_line2",
    "bandit_bullying_line1",
    "bandit_bullying_line2",
)


def find_font(custom_path: Path | str | None = None) -> Path:
    """Locate PressStart2P.ttf font file."""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p
        raise FileNotFoundError(f"Custom font not found: {custom_path}")

    candidates = (
        DEFAULT_FONT_PATH,
        PATCH_REPO / "fonts" / "PressStart2P.ttf",
        Path("fonts/PressStart2P.ttf"),
    )
    for c in candidates:
        if c.is_file():
            return c.resolve()
    raise FileNotFoundError("PressStart2P.ttf font not found in repository.")


def load_minigames_menu_catalog(path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate translations/minigames_menu_ru.json catalog."""
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Minigames menu catalog not found: {catalog_path}")

    with open(catalog_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if not isinstance(doc, dict):
        raise ValueError(f"Catalog at {catalog_path} must be a JSON object")

    if "menu_items" not in doc:
        raise ValueError(f"Catalog at {catalog_path} missing 'menu_items' object")

    items = doc["menu_items"]
    if not isinstance(items, dict):
        raise ValueError(f"'menu_items' in {catalog_path} must be a dictionary")

    for key in REQUIRED_MENU_KEYS:
        if key not in items:
            raise ValueError(f"Missing required menu item '{key}' in catalog")
        item = items[key]
        if not isinstance(item, dict):
            raise ValueError(f"Menu item '{key}' must be a dictionary")
        for field in ("entry", "sector_offset", "vram_x", "vram_y", "width", "height", "text_ru", "font_size", "color_index"):
            if field not in item:
                raise ValueError(f"Menu item '{key}' missing required field '{field}'")
        if item["width"] <= 0 or item["width"] % 4 != 0:
            raise ValueError(f"Menu item '{key}' width ({item['width']}) must be a positive multiple of 4")
        if item["height"] <= 0:
            raise ValueError(f"Menu item '{key}' height ({item['height']}) must be positive")
        if not (0 <= item["color_index"] < 16):
            raise ValueError(f"Menu item '{key}' color_index ({item['color_index']}) must be in 0..15")

    return doc


def render_text_mask_with_tracking(
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont | Path | str,
    tracking: int = 0,
    width: int | None = None,
    height: int | None = None,
) -> Image.Image:
    """Render single-line text glyphs with configurable character tracking (letter spacing).

    Parameters
    ----------
    text : str
        The string to render.
    font : ImageFont.ImageFont | ImageFont.FreeTypeFont | Path | str
        The font object or path.
    tracking : int
        Extra horizontal spacing in pixels between consecutive characters.
    width : int | None
        Target image width. If None, tight width matching total advance.
    height : int | None
        Target image height. If None, font size / line height.

    Returns
    -------
    Image.Image
        1-bit monochrome mask (mode '1') with active pixels set to 1.
    """
    if isinstance(font, (str, Path)):
        font = ImageFont.truetype(str(font), 10)

    char_adv = [int(font.getlength(c)) for c in text]
    total_advance = sum(char_adv) + max(0, len(text) - 1) * tracking

    canvas_w = width if width is not None else max(1, total_advance)
    font_size = getattr(font, "size", 10)
    canvas_h = height if height is not None else max(1, font_size)

    start_x = (canvas_w - total_advance) // 2 if width is not None else 0
    start_y = (canvas_h - font_size) // 2 if height is not None else 0

    mask = Image.new("1", (canvas_w, canvas_h), 0)
    draw = ImageDraw.Draw(mask)

    cx = start_x
    for i, ch in enumerate(text):
        draw.text((cx, start_y), ch, font=font, fill=1)
        cx += char_adv[i] + tracking

    return mask


def render_text_mask(
    text: str,
    font_path: Path | str,
    font_size: int,
    width: int,
    height: int,
    tracking: int = 0,
) -> Image.Image:
    """Render single-line text into a 1-bit monochrome mask centered in (width, height)."""
    font = ImageFont.truetype(str(font_path), font_size)
    return render_text_mask_with_tracking(
        text, font, tracking=tracking, width=width, height=height
    )


def build_4bpp_pixel_data(
    mask: Image.Image,
    color_index: int = 15,
    bevel_index: int | None = None,
) -> bytes:
    """Convert a 1-bit monochrome mask or indexed image into PS1 4bpp pixel data.

    In 4bpp TIM format:
    - 2 pixels per byte
    - Low nibble = pixel 0 (left)
    - High nibble = pixel 1 (right)
    - Active pixels receive `color_index` (core text).
    - If `bevel_index` is provided, pixels at (x+1, y+1) receive `bevel_index` where core is not drawn.
    """
    w, h = mask.size
    row_bytes = w // 2
    out = bytearray(row_bytes * h)

    for y in range(h):
        row_offset = y * row_bytes
        for x in range(0, w, 2):
            if bevel_index is not None:
                if mask.getpixel((x, y)):
                    p0 = color_index
                elif x > 0 and y > 0 and mask.getpixel((x - 1, y - 1)):
                    p0 = bevel_index
                else:
                    p0 = 0

                if mask.getpixel((x + 1, y)):
                    p1 = color_index
                elif (x + 1) > 0 and y > 0 and mask.getpixel((x, y - 1)):
                    p1 = bevel_index
                else:
                    p1 = 0
            elif mask.mode == "1":
                p0 = color_index if mask.getpixel((x, y)) else 0
                p1 = color_index if mask.getpixel((x + 1, y)) else 0
            else:
                p0 = int(mask.getpixel((x, y))) & 0x0F
                p1 = int(mask.getpixel((x + 1, y))) & 0x0F

            out[row_offset + (x // 2)] = (p0 & 0x0F) | ((p1 & 0x0F) << 4)

    return bytes(out)

def parse_tim(tim_bytes: bytes) -> dict[str, Any]:
    """Parse PS1 TIM header, CLUT, and image dimensions."""
    if len(tim_bytes) < 8 or tim_bytes[:4] != b"\x10\x00\x00\x00":
        raise ValueError("Invalid TIM magic (expected 0x00000010)")

    flag = struct.unpack_from("<I", tim_bytes, 4)[0]
    pmode = flag & 7
    has_clut = bool(flag & 8)

    pos = 8
    clut_info: dict[str, Any] | None = None
    if has_clut:
        clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", tim_bytes, pos)
        clut_data = tim_bytes[pos + 12 : pos + clut_len]
        clut_info = {
            "len": clut_len,
            "x": clut_x,
            "y": clut_y,
            "w": clut_w,
            "h": clut_h,
            "data": clut_data,
            "num_colors": (clut_len - 12) // 2,
        }
        pos += clut_len

    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", tim_bytes, pos)
    pixel_data = tim_bytes[pos + 12 : pos + img_len]

    pixel_width = img_w * (4 if pmode == 0 else 2 if pmode == 1 else 1)

    return {
        "pmode": pmode,
        "flag": flag,
        "has_clut": has_clut,
        "clut": clut_info,
        "img_x": img_x,
        "img_y": img_y,
        "img_w": img_w,
        "img_h": img_h,
        "pixel_width": pixel_width,
        "pixel_height": img_h,
        "img_len": img_len,
        "pixel_data": pixel_data,
        "total_tim_len": pos + img_len,
    }


def build_tim(
    clut_x: int,
    clut_y: int,
    clut_data: bytes,
    img_x: int,
    img_y: int,
    width: int,
    height: int,
    pixel_data: bytes,
) -> bytes:
    """Assemble a standard PS1 4bpp TIM file and pad to 2048 bytes."""
    if len(clut_data) >= 32:
        clut_bytes = bytearray(clut_data)
        clut_bytes[30:32] = struct.pack("<H", 0x8000)
        clut_data = bytes(clut_bytes)

    header = b"\x10\x00\x00\x00\x08\x00\x00\x00"
    clut_len = 12 + len(clut_data)
    clut_block = struct.pack("<IHHHH", clut_len, clut_x, clut_y, 16, 1) + clut_data

    img_w_words = width // 4
    img_len = 12 + len(pixel_data)
    img_block = struct.pack("<IHHHH", img_len, img_x, img_y, img_w_words, height) + pixel_data

    tim_buffer = header + clut_block + img_block
    if len(tim_buffer) > USER_DATA_SIZE:
        raise ValueError(
            f"TIM buffer size ({len(tim_buffer)} bytes) exceeds sector user data limit ({USER_DATA_SIZE} bytes)"
        )

    return tim_buffer.ljust(USER_DATA_SIZE, b"\x00")


def read_sector_extent(bin_path: Path, lba: int, count: int = 1) -> bytes:
    """Read `count` complete 2048-byte user data sectors starting at `lba`."""
    with open(bin_path, "rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        buf = bytearray()
        for i in range(count):
            f.seek((lba + i) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            chunk = f.read(USER_DATA_SIZE)
            if len(chunk) != USER_DATA_SIZE:
                raise IOError(f"Unexpected EOF reading LBA {lba + i} from {bin_path}")
            buf.extend(chunk)
        return bytes(buf)


def read_raw_sector(bin_path: Path, lba: int) -> bytes:
    """Read a complete 2352-byte raw disc sector."""
    with open(bin_path, "rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE)
        raw = f.read(RAW_SECTOR_SIZE)
        if len(raw) != RAW_SECTOR_SIZE:
            raise IOError(f"Unexpected EOF reading raw sector at LBA {lba} from {bin_path}")
        return raw


def get_pristine_sector_data(sector_offset: int, candidate_bins: Sequence[Path]) -> bytes:
    """Locate a valid original TIM sector from available disc images."""
    lba = OPT_ARCHIVE_LBA + sector_offset
    for cand in candidate_bins:
        if cand.is_file():
            try:
                data = read_sector_extent(cand, lba, 1)
                if data[:4] == b"\x10\x00\x00\x00":
                    return data
            except Exception:
                continue
    raise FileNotFoundError(f"Could not read valid TIM sector at LBA {lba} from any candidate disc image")

def generate_tim_entry(
    item_or_text: dict[str, Any] | str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont | Path | str | None = None,
    clut_info: dict[str, Any] | None = None,
    img_x: int | None = None,
    img_y: int | None = None,
    pristine_tim: bytes | None = None,
    candidate_bins: Sequence[Path] | None = None,
    width: int | None = None,
    height: int | None = None,
    font_size: int | None = None,
    tracking: int | None = None,
    color_index: int = 15,
    bevel_index: int = 1,
) -> bytes:
    """Generate a complete 2048-byte PS1 4bpp TIM sector for a minigame menu entry.

    Renders:
    - Text core at (x, y) with palette index 15.
    - 1px bevel/highlight at (x + 1, y + 1) with palette index 1 (where core is not drawn).
    - Color 15 in CLUT set to 0x8000 (PS1 opaque black).
    """
    if isinstance(item_or_text, dict):
        text = item_or_text["text_ru"]
        w = width if width is not None else item_or_text["width"]
        h = height if height is not None else item_or_text["height"]
        fs = font_size if font_size is not None else item_or_text.get("font_size", 10)
        trk = item_or_text.get("tracking", 0) if tracking is None else tracking
        sec_off = item_or_text.get("sector_offset")
        ci = item_or_text.get("color_index", color_index)
        if img_x is None:
            img_x = item_or_text.get("vram_x", 0)
        if img_y is None:
            img_y = item_or_text.get("vram_y", 0)
    else:
        text = str(item_or_text)
        w = width if width is not None else 120
        h = height if height is not None else 24
        fs = font_size if font_size is not None else 10
        trk = 0 if tracking is None else tracking
        sec_off = None
        ci = color_index

    # Resolve font
    if font is None:
        font_path = find_font()
        font_obj = ImageFont.truetype(str(font_path), fs)
    elif isinstance(font, (str, Path)):
        font_obj = ImageFont.truetype(str(font), fs)
    else:
        font_obj = font

    # Resolve CLUT and VRAM coordinates
    resolved_clut_x = 0
    resolved_clut_y = 0
    resolved_clut_data: bytes | None = None

    if clut_info is not None:
        resolved_clut_x = clut_info["x"]
        resolved_clut_y = clut_info["y"]
        resolved_clut_data = clut_info["data"]
    elif pristine_tim is not None:
        parsed = parse_tim(pristine_tim)
        if parsed.get("clut"):
            resolved_clut_x = parsed["clut"]["x"]
            resolved_clut_y = parsed["clut"]["y"]
            resolved_clut_data = parsed["clut"]["data"]
        if img_x is None or img_x == 0:
            img_x = parsed["img_x"]
        if img_y is None or img_y == 0:
            img_y = parsed["img_y"]
    elif sec_off is not None:
        cands = list(candidate_bins) if candidate_bins else [
            DEFAULT_TARGET_BIN,
            DEFAULT_SRC_BIN,
            DEFAULT_EN_BIN,
            DEFAULT_PATCH_REPO_BIN,
        ]
        pristine_tim = get_pristine_sector_data(sec_off, cands)
        parsed = parse_tim(pristine_tim)
        if parsed.get("clut"):
            resolved_clut_x = parsed["clut"]["x"]
            resolved_clut_y = parsed["clut"]["y"]
            resolved_clut_data = parsed["clut"]["data"]
        if img_x is None or img_x == 0:
            img_x = parsed["img_x"]
        if img_y is None or img_y == 0:
            img_y = parsed["img_y"]

    if resolved_clut_data is None:
        dummy_clut = bytearray(32)
        struct.pack_into("<H", dummy_clut, 2, 0x0CEA)
        struct.pack_into("<H", dummy_clut, 30, 0x8000)
        resolved_clut_data = bytes(dummy_clut)
        resolved_clut_x = 0
        resolved_clut_y = 500

    if img_x is None:
        img_x = 512
    if img_y is None:
        img_y = 288

    mask = render_text_mask_with_tracking(text, font_obj, tracking=trk, width=w, height=h)
    pixel_data = build_4bpp_pixel_data(mask, color_index=ci, bevel_index=bevel_index)

    return build_tim(
        clut_x=resolved_clut_x,
        clut_y=resolved_clut_y,
        clut_data=resolved_clut_data,
        img_x=img_x,
        img_y=img_y,
        width=w,
        height=h,
        pixel_data=pixel_data,
    )


def patch_menu_sector(bin_path: Path, lba: int, payload: bytes) -> None:
    """Inject 2048-byte payload into disc image at LBA and recalculate EDC/ECC."""
    if len(payload) != USER_DATA_SIZE:
        raise ValueError(f"Payload size must be exactly {USER_DATA_SIZE} bytes (got {len(payload)})")

    if replace_extent_in_place is not None:
        replace_extent_in_place(bin_path, lba, payload)
    else:
        # Fallback implementation
        chk = CdChecksums()
        with open(bin_path, "r+b") as f:
            f.seek(lba * RAW_SECTOR_SIZE)
            sector = bytearray(f.read(RAW_SECTOR_SIZE))
            if len(sector) != RAW_SECTOR_SIZE:
                raise IOError(f"Cannot read sector at LBA {lba}")
            sector[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE] = payload
            chk.repair_mode2_form1(sector)
            f.seek(lba * RAW_SECTOR_SIZE)
            f.write(sector)


def tim_to_rgba_image(tim_bytes: bytes, transparent_zero: bool = True) -> Image.Image:
    """Convert a 4bpp PS1 TIM buffer into an RGBA PIL Image."""
    info = parse_tim(tim_bytes)
    clut_info = info["clut"]
    if not clut_info:
        raise ValueError("TIM has no CLUT palette")

    clut_data = clut_info["data"]
    colors: list[tuple[int, int, int, int]] = []
    for i in range(0, len(clut_data), 2):
        c = struct.unpack_from("<H", clut_data, i)[0]
        r = (c & 0x1F) << 3
        g = ((c >> 5) & 0x1F) << 3
        b = ((c >> 10) & 0x1F) << 3
        a = 0 if (i == 0 and transparent_zero) else 255
        colors.append((r, g, b, a))

    w = info["pixel_width"]
    h = info["pixel_height"]
    pixels = []
    for b in info["pixel_data"]:
        p0 = b & 0x0F
        p1 = (b >> 4) & 0x0F
        pixels.append(colors[p0] if p0 < len(colors) else (0, 0, 0, 0))
        pixels.append(colors[p1] if p1 < len(colors) else (0, 0, 0, 0))

    im = Image.new("RGBA", (w, h))
    im.putdata(pixels)
    return im


def generate_preview(
    catalog: dict[str, Any],
    bin_path: Path | None = None,
    font_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Generate composite preview data/preview_minigames_menu_ru.png showing all wooden planks."""
    out_file = Path(output_path) if output_path else DEFAULT_PREVIEW_PATH
    out_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_font = find_font(font_path)

    items = catalog["menu_items"]

    # Candidate disc paths to retrieve authentic wooden plank textures
    cands: list[Path] = []
    if bin_path and Path(bin_path).is_file():
        cands.append(Path(bin_path))
    for p in (DEFAULT_TARGET_BIN, DEFAULT_SRC_BIN, DEFAULT_EN_BIN, DEFAULT_PATCH_REPO_BIN):
        if p.is_file() and p not in cands:
            cands.append(p)

    # Load wooden textures:
    # Header plank: Entry 150 (offset 2503, 136x24)
    # Prompts plank: Entry 151 (offset 2504, 2 sectors, 264x24)
    # Minigame plank: Entry 169 (offset 2523, 3 sectors, 224x48)
    im_bg_header: Image.Image | None = None
    im_bg_prompt: Image.Image | None = None
    im_bg_plank: Image.Image | None = None

    for cand in cands:
        try:
            d_hdr = read_sector_extent(cand, OPT_ARCHIVE_LBA + 2503, 1)
            im_bg_header = tim_to_rgba_image(d_hdr, transparent_zero=False)
            d_prm = read_sector_extent(cand, OPT_ARCHIVE_LBA + 2504, 2)
            im_bg_prompt = tim_to_rgba_image(d_prm, transparent_zero=False)
            d_plk = read_sector_extent(cand, OPT_ARCHIVE_LBA + 2523, 3)
            im_bg_plank = tim_to_rgba_image(d_plk, transparent_zero=False)
            break
        except Exception:
            continue

    # Fallbacks if disc images are not available
    if im_bg_header is None:
        im_bg_header = Image.new("RGBA", (136, 24), (72, 48, 24, 255))
    if im_bg_prompt is None:
        im_bg_prompt = Image.new("RGBA", (264, 24), (56, 40, 16, 255))
    if im_bg_plank is None:
        im_bg_plank = Image.new("RGBA", (224, 48), (64, 40, 24, 255))

    # Helper to render an item's RGBA sprite using engraved black text with light highlight
    def render_item_sprite(item_spec: dict[str, Any]) -> Image.Image:
        tim_bytes = generate_tim_entry(
            item_spec,
            font=resolved_font,
            candidate_bins=cands,
        )
        return tim_to_rgba_image(tim_bytes, transparent_zero=True)

    # 1. Header plank
    sp_header = render_item_sprite(items["header"])
    plank_header = im_bg_header.copy()
    plank_header.alpha_composite(sp_header, ((im_bg_header.width - sp_header.width) // 2, (im_bg_header.height - sp_header.height) // 2))

    # 2. Prompt plank 1
    sp_prompt1 = render_item_sprite(items["nav_prompt"])
    plank_prompt1 = im_bg_prompt.copy()
    plank_prompt1.alpha_composite(sp_prompt1, ((im_bg_prompt.width - sp_prompt1.width) // 2, (im_bg_prompt.height - sp_prompt1.height) // 2))

    # 3. Prompt plank 2
    sp_prompt2 = render_item_sprite(items["action_prompt"])
    plank_prompt2 = im_bg_prompt.copy()
    plank_prompt2.alpha_composite(sp_prompt2, ((im_bg_prompt.width - sp_prompt2.width) // 2, (im_bg_prompt.height - sp_prompt2.height) // 2))

    # 4. 7 Minigame planks (2 lines per plank: line 1 on left, line 2 on right)
    minigame_pairs = (
        ("eating_contest_line1", "eating_contest_line2"),
        ("amelia_climb_line1", "amelia_climb_line2"),
        ("naga_laugh_line1", "naga_laugh_line2"),
        ("slayers_quiz_line1", "slayers_quiz_line2"),
        ("bandit_bullying_line1", "bandit_bullying_line2"),
        ("knight_monster_line1", "knight_monster_line2"),
        ("slot_machine_line1", "slot_machine_line2"),
    )
    mg_planks: list[Image.Image] = []
    for k1, k2 in minigame_pairs:
        sp1 = render_item_sprite(items[k1])
        sp2 = render_item_sprite(items[k2])
        pl = im_bg_plank.copy()
        # Y-offset is centered vertically in plank (48 - 32) // 2 = 8
        pl.alpha_composite(sp1, (0, (im_bg_plank.height - sp1.height) // 2))
        pl.alpha_composite(sp2, (112, (im_bg_plank.height - sp2.height) // 2))
        mg_planks.append(pl)

    # Canvas dimensions: standard PS1 width 320, vertical height 540
    canvas = Image.new("RGBA", (320, 540), (20, 16, 12, 255))

    # Place Header
    y = 12
    canvas.alpha_composite(plank_header, ((320 - plank_header.width) // 2, y))
    y += plank_header.height + 14

    # Place 7 Minigame planks
    for pl in mg_planks:
        canvas.alpha_composite(pl, ((320 - pl.width) // 2, y))
        y += pl.height + 6

    y += 8
    # Place Prompt 1
    canvas.alpha_composite(plank_prompt1, ((320 - plank_prompt1.width) // 2, y))
    y += plank_prompt1.height + 6

    # Place Prompt 2
    canvas.alpha_composite(plank_prompt2, ((320 - plank_prompt2.width) // 2, y))

    canvas.save(out_file)
    return out_file

def patch_minigames_menu(
    bin_path: Path | str | None = None,
    catalog_path: Path | str | None = None,
    font_path: Path | str | None = None,
    preview: bool = True,
    preview_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Patch all 17 minigame menu elements into disc image(s)."""
    target_bin = Path(bin_path) if bin_path else DEFAULT_TARGET_BIN
    if not dry_run and not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    catalog = load_minigames_menu_catalog(catalog_path)
    resolved_font = find_font(font_path)

    # Prioritized list of candidates to extract pristine CLUT & VRAM coordinates
    cands: list[Path] = []
    if target_bin.is_file():
        cands.append(target_bin)
    for p in (DEFAULT_SRC_BIN, DEFAULT_EN_BIN, DEFAULT_PATCH_REPO_BIN):
        if p.is_file() and p not in cands:
            cands.append(p)

    targets: list[Path] = [target_bin]
    if not dry_run:
        for sec in (DEFAULT_PATCH_REPO_BIN, DEFAULT_TARGET_BIN):
            if sec.is_file() and sec.resolve() != target_bin.resolve() and sec not in targets:
                targets.append(sec)

    items = catalog["menu_items"]
    patched_entries = 0
    patched_sectors: list[dict[str, Any]] = []

    for key in REQUIRED_MENU_KEYS:
        item = items[key]
        sec_off = item["sector_offset"]
        lba = OPT_ARCHIVE_LBA + sec_off
        w = item["width"]
        h = item["height"]
        text_ru = item["text_ru"]
        font_size = item["font_size"]
        color_index = item["color_index"]

        # Generate TIM sector with tracking, solid black core, and 1px highlight bevel
        tim_sector = generate_tim_entry(
            item,
            font=resolved_font,
            candidate_bins=cands,
        )

        if not dry_run:
            for tgt in targets:
                patch_menu_sector(tgt, lba, tim_sector)

        patched_entries += 1
        patched_sectors.append({
            "key": key,
            "entry": item["entry"],
            "lba": lba,
            "sector_offset": sec_off,
            "text_ru": text_ru,
            "size": f"{w}x{h}",
        })

    saved_preview: Path | None = None
    if preview and not dry_run:
        saved_preview = generate_preview(
            catalog,
            bin_path=target_bin,
            font_path=resolved_font,
            output_path=Path(preview_path) if preview_path else DEFAULT_PREVIEW_PATH,
        )

    return {
        "status": "success",
        "dry_run": dry_run,
        "patched_entries": patched_entries,
        "patched_sectors": patched_sectors,
        "targets": [str(t) for t in targets] if not dry_run else [],
        "preview_path": str(saved_preview) if saved_preview else None,
    }


def verify_minigames_menu(
    bin_path: Path | str | None = None,
    catalog_path: Path | str | None = None,
    font_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify binary integrity, Mode 2 Form 1 EDC/ECC, and rendered text on disc image."""
    target_bin = Path(bin_path) if bin_path else DEFAULT_TARGET_BIN
    if not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    catalog = load_minigames_menu_catalog(catalog_path)
    resolved_font = find_font(font_path)
    chk = CdChecksums() if CdChecksums is not None else None

    items = catalog["menu_items"]
    verified_sectors = 0
    verified_items = 0

    for key in REQUIRED_MENU_KEYS:
        item = items[key]
        sec_off = item["sector_offset"]
        lba = OPT_ARCHIVE_LBA + sec_off
        w = item["width"]
        h = item["height"]
        text_ru = item["text_ru"]
        font_size = item["font_size"]
        color_index = item["color_index"]

        # Read 2352-byte raw sector
        raw_sec = read_raw_sector(target_bin, lba)

        # 1. Verify Mode 2 Form 1 EDC/ECC checksums
        if chk is not None:
            edc_expected = raw_sec[0x818:0x81C]
            edc_computed = chk.compute_edc(raw_sec[0x10:0x818])
            if edc_expected != edc_computed:
                raise ValueError(
                    f"EDC mismatch at LBA {lba} ({key}): expected {edc_expected.hex()}, computed {edc_computed.hex()}"
                )

            ecc_p_expected = raw_sec[0x81C:0x8C8]
            ecc_p_computed = chk.compute_ecc(raw_sec[0x10:], 86, 24, 2, 86)
            if ecc_p_expected != ecc_p_computed:
                raise ValueError(f"ECC P-parity mismatch at LBA {lba} ({key})")

            ecc_q_expected = raw_sec[0x8C8:0x930]
            ecc_q_computed = chk.compute_ecc(raw_sec[0x10:], 52, 43, 86, 88)
            if ecc_q_expected != ecc_q_computed:
                raise ValueError(f"ECC Q-parity mismatch at LBA {lba} ({key})")

        verified_sectors += 1

        # 2. Verify TIM structure in user data
        user_data = raw_sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE]
        parsed = parse_tim(user_data)

        if parsed["pmode"] != 0:
            raise ValueError(f"TIM at LBA {lba} is not 4bpp (pmode={parsed['pmode']})")
        if not parsed["has_clut"] or not parsed["clut"]:
            raise ValueError(f"TIM at LBA {lba} missing CLUT")
        if parsed["pixel_width"] != w or parsed["pixel_height"] != h:
            raise ValueError(
                f"TIM at LBA {lba} dimension mismatch: expected {w}x{h}, found {parsed['pixel_width']}x{parsed['pixel_height']}"
            )
        clut_raw = parsed["clut"]["data"]
        if len(clut_raw) >= 32:
            c15 = struct.unpack_from("<H", clut_raw, 30)[0]
            if c15 != 0x8000:
                raise ValueError(
                    f"TIM at LBA {lba} ({key}) Color 15 is 0x{c15:04X}, expected 0x8000"
                )

        # 3. Verify rendered text pixels against catalog
        expected_tim = generate_tim_entry(
            item,
            font=resolved_font,
            candidate_bins=[target_bin, DEFAULT_SRC_BIN, DEFAULT_EN_BIN, DEFAULT_PATCH_REPO_BIN],
        )
        expected_parsed = parse_tim(expected_tim)

        if parsed["pixel_data"] != expected_parsed["pixel_data"]:
            raise ValueError(f"Pixel data mismatch at LBA {lba} ({key}): text='{text_ru}'")

        # 4. Verify sector padding is zeroed
        trailing = user_data[parsed["total_tim_len"] :]
        if any(b != 0 for b in trailing):
            raise ValueError(f"Non-zero sector padding at LBA {lba} ({key})")

        verified_items += 1

    return {
        "status": "success",
        "verified_items": verified_items,
        "verified_sectors": verified_sectors,
        "total_items": len(REQUIRED_MENU_KEYS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch minigame selection menu in Slayers Royal (PS1)."
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=DEFAULT_TARGET_BIN,
        help=f"Path to target disc image (.bin) (default: {DEFAULT_TARGET_BIN})",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Path to catalog JSON (default: {DEFAULT_CATALOG})",
    )
    parser.add_argument(
        "--font",
        type=Path,
        default=None,
        help="Path to PressStart2P.ttf font file",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate composite preview image in data/preview_minigames_menu_ru.png",
    )
    parser.add_argument(
        "--preview-out",
        type=Path,
        default=DEFAULT_PREVIEW_PATH,
        help=f"Custom preview output path (default: {DEFAULT_PREVIEW_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render in memory without modifying disc image",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify binary integrity, rendered text, and Mode 2 Form 1 EDC/ECC",
    )

    args = parser.parse_args()

    if args.verify:
        print(f"[*] Verifying minigames menu on {args.bin}...")
        try:
            res = verify_minigames_menu(args.bin, args.catalog, args.font)
            print(
                f"[✓] Verification SUCCESSFUL!\n"
                f"    Menu items:     {res['verified_items']} / {res['total_items']} verified.\n"
                f"    Disc sectors:   {res['verified_sectors']} sectors with 100% valid Mode 2 Form 1 EDC/ECC."
            )
            return 0
        except Exception as exc:
            print(f"[!] Verification FAILED: {exc}", file=sys.stderr)
            return 1

    print(f"[*] Patching minigames menu from {args.catalog} into {args.bin}...")
    try:
        res = patch_minigames_menu(
            bin_path=args.bin,
            catalog_path=args.catalog,
            font_path=args.font,
            preview=True,  # Always generate preview on patch
            preview_path=args.preview_out,
            dry_run=args.dry_run,
        )
        print(
            f"[✓] Minigames menu successfully patched!\n"
            f"    Patched items:   {res['patched_entries']} items.\n"
            f"    Target images:   {', '.join(res['targets']) if res['targets'] else '(dry run)'}\n"
            f"    Preview image:   {res['preview_path']}"
        )
        return 0
    except Exception as exc:
        print(f"[!] Patching FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
