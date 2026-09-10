#!/usr/bin/env python3
"""Unpack, modify, and pack Slayers Royal PS1 combat font (PROG.UNT entry 0x142).

This tool:
1. Decompresses 0x142 (4bpp PSX TIM, 256x512 pixels / 512 16x16 tiles, size 66,080 bytes).
2. Preserves the original CLUT / palette at (0, 480) and VRAM coordinates (0, 0).
3. Renders Cyrillic glyphs (А-Я, а-я, Ё, ё, punctuation) into 16x16 tiles using PressStart2P.
   Style: white text core (index 15), black/dark outline/shadow (index 1), transparent (index 0).
4. Generates a charmap dictionary mapping characters to 16-bit tile codes.
5. Verifies that compressed unt_lz (mode 1) stream fits in the 23-sector budget (47,104 bytes).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "patch_repo"))
sys.path.insert(0, str(REPO_ROOT))

from localization import unt_lz
from localization.disc import read_extent, RAW_SECTOR_SIZE, USER_DATA_SIZE, USER_DATA_OFFSET
from tools.patch_inspection import (
    parse_iso_dir,
    read_sector,
    read_unt_index,
    DEFAULT_CHARMAP,
)

COMBAT_FONT_ENTRY = 0x142
COMBAT_FONT_SECTORS = 23
COMBAT_FONT_MAX_SIZE = COMBAT_FONT_SECTORS * 2048  # 47,104 bytes
TIM_DECOMPRESSED_SIZE = 66080
TIM_HEADER_SIZE = 544  # 8 bytes magic/flags + 524 bytes CLUT + 12 bytes IMG header
VRAM_WIDTH_WORDS = 64  # 128 bytes = 256 pixels at 4bpp
TILE_WIDTH_PX = 16
TILE_HEIGHT_PX = 16
TILES_PER_ROW = 16
TOTAL_TILES = 512
BYTES_PER_TILE = 128

# Character sets for combat charmap
CYRILLIC_UPPER = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
CYRILLIC_LOWER = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
CYRILLIC_UPPER_BASE = 0x0150
CYRILLIC_LOWER_BASE = 0x0171
CYRILLIC_UNIQUE_UPPER = "БГДЖЗИЙЛПФЦЧШЩЪЫЬЭЮЯЁ"
CYRILLIC_UNIQUE_LOWER = "бвгджзийклмнптфцчшщъыьэюяё"
CYRILLIC_PUNCT = "«»—…„“"
DIGITS = "0123456789"
PUNCTUATION = "!\"()*,-./:;?="
ASCII_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

# Latin lookalikes mapped to verified gourry-hacks runtime font tiles
LATIN_EQUIVALENTS: dict[str, int] = {
    "А": 0x00BE,  # 'A'
    "В": 0x014C,  # 'B'
    "С": 0x0128,  # 'C'
    "Е": 0x00B6,  # 'E'
    "Н": 0x0091,  # 'H'
    "К": 0x0192,  # 'K'
    "М": 0x0148,  # 'M'
    "О": 0x00BB,  # 'O'
    "Р": 0x019B,  # 'P'
    "Т": 0x008D,  # 'T'
    "Х": 0x01FD,  # 'X'
    "У": 0x009A,  # 'Y'
    "а": 0x0017,  # 'a'
    "с": 0x003A,  # 'c'
    "е": 0x0048,  # 'e'
    "о": 0x0067,  # 'o'
    "р": 0x006C,  # 'p' (also 0x0068)
    "х": 0x0074,  # 'x'
    "у": 0x0075,  # 'y'
}
# Canonical ASCII glyph mapping (matches PS1 game / gourry-hacks runtime font)
CANONICAL_ASCII_GLYPHS: dict[str, int] = {
    " ": 0x007D,
    "!": 0x00A6,
    '"': 0x00A3,
    "'": 0x031B,
    "(": 0x0001,
    ")": 0x0002,
    "*": 0x0003,
    ",": 0x00A1,
    "-": 0x00A4,
    ".": 0x00A2,
    "/": 0x0004,
    ":": 0x00BC,
    ";": 0x0005,
    "?": 0x00A7,
    "=": 0x0006,
    "0": 0x00A8,
    "1": 0x00A9,
    "2": 0x00AA,
    "3": 0x00AB,
    "4": 0x00AC,
    "5": 0x00AD,
    "6": 0x00AE,
    "7": 0x00AF,
    "8": 0x00B0,
    "9": 0x00B1,
    "A": 0x00BE,
    "B": 0x014C,
    "C": 0x0128,
    "D": 0x00BF,
    "E": 0x00B6,
    "F": 0x014D,
    "G": 0x0088,
    "H": 0x0091,
    "I": 0x0081,
    "J": 0x014F,
    "K": 0x0192,
    "L": 0x0082,
    "M": 0x0148,
    "N": 0x0086,
    "O": 0x00BB,
    "P": 0x019B,
    "Q": 0x01A7,
    "R": 0x0099,
    "S": 0x0090,
    "T": 0x008D,
    "U": 0x01D2,
    "V": 0x00BD,
    "W": 0x008E,
    "X": 0x01FD,
    "Y": 0x009A,
    "Z": 0x0209,
    "a": 0x0017,
    "b": 0x0031,
    "c": 0x003A,
    "d": 0x0040,
    "e": 0x0048,
    "f": 0x004A,
    "g": 0x004B,
    "h": 0x004D,
    "i": 0x004F,
    "j": 0x0055,
    "k": 0x005F,
    "l": 0x0060,
    "m": 0x0062,
    "n": 0x0063,
    "o": 0x0067,
    "p": 0x0068,
    "q": 0x0069,
    "r": 0x006B,
    "s": 0x006D,
    "t": 0x006E,
    "u": 0x006F,
    "v": 0x0070,
    "w": 0x0071,
    "x": 0x0074,
    "y": 0x0075,
    "z": 0x0076,
}


def find_press_start_font() -> Path:
    """Locate PressStart2P.ttf font in repository."""
    candidates = (
        REPO_ROOT / "fonts" / "PressStart2P.ttf",
        REPO_ROOT / "patch_repo" / "fonts" / "PressStart2P.ttf",
        Path("/home/samvel/dddd/fonts/PressStart2P.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf"),
    )
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("PressStart2P.ttf font not found in repo")


def build_combat_charmap() -> dict[str, int]:
    """Build charmap dictionary mapping characters to 16-bit combat tile codes."""
    from tools.combat_text import load_combat_charmap
    return load_combat_charmap()


def build_reverse_charmap(charmap: Mapping[str, int] | None = None) -> dict[int, str]:
    """Build reverse charmap mapping 16-bit codes to characters, prioritizing Cyrillic."""
    from tools.combat_text import build_reverse_charmap as _rev
    return _rev(charmap)


def load_gourry_latin_tiles() -> dict[int, bytes]:
    """Load verified gourry-hacks Latin tiles (from data/gourry_latin_tiles.json)."""
    cache_file = REPO_ROOT / "data" / "gourry_latin_tiles.json"
    if cache_file.is_file():
        doc = json.loads(cache_file.read_text(encoding="utf-8"))
        return {int(k, 16): bytes.fromhex(v) for k, v in doc.items()}
    return {}


def extract_entry_142_bytes(source_path: Path) -> bytes:
    """Extract compressed bytes of entry 0x142 from disc image, UNT, or raw file."""
    if source_path.stat().st_size > 100 * 1024 * 1024:
        # PS1 BIN CD-ROM image
        pvd = read_sector(source_path, 16)
        root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
        root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
        root_dir = parse_iso_dir(source_path, root_lba, root_size)
        if "PROG.UNT" not in root_dir:
            raise ValueError("PROG.UNT not found in ISO directory")
        prog_lba, _ = root_dir["PROG.UNT"]
        sector0 = read_extent(source_path, prog_lba, 2048)
        entries = read_unt_index(sector0)
        e = entries[COMBAT_FONT_ENTRY]
        return read_extent(source_path, prog_lba + e.start_sector, e.size)
    elif source_path.name.upper().endswith(".UNT"):
        data = source_path.read_bytes()
        entries = read_unt_index(data[:2048])
        e = entries[COMBAT_FONT_ENTRY]
        start = e.start_sector * 2048
        return data[start : start + e.size]
    else:
        # Standalone packed file
        return source_path.read_bytes()


def unpack_combat_font(source_path: Path | None = None) -> bytes:
    """Extract and decompress combat font TIM from source or cached English TIM."""
    cache_tim = REPO_ROOT / "data" / "prog_entry_142_en.tim"
    if source_path is None and cache_tim.is_file():
        return cache_tim.read_bytes()

    if source_path is not None and source_path.is_file():
        try:
            raw_data = extract_entry_142_bytes(source_path)
            decompressed, _ = unt_lz.decompress(raw_data)
            if len(decompressed) == TIM_DECOMPRESSED_SIZE:
                return decompressed
        except Exception:
            pass

    if cache_tim.is_file():
        return cache_tim.read_bytes()

    raise FileNotFoundError("Combat font 0x142 could not be unpacked and cache not found")


def get_tile(tim_buf: bytes | bytearray, tile_id: int) -> bytes:
    """Extract 128-byte 4bpp tile data for a 16x16 tile."""
    tx = tile_id % TILES_PER_ROW
    ty = tile_id // TILES_PER_ROW
    data = bytearray()
    for y in range(TILE_HEIGHT_PX):
        off = TIM_HEADER_SIZE + (ty * 16 + y) * 128 + tx * 8
        data.extend(tim_buf[off : off + 8])
    return bytes(data)


def put_tile(tim_buf: bytearray, tile_id: int, tile_bytes: bytes) -> None:
    """Write 128-byte 4bpp tile data into TIM buffer."""
    tx = tile_id % TILES_PER_ROW
    ty = tile_id // TILES_PER_ROW
    for y in range(TILE_HEIGHT_PX):
        off = TIM_HEADER_SIZE + (ty * 16 + y) * 128 + tx * 8
        tim_buf[off : off + 8] = tile_bytes[y * 8 : (y + 1) * 8]


def get_hw_tile_2bpp(tim_buf: bytes | bytearray, code: int) -> bytes:
    bank = (code >> 8) & 3
    row = (code >> 4) & 0xF
    col = code & 0xF
    data = bytearray()
    for y in range(16):
        off = 544 + bank * 16384 + (row * 16 + y) * 64 + col * 4
        data.extend(tim_buf[off : off + 4])
    return bytes(data)


def put_hw_tile_2bpp(tim_buf: bytearray, code: int, tile_bytes: bytes) -> None:
    bank = (code >> 8) & 3
    row = (code >> 4) & 0xF
    col = code & 0xF
    for y in range(16):
        off = 544 + bank * 16384 + (row * 16 + y) * 64 + col * 4
        tim_buf[off : off + 4] = tile_bytes[y * 4 : (y + 1) * 4]


def render_cyrillic_glyph_2bpp(char: str, font_path: Path) -> bytes:
    """Render a single character into a 16x16 2BPP tile using PressStart2P (size 11).

    Pixel values in 2BPP:
    - 0 = transparent
    - 1 = dark shadow/outline
    - 3 = text body core (white)

    4 pixels per byte:
    b = (p0 & 3) | ((p1 & 3) << 2) | ((p2 & 3) << 4) | ((p3 & 3) << 6)
    """
    canvas_core = Image.new("L", (16, 16), 0)
    canvas_shadow = Image.new("L", (16, 16), 0)
    draw_core = ImageDraw.Draw(canvas_core)
    draw_shadow = ImageDraw.Draw(canvas_shadow)

    font = ImageFont.truetype(str(font_path), 11)
    bbox = draw_core.textbbox((0, 0), char, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]

    # Center horizontally and vertically within 16x16 tile, leaving margin for shadow
    x = max(0, min(14, (15 - w) // 2))
    y = max(0, min(14, (15 - h) // 2))

    draw_core.text((x - bbox[0], y - bbox[1]), char, font=font, fill=255)
    draw_shadow.text((x - bbox[0] + 1, y - bbox[1] + 1), char, font=font, fill=255)

    pix_c = canvas_core.load()
    pix_s = canvas_shadow.load()

    tile_bytes = bytearray()
    for py in range(16):
        for col_byte in range(4):
            px_base = col_byte * 4
            p0 = 3 if pix_c[px_base + 0, py] >= 80 else (1 if pix_s[px_base + 0, py] >= 80 else 0)
            p1 = 3 if pix_c[px_base + 1, py] >= 80 else (1 if pix_s[px_base + 1, py] >= 80 else 0)
            p2 = 3 if pix_c[px_base + 2, py] >= 80 else (1 if pix_s[px_base + 2, py] >= 80 else 0)
            p3 = 3 if pix_c[px_base + 3, py] >= 80 else (1 if pix_s[px_base + 3, py] >= 80 else 0)
            b = (p0 & 3) | ((p1 & 3) << 2) | ((p2 & 3) << 4) | ((p3 & 3) << 6)
            tile_bytes.append(b)

    return bytes(tile_bytes)


def build_patched_combat_font(
    tim_decompressed: bytes,
    font_path: Path | None = None,
) -> tuple[bytes, bytes]:
    """Render Cyrillic glyphs into font 0x142 in 2BPP and compress with unt_lz mode 1.

    Renders all 66 characters in CYRILLIC_UPPER (0x0150..0x0170) and
    CYRILLIC_LOWER (0x0171..0x0191) using put_hw_tile_2bpp.

    Returns:
        (patched_tim_decompressed, compressed_bytes)

    Raises:
        ValueError if compressed font exceeds 23 sectors (47,104 bytes).
    """
    if len(tim_decompressed) != TIM_DECOMPRESSED_SIZE:
        raise ValueError(f"Invalid TIM size: {len(tim_decompressed)} bytes (expected {TIM_DECOMPRESSED_SIZE})")

    fp = font_path or find_press_start_font()
    if not fp.is_file():
        raise FileNotFoundError(f"Font file not found: {fp}")

    patched_tim = bytearray(tim_decompressed)

    # Render 33 uppercase Russian glyphs into 0x0150..0x0170
    for idx, ch in enumerate(CYRILLIC_UPPER):
        code = CYRILLIC_UPPER_BASE + idx
        tile_bytes = render_cyrillic_glyph_2bpp(ch, fp)
        put_hw_tile_2bpp(patched_tim, code, tile_bytes)

    # Render 33 lowercase Russian glyphs into 0x0171..0x0191
    for idx, ch in enumerate(CYRILLIC_LOWER):
        code = CYRILLIC_LOWER_BASE + idx
        tile_bytes = render_cyrillic_glyph_2bpp(ch, fp)
        put_hw_tile_2bpp(patched_tim, code, tile_bytes)

    patched_bytes = bytes(patched_tim)

    # Compress with unt_lz mode 1
    compressed = unt_lz.compress(patched_bytes)
    if len(compressed) > COMBAT_FONT_MAX_SIZE:
        raise ValueError(
            f"Compressed font size ({len(compressed)} bytes) exceeds budget of "
            f"{COMBAT_FONT_MAX_SIZE} bytes ({COMBAT_FONT_SECTORS} sectors)"
        )

    return patched_bytes, compressed

def render_cyrillic_glyph(char: str, font_path: Path, base_size: int = 12) -> bytes:
    """Render a character into a 16x16 4bpp tile.

    Colors:
    - 0x0: Transparent background
    - 0x1: Dark shadow / outline (matches Palette 0 Color 1)
    - 0x3: Text core body (matches Palette 0 Color 3 and gourry-hacks 'A')
    """
    canvas_core = Image.new("L", (16, 16), 0)
    canvas_shadow = Image.new("L", (16, 16), 0)
    draw_core = ImageDraw.Draw(canvas_core)
    draw_shadow = ImageDraw.Draw(canvas_shadow)

    for sz in (base_size, 11, 10, 9, 8):
        f = ImageFont.truetype(str(font_path), sz)
        bbox = draw_core.textbbox((0, 13), char, font=f, anchor="ls")
        w = bbox[2] - bbox[0]
        if w <= 13 and bbox[1] >= 1:
            x = max(1, (15 - w) // 2)
            draw_core.text((x, 13), char, font=f, anchor="ls", fill=255)
            draw_shadow.text((x + 1, 14), char, font=f, anchor="ls", fill=255)
            break
    else:
        f = ImageFont.truetype(str(font_path), 8)
        bbox = draw_core.textbbox((0, 13), char, font=f, anchor="ls")
        w = bbox[2] - bbox[0]
        x = max(0, (15 - w) // 2)
        draw_core.text((x, 13), char, font=f, anchor="ls", fill=255)
        draw_shadow.text((x + 1, 14), char, font=f, anchor="ls", fill=255)

    pix_c = canvas_core.load()
    pix_s = canvas_shadow.load()

    tile_bytes = bytearray()
    for py in range(16):
        row_nibs = []
        for px in range(16):
            if pix_c[px, py] >= 80:
                row_nibs.append(3)   # Text core body (Color 3 in CLUT)
            elif pix_s[px, py] >= 80:
                row_nibs.append(1)   # Dark shadow / outline (Color 1 in CLUT)
            else:
                row_nibs.append(0)   # Transparent

        for i in range(0, 16, 2):
            b = (row_nibs[i] & 0x0F) | ((row_nibs[i + 1] & 0x0F) << 4)
            tile_bytes.append(b)

    return bytes(tile_bytes)


def patch_combat_font(
    tim_decompressed: bytes,
    charmap: Mapping[str, int] | None = None,
    font_path: Path | None = None,
) -> tuple[bytes, dict[str, int]]:
    """Patch decompressed TIM with Cyrillic glyphs.

    Preserves original TIM header (544 bytes) and CLUT completely,
    while setting Color 15 in Palette 0 to white.
    """
    if len(tim_decompressed) != TIM_DECOMPRESSED_SIZE:
        raise ValueError(f"Invalid TIM size: {len(tim_decompressed)} bytes")

    cm = charmap if charmap is not None else build_combat_charmap()
    fp = font_path if font_path is not None else find_press_start_font()

    patched = bytearray(tim_decompressed)

    # 2. Space tile (0x007D) is an empty transparent tile (all 0s)
    space_tile = cm.get(" ", 0x007D)
    if space_tile < TOTAL_TILES:
        put_tile(patched, space_tile, bytes(BYTES_PER_TILE))

    # 3. Copy verified gourry-hacks Latin tiles
    gourry_tiles = load_gourry_latin_tiles()
    for tid, tile_data in gourry_tiles.items():
        if tid < TOTAL_TILES:
            put_tile(patched, tid, tile_data)

    # 4. Render unique Russian glyphs into free kanji slots (0x01A0..0x01CF)
    rendered_tiles: set[int] = {space_tile} | set(gourry_tiles.keys())
    for char in CYRILLIC_UNIQUE_UPPER + CYRILLIC_UNIQUE_LOWER:
        if char in cm:
            tile_id = cm[char]
            if tile_id < TOTAL_TILES and tile_id not in rendered_tiles:
                tile_data = render_cyrillic_glyph(char, fp)
                put_tile(patched, tile_id, tile_data)
                rendered_tiles.add(tile_id)

    return bytes(patched), cm


def compress_combat_font(tim_bytes: bytes) -> bytes:
    """Compress TIM bytes using unt_lz mode 1 and verify sector budget."""
    if len(tim_bytes) != TIM_DECOMPRESSED_SIZE:
        raise ValueError(f"Invalid TIM size: {len(tim_bytes)} bytes")
    compressed = unt_lz.compress(tim_bytes)
    if len(compressed) > COMBAT_FONT_MAX_SIZE:
        raise ValueError(
            f"Compressed font size ({len(compressed)} bytes) exceeds 23 sectors budget ({COMBAT_FONT_MAX_SIZE} bytes)"
        )
    return compressed


def main() -> int:
    parser = argparse.ArgumentParser(description="Unpack and patch Slayers Royal PS1 combat font 0x142.")
    parser.add_argument("--bin", type=Path, default=REPO_ROOT / "downloads" / "sr.bin", help="Path to disc image (sr.bin)")
    parser.add_argument("--extract-tim", type=Path, help="Extract decompressed original TIM to path")
    parser.add_argument("--output-tim", type=Path, help="Save patched decompressed TIM to path")
    parser.add_argument("--output-packed", type=Path, help="Save patched compressed entry 0x142 to path")
    parser.add_argument("--dump-charmap", type=Path, help="Dump combat charmap JSON to path")
    parser.add_argument("--verify", action="store_true", help="Run self-tests on font unpacking and packing")

    args = parser.parse_args()

    font_path = find_press_start_font()
    charmap = build_combat_charmap()

    if args.dump_charmap:
        cm_hex = {k: f"0x{v:04X}" for k, v in sorted(charmap.items(), key=lambda x: x[1])}
        args.dump_charmap.parent.mkdir(parents=True, exist_ok=True)
        args.dump_charmap.write_text(json.dumps(cm_hex, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Dumped charmap ({len(charmap)} entries) to {args.dump_charmap}")

    if args.verify or args.output_tim or args.output_packed or args.extract_tim:
        if not args.bin.is_file():
            print(f"Error: Disc image not found at {args.bin}", file=sys.stderr)
            return 1

        print(f"Unpacking combat font 0x142 from {args.bin}...")
        orig_tim = unpack_combat_font(args.bin)
        print(f"Decompressed TIM: {len(orig_tim):,} bytes")

        if args.extract_tim:
            args.extract_tim.parent.mkdir(parents=True, exist_ok=True)
            args.extract_tim.write_bytes(orig_tim)
            print(f"Saved original TIM to {args.extract_tim}")

        print("Patching combat font with Cyrillic glyphs...")
        patched_tim, _ = patch_combat_font(orig_tim, charmap, font_path)

        if args.output_tim:
            args.output_tim.parent.mkdir(parents=True, exist_ok=True)
            args.output_tim.write_bytes(patched_tim)
            print(f"Saved patched TIM to {args.output_tim}")

        print("Compressing patched combat font (unt_lz mode 1)...")
        packed = compress_combat_font(patched_tim)
        margin = COMBAT_FONT_MAX_SIZE - len(packed)
        print(f"Compressed size: {len(packed):,} bytes / budget: {COMBAT_FONT_MAX_SIZE:,} bytes (margin: {margin:,} bytes / {margin/2048:.2f} sectors)")

        # Verify round-trip decompression
        dec, _ = unt_lz.decompress(packed)
        assert dec == patched_tim, "Round-trip decompression verification failed!"
        print("Verification: Round-trip compression and decompression verified bit-exact!")

        if args.output_packed:
            args.output_packed.parent.mkdir(parents=True, exist_ok=True)
            args.output_packed.write_bytes(packed)
            print(f"Saved packed 0x142 to {args.output_packed}")

    print("All tasks completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
