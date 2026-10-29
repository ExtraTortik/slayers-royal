# -*- coding: utf-8 -*-
"""core/sync_savestates.py — Живая синхронизация сейвстейтов DuckStation с RAM.

Назначение:
Патчит текстовые буферы и указатели прямо внутри файлов быстрых сохранений
эмулятора DuckStation (.sav). Позволяет видеть изменения текста в игре по
нажатию F3 (Load State) без необходимости перезагрузки игры с титульного экрана.

Поддерживает:
- Windows: %USERPROFILE%\\Documents\\DuckStation\\savestates\\
- Linux:   ~/.local/share/duckstation/savestates/
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import zlib
import struct


def find_duckstation_savestates(serial: str = "") -> list[Path]:
    """Поиск файлов сохранений DuckStation для заданной игры."""
    candidates = []

    # Windows путь
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        win_path = Path(user_profile) / "Documents" / "DuckStation" / "savestates"
        if win_path.is_dir():
            candidates.extend(win_path.glob(f"*{serial}*.sav" if serial else "*.sav"))

    # Linux путь
    home = os.environ.get("HOME")
    if home:
        linux_path = Path(home) / ".local" / "share" / "duckstation" / "savestates"
        if linux_path.is_dir():
            candidates.extend(linux_path.glob(f"*{serial}*.sav" if serial else "*.sav"))

    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def patch_savestate_ram(
    sav_path: Path | str,
    ram_offset_hex: int,
    payload_bytes: bytes,
    backup: bool = True
) -> bool:
    """Инъекция байтов в оперативную память внутри сейвстейта DuckStation.
    
    ram_offset_hex: физический адрес в 2 МБ пространстве RAM (например, 0x8004E5B0 -> смещение 0x4E5B0).
    """
    p = Path(sav_path)
    if not p.is_file():
        raise FileNotFoundError(f"Файл сейвстейта не найден: {p}")

    raw_sav = p.read_bytes()

    # DuckStation сохраняет память в zlib-сжатых блоках
    # В несжатых версиях 2 МБ RAM лежат непрерывным куском
    ram_target_offset = ram_offset_hex & 0x001FFFFF  # 2MB маска RAM

    # Поиск RAM-блока (сигнатура или размер 2097152 байт)
    ram_start = raw_sav.find(b"\x00\x00\x00\x00" * 8, 0x1000)

    if backup:
        bak_file = p.with_suffix(".sav.bak")
        if not bak_file.exists():
            bak_file.write_bytes(raw_sav)

    # Простая замена в несжатом сейве
    if len(raw_sav) >= 2 * 1024 * 1024:
        patched = bytearray(raw_sav)
        # Находим базовое смещение RAM
        pos = ram_target_offset
        if pos + len(payload_bytes) <= len(patched):
            patched[pos : pos + len(payload_bytes)] = payload_bytes
            p.write_bytes(bytes(patched))
            return True

    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Синхронизатор сейвстейтов DuckStation с RAM")
    parser.add_argument("--serial", default="", help="Серийный номер игры (например, SLPS-01363)")
    parser.add_argument("--list", action="store_true", help="Показать доступные сейвстейты")
    args = parser.parse_args()

    savs = find_duckstation_savestates(args.serial)
    print(f"Найдено сейвстейтов: {len(savs)}")
    for s in savs[:10]:
        print(f"  {s.name} ({s.stat().st_size} байт, изменён: {s.stat().st_mtime})")
