# -*- coding: utf-8 -*-
"""core/disc.py — Универсальный драйвер дисков CD-ROM XA Mode 2 Form 1 для PlayStation 1.

Предоставляет:
1. Чтение и замену секторов по LBA (Logical Block Address).
2. Автоматический расчёт аппаратной контрольной суммы EDC (32-бит) для Mode 2 Form 1.
3. Парсинг структуры файловой системы ISO-9660 (PVD на LBA 16 и директории).
4. Извлечение файлов из диска и инъекцию модифицированных файлов обратно.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Mapping

RAW_SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048


def compute_edc(data: bytes) -> int:
    """Вычисление 32-битной контрольной суммы EDC для CD-ROM XA Mode 2 Form 1."""
    edc = 0
    for b in data:
        edc ^= b
        for _ in range(8):
            if edc & 1:
                edc = (edc >> 1) ^ 0xD8018001
            else:
                edc >>= 1
    return edc & 0xFFFFFFFF


def read_sector(bin_path: Path | str, lba: int) -> bytes:
    """Чтение 2048 байт пользовательских данных сектора по LBA-адресу."""
    with open(bin_path, "rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        data = f.read(USER_DATA_SIZE)
        if len(data) != USER_DATA_SIZE:
            raise IOError(f"Не удалось прочитать LBA {lba} из {bin_path} (размер {len(data)})")
        return data


def read_raw_sector(bin_path: Path | str, lba: int) -> bytes:
    """Чтение полного сырого сектора 2352 байт."""
    with open(bin_path, "rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE)
        raw = f.read(RAW_SECTOR_SIZE)
        if len(raw) != RAW_SECTOR_SIZE:
            raise IOError(f"Не удалось прочитать полный сектор LBA {lba} из {bin_path}")
        return raw


def read_extent(bin_path: Path | str, lba: int, size_bytes: int) -> bytes:
    """Чтение непрерывного диапазона секторов для файла известного размера."""
    sectors_count = (size_bytes + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    buf = bytearray()
    with open(bin_path, "rb") as f:
        for i in range(sectors_count):
            f.seek((lba + i) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            chunk = f.read(USER_DATA_SIZE)
            buf.extend(chunk)
    return bytes(buf[:size_bytes])


def replace_sector_in_place(bin_path: Path | str, lba: int, user_data: bytes):
    """Запись 2048 байт данных в сектор с пересчётом контрольной суммы EDC."""
    if len(user_data) != USER_DATA_SIZE:
        raise ValueError(f"Размер данных обязан быть строго {USER_DATA_SIZE} байт, получено {len(user_data)}")

    with open(bin_path, "r+b") as f:
        # Читаем исходный заголовок сектора (первые 24 байта)
        f.seek(lba * RAW_SECTOR_SIZE)
        header = f.read(USER_DATA_OFFSET)
        if len(header) != USER_DATA_OFFSET:
            raise IOError(f"Не удалось прочитать заголовок LBA {lba}")

        # Вычисляем EDC по подзаголовку (8 байт: 16..24) + полезным данным (2048 байт)
        subheader = header[16:24]
        edc_val = compute_edc(subheader + user_data)
        edc_bytes = struct.pack("<I", edc_val)

        # Записываем обновлённые данные и новую контрольную сумму
        f.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        f.write(user_data)
        f.write(edc_bytes)


def replace_extent_in_place(bin_path: Path | str, start_lba: int, payload: bytes):
    """Пакетная замена диапазона секторов с автоматическим паддингом нулями до границы сектора."""
    sectors_count = (len(payload) + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    padded = payload.ljust(sectors_count * USER_DATA_SIZE, b"\x00")
    for i in range(sectors_count):
        chunk = padded[i * USER_DATA_SIZE : (i + 1) * USER_DATA_SIZE]
        replace_sector_in_place(bin_path, start_lba + i, chunk)


def parse_iso_directory(bin_path: Path | str, dir_lba: int, dir_size: int) -> dict[str, tuple[int, int]]:
    """Парсинг сектора каталога ISO-9660. Возвращает { 'FILENAME.EXT': (LBA, size_bytes) }."""
    dir_data = read_extent(bin_path, dir_lba, dir_size)
    files = {}
    offset = 0
    while offset < len(dir_data):
        record_len = dir_data[offset]
        if record_len == 0:
            # Выравнивание по границе сектора
            next_sector = ((offset // USER_DATA_SIZE) + 1) * USER_DATA_SIZE
            if next_sector >= len(dir_data):
                break
            offset = next_sector
            continue

        file_lba = struct.unpack_from("<I", dir_data, offset + 2)[0]
        file_size = struct.unpack_from("<I", dir_data, offset + 10)[0]
        name_len = dir_data[offset + 32]
        raw_name = dir_data[offset + 33 : offset + 33 + name_len].decode("ascii", errors="ignore")
        name = raw_name.split(";")[0].strip()

        # Пропускаем служебные записи . и ..
        if name and name not in ("\x00", "\x01"):
            files[name] = (file_lba, file_size)

        offset += record_len
    return files


def parse_iso_root(bin_path: Path | str) -> dict[str, tuple[int, int]]:
    """Парсинг корневой директории ISO-9660 диска через PVD (LBA 16)."""
    pvd = read_sector(bin_path, 16)
    if pvd[1:6] != b"CD001":
        raise ValueError("Диск не содержит валидной файловой системы ISO-9660 (отсутствует сигнатура CD001)")

    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]
    return parse_iso_directory(bin_path, root_lba, root_size)


def extract_file_from_iso(bin_path: Path | str, target_filename: str, out_path: Path | str) -> int:
    """Извлечение файла из ISO-образа на локальный диск."""
    files = parse_iso_root(bin_path)
    clean_target = target_filename.upper().strip()
    if clean_target not in files:
        raise FileNotFoundError(f"Файл {target_filename} не найден в корневом каталоге диска. Доступные: {list(files.keys())}")

    lba, size = files[clean_target]
    payload = read_extent(bin_path, lba, size)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(payload)
    return size
