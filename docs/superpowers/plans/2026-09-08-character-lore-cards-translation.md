# Slayers Royal PS1 Character Lore Cards Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify the exact storage and rendering mechanism of the in-game character lore cards (such as "[S] Naga the White Serpent") in the Slayers Royal PS1 disc, extract all corresponding Russian descriptions from *Slayers Royal: Ren'Py Edition*, develop an automated injection pipeline, and rebuild `slayers_royal_ru.bin` / `slayers_royal_ru.cue` so that all character information cards display in Russian.

**Architecture:**
1. Reverse-engineer the character status card subsystem in the PS1 ROM: trace the execution path from scene `0x03B` choice `ナ-ガの説明を見る` (record `E00D`) to find where the card layout, graphics, and text are stored.
2. Extract all ~10 character lore cards and descriptions from the Ren'Py edition (`renpy_extracted/game/help_cards.rpy` and `script.rpy`).
3. Implement an injection adapter (`tools/patch_lore_cards.py`) that encodes the Russian text according to the subsystem's font renderer and updates the corresponding archive entries.
4. Rebuild the localized PS1 disc image with recalculated Mode 2 Form 1 EDC/ECC checksums.
5. Verify in DuckStation and ensure zero regressions.

**Tech Stack:**
- Python 3.14 (Pillow, struct, binary patching)
- Slayers Royal CD-ROM tools (`patch.py`, `localize.py`, `tools/fit_dialogue_budget.py`)
- DuckStation emulator for visual verification

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Text source: Russian translation from `renpy_extracted/game/help_cards.rpy` and `script.rpy`.
- No regressions in story dialogue, font baseline, or scene budgets.
- All actions executed via subagents.

---

### Task 1: Reverse-Engineering & Locating Lore Card Data in PS1 ROM

**Files:**
- Create: `tools/inspect_lore_card.py`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/lore-cards-reverse-report.md`

**Interfaces:**
- Consumes: `downloads/sr.bin`, `localization-output/ru/slayers_royal_ru.bin`, `patch_repo/`.
- Produces: Exact archive, entry index, offset, and encoding format used by the character lore card screen.

- [x] **Step 1: Trace execution from scene 0x03B record E00D**
Analyze how `0x03B` calls the character explanation:
- Examine the bytecode around `0x03B:0x039A` (`E00D`).
- Identify the engine function/interrupt invoked when choice 1 is selected.
- Determine which file (`OPT.UNT`, `BASYOG.UNT`, `PROG.UNT`, or `SLPS_013.63`) contains the text data or rendering logic.

- [x] **Step 2: Inspect candidate resource archives**
Write `tools/inspect_lore_card.py` to search for:
- 8-bit, 16-bit, and compressed text tables corresponding to the 10 character cards:
  - Naga the White Serpent (`［さ］白蛇のナーガ`)
  - Zelgadis Greywords (`［ぜ］ゼルガディス`)
  - Amelia Wil Tesla Seyruun (`［あ］アメリア`)
  - Sylphiel Nels Lahda (`［し］シルフィール`)
  - Lark Dea Flamedore (`［ら］ラーク`)
  - Galef Kainsard (`［が］ガレフ`)
  - Spell descriptions (`［じ］呪文の特性の説明`)
  - Legend of Rezarium (`［れ］レザリアムの伝説`)
  - Necklaces of Rezarium (`［れ］レザリオムの首飾り`)
  - Magic of Rezarium (`レザリアムの魔法`)
- Identify font texture and character width table used for the proportional card font.

- [x] **Step 3: Document findings**
Write report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/lore-cards-reverse-report.md`.

---

### Task 2: Extract & Catalog Russian Lore Card Texts from Ren'Py

**Files:**
- Create: `tools/extract_renpy_lore_cards.py`
- Output: `data/lore_cards_ru.json`

**Interfaces:**
- Consumes: `renpy_extracted/game/script.rpy`, `renpy_extracted/game/help_cards.rpy`.
- Produces: Structured JSON catalog `data/lore_cards_ru.json` containing:
  - Card ID / Character Key
  - Title (e.g. `[С] Нага Белая Змея (Нага Змеюка)`)
  - Description body formatted for PS1 screen
  - Footnote / Synonym (e.g. `Синоним: помёт золотой рыбки`)

- [ ] **Step 1: Implement extractor script**
Write `tools/extract_renpy_lore_cards.py` to extract all `call show_character_info` invocations, pairing them with the Japanese and English reference comments.

- [ ] **Step 2: Format and validate extracted cards**
Ensure text fits within the PS1 character card text box dimensions.

- [ ] **Step 3: Save to `data/lore_cards_ru.json`**
Run:
```bash
python3 tools/extract_renpy_lore_cards.py --out data/lore_cards_ru.json
```

---

### Task 3: Develop Lore Card Injection Adapter

**Files:**
- Create: `tools/patch_lore_cards.py`
- Create: `tools/test_patch_lore_cards.py`

**Interfaces:**
- Consumes: `data/lore_cards_ru.json`, target PS1 archive (`OPT.UNT` / `PROG.UNT` / `BASYOG.UNT`).
- Produces: Patched archive containing Russian character lore cards with proper glyph encoding.

- [ ] **Step 1: Implement card text encoder**
Encode Russian text using the font renderer discovered in Task 1. If Cyrillic glyphs are needed, inject them into the card font texture sheet.

- [ ] **Step 2: Implement archive patcher**
Replace the English card entries with the newly encoded Russian card entries, updating archive entry headers and offsets.

- [ ] **Step 3: Write unit tests**
Implement `tools/test_patch_lore_cards.py` to verify round-trip encoding and archive integrity.
Run:
```bash
python3 -m pytest tools/test_patch_lore_cards.py
```

---

### Task 4: Disc Rebuild, Checksum Recalculation & Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/task-cards-final-report.md`

**Interfaces:**
- Consumes: Patched archives, `downloads/sr.bin`.
- Produces: Final bootable PS1 image `localization-output/ru/slayers_royal_ru.bin` with 100% translated character lore cards.

- [ ] **Step 1: Inject patched archives into CD-ROM image**
Write patched sectors into `slayers_royal_ru.bin` and recalculate Mode 2 Form 1 EDC/ECC checksums for all modified 2352-byte sectors.

- [ ] **Step 2: Verify disc integrity**
Confirm exact disc size `712,300,848` bytes and valid CUE descriptor.

- [ ] **Step 3: Visual verification**
Launch DuckStation via `./run_game.sh` and navigate to the tavern scene, select *«Посмотреть описание Наги»*, and verify that the Naga card is displayed in Russian.
