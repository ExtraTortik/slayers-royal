# Пошаговое руководство: Как начать перевод и ромхакинг НОВОЙ игры PS1

Этот гайд объясняет, как за 7 последовательных шагов начать перевод любой новой игры PlayStation 1 с помощью этого стартового набора.

---

## Шаг 1. Подготовка оригинального дампа
1. Получите чистый Redump-образ игры в формате `.bin` + `.cue` (Mode 2 Form 1, 2352 байта/сектор).
2. Положите файлы в папку:
   * `downloads/game.bin`
   * `downloads/game.cue`
3. Узнайте серийный номер диска (он указан в корневом каталоге, например `SLPS-01363`, `SLES-00123`, `SLUS-00456`).

---

## Шаг 2. Разведка структуры диска (ISO-9660)
Запустите быстрый скрипт чтения оглавления диска:

```bash
python -c "from core.disc import parse_iso_root; [print(f'{k:16s} LBA {v[0]:6d}, {v[1]} байт') for k, v in parse_iso_root('downloads/game.bin').items()]"
```

Вы увидите список всех файлов диска, их стартовые LBA-сектора и размеры:
* `SYSTEM.CNF` — конфигуратор диска.
* `SLPS_XXX.XX` — главный исполняемый бинарник процессора MIPS.
* Большие архивы с расширениями `.BIN`, `.DAT`, `.PAC`, `.UNT`, `.ARC`, `.GRP` — хранилища текстов и графики.

Извлеките интересующий архив на диск для анализа:
```python
from core.disc import extract_file_from_iso
extract_file_from_iso("downloads/game.bin", "MAIN_PROG.BIN", "data/extracted/MAIN_PROG.BIN")
```

---

## Шаг 3. Поиск шрифта через DuckStation VRAM Viewer
1. Запустите игру в DuckStation через лаунчер:
   ```cmd
   run_game.bat --orig
   ```
2. Дойдите до экрана с текстом или диалогом.
3. Нажмите клавишу **`F10`** (меню `Tools -> VRAM Viewer`).
4. В окне видеопамяти найдите атлас шрифта:
   * Наведите курсор на букву: в нижней панели отобразятся координаты в VRAM $(X, Y)$, глубина цвета (обычно 4bpp или 2bpp) и координаты палитры CLUT.
   * Сохраните фреймбуфер (`Dump VRAM to PNG`) в папку `data/vram_dump.png`.
5. По VRAM-координатам найдите файл на диске, который загружает этот тайловый атлас:
   * Сделайте поиск заголовка TIM (`10 00 00 00`) с нужными координатами $X, Y$ внутри извлечённых архивов.

---

## Шаг 4. Построение кодовой таблицы (Charmap)
1. Выясните порядок символов в оригинальном шрифте (обычно ASCII или японская Shift-JIS / внутренний тайловый порядок).
2. Замените неиспользуемые японские глифы (кандзи или катакану) на русские буквы в атласе.
3. Составьте таблицу `translations/charmap.json`, связывающую русскую букву с номером её тайла во VRAM:
   ```json
   {
     "А": 11,
     "Б": 12,
     "В": 13,
     ...
   }
   ```

---

## Шаг 5. Поиск текста и таблиц указателей в RAM
1. В эмуляторе найдите базовый адрес загрузки текстового модуля в оперативную память (обычно в диапазоне `0x80010000..0x801FFFFF`).
2. В hex-редакторе найдите массив 32-битных указателей (Little-Endian адреса `XX XX 04 80` или `XX XX 10 80`).
3. Разница между указателями показывает длину каждой реплики в байтах.
4. Создайте каталог `translations/dialogues.json`, где каждая фраза имеет уникальный `id`.

---

## Шаг 6. Написание скрипта сборщика
Используйте модули из папки `core/`:

```python
from core.disc import read_extent, replace_extent_in_place
from core.text_engine import compile_dialogue_block
import json

# 1. Загружаем каталог и чармап
dialogues = json.loads(open("translations/dialogues.json").read())
charmap = json.loads(open("translations/charmap.json").read())

# 2. Компилируем текст и новые указатели
strings_list = [d["text_ru"] for d in dialogues["scenes"][0]["dialogues"]]
compiled_body, new_pointers = compile_dialogue_block(
    strings_list, charmap, ram_base=0x80100000
)

# 3. Инжектируем в образ диска с автоматическим пересчётом EDC/ECC
replace_extent_in_place("localization-output/ru/game_ru.bin", start_lba=1250, payload=compiled_body)
```

---

## Шаг 7. Тестирование и быстрая отладка
* Соберите диск:
  ```cmd
  build.bat
  ```
* Запустите игру:
  ```cmd
  run_game.bat
  ```
* Для мгновенного обновления текста в текущей сцене без выхода из игры используйте:
  ```cmd
  python core/sync_savestates.py
  ```
  и нажимайте `F3` (Load State) в DuckStation.
