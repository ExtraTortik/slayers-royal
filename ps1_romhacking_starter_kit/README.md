# PS1 ROM Hacking & Translation Starter Kit

Универсальный стартовый шаблон и инженерный фреймворк для локализации и реверс-инжиниринга любой игры Sony PlayStation 1 (PS1 / PSX) на Windows и Linux.

---

## Что входит в стартовый набор:

### 1. Ядро утилит (`core/`):
* **`disc.py`** — низкоуровневый драйвер CD-ROM XA Mode 2 Form 1: чтение/запись секторов (LBA), автоматический пересчёт контрольных сумм EDC/ECC, парсер структуры ISO-9660.
* **`tim.py`** — универсальный конвертер текстур TIM в PNG и обратно (4bpp, 8bpp, 16bpp с палитрами CLUT).
* **`font_builder.py`** — рендерер шрифтов TTF/OTF в тайловые атласы VRAM (2bpp, 4bpp) с генерацией таблицы `charmap.json`.
* **`text_engine.py`** — компилятор текста, умный перенос строк, пересчёт 32-битных RAM-указателей и сжатие биграмм (DTE).
* **`sync_savestates.py`** — живая синхронизация сейвстейтов DuckStation с RAM для мгновенного тестирования текста без перезапуска игры.
* **`patch_maker.py`** — генератор легковесных релизных патчей xdelta3 (2–10 МБ).

### 2. Скрипты сборки и запуска:
* **`start_project.bat`** / **`start_project.sh`** — главный мастер-скрипт входа: проверка Python, установка библиотек, подключение агентских профилей и интерактивное меню.
* **`build.bat`** / **`build.sh`** — сборочный конвейер (создание модифицированного `.bin`/`.cue`).
* **`run_game.bat`** / **`run_game.sh`** — автолаунчер эмулятора DuckStation / Mednafen.

### 3. Документация (`docs/`):
* **`HOW_TO_START_NEW_GAME.md`** — пошаговый гайд от чистого диска до первого переведённого диалога.
* **`EMULATOR_DEBUGGING_GUIDE.md`** — исчерпывающее руководство по отладке через DuckStation (VRAM Viewer, RAM Breakpoints, анализ сбоев MIPS).
* **`PS1_ROMHACKING_GUIDE_WINDOWS.md`** — спецификация форматов PS1 под Windows.

### 4. Настройки ИИ-агентов (`agent_config/`):
* Готовые роли и системные промпты (`Orchestrator`, `MipsScout`, `VramGraphicsSpecialist`, `DialogueCompiler`, `QualityReviewer`) для работы с LLM (Oh My Pi, OpenDevin, Cursor, Claude Desktop).

---

## Быстрый старт:

### На Windows:
```cmd
start_project.bat
```

### На Linux / macOS:
```bash
chmod +x start_project.sh
./start_project.sh
```
