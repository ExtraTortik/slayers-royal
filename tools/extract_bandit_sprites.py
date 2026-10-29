#!/usr/bin/env python3
"""
Slayers Royal (PS1) - Minigame "Bandit Bullying" (Отстрел бандитов)
Sprite Extraction & Reverse-Engineering Pipeline.

Extracts SMINI.UNT Entry 4 (LBA 223787 + 1317, 393216 bytes).
- Unpacks 23 files from PMA container (Files 00..07: TIM, Files 08..22: AMA).
- Decodes all 8 TIM files with all CLUT palettes into PNG.
- Parses all AMA files (08..22), decodes frames, quads, and timelines.
- Builds composite frames, individual quads, and preview animated GIFs.
- Crops HUD digits, labels, status banners, Lina portraits, background, effects.
- Organizes assets into build/bandit_extraction/user_preparation/ and
  /home/samvel/Downloads/Telegram Desktop/Slayers Royal/BANDIT_RAW_SPRITES/.
- Generates detailed technical report in build/bandit_extraction/sprites_report.md.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DISC_BIN_RU = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DISC_BIN_ORIG = REPO_ROOT / "downloads" / "sr.bin"

BUILD_DIR = REPO_ROOT / "build" / "bandit_extraction"
RAW_PMA_DIR = BUILD_DIR / "raw_pma"
RAW_TIMS_DIR = BUILD_DIR / "raw_tims_png"
COMPOSITE_DIR = BUILD_DIR / "composite_frames"
INDIVIDUAL_QUADS_DIR = BUILD_DIR / "individual_quads"
USER_PREP_DIR = BUILD_DIR / "user_preparation"
REPORT_FILE = BUILD_DIR / "sprites_report.md"

TARGET_RENPY_DIR = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/BANDIT_RAW_SPRITES")

RAW_SECTOR_SIZE = 2352
USER_DATA_SIZE = 2048
SMINI_DEFAULT_LBA = 223787
ENTRY_4_INDEX = 4
ENTRY_4_START_SECTOR = 1317
ENTRY_4_SECTOR_COUNT = 192
ENTRY_4_BYTE_SIZE = ENTRY_4_SECTOR_COUNT * USER_DATA_SIZE  # 393216 bytes


def get_disc_path() -> Path:
    if DISC_BIN_RU.is_file():
        return DISC_BIN_RU
    if DISC_BIN_ORIG.is_file():
        return DISC_BIN_ORIG
    raise FileNotFoundError(f"Neither {DISC_BIN_RU} nor {DISC_BIN_ORIG} found.")


def read_smini_entry_4(bin_path: Path) -> bytearray:
    """Read Entry 4 directly from disc image."""
    data = bytearray()
    with bin_path.open("rb") as f:
        for s in range(ENTRY_4_SECTOR_COUNT):
            sector_num = SMINI_DEFAULT_LBA + ENTRY_4_START_SECTOR + s
            f.seek(sector_num * RAW_SECTOR_SIZE + 24)
            chunk = f.read(USER_DATA_SIZE)
            data.extend(chunk)
    if len(data) != ENTRY_4_BYTE_SIZE:
        raise ValueError(f"Expected {ENTRY_4_BYTE_SIZE} bytes, got {len(data)}")
    return data


def unpack_pma(e4_data: bytearray, out_dir: Path) -> List[Tuple[int, int, str]]:
    """Unpack PMA container into raw files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    magic, num_files = struct.unpack_from("<II", e4_data, 0)
    if magic != 0x014D4D50 and magic != 0x504D4101 and e4_data[:4] != b"PMA\x01":
        raise ValueError(f"Invalid PMA magic: {e4_data[:4]}")
    
    offsets = [struct.unpack_from("<I", e4_data, 8 + i * 4)[0] for i in range(num_files)]
    offsets.append(len(e4_data))
    
    file_records = []
    for i in range(num_files):
        start = offsets[i]
        end = offsets[i + 1]
        chunk = e4_data[start:end]
        ext = "tim" if i < 8 else "ama"
        filename = f"file_{i:02d}.{ext}"
        out_path = out_dir / filename
        out_path.write_bytes(chunk)
        file_records.append((start, end - start, filename))
    return file_records


def parse_tim_header(tim_bytes: bytes) -> Dict[str, Any]:
    """Parse PS1 TIM header."""
    if len(tim_bytes) < 8:
        raise ValueError("Buffer too short for TIM")
    magic, flags = struct.unpack_from("<II", tim_bytes, 0)
    if magic != 0x00000010:
        raise ValueError(f"Invalid TIM magic: {magic:#x}")

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


def decode_tim_palettes(tim_bytes: bytes, prefix: str, out_dir: Path) -> Tuple[Dict[str, Any], List[Path]]:
    """Decode TIM with all available CLUT palettes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    info = parse_tim_header(tim_bytes)
    bpp_mode = info["bpp_mode"]
    has_clut = info["has_clut"]
    clut = info["clut"]

    palette_size = 16 if bpp_mode == 0 else 256
    num_palettes = 1
    if has_clut:
        num_palettes = clut["colors"] // palette_size

    w = info["vram_w_words"]
    h = info["height"]
    pix_w = info["pixel_width"]
    pixel_data = tim_bytes[info["image_data_offset"]: info["image_data_offset"] + info["image_data_length"]]

    saved_paths = []
    for pal_idx in range(num_palettes):
        colors = []
        if has_clut:
            clut_data = tim_bytes[clut["offset"]: clut["offset"] + clut["colors"] * 2]
            for i in range(palette_size):
                idx = (pal_idx * palette_size + i) * 2
                c16 = struct.unpack_from("<H", clut_data, idx)[0]
                r = round(((c16 & 0x1F) * 255) / 31)
                g = round((((c16 >> 5) & 0x1F) * 255) / 31)
                b = round((((c16 >> 10) & 0x1F) * 255) / 31)
                
                # In TIM 05 (background), make fully opaque
                if prefix == "tim_05":
                    a = 255
                else:
                    a = 0 if i == 0 else 255
                colors.append((r, g, b, a))
        else:
            colors = [(i, i, i, 255) for i in range(palette_size)]

        img = Image.new("RGBA", (pix_w, h), (0, 0, 0, 0))
        if bpp_mode == 0:  # 4bpp
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
                        c = colors[p] if p < len(colors) else (0, 0, 0, 0)
                        img.putpixel((x_w * 4 + px_idx, y), c)
        elif bpp_mode == 1:  # 8bpp
            for y in range(h):
                for x in range(pix_w):
                    idx = y * pix_w + x
                    if idx >= len(pixel_data):
                        break
                    p = pixel_data[idx]
                    c = colors[p] if p < len(colors) else (0, 0, 0, 0)
                    img.putpixel((x, y), c)

        out_file = out_dir / f"{prefix}_pal{pal_idx:02d}.png"
        img.save(out_file)
        saved_paths.append(out_file)

    return info, saved_paths


def parse_ama(data: bytes, file_idx: int) -> Dict[str, Any]:
    """Parse PS1 AMA animation file."""
    magic, zero, num_frames = struct.unpack_from("<III", data, 0)
    if magic != 0x01414D41:
        raise ValueError(f"Invalid AMA magic: {magic:#x}")
    offset = 12
    frames = []
    for f in range(num_frames):
        num_parts = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        parts = []
        for p in range(num_parts):
            u, v, x, y, w, h, tpage, clut = struct.unpack_from("<hhhhhhHH", data, offset)
            offset += 16
            parts.append({
                "u": u, "v": v, "x": x, "y": y, "w": w, "h": h,
                "tpage": hex(tpage), "clut": hex(clut),
                "raw_tpage": tpage, "raw_clut": clut
            })
        frames.append(parts)

    num_timeline = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    timeline = []
    for t in range(num_timeline):
        flags, duration, frame_idx = struct.unpack_from("<IHH", data, offset)
        offset += 8
        timeline.append({"flags": flags, "duration": duration, "frame_index": frame_idx})

    return {
        "file_idx": file_idx,
        "num_frames": num_frames,
        "frames": frames,
        "num_timeline": num_timeline,
        "timeline": timeline,
    }


def map_tpage_to_tim(tpage: int) -> int:
    """Map PS1 TPAGE register to TIM index (0..7)."""
    tx = (tpage & 0xF) * 64
    ty = ((tpage >> 4) & 1) * 256
    bpp_mode = (tpage >> 7) & 3

    if tx == 320 and ty == 0 and bpp_mode == 0:
        return 0
    elif tx == 384 and ty == 0 and bpp_mode == 0:
        return 1
    elif tx == 448 and ty == 0 and bpp_mode == 1:
        return 2
    elif tx == 704 and ty == 0 and bpp_mode == 1:
        return 3
    elif tx == 640 and ty == 256 and bpp_mode == 1:
        return 4
    elif tx == 448 and ty == 256 and bpp_mode == 1:
        return 5
    elif tx == 320 and ty == 256 and bpp_mode == 1:
        return 6
    elif tx == 960 and ty == 0 and bpp_mode == 0:
        return 7
    return 0


def render_ama_animations(
    amas: Dict[int, Dict[str, Any]],
    raw_tims_dir: Path,
    composite_dir: Path,
    quads_dir: Path,
) -> Dict[int, Dict[str, Any]]:
    """Render composite frames and extract quads for all AMAs."""
    composite_dir.mkdir(parents=True, exist_ok=True)
    quads_dir.mkdir(parents=True, exist_ok=True)

    ama_metadata = {}

    for a_idx, ama in amas.items():
        ama_comp_dir = composite_dir / f"ama_{a_idx:02d}"
        ama_quad_dir = quads_dir / f"ama_{a_idx:02d}"
        ama_comp_dir.mkdir(parents=True, exist_ok=True)
        ama_quad_dir.mkdir(parents=True, exist_ok=True)

        frames = ama["frames"]
        timeline = ama["timeline"]

        # Calculate bounding box of all parts across all frames
        all_xs = [p["x"] for f in frames for p in f]
        all_ys = [p["y"] for f in frames for p in f]
        all_max_xs = [p["x"] + p["w"] for f in frames for p in f]
        all_max_ys = [p["y"] + p["h"] for f in frames for p in f]

        min_x = min(all_xs) if all_xs else 0
        min_y = min(all_ys) if all_ys else 0
        max_x = max(all_max_xs) if all_max_xs else 48
        max_y = max(all_max_ys) if all_max_ys else 64
        bw = max(1, max_x - min_x)
        bh = max(1, max_y - min_y)

        rendered_frames_tight = []
        rendered_frames_screen = []

        # Default palette for TIMs
        # TIM 00: pal 02 for fire/flare arrow, pal 00 for hud
        # TIM 01: pal 00 for explosion
        for f_idx, f in enumerate(frames):
            frame_tight = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            frame_screen = Image.new("RGBA", (320, 224), (0, 0, 0, 0))

            for p_idx, p in enumerate(f):
                tim_idx = map_tpage_to_tim(p["raw_tpage"])
                pal_idx = 0
                if tim_idx == 0:
                    pal_idx = 2  # fire palette for effects
                tim_png = raw_tims_dir / f"tim_{tim_idx:02d}_pal{pal_idx:02d}.png"
                if not tim_png.exists():
                    tim_png = raw_tims_dir / f"tim_{tim_idx:02d}_pal00.png"
                
                with Image.open(tim_png) as tim_img:
                    part_crop = tim_img.crop((p["u"], p["v"], p["u"] + p["w"], p["v"] + p["h"]))
                
                # Save individual quad
                quad_path = ama_quad_dir / f"f{f_idx:02d}_p{p_idx:02d}_u{p['u']}_v{p['v']}_{p['w']}x{p['h']}.png"
                part_crop.save(quad_path)

                # Paste onto tight canvas
                dest_x = p["x"] - min_x
                dest_y = p["y"] - min_y
                frame_tight.paste(part_crop, (dest_x, dest_y), part_crop)

                # Paste onto screen canvas
                if 0 <= p["x"] < 320 and 0 <= p["y"] < 224:
                    frame_screen.paste(part_crop, (p["x"], p["y"]), part_crop)

            tight_path = ama_comp_dir / f"frame_{f_idx:02d}.png"
            screen_path = ama_comp_dir / f"screen_frame_{f_idx:02d}.png"
            frame_tight.save(tight_path)
            frame_screen.save(screen_path)

            rendered_frames_tight.append(frame_tight)
            rendered_frames_screen.append(frame_screen)

        # Generate animated GIF following timeline steps
        gif_frames = []
        durations = []
        for step in timeline:
            f_idx = step["frame_index"]
            dur = step["duration"]
            if f_idx < len(rendered_frames_tight):
                gif_frames.append(rendered_frames_tight[f_idx])
                # Convert duration in ticks (1/60 s) to ms
                dur_ms = max(20, int(dur * 1000 / 60)) if dur < 200 else 400
                durations.append(dur_ms)

        if gif_frames:
            gif_path = ama_comp_dir / f"ama_{a_idx:02d}_preview.gif"
            gif_frames[0].save(
                gif_path,
                save_all=True,
                append_images=gif_frames[1:],
                duration=durations,
                loop=0,
                disposal=2
            )

        ama_metadata[a_idx] = {
            "bbox": (min_x, min_y, max_x, max_y),
            "size": (bw, bh),
            "num_frames": len(frames),
            "num_timeline": len(timeline),
            "tight_paths": [str(ama_comp_dir / f"frame_{i:02d}.png") for i in range(len(frames))],
            "gif_path": str(ama_comp_dir / f"ama_{a_idx:02d}_preview.gif") if gif_frames else None,
        }

    return ama_metadata


def extract_specialized_assets(raw_tims_dir: Path, build_dir: Path) -> Dict[str, Any]:
    """Extract individual UI, character, and background assets."""
    assets_extracted = {}

    im00_p0 = Image.open(raw_tims_dir / "tim_00_pal00.png")
    im00_p2 = Image.open(raw_tims_dir / "tim_00_pal02.png")
    im04_p0 = Image.open(raw_tims_dir / "tim_04_pal00.png")
    im05_p0 = Image.open(raw_tims_dir / "tim_05_pal00.png")

    hud_dir = build_dir / "extracted_hud"
    portraits_dir = build_dir / "extracted_portraits"
    bg_dir = build_dir / "extracted_background"
    effects_dir = build_dir / "extracted_effects"

    for d in (hud_dir, portraits_dir, bg_dir, effects_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Digits 0..9 and LV
    digits_coords = {
        "digit_1": (4, 1, 12, 16),
        "digit_2": (18, 1, 31, 16),
        "digit_3": (35, 1, 47, 16),
        "digit_4": (49, 1, 63, 16),
        "digit_5": (65, 1, 80, 16),
        "digit_6": (81, 1, 95, 16),
        "digit_7": (97, 1, 111, 16),
        "digit_8": (113, 1, 127, 16),
        "digit_9": (129, 1, 143, 16),
        "digit_0": (145, 1, 159, 16),
        "label_lv": (163, 1, 191, 16),
    }
    for name, box in digits_coords.items():
        crop = im00_p0.crop(box)
        p = hud_dir / f"{name}.png"
        crop.save(p)
        assets_extracted[name] = str(p)

    # 2. Text Banners and labels
    banners_coords = {
        "label_hits_hit_rate": (43, 31, 192, 42),
        "banner_ready_go": (8, 55, 163, 72),
        "banner_ready": (8, 55, 96, 72),
        "banner_go": (98, 55, 163, 72),
        "banner_game_over": (0, 75, 168, 104),
        "banner_game_clear": (0, 104, 184, 133),
        "banner_strategic_retreat": (31, 220, 226, 234),
    }
    for name, box in banners_coords.items():
        crop = im00_p0.crop(box)
        p = hud_dir / f"{name}.png"
        crop.save(p)
        assets_extracted[name] = str(p)

    # 3. Projectiles (Flare Arrow) from TIM 00
    projectile_coords = {
        "flare_arrow_diag_1": (192, 0, 256, 40),
        "flare_arrow_diag_2": (192, 40, 256, 80),
        "flare_arrow_diag_3": (192, 80, 256, 120),
    }
    for name, box in projectile_coords.items():
        crop = im00_p2.crop(box)
        p = effects_dir / f"{name}.png"
        crop.save(p)
        assets_extracted[name] = str(p)

    # 4. 5-frame explosion sequence in TIM 00 Band 2 (Y=136..192)
    explosion_coords = {
        "explosion_seq_00": (0, 136, 48, 192),
        "explosion_seq_01": (48, 136, 96, 192),
        "explosion_seq_02": (96, 136, 144, 192),
        "explosion_seq_03": (144, 136, 192, 192),
        "explosion_seq_04": (192, 136, 240, 192),
    }
    for name, box in explosion_coords.items():
        crop = im00_p2.crop(box)
        p = effects_dir / f"{name}.png"
        crop.save(p)
        assets_extracted[name] = str(p)

    # 5. Lina Portraits from TIM 04 (96x192)
    # Top portrait: Victory / Laughing
    # Bottom portrait: Defeat / Sweat drop
    crop_vic = im04_p0.crop((0, 0, 96, 96))
    p_vic = portraits_dir / "portrait_lina_victory.png"
    crop_vic.save(p_vic)
    assets_extracted["portrait_lina_victory"] = str(p_vic)

    crop_def = im04_p0.crop((0, 96, 96, 192))
    p_def = portraits_dir / "portrait_lina_defeat.png"
    crop_def.save(p_def)
    assets_extracted["portrait_lina_defeat"] = str(p_def)

    # 6. Background from TIM 05 (320x224)
    p_bg = bg_dir / "background_woodland_camp.png"
    im05_p0.save(p_bg)
    assets_extracted["background_woodland_camp"] = str(p_bg)

    # Defense line ground crop
    crop_ground = im05_p0.crop((0, 140, 320, 224))
    p_ground = bg_dir / "background_defense_line.png"
    crop_ground.save(p_ground)
    assets_extracted["background_defense_line"] = str(p_ground)

    return assets_extracted


def populate_user_directories(
    build_user_dir: Path,
    external_user_dir: Path,
    raw_tims_dir: Path,
    composite_dir: Path,
    extracted_assets: Dict[str, Any],
):
    """Copy all organized assets to user preparation folders."""
    subfolders = [
        "lina",
        "bandits",
        "barrels",
        "effects",
        "hud_ui",
        "background",
        "raw_tim_sheets",
    ]

    for root in (build_user_dir, external_user_dir):
        for sub in subfolders:
            (root / sub).mkdir(parents=True, exist_ok=True)

    def copy_file(src: Path, rel_dst: str):
        if not src.exists():
            return
        for root in (build_user_dir, external_user_dir):
            dst = root / rel_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    # 1. Lina assets (AMA 08..11, portraits)
    # AMA 08: Cast Flare Arrow
    ama08_dir = composite_dir / "ama_08"
    for p in ama08_dir.glob("*.png"):
        copy_file(p, f"lina/cast_flare_arrow/{p.name}")
    if (ama08_dir / "ama_08_preview.gif").exists():
        copy_file(ama08_dir / "ama_08_preview.gif", "lina/cast_flare_arrow/cast_flare_arrow.gif")

    # AMA 09: Walk Up
    ama09_dir = composite_dir / "ama_09"
    for p in ama09_dir.glob("*.png"):
        copy_file(p, f"lina/walk_up/{p.name}")
    if (ama09_dir / "ama_09_preview.gif").exists():
        copy_file(ama09_dir / "ama_09_preview.gif", "lina/walk_up/walk_up.gif")

    # AMA 10: Idle / Face Down
    ama10_dir = composite_dir / "ama_10"
    for p in ama10_dir.glob("*.png"):
        copy_file(p, f"lina/idle_down/{p.name}")
    if (ama10_dir / "ama_10_preview.gif").exists():
        copy_file(ama10_dir / "ama_10_preview.gif", "lina/idle_down/idle_down.gif")

    # AMA 11: Walk Down
    ama11_dir = composite_dir / "ama_11"
    for p in ama11_dir.glob("*.png"):
        copy_file(p, f"lina/walk_down/{p.name}")
    if (ama11_dir / "ama_11_preview.gif").exists():
        copy_file(ama11_dir / "ama_11_preview.gif", "lina/walk_down/walk_down.gif")

    # Portraits
    copy_file(Path(extracted_assets["portrait_lina_victory"]), "lina/portraits/portrait_lina_victory.png")
    copy_file(Path(extracted_assets["portrait_lina_defeat"]), "lina/portraits/portrait_lina_defeat.png")

    # 2. Bandits (AMA 14..17)
    # Bandit 1 (Spear Fighter / Tunic): AMA 14 (Run), AMA 15 (Hit)
    ama14_dir = composite_dir / "ama_14"
    for p in ama14_dir.glob("*.png"):
        copy_file(p, f"bandits/bandit_1_spear_fighter/run/{p.name}")
    if (ama14_dir / "ama_14_preview.gif").exists():
        copy_file(ama14_dir / "ama_14_preview.gif", "bandits/bandit_1_spear_fighter/run/run.gif")

    ama15_dir = composite_dir / "ama_15"
    for p in ama15_dir.glob("*.png"):
        copy_file(p, f"bandits/bandit_1_spear_fighter/hit_recoil/{p.name}")
    if (ama15_dir / "ama_15_preview.gif").exists():
        copy_file(ama15_dir / "ama_15_preview.gif", "bandits/bandit_1_spear_fighter/hit_recoil/hit_recoil.gif")

    # Bandit 2 (Vest Brawler / Bandana): AMA 16 (Run), AMA 17 (Strut/Hit)
    ama16_dir = composite_dir / "ama_16"
    for p in ama16_dir.glob("*.png"):
        copy_file(p, f"bandits/bandit_2_vest_brawler/run/{p.name}")
    if (ama16_dir / "ama_16_preview.gif").exists():
        copy_file(ama16_dir / "ama_16_preview.gif", "bandits/bandit_2_vest_brawler/run/run.gif")

    ama17_dir = composite_dir / "ama_17"
    for p in ama17_dir.glob("*.png"):
        copy_file(p, f"bandits/bandit_2_vest_brawler/strut_hit/{p.name}")
    if (ama17_dir / "ama_17_preview.gif").exists():
        copy_file(ama17_dir / "ama_17_preview.gif", "bandits/bandit_2_vest_brawler/strut_hit/strut_hit.gif")

    # 3. Barrels (AMA 12..13)
    ama12_dir = composite_dir / "ama_12"
    for p in ama12_dir.glob("*.png"):
        copy_file(p, f"barrels/roll_direction_a/{p.name}")
    if (ama12_dir / "ama_12_preview.gif").exists():
        copy_file(ama12_dir / "ama_12_preview.gif", "barrels/roll_direction_a/roll_a.gif")

    ama13_dir = composite_dir / "ama_13"
    for p in ama13_dir.glob("*.png"):
        copy_file(p, f"barrels/roll_direction_b/{p.name}")
    if (ama13_dir / "ama_13_preview.gif").exists():
        copy_file(ama13_dir / "ama_13_preview.gif", "barrels/roll_direction_b/roll_b.gif")

    # Static barrel
    if (ama12_dir / "frame_00.png").exists():
        copy_file(ama12_dir / "frame_00.png", "barrels/barrel_standing_intact.png")

    # 4. Effects
    # Flare Arrow Projectile (AMA 22 & TIM 00 crops)
    ama22_dir = composite_dir / "ama_22"
    for p in ama22_dir.glob("*.png"):
        copy_file(p, f"effects/flare_arrow_projectile/{p.name}")
    if (ama22_dir / "ama_22_preview.gif").exists():
        copy_file(ama22_dir / "ama_22_preview.gif", "effects/flare_arrow_projectile/flare_arrow_flying.gif")
    for k in ("flare_arrow_diag_1", "flare_arrow_diag_2", "flare_arrow_diag_3"):
        copy_file(Path(extracted_assets[k]), f"effects/flare_arrow_projectile/{k}.png")

    # Small Fire Bursts (AMA 19 & 20)
    ama19_dir = composite_dir / "ama_19"
    for p in ama19_dir.glob("*.png"):
        copy_file(p, f"effects/fire_burst_small_a/{p.name}")
    if (ama19_dir / "ama_19_preview.gif").exists():
        copy_file(ama19_dir / "ama_19_preview.gif", "effects/fire_burst_small_a/fire_burst_a.gif")

    ama20_dir = composite_dir / "ama_20"
    for p in ama20_dir.glob("*.png"):
        copy_file(p, f"effects/fire_burst_small_b/{p.name}")
    if (ama20_dir / "ama_20_preview.gif").exists():
        copy_file(ama20_dir / "ama_20_preview.gif", "effects/fire_burst_small_b/fire_burst_b.gif")

    # 5-stage explosion row
    for k in ("explosion_seq_00", "explosion_seq_01", "explosion_seq_02", "explosion_seq_03", "explosion_seq_04"):
        copy_file(Path(extracted_assets[k]), f"effects/explosion_fire_sequence/{k}.png")

    # Barrel detonation / smoke (AMA 18)
    ama18_dir = composite_dir / "ama_18"
    for p in ama18_dir.glob("*.png"):
        copy_file(p, f"effects/barrel_detonation_smoke/{p.name}")
    if (ama18_dir / "ama_18_preview.gif").exists():
        copy_file(ama18_dir / "ama_18_preview.gif", "effects/barrel_detonation_smoke/detonation_smoke.gif")

    # Mega explosion with shockwaves (AMA 21)
    ama21_dir = composite_dir / "ama_21"
    for p in ama21_dir.glob("*.png"):
        copy_file(p, f"effects/mega_explosion_shockwave/{p.name}")
    if (ama21_dir / "ama_21_preview.gif").exists():
        copy_file(ama21_dir / "ama_21_preview.gif", "effects/mega_explosion_shockwave/mega_explosion.gif")

    # 5. HUD / UI
    for i in range(10):
        copy_file(Path(extracted_assets[f"digit_{i}"]), f"hud_ui/digits/digit_{i}.png")
    for k in ("label_lv", "label_hits_hit_rate"):
        copy_file(Path(extracted_assets[k]), f"hud_ui/labels/{k}.png")
    for k in (
        "banner_ready",
        "banner_go",
        "banner_ready_go",
        "banner_game_over",
        "banner_game_clear",
        "banner_strategic_retreat",
    ):
        copy_file(Path(extracted_assets[k]), f"hud_ui/banners/{k}.png")

    # Font sheet
    copy_file(raw_tims_dir / "tim_07_pal00.png", "hud_ui/font/font_sheet_tim07.png")

    # 6. Background
    copy_file(Path(extracted_assets["background_woodland_camp"]), "background/background_woodland_camp.png")
    copy_file(Path(extracted_assets["background_defense_line"]), "background/background_defense_line.png")

    # 7. Raw TIM sheets
    for p in raw_tims_dir.glob("*.png"):
        copy_file(p, f"raw_tim_sheets/{p.name}")


def generate_technical_report(
    tim_infos: Dict[int, Any],
    ama_metadata: Dict[int, Any],
    file_records: List[Tuple[int, int, str]],
    report_path: Path,
):
    """Generate Markdown report detailing TIMs, AMAs, layouts, palettes, and mapping."""
    lines = [
        "# Отчёт по графическим ассетам, анимациям и спрайтам: «Отстрел бандитов» (Bandit Bullying, Slayers Royal PS1)",
        "",
        "## 1. Обзор архитектуры данных и дисковой структуры",
        "",
        "- **Источник данных:** `SMINI.UNT` Entry 4 (LBA сектор `223787 + 1317 = 225104`, размер 192 сектора = 393,216 байт).",
        "- **Формат контейнера:** Заголовочный контейнер `PMA` (версия 1, сигнатура `50 4D 41 01` / `PMA\\x01`), содержащий ровно **23 внутренних файла**:",
        "  - **Files 00..07:** 8 текстурных файлов PlayStation TIM.",
        "  - **Files 08..22:** 15 анимационных файлов `AMA` (`41 4D 41 01` / `AMA\\x01`).",
        "- **Базовое разрешение экрана PS1:** 320x224 пикселя (родной видеорежим NTSC Sony PlayStation).",
        "- **Целевые папки подготовленных спрайтов:**",
        "  1. `build/bandit_extraction/user_preparation/`",
        "  2. `/home/samvel/Downloads/Telegram Desktop/Slayers Royal/BANDIT_RAW_SPRITES/`",
        "",
        "---",
        "",
        "## 2. Анализ 8 TIM-изображений из SMINI.UNT Entry 4",
        "",
        "| Файл | Формат BPP | Разрешение (px) | VRAM (X, Y) | Слов VRAM | Палитры CLUT | Описание содержимого |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    tim_descriptions = {
        0: "**Главный атлас HUD/UI и эффектов:** Цифры 0..9, надписи LV, HITS, HIT RATE %, баннеры READY, GO!, GAME OVER, GAME CLEAR, STRATEGIC RETREAT, 3 кадра летящего снаряда Flare Arrow, 5-кадровый взрыв огня.",
        1: "**Атлас сложных спецэффектов взрывов:** Огненные шары, взрывные вспышки, грибовидные облака дыма, ударные кольца/волны, вихри рассеивания, искры и тлеющие угли для композитных взрывов бочек.",
        2: "**Спрайты Лины Инверс (8bpp):** Анимации Лины (48x64): каст заклинания Flare Arrow (руки вверх), ходьба вверх (от зрителя), стойка / поворот вниз, ходьба вниз (к зрителю).",
        3: "**Спрайты бандитов (8bpp):** Бандит 1 (зелёная туника, повязка на поясе, короткие волосы): бег и отлёт/удар; Бандит 2 (коричневая жилетка, голый торс, повязка): бег и отлёт/удар.",
        4: "**Портреты Лины (8bpp, 96x192):** Верхний кадр (96x96): Лина победно смеётся (Victory). Нижний кадр (96x96): Лина в поту / сконфужена (Defeat / Game Over).",
        5: "**Фоновая локация (8bpp, 320x224):** Полноэкранный фон лесной поляны / лагеря бандитов с грунтовой дорогой, деревьями, пограничной линией обороны и кустами.",
        6: "**Спрайты бочек (8bpp):** Деревянные бочки с металлическими обручами. Анимация качения бочки в двух изометрических направлениях (7 кадров каждого направления).",
        7: "**Шрифт и системный атлас (4bpp):** Текстовые глифы правил и диалогов мини-игры.",
    }

    for i in range(8):
        info = tim_infos[i][0]
        clut = info["clut"]
        clut_desc = f"{clut['colors'] // (16 if info['bpp_mode'] == 0 else 256)} палитр ({clut['width']}x{clut['height']}) @ ({clut['vram_x']},{clut['vram_y']})" if clut else "Без CLUT"
        lines.append(
            f"| **File {i:02d}** | {info['bpp']} | {info['pixel_width']}x{info['height']} | ({info['vram_x']}, {info['vram_y']}) | {info['vram_w_words']} | {clut_desc} | {tim_descriptions.get(i, '')} |"
        )

    lines.extend([
        "",
        "### 2.1. Палитры File 00 (HUD, таймер, плашки и огонь)",
        "File 00 содержит 16 палитр, из которых ключевые используются движком:",
        "1. **Палитра 00 (Золотисто-оранжевая):** Основная палитра для цифр таймера (0..9), плашек `LV`, `HITS / HIT RATE %`, баннеров `READY`, `GO!`, `GAME OVER`, `GAME CLEAR`.",
        "2. **Палитра 01 (Ярко-красный градиент):** Альтернативная палитра урона / критического состояния.",
        "3. **Палитра 02 (Насыщенный огненный градиент #F78410 / #FFF0E0):** Основная палитра для снарядов Flare Arrow и огненных взрывов.",
        "4. **Палитра 03 (Бирюзово-голубой градиент):** Магические вспышки / ледяные искры.",
        "5. **Палитра 04 (Тёмно-вишнёвый градиент):** Дым и угли.",
        "",
        "---",
        "",
        "## 3. Реверс-инжиниринг формата анимаций AMA (Files 08..22)",
        "",
        "Структура файла AMA (`0x01414D41`):",
        "```",
        "+---------------------------------------------------------------+--------------+",
        "| Заголовок AMA (12 байт):                                      |              |",
        "|   uint32 magic;         // 0x01414D41 (\"AMA\\x01\")             | 4 байта      |",
        "|   uint32 zero;          // 0                                  | 4 байта      |",
        "|   uint32 num_frames;    // Количество уникальных кадров        | 4 байта      |",
        "+---------------------------------------------------------------+--------------+",
        "| Для каждого кадра 0..(num_frames - 1):                        |              |",
        "|   uint32 num_parts;     // Количество спрайтовых ксиков (quad) | 4 байта      |",
        "|   Для каждого ксика:                                          |              |",
        "|     int16 u, v;         // UV координаты в текстуре            | 4 байта      |",
        "|     int16 x, y;         // Экранные координаты (0..320, 0..224)| 4 байта      |",
        "|     int16 w, h;         // Ширина и высота ксика               | 4 байта      |",
        "|     int16 tpage;        // Регистр TPAGE (выбор TIM-файла)     | 2 байта      |",
        "|     int16 clut;         // Регистр CLUT (палитра)              | 2 байта      |",
        "+---------------------------------------------------------------+--------------+",
        "| Таймлайн анимации:                                            |              |",
        "|   uint32 num_timeline;  // Количество шагов таймлайна          | 4 байта      |",
        "|   Для каждого шага:                                           |              |",
        "|     uint32 flags;       // Флаги (0)                           | 4 байта      |",
        "|     uint16 duration;    // Длительность в тиках (1/60 c)       | 2 байта      |",
        "|     uint16 frame_index; // Индекс кадра (0..num_frames-1)      | 2 байта      |",
        "+---------------------------------------------------------------+--------------+",
        "```",
        "",
        "### 3.1. Декодирование регистра TPAGE в индекс TIM",
        "- `0x0045` -> VRAM (320, 0), 4bpp -> **TIM 00** (HUD, эффекты огня, снаряды)",
        "- `0x0046` -> VRAM (384, 0), 4bpp -> **TIM 01** (Композитные взрывы и дым)",
        "- `0x00C7` -> VRAM (448, 0), 8bpp -> **TIM 02** (Лина Инверс)",
        "- `0x00CB` -> VRAM (704, 0), 8bpp -> **TIM 03** (Бандиты 1 и 2)",
        "- `0x00D5` -> VRAM (320, 256), 8bpp -> **TIM 06** (Бочки)",
        "",
        "### 3.2. Опкоды завершения и зацикливания таймлайна",
        "- `0x00FC` (252): **STOP / TERMINATE** — остановка анимации.",
        "- `0x00FE` (254): **HOLD** — удержание последнего кадра.",
        "- `0x00FF` (255): **LOOP** — бесконечное зацикливание таймлайна.",
        "",
        "---",
        "",
        "## 4. Каталог анимационных файлов AMA 08..22",
        "",
        "| AMA Файл | Кадров | Шагов TL | Источник TIM | Размеры спрайта | Действие персонажа / объекта | Описание анимации |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        "| **AMA 08** | 6 | 7 | TIM 02 | 48x64 | **Лина: Каст Flare Arrow** | Лина стоит спиной/на северо-восток, воздевает обе руки вверх, концентрирует пламя и выпускает стрелу. |",
        "| **AMA 09** | 3 | 3 | TIM 02 | 48x64 | **Лина: Ходьба вверх** | Лина шагает вверх/от зрителя в изометрической проекции. |",
        "| **AMA 10** | 5 | 6 | TIM 02 | 48x64 | **Лина: Стойка / Поворот** | Лина поворачивается лицом к зрителю (на юг), покачиваясь в боевой стойке. |",
        "| **AMA 11** | 6 | 7 | TIM 02 | 48x64 | **Лина: Ходьба вниз** | Лина шагает вниз/к зрителю, плащ развевается, ноги переступают. |",
        "| **AMA 12** | 7 | 8 | TIM 06 | 48x64 | **Бочка: Качение направо/вниз** | Полный цикл вращения бочки по диагонали (7 уникальных фаз качения). |",
        "| **AMA 13** | 7 | 8 | TIM 06 | 48x64 | **Бочка: Качение налево/вверх** | Полный цикл вращения бочки в обратном направлении (7 фаз). |",
        "| **AMA 14** | 6 | 7 | TIM 03 | 48x64 | **Бандит 1: Бег** | Бандит в зелёной тунике и с короткими волосами бежит наперевес к линии обороны Лины. |",
        "| **AMA 15** | 3 | 4 | TIM 03 | 64x64 | **Бандит 1: Отлёт / Попадание** | Попадание снарядом Flare Arrow: бандит отклоняется назад, теряет равновесие и отлетает. |",
        "| **AMA 16** | 6 | 7 | TIM 03 | 48x64 | **Бандит 2: Бег** | Бандит в жилетке с голым торсом и зелёной повязкой на голове быстро бежит вперёд. |",
        "| **AMA 17** | 3 | 4 | TIM 03 | 64x64 | **Бандит 2: Попадание / Нокдаун** | Реакция на попадание магии: отбрасывание назад и падение. |",
        "| **AMA 18** | 10 | 9 | TIM 01 | 176x128 | **Взрыв бочки (Дым и огонь)** | Многослойная композитная анимация взрыва: детонация, разлёт обломков и клубящийся дым. |",
        "| **AMA 19** | 6 | 6 | TIM 00 | 48x64 | **Вспышка пламени A** | Быстрая вспышка огня при детонации снаряда Flare Arrow. |",
        "| **AMA 20** | 6 | 6 | TIM 00 | 48x64 | **Вспышка пламени B** | Расширяющееся облако пламени и рассеивание дыма. |",
        "| **AMA 21** | 11 | 11 | TIM 01 | 288x208 | **Мега-взрыв цепи бочек** | Огромный составной взрыв на пол-экрана с круговой ударной волной, вспышками и шлейфом сажи. |",
        "| **AMA 22** | 3 | 3 | TIM 00 | 64x40 | **Полёт Flare Arrow** | Огненная стрела, летящая с хвостом пламени (3 фазы пульсации огня). |",
        "",
        "---",
        "",
        "## 5. Организация каталогов для переноса в Ren'Py",
        "",
        "Все спрайты скопированы и структурированы в `BANDIT_RAW_SPRITES/`:",
        "```",
        "BANDIT_RAW_SPRITES/",
        "├── lina/",
        "│   ├── cast_flare_arrow/       # 6 кадров каста + cast_flare_arrow.gif + ксики",
        "│   ├── walk_up/                # 3 кадра ходьбы вверх + walk_up.gif + ксики",
        "│   ├── idle_down/              # 5 кадров стойки лицом вниз + idle_down.gif + ксики",
        "│   ├── walk_down/              # 6 кадров ходьбы вниз + walk_down.gif + ксики",
        "│   └── portraits/              # portrait_lina_victory.png, portrait_lina_defeat.png",
        "├── bandits/",
        "│   ├── bandit_1_spear_fighter/",
        "│   │   ├── run/                # 6 кадров бега + run.gif",
        "│   │   └── hit_recoil/         # 3 кадра отлёта + hit_recoil.gif",
        "│   └── bandit_2_vest_brawler/",
        "│       ├── run/                # 6 кадров бега + run.gif",
        "│       └── strut_hit/          # 3 кадра отлёта/попадания + strut_hit.gif",
        "├── barrels/",
        "│   ├── roll_direction_a/       # 7 кадров качения в направлении A + roll_a.gif",
        "│   ├── roll_direction_b/       # 7 кадров качения в направлении B + roll_b.gif",
        "│   └── barrel_standing_intact.png # Целая стоящая бочка",
        "├── effects/",
        "│   ├── flare_arrow_projectile/ # 3 кадра полёта + GIF + 3 диагональных спрайта",
        "│   ├── fire_burst_small_a/     # 6 кадров огненной вспышки A + GIF",
        "│   ├── fire_burst_small_b/     # 6 кадров огненной вспышки B + GIF",
        "│   ├── explosion_fire_sequence/# 5 стадий расширения огненного шара",
        "│   ├── barrel_detonation_smoke/# 10 композитных кадров детонации бочки + GIF",
        "│   └── mega_explosion_shockwave/# 11 композитных кадров мега-взрыва + GIF",
        "├── hud_ui/",
        "│   ├── digits/                 # digit_0.png .. digit_9.png (10 отдельных цифр)",
        "│   ├── labels/                 # label_lv.png, label_hits_hit_rate.png",
        "│   ├── banners/                # banner_ready.png, banner_go.png, banner_game_over.png, banner_game_clear.png, banner_strategic_retreat.png",
        "│   └── font/                   # font_sheet_tim07.png",
        "├── background/",
        "│   ├── background_woodland_camp.png # Полный фон 320x224",
        "│   └── background_defense_line.png  # Линия защиты Лины (нижняя треть фона)",
        "└── raw_tim_sheets/             # Полные текстурные листы TIM 00..07 со всеми палитрами",
        "```",
        "",
        "---",
        "",
        "*Отчёт сформирован автоматически в ходе реверс-инжиниринга и извлечения графических ассетов PS1.*",
    ])

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Generated report at {report_path}")


def main():
    print("[*] Starting Bandit Bullying Sprite Extraction Pipeline...")
    disc_path = get_disc_path()
    print(f"[*] Reading disc image: {disc_path}")

    # 1. Read Entry 4
    e4_data = read_smini_entry_4(disc_path)
    print(f"[*] Loaded Entry 4: {len(e4_data)} bytes")

    # 2. Unpack PMA
    file_records = unpack_pma(e4_data, RAW_PMA_DIR)
    print(f"[*] Unpacked {len(file_records)} files to {RAW_PMA_DIR}")

    # 3. Decode TIMs
    tim_infos = {}
    for i in range(8):
        tim_file = RAW_PMA_DIR / f"file_{i:02d}.tim"
        info, paths = decode_tim_palettes(tim_file.read_bytes(), f"tim_{i:02d}", RAW_TIMS_DIR)
        tim_infos[i] = (info, paths)
    print(f"[*] Decoded all 8 TIM files into {RAW_TIMS_DIR}")

    # 4. Parse AMAs
    amas = {}
    for i in range(8, len(file_records)):
        ama_file = RAW_PMA_DIR / f"file_{i:02d}.ama"
        ama_parsed = parse_ama(ama_file.read_bytes(), i)
        amas[i] = ama_parsed
    print(f"[*] Parsed {len(amas)} AMA files")

    # 5. Render composite frames and quads
    ama_metadata = render_ama_animations(amas, RAW_TIMS_DIR, COMPOSITE_DIR, INDIVIDUAL_QUADS_DIR)
    print(f"[*] Rendered composite frames and extracted quads to {COMPOSITE_DIR}")

    # 6. Extract specialized HUD / UI / Portrait / Background assets
    extracted_assets = extract_specialized_assets(RAW_TIMS_DIR, BUILD_DIR)
    print(f"[*] Extracted specialized assets ({len(extracted_assets)} items)")

    # 7. Populate user directories
    populate_user_directories(USER_PREP_DIR, TARGET_RENPY_DIR, RAW_TIMS_DIR, COMPOSITE_DIR, extracted_assets)
    print(f"[*] Populated user preparation folders: {USER_PREP_DIR} and {TARGET_RENPY_DIR}")

    # 8. Generate technical report
    generate_technical_report(tim_infos, ama_metadata, file_records, REPORT_FILE)
    print("[*] Pipeline completed successfully!")


if __name__ == "__main__":
    main()
