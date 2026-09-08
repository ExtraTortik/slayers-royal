#!/usr/bin/env python3
"""Inspect, decode, and verify character lore cards in Slayers Royal PS1 disc images.

This tool reverse-engineers and catalogs the character lore cards and help screens
stored in PROG.UNT and OPT.UNT across both the original Japanese release (downloads/sr.bin)
and the patched image (localization-output/ru/slayers_royal_ru.bin).
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image

# Import unt_lz decompressor from patch_repo if available
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "patch_repo"))
from localization.unt_lz import decompress

SECTOR_SIZE = 2352
USER_OFFSET = 24
USER_SIZE = 2048

# Known card specifications
# Each entry corresponds to an in-game lore / explanation card.
# Most cards are composed of an 8bpp background TIM (PROG.UNT) and a 4bpp text overlay TIM (PROG.UNT),
# with an optional title banner TIM in OPT.UNT.
CARD_CATALOG = [
    {
        "id": "lina",
        "name": "Lina Inverse",
        "jp_title": "［り］リナ＝インバース",
        "en_title": "LINA INVERSE",
        "art_entry": 31,
        "text_entry": 32,
        "opt_title_entry": 182,
        "type": "split_card",
        "trigger_scene": None,
    },
    {
        "id": "gourry",
        "name": "Gourry Gabriev",
        "jp_title": "［が］ガウリィ=ガブリエフ",
        "en_title": "GOURRY GABRIEV",
        "art_entry": 33,
        "text_entry": 34,
        "opt_title_entry": 183,
        "type": "split_card",
        "trigger_scene": None,
    },
    {
        "id": "naga",
        "name": "Naga the White Serpent",
        "jp_title": "［さ］白蛇のナーガ（サーペントのナーガ）",
        "en_title": "NAGA THE SERPENT",
        "art_entry": 35,
        "text_entry": 36,
        "opt_title_entry": 184,
        "type": "split_card",
        "trigger_scene": "0x03B",
        "trigger_record": "E00D",
        "choice_index": 1,
    },
    {
        "id": "map_controls",
        "name": "Map Screen Controls",
        "jp_title": "［ば］場所画面の説明",
        "en_title": "MAP SCREEN CONTROLS",
        "art_entry": 37,
        "text_entry": None,
        "opt_title_entry": None,
        "type": "combined_8bpp",
        "trigger_scene": "0x03B",
        "trigger_record": "E01A",
        "choice_index": 1,
    },
    {
        "id": "spell_traits",
        "name": "Spell Traits Explanation",
        "jp_title": "［じ］呪文の特性の説明",
        "en_title": "SPELL TRAITS",
        "art_entry": 38,
        "text_entry": None,
        "opt_title_entry": 186,
        "type": "combined_8bpp",
        "trigger_scene": "0x03C",
        "trigger_record": "E028",
        "choice_index": 1,
    },
    {
        "id": "rezarium_legend",
        "name": "Legend of Rezarium",
        "jp_title": "［れ］レザリアムの伝説",
        "en_title": "LEGEND OF LEZARIAM",
        "art_entry": 39,
        "text_entry": 40,
        "opt_title_entry": 187,
        "type": "split_card",
        "trigger_scene": "0x03C",
        "trigger_record": "E045",
        "choice_index": 1,
    },
    {
        "id": "campaign_guide",
        "name": "Inn Campaign Guide",
        "jp_title": "［き］キャンペーンの説明",
        "en_title": "CAMPAIGN GUIDE",
        "art_entry": 41,
        "text_entry": None,
        "opt_title_entry": 188,
        "type": "combined_8bpp",
        "trigger_scene": "0x03C",
        "trigger_record": "E079",
        "choice_index": 1,
    },
    {
        "id": "necklace",
        "name": "Necklaces of Rezarium",
        "jp_title": "［れ］レザリアムの首飾り",
        "en_title": "LEZARIAM NECKLACE",
        "art_entry": 42,
        "text_entry": 43,
        "opt_title_entry": 189,
        "type": "split_card",
        "trigger_scene": "0x03D",
        "trigger_record": "E0E9",
        "choice_index": 1,
    },
    {
        "id": "zelgadis",
        "name": "Zelgadis Greywords",
        "jp_title": "［ぜ］ゼルガディス",
        "en_title": "ZELGADIS",
        "art_entry": 44,
        "text_entry": 45,
        "opt_title_entry": 190,
        "type": "split_card",
        "trigger_scene": "0x03E / 0x04B",
        "trigger_record": "E19C / E11B",
        "choice_index": 1,
    },
    {
        "id": "amelia",
        "name": "Amelia Wil Tesla Seyruun",
        "jp_title": "［あ］アメリア=ウィル=テスラ=セイルーン",
        "en_title": "AMELIA WIL TESLA SEYRUUN",
        "art_entry": 46,
        "text_entry": 47,
        "opt_title_entry": 191,
        "type": "split_card",
        "trigger_scene": "0x03E",
        "trigger_record": "E170",
        "choice_index": 1,
    },
    {
        "id": "sylphiel",
        "name": "Sylphiel Nels Lahda",
        "jp_title": "［し］シルフィール＝ネルス＝ラーダ",
        "en_title": "SYLPHIEL NELS LAHDA",
        "art_entry": 48,
        "text_entry": 49,
        "opt_title_entry": 192,
        "type": "split_card",
        "trigger_scene": "0x043",
        "trigger_record": "E1B8",
        "choice_index": 1,
    },
    {
        "id": "rezarium_magic",
        "name": "Magic of Rezarium",
        "jp_title": "［れ］レザリアムの魔法",
        "en_title": "LEZARIAM MAGIC",
        "art_entry": 50,
        "text_entry": 51,
        "opt_title_entry": 193,
        "type": "split_card",
        "trigger_scene": "0x043",
        "trigger_record": "E1C3",
        "choice_index": 1,
    },
    {
        "id": "galef",
        "name": "Galef Kainsard",
        "jp_title": "［が］ガレフ＝カインザード",
        "en_title": "GALEV KAINZARD",
        "art_entry": 52,
        "text_entry": 53,
        "opt_title_entry": None,
        "type": "split_card",
        "trigger_scene": "0x04F",
        "trigger_record": "U04F-S066",
        "choice_index": 1,
    },
]


@dataclass
class ArchiveEntry:
    index: int
    start_sector: int
    sector_count: int

    @property
    def offset(self) -> int:
        return self.start_sector * USER_SIZE

    @property
    def size(self) -> int:
        return self.sector_count * USER_SIZE


def read_sector(disc_path: Path, lba: int) -> bytes:
    with disc_path.open("rb") as f:
        f.seek(lba * SECTOR_SIZE + USER_OFFSET)
        return f.read(USER_SIZE)


def read_extent(disc_path: Path, lba: int, size: int) -> bytes:
    sectors = (size + USER_SIZE - 1) // USER_SIZE
    with disc_path.open("rb") as f:
        buf = bytearray()
        for s in range(sectors):
            f.seek((lba + s) * SECTOR_SIZE + USER_OFFSET)
            buf.extend(f.read(USER_SIZE))
        return bytes(buf[:size])


def parse_iso_dir(disc_path: Path, lba: int, size: int) -> dict[str, tuple[int, int]]:
    data = read_extent(disc_path, lba, size)
    pos = 0
    records: dict[str, tuple[int, int]] = {}
    while pos < size:
        length = data[pos]
        if length == 0:
            pos = ((pos // USER_SIZE) + 1) * USER_SIZE
            continue
        record = data[pos : pos + length]
        extent_lba = struct.unpack_from("<I", record, 2)[0]
        extent_size = struct.unpack_from("<I", record, 10)[0]
        name_len = record[32]
        name = record[33 : 33 + name_len].decode("ascii", errors="replace")
        records[name.split(";")[0]] = (extent_lba, extent_size)
        pos += length
    return records


def read_unt_index(archive_bytes: bytes) -> list[ArchiveEntry]:
    entries: list[ArchiveEntry] = []
    expected = 1
    for offset in range(0, USER_SIZE, 4):
        start = int.from_bytes(archive_bytes[offset : offset + 2], "little")
        count = int.from_bytes(archive_bytes[offset + 2 : offset + 4], "little")
        if start != expected or count == 0:
            break
        entries.append(ArchiveEntry(len(entries), start, count))
        expected += count
    return entries


def parse_tim(tim_bytes: bytes) -> dict[str, Any] | None:
    if len(tim_bytes) < 8 or tim_bytes[:4] != b"\x10\x00\x00\x00":
        return None
    flag = int.from_bytes(tim_bytes[4:8], "little")
    pmode = flag & 7
    has_clut = (flag & 8) != 0
    pos = 8
    clut_info = None
    if has_clut:
        clut_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
        clut_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
        clut_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
        clut_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
        clut_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")
        clut_info = {
            "x": clut_x,
            "y": clut_y,
            "w": clut_w,
            "h": clut_h,
            "len": clut_len,
            "num_colors": (clut_len - 12) // 2,
        }
        pos += clut_len
    img_len = int.from_bytes(tim_bytes[pos : pos + 4], "little")
    img_x = int.from_bytes(tim_bytes[pos + 4 : pos + 6], "little")
    img_y = int.from_bytes(tim_bytes[pos + 6 : pos + 8], "little")
    img_w = int.from_bytes(tim_bytes[pos + 8 : pos + 10], "little")
    img_h = int.from_bytes(tim_bytes[pos + 10 : pos + 12], "little")
    bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(pmode, 0)
    pixel_width = img_w * (4 if pmode == 0 else 2 if pmode == 1 else 1)

    return {
        "pmode": pmode,
        "bpp": bpp,
        "clut": clut_info,
        "vram_x": img_x,
        "vram_y": img_y,
        "vram_w": img_w,
        "vram_h": img_h,
        "pixel_width": pixel_width,
        "pixel_height": img_h,
        "data_len": img_len,
        "total_len": pos + img_len,
    }


def tim_to_rgba(tim_bytes: bytes, transparent_zero: bool = True) -> Image.Image | None:
    info = parse_tim(tim_bytes)
    if not info:
        return None
    pos = 8
    clut: list[tuple[int, int, int, int]] = []
    if info["clut"]:
        clut_len = info["clut"]["len"]
        clut_data = tim_bytes[pos + 12 : pos + clut_len]
        for c in range(0, len(clut_data), 2):
            raw = int.from_bytes(clut_data[c : c + 2], "little")
            r = (raw & 0x1F) << 3
            g = ((raw >> 5) & 0x1F) << 3
            b = ((raw >> 10) & 0x1F) << 3
            stp = (raw >> 15) & 1
            if c == 0 and transparent_zero:
                a = 0
            else:
                a = 255
            clut.append((r, g, b, a))
        pos += clut_len

    img_len = info["data_len"]
    pixel_data = tim_bytes[pos + 12 : pos + img_len]
    w = info["pixel_width"]
    h = info["pixel_height"]
    pmode = info["pmode"]

    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pixels: list[tuple[int, int, int, int]] = []
    if pmode == 0:  # 4bpp
        for b in pixel_data:
            c0 = b & 0x0F
            c1 = (b >> 4) & 0x0F
            pixels.append(clut[c0] if c0 < len(clut) else (0, 0, 0, 0))
            pixels.append(clut[c1] if c1 < len(clut) else (0, 0, 0, 0))
    elif pmode == 1:  # 8bpp
        for b in pixel_data:
            pixels.append(clut[b] if b < len(clut) else (0, 0, 0, 0))
    elif pmode == 2:  # 16bpp
        for c in range(0, len(pixel_data), 2):
            raw = int.from_bytes(pixel_data[c : c + 2], "little")
            r = (raw & 0x1F) << 3
            g = ((raw >> 5) & 0x1F) << 3
            b = ((raw >> 10) & 0x1F) << 3
            pixels.append((r, g, b, 255))
    im.putdata(pixels[: w * h])
    return im


def inspect_card(
    card_spec: dict[str, Any],
    prog_archive: bytes,
    prog_index: list[ArchiveEntry],
    opt_archive: bytes,
    opt_index: list[ArchiveEntry],
    prog_lba: int,
) -> dict[str, Any]:
    card_id = card_spec["id"]
    art_entry_idx = card_spec["art_entry"]
    text_entry_idx = card_spec["text_entry"]
    title_entry_idx = card_spec["opt_title_entry"]

    # Background art entry
    art_e = prog_index[art_entry_idx]
    art_raw = prog_archive[art_e.offset : art_e.offset + art_e.size]
    art_dec, _ = decompress(art_raw)
    art_info = parse_tim(art_dec)

    # Text overlay entry (if separate)
    text_info = None
    text_sectors = 0
    text_raw_size = 0
    text_decomp_size = 0
    if text_entry_idx is not None:
        text_e = prog_index[text_entry_idx]
        text_raw = prog_archive[text_e.offset : text_e.offset + text_e.size]
        text_dec, _ = decompress(text_raw)
        text_info = parse_tim(text_dec)
        text_sectors = text_e.sector_count
        text_raw_size = len(text_raw)
        text_decomp_size = len(text_dec)

    # Title banner entry (in OPT.UNT)
    title_info = None
    if title_entry_idx is not None:
        opt_e = opt_index[title_entry_idx]
        title_raw = opt_archive[opt_e.offset : opt_e.offset + opt_e.size]
        # Check if raw or lz
        if title_raw[:4] == b"\x10\x00\x00\x00":
            title_info = parse_tim(title_raw)
        elif title_raw[0] in (0, 1):
            title_dec, _ = decompress(title_raw)
            title_info = parse_tim(title_dec)

    result = {
        "id": card_id,
        "name": card_spec["name"],
        "jp_title": card_spec["jp_title"],
        "en_title": card_spec["en_title"],
        "type": card_spec["type"],
        "trigger": {
            "scene": card_spec.get("trigger_scene"),
            "record": card_spec.get("trigger_record"),
            "choice_index": card_spec.get("choice_index"),
        },
        "background_art": {
            "archive": "PROG.UNT",
            "entry_index": art_entry_idx,
            "entry_hex": f"0x{art_entry_idx:03X}",
            "lba": prog_lba + art_e.start_sector,
            "sectors": art_e.sector_count,
            "raw_size": len(art_raw),
            "decompressed_size": len(art_dec),
            "format": f"{art_info['bpp']}bpp TIM" if art_info else "Unknown",
            "resolution": f"{art_info['pixel_width']}x{art_info['pixel_height']}"
            if art_info
            else "N/A",
        },
        "text_overlay": {
            "archive": "PROG.UNT" if text_entry_idx else None,
            "entry_index": text_entry_idx,
            "entry_hex": f"0x{text_entry_idx:03X}" if text_entry_idx else None,
            "lba": (prog_lba + prog_index[text_entry_idx].start_sector)
            if text_entry_idx
            else None,
            "sectors": text_sectors,
            "raw_size": text_raw_size,
            "decompressed_size": text_decomp_size,
            "format": f"{text_info['bpp']}bpp TIM" if text_info else "Embedded in Art",
            "resolution": f"{text_info['pixel_width']}x{text_info['pixel_height']}"
            if text_info
            else "N/A",
        },
        "title_banner": {
            "archive": "OPT.UNT" if title_entry_idx else None,
            "entry_index": title_entry_idx,
            "entry_hex": f"0x{title_entry_idx:03X}" if title_entry_idx else None,
            "resolution": f"{title_info['pixel_width']}x{title_info['pixel_height']}"
            if title_info
            else "N/A",
            "format": f"{title_info['bpp']}bpp TIM" if title_info else "N/A",
        },
    }
    return result


def export_card_image(
    card_spec: dict[str, Any],
    prog_archive: bytes,
    prog_index: list[ArchiveEntry],
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    card_id = card_spec["id"]
    art_idx = card_spec["art_entry"]
    text_idx = card_spec["text_entry"]

    # Background art
    art_e = prog_index[art_idx]
    art_dec, _ = decompress(prog_archive[art_e.offset : art_e.offset + art_e.size])
    im_art = tim_to_rgba(art_dec, transparent_zero=False)

    if text_idx is not None:
        text_e = prog_index[text_idx]
        text_dec, _ = decompress(
            prog_archive[text_e.offset : text_e.offset + text_e.size]
        )
        im_text = tim_to_rgba(text_dec, transparent_zero=True)
        im_text_opaque = tim_to_rgba(text_dec, transparent_zero=False)

        # Save individual assets
        if im_art:
            im_art.save(out_dir / f"{card_id}_art_entry_{art_idx:03d}.png")
        if im_text_opaque:
            im_text_opaque.save(out_dir / f"{card_id}_text_entry_{text_idx:03d}.png")

        # Save composite
        if im_art and im_text:
            composite = Image.alpha_composite(im_art.convert("RGBA"), im_text)
            composite.save(out_dir / f"{card_id}_composite.png")
    else:
        if im_art:
            im_art.save(out_dir / f"{card_id}_combined_entry_{art_idx:03d}.png")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect Slayers Royal character lore cards"
    )
    parser.add_argument(
        "--bin",
        type=Path,
        default=Path("localization-output/ru/slayers_royal_ru.bin"),
        help="Path to PS1 BIN image (default: localization-output/ru/slayers_royal_ru.bin)",
    )
    parser.add_argument(
        "--card",
        type=str,
        default="all",
        help="Card identifier (e.g. naga, lina, gourry, zelgadis, amelia, sylphiel, galef, or all)",
    )
    parser.add_argument(
        "--dump-images",
        type=Path,
        default=None,
        help="Directory to dump PNG image assets and composites",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON catalog",
    )
    args = parser.parse_args()

    disc_path = args.bin
    if not disc_path.exists():
        fallback = Path("downloads/sr.bin")
        if fallback.exists():
            disc_path = fallback
        else:
            sys.exit(f"Error: Disc image {args.bin} not found.")

    # Read ISO Root directory (LBA 16 -> PVD)
    pvd = read_sector(disc_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    root_dir = parse_iso_dir(disc_path, root_lba, root_size)

    prog_lba, prog_size = root_dir["PROG.UNT"]
    opt_lba, opt_size = root_dir["OPT.UNT"]

    prog_archive = read_extent(disc_path, prog_lba, prog_size)
    opt_archive = read_extent(disc_path, opt_lba, opt_size)

    prog_index = read_unt_index(prog_archive)
    opt_index = read_unt_index(opt_archive)

    target_cards = (
        CARD_CATALOG
        if args.card.lower() == "all"
        else [c for c in CARD_CATALOG if c["id"] == args.card.lower()]
    )

    if not target_cards:
        sys.exit(f"Error: Unknown card '{args.card}'")

    reports = []
    for c in target_cards:
        info = inspect_card(
            c, prog_archive, prog_index, opt_archive, opt_index, prog_lba
        )
        reports.append(info)
        if args.dump_images:
            export_card_image(c, prog_archive, prog_index, args.dump_images)

    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))
        return

    print("=" * 80)
    print(f"SLAYERS ROYAL PS1 CHARACTER LORE CARD INSPECTION REPORT")
    print(f"Target Disc: {disc_path.name} ({disc_path.stat().st_size:,} bytes)")
    print(f"PROG.UNT LBA: {prog_lba} ({len(prog_index)} entries)")
    print(f"OPT.UNT LBA:  {opt_lba} ({len(opt_index)} entries)")
    print("=" * 80)

    for r in reports:
        print(f"\n[Card ID: {r['id'].upper()}] - {r['name']}")
        print(f"  JP Title:   {r['jp_title']}")
        print(f"  EN Title:   {r['en_title']}")
        print(f"  Type:       {r['type']}")
        if r["trigger"]["scene"]:
            print(
                f"  Trigger:    Scene {r['trigger']['scene']} record {r['trigger']['record']} (choice {r['trigger']['choice_index']})"
            )
        art = r["background_art"]
        print(
            f"  Background: {art['archive']} Entry {art['entry_index']:3d} ({art['entry_hex']}) "
            f"LBA={art['lba']} Sectors={art['sectors']} ({art['raw_size']}B raw -> {art['decompressed_size']}B {art['format']} {art['resolution']})"
        )
        txt = r["text_overlay"]
        if txt["archive"]:
            print(
                f"  Text Layer: {txt['archive']} Entry {txt['entry_index']:3d} ({txt['entry_hex']}) "
                f"LBA={txt['lba']} Sectors={txt['sectors']} ({txt['raw_size']}B raw -> {txt['decompressed_size']}B {txt['format']} {txt['resolution']})"
            )
        else:
            print(f"  Text Layer: {txt['format']}")
        ban = r["title_banner"]
        if ban["archive"]:
            print(
                f"  Title Tim:  {ban['archive']} Entry {ban['entry_index']:3d} ({ban['entry_hex']}) {ban['format']} {ban['resolution']}"
            )
    print("=" * 80)


if __name__ == "__main__":
    main()
