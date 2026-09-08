"""Align Ren'Py Russian translation script with PS1 dialogue.po catalog."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Ensure patch_repo and tools are available
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCH_REPO = REPO_ROOT / "patch_repo"
if str(PATCH_REPO) not in sys.path:
    sys.path.insert(0, str(PATCH_REPO))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from localization.po import PoEntry, read_po, write_po
from localization.script import parse_target
from tools.text_wrapper import wrap_dialogue

SPEAKER_MAP = {
    "l": "Lina",
    "g": "Gourry",
    "n": "Naga",
    "z": "Zelgadis",
    "a": "Amelia",
    "s": "Sylphiel",
    "lk": "Lark",
    "kz": "Galef",
}


@dataclass
class RenPyItem:
    index: int
    line_num: int
    speaker: str
    text: str
    voice: Optional[str]
    jp_parts: list[str]
    en_parts: list[str]
    norm_jp: str
    matched_po: Optional[int] = None


def norm_jp(text: str) -> str:
    """Normalize Japanese text for comparison between PS1 disc encoding and Ren'Py comments."""
    if not text:
        return ""
    text = text.replace("\\n", "\n").replace("\\r", "\r")
    table = {
        "？": "?",
        "！": "!",
        "、": ",",
        "。": ".",
        "ー": "-",
        "‥": '"',
        "…": '"',
        "・": "",
        "゠": "-",
        "＝": "-",
        "〜": "~",
        "～": "~",
        "=": "-",
        "―": "-",
        "—": "-",
        "‐": "-",
        "（": "(",
        "）": ")",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "♥": "",
        "♡": "",
        "♪": "",
        " ": "",
        "　": "",
        "\n": "",
        "\r": "",
        "⁉": "!?",
        "~": "-",
        "-": "-",
        "middle-dot": "",
        "heart": "",
        "music": "",
        "spade": "",
        "”": '"',
        "“": '"',
    }
    for k, v in table.items():
        text = text.replace(k, v)
    # Map full-width digits and letters to half-width
    for i in range(10):
        text = text.replace(chr(ord("０") + i), str(i))
    for i in range(26):
        text = text.replace(chr(ord("Ａ") + i), chr(ord("A") + i))
        text = text.replace(chr(ord("ａ") + i), chr(ord("a") + i))
    return "".join(c for c in text if not c.isspace())


def parse_renpy_script(script_path: Path) -> list[RenPyItem]:
    """Parse dialogue lines, speakers, voice cues, and comments from script.rpy."""
    lines = script_path.read_text(encoding="utf-8").splitlines()
    items: list[RenPyItem] = []
    current_voice: Optional[str] = None
    voice_pattern = re.compile(r'^\s*voice\s+"([^"]+)"')

    dialogue_pattern = re.compile(
        r"""^(?:#\s*)?(?:([a-z0-9_]+|"(?:[^"\\]|\\.)*")\s+)?("((?:[^"\\]|\\.)*)")(?:\s*(.*))?$"""
    )

    skip_prefixes = (
        "$",
        "show ",
        "hide ",
        "scene ",
        "play ",
        "stop ",
        "queue ",
        "define ",
        "default ",
        "label ",
        "jump ",
        "call ",
        "return",
        "if ",
        "elif ",
        "else:",
        "while ",
        "transform ",
        "screen ",
        "menu:",
        "window ",
        "pause",
    )

    for line_idx, line in enumerate(lines):
        vm = voice_pattern.match(line)
        if vm:
            current_voice = vm.group(1)
            continue

        sline = line.strip()
        if not sline:
            continue

        if sline.startswith(skip_prefixes):
            continue

        if sline.startswith("#") and not ('"' in sline and "#(JP)" in sline):
            continue

        m = dialogue_pattern.match(sline)
        if not m:
            continue

        speaker = m.group(1) or ""
        text = m.group(3)
        rest = m.group(4) or ""

        # Extract Japanese comment parts
        jp_parts: list[str] = []
        en_parts: list[str] = []
        if "#(JP)" in sline:
            parts = sline.split("#(JP)")
            for p in parts[1:]:
                jp = p.split("#(EN)")[0].strip()
                if not jp and "#(EN)" in p:
                    en_rest = p.split("#(EN)")[1].strip()
                    if any(ord(c) > 0x3000 for c in en_rest):
                        jp = en_rest
                if jp and jp not in ("—", "-"):
                    jp_parts.append(jp)

        if "#(EN)" in sline:
            parts = sline.split("#(EN)")
            for p in parts[1:]:
                en = p.split("#(JP)")[0].strip()
                if en and not any(ord(c) > 0x3000 for c in en):
                    en_parts.append(en)

        comb_jp = "".join(jp_parts)
        norm = norm_jp(comb_jp)

        items.append(
            RenPyItem(
                index=len(items),
                line_num=line_idx + 1,
                speaker=speaker,
                text=text,
                voice=current_voice,
                jp_parts=jp_parts,
                en_parts=en_parts,
                norm_jp=norm,
            )
        )
        current_voice = None

    return items


def speaker_matches(r_spk: str, po_spk: Optional[str]) -> bool:
    """Check if Ren'Py speaker tag aligns with PO probable speaker hint."""
    if not po_spk:
        return True
    mapped = SPEAKER_MAP.get(r_spk, r_spk.strip('"'))
    return mapped.lower() == po_spk.lower()


def align_and_update(
    renpy_items: list[RenPyItem], po_entries: list[PoEntry]
) -> tuple[list[PoEntry], dict[str, int]]:
    """Align Ren'Py dialogue lines with PO entries using Pass 1 and Pass 2."""
    po_data = []
    po_by_norm: dict[str, list[int]] = {}

    for idx, e in enumerate(po_entries):
        n = norm_jp(e.source)
        spk = [c for c in e.comments if "speaker" in c]
        spk_name = spk[0].replace("Probable speaker: ", "") if spk else None
        allow_cont = not any("cannot add another page" in c for c in e.comments)
        po_data.append(
            {
                "idx": idx,
                "entry": e,
                "norm": n,
                "speaker": spk_name,
                "allow_continuation": allow_cont,
                "matched_renpy": None,
                "method": None,
            }
        )
        po_by_norm.setdefault(n, []).append(idx)

    # ---------------------------------------------------------
    # Pass 1: Exact normalized Japanese matching (chronological)
    # ---------------------------------------------------------
    po_pointer = 0
    pass1_count = 0

    for r in renpy_items:
        if not r.norm_jp and not r.jp_parts:
            continue

        matched_idx: Optional[int] = None
        if r.norm_jp in po_by_norm:
            cands = [i for i in po_by_norm[r.norm_jp] if po_data[i]["matched_renpy"] is None]
            if cands:
                cands_after = [i for i in cands if i >= po_pointer]
                matched_idx = cands_after[0] if cands_after else cands[0]
        else:
            for p in r.jp_parts:
                pn = norm_jp(p)
                if pn in po_by_norm:
                    cands = [i for i in po_by_norm[pn] if po_data[i]["matched_renpy"] is None]
                    if cands:
                        cands_after = [i for i in cands if i >= po_pointer]
                        matched_idx = cands_after[0] if cands_after else cands[0]
                        break

        if matched_idx is not None:
            po_data[matched_idx]["matched_renpy"] = r
            po_data[matched_idx]["method"] = "exact_jp"
            r.matched_po = matched_idx
            po_pointer = matched_idx
            pass1_count += 1

    # ---------------------------------------------------------
    # Pass 2: Sequential alignment in scenes using speaker matching
    # ---------------------------------------------------------
    pass2_count = 0

    # Build gap intervals between matched anchors
    gaps: list[tuple[Optional[int], Optional[int], list[RenPyItem]]] = []
    curr_gap: list[RenPyItem] = []
    prev_po: Optional[int] = None

    for r in renpy_items:
        if r.matched_po is None:
            curr_gap.append(r)
        else:
            if curr_gap and prev_po is not None:
                gaps.append((prev_po, r.matched_po, curr_gap))
                curr_gap = []
            prev_po = r.matched_po

    for prev_p, next_p, r_list in gaps:
        if prev_p is None or next_p is None or prev_p >= next_p:
            continue
        cands = [p for p in po_data[prev_p + 1 : next_p] if p["matched_renpy"] is None]
        if not cands:
            continue

        # Case A: Exact 1-to-1 match in gap
        if len(r_list) == len(cands):
            if all(speaker_matches(r.speaker, p["speaker"]) for r, p in zip(r_list, cands)):
                for r, p in zip(r_list, cands):
                    p["matched_renpy"] = r
                    p["method"] = "sequential_gap"
                    r.matched_po = p["idx"]
                    pass2_count += 1
                continue

        # Case B: Single Ren'Py item in gap
        if len(r_list) == 1:
            spk_cands = [p for p in cands if speaker_matches(r_list[0].speaker, p["speaker"])]
            if len(spk_cands) == 1:
                p_match = spk_cands[0]
                p_match["matched_renpy"] = r_list[0]
                p_match["method"] = "sequential_gap"
                r_list[0].matched_po = p_match["idx"]
                pass2_count += 1
            elif len(cands) == 1:
                p_match = cands[0]
                p_match["matched_renpy"] = r_list[0]
                p_match["method"] = "sequential_gap"
                r_list[0].matched_po = p_match["idx"]
                pass2_count += 1

    # ---------------------------------------------------------
    # Format matched Russian text using wrap_dialogue
    # ---------------------------------------------------------
    updated_entries: list[PoEntry] = []
    stats = {
        "total_po": len(po_entries),
        "total_renpy": len(renpy_items),
        "pass1_exact": pass1_count,
        "pass2_gap": pass2_count,
        "total_matched": pass1_count + pass2_count,
    }

    for p in po_data:
        entry = p["entry"]
        r = p["matched_renpy"]
        if r is not None and r.text:
            allow_cont = p["allow_continuation"]
            wrapped_text = wrap_dialogue(r.text, allow_continuation=allow_cont)
            # Guarantee parse_target validation passes
            delimiter = 0x00FD if allow_cont else 0x00FF
            parse_target(wrapped_text, delimiter, entry.context)
            updated_entries.append(
                PoEntry(
                    context=entry.context,
                    source=entry.source,
                    translation=wrapped_text,
                    comments=entry.comments,
                )
            )
        else:
            updated_entries.append(entry)

    return updated_entries, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Align Ren'Py Russian script with PS1 dialogue.po catalog."
    )
    parser.add_argument(
        "--renpy-dir",
        type=Path,
        default=Path("renpy_extracted/game"),
        help="Path to Ren'Py game directory containing script.rpy",
    )
    parser.add_argument(
        "--po",
        type=Path,
        default=Path("patch_repo/localization-work/ru/dialogue.po"),
        help="Input path to dialogue.po",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for updated dialogue.po (defaults to overwriting --po)",
    )

    args = parser.parse_args()

    renpy_dir: Path = args.renpy_dir
    script_path = renpy_dir / "script.rpy" if (renpy_dir / "script.rpy").exists() else renpy_dir
    if not script_path.exists():
        print(f"Error: Ren'Py script not found at {script_path}", file=sys.stderr)
        sys.exit(1)

    po_path: Path = args.po
    if not po_path.exists():
        print(f"Error: PO catalog not found at {po_path}", file=sys.stderr)
        sys.exit(1)

    out_path = args.out or po_path

    print(f"Parsing Ren'Py script: {script_path}")
    renpy_items = parse_renpy_script(script_path)
    print(f"Extracted {len(renpy_items)} dialogue items from Ren'Py script.")

    print(f"Reading PO catalog: {po_path}")
    po_entries = read_po(po_path)
    print(f"Loaded {len(po_entries)} segments across records.")

    print("Aligning dialogue lines and applying text wrapping...")
    updated_entries, stats = align_and_update(renpy_items, po_entries)

    print(f"Writing updated catalog: {out_path}")
    write_po(out_path, updated_entries, language="ru")

    pct1 = stats["pass1_exact"] / stats["total_po"] * 100
    pct2 = stats["pass2_gap"] / stats["total_po"] * 100
    pct_total = stats["total_matched"] / stats["total_po"] * 100

    print("\nAlignment Statistics:")
    print(f"  Total PO segments:     {stats['total_po']}")
    print(f"  Total Ren'Py lines:    {stats['total_renpy']}")
    print(f"  Pass 1 (Exact JP):     {stats['pass1_exact']} ({pct1:.1f}%)")
    print(f"  Pass 2 (Sequential):   {stats['pass2_gap']} ({pct2:.1f}%)")
    print(f"  Total Matched:         {stats['total_matched']} ({pct_total:.1f}%)")
    print("Done!")


if __name__ == "__main__":
    main()
