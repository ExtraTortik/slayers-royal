# Slayers Royal PS1: Fix Mojibake Choices & Translate Object Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all garbled text (mojibake) in dialogue and tavern choices by translating all remaining untranslated choices in `dialogue.po`, and translate all room object inspection strings (such as "Hanging lamp", "Wooden table", "Plank flooring") into Russian in the `PROG.UNT` room inspection entries (entries `0x059`..`0x138`).

**Architecture:**
1. **Fix Mojibake Choices:** In `patch_repo/localization-work/ru/dialogue.po`, identify all untranslated choices (containing `\n`, including `dialogue/03B/E01B/061` `詳しく聞いてみる.\n聞くのをやめる.` and other choices in `0x03B` and narrative scenes), provide clean, natural Russian translations adhering to `parse_target` ($\le 15$ chars/line, 1-3 lines/page), and rebuild the dialogue catalog.
2. **Translate Object Inspection:** Reverse-engineer and build an automated translator/injector for `PROG.UNT` room inspection entries (`0x058`..`0x138`):
   - Parse string pointer tables (at `0x0A08`..`0x0A80` in `0x05D` and corresponding tables in other rooms).
   - Extract English object names and descriptions.
   - Translate them into Russian (e.g. `A hanging lamp.` $\to$ `Подвесная лампа.`, `The lamp cord.` $\to$ `Шнур лампы.`, `A wooden table.` $\to$ `Деревянный стол.`).
   - Encode Russian strings into 16-bit big-endian words using `patch_repo`'s Cyrillic `charmap`.
   - Re-pack the entry, update absolute 32-bit RAM pointers, and zero-pad to sector boundaries.
3. **Rebuild & Recalculate:**
   - Compile `PROG.UNT` and update `localization-output/ru/slayers_royal_ru.bin` and `slayers_royal_ru.cue`.
   - Recalculate Mode 2 Form 1 EDC/ECC sector checksums.
4. **Verification:**
   - Verify `dialogue/03B/E01B/061` choice displays in clean Russian: `Расспросить.\nХватит.`
   - Verify tavern inspection strings in `0x05D` display in Russian (`Подвесная лампа.` etc.).
   - Run all test suites.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Hardware constraints: $\le 15$ characters per line for dialogue, valid delimiters `0x00FD` / `0x00FF`.
- All actions executed via subagents.

---

### Task 1: Eliminate Mojibake by Translating All Dialogue Choices

**Files:**
- Modify: `patch_repo/localization-work/ru/dialogue.po`
- Create: `tools/translate_choices.py`
- Test: `patch_repo/localization/tests`

**Interfaces:**
- Consumes: `patch_repo/localization-work/ru/dialogue.po`.
- Produces: 100% translated choices in `dialogue.po` with zero empty `msgstr` on choice records.

- [ ] **Step 1: Identify all untranslated choices**
Write `tools/translate_choices.py` to scan `dialogue.po` for all untranslated entries containing choices or prompts:
- `dialogue/03B/E01B/061`: `詳しく聞いてみる.\n聞くのをやめる.` $\to$ `Расспросить.\nХватит.`
- `dialogue/03B/E01A/002`: `説明を見る\n説明を見ない` $\to$ `Посмотреть\nсправку\nНе смотреть`
- `dialogue/03B/E01B/161`: `やめさせる.\nナ-ガをけしかける.` $\to$ `Остановить.\nНатравить Нагу.`
- `dialogue/03B/E01B/225`: `世間話をしてみる\n話をやめる` $\to$ `Поболтать.\nЗакончить.`
- And all other remaining untranslated choices and prompts in `0x03B` and subsequent scenes.

- [ ] **Step 2: Apply translations and validate**
Apply the translated strings to `dialogue.po`. Verify each with `parse_target` to guarantee no lines $>15$ characters and no illegal continuation pages.
Run:
```bash
python3 tools/translate_choices.py --po patch_repo/localization-work/ru/dialogue.po
```

- [ ] **Step 3: Run catalog validator**
Run:
```bash
cd patch_repo && python3 localize.py validate --bin ../downloads/sr.bin --workspace localization-work/ru --locale ru --allow-incomplete
```
Expected: 0 errors, 0 warnings.

---

### Task 2: Implement Object Inspection Translation Pipeline

**Files:**
- Create: `tools/patch_inspection.py`
- Create: `tools/test_patch_inspection.py`
- Create: `data/inspection_ru.json`

**Interfaces:**
- Consumes: `english_prog` room entries `0x059`..`0x138`, `patch_repo/localization/sr_charmap.py`.
- Produces: Translated and re-pointed `PROG.UNT` room inspection entries with 16-bit Cyrillic charmap words.

- [ ] **Step 1: Build inspection parser & extractor**
Implement `extract_inspection_strings(entry_data)` in `tools/patch_inspection.py` to locate the pointer table at `0x0A00`..`0x0B00` (or `0x0400`..`0x0500`) and extract all English object names and inspection turns.

- [ ] **Step 2: Create Russian dictionary for room inspection**
Provide natural Russian translations for:
- Room 0x05D (Lakewood Tavern):
  - `Diner ceiling.` $\to$ `Потолок таверны.`
  - `No upstairs.` $\to$ `Второго этажа\nнет. Хозяева\nживут внизу.`
  - `Just a wall.` $\to$ `Обычная стена.`
  - `Outside, past this wall. Obviously.` $\to$ `За этой стеной\nулица. Вполне\nочевидно.`
  - `Barred window.` $\to$ `Окно с решёткой.`
  - `No glass, just iron bars.` $\to$ `Стекла нет,\nтолько железная\nрешётка.`
  - `The diner door.` $\to$ `Дверь таверны.`
  - `A hanging lamp.` $\to$ `Подвесная лампа.`
  - `It takes a lamp this big to light it all.` $\to$ `Такая большая\nлампа освещает\nвесь зал.`
  - `The lamp cord.` $\to$ `Шнур лампы.`
  - `Plank flooring.` $\to$ `Дощатый пол.`
  - `A wooden chair.` $\to$ `Деревянный\nстул.`
  - `A wooden table.` $\to$ `Деревянный\nстол.`
  - `A water jar.` $\to$ `Кувшин с водой.`
  - `Two customers.` $\to$ `Два посетителя.`
  - `B lunch.` $\to$ `Обед Б.`
  - `A lunch.` $\to$ `Обед А.`
- And common object names across other rooms (doors, windows, counters, signs, shelves, beds, barrels).

- [ ] **Step 3: Implement 16-bit Cyrillic encoder & pointer recalculator**
- Encode each Russian string into 16-bit words using `patch_repo`'s `charmap` (where Cyrillic glyphs are allocated).
- Rebuild string block between `0x0430` and the pointer table.
- Recalculate 32-bit big-endian RAM pointers (`0x00200000 + offset`) in the pointer table.
- Verify rebuilt entry size matches entry sector size (`entry.size`).

- [ ] **Step 4: Write unit tests**
Implement `tools/test_patch_inspection.py` and run with `pytest`.

---

### Task 3: Rebuild Disc Image & Full System Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/mojibake-inspection-report.md`

**Interfaces:**
- Consumes: Updated `dialogue.po`, `tools/patch_inspection.py`, `tools/patch_lore_cards.py`.
- Produces: Verified bootable PS1 image with zero mojibake choices and Russian object inspection.

- [ ] **Step 1: Rebuild dialogue and PROG.UNT**
Run:
```bash
cd patch_repo && python3 localize.py build \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru \
  --output-dir localization-output/ru \
  --allow-incomplete \
  --force
```

- [ ] **Step 2: Inject inspection strings and lore cards**
- Run `python3 tools/patch_inspection.py --disc localization-output/ru/slayers_royal_ru.bin`
- Run `python3 tools/patch_lore_cards.py --disc localization-output/ru/slayers_royal_ru.bin --cards data/lore_cards_ru.json`
- Recalculate Mode 2 Form 1 EDC/ECC checksums for all modified sectors.

- [ ] **Step 3: Run all test suites**
Run:
```bash
python3 -m pytest tools/
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests
```
Expected: 100% tests pass.

- [ ] **Step 4: Verify launcher and write final report**
Test `./run_game.sh --dry-run`.
Write execution report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/mojibake-inspection-report.md`.
