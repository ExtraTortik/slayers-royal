#!/usr/bin/env python3
"""Slayers Royal (PS1) - Title Logo Patcher.

Replaces original Japanese title screen logo ("スレイヤーズ ろいやる")
with the Russian stylized logo ("РУБАКИ КОРОЛЕВСКИЕ") from user artwork
or renpy_extracted/.

Architecture & Technical Specifications:
- Target Archive: PROG.UNT Entry 314 (0x13A), LBA 232763..233104 (342 sectors).
- Sprite Storage Format on CD-ROM & in RAM/VRAM:
  1. Part 1 ("РУБА" / "スレイ"):
     - Starts at LBA 232865, offset 0x4E in user sector.
     - Dimensions: 136 x 54 px (68 bytes/row * 54 rows = 3672 bytes).
     - Sector layout: LBA 232865 (1970 bytes: 0x4E..0x800) + LBA 232866 (1702 bytes: 0x00..0x6A6).
     - RAM offset: 0x134AAC.
     - VRAM position: Texpage 8 (X=512 words = 1024 bytes), Y=0..54.
     - Uses CLUT 0 at VRAM (0, 511) (Yellow/Orange fill with Red border).
  2. Part 2 ("КИ" / "ヤーズ"):
     - Starts at LBA 232866, offset 0x724 in user sector.
     - Dimensions: 136 x 54 px (68 bytes/row * 54 rows = 3672 bytes).
     - Sector layout: LBA 232866 (220 bytes: 0x724..0x800) + LBA 232867 (2048 bytes) + LBA 232868 (1404 bytes: 0x00..0x57C).
     - RAM offset: 0x1357C0.
     - VRAM position: Texpage 9 (X=576 words = 1152 bytes), Y=0..54.
     - Uses CLUT 0 at VRAM (0, 511).
  3. Subtitle ("КОРОЛЕВСКИЕ" / "ろいやる"):
     - Starts at LBA 232951, offset 0x798 in user sector.
     - Dimensions: 176 x 43 px (88 bytes/row * 43 rows = 3784 bytes).
     - Sector layout: LBA 232951 (104 bytes: 0x798..0x800) + LBA 232952 (2048 bytes) + LBA 232953 (1632 bytes: 0x00..0x660).
     - RAM offset: 0x160264.
     - VRAM position: Texpage 8 (X=512 words = 1024 bytes), Y=112..155.
     - Uses CLUT 1 at VRAM (16, 511) (Royal Blue fill with White/Red border).
- Automatic EDC/ECC regeneration (Mode 2 Form 1, 2352 bytes/sector across all 7 sectors).
- Automatic DuckStation savestate VRAM/RAM synchronization (~/.local/share/duckstation/savestates/).
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

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

DEFAULT_ORIG_BIN = REPO_ROOT / "downloads" / "sr.bin"
DEFAULT_TARGET_BIN = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_PATCH_REPO_BIN = REPO_ROOT / "patch_repo" / "localization-output" / "ru" / "slayers_royal_ru.bin"
DEFAULT_SAVESTATES_DIR = Path(os.path.expanduser("~/.local/share/duckstation/savestates"))
DEFAULT_PREVIEW_PATH = REPO_ROOT / "data" / "preview_title_logo_ru.png"
DEFAULT_CUSTOM_DIR = REPO_ROOT / "data" / "custom_title_logo"
DEFAULT_LOGO_RU_PATH = REPO_ROOT / "renpy_extracted" / "game" / "gui" / "menu_assets" / "logo_ru.png"

PATCHED_SECTORS = [232865, 232866, 232867, 232868, 232951, 232952, 232953]

# Hardcoded PS1 VRAM CLUT palettes (16 colors RGB)
CLUT0_RGB = [
    (248, 216, 0), (240, 184, 8), (232, 152, 24), (232, 120, 32),
    (224, 88, 48), (216, 56, 64), (232, 24, 48), (184, 24, 40),
    (144, 24, 32), (96, 24, 24), (0, 248, 0), (112, 184, 96),
    (168, 216, 152), (224, 232, 224), (0, 0, 0), (248, 248, 248),
]

CLUT1_RGB = [
    (240, 184, 200), (240, 144, 160), (232, 104, 120), (232, 64, 80),
    (232, 24, 48), (184, 24, 40), (144, 24, 32), (96, 24, 24),
    (240, 248, 248), (184, 224, 232), (144, 192, 216), (96, 168, 200),
    (64, 136, 176), (24, 96, 160), (168, 168, 168), (16, 16, 16),
]


def quantize_to_palette(img_rgba: Image.Image, palette_rgb: list[tuple[int, int, int]]) -> np.ndarray:
    """Quantize RGBA image to 4bpp (0..15) palette indices."""
    w, h = img_rgba.size
    data = np.array(img_rgba)
    rgb = data[:, :, :3]
    alpha = data[:, :, 3]

    indices = np.zeros((h, w), dtype=np.uint8)
    pal_array = np.array(palette_rgb, dtype=np.int32)

    for y in range(h):
        for x in range(w):
            if alpha[y, x] < 50:
                indices[y, x] = 0
            else:
                c = rgb[y, x].astype(np.int32)
                dists = np.sum((pal_array[1:] - c) ** 2, axis=1)
                best_idx = 1 + int(np.argmin(dists))
                indices[y, x] = best_idx
    return indices


def indices_to_bytes(indices: np.ndarray) -> bytes:
    """Pack 4bpp indices into raw PS1 bytes (2 pixels per byte, low nibble first)."""
    h, w = indices.shape
    if w % 2 != 0:
        raise ValueError(f"Width must be even, got {w}")
    raw = bytearray()
    for y in range(h):
        for x in range(0, w, 2):
            p0 = indices[y, x] & 0x0F
            p1 = indices[y, x + 1] & 0x0F
            raw.append(p0 | (p1 << 4))
    return bytes(raw)


def extract_and_render_sprites(
    top_path: Path | str | None = None,
    bottom_path: Path | str | None = None,
) -> tuple[bytes, bytes, bytes, Image.Image]:
    """Load user artwork or fallback logo, quantize to hardware palettes, and generate preview."""
    # Find top artwork
    p_top = None
    candidates_top = [
        Path(top_path) if top_path else None,
        REPO_ROOT / "НАДПИСЬ РУБАКИ_272x54.png",
        DEFAULT_CUSTOM_DIR / "title_logo_top_272x54.png",
    ]
    for c in candidates_top:
        if c and c.is_file():
            p_top = c
            break

    # Find bottom artwork
    p_bot = None
    candidates_bot = [
        Path(bottom_path) if bottom_path else None,
        REPO_ROOT / "НАДПИСЬ КОРОЛЕВСКИЕ_176x43.png",
        DEFAULT_CUSTOM_DIR / "title_logo_bottom_176x43.png",
    ]
    for c in candidates_bot:
        if c and c.is_file():
            p_bot = c
            break

    if p_top and p_bot:
        top_img = Image.open(p_top).convert("RGBA")
        bbox_t = top_img.getbbox()
        if bbox_t and (bbox_t[2] - bbox_t[0] < 272):
            pure_t = top_img.crop(bbox_t)
            canvas_t = Image.new("RGBA", (272, 54), (0, 0, 0, 0))
            x_pos = max(0, (272 - pure_t.width) // 2)
            y_pos = max(0, (54 - pure_t.height) // 2)
            canvas_t.paste(pure_t, (x_pos, y_pos))
            top_img = canvas_t
        elif top_img.size != (272, 54):
            top_img = top_img.resize((272, 54), Image.Resampling.LANCZOS)
        p1_img = top_img.crop((0, 0, 136, 54))
        p2_img = top_img.crop((136, 0, 272, 54))

        bot_img = Image.open(p_bot).convert("RGBA")
        if bot_img.size != (176, 43):
            bot_img = bot_img.resize((176, 43), Image.Resampling.LANCZOS)
    else:
        # Fallback to pure extraction from logo_ru.png
        logo = Image.open(DEFAULT_LOGO_RU_PATH).convert("RGBA")
        w_orig, h_orig = logo.size
        arr = np.array(logo)
        rubaki_mask = (arr[:, :, 3] > 50) & (arr[:, :, 0] > 35) & (np.arange(h_orig)[:, None] <= 245)
        rubaki_arr = arr.copy()
        rubaki_arr[~rubaki_mask] = 0
        crop_r = Image.fromarray(rubaki_arr).crop(Image.fromarray(rubaki_arr).getbbox())

        canvas_rubaki = Image.new("RGBA", (272, 54), (0, 0, 0, 0))
        scaled_r = crop_r.resize((272, 54), Image.Resampling.LANCZOS)
        canvas_rubaki.paste(scaled_r, (0, 0))
        p1_img = canvas_rubaki.crop((0, 0, 136, 54))
        p2_img = canvas_rubaki.crop((136, 0, 272, 54))

        # Bottom
        crop_k_pure = logo.crop((202, 267, 812, 358))
        arr_k = np.array(crop_k_pure)
        blue_m = (arr_k[:, :, 3] > 50) & (arr_k[:, :, 2] > 100) & (arr_k[:, :, 0] < 110)
        white_m = (arr_k[:, :, 3] > 50) & (arr_k[:, :, 0] > 185) & (arr_k[:, :, 1] > 185) & (arr_k[:, :, 2] > 185)
        core_text_m = blue_m | white_m

        h_k, w_k = core_text_m.shape
        allowed_zone = core_text_m.copy()
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                if dx * dx + dy * dy <= 9:
                    y1 = max(0, dy)
                    y2 = min(h_k, h_k + dy)
                    x1 = max(0, dx)
                    x2 = min(w_k, w_k + dx)
                    sy1 = max(0, -dy)
                    sy2 = min(h_k, h_k - dy)
                    sx1 = max(0, -dx)
                    sx2 = min(w_k, w_k - dx)
                    allowed_zone[y1:y2, x1:x2] |= core_text_m[sy1:sy2, sx1:sx2]

        final_k_arr = arr_k.copy()
        final_k_arr[~allowed_zone] = 0
        is_black = (final_k_arr[:, :, 0] < 35) & (final_k_arr[:, :, 1] < 35) & (final_k_arr[:, :, 2] < 35)
        final_k_arr[is_black] = 0

        crop_k_iso = Image.fromarray(final_k_arr)
        pure_k_trimmed = crop_k_iso.crop(crop_k_iso.getbbox() or (0, 0, crop_k_iso.width, crop_k_iso.height))

        bot_img = Image.new("RGBA", (176, 43), (0, 0, 0, 0))
        scaled_k = pure_k_trimmed.resize((164, 28), Image.Resampling.LANCZOS)
        bot_img.paste(scaled_k, (10, 12))

    # Quantize
    ind_p1 = quantize_to_palette(p1_img, CLUT0_RGB)
    ind_p2 = quantize_to_palette(p2_img, CLUT0_RGB)
    ind_sub = quantize_to_palette(bot_img, CLUT1_RGB)

    raw_p1 = indices_to_bytes(ind_p1)
    raw_p2 = indices_to_bytes(ind_p2)
    raw_sub = indices_to_bytes(ind_sub)

    # Generate composite preview (320x240)
    preview = Image.new("RGBA", (320, 240), (20, 24, 20, 255))
    opt147 = REPO_ROOT / "data" / "title_screen_dump" / "opt_147_320x224_uncompressed.png"
    if opt147.is_file():
        bg = Image.open(opt147).convert("RGBA")
        preview.paste(bg, (0, 8))

    # Reconstruct RGBA sprites from indexed data
    p1_rgba = Image.new("RGBA", (136, 54))
    for y in range(54):
        for x in range(136):
            idx = ind_p1[y, x]
            c = CLUT0_RGB[idx] if idx != 0 else (0, 0, 0)
            a = 0 if idx == 0 else 255
            p1_rgba.putpixel((x, y), (*c, a))

    p2_rgba = Image.new("RGBA", (136, 54))
    for y in range(54):
        for x in range(136):
            idx = ind_p2[y, x]
            c = CLUT0_RGB[idx] if idx != 0 else (0, 0, 0)
            a = 0 if idx == 0 else 255
            p2_rgba.putpixel((x, y), (*c, a))

    sub_rgba = Image.new("RGBA", (176, 43))
    for y in range(43):
        for x in range(176):
            idx = ind_sub[y, x]
            c = CLUT1_RGB[idx] if idx != 0 else (0, 0, 0)
            a = 0 if idx == 0 else 255
            sub_rgba.putpixel((x, y), (*c, a))

    # Exact on-screen hardware positions (SPRT commands)
    preview.alpha_composite(p1_rgba, (24, 52))
    preview.alpha_composite(p2_rgba, (160, 52))
    preview.alpha_composite(sub_rgba, (64, 89))

    return raw_p1, raw_p2, raw_sub, preview


def patch_sector_data(f, lba: int, offset_in_user: int, payload: bytes, chk: CdChecksums) -> None:
    """Inject payload into 2048-byte user data and repair Mode 2 Form 1 EDC/ECC."""
    f.seek(lba * RAW_SECTOR_SIZE)
    sector = bytearray(f.read(RAW_SECTOR_SIZE))
    user_start = USER_DATA_OFFSET + offset_in_user
    sector[user_start : user_start + len(payload)] = payload
    chk.repair_mode2_form1(sector)
    f.seek(lba * RAW_SECTOR_SIZE)
    f.write(sector)


def patch_disc_title_logo(
    bin_path: Path | str,
    raw_p1: bytes,
    raw_p2: bytes,
    raw_sub: bytes,
) -> list[int]:
    """Patch PROG.UNT Entry 314 sectors on CD-ROM with Mode 2 Form 1 EDC/ECC repair."""
    bp = Path(bin_path)
    if not bp.is_file():
        raise FileNotFoundError(f"Disc image not found: {bp}")

    chk = CdChecksums()

    # Part 1 (3672 bytes): LBA 232865 offset 0x4E (1970 bytes) + LBA 232866 (1702 bytes)
    p1_s1 = raw_p1[:1970]
    p1_s2 = raw_p1[1970:]

    # Part 2 (3672 bytes): LBA 232866 offset 0x724 (220 bytes) + LBA 232867 (2048 bytes) + LBA 232868 (1404 bytes)
    p2_s1 = raw_p2[:220]
    p2_s2 = raw_p2[220 : 220 + 2048]
    p2_s3 = raw_p2[220 + 2048 :]

    # Subtitle (3784 bytes): LBA 232951 offset 0x798 (104 bytes) + LBA 232952 (2048 bytes) + LBA 232953 (1632 bytes)
    sub_s1 = raw_sub[:104]
    sub_s2 = raw_sub[104 : 104 + 2048]
    sub_s3 = raw_sub[104 + 2048 :]

    with bp.open("r+b") as f:
        # Part 1
        patch_sector_data(f, 232865, 0x4E, p1_s1, chk)
        patch_sector_data(f, 232866, 0x00, p1_s2, chk)
        # Part 2
        patch_sector_data(f, 232866, 0x724, p2_s1, chk)
        patch_sector_data(f, 232867, 0x00, p2_s2, chk)
        patch_sector_data(f, 232868, 0x00, p2_s3, chk)
        # Subtitle
        patch_sector_data(f, 232951, 0x798, sub_s1, chk)
        patch_sector_data(f, 232952, 0x00, sub_s2, chk)
        patch_sector_data(f, 232953, 0x00, sub_s3, chk)

    return list(PATCHED_SECTORS)


def extract_orig_sprites(orig_bin: Path | str = DEFAULT_ORIG_BIN) -> tuple[bytes, bytes, bytes]:
    """Extract original Japanese title logo sprites from orig_bin."""
    op = Path(orig_bin)
    with op.open("rb") as f:
        # Part 1 (3672 bytes): LBA 232865 offset 0x4E (1970 bytes) + LBA 232866 (1702 bytes)
        f.seek(232865 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x4E)
        p1_1 = f.read(1970)
        f.seek(232866 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        p1_2 = f.read(1702)
        raw_p1 = p1_1 + p1_2

        # Part 2 (3672 bytes): LBA 232866 offset 0x724 (220 bytes) + LBA 232867 (2048 bytes) + LBA 232868 (1404 bytes)
        f.seek(232866 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x724)
        p2_1 = f.read(220)
        f.seek(232867 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        p2_2 = f.read(2048)
        f.seek(232868 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        p2_3 = f.read(1404)
        raw_p2 = p2_1 + p2_2 + p2_3

        # Subtitle (3784 bytes): LBA 232951 offset 0x798 (104 bytes) + LBA 232952 (2048 bytes) + LBA 232953 (1632 bytes)
        f.seek(232951 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x798)
        sub_1 = f.read(104)
        f.seek(232952 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        sub_2 = f.read(2048)
        f.seek(232953 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        sub_3 = f.read(1632)
        raw_sub = sub_1 + sub_2 + sub_3

    return raw_p1, raw_p2, raw_sub


def restore_orig_title_logo(
    target_bin: Path | str,
    orig_bin: Path | str = DEFAULT_ORIG_BIN,
) -> list[int]:
    """Restore the 7 title logo sectors in target_bin from orig_bin and recalculate EDC/ECC."""
    target_p = Path(target_bin)
    orig_p = Path(orig_bin)
    if not target_p.is_file():
        raise FileNotFoundError(f"Target disc image not found: {target_p}")
    if not orig_p.is_file():
        raise FileNotFoundError(f"Original disc image not found: {orig_p}")

    if replace_extent_in_place is not None and read_extent is not None:
        chunk1_data = read_extent(orig_p, 232865, 4 * USER_DATA_SIZE)
        replace_extent_in_place(target_p, 232865, chunk1_data)

        chunk2_data = read_extent(orig_p, 232951, 3 * USER_DATA_SIZE)
        replace_extent_in_place(target_p, 232951, chunk2_data)
    else:
        chk = CdChecksums()
        with orig_p.open("rb") as f_orig, target_p.open("r+b") as f_target:
            for lba in PATCHED_SECTORS:
                f_orig.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
                payload = f_orig.read(USER_DATA_SIZE)
                patch_sector_data(f_target, lba, 0, payload, chk)

    return list(PATCHED_SECTORS)

def sync_savestate_title_logo(
    sav_path: Path | str,
    raw_p1: bytes,
    raw_p2: bytes,
    raw_sub: bytes,
    preview_fb: Image.Image | None = None,
    backup: bool = True,
) -> bool:
    """Synchronize title logo in DuckStation savestate (RAM + VRAM + Framebuffers)."""
    sp = Path(sav_path)
    if not sp.is_file():
        return False

    data = sp.read_bytes()
    magics = []
    p = 0
    while True:
        idx = data.find(b"\x28\xb5\x2f\xfd", p)
        if idx == -1:
            break
        magics.append(idx)
        p = idx + 4

    if not magics:
        return False

    stream_off = magics[1] if len(magics) >= 2 else magics[0]
    try:
        res = subprocess.run(["zstd", "-d"], input=data[stream_off:], capture_output=True, check=True)
        decomp = bytearray(res.stdout)
    except Exception:
        return False

    # 1. Update RAM sprite buffers
    updated = False
    ram_start = -1
    p = 0
    while p < len(decomp) - 8:
        tag_len = int.from_bytes(decomp[p : p + 4], "little")
        if 1 <= tag_len <= 32 and p + 4 + tag_len + 4 <= len(decomp):
            name = decomp[p + 4 : p + 4 + tag_len]
            if name == b"Bus":
                ram_start = p + 4 + tag_len + 4
                break
        p += 1

    if ram_start != -1:
        if ram_start + 0x134AAC + len(raw_p1) <= len(decomp):
            decomp[ram_start + 0x134AAC : ram_start + 0x134AAC + len(raw_p1)] = raw_p1
            updated = True
        if ram_start + 0x1357C0 + len(raw_p2) <= len(decomp):
            decomp[ram_start + 0x1357C0 : ram_start + 0x1357C0 + len(raw_p2)] = raw_p2
            updated = True
        if ram_start + 0x160264 + len(raw_sub) <= len(decomp):
            decomp[ram_start + 0x160264 : ram_start + 0x160264 + len(raw_sub)] = raw_sub
            updated = True

    # Also update direct RAM offsets if decomp is flat RAM
    if len(decomp) >= 0x200000:
        if len(decomp) >= 0x134AAC + len(raw_p1):
            decomp[0x134AAC : 0x134AAC + len(raw_p1)] = raw_p1
            updated = True
        if len(decomp) >= 0x1357C0 + len(raw_p2):
            decomp[0x1357C0 : 0x1357C0 + len(raw_p2)] = raw_p2
        if len(decomp) >= 0x160264 + len(raw_sub):
            decomp[0x160264 : 0x160264 + len(raw_sub)] = raw_sub

    # 2. Update VRAM texture atlas and zero out mask slots
    idx_vram = decomp.find(b"VRAM")
    if idx_vram != -1 and idx_vram + 8 + 1048576 <= len(decomp):
        vram_start = idx_vram + 8
        # Part 1 into VRAM: Texpage 8 (X=512 words = 1024 bytes in scanline)
        for r in range(54):
            v_start = vram_start + r * 2048 + 512 * 2
            decomp[v_start : v_start + 68] = raw_p1[r * 68 : (r + 1) * 68]
        # Clear rows 54..55 of Part 1 (hardware sprite height is 56)
        for r in range(54, 56):
            v_start = vram_start + r * 2048 + 512 * 2
            decomp[v_start : v_start + 68] = b"\x00" * 68

        # Part 2 into VRAM: Texpage 9 (X=576 words = 1152 bytes in scanline)
        for r in range(54):
            v_start = vram_start + r * 2048 + 576 * 2
            decomp[v_start : v_start + 68] = raw_p2[r * 68 : (r + 1) * 68]
        # Clear rows 54..55 of Part 2
        for r in range(54, 56):
            v_start = vram_start + r * 2048 + 576 * 2
            decomp[v_start : v_start + 68] = b"\x00" * 68

        # Subtitle into VRAM: Texpage 8 (X=512 words = 1024 bytes in scanline, Y=112..155)
        for r in range(43):
            v_start = vram_start + (112 + r) * 2048 + 512 * 2
            decomp[v_start : v_start + 88] = raw_sub[r * 88 : (r + 1) * 88]
        # Clear rows 155..160 of Subtitle (hardware sprite height is 48)
        for r in range(43, 48):
            v_start = vram_start + (112 + r) * 2048 + 512 * 2
            decomp[v_start : v_start + 88] = b"\x00" * 88
        # Zero out shadow / mask slots in VRAM:
        for y in range(55, 112):
            v_s = vram_start + y * 2048 + 512 * 2
            decomp[v_s : v_s + 128 * 2] = b"\x00" * 256

        for y in range(156, 210):
            v_s = vram_start + y * 2048 + 512 * 2
            decomp[v_s : v_s + 128 * 2] = b"\x00" * 256

        # 3. Clean composed framebuffers in VRAM
        if preview_fb:
            fb_rgb = preview_fb.convert("RGB")
            for y in range(240):
                for x in range(320):
                    r_c, g_c, b_c = fb_rgb.getpixel((x, y))
                    w = ((b_c >> 3) << 10) | ((g_c >> 3) << 5) | (r_c >> 3)
                    idx0 = vram_start + (y * 1024 + x) * 2
                    decomp[idx0 : idx0 + 2] = struct.pack("<H", w)
                    idx1 = vram_start + ((256 + y) * 1024 + x) * 2
                    decomp[idx1 : idx1 + 2] = struct.pack("<H", w)

        updated = True

    if updated:
        if backup:
            bak = sp.with_suffix(".sav.bak")
            if not bak.exists():
                shutil.copy2(sp, bak)
        res_c = subprocess.run(["zstd", "-3"], input=bytes(decomp), capture_output=True, check=True)
        sp.write_bytes(data[:stream_off] + res_c.stdout)
        return True

    return False


def verify_disc_title_logo(bin_path: Path | str, raw_p1: bytes, raw_p2: bytes, raw_sub: bytes) -> bool:
    """Verify that all 7 sectors on CD-ROM match the Russian sprite payloads and have valid EDC/ECC."""
    bp = Path(bin_path)
    if not bp.is_file():
        return False

    chk = CdChecksums()
    with bp.open("rb") as f:
        for lba in PATCHED_SECTORS:
            f.seek(lba * RAW_SECTOR_SIZE)
            sec = f.read(RAW_SECTOR_SIZE)
            if sec[0x818:0x81C] != chk.compute_edc(sec[0x10:0x818]):
                return False
            if sec[0x81C:0x8C8] != chk.compute_ecc(sec[0x10:], 86, 24, 2, 86):
                return False
            if sec[0x8C8:0x930] != chk.compute_ecc(sec[0x10:], 52, 43, 86, 88):
                return False

        # Check payload bytes
        f.seek(232865 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x4E)
        if f.read(1970) != raw_p1[:1970]:
            return False
        f.seek(232866 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        if f.read(1702) != raw_p1[1970:]:
            return False
        f.seek(232866 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x724)
        if f.read(220) != raw_p2[:220]:
            return False
        f.seek(232867 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        if f.read(2048) != raw_p2[220 : 220 + 2048]:
            return False
        f.seek(232868 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        if f.read(1404) != raw_p2[220 + 2048:]:
            return False
        f.seek(232951 * RAW_SECTOR_SIZE + USER_DATA_OFFSET + 0x798)
        if f.read(104) != raw_sub[:104]:
            return False
        f.seek(232952 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        if f.read(2048) != raw_sub[104 : 104 + 2048]:
            return False
        f.seek(232953 * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        if f.read(1632) != raw_sub[104 + 2048:]:
            return False

    return True

def verify_orig_title_logo(
    bin_path: Path | str,
    orig_bin: Path | str = DEFAULT_ORIG_BIN,
) -> bool:
    """Verify that all 7 sectors on CD-ROM match the original Japanese disc and have valid EDC/ECC."""
    bp = Path(bin_path)
    op = Path(orig_bin)
    if not bp.is_file() or not op.is_file():
        return False

    chk = CdChecksums()
    with bp.open("rb") as f_target, op.open("rb") as f_orig:
        for lba in PATCHED_SECTORS:
            f_target.seek(lba * RAW_SECTOR_SIZE)
            sec = f_target.read(RAW_SECTOR_SIZE)
            if sec[0x818:0x81C] != chk.compute_edc(sec[0x10:0x818]):
                return False
            if sec[0x81C:0x8C8] != chk.compute_ecc(sec[0x10:], 86, 24, 2, 86):
                return False
            if sec[0x8C8:0x930] != chk.compute_ecc(sec[0x10:], 52, 43, 86, 88):
                return False

            f_orig.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            orig_user = f_orig.read(USER_DATA_SIZE)
            target_user = sec[USER_DATA_OFFSET : USER_DATA_OFFSET + USER_DATA_SIZE]
            if orig_user != target_user:
                return False

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch title screen logo in Slayers Royal (PS1)")
    parser.add_argument("--bin", type=Path, default=DEFAULT_TARGET_BIN, help="Path to target disc image")
    parser.add_argument("--orig", "--orig-bin", dest="orig_bin", type=Path, default=DEFAULT_ORIG_BIN, help="Path to original Japanese disc image")
    parser.add_argument("--restore-orig", "--japanese", dest="restore_orig", action="store_true", help="Restore original Japanese title logo from original disc")
    parser.add_argument("--top", type=Path, default=None, help="Path to custom top logo PNG (272x54)")
    parser.add_argument("--bottom", type=Path, default=None, help="Path to custom bottom logo PNG (176x43)")
    parser.add_argument("--savestates", type=Path, default=DEFAULT_SAVESTATES_DIR, help="DuckStation savestates directory")
    parser.add_argument("--verify", action="store_true", help="Verify patched logo on disc image")
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW_PATH, help="Path to save preview image")
    parser.add_argument("--dry-run", action="store_true", help="Do not modify disc image")

    args = parser.parse_args()

    if args.restore_orig:
        targets = [args.bin]
        if DEFAULT_PATCH_REPO_BIN.is_file() and DEFAULT_PATCH_REPO_BIN.resolve() != args.bin.resolve():
            targets.append(DEFAULT_PATCH_REPO_BIN)

        if args.dry_run:
            print("[*] Dry-run mode: no changes written to disc.")
            return 0

        for target in targets:
            patched_lbas = restore_orig_title_logo(target, args.orig_bin)
            print(f"[✓] Restored Japanese title logo on {target.name}: {len(patched_lbas)} sectors restored (LBAs: {patched_lbas})")

        # Sync DuckStation savestates if available
        if args.savestates and args.savestates.is_dir():
            orig_p1, orig_p2, orig_sub = extract_orig_sprites(args.orig_bin)
            synced = 0
            for s in args.savestates.glob("SLPS-01363_*.sav"):
                if sync_savestate_title_logo(s, orig_p1, orig_p2, orig_sub, preview_fb=None):
                    synced += 1
            print(f"[✓] Synchronized {synced} DuckStation savestate(s) with Japanese logo")

        return 0

    if args.verify:
        if args.orig_bin and args.orig_bin.is_file() and verify_orig_title_logo(args.bin, args.orig_bin):
            print(f"[✓] Title logo verification SUCCESSFUL (Japanese original) on {args.bin}")
            return 0

        raw_p1, raw_p2, raw_sub, preview = extract_and_render_sprites(args.top, args.bottom)
        ok = verify_disc_title_logo(args.bin, raw_p1, raw_p2, raw_sub)
        if ok:
            print(f"[✓] Title logo verification SUCCESSFUL (Russian patched) on {args.bin}")
            return 0
        else:
            print(f"[✗] Title logo verification FAILED on {args.bin}")
            return 1

    raw_p1, raw_p2, raw_sub, preview = extract_and_render_sprites(args.top, args.bottom)
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        preview.save(args.preview)
        print(f"[✓] Title logo preview saved to {args.preview}")
    if args.dry_run:
        print("[*] Dry-run mode: no changes written to disc.")
        return 0

    targets = [args.bin]
    if DEFAULT_PATCH_REPO_BIN.is_file() and DEFAULT_PATCH_REPO_BIN.resolve() != args.bin.resolve():
        targets.append(DEFAULT_PATCH_REPO_BIN)

    for target in targets:
        patched_lbas = patch_disc_title_logo(target, raw_p1, raw_p2, raw_sub)
        print(f"[✓] Patched title logo on {target.name}: {len(patched_lbas)} sectors updated (LBAs: {patched_lbas})")

    # Sync DuckStation savestates if available
    if args.savestates and args.savestates.is_dir():
        synced = 0
        for s in args.savestates.glob("SLPS-01363_*.sav"):
            if sync_savestate_title_logo(s, raw_p1, raw_p2, raw_sub, preview_fb=preview):
                synced += 1
        print(f"[✓] Synchronized {synced} DuckStation savestate(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
