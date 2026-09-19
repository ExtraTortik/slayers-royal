#!/usr/bin/env python3
"""Slayers Royal (PS1) - Bonus Menu and Title Menu Patcher.

This tool:
1. Loads human-editable catalog `translations/bonus_menu_ru.json` covering:
   - Bonus Room section titles in OPT.UNT:
     - Entry 143 (LBA 228458, sector offset 2458): "SOUND MODE" -> "ЗВУК" (112x16, VRAM 384, 224, CLUT 0, 483)
     - Entry 144 (LBA 228459, sector offset 2459): "MOVIES" -> "РОЛИКИ" (64x16, VRAM 412, 224, CLUT 0, 484)
     - Entry 145 (LBA 228460, sector offset 2460): "HELP" -> "ПОМОЩЬ" (64x16, VRAM 428, 224, CLUT 0, 485)
     - Entry 146 (LBA 228461, sector offset 2461): "MINIGAMES" -> "МИНИ-ИГРЫ" (80x16, VRAM 384, 240, CLUT 0, 486)
   - Title screen menu items:
     - "START" -> "СТАРТ"
     - "CONTINUE" -> "ЗАГРУЗКА"
     - "BONUS" -> "БОНУС"
2. Renders Cyrillic text centered using `fonts/PressStart2P.ttf`:
   - Transparent background (color index 0)
   - Core white glyphs (color index 1)
   - 1px dark outline/shadow (color index 15)
3. Constructs standard 4bpp PS1 TIM files (magic 0x10, flag 0x08, CLUT, pixel data).
4. Pads each TIM to 2048 bytes (1 sector).
5. Injects into disc images (`localization-output/ru/slayers_royal_ru.bin` and
   `patch_repo/localization-output/ru/slayers_royal_ru.bin`) with 100% valid Mode 2 Form 1
   EDC/ECC checksum recalculation.
6. Generates visual preview `data/preview_bonus_menu_ru.png` showing the 4 rendered
   section headers inside template frame 142, plus title menu previews.
7. Provides CLI with `--bin`, `--catalog`, `--verify`, `--preview`, `--dry-run`.
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
DEFAULT_CATALOG = REPO_ROOT / "translations" / "bonus_menu_ru.json"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_PATCH_REPO_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SRC_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_EN_BIN = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"
DEFAULT_FONT_PATH = REPO_ROOT / "fonts" / "PressStart2P.ttf"
DEFAULT_PREVIEW_PATH = REPO_ROOT / "data" / "preview_bonus_menu_ru.png"

REQUIRED_BONUS_KEYS = ("sound_mode", "movies", "help", "minigames")
REQUIRED_TITLE_KEYS = ("start", "continue", "bonus")


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


def load_bonus_menu_catalog(path: Path | str | None = None) -> dict[str, Any]:
    """Load and validate translations/bonus_menu_ru.json catalog."""
    catalog_path = Path(path) if path else DEFAULT_CATALOG
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Bonus menu catalog not found: {catalog_path}")

    with open(catalog_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if not isinstance(doc, dict):
        raise ValueError(f"Catalog at {catalog_path} must be a JSON object")

    if "bonus_menu" not in doc:
        raise ValueError(f"Catalog at {catalog_path} missing 'bonus_menu' object")

    items = doc["bonus_menu"]
    if not isinstance(items, dict):
        raise ValueError(f"'bonus_menu' in {catalog_path} must be a dictionary")

    for key in REQUIRED_BONUS_KEYS:
        if key not in items:
            raise ValueError(f"Missing required bonus menu item '{key}' in catalog")
        item = items[key]
        if not isinstance(item, dict):
            raise ValueError(f"Bonus menu item '{key}' must be a dictionary")
        for field in ("entry", "sector_offset", "vram_x", "vram_y", "width", "height", "text_ru"):
            if field not in item:
                raise ValueError(f"Bonus menu item '{key}' missing required field '{field}'")
        if item["width"] <= 0 or item["width"] % 4 != 0:
            raise ValueError(f"Bonus menu item '{key}' width ({item['width']}) must be a positive multiple of 4")
        if item["height"] <= 0:
            raise ValueError(f"Bonus menu item '{key}' height ({item['height']}) must be positive")

    return doc


def render_text_with_outline(
    text: str,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont | Path | str,
    width: int,
    height: int,
    core_idx: int = 1,
    outline_idx: int = 15,
    tracking: int = 0,
) -> Image.Image:
    """Render single-line Cyrillic text with 1px dark outline centered within (width, height).

    Parameters
    ----------
    text : str
        String to render.
    font : ImageFont or path
        Font instance or path to truetype font.
    width : int
        Target sprite width in pixels.
    height : int
        Target sprite height in pixels.
    core_idx : int
        Palette index for core text glyphs (default 1: white).
    outline_idx : int
        Palette index for 1px outline/shadow (default 15: dark).
    tracking : int
        Extra horizontal spacing in pixels between characters.

    Returns
    -------
    Image.Image
        Indexed 'P' mode image with values in 0..15.
    """
    if isinstance(font, (str, Path)):
        font = ImageFont.truetype(str(font), 8)

    char_adv = [int(font.getlength(c)) for c in text]
    total_advance = sum(char_adv) + max(0, len(text) - 1) * tracking
    font_size = getattr(font, "size", 8)

    start_x = max(0, (width - total_advance) // 2)
    start_y = max(0, (height - font_size) // 2)

    mask = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(mask)

    cx = start_x
    for i, ch in enumerate(text):
        draw.text((cx, start_y), ch, font=font, fill=1)
        cx += char_adv[i] + tracking

    out = Image.new("P", (width, height), 0)
    for y in range(height):
        for x in range(width):
            if mask.getpixel((x, y)):
                out.putpixel((x, y), core_idx)
            else:
                has_neighbor = False
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dx == 0 and dy == 0:
                            continue
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < width and 0 <= ny < height and mask.getpixel((nx, ny)):
                            has_neighbor = True
                            break
                    if has_neighbor:
                        break
                if has_neighbor:
                    out.putpixel((x, y), outline_idx)

    return out


def build_4bpp_pixel_data(image: Image.Image) -> bytes:
    """Convert an indexed image (0..15) into PS1 4bpp pixel data."""
    w, h = image.size
    row_bytes = w // 2
    out = bytearray(row_bytes * h)

    for y in range(h):
        row_offset = y * row_bytes
        for x in range(0, w, 2):
            p0 = int(image.getpixel((x, y))) & 0x0F
            p1 = int(image.getpixel((x + 1, y))) & 0x0F
            out[row_offset + (x // 2)] = p0 | (p1 << 4)

    return bytes(out)


def parse_tim(tim_bytes: bytes) -> dict[str, Any]:
    """Parse PS1 TIM header, CLUT, and dimensions."""
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


def tim_to_rgba_image(tim_bytes: bytes, transparent_zero: bool = True) -> Image.Image:
    """Convert a 4bpp or 8bpp PS1 TIM buffer into an RGBA PIL Image."""
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
    if info["pmode"] == 0:
        for b in info["pixel_data"]:
            p0 = b & 0x0F
            p1 = (b >> 4) & 0x0F
            pixels.append(colors[p0] if p0 < len(colors) else (0, 0, 0, 0))
            pixels.append(colors[p1] if p1 < len(colors) else (0, 0, 0, 0))
    elif info["pmode"] == 1:
        for b in info["pixel_data"]:
            pixels.append(colors[b] if b < len(colors) else (0, 0, 0, 0))
    else:
        raise ValueError(f"Unsupported pmode: {info['pmode']}")

    im = Image.new("RGBA", (w, h))
    im.putdata(pixels[: w * h])
    return im


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


def generate_bonus_tim(
    item: dict[str, Any],
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont | Path | str | None = None,
    candidate_bins: Sequence[Path] | None = None,
) -> bytes:
    """Generate a complete 2048-byte PS1 4bpp TIM sector for a bonus menu entry."""
    text_ru = item["text_ru"]
    w = item["width"]
    h = item["height"]
    font_size = item.get("font_size", 8)
    tracking = item.get("tracking", 0)
    core_idx = item.get("color_index", 1)
    outline_idx = item.get("outline_index", 15)
    sec_off = item["sector_offset"]
    vram_x = item["vram_x"]
    vram_y = item["vram_y"]
    clut_x = item.get("clut_x", 0)
    clut_y = item.get("clut_y", 483)

    if font is None:
        font_path = find_font()
        font_obj = ImageFont.truetype(str(font_path), font_size)
    elif isinstance(font, (str, Path)):
        font_obj = ImageFont.truetype(str(font), font_size)
    else:
        font_obj = font

    # Retrieve original pristine CLUT palette
    clut_data: bytes | None = None
    cands = list(candidate_bins) if candidate_bins else [
        DEFAULT_TARGET_BIN,
        DEFAULT_SRC_BIN,
        DEFAULT_EN_BIN,
        DEFAULT_PATCH_REPO_BIN,
    ]
    try:
        pristine_tim = get_pristine_sector_data(sec_off, cands)
        parsed = parse_tim(pristine_tim)
        if parsed.get("clut"):
            clut_data = parsed["clut"]["data"]
            clut_x = parsed["clut"]["x"]
            clut_y = parsed["clut"]["y"]
    except Exception:
        pass

    if clut_data is None:
        # Construct standard 16-color grayscale CLUT
        raw_clut = bytearray(32)
        # Index 0: 0x0000 transparent
        # Index 1: 0x7FFF white
        struct.pack_into("<H", raw_clut, 2, 0x7FFF)
        # Index 15: 0x0842 dark outline
        struct.pack_into("<H", raw_clut, 30, 0x0842)
        clut_data = bytes(raw_clut)

    # Render outlined text
    rendered_im = render_text_with_outline(
        text=text_ru,
        font=font_obj,
        width=w,
        height=h,
        core_idx=core_idx,
        outline_idx=outline_idx,
        tracking=tracking,
    )

    pixel_data = build_4bpp_pixel_data(rendered_im)

    return build_tim(
        clut_x=clut_x,
        clut_y=clut_y,
        clut_data=clut_data,
        img_x=vram_x,
        img_y=vram_y,
        width=w,
        height=h,
        pixel_data=pixel_data,
    )


def patch_disc_sector(bin_path: Path, lba: int, payload: bytes) -> None:
    """Inject 2048-byte payload into disc image at LBA and recalculate EDC/ECC."""
    if len(payload) != USER_DATA_SIZE:
        raise ValueError(f"Payload size must be exactly {USER_DATA_SIZE} bytes (got {len(payload)})")

    if replace_extent_in_place is not None:
        replace_extent_in_place(bin_path, lba, payload)
    else:
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


def generate_preview(
    catalog: dict[str, Any],
    bin_path: Path | None = None,
    font_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """Generate visual preview data/preview_bonus_menu_ru.png.

    Displays:
    - 4 Bonus Room headers centered inside Template Frame 142 (navy with gold border).
    - 3 Title Menu items (СТАРТ, ЗАГРУЗКА, БОНУС).
    """
    out_file = Path(output_path) if output_path else DEFAULT_PREVIEW_PATH
    out_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_font = find_font(font_path)

    b_items = catalog["bonus_menu"]
    t_items = catalog.get("title_menu", {})

    # Load template frame 142 from candidate disc images
    cands: list[Path] = []
    if bin_path and Path(bin_path).is_file():
        cands.append(Path(bin_path))
    for p in (DEFAULT_TARGET_BIN, DEFAULT_SRC_BIN, DEFAULT_EN_BIN, DEFAULT_PATCH_REPO_BIN):
        if p.is_file() and p not in cands:
            cands.append(p)

    frame_entry = b_items.get("frame", {})
    frame_sec_off = frame_entry.get("sector_offset", 2456)
    frame_lba = OPT_ARCHIVE_LBA + frame_sec_off
    frame_count = frame_entry.get("sectors", 2)

    frame_im: Image.Image | None = None
    for cand in cands:
        try:
            frame_data = read_sector_extent(cand, frame_lba, frame_count)
            frame_im = tim_to_rgba_image(frame_data)
            break
        except Exception:
            continue

    if frame_im is None:
        # Fallback frame: 128x32 navy box with gold border
        frame_im = Image.new("RGBA", (128, 32), (0, 0, 0, 0))
        d = ImageDraw.Draw(frame_im)
        d.rectangle([0, 0, 127, 31], fill=(16, 24, 64, 255), outline=(216, 176, 48, 255), width=2)

    # Canvas width: 320 px, height: 260 px
    canvas_w = 320
    canvas_h = 260
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (20, 24, 32, 255))
    draw = ImageDraw.Draw(canvas)

    header_font = ImageFont.truetype(str(resolved_font), 8)
    draw.text((16, 10), "--- БОНУСНАЯ КОМНАТА (OPT.UNT 143..146) ---", font=header_font, fill=(240, 200, 80, 255))

    y = 28
    for key in REQUIRED_BONUS_KEYS:
        item = b_items[key]
        tim_bytes = generate_bonus_tim(item, font=resolved_font, candidate_bins=cands)
        text_im = tim_to_rgba_image(tim_bytes)

        # Composite frame and text
        item_frame = frame_im.copy()
        tx = (item_frame.width - text_im.width) // 2
        ty = (item_frame.height - text_im.height) // 2
        item_frame.alpha_composite(text_im, (tx, ty))

        canvas.alpha_composite(item_frame, (16, y))

        # Add label on right
        info_str = f"Entry {item['entry']}: {item['text_en']} -> {item['text_ru']} ({item['width']}x{item['height']})"
        draw.text((152, y + 10), info_str, font=header_font, fill=(220, 220, 220, 255))
        y += 38

    # Title screen menu section
    y += 10
    draw.text((16, y), "--- ГЛАВНОЕ МЕНЮ (TITLE SCREEN) ---", font=header_font, fill=(240, 200, 80, 255))
    y += 18

    tx_start = 16
    for t_key in REQUIRED_TITLE_KEYS:
        if t_key in t_items:
            t_item = t_items[t_key]
            text_ru = t_item["text_ru"]
            w = t_item["width"]
            h = t_item["height"]
            rendered = render_text_with_outline(
                text=text_ru,
                font=header_font,
                width=w,
                height=h,
                core_idx=1,
                outline_idx=15,
            )
            # Make visible RGBA for preview
            rgba_t = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            for py in range(h):
                for px in range(w):
                    c = rendered.getpixel((px, py))
                    if c == 1:
                        rgba_t.putpixel((px, py), (248, 248, 248, 255))
                    elif c == 15:
                        rgba_t.putpixel((px, py), (24, 24, 24, 255))

            # Draw framed button
            button_box = Image.new("RGBA", (w + 16, h + 8), (32, 40, 64, 255))
            b_draw = ImageDraw.Draw(button_box)
            b_draw.rectangle([0, 0, w + 15, h + 7], outline=(180, 140, 40, 255), width=1)
            button_box.alpha_composite(rgba_t, (8, 4))

            canvas.alpha_composite(button_box, (tx_start, y))
            tx_start += w + 24

    canvas.save(out_file)
    return out_file


def patch_bonus_menu(
    bin_path: Path | str | None = None,
    catalog_path: Path | str | None = None,
    font_path: Path | str | None = None,
    preview: bool = True,
    preview_path: Path | str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Patch all 4 bonus room section titles into disc image(s)."""
    target_bin = Path(bin_path) if bin_path else DEFAULT_TARGET_BIN
    if not dry_run and not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    catalog = load_bonus_menu_catalog(catalog_path)
    resolved_font = find_font(font_path)

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

    b_items = catalog["bonus_menu"]
    patched_entries = 0
    patched_sectors: list[dict[str, Any]] = []

    for key in REQUIRED_BONUS_KEYS:
        item = b_items[key]
        sec_off = item["sector_offset"]
        lba = OPT_ARCHIVE_LBA + sec_off
        w = item["width"]
        h = item["height"]
        text_ru = item["text_ru"]

        tim_sector = generate_bonus_tim(
            item,
            font=resolved_font,
            candidate_bins=cands,
        )

        if not dry_run:
            for tgt in targets:
                patch_disc_sector(tgt, lba, tim_sector)

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
        "title_menu": catalog.get("title_menu", {}),
    }


def verify_bonus_menu(
    bin_path: Path | str | None = None,
    catalog_path: Path | str | None = None,
    font_path: Path | str | None = None,
) -> dict[str, Any]:
    """Verify binary integrity, Mode 2 Form 1 EDC/ECC, and rendered text on disc image."""
    target_bin = Path(bin_path) if bin_path else DEFAULT_TARGET_BIN
    if not target_bin.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_bin}")

    catalog = load_bonus_menu_catalog(catalog_path)
    chk = CdChecksums() if CdChecksums is not None else None

    b_items = catalog["bonus_menu"]
    verified_sectors = 0
    verified_items = 0

    for key in REQUIRED_BONUS_KEYS:
        item = b_items[key]
        sec_off = item["sector_offset"]
        lba = OPT_ARCHIVE_LBA + sec_off
        w = item["width"]
        h = item["height"]
        text_ru = item["text_ru"]

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
        if parsed["img_x"] != item["vram_x"] or parsed["img_y"] != item["vram_y"]:
            raise ValueError(
                f"TIM at LBA {lba} VRAM mismatch: expected ({item['vram_x']},{item['vram_y']}), found ({parsed['img_x']},{parsed['img_y']})"
            )

        # 3. Verify non-trivial pixel data
        non_zero = sum(1 for b in parsed["pixel_data"] if b != 0)
        if non_zero < 10:
            raise ValueError(f"TIM at LBA {lba} has insufficient active pixels ({non_zero})")

        verified_items += 1

    return {
        "status": "verified",
        "disc": str(target_bin),
        "verified_sectors": verified_sectors,
        "verified_items": verified_items,
        "bonus_menu_items": list(REQUIRED_BONUS_KEYS),
        "title_menu_items": list(REQUIRED_TITLE_KEYS),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch and verify Bonus Menu and Title Menu for Slayers Royal PS1")
    parser.add_argument("--bin", type=Path, default=DEFAULT_TARGET_BIN, help="Path to target disc image (.bin)")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Path to JSON catalog")
    parser.add_argument("--font", type=Path, default=None, help="Path to PressStart2P.ttf font")
    parser.add_argument("--preview", type=Path, default=None, help="Path to output preview PNG")
    parser.add_argument("--no-preview", action="store_true", help="Skip preview generation")
    parser.add_argument("--verify", action="store_true", help="Verify patched sectors on disc image")
    parser.add_argument("--dry-run", action="store_true", help="Run rendering without writing to disc")

    args = parser.parse_args()

    if args.verify:
        try:
            res = verify_bonus_menu(bin_path=args.bin, catalog_path=args.catalog, font_path=args.font)
            print(f"[✓] Успешная верификация меню бонусов и главного меню: {res['verified_items']} элементов, {res['verified_sectors']} секторов")
            return 0
        except Exception as e:
            print(f"[✗] Ошибка верификации: {e}", file=sys.stderr)
            return 1

    try:
        res = patch_bonus_menu(
            bin_path=args.bin,
            catalog_path=args.catalog,
            font_path=args.font,
            preview=not args.no_preview,
            preview_path=args.preview,
            dry_run=args.dry_run,
        )
        print(f"[✓] Успешно внедрено {res['patched_entries']} элементов меню бонусов.")
        for sec in res["patched_sectors"]:
            print(f"    - Entry {sec['entry']} ({sec['key']}): {sec['text_ru']} (LBA {sec['lba']}, {sec['size']})")
        if res.get("preview_path"):
            print(f"    - Превью сохранено в {res['preview_path']}")
        return 0
    except Exception as e:
        print(f"[✗] Ошибка сборки меню: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
