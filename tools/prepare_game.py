#!/usr/bin/env python3
"""Validate the user-supplied disc dump and create the canonical CUE sheet.

The build never ships game data.  Put your own Redump dump of *Slayers Royal*
(Japan, SLPS-01363) at ``downloads/sr.bin`` and run this script; it verifies
the SHA-256 and writes the exact 68-byte ``downloads/sr.cue`` the toolkit and
emulator expect.

Usage::

    python3 tools/prepare_game.py
    python3 tools/prepare_game.py --bin "D:\\dumps\\sr.bin" --cue "D:\\dumps\\sr.cue"
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def _configure_stdio() -> None:
    """Windows consoles default to cp1251/cp866; force UTF-8 so messages survive."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


_configure_stdio()

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPECTED_SIZE = 712_300_848
EXPECTED_SHA256 = "89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe"
CUE_BYTES = b'FILE "sr.bin" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n'


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate sr.bin and create sr.cue")
    parser.add_argument("--bin", type=Path, default=REPO_ROOT / "downloads" / "sr.bin")
    parser.add_argument("--cue", type=Path, default=None)
    parser.add_argument("--skip-hash", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    bin_path: Path = args.bin
    cue_path = args.cue or bin_path.with_suffix(".cue")

    if not bin_path.is_file():
        print(f"[ОШИБКА] Образ диска не найден: {bin_path}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Положите свой дамп Slayers Royal (Japan) сюда:", file=sys.stderr)
        print(f"  {REPO_ROOT / 'downloads' / 'sr.bin'}", file=sys.stderr)
        print("", file=sys.stderr)
        print(f"  размер : {EXPECTED_SIZE:,} байт".replace(",", " "), file=sys.stderr)
        print(f"  SHA-256: {EXPECTED_SHA256}", file=sys.stderr)
        return 2

    size = bin_path.stat().st_size
    if size != EXPECTED_SIZE:
        print(
            f"[ОШИБКА] Неверный размер {bin_path.name}: {size} байт, "
            f"ожидается {EXPECTED_SIZE} байт.",
            file=sys.stderr,
        )
        print("Нужен образ именно этого издания (SLPS-01363), а не ISO-конверсия.", file=sys.stderr)
        return 3

    if not args.skip_hash:
        print(f"[*] Проверка SHA-256: {bin_path.name} ...")
        actual = _sha256(bin_path)
        if actual != EXPECTED_SHA256:
            print("[ОШИБКА] Контрольная сумма не совпадает.", file=sys.stderr)
            print(f"  ожидается: {EXPECTED_SHA256}", file=sys.stderr)
            print(f"  получено : {actual}", file=sys.stderr)
            return 3

    if not cue_path.is_file():
        cue_path.write_bytes(CUE_BYTES)
        print(f"[✓] Создан CUE: {cue_path}")
    else:
        content = cue_path.read_bytes()
        if content != CUE_BYTES:
            print(f"[!] CUE уже существует и отличается от канонического: {cue_path}")
            print("    Ожидаемое содержимое (CRLF):")
            print('    FILE "sr.bin" BINARY')
            print("      TRACK 01 MODE2/2352")
            print("        INDEX 01 00:00:00")

    print(f"[✓] Образ диска проверен: {bin_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
