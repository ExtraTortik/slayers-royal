# -*- coding: utf-8 -*-
"""core/patch_maker.py — Генератор релизных дельта-патчей (xdelta3 / PPF).

Позволяет создавать легковесные патчи (2-10 МБ) вместо распространения
полных образов дисков (700 МБ), что легально и удобно для пользователей.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def find_xdelta3_binary() -> str | None:
    """Поиск бинарника xdelta3 в системе."""
    # Проверка в PATH
    found = shutil.which("xdelta3")
    if found:
        return found

    # Проверка в локальных папках
    candidates = [
        Path("tools/bin/xdelta3.exe"),
        Path("tools/bin/xdelta3"),
        Path("xdelta3.exe"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c.resolve())
    return None


def create_xdelta_patch(orig_bin: Path | str, mod_bin: Path | str, out_patch: Path | str) -> bool:
    """Создание xdelta3 патча между оригиналом и модификацией."""
    xdelta_bin = find_xdelta3_binary()
    orig = Path(orig_bin)
    mod = Path(mod_bin)
    out = Path(out_patch)

    if not orig.is_file():
        raise FileNotFoundError(f"Оригинальный образ не найден: {orig}")
    if not mod.is_file():
        raise FileNotFoundError(f"Модифицированный образ не найден: {mod}")

    out.parent.mkdir(parents=True, exist_ok=True)

    if not xdelta_bin:
        print("[!] Бинарник xdelta3 не найден в PATH или tools/bin.")
        print("[!] Скачайте xdelta3 с https://github.com/jmacd/xdelta/releases")
        return False

    cmd = [xdelta_bin, "-e", "-f", "-s", str(orig), str(mod), str(out)]
    print(f"[*] Выполнение: {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode == 0:
        print(f"[✓] Патч успешно создан: {out} ({out.stat().st_size // 1024} КБ)")
        return True
    return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Создатель дельта-патчей xdelta3 для PS1")
    parser.add_argument("--orig", required=True, help="Путь к оригинальному bin")
    parser.add_argument("--mod", required=True, help="Путь к модифицированному bin")
    parser.add_argument("--out", default="release/patch.xdelta", help="Выходной файл патча")
    args = parser.parse_args()

    success = create_xdelta_patch(args.orig, args.mod, args.out)
    sys.exit(0 if success else 1)
