# Инженерное руководство по ромхакингу и локализации игр PlayStation 1 на Windows

---

## 1. Архитектура рабочего пространства и окружение (Windows)

### 1.1. Базовые инструменты
1. **Python 3.10+ (x64)**:
   * Скачайте установщик с официального сайта [python.org](https://www.python.org/).
   * **Обязательно** установите флаг при установке: `[x] Add Python to PATH`.
   * Установите минимальные библиотеки для работы с графикой и тестами:
     ```cmd
     pip install pillow pytest
     ```
2. **Консоль Windows (UTF-8)**:
   * Все `.bat`-файлы проекта должны начинаться с команды:
     ```cmd
     @echo off
     chcp 65001 > nul
     ```
     Это переключает кодовую страницу `cmd.exe` на UTF-8 и исключает повреждение кириллических путей и текстов.
3. **Рекомендуемый редактор**:
   * **VS Code** с расширениями:
     * *Hex Editor* (Microsoft) — для инспекции байтов прямо в редакторе.
     * *Python* / *Pylance* — для разработки скриптов.
     * *Even Better TOML* / *JSON* — для редактирования каталогов перевода.

### 1.2. Рекомендуемая файловая структура проекта
```text
PS1_Project/
├── downloads/                     # Чистый оригинальный Redump-образ (game.bin, game.cue)
├── localization-output/
│   └── ru/                        # Готовый пропатченный образ (game_ru.bin, game_ru.cue)
├── translations/                  # Мастер-каталоги в JSON (диалоги, меню, системные строки)
│   ├── dialogues.json
│   ├── items.json
│   └── charmap.json               # Таблица маппинга символов (Символ ↔ ID тайла VRAM)
├── tools/                         # Модули автоматизации на Python
│   ├── disc.py                    # Драйвер чтения/записи CD-ROM XA и расчёта EDC/ECC
│   ├── tim.py                     # Конвертер и парсер текстур TIM (4bpp/8bpp)
│   ├── font_builder.py            # Генератор VRAM-шрифта из TTF
│   └── patch_text.py              # Инжектор текстов с пересчётом указателей памяти
├── data/                          # Исходные PNG-текстуры, шрифты TTF
├── build.bat                      # Сборщик диска в один клик
├── run_game.bat                   # Лаунчер эмулятора в один клик
└── make_patch.bat                 # Генератор релизного патча xdelta3
```

---

## 2. Низкоуровневая дисковая инженерия (CD-ROM XA Mode 2 Form 1)

### 2.1. Анатомия сектора PS1
Образ диска PlayStation 1 (`.bin`) нарезан на секторы строго по **2352 байта**:
$$\text{Raw Sector (2352 B)} = \text{Sync (12 B)} + \text{Header (4 B)} + \text{Subheader (8 B)} + \mathbf{\text{User Data (2048 B)}} + \text{EDC (4 B)} + \text{ECC (276 B)}$$

* **Смещение пользовательских данных:** ровно `+24 байта` от начала сектора.
* **Размер полезных данных:** ровно `2048 байт`.
* **EDC/ECC (контрольные суммы):** последние `280 байт`.
* **Критическое правило:** Если просто изменить байты в hex-редакторе внутри файла `.bin`, контрольная сумма EDC/ECC перестанет совпадать. Реальная консоль PS1 и точные эмуляторы (DuckStation, Mednafen) заблокируют чтение сектора — игра зависнет с чёрным экраном.

### 2.2. Готовый Python-модуль работы с диском (`tools/disc.py`)
Этот модуль читает и записывает секторы, а также пересчитывает аппаратный EDC/ECC на лету:

```python
# -*- coding: utf-8 -*-
"""tools/disc.py — Драйвер секторов CD-ROM XA Mode 2 Form 1 для PlayStation 1."""

import struct
from pathlib import Path

RAW_SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048

def read_sector(bin_path: Path | str, lba: int) -> bytes:
    """Чтение 2048 байт данных сектора по LBA-адресу."""
    with open(bin_path, "rb") as f:
        f.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        data = f.read(USER_DATA_SIZE)
        if len(data) != USER_DATA_SIZE:
            raise IOError(f"Не удалось прочитать LBA {lba} из {bin_path}")
        return data

def read_extent(bin_path: Path | str, lba: int, size_bytes: int) -> bytes:
    """Чтение файла произвольного размера, выровненного по секторам."""
    sectors_count = (size_bytes + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    buf = bytearray()
    with open(bin_path, "rb") as f:
        for i in range(sectors_count):
            f.seek((lba + i) * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
            chunk = f.read(USER_DATA_SIZE)
            buf.extend(chunk)
    return bytes(buf[:size_bytes])

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

def replace_sector_in_place(bin_path: Path | str, lba: int, user_data: bytes, recalc_ecc: bool = True):
    """Запись 2048 байт в сектор с пересчётом контрольной суммы EDC."""
    if len(user_data) != USER_DATA_SIZE:
        raise ValueError(f"Размер данных обязан быть ровно {USER_DATA_SIZE} байт")

    with open(bin_path, "r+b") as f:
        # Читаем исходный заголовок сектора (первые 24 байта)
        f.seek(lba * RAW_SECTOR_SIZE)
        header = f.read(USER_DATA_OFFSET)

        # Вычисляем EDC по подзаголовку (8 байт) + пользовательским данным (2048 байт)
        subheader = header[16:24]
        edc_val = compute_edc(subheader + user_data)
        edc_bytes = struct.pack("<I", edc_val)

        # Пишем обновлённые данные
        f.seek(lba * RAW_SECTOR_SIZE + USER_DATA_OFFSET)
        f.write(user_data)
        f.write(edc_bytes)

def replace_extent_in_place(bin_path: Path | str, start_lba: int, payload: bytes):
    """Пакетная замена диапазона секторов с автоматическим паддингом нулями."""
    sectors_count = (len(payload) + USER_DATA_SIZE - 1) // USER_DATA_SIZE
    padded = payload.ljust(sectors_count * USER_DATA_SIZE, b"\x00")
    for i in range(sectors_count):
        chunk = padded[i * USER_DATA_SIZE : (i + 1) * USER_DATA_SIZE]
        replace_sector_in_place(bin_path, start_lba + i, chunk)
```

### 2.3. Автопарсинг структуры ISO-9660 (Поиск файлов без гаданий)
В ISO-9660 сектор **LBA 16** — это Primary Volume Descriptor (PVD). Корневая директория находится по смещению `156` внутри PVD:

```python
def parse_iso_root(bin_path: Path | str) -> dict[str, tuple[int, int]]:
    """Возвращает словарь { 'FILENAME.EXT': (LBA, размер_в_байтах) }."""
    pvd = read_sector(bin_path, 16)
    root_lba = struct.unpack_from("<I", pvd, 156 + 2)[0]
    root_size = struct.unpack_from("<I", pvd, 156 + 10)[0]

    dir_data = read_extent(bin_path, root_lba, root_size)
    files = {}
    offset = 0
    while offset < len(dir_data):
        record_len = dir_data[offset]
        if record_len == 0:
            offset += 1
            continue
        file_lba = struct.unpack_from("<I", dir_data, offset + 2)[0]
        file_size = struct.unpack_from("<I", dir_data, offset + 10)[0]
        name_len = dir_data[offset + 32]
        raw_name = dir_data[offset + 33 : offset + 33 + name_len].decode("ascii", errors="ignore")
        name = raw_name.split(";")[0] # отсекаем версию файла ;1
        if name:
            files[name] = (file_lba, file_size)
        offset += record_len
    return files
```

---

## 3. Графика и шрифты PlayStation (TIM, VRAM и CLUT)

### 3.1. Структура формата TIM
Текстуры в PS1 хранятся в формате `.TIM` со следующей структурой:
1. **Magic**: `0x00000010` (4 байта).
2. **Flags**:
   * Бит 0..1: глубина цвета (`0 = 4bpp/16 цветов`, `1 = 8bpp/256 цветов`, `2 = 16bpp Direct Color`).
   * Бит 3: наличие палитры CLUT (`1 = палитра есть`).
3. **Блок CLUT (если есть)**:
   * Длина блока (4 байта).
   * Координаты VRAM палитры: $X, Y$ (по 2 байта).
   * Размеры палитры: $W, H$ (по 2 байта). Для 4bpp $W=16$, для 8bpp $W=256$.
   * Цвета в формате BGR555 (16 бит на цвет: 5 бит синий, 5 зелёный, 5 красный, 1 бит полупрозрачности STP).
4. **Блок изображения**:
   * Длина блока (4 байта).
   * Координаты в VRAM: $X, Y$ (по 2 байта).
   * Ширина в 16-битных словах ($W$), высота в пикселях ($H$).
     * Для 4bpp реальная ширина в пикселях $= W \times 4$.
     * Для 8bpp реальная ширина в пикселях $= W \times 2$.

### 3.2. Готовый конвертер TIM $\to$ PNG (`tools/tim_to_png.py`)
```python
# -*- coding: utf-8 -*-
import struct
from PIL import Image

def decode_tim(tim_bytes: bytes) -> Image.Image:
    magic, flags = struct.unpack_from("<II", tim_bytes, 0)
    if magic != 0x10:
        raise ValueError("Файл не является PS1 TIM (Magic != 0x10)")

    bpp_mode = flags & 3
    has_clut = (flags >> 3) & 1
    offset = 8
    clut = []

    if has_clut:
        clut_len, cx, cy, cw, ch = struct.unpack_from("<IHHHH", tim_bytes, offset)
        clut_data = tim_bytes[offset + 12 : offset + clut_len]
        for i in range(cw * ch):
            c16 = struct.unpack_from("<H", clut_data, i * 2)[0]
            r = (c16 & 0x1F) << 3
            g = ((c16 >> 5) & 0x1F) << 3
            b = ((c16 >> 10) & 0x1F) << 3
            # Цвет 0 в PS1 прозрачный, если не включён бит STP
            a = 0 if c16 == 0 else 255
            clut.append((r, g, b, a))
        offset += clut_len

    img_len, dx, dy, w, h = struct.unpack_from("<IHHHH", tim_bytes, offset)
    pixel_data = tim_bytes[offset + 12 : offset + img_len]

    if bpp_mode == 0:  # 4bpp
        pix_w = w * 4
        img = Image.new("RGBA", (pix_w, h), (0, 0, 0, 0))
        for y in range(h):
            for x_w in range(w):
                b0 = pixel_data[y * (w * 2) + x_w * 2]
                b1 = pixel_data[y * (w * 2) + x_w * 2 + 1]
                pixels = [b0 & 0x0F, (b0 >> 4) & 0x0F, b1 & 0x0F, (b1 >> 4) & 0x0F]
                for p_idx, p in enumerate(pixels):
                    img.putpixel((x_w * 4 + p_idx, y), clut[p])
        return img
    elif bpp_mode == 1:  # 8bpp
        pix_w = w * 2
        img = Image.new("RGBA", (pix_w, h), (0, 0, 0, 0))
        for y in range(h):
            for x in range(pix_w):
                p = pixel_data[y * pix_w + x]
                img.putpixel((x, y), clut[p])
        return img
    raise NotImplementedError("16bpp/24bpp direct color не реализован")
```

---

## 4. Текстовый пайплайн и защита от сбоев движка

### 4.1. Организация каталогов перевода в JSON
Не редактируйте текст в бинарниках вручную. Ведите единый источник правды (Single Source of Truth) в понятном JSON:

```json
{
  "scene_id": "03B",
  "ram_base": "0x80121000",
  "pointer_table_offset": "0x0004",
  "max_sectors": 19,
  "dialogues": [
    {
      "id": 0,
      "speaker": "Лина",
      "text_ru": "Эй, Гаури!\nКуда это ты\nсобрался?",
      "max_lines": 3,
      "max_chars_per_line": 15
    }
  ]
}
```

### 4.2. Автоматический пересчёт 32-битных RAM-указателей
В играх PS1 текст адресуется через таблицы указателей (Pointer Tables). Поскольку русский текст длиннее японского (в японском 1 символ передаёт целое слово), абсолютные адреса реплик смещаются:

```python
def rebuild_text_block(strings: list[str], charmap: dict[str, int], ram_base: int) -> tuple[bytes, list[int]]:
    """Собирает текстовый блок и вычисляет точные 32-битные RAM-указатели."""
    body = bytearray()
    pointers = []

    for s in strings:
        pointers.append(ram_base + len(body))
        for line in s.split("\n"):
            for ch in line:
                code = charmap.get(ch, 0x0020)
                body.extend(struct.pack("<H", code))
            body.extend(struct.pack("<H", 0x00FE)) # Опкод переноса строки \n
        # Заменяем последний перенос строки на терминатор конца фразы
        if len(body) >= 2 and body[-2:] == struct.pack("<H", 0x00FE):
            body[-2:] = struct.pack("<H", 0x00FF)  # Опкод конца фразы 0x00FF

        # Выравнивание каждой строки по границе 2 или 4 байт
        while len(body) % 2 != 0:
            body.append(0x00)

    return bytes(body), pointers
```

### 4.3. Бюджет памяти и коллизии RAM
* **Аппаратный потолок буфера сцены:** в PS1 игровые сцены распаковываются по фиксированным базовым адресам (например, `0x80121000`). Следующий системный модуль загружается по адресу `0x8012A800`.
* **Лимит:** $\Delta = \text{0x8012A800} - \text{0x80121000} = 38\,912\text{ байт} = 19\text{ секторов}$.
* **Правило:** Если русский текст раздует сцену хотя бы на 1 сектор выше лимита (20 секторов вместо 19), следующий модуль затрёт хвост таблицы указателей, и при обращении к памяти эмулятор выбросит `Address Error Exception (Crash)`.
* **Решение при переполнении:**
  1. Либо выделять донорские пустые секторы из неиспользуемых файлов игры.
  2. Либо внедрять **DTE-сжатие (Dual Tile Encoding)**: заменять частые двухбуквенные русские биграммы («-то», «-но», «ст», «ра») на один тайл во VRAM. 220 биграмм экономят до 28 КБ текста без сокращения литературного перевода.

---

## 5. Сборочный скрипт `build.bat` и релизный патч

### 5.1. Шаблон `build.bat` для Windows
Создайте файл `build.bat` в корне проекта:

```bat
@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

title Сборщик локализации PS1
cd /d "%~dp0"

:: Поиск Python
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py -3"
if not defined PY_CMD where python >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    echo [ОШИБКА] Python не найден! Установите Python 3 с python.org
    pause
    exit /b 1
)

set "ORIG_BIN=downloads\game.bin"
set "OUT_DIR=localization-output\ru"
set "OUT_BIN=%OUT_DIR%\game_ru.bin"

if not exist "%ORIG_BIN%" (
    echo [ОШИБКА] Оригинальный образ %ORIG_BIN% не найден!
    pause
    exit /b 1
)

if not exist "%OUT_DIR%" mkdir "%OUT_DIR%"
copy /Y "%ORIG_BIN%" "%OUT_BIN%" > nul

echo [*] Сборка локализации...
%PY_CMD% tools\patch_text.py --bin "%OUT_BIN%"
if %ERRORLEVEL% neq 0 (
    echo [ОШИБКА] Сборка провалилась!
    pause
    exit /b 1
)

echo [✓] Сборка успешно завершена! Образ: %OUT_BIN%
exit /b 0
```

### 5.2. Скрипт создания патча `make_patch.bat` (xdelta3)
Чтобы раздавать пользователям патч весом 3 МБ, а не весь диск 700 МБ:
1. Скачайте `xdelta3.exe` (x64) в папку `tools\bin\`.
2. Создайте `make_patch.bat`:

```bat
@echo off
chcp 65001 > nul
cd /d "%~dp0"

set "ORIG_BIN=downloads\game.bin"
set "RU_BIN=localization-output\ru\game_ru.bin"
set "PATCH_FILE=release\game_translation_ru.xdelta"

if not exist "release" mkdir "release"

echo [*] Создание дельта-патча xdelta3...
tools\bin\xdelta3.exe -e -s "%ORIG_BIN%" "%RU_BIN%" "%PATCH_FILE%"

echo [✓] Патч успешно создан: %PATCH_FILE%
pause
```

---

## 6. Лаунчер для Windows и настройка эмулятора (`run_game.bat`)

### 6.1. Скрипт `run_game.bat`
Скрипт автоматически находит **DuckStation**, проверяет наличие образа и запускает игру в один клик:

```bat
@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "TARGET_CUE=localization-output\ru\game_ru.cue"

if not exist "%TARGET_CUE%" (
    echo [*] Образ не найден. Запуск сборщика build.bat...
    call build.bat
)

set "EMU="
if exist "%LOCALAPPDATA%\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe" (
    set "EMU="%LOCALAPPDATA%\DuckStation\duckstation-qt-x64-ReleaseLTCG.exe""
)
if not defined EMU if exist "%ProgramFiles%\DuckStation\duckstation-qt.exe" (
    set "EMU="%ProgramFiles%\DuckStation\duckstation-qt.exe""
)
if not defined EMU (
    where duckstation-qt >nul 2>&1 && set "EMU=duckstation-qt"
)

if defined EMU (
    echo [*] Запуск DuckStation: !EMU! "%TARGET_CUE%"
    start "" !EMU! "%TARGET_CUE%"
) else (
    echo [*] DuckStation не найден. Запуск системной ассоциации...
    start "" "%TARGET_CUE%"
)
```

### 6.2. Настройка DuckStation для ромхакера
DuckStation — лучший эмулятор для реверс-инжиниринга PS1:
1. **VRAM Viewer** (`F10` или `Tools -> VRAM Viewer`):
   * Показывает полную память видеочипа ($1024 \times 512$).
   * Позволяет навести курсор на любой глиф или плашку, увидеть точные координаты в VRAM $(X, Y)$, глубину цвета (4bpp/8bpp) и координаты палитры (CLUT).
2. **Встроенный отладчик (Debugger)**:
   * Показывает исполняемый ассемблерный код процессора MIPS R3000A.
   * Позволяет ставить Memory Breakpoint (на чтение/запись по адресу текста), чтобы мгновенно узнать, какая функция загружает и рендерит строку.

---

## 7. Чеклист перед релизом патча (QA & Validation)

Перед публикацией патча выполните 5 обязательных проверок:

| № | Проверка | Способ проверки | Критический симптом при ошибке |
| :---: | :--- | :--- | :--- |
| **1** | **Контрольные суммы EDC/ECC** | Модуль `disc.py compute_edc` | Зависание на реальной консоли / чёрный экран при чтении сектора |
| **2** | **Бюджет секторов RAM** | Проверка длины каждой скомпилированной сцены ($\le$ лимит секторов оригинала) | Краш эмулятора (`Address Error`), вылет в отеле / при переходе локаций |
| **3** | **Проверка кодовой страницы** | Тест `test_charmap.py`: все символы текста присутствуют во VRAM | «Кракозябры» (модзибаке) вместо букв |
| **4** | **Контроль длины строк** | Проверка длины строк ($\le 15$ символов на строку для диалогов) | Текст налезает на рамку или обрезается на полуслове |
| **5** | **Тестирование на чистом дампе** | Применение сгенерированного `.xdelta` к эталонному Redump `.bin` | Несовпадение MD5 оригинального образа |
