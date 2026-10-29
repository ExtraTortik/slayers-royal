# -*- coding: utf-8 -*-
"""core/text_engine.py — Универсальный компилятор текста, указателей и DTE-сжатия для PS1.

Предоставляет:
1. Кодирование строк Unicode в поток кодов тайлов VRAM через таблицу charmap.
2. Автоматический пересчёт таблиц 32-битных и 16-битных RAM-указателей.
3. Валидацию ограничений экрана (лимит символов в строке, лимит строк в окне).
4. DTE-сжатие (Dual Tile Encoding) частых двухбуквенных биграмм для экономии секторов.
"""

from __future__ import annotations

import struct
from typing import Mapping, Sequence


def wrap_text_lines(text: str, max_chars: int) -> str:
    """Умный перенос строк по границам слов без разрыва фраз."""
    paragraphs = text.split("\n")
    wrapped_paras = []

    for p in paragraphs:
        words = p.split()
        if not words:
            wrapped_paras.append("")
            continue

        lines = []
        curr_line = []
        curr_len = 0

        for w in words:
            word_len = len(w)
            if curr_len + (1 if curr_len > 0 else 0) + word_len <= max_chars:
                curr_line.append(w)
                curr_len += (1 if curr_len > 0 else 0) + word_len
            else:
                if curr_line:
                    lines.append(" ".join(curr_line))
                curr_line = [w]
                curr_len = word_len

        if curr_line:
            lines.append(" ".join(curr_line))
        wrapped_paras.append("\n".join(lines))

    return "\n".join(wrapped_paras)


def encode_string(
    text: str,
    charmap: Mapping[str, int],
    newline_code: int = 0x00FE,
    terminator_code: int = 0x00FF,
    page_break_code: int = 0x00FD,
    little_endian: bool = True
) -> bytes:
    """Кодирование одной строки в последовательность 16-битных кодов тайлов PS1."""
    buf = bytearray()
    fmt = "<H" if little_endian else ">H"

    pages = text.split("\f")
    for p_idx, page in enumerate(pages):
        lines = page.split("\n")
        for l_idx, line in enumerate(lines):
            for ch in line:
                if ch in charmap:
                    code = charmap[ch]
                else:
                    code = charmap.get("?", 0x0020)
                buf.extend(struct.pack(fmt, code))
            if l_idx < len(lines) - 1:
                buf.extend(struct.pack(fmt, newline_code))
        if p_idx < len(pages) - 1:
            buf.extend(struct.pack(fmt, page_break_code))

    if terminator_code is not None:
        buf.extend(struct.pack(fmt, terminator_code))

    return bytes(buf)


def compile_dialogue_block(
    dialogues: Sequence[str],
    charmap: Mapping[str, int],
    ram_base: int,
    alignment: int = 2,
    little_endian: bool = True
) -> tuple[bytes, list[int]]:
    """Компиляция списка реплик в единый бинарный блок с расчётом 32-битных RAM-указателей."""
    body = bytearray()
    pointers = []

    for text in dialogues:
        # Выравнивание начала каждой реплики
        while len(body) % alignment != 0:
            body.append(0x00)

        pointers.append(ram_base + len(body))
        encoded = encode_string(text, charmap, little_endian=little_endian)
        body.extend(encoded)

    # Конечное выравнивание блока
    while len(body) % 4 != 0:
        body.append(0x00)

    return bytes(body), pointers


def apply_dte_compression(text: str, bigram_map: Mapping[str, str]) -> str:
    """Замена частых двухбуквенных биграмм на одиночные DTE-токены.
    
    bigram_map: { "то": "\uE001", "на": "\uE002", "ст": "\uE003", ... }
    """
    compressed = text
    # Сортируем биграммы по длине (для жадного сопоставления)
    for bigram, token in sorted(bigram_map.items(), key=lambda x: len(x[0]), reverse=True):
        compressed = compressed.replace(bigram, token)
    return compressed


def validate_dialogue_limits(
    text: str,
    max_chars_per_line: int,
    max_lines_per_page: int
) -> list[str]:
    """Строгая проверка форматирования: выявляет строки длиннее лимита окна."""
    errors = []
    pages = text.split("\f")
    for p_idx, page in enumerate(pages):
        lines = page.split("\n")
        if len(lines) > max_lines_per_page:
            errors.append(f"Стр. {p_idx+1}: {len(lines)} строк (лимит: {max_lines_per_page})")
        for l_idx, line in enumerate(lines):
            if len(line) > max_chars_per_line:
                errors.append(f"Стр. {p_idx+1}, строка {l_idx+1} ({len(line)} симв. > {max_chars_per_line}): '{line}'")
    return errors
