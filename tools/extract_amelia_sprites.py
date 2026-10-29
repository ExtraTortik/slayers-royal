#!/usr/bin/env python3
"""Slayers Royal (PS1) — Amelia's Jump Minigame Sprite Extraction Pipeline.

Extracts, unpacks, decodes, and renders all visual assets for the PS1 minigame
"Amelia's Jump" (Прыжок Амелии / Amelia Cliff Jump / amelia_climb):
  - SMINI.UNT Entry 1 (LBA 223787 + 321, 339 sectors = 694,272 bytes)
  - Unpacks PMA container with 42 files: 12 TIM textures + 30 AMA animations
  - Decodes all 12 TIM textures across all CLUT palettes into PNG
  - Maps TPAGE values to the correct TIM index
  - Renders all 30 AMAs (composite tight frames, 320x224 screen reference, animated GIFs)
  - Extracts individual quads for all AMAs
  - Extracts and stitches vertical scrolling cliff layers (320x768 full backdrop)
  - Extracts HUD & UI elements (combo window, controller glyphs, banners, portraits)
  - Mirrors assets to /home/samvel/Downloads/Telegram Desktop/Slayers Royal/AMELIA_RAW_SPRITES/
  - Generates comprehensive sprites_report.md
"""

from __future__ import annotations

import argparse
import os
import shutil
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
DISC_BIN_RU = REPO_ROOT / "localization-output" / "ru" / "slayers_royal_ru.bin"
DISC_BIN_ORIG = REPO_ROOT / "downloads" / "sr.bin"

BUILD_DIR = REPO_ROOT / "build" / "amelia_extraction"
RAW_PMA_DIR = BUILD_DIR / "raw_pma"
RAW_TIMS_DIR = BUILD_DIR / "raw_tims_png"
COMPOSITE_DIR = BUILD_DIR / "composite_frames"
INDIVIDUAL_QUADS_DIR = BUILD_DIR / "individual_quads"
ANIMATIONS_GIF_DIR = BUILD_DIR / "animations_gif"
BACKGROUND_CLIFF_DIR = BUILD_DIR / "background_cliff"
HUD_UI_DIR = BUILD_DIR / "hud_ui"
AMELIA_POSES_DIR = BUILD_DIR / "amelia_poses"
REPORT_FILE = BUILD_DIR / "sprites_report.md"

TARGET_USER_DIR = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/AMELIA_RAW_SPRITES")

RAW_SECTOR_SIZE = 2352
USER_DATA_SIZE = 2048
SMINI_DEFAULT_LBA = 223787
ENTRY_1_INDEX = 1
ENTRY_1_START_SECTOR = 321
ENTRY_1_SECTOR_COUNT = 339
ENTRY_1_BYTE_SIZE = ENTRY_1_SECTOR_COUNT * USER_DATA_SIZE  # 694,272 bytes

# Descriptive names for all 30 AMA animations (File index 12..41, MIPS anim_id 0..29)
# Confirmed via MIPS disassembly of loop at 0x8004E87C / descriptors at 0x80070550:
# File Index = anim_id + 12.
AMA_ACTION_NAMES: Dict[int, Dict[str, Any]] = {
    12: {"anim_id": 0, "id": "anim_00_cliff_speech_prep", "title": "Standing on Cliff Ledge / Speech Prep (Anim 0)", "category": "intro"},
    13: {"anim_id": 1, "id": "anim_01_cliff_speech_talk", "title": "Justice Speech on Cliff Ledge (Anim 1)", "category": "speech"},
    14: {"anim_id": 2, "id": "anim_02_jump_takeoff", "title": "Leap Takeoff into Abyss (Anim 2)", "category": "takeoff"},
    15: {"anim_id": 3, "id": "anim_03_easy_pose_a", "title": "Attempt 1 (Easy): Level A Pose (Anim 3)", "category": "poses_easy"},
    16: {"anim_id": 4, "id": "anim_04_easy_pose_b", "title": "Attempt 1 (Easy): Level B Pose (Anim 4)", "category": "poses_easy"},
    17: {"anim_id": 5, "id": "anim_05_easy_pose_c", "title": "Attempt 1 (Easy): Level C Pose (Anim 5)", "category": "poses_easy"},
    18: {"anim_id": 6, "id": "anim_06_easy_pose_s", "title": "Attempt 1 (Easy): Level S Pose (Anim 6)", "category": "poses_easy"},
    19: {"anim_id": 7, "id": "anim_07_normal_pose_a", "title": "Attempt 2 (Normal): Level A Pose (Anim 7)", "category": "poses_normal"},
    20: {"anim_id": 8, "id": "anim_08_normal_pose_b", "title": "Attempt 2 (Normal): Level B Pose (Anim 8)", "category": "poses_normal"},
    21: {"anim_id": 9, "id": "anim_09_normal_pose_c", "title": "Attempt 2 (Normal): Level C Pose (Anim 9)", "category": "poses_normal"},
    22: {"anim_id": 10, "id": "anim_10_normal_pose_s", "title": "Attempt 2 (Normal): Level S Pose (Anim 10)", "category": "poses_normal"},
    23: {"anim_id": 11, "id": "anim_11_hard_pose_a", "title": "Attempt 3 (Hard): Level A Pose (Anim 11)", "category": "poses_hard"},
    24: {"anim_id": 12, "id": "anim_12_hard_pose_b", "title": "Attempt 3 (Hard): Level B Pose (Anim 12)", "category": "poses_hard"},
    25: {"anim_id": 13, "id": "anim_13_hard_pose_c", "title": "Attempt 3 (Hard): Level C Pose (Anim 13)", "category": "poses_hard"},
    26: {"anim_id": 14, "id": "anim_14_hard_pose_s", "title": "Attempt 3 (Hard): Level S Pose (Anim 14)", "category": "poses_hard"},
    27: {"anim_id": 15, "id": "anim_15_impact_flash", "title": "Radiant Aura / Impact Flash Burst (Anim 15)", "category": "effects"},
    28: {"anim_id": 16, "id": "anim_16_landing_safe", "title": "Safe Touchdown / Ground Landing (Anim 16)", "category": "landing"},
    29: {"anim_id": 17, "id": "anim_17_victory_pose", "title": "Victory Stance Celebration (Anim 17)", "category": "victory"},
    30: {"anim_id": 18, "id": "anim_18_stumble_penalty_1", "title": "Stumble / Slip Penalty 1 (Anim 18)", "category": "penalty"},
    31: {"anim_id": 19, "id": "anim_19_stumble_penalty_2", "title": "Stumble / Twitching Feet Penalty 2 (Anim 19)", "category": "penalty"},
    32: {"anim_id": 20, "id": "anim_20_recovering_get_up", "title": "Recovery / Getting Up (Anim 20)", "category": "landing"},
    33: {"anim_id": 21, "id": "anim_21_crash_faceplant_splat", "title": "Crash / Splat Faceplant (Anim 21)", "category": "penalty"},
    34: {"anim_id": 22, "id": "anim_22_dust_off_fist_pump", "title": "Stand Up Dust Off / Fist Pump (Anim 22)", "category": "landing"},
    35: {"anim_id": 23, "id": "anim_23_pose_s_variant_1", "title": "Pose S Alternative Variant 1 (Anim 23)", "category": "poses_variant"},
    36: {"anim_id": 24, "id": "anim_24_pose_s_variant_2", "title": "Pose S Alternative Variant 2 (Anim 24)", "category": "poses_variant"},
    37: {"anim_id": 25, "id": "anim_25_particle_spark_01", "title": "Justice Spark 1 (8x8) (Anim 25)", "category": "effects"},
    38: {"anim_id": 26, "id": "anim_26_particle_spark_02", "title": "Justice Spark 2 (8x8) (Anim 26)", "category": "effects"},
    39: {"anim_id": 27, "id": "anim_27_particle_spark_03", "title": "Justice Spark 3 (8x8) (Anim 27)", "category": "effects"},
    40: {"anim_id": 28, "id": "anim_28_justice_energy_beam", "title": "Descending Justice Column Beam (40x136) (Anim 28)", "category": "effects"},
    41: {"anim_id": 29, "id": "anim_29_sweat_drop_effect", "title": "Sweat Drop / Shock Effect (32x24) (Anim 29)", "category": "effects"},
}


def get_disc_path() -> Path:
    """Return available disc binary path."""
    if DISC_BIN_RU.is_file():
        return DISC_BIN_RU
    if DISC_BIN_ORIG.is_file():
        return DISC_BIN_ORIG
    raise FileNotFoundError(f"Neither {DISC_BIN_RU} nor {DISC_BIN_ORIG} found.")


def read_smini_entry_1(bin_path: Path) -> bytearray:
    """Read Entry 1 directly from disc image."""
    data = bytearray()
    with bin_path.open("rb") as f:
        for s in range(ENTRY_1_SECTOR_COUNT):
            sector_num = SMINI_DEFAULT_LBA + ENTRY_1_START_SECTOR + s
            f.seek(sector_num * RAW_SECTOR_SIZE + 24)
            chunk = f.read(USER_DATA_SIZE)
            data.extend(chunk)
    if len(data) != ENTRY_1_BYTE_SIZE:
        raise ValueError(f"Expected {ENTRY_1_BYTE_SIZE} bytes, got {len(data)}")
    return data


def unpack_pma(e1_data: bytearray, out_dir: Path) -> List[Tuple[int, int, str]]:
    """Unpack PMA container into raw files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    magic, num_files = struct.unpack_from("<II", e1_data, 0)
    if magic != 0x014D4D50 and magic != 0x504D4101 and e1_data[:4] != b"PMA\x01":
        raise ValueError(f"Invalid PMA magic: {e1_data[:4]}")

    offsets = [struct.unpack_from("<I", e1_data, 8 + i * 4)[0] for i in range(num_files)]
    offsets.append(len(e1_data))

    file_records = []
    for i in range(num_files):
        start = offsets[i]
        end = offsets[i + 1]
        chunk = e1_data[start:end]
        ext = "tim" if i < 12 else "ama"
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
            "palettes": (cw * ch) // (16 if bpp_mode == 0 else 256),
            "offset": offset + 12,
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
        "image_data_length": img_len - 12,
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
    if has_clut and clut:
        num_palettes = clut["colors"] // palette_size

    w = info["vram_w_words"]
    h = info["height"]
    pix_w = info["pixel_width"]
    pixel_data = tim_bytes[info["image_data_offset"] : info["image_data_offset"] + info["image_data_length"]]

    saved_paths = []
    for pal_idx in range(num_palettes):
        colors = []
        if has_clut and clut:
            clut_data = tim_bytes[clut["offset"] : clut["offset"] + clut["colors"] * 2]
            for i in range(palette_size):
                idx = (pal_idx * palette_size + i) * 2
                c16 = struct.unpack_from("<H", clut_data, idx)[0]
                r = round(((c16 & 0x1F) * 255) / 31)
                g = round((((c16 >> 5) & 0x1F) * 255) / 31)
                b = round((((c16 >> 10) & 0x1F) * 255) / 31)
                # Background textures (TIM 08, 09, 10): fully opaque
                if prefix in ("tim_08", "tim_09", "tim_10"):
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
                "raw_tpage": tpage, "raw_clut": clut,
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
    """Map PS1 TPAGE register to TIM index (0..11).

    Mappings:
      - 0x06, 0x66 -> TIM 1 (4bpp at VRAM X=384, Y=0)
      - 0x87, 0xe7 -> TIM 2 (8bpp at VRAM X=448, Y=0)
      - 0x89       -> TIM 3 (8bpp at VRAM X=576, Y=0)
      - 0x8b       -> TIM 4 (8bpp at VRAM X=704, Y=0)
      - 0x8d       -> TIM 5 (8bpp at VRAM X=832, Y=0)
      - 0xd7       -> TIM 7 (8bpp at VRAM X=448, Y=256)
    """
    if tpage in (0x06, 0x66):
        return 1
    elif tpage in (0x87, 0xE7):
        return 2
    elif tpage == 0x89:
        return 3
    elif tpage == 0x8B:
        return 4
    elif tpage == 0x8D:
        return 5
    elif tpage == 0xD7:
        return 7

    # Hardware fallback by VRAM coordinates
    tx = (tpage & 0xF) * 64
    ty = ((tpage >> 4) & 1) * 256
    bpp_mode = (tpage >> 7) & 3

    if tx == 320 and ty == 0 and bpp_mode == 0:
        return 0
    elif tx == 384 and ty == 0 and bpp_mode == 0:
        return 1
    elif tx == 448 and ty == 0 and bpp_mode == 1:
        return 2
    elif tx == 576 and ty == 0 and bpp_mode == 1:
        return 3
    elif tx == 704 and ty == 0 and bpp_mode == 1:
        return 4
    elif tx == 832 and ty == 0 and bpp_mode == 1:
        return 5
    elif tx == 960 and ty == 0 and bpp_mode == 1:
        return 6
    elif tx == 448 and ty == 256 and bpp_mode == 1:
        return 7
    elif tx == 320 and ty == 256 and bpp_mode == 1:
        return 8
    elif tx == 512 and ty == 256 and bpp_mode == 1:
        return 9
    elif tx == 704 and ty == 256 and bpp_mode == 1:
        return 10
    elif tx == 896 and ty == 256 and bpp_mode == 0:
        return 11
    return 2


def render_ama_animations(
    amas: Dict[int, Dict[str, Any]],
    raw_tims_dir: Path,
    composite_dir: Path,
    quads_dir: Path,
    gifs_dir: Path,
) -> Dict[int, Dict[str, Any]]:
    """Render composite frames, animated GIFs, and quads for all AMAs."""
    if composite_dir.is_dir():
        shutil.rmtree(composite_dir)
    composite_dir.mkdir(parents=True, exist_ok=True)
    if quads_dir.is_dir():
        shutil.rmtree(quads_dir)
    quads_dir.mkdir(parents=True, exist_ok=True)
    if gifs_dir.is_dir():
        shutil.rmtree(gifs_dir)
    gifs_dir.mkdir(parents=True, exist_ok=True)

    ama_metadata = {}

    for a_idx, ama in amas.items():
        name_info = AMA_ACTION_NAMES.get(a_idx, {"id": f"ama_{a_idx:02d}", "title": f"AMA {a_idx:02d}", "anim_id": a_idx - 12})
        action_id = name_info["id"]
        anim_id = name_info.get("anim_id", a_idx - 12)
        ama_comp_dir = composite_dir / f"ama_{a_idx:02d}_{action_id}"
        ama_quad_dir = quads_dir / f"ama_{a_idx:02d}_{action_id}"
        ama_comp_dir.mkdir(parents=True, exist_ok=True)
        ama_quad_dir.mkdir(parents=True, exist_ok=True)

        frames = ama["frames"]
        timeline = ama["timeline"]

        all_xs = [p["x"] for f in frames for p in f]
        all_ys = [p["y"] for f in frames for p in f]
        all_max_xs = [p["x"] + p["w"] for f in frames for p in f]
        all_max_ys = [p["y"] + p["h"] for f in frames for p in f]

        min_x = min(all_xs) if all_xs else 0
        min_y = min(all_ys) if all_ys else 0
        max_x = max(all_max_xs) if all_max_xs else 64
        max_y = max(all_max_ys) if all_max_ys else 64
        bw = max(1, max_x - min_x)
        bh = max(1, max_y - min_y)

        rendered_tight = []
        rendered_screen = []

        for f_idx, f in enumerate(frames):
            frame_tight = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            frame_screen = Image.new("RGBA", (320, 224), (0, 0, 0, 0))

            for p_idx, p in enumerate(f):
                tim_idx = map_tpage_to_tim(p["raw_tpage"])
                pal_idx = 0
                if tim_idx == 1:
                    pal_idx = 1  # Multi-color effects palette for TIM 1
                tim_png = raw_tims_dir / f"tim_{tim_idx:02d}_pal{pal_idx:02d}.png"
                if not tim_png.exists():
                    tim_png = raw_tims_dir / f"tim_{tim_idx:02d}_pal00.png"

                with Image.open(tim_png) as tim_img:
                    part_crop = tim_img.crop((p["u"], p["v"], p["u"] + p["w"], p["v"] + p["h"]))

                quad_path = ama_quad_dir / f"f{f_idx:02d}_p{p_idx:02d}_u{p['u']}_v{p['v']}_{p['w']}x{p['h']}.png"
                part_crop.save(quad_path)

                dest_x = p["x"] - min_x
                dest_y = p["y"] - min_y
                frame_tight.paste(part_crop, (dest_x, dest_y), part_crop)

                if 0 <= p["x"] < 320 and 0 <= p["y"] < 224:
                    frame_screen.paste(part_crop, (p["x"], p["y"]), part_crop)

            tight_path = ama_comp_dir / f"frame_{f_idx:02d}.png"
            screen_path = ama_comp_dir / f"screen_frame_{f_idx:02d}.png"
            frame_tight.save(tight_path)
            frame_screen.save(screen_path)

            rendered_tight.append(frame_tight)
            rendered_screen.append(frame_screen)

        gif_frames = []
        durations = []
        for step in timeline:
            f_idx = step["frame_index"]
            dur = step["duration"]
            if f_idx < len(rendered_tight):
                gif_frames.append(rendered_tight[f_idx])
                dur_ms = max(20, int(dur * 1000 / 60)) if dur < 200 else 400
                durations.append(dur_ms)

        gif_path = None
        if gif_frames:
            gif_filename = f"ama_{a_idx:02d}_{action_id}.gif"
            gif_path = gifs_dir / gif_filename
            gif_frames[0].save(
                gif_path,
                save_all=True,
                append_images=gif_frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
            )
            # Also save copy in composite dir
            gif_frames[0].save(
                ama_comp_dir / f"preview.gif",
                save_all=True,
                append_images=gif_frames[1:],
                duration=durations,
                loop=0,
                disposal=2,
            )

        ama_metadata[a_idx] = {
            "anim_id": anim_id,
            "action_id": action_id,
            "title": name_info["title"],
            "category": name_info.get("category", "poses"),
            "bbox": (min_x, min_y, max_x, max_y),
            "size": (bw, bh),
            "num_frames": len(frames),
            "num_timeline": len(timeline),
            "total_ticks": sum(s["duration"] for s in timeline),
            "tight_paths": [str(ama_comp_dir / f"frame_{i:02d}.png") for i in range(len(frames))],
            "gif_path": str(gif_path) if gif_path else None,
        }

    return ama_metadata


def extract_background_cliff(raw_tims_dir: Path, out_dir: Path) -> Dict[str, Any]:
    """Extract and assemble vertical scrolling cliff layers."""
    out_dir.mkdir(parents=True, exist_ok=True)
    im8 = Image.open(raw_tims_dir / "tim_08_pal00.png")
    im9 = Image.open(raw_tims_dir / "tim_09_pal00.png")
    im10 = Image.open(raw_tims_dir / "tim_10_pal00.png")

    p_top = out_dir / "cliff_layer_01_top_sky_320x256.png"
    p_mid = out_dir / "cliff_layer_02_middle_wall_320x256.png"
    p_bot = out_dir / "cliff_layer_03_bottom_ground_320x256.png"
    p_full = out_dir / "cliff_full_320x768.png"

    im8.save(p_top)
    im9.save(p_mid)
    im10.save(p_bot)

    # Stitched 320x768 background
    cliff_full = Image.new("RGBA", (320, 768))
    cliff_full.paste(im8, (0, 0))
    cliff_full.paste(im9, (0, 256))
    cliff_full.paste(im10, (0, 512))
    cliff_full.save(p_full)

    return {
        "top": str(p_top),
        "mid": str(p_mid),
        "bot": str(p_bot),
        "full": str(p_full),
    }


def extract_hud_ui_assets(raw_tims_dir: Path, out_dir: Path) -> Dict[str, Any]:
    """Extract individual HUD, UI, banners, buttons, and glyph assets."""
    out_dir.mkdir(parents=True, exist_ok=True)
    im0_p0 = Image.open(raw_tims_dir / "tim_00_pal00.png")
    im0_p1 = Image.open(raw_tims_dir / "tim_00_pal01.png")
    im0_p2 = Image.open(raw_tims_dir / "tim_00_pal02.png")
    im0_p3 = Image.open(raw_tims_dir / "tim_00_pal03.png")

    im1_p1 = Image.open(raw_tims_dir / "tim_01_pal01.png")
    im1_p9 = Image.open(raw_tims_dir / "tim_01_pal09.png")
    im11 = Image.open(raw_tims_dir / "tim_11_pal00.png")

    assets = {}

    # 1. Combo Window Frame & Indicators from TIM 00
    p_box = out_dir / "combo_window_frame.png"
    im0_p0.crop((0, 0, 96, 64)).save(p_box)
    assets["combo_window_frame"] = str(p_box)

    p_circle_btn = out_dir / "hud_circle_button.png"
    im0_p0.crop((128, 0, 144, 16)).save(p_circle_btn)
    assets["hud_circle_button"] = str(p_circle_btn)

    p_arrow_u = out_dir / "hud_arrow_up.png"
    im0_p0.crop((32, 0, 48, 21)).save(p_arrow_u)
    assets["hud_arrow_up"] = str(p_arrow_u)

    p_arrow_d = out_dir / "hud_arrow_down.png"
    im0_p0.crop((96, 0, 112, 21)).save(p_arrow_d)
    assets["hud_arrow_down"] = str(p_arrow_d)

    # 2. PlayStation Controller Glyphs from TIM 11 (16x16 authentic font tiles)
    glyphs_spec = {
        "glyph_circle": 0x006B,
        "glyph_arrow_up": 0x0074,
        "glyph_arrow_down": 0x0075,
        "glyph_arrow_right": 0x0076,
        "glyph_arrow_left": 0x0077,
    }
    for g_name, gid in glyphs_spec.items():
        col = gid % 16
        row = gid // 16
        x = col * 16
        y = row * 16
        crop = im11.crop((x, y, x + 16, y + 16))
        p = out_dir / f"{g_name}_16x16.png"
        crop.save(p)
        assets[g_name] = str(p)

    # 3. Banners & Titles from TIM 00
    banners_dir = out_dir / "banners"
    banners_dir.mkdir(parents=True, exist_ok=True)

    # Japanese Minigame Title: "アメリアジャンプ" (Amelia Jump)
    p_title = banners_dir / "banner_title_amelia_jump.png"
    im0_p0.crop((0, 64, 120, 96)).save(p_title)
    assets["banner_title_amelia_jump"] = str(p_title)

    # English Banner: "JUSTICE"
    p_justice = banners_dir / "banner_justice.png"
    im0_p0.crop((70, 148, 185, 175)).save(p_justice)
    assets["banner_justice"] = str(p_justice)

    # English Banner: "SPIRIT"
    p_spirit = banners_dir / "banner_spirit.png"
    im0_p0.crop((80, 184, 175, 210)).save(p_spirit)
    assets["banner_spirit"] = str(p_spirit)

    # English Banner: "LOVE"
    p_love = banners_dir / "banner_love.png"
    im0_p0.crop((184, 60, 248, 84)).save(p_love)
    assets["banner_love"] = str(p_love)

    # Japanese Victory Banner: "大成功" / Grand Success
    p_succ = banners_dir / "banner_grand_success.png"
    im0_p0.crop((110, 224, 205, 255)).save(p_succ)
    assets["banner_grand_success"] = str(p_succ)

    # 4. Digits & Indicators from TIM 00
    p_digits = out_dir / "digits_strip_0_to_9.png"
    im0_p0.crop((184, 116, 248, 128)).save(p_digits)
    assets["digits_strip"] = str(p_digits)

    # 5. Specialized Graphics from TIM 01
    p_port = out_dir / "portrait_amelia_tim01.png"
    im1_p9.crop((136, 0, 224, 128)).save(p_port)
    assets["portrait_amelia"] = str(p_port)

    p_dust1 = out_dir / "dust_cloud_silhouette_small.png"
    im1_p1.crop((0, 2, 122, 79)).save(p_dust1)
    assets["dust_cloud_small"] = str(p_dust1)

    p_dust2 = out_dir / "dust_cloud_silhouette_large.png"
    im1_p1.crop((0, 81, 162, 175)).save(p_dust2)
    assets["dust_cloud_large"] = str(p_dust2)

    p_bub1 = out_dir / "speech_bubble_small.png"
    im1_p1.crop((7, 192, 57, 232)).save(p_bub1)
    assets["speech_bubble_small"] = str(p_bub1)

    p_bub2 = out_dir / "speech_bubble_medium.png"
    im1_p1.crop((70, 192, 122, 233)).save(p_bub2)
    assets["speech_bubble_medium"] = str(p_bub2)

    p_wings = out_dir / "wings_aura_effect.png"
    im1_p1.crop((128, 192, 192, 230)).save(p_wings)
    assets["wings_aura_effect"] = str(p_wings)

    # 6. Entire Font Sheet TIM 11
    p_font = out_dir / "font_sheet_tim11.png"
    im11.save(p_font)
    assets["font_sheet_tim11"] = str(p_font)

    return assets


def organize_amelia_poses(
    composite_dir: Path,
    out_dir: Path,
    ama_meta: Dict[int, Dict[str, Any]],
) -> None:
    """Organize composite Amelia frames into structured action directories."""
    if out_dir.is_dir():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for a_idx, meta in ama_meta.items():
        action_id = meta["action_id"]
        sub_dir = out_dir / f"{a_idx:02d}_{action_id}"
        sub_dir.mkdir(parents=True, exist_ok=True)

        src_dir = composite_dir / f"ama_{a_idx:02d}_{action_id}"
        if src_dir.is_dir():
            for f_name in os.listdir(src_dir):
                if f_name.endswith(".png"):
                    shutil.copy2(src_dir / f_name, sub_dir / f_name)


def populate_user_directories(
    user_root: Path,
    raw_tims_dir: Path,
    amelia_poses_dir: Path,
    gifs_dir: Path,
    cliff_dir: Path,
    hud_dir: Path,
    quads_dir: Path,
) -> None:
    """Mirror all organized assets to the user inspection directory."""
    user_root.mkdir(parents=True, exist_ok=True)

    dest_tims = user_root / "raw_tim_sheets"
    dest_poses = user_root / "amelia_poses"
    dest_gifs = user_root / "animations_gif"
    dest_cliff = user_root / "background_cliff"
    dest_hud = user_root / "hud_ui"
    dest_quads = user_root / "individual_quads"

    for d in (dest_tims, dest_poses, dest_gifs, dest_cliff, dest_hud, dest_quads):
        if d.is_dir():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)

    # 1. Copy raw TIM sheets
    for f in raw_tims_dir.glob("*.png"):
        shutil.copy2(f, dest_tims / f.name)

    # 2. Copy amelia poses
    if amelia_poses_dir.is_dir():
        shutil.copytree(amelia_poses_dir, dest_poses, dirs_exist_ok=True)

    # 3. Copy animated GIFs
    for f in gifs_dir.glob("*.gif"):
        shutil.copy2(f, dest_gifs / f.name)

    # 4. Copy background cliff
    for f in cliff_dir.glob("*.png"):
        shutil.copy2(f, dest_cliff / f.name)

    # 5. Copy HUD & UI
    if hud_dir.is_dir():
        shutil.copytree(hud_dir, dest_hud, dirs_exist_ok=True)

    # 6. Copy individual quads
    if quads_dir.is_dir():
        shutil.copytree(quads_dir, dest_quads, dirs_exist_ok=True)


def generate_sprites_report(
    tim_infos: Dict[int, Dict[str, Any]],
    ama_meta: Dict[int, Dict[str, Any]],
    report_path: Path,
) -> None:
    """Generate Markdown report detailing TIMs, AMAs, quads, and palettes."""
    lines = [
        "# Slayers Royal (PS1) — Amelia's Cliff Jump Sprite Extraction Report",
        "",
        "## 1. Executive Summary",
        "",
        "- **Minigame**: Прыжок Амелии / Amelia Cliff Jump (`amelia_climb`)",
        "- **Source Archive**: `SMINI.UNT` Entry 1",
        "- **Disc Location**: LBA 223787 + 321 (339 sectors = 694,272 bytes)",
        "- **Container**: PMA (42 raw files: 12 TIM textures + 30 AMA animations)",
        "- **Target Directory**: `/home/samvel/Downloads/Telegram Desktop/Slayers Royal/AMELIA_RAW_SPRITES/`",
        "",
        "---",
        "",
        "## 2. TIM Texture Sheets Catalog (12 TIMs)",
        "",
        "| TIM | Dimensions | BPP | VRAM (X, Y) | Palettes | Colors | Content Description |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|:---|",
    ]

    tim_descriptions = {
        0: "HUD, UI, combo window frame, button prompts, banners (JUSTICE, LOVE, SPIRIT, Amelia Jump)",
        1: "Effects, Amelia portrait, dust clouds, speech balloons, energy beam & spark quads",
        2: "Amelia character sheet 1 (intro stance, jump takeoff, falling idle, pose transitions)",
        3: "Amelia character sheet 2 (acrobatic poses A, B, C, aerial twirls, dynamic kicks)",
        4: "Amelia character sheet 3 (Grand Justice Pose S, cape flairs, mid-air flips, spins)",
        5: "Amelia character sheet 4 (ground touchdown, splat faceplant, dazed, recover, victory)",
        6: "Amelia character sheet 5 (additional pose components and gestures)",
        7: "Amelia character sheet 6 (radiant aura burst, impact flash, climax justice speech)",
        8: "Cliff backdrop Layer 1: Top cliff ledge, sky, horizon (320x256)",
        9: "Cliff backdrop Layer 2: Middle vertical rock face wall (320x256)",
        10: "Cliff backdrop Layer 3: Bottom ground landing zone and grass (320x256)",
        11: "Font sheet & authentic PlayStation controller button glyphs (○, ↑, ↓, →, ←)",
    }

    for tid, info in sorted(tim_infos.items()):
        clut = info.get("clut")
        pal_count = clut["palettes"] if clut else 1
        colors = clut["colors"] if clut else (16 if info["bpp_mode"] == 0 else 256)
        desc = tim_descriptions.get(tid, "Texture sheet")
        lines.append(
            f"| TIM {tid:02d} | {info['pixel_width']}x{info['height']} | {info['bpp']} | "
            f"({info['vram_x']}, {info['vram_y']}) | {pal_count} | {colors} | {desc} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 3. PS1 VRAM Architecture & TPAGE Register Mapping",
        "",
        "The PS1 GPU addressing maps hardware TPAGE values directly to the PMA TIM textures:",
        "",
        "| TPAGE (Hex) | VRAM X | VRAM Y | BPP Mode | Semi-Trans | Target TIM |",
        "|:---:|:---:|:---:|:---:|:---:|:---:|",
        "| `0x06` | 384 | 0 | 4bpp | None | **TIM 01** (Effects & UI) |",
        "| `0x66` | 384 | 0 | 4bpp | Mode 3 (Add) | **TIM 01** (Sparks & Beam) |",
        "| `0x87` | 448 | 0 | 8bpp | None | **TIM 02** (Amelia Sheet 1) |",
        "| `0xE7` | 448 | 0 | 8bpp | Mode 3 (Add) | **TIM 02** (Amelia Sheet 1 Semi-Trans) |",
        "| `0x89` | 576 | 0 | 8bpp | None | **TIM 03** (Amelia Sheet 2) |",
        "| `0x8B` | 704 | 0 | 8bpp | None | **TIM 04** (Amelia Sheet 3) |",
        "| `0x8D` | 832 | 0 | 8bpp | None | **TIM 05** (Amelia Sheet 4) |",
        "| `0xD7` | 448 | 256 | 8bpp | Mode 2 (Sub) | **TIM 07** (Amelia Sheet 6 / Flash) |",
        "",
        "---",
        "",
        "## 4. AMA Animations Catalog (30 Animations, Files 12..41)",
        "",
        "| AMA | MIPS Anim | Action Identifier | Category | Frames | Steps | Ticks (1/60s) | Canvas Size | Bounding Box | Key Feature |",
        "|:---:|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---|",
    ])

    for a_idx, meta in sorted(ama_meta.items()):
        act_id = meta["action_id"]
        title = meta["title"]
        cat = meta["category"]
        nf = meta["num_frames"]
        nt = meta["num_timeline"]
        ticks = meta["total_ticks"]
        sz = f"{meta['size'][0]}x{meta['size'][1]}"
        bb = f"({meta['bbox'][0]},{meta['bbox'][1]})-({meta['bbox'][2]},{meta['bbox'][3]})"
        lines.append(
            f"| AMA {a_idx:02d} | `Anim {meta['anim_id']:02d}` | `{act_id}` | {cat} | {nf} | {nt} | {ticks} | {sz} | {bb} | {title} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. Background Cliff Architecture",
        "",
        "- **Slices**: 3 vertical layers of 320x256 each:",
        "  1. `cliff_layer_01_top_sky_320x256.png` (TIM 08): Ledge at cliff top with blue sky and horizon.",
        "  2. `cliff_layer_02_middle_wall_320x256.png` (TIM 09): Vertical rock wall and cliff face.",
        "  3. `cliff_layer_03_bottom_ground_320x256.png` (TIM 10): Lawn / ground landing zone with grass.",
        "- **Stitched Background**: `cliff_full_320x768.png` (320x768) provides a continuous vertical panorama.",
        "- **Scrolling Logic**: As Amelia falls, the camera scrolls vertically downward along the 768px height from Y=0 to Y=544.",
        "",
        "---",
        "",
        "## 6. HUD & UI Elements Catalog",
        "",
        "- **Combo Window**: `combo_window_frame.png` (96x64 stone-carved frame).",
        "- **Controller Button Glyphs** (TIM 11 authentic 16x16 tiles):",
        "  * `glyph_circle_16x16.png` (○ Circle button, GID `0x006B`)",
        "  * `glyph_arrow_up_16x16.png` (↑ Up arrow, GID `0x0074`)",
        "  * `glyph_arrow_down_16x16.png` (↓ Down arrow, GID `0x0075`)",
        "  * `glyph_arrow_right_16x16.png` (→ Right arrow, GID `0x0076`)",
        "  * `glyph_arrow_left_16x16.png` (← Left arrow, GID `0x0077`)",
        "- **Minigame Banners** (TIM 00):",
        "  * `banner_title_amelia_jump.png`: Japanese title logo «アメリアジャンプ».",
        "  * `banner_justice.png`: «JUSTICE».",
        "  * `banner_spirit.png`: «SPIRIT».",
        "  * `banner_love.png`: «LOVE».",
        "  * `banner_grand_success.png`: Japanese victory banner «大成功».",
        "- **Portraits and Effects** (TIM 01):",
        "  * `portrait_amelia_tim01.png`: Amelia bust portrait (88x128).",
        "  * `dust_cloud_silhouette_small.png` / `dust_cloud_silhouette_large.png`: Landing impact clouds.",
        "  * `speech_bubble_small.png` / `speech_bubble_medium.png`: Dialogue callouts.",
        "  * `wings_aura_effect.png`: Radiant energy aura wings.",
        "",
        "---",
        "",
        "## 7. Mirror Directory Structure for User Preparation",
        "",
        "Assets mirrored to `/home/samvel/Downloads/Telegram Desktop/Slayers Royal/AMELIA_RAW_SPRITES/`:",
        "```",
        "AMELIA_RAW_SPRITES/",
        "├── raw_tim_sheets/             # 12 TIM textures across all palettes",
        "├── amelia_poses/               # 30 organized action folders with PNG frames",
        "│   ├── 01_jump_prep_ledge/",
        "│   ├── 02_cliff_speech_intro/",
        "│   ├── 03_jump_takeoff/",
        "│   ├── 04_falling_idle/",
        "│   ├── 06_pose_a_heroic_strike/",
        "│   ├── 07_pose_b_flying_kick/",
        "│   ├── 08_pose_c_justice_twirl/",
        "│   ├── 11_pose_s_grand_justice/",
        "│   ├── 17_ground_landing/",
        "│   ├── 18_crash_landing_splat/",
        "│   ├── 23_victory_fist_pump/",
        "│   └── ...",
        "├── animations_gif/             # 30 animated GIFs matching timeline steps",
        "├── background_cliff/           # cliff_full_320x768.png + 3 vertical layers",
        "├── hud_ui/                     # combo window, glyphs, banners, portraits",
        "└── individual_quads/           # raw extracted quads per AMA animation",
        "```",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[✓] Generated technical report at {report_path}")


def main() -> None:
    """Run Amelia's Jump minigame sprite extraction pipeline."""
    parser = argparse.ArgumentParser(description="Amelia Sprite Extraction Pipeline")
    parser.add_argument("--disc", type=Path, default=None, help="Path to disc image .bin")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing files")
    args = parser.parse_args()

    disc_path = args.disc or get_disc_path()
    print(f"[*] Reading SMINI.UNT Entry 1 from {disc_path}...")
    e1_data = read_smini_entry_1(disc_path)
    print(f"[✓] Read Entry 1: {len(e1_data):,} bytes (339 sectors).")

    if args.dry_run:
        print("[*] Dry run mode — skipping file export.")
        return

    # 1. Unpack PMA container
    print(f"[*] Unpacking PMA container into {RAW_PMA_DIR}...")
    file_records = unpack_pma(e1_data, RAW_PMA_DIR)
    print(f"[✓] Unpacked {len(file_records)} files (12 TIMs, 30 AMAs).")

    # 2. Decode all 12 TIM textures across all palettes
    print(f"[*] Decoding 12 TIM textures into {RAW_TIMS_DIR}...")
    tim_infos = {}
    for i in range(12):
        tim_bytes = (RAW_PMA_DIR / f"file_{i:02d}.tim").read_bytes()
        prefix = f"tim_{i:02d}"
        info, saved = decode_tim_palettes(tim_bytes, prefix, RAW_TIMS_DIR)
        tim_infos[i] = info
        print(f"    - TIM {i:02d}: {info['pixel_width']}x{info['height']} {info['bpp']}, {len(saved)} palette(s)")

    # 3. Parse all 30 AMA files
    print("[*] Parsing 30 AMA animation files...")
    amas = {}
    for i in range(12, 42):
        ama_bytes = (RAW_PMA_DIR / f"file_{i:02d}.ama").read_bytes()
        ama = parse_ama(ama_bytes, i)
        amas[i] = ama

    # 4. Render composite frames, individual quads, and animated GIFs
    print(f"[*] Rendering composite frames and GIFs into {COMPOSITE_DIR}...")
    ama_meta = render_ama_animations(
        amas,
        RAW_TIMS_DIR,
        COMPOSITE_DIR,
        INDIVIDUAL_QUADS_DIR,
        ANIMATIONS_GIF_DIR,
    )
    print(f"[✓] Rendered all {len(ama_meta)} AMA animations.")

    # 5. Extract background cliff layers
    print(f"[*] Extracting background cliff layers into {BACKGROUND_CLIFF_DIR}...")
    cliff_assets = extract_background_cliff(RAW_TIMS_DIR, BACKGROUND_CLIFF_DIR)
    print(f"[✓] Created stitched 320x768 background and 3 cliff layers.")

    # 6. Extract HUD & UI elements
    print(f"[*] Extracting HUD & UI elements into {HUD_UI_DIR}...")
    hud_assets = extract_hud_ui_assets(RAW_TIMS_DIR, HUD_UI_DIR)
    print(f"[✓] Extracted {len(hud_assets)} HUD and UI elements.")

    # 7. Organize Amelia poses by action
    print(f"[*] Organizing Amelia poses into {AMELIA_POSES_DIR}...")
    organize_amelia_poses(COMPOSITE_DIR, AMELIA_POSES_DIR, ama_meta)
    print(f"[✓] Organized poses across {len(ama_meta)} action directories.")

    # 8. Mirror to user directory
    print(f"[*] Mirroring assets to {TARGET_USER_DIR}...")
    populate_user_directories(
        TARGET_USER_DIR,
        RAW_TIMS_DIR,
        AMELIA_POSES_DIR,
        ANIMATIONS_GIF_DIR,
        BACKGROUND_CLIFF_DIR,
        HUD_UI_DIR,
        INDIVIDUAL_QUADS_DIR,
    )
    print(f"[✓] Mirrored all assets to {TARGET_USER_DIR}.")

    # 9. Generate technical Markdown report
    print(f"[*] Generating technical report at {REPORT_FILE}...")
    generate_sprites_report(tim_infos, ama_meta, REPORT_FILE)
    print("[*] Amelia sprite extraction pipeline completed successfully!")


if __name__ == "__main__":
    main()
