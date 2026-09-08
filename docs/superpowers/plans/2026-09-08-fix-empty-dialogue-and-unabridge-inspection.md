# Slayers Royal PS1: Fix Empty Dialogue Windows & Unabridge Room Inspection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate all blank/empty dialogue windows across the entire game (especially on MAIN ST in Scene `0x03C` and subsequent town navigation scenes) by completing Russian translations for all remaining untranslated dialogue turns in `dialogue.po`, and fix all 143 prematurely truncated room inspection strings in `translations/room_inspection_ru.json` so every single sentence is complete, natural, and grammatically whole without abrupt `...` cutoffs.

**Architecture:**
1. **Fix Empty Dialogue Windows (Scenes 03C..057):**
   - Extract the English reference text from `english_prog` for all 1,395 previously untranslated dialogue segments in `patch_repo/localization-work/ru/dialogue.po`.
   - Translate all remaining entries into authentic Russian adhering to `parse_target` ($\le 15$ characters per line, 1–3 lines per page, proper `0x00FD`/`0x00FF` delimiters), paying special attention to Lakewood MAIN ST (Scene `0x03C`, 189 entries), town navigation, and choices.
   - Fix corrupted choice entries (e.g. `dialogue/03C/E028/001` which previously had `"3,202"` $\to$ `Свойства магии\nНе смотреть`).
   - Validate `dialogue.po` with `localize.py validate`.
2. **Unabridge Room Inspection Catalog:**
   - Scan `translations/room_inspection_ru.json` for all 143 strings with mechanical trailing `...` truncations.
   - Re-author each string so that the sentence is complete, witty, and grammatically whole (e.g. `"That upper window is open. Toss in a rock?"` $\to$ `"Вон то окно\nоткрыто. Кинуть\nтуда камешек?"` instead of `"Окно открыто.\nШвырнуть туда\nкамешек, что..."`).
   - Guarantee that every line is strictly $\le 15$ characters and the total lines are $\le 3$.
3. **Batch Injection & Disc Rebuild:**
   - Compile base localized image with 100% translated dialogue via `localize.py build`.
   - Batch-patch all 149 room entries with the unabridged `translations/room_inspection_ru.json`.
   - Inject Russian character lore cards and banners.
   - Recalculate Mode 2 Form 1 EDC/ECC checksums.
4. **Verification:**
   - Verify Scene `0x03C` on MAIN ST has 0 empty dialogue entries.
   - Verify `translations/room_inspection_ru.json` has 0 prematurely truncated strings.
   - Run full regression test suites.
   - Verify launcher dry-run.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Total Scope: 100% dialogue coverage in `dialogue.po` (4,514/4,514 entries) and 100% complete sentences in `translations/room_inspection_ru.json` (734/734 strings).
- Hardware Layout: $\le 15$ Unicode characters per line, 1–3 lines per page, NFC Unicode.
- All tasks executed via subagents.

---

### Task 1: Complete 100% Dialogue Translation & Eliminate Empty Windows

**Files:**
- Modify: `patch_repo/localization-work/ru/dialogue.po`
- Create: `tools/complete_all_dialogue.py`
- Test: `patch_repo/localization/tests`

**Interfaces:**
- Consumes: `patch_repo/localization-work/ru/dialogue.po`, `english_prog`.
- Produces: 100% populated `dialogue.po` with 0 empty `msgstr` entries.

- [x] **Step 1: Extract English references for all untranslated entries**
Write `tools/complete_all_dialogue.py`:
- Identify all entries in `dialogue.po` where `msgstr == ""`.
- Decode the verified English text from `english_prog` for each untranslated context.
- Group by scene:
  - `0x03C` (189 entries: Lakewood Main St, Back St, Plaza, citizen conversations, merchant choices)
  - `0x03D` (74 entries: Outskirts and bandit trail)
  - `0x03E` (274 entries: Sonia City exploration and side quests)
  - `0x040`..`0x057` (remaining side turns and narrative scenes)

- [x] **Step 2: Generate natural Russian translations fitting PS1 limits**
Translate all untranslated entries:
- Fix `dialogue/03C/E028/001` (`"3,202"` $\to$ `"Свойства магии\nНе смотреть"`).
- Translate `dialogue/03C/E02E/000` (`"俺が聞いてわかるのか?"` $\to$ `"А я пойму,\nесли послушаю?"`).
- Translate `dialogue/03C/E02F/000` (`"\"\"そうよね,あんたが聞いても\nしかたないわよね."` $\to$ `"И правда, тебе\nвсё равно без\nтолку."`).
- Translate `dialogue/03C/E030/000` (`"そうだろ?\nはっはっはっはっはっ!"` $\to$ `"То-то же!\nХа-ха-ха!"`).
- Translate `dialogue/03C/E031/000` (`"いや,笑われても\"\"まっいいか.\nで,ラ-ク,話の続きなんだけど\"\"\nそうなんでしょ?"` $\to$ `"Смешно ему...\nТак вот, Ларк,\nпродолжай."`).
- Format all translated text using `wrap_dialogue` enforcing $\le 15$ characters per line and 1–3 lines per page.
- Update `dialogue.po`.

- [x] **Step 3: Validate complete catalog**
Run:
```bash
cd patch_repo && python3 localize.py validate \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru
```
Notice: Run WITHOUT `--allow-incomplete` to verify that 100% of entries (4,514/4,514) are translated!
Expected: `validated Russian catalog: 4514 translated, 0 untranslated, 4514 total`.

- [x] **Step 4: Commit changes**
```bash
git add patch_repo/localization-work/ru/dialogue.po tools/complete_all_dialogue.py
git commit -m "fix(dialogue): translate all remaining dialogue entries and eliminate empty windows"
```

---

### Task 2: Unabridge All 143 Truncated Room Inspection Strings

**Files:**
- Modify: `translations/room_inspection_ru.json`
- Create: `tools/unabridge_inspection_strings.py`
- Test: `tools/test_inspection_translations.py`

**Interfaces:**
- Consumes: `translations/room_inspection_ru.json`.
- Produces: Updated `translations/room_inspection_ru.json` with 0 truncated sentences and 100% natural, complete phrasing.

- [ ] **Step 1: Re-author all 143 truncated inspection strings**
Write `tools/unabridge_inspection_strings.py`:
- Identify every entry in `translations/room_inspection_ru.json` where any line ends with `...` due to word cutoff.
- Provide a carefully crafted, complete Russian translation for each:
  - `"That upper\nwindow is open.\nToss in a rock?"`:
    `"Вон то окно\nоткрыто. Кинуть\nтуда камешек?"`
  - `"Someone's bound\nto trip on that\nstep."`:
    `"Кто-то точно\nспоткнётся на\nэтой ступеньке!"`
  - `"Look them in\nthe face when\nyou speak."`:
    `"Говоришь с\nкем-то — смотри\nпрямо в лицо."`
  - `"Older than me.\nStill pretty\nyoung, though."`:
    `"Старше меня, но\nвсё равно еще\nмолодой парень."`
  - `"Big place, but\nonly one door."`:
    `"Зал большой, а\nдверь наружу\nвсего одна."`
  - `"A tree this big\nought to have\nsome fruit."`:
    `"Такой гигант!\nХоть бы яблоки\nросли на нём."`
  - `"Turn this rock\nover and you'll\nfind tiny bugs."`:
    `"Подними камень —\nтам наверняка\nкуча букашек."`
  - `"Never saw this\ntower in town."`:
    `"Башня виднеется.\nВ самом городе\nеё не видать."`
  - `"Climb these\nstairs, go on,\nthen down the"`:
    `"Вверх по этой,\nчуть дальше и\nвниз по другой."`
  - And all remaining truncated strings.
- Verify that every re-authored string strictly satisfies:
  - $\le 15$ Unicode characters per line.
  - 1 to 3 lines per string.
  - NFC Unicode normalization.
  - 100% valid Cyrillic charmap glyphs.
  - Complete, natural punctuation (`.`, `!`, `?`, etc.) with no artificial trailing `...`.

- [ ] **Step 2: Update `translations/room_inspection_ru.json` and verify tests**
Run:
```bash
python3 tools/unabridge_inspection_strings.py
python3 -m pytest tools/test_inspection_translations.py
```
Expected: 100% tests pass.

- [ ] **Step 3: Commit changes**
```bash
git add translations/room_inspection_ru.json tools/unabridge_inspection_strings.py
git commit -m "fix(inspection): unabridge all 143 truncated inspection strings into complete sentences"
```

---

### Task 3: Full Master Rebuild & System Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/unabridged-master-report.md`

**Interfaces:**
- Consumes: Fully translated `dialogue.po`, unabridged `translations/room_inspection_ru.json`.
- Produces: Final bootable PS1 disc image with 100% complete Russian dialogue, zero blank windows, unabridged room inspection, and valid Mode 2 Form 1 EDC/ECC checksums.

- [ ] **Step 1: Execute master disc rebuild**
Run:
```bash
# 1. Build base disc with 100% translated dialogue (0 untranslated entries)
cd patch_repo && python3 localize.py build \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru \
  --output-dir localization-output/ru \
  --force
cd ..

# 2. Mirror base disc
cp patch_repo/localization-output/ru/slayers_royal_ru.* localization-output/ru/

# 3. Batch-patch all 149 room inspection entries with unabridged catalog
python3 tools/patch_inspection.py \
  --bin localization-output/ru/slayers_royal_ru.bin \
  --translations translations/room_inspection_ru.json \
  --all-rooms

# 4. Inject 13 Russian character lore cards and title banners
python3 tools/patch_lore_cards.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --cards data/lore_cards_ru.json

# 5. Mirror final disc
cp localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

- [ ] **Step 2: Verify disc integrity & EDC/ECC**
- Confirm size is exactly `712,300,848` bytes.
- Record final SHA-256 checksum.

- [ ] **Step 3: Run all regression test suites**
Run:
```bash
python3 -m pytest tools/ -v
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests -v
```
Expected: 100% tests pass.

- [ ] **Step 4: Spot check MAIN ST and inspection strings**
- Verify Scene `0x03C` entries (E028, E02E, E02F, E030, E031) have complete Russian dialogue.
- Verify `translations/room_inspection_ru.json` has 0 trailing `...` cutoffs.
- Verify `./run_game.sh --dry-run`.
- Write execution report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/unabridged-master-report.md`.
- Commit changes.
