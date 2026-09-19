#!/usr/bin/env python3
"""Slayers Royal (PS1) - BASYOG.UNT Entry 162 Character Tabs & Status UI Atlas Patcher.

Entry 162 (LBA 233328 + 6046 = 239374, 4 sectors = 8,192 bytes budget)
contains the character tabs, status screen labels, and status UI texture atlas
displayed during character status, equipment, and profile screens.

Uncompressed format:
- PlayStation 1 8bpp TIM image (magic 0x10, flag 0x09)
- 256-color CLUT at VRAM (0, 480) [524 bytes: 12 header + 512 palette]
- 256x256 pixels (128 words x 256 lines) at VRAM (0, 0) [65,548 bytes: 12 header + 65,536 pixel data]
- Total uncompressed size: 66,080 bytes

Compression:
- Slayers Royal LZSS mode 1 (unt_lz) within the 4-sector budget (8,192 bytes).
- Sector replacement with Mode 2 Form 1 EDC/ECC recalculation.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

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
        read_extent,
        replace_extent_in_place,
    )
except ImportError:
    from patch_repo.localization import unt_lz
    from patch_repo.localization.disc import (
        CdChecksums,
        RAW_SECTOR_SIZE,
        read_extent,
        replace_extent_in_place,
    )

BASYOG_LBA = 233328
ENTRY_162_OFFSET = 6046
ENTRY_162_SECTORS = 4
ENTRY_162_BUDGET = 8192
ENTRY_162_LBA = BASYOG_LBA + ENTRY_162_OFFSET  # 239374

DEFAULT_RU_PNG = REPO_ROOT / "data" / "preview_basyog_162_ru.png"
DEFAULT_EN_PNG = REPO_ROOT / "data" / "preview_basyog_162_en.png"
SECONDARY_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"

TIM_WIDTH = 256
TIM_HEIGHT = 256
UNCOMPRESSED_TIM_SIZE = 66080  # 8 + 524 + 65548
CLUT_BLOCK_SIZE = 524
IMAGE_HEADER_SIZE = 12
PIXEL_DATA_SIZE = TIM_WIDTH * TIM_HEIGHT  # 65536 bytes

# Standard original 41 active indices used in BASYOG.UNT Entry 162
USED_CLUT_INDICES = [
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
    36, 37, 38, 39, 40, 41, 43, 44, 45, 64,
]

# Canonical 524-byte CLUT block from original Slayers Royal BASYOG Entry 162
FALLBACK_CLUT = bytes.fromhex(
    "0c0200000000e001000101000000ffff39e773ceadb508a15caaf7a193992e91"
    "ca88de9f189752928c89e7840000ffa2589ab2910b8985803fa9f99cb3946d8c"
    "278469d3a7c205b263a1c194000008a110c218e388b845a452fe7ed29fb7cde1"
    "000051fd0ee5cbd088b845a4000000bc00b800b400b000ac00a800a400a0009c"
    "009800949f83b782cf81e7802184000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000"
)


def get_candidate_bins() -> list[Path]:
    """List potential candidate disc images containing pristine or patched Entry 162."""
    return [
        REPO_ROOT / "build" / "en_patched" / "sr_patched.bin",
        REPO_ROOT / "downloads" / "sr.bin",
        REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin",
        REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin",
    ]


def extract_clut_from_disc(disc_path: Path | str) -> bytes | None:
    """Extract 524-byte CLUT block for Entry 162 from candidate disc image."""
    path = Path(disc_path)
    if not path.is_file():
        return None
    try:
        raw = read_extent(path, ENTRY_162_LBA, ENTRY_162_BUDGET)
        decomp, _ = unt_lz.decompress(raw)
        if len(decomp) == UNCOMPRESSED_TIM_SIZE and decomp[:8] == b"\x10\x00\x00\x00\x09\x00\x00\x00":
            clut_len = struct.unpack_from("<I", decomp, 8)[0]
            if clut_len == CLUT_BLOCK_SIZE:
                return bytes(decomp[8 : 8 + CLUT_BLOCK_SIZE])
    except Exception:
        pass
    return None


def get_entry_162_clut(candidate_bins: Sequence[Path | str] | None = None) -> bytes:
    """Retrieve 524-byte CLUT block from candidate disc images or fallback."""
    candidates = list(candidate_bins) if candidate_bins else get_candidate_bins()
    for cand in candidates:
        clut = extract_clut_from_disc(cand)
        if clut is not None:
            return clut
    return FALLBACK_CLUT


def png_to_basyog_162_tim(
    png_path: Path | str,
    candidate_bins: Sequence[Path | str] | None = None,
) -> bytes:
    """Convert user-edited PNG texture atlas to uncompressed 8bpp TIM.

    Args:
        png_path: Path to source 256x256 PNG image.
        candidate_bins: Optional candidate disc images to source the original CLUT.

    Returns:
        Exact 66,080 bytes uncompressed TIM (magic 0x10, flag 0x09).
    """
    path = Path(png_path)
    if not path.is_file():
        raise FileNotFoundError(f"Source PNG not found: {png_path}")

    img = Image.open(path).convert("RGBA")
    if img.size != (TIM_WIDTH, TIM_HEIGHT):
        raise ValueError(
            f"Invalid image dimensions: {img.size}, expected ({TIM_WIDTH}, {TIM_HEIGHT})"
        )

    clut_block = get_entry_162_clut(candidate_bins)
    if len(clut_block) != CLUT_BLOCK_SIZE:
        raise ValueError(f"Invalid CLUT block size: {len(clut_block)}, expected {CLUT_BLOCK_SIZE}")

    # Parse 256 16-bit BGR555 color words
    clut_words = [struct.unpack_from("<H", clut_block, 12 + i * 2)[0] for i in range(256)]
    clut_palette: list[tuple[int, int, int]] = []
    for w in clut_words:
        r = (w & 0x1F) << 3
        g = ((w >> 5) & 0x1F) << 3
        b = ((w >> 10) & 0x1F) << 3
        clut_palette.append((r, g, b))

    # Fast Euclidean color mapper with priority for known active USED_CLUT_INDICES
    used_set = set(USED_CLUT_INDICES)
    color_cache: dict[tuple[int, int, int], int] = {}

    def map_rgb(r: int, g: int, b: int) -> int:
        rgb = (r, g, b)
        if rgb in color_cache:
            return color_cache[rgb]

        # 1. Exact match in USED_CLUT_INDICES
        for idx in USED_CLUT_INDICES:
            if clut_palette[idx] == rgb:
                color_cache[rgb] = idx
                return idx

        # 2. Exact match in any CLUT index
        for idx in range(256):
            if clut_palette[idx] == rgb:
                color_cache[rgb] = idx
                return idx

        # 3. Nearest Euclidean distance (preferring USED_CLUT_INDICES on ties)
        best_idx = 0
        best_dist = float("inf")
        for idx in USED_CLUT_INDICES:
            cr, cg, cb = clut_palette[idx]
            dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = idx

        for idx in range(256):
            if idx in used_set:
                continue
            cr, cg, cb = clut_palette[idx]
            dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if dist < best_dist:
                best_dist = dist
                best_idx = idx

        color_cache[rgb] = best_idx
        return best_idx

    img_arr = np.array(img)
    rgb_data = img_arr[:, :, :3]
    unique_colors = np.unique(rgb_data.reshape(-1, 3), axis=0)

    # Pre-populate cache for all unique colors in the image
    for c in unique_colors:
        map_rgb(int(c[0]), int(c[1]), int(c[2]))

    flat_rgb = rgb_data.reshape(-1, 3)
    mapped_pixels = np.empty(flat_rgb.shape[0], dtype=np.uint8)
    for c in unique_colors:
        key = (int(c[0]), int(c[1]), int(c[2]))
        idx = color_cache[key]
        mask = (
            (flat_rgb[:, 0] == c[0])
            & (flat_rgb[:, 1] == c[1])
            & (flat_rgb[:, 2] == c[2])
        )
        mapped_pixels[mask] = idx

    pixel_bytes = mapped_pixels.tobytes()
    if len(pixel_bytes) != PIXEL_DATA_SIZE:
        raise ValueError(
            f"Pixel data size {len(pixel_bytes)} does not match {PIXEL_DATA_SIZE}"
        )

    # Construct 8bpp TIM binary
    # Magic 0x00000010, Flags 0x00000009 (8bpp with CLUT)
    tim_header = b"\x10\x00\x00\x00\x09\x00\x00\x00"
    # Image Block: 12 bytes header (len=65548, x=0, y=0, w=128 words, h=256 lines)
    image_header = struct.pack(
        "<IHHHH",
        IMAGE_HEADER_SIZE + PIXEL_DATA_SIZE,
        0,
        0,
        TIM_WIDTH // 2,
        TIM_HEIGHT,
    )

    tim = bytearray()
    tim.extend(tim_header)
    tim.extend(clut_block)
    tim.extend(image_header)
    tim.extend(pixel_bytes)

    if len(tim) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(
            f"Assembled TIM size {len(tim)} does not match expected {UNCOMPRESSED_TIM_SIZE}"
        )
    return bytes(tim)


def patch_basyog_162(
    bin_path: Path | str,
    png_path: Path | str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Patch BASYOG.UNT Entry 162 with user-edited texture atlas.

    Args:
        bin_path: Path to target PS1 CD-ROM BIN image.
        png_path: Optional explicit path to PNG texture atlas.
        force: If True, fallback to preview_basyog_162_en.png when RU PNG is missing.
        dry_run: If True, simulate TIM encoding and compression without writing.

    Returns:
        Dictionary describing patch result or skip reason.
    """
    target_bin = Path(bin_path)

    # Resolve PNG path
    resolved_png: Path | None = None
    if png_path is not None:
        explicit_png = Path(png_path)
        if explicit_png.is_file():
            resolved_png = explicit_png
        elif force and DEFAULT_EN_PNG.is_file():
            resolved_png = DEFAULT_EN_PNG
        else:
            rel_path = explicit_png.relative_to(REPO_ROOT) if explicit_png.is_relative_to(REPO_ROOT) else explicit_png
            print(f"{rel_path} not found, skipping")
            return {"status": "skipped", "reason": f"{explicit_png} not found"}
    else:
        if DEFAULT_RU_PNG.is_file():
            resolved_png = DEFAULT_RU_PNG
        elif force and DEFAULT_EN_PNG.is_file():
            resolved_png = DEFAULT_EN_PNG
        else:
            print("data/preview_basyog_162_ru.png not found, skipping")
            return {
                "status": "skipped",
                "reason": "data/preview_basyog_162_ru.png not found",
            }

    # Encode PNG to 8bpp TIM
    tim_bytes = png_to_basyog_162_tim(resolved_png, candidate_bins=[target_bin])

    # Compress with unt_lz mode 1
    compressed = unt_lz.compress(tim_bytes)
    if len(compressed) > ENTRY_162_BUDGET:
        raise ValueError(
            f"Compressed Entry 162 size ({len(compressed)} B) exceeds 4-sector budget ({ENTRY_162_BUDGET} B)"
        )

    # Pad with zeros to complete 4 full Mode 2 Form 1 sectors (8,192 bytes)
    payload = compressed.ljust(ENTRY_162_BUDGET, b"\x00")

    secondary_updated = False
    if not dry_run:
        if not target_bin.is_file():
            raise FileNotFoundError(f"Target disc image not found: {target_bin}")
        replace_extent_in_place(target_bin, ENTRY_162_LBA, payload)

        # Also update secondary disc image if present
        if SECONDARY_BIN.is_file() and SECONDARY_BIN.resolve() != target_bin.resolve():
            replace_extent_in_place(SECONDARY_BIN, ENTRY_162_LBA, payload)
            secondary_updated = True

    return {
        "status": "dry_run" if dry_run else "success",
        "png_path": str(resolved_png),
        "bin_path": str(target_bin),
        "secondary_bin_path": str(SECONDARY_BIN) if secondary_updated else None,
        "tim_size": len(tim_bytes),
        "compressed_size": len(compressed),
        "budget": ENTRY_162_BUDGET,
        "margin": ENTRY_162_BUDGET - len(compressed),
        "lba": ENTRY_162_LBA,
        "sectors": ENTRY_162_SECTORS,
        "dry_run": dry_run,
    }


def verify_basyog_162(bin_path: Path | str) -> dict[str, Any]:
    """Verify Mode 2 Form 1 EDC/ECC and TIM integrity of Entry 162 in disc image.

    Validates:
    1. Complete 4 sectors readable at LBA 239374.
    2. Mode 2 Form 1 EDC and ECC P/Q checksums 100% valid on all 4 sectors.
    3. unt_lz decompression succeeds.
    4. Decompressed payload is valid 8bpp TIM (66,080 bytes, 256x256 image, 256-color CLUT).
    """
    path = Path(bin_path)
    if not path.is_file():
        raise FileNotFoundError(f"Disc image not found: {bin_path}")

    checksums = CdChecksums()
    with path.open("rb") as f:
        for s in range(ENTRY_162_SECTORS):
            lba = ENTRY_162_LBA + s
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            if len(sec) != RAW_SECTOR_SIZE:
                raise ValueError(f"Incomplete sector at LBA {lba}: read {len(sec)} bytes")
            edc = checksums.compute_edc(sec[0x10:0x818])
            if sec[0x818:0x81C] != edc:
                raise ValueError(f"EDC checksum mismatch at LBA {lba}")
            ecc_p = checksums.compute_ecc(sec[0x10:], 86, 24, 2, 86)
            if sec[0x81C:0x8C8] != ecc_p:
                raise ValueError(f"ECC P-parity mismatch at LBA {lba}")
            ecc_q = checksums.compute_ecc(sec[0x10:], 52, 43, 86, 88)
            if sec[0x8C8:0x930] != ecc_q:
                raise ValueError(f"ECC Q-parity mismatch at LBA {lba}")

    extent = read_extent(path, ENTRY_162_LBA, ENTRY_162_BUDGET)
    decomp, consumed = unt_lz.decompress(extent)
    if len(decomp) != UNCOMPRESSED_TIM_SIZE:
        raise ValueError(
            f"Invalid decompressed TIM size: {len(decomp)} (expected {UNCOMPRESSED_TIM_SIZE})"
        )

    magic, flags = struct.unpack_from("<II", decomp, 0)
    if magic != 0x10 or flags != 0x09:
        raise ValueError(f"Invalid TIM header: magic=0x{magic:08X}, flags=0x{flags:08X}")

    clut_len, clut_x, clut_y, clut_w, clut_h = struct.unpack_from("<IHHHH", decomp, 8)
    if clut_len != CLUT_BLOCK_SIZE or clut_x != 0 or clut_y != 480 or clut_w != 256 or clut_h != 1:
        raise ValueError(
            f"Invalid CLUT header: len={clut_len}, x={clut_x}, y={clut_y}, w={clut_w}, h={clut_h}"
        )

    img_offset = 8 + clut_len
    img_len, img_x, img_y, img_w, img_h = struct.unpack_from("<IHHHH", decomp, img_offset)
    if (
        img_len != IMAGE_HEADER_SIZE + PIXEL_DATA_SIZE
        or img_x != 0
        or img_y != 0
        or img_w != TIM_WIDTH // 2
        or img_h != TIM_HEIGHT
    ):
        raise ValueError(
            f"Invalid Image header: len={img_len}, x={img_x}, y={img_y}, w={img_w}, h={img_h}"
        )

    return {
        "status": "ok",
        "bin_path": str(path),
        "lba": ENTRY_162_LBA,
        "sectors": ENTRY_162_SECTORS,
        "compressed_size": consumed,
        "budget": ENTRY_162_BUDGET,
        "margin": ENTRY_162_BUDGET - consumed,
        "tim_size": len(decomp),
        "edc_ecc_valid": True,
        "clut_info": {"x": clut_x, "y": clut_y, "w": clut_w, "h": clut_h},
        "image_info": {"x": img_x, "y": img_y, "w": img_w, "h": img_h},
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch character tabs and status UI texture atlas (BASYOG.UNT Entry 162) for Slayers Royal (PS1)."
    )
    default_bin = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
    if not default_bin.is_file():
        fallback_bin = REPO_ROOT / "downloads" / "sr.bin"
        if fallback_bin.is_file():
            default_bin = fallback_bin
        else:
            default_bin = REPO_ROOT / "build" / "en_patched" / "sr_patched.bin"

    parser.add_argument(
        "--bin",
        type=Path,
        default=default_bin,
        help=f"Path to target PS1 CD-ROM BIN image (default: {default_bin})",
    )
    parser.add_argument(
        "--png",
        type=Path,
        default=None,
        help="Path to user-edited PNG texture atlas (default: data/preview_basyog_162_ru.png)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force patching using fallback English PNG if Russian PNG is missing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify BASYOG.UNT Entry 162 at LBA 239374 in target disc image",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Encode and compress without modifying disc image",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.verify:
        try:
            result = verify_basyog_162(args.bin)
            print(
                f"[VERIFY OK] BASYOG.UNT Entry 162 at LBA {ENTRY_162_LBA}..{ENTRY_162_LBA + ENTRY_162_SECTORS - 1}:"
            )
            print(
                f"  - Compressed stream: {result['compressed_size']:,} bytes (budget: {ENTRY_162_BUDGET:,} bytes)"
            )
            print(
                f"  - Decompressed TIM: {result['tim_size']:,} bytes (8bpp 256x256, 256-color CLUT)"
            )
            print(f"  - EDC/ECC checksums valid: {result['edc_ecc_valid']}")
            return 0
        except Exception as exc:
            print(f"[VERIFY FAILED] Verification failed: {exc}", file=sys.stderr)
            return 1

    result = patch_basyog_162(
        bin_path=args.bin,
        png_path=args.png,
        force=args.force,
        dry_run=args.dry_run,
    )
    if result.get("status") == "skipped":
        # Report waiting without breaking build
        return 0
    elif result.get("status") in ("success", "dry_run"):
        action = "Validated (dry-run)" if args.dry_run else "Patched"
        print(f"[{action}] BASYOG.UNT Entry 162:")
        print(f"  - Source PNG: {result.get('png_path')}")
        print(
            f"  - Compressed: {result.get('compressed_size'):,} bytes / budget: {result.get('budget'):,} bytes (margin: {result.get('margin'):,} bytes)"
        )
        if not args.dry_run:
            print(f"  - Injected to: {result.get('bin_path')} at LBA {result.get('lba')}")
            if result.get("secondary_bin_path"):
                print(f"  - Secondary disc updated: {result.get('secondary_bin_path')}")
        return 0
    else:
        print(f"[ERROR] Failed to patch: {result}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
