# Slayers Royal PS1: Full-Game Room Object Inspection Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate all object inspection and environmental examination strings across all 149 interactive rooms and locations in the game (`PROG.UNT` entries `0x059`..`0x0F8`) from English into authentic, characterful Russian in the voice of Lina Inverse, encode them into 16-bit Cyrillic charmap words, recalculate all room pointer tables, and rebuild `slayers_royal_ru.bin` so that 100% of examined objects in every town, dungeon, inn, shop, and castle are fully localized.

**Architecture:**
1. **Extraction & Cataloging:** Scan all 160 entries (`0x059`..`0x0F8`) in `PROG.UNT` using `tools/patch_inspection.py`'s parsing engine. Extract all 1,904 string instances and deduplicate them into exactly 734 unique translatable strings, cataloged with their occurrence counts, room IDs, and context in `data/full_inspection_catalog.json`.
2. **Translation & Linguistic Adaptation:** Translate all 734 unique strings into natural, expressive Russian matching Lina Inverse's humorous, cynical tone from the anime and light novels. Enforce strict line length limits ($\le 15$ characters per line) and page height limits (1–3 lines per page separated by `\n`).
3. **Batch Injection Engine:** Extend `tools/patch_inspection.py` to process all 149 rooms in a single automated batch pass. For each room: rebuild the string block, recalculate 32-bit big-endian RAM pointers (`0x00200000 + offset`), preserve pointer deduplication, update header relocation fields at `0x0024`, `0x002C`, `0x0030`, and verify that the rebuilt entry fits within its allocated sector boundary.
4. **Disc Rebuild & EDC/ECC Checksum Recalculation:** Inject the patched rooms into `localization-output/ru/slayers_royal_ru.bin` and recalculate Mode 2 Form 1 EDC (CRC-32) and L-EC (Reed-Solomon P/Q) checksums across all modified sectors.
5. **Quality Assurance & Verification:** Validate with unit tests covering encoding, pointer relocation, and sector bounds across all 149 rooms. Verify launcher dry-run and spot-check key locations in DuckStation.

**Tech Stack:**
- Python 3.14 (standard library + Pillow, struct)
- Slayers Royal CD-ROM tools (`tools/patch_inspection.py`, `tools/patch_lore_cards.py`)
- Test runner: `pytest`

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Total Scope: 149 valid room entries (`0x059`..`0x0F8`), 734 unique translatable strings, 1,904 total string references.
- Display Limits: $\le 15$ Unicode characters per line, at most 3 lines per page (`\n` line break, `0x00FF` terminator).
- Character Encoding: 16-bit big-endian Cyrillic charmap words via `patch_repo`'s verified Russian glyph atlas.
- Subagent Rule: Top-level agent orchestrates via subagents; tasks must be self-contained and verifiable.

---

### Task 1: Comprehensive Inspection String Extraction & Cataloging

**Files:**
- Create: `tools/extract_all_inspection_strings.py`
- Output: `data/full_inspection_catalog.json`

**Interfaces:**
- Consumes: `english_prog` extracted from `downloads/sr.bin` / `localization-output/ru/slayers_royal_ru.bin`.
- Produces: Complete JSON catalog `data/full_inspection_catalog.json` containing all 734 unique strings mapped to room IDs, offsets, and categories.

- [ ] **Step 1: Implement full inspection extractor**
Write `tools/extract_all_inspection_strings.py`:
- Iterate through all 160 entries (`0x059` to `0x0F8`) in `PROG.UNT`.
- Use `parse_inspection_entry` to extract all valid string tables.
- Filter out empty strings (`""`) and placeholders (`"UNDER\nCONSTRUCTION"`).
- Deduplicate into a dictionary of 734 unique strings, recording:
  - `english`: original English string.
  - `occurrences`: list of `{room_id, pointer_indices}`.
  - `frequency`: total occurrence count.
  - `category`: categorized into `common_object`, `town_specific`, `dungeon_specific`, `npc_observation`, `story_hint`.

- [ ] **Step 2: Run extractor and verify catalog completeness**
Run:
```bash
python3 tools/extract_all_inspection_strings.py --out data/full_inspection_catalog.json
```
Expected output: Exactly 734 unique strings extracted from 149 valid room entries.

- [ ] **Step 3: Commit extractor and dataset**
```bash
git add tools/extract_all_inspection_strings.py data/full_inspection_catalog.json
git commit -m "feat: extract and catalog all 734 unique room inspection strings across 149 rooms"
```

---

### Task 2: Translation & Text Formatting of the Master Inspection Catalog

**Files:**
- Modify: `data/full_inspection_catalog.json`
- Create: `tools/build_inspection_translations.py`
- Test: `tools/test_inspection_translations.py`

**Interfaces:**
- Consumes: `data/full_inspection_catalog.json`.
- Produces: Populated `russian` fields for all 734 unique strings, 100% compliant with $\le 15$ characters per line and 1–3 lines per page.

- [ ] **Step 1: Implement translation builder with category-specific glossaries**
Write `tools/build_inspection_translations.py` with structured translation modules:
1. **Recurring Common Objects (approx. 120 strings):**
   - Walls, doors, windows, ceilings, floorboards, stairs, railings, roofs.
   - Furniture: chairs, tables, beds, benches, counters, shelves, desks, chests, wardrobes.
   - Lighting & fire: lamps, cords, hanging lamps, lanterns, candles, candlesticks, chandeliers, fireplaces, hearths, chimneys, torches.
   - Utensils & containers: bottles, jars, cups, mugs, barrels, crates, boxes, sacks, pots, pans, dishes, water jars.
   - Nature: trees, bushes, flowers, grass, weeds, mountains, sky, clouds, rivers, streams, rocks, stones, dirt, cliffs, wells.
2. **Town Establishments (approx. 280 strings):**
   - **Lakewood & Burkland:** forest village huts, lumber yards, wooden bridges, town squares.
   - **Grumstock & Freeground:** frontier market stalls, outposts, town gates, watchtowers.
   - **Sonia & Iselsen:** canal districts, docks, warehouses, residential alleyways.
   - **Saillune (City of White Magic):** grand cathedrals, royal palaces, marble colonnades, statues, libraries, guildhalls.
   - **Quezax & Sumbulk:** coastal ports, lighthouses, merchant ships, bazaars, seafood stalls.
   - **Truecity:** industrial workshops, guild headquarters, clock towers, stone streets.
3. **Dungeons & Lore Locations (approx. 200 strings):**
   - **Bandit Caves & Mountain Passes:** stalactites, stone pillars, rope bridges, campfires, iron bars, trapdoors.
   - **Catacombs & Ancient Ruins:** sarcophagi, elven altars, mossy runes, stone tablets, glowing crystals, sealed gates, magical devices.
   - **Sorcerer Towers & Shrines:** spellbooks, alchemical apparatus, crystal orbs, astrological maps, magical circles, summon pedestals.
   - **Rezarium Final Dungeons:** ancient control mechanisms, elven seal chambers, dimensional mirrors.
4. **NPC & Crowd Observations (approx. 134 strings):**
   - Lina's snarky, witty commentary on patrons, innkeepers, barkeeps, merchants, guards, drunkards, priests, scholars, and shady characters.

- [ ] **Step 2: Line wrapping & constraint validation**
Incorporate `tools/text_wrapper.py` logic to format each translation:
- Each line length strictly $\le 15$ characters.
- Between 1 and 3 lines per string (joined with `\n`).
- NFC Unicode normalization.
- Punctuation and quotation marks adapted for retro PS1 bitmap font.

- [ ] **Step 3: Implement validation test suite**
Write `tools/test_inspection_translations.py`:
- Verifies all 734 entries have non-empty Russian translations.
- Verifies every line $\le 15$ characters.
- Verifies every string $\le 3$ lines.
- Verifies all characters exist in Cyrillic `charmap`.
Run:
```bash
python3 -m pytest tools/test_inspection_translations.py
```
Expected: 100% tests pass.

- [ ] **Step 4: Commit translated catalog**
```bash
git add data/full_inspection_catalog.json tools/build_inspection_translations.py tools/test_inspection_translations.py
git commit -m "feat: complete Russian translation for all 734 room inspection strings"
```

---

### Task 3: Automated Batch Injection Pipeline & Sector Budget Enforcer

**Files:**
- Modify: `tools/patch_inspection.py`
- Create: `tools/test_batch_inspection_patch.py`

**Interfaces:**
- Consumes: `data/full_inspection_catalog.json`, `tools/patch_inspection.py`.
- Produces: Batch-patching engine that updates all 149 room inspection entries in `PROG.UNT` with zero sector overflows.

- [ ] **Step 1: Extend `tools/patch_inspection.py` for full batch injection**
Add `--batch` mode to `tools/patch_inspection.py`:
- Accepts `data/full_inspection_catalog.json` mapping English strings to Russian strings.
- Iterates over all 149 entries in `PROG.UNT` (`0x059`..`0x0F8`).
- For each entry:
  - Parses existing string table and pointer table.
  - Replaces each string with its Russian translation from the catalog.
  - Re-encodes using 16-bit big-endian words via `charmap`.
  - Rebuilds string block and pointer table.
  - Updates header pointers at `0x0024`, `0x002C`, `0x0030`.
  - Zero-pads to entry sector size (`entry.size`).
  - Asserts `rebuilt_size <= entry.size`. If any room exceeds capacity, automatically applies progressive line condensation (`tools/text_wrapper.py:shorten_lines`) until it fits within its proven sector allocation.

- [ ] **Step 2: Write batch unit and regression tests**
Implement `tools/test_batch_inspection_patch.py`:
- Verifies all 149 rooms patch successfully in synthetic and real `PROG.UNT`.
- Verifies 0 sector overflows across all 149 rooms.
- Verifies pointer table integrity and round-trip readability.
Run:
```bash
python3 -m pytest tools/test_batch_inspection_patch.py
```
Expected: PASS.

- [ ] **Step 3: Commit batch injection engine**
```bash
git add tools/patch_inspection.py tools/test_batch_inspection_patch.py
git commit -m "feat: implement automated batch injection engine for 149 room inspection entries"
```

---

### Task 4: Full Disc Rebuild, Checksum Recalculation & Comprehensive Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/full-inspection-final-report.md`

**Interfaces:**
- Consumes: All 149 patched inspection entries, 13 lore cards, updated `dialogue.po`.
- Produces: Final bootable PS1 disc image with 100% translated room inspection objects across the entire game.

- [ ] **Step 1: Execute complete batch patching**
Run:
```bash
# 1. Rebuild base dialogue with 0 untranslated choices
cd patch_repo && python3 localize.py build \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru \
  --output-dir localization-output/ru \
  --allow-incomplete \
  --force
cd ..

# 2. Mirror to localization-output/ru/
cp patch_repo/localization-output/ru/slayers_royal_ru.* localization-output/ru/

# 3. Batch-patch all 149 room inspection entries
python3 tools/patch_inspection.py \
  --bin localization-output/ru/slayers_royal_ru.bin \
  --catalog data/full_inspection_catalog.json \
  --all-rooms

# 4. Inject 13 character lore cards and banners
python3 tools/patch_lore_cards.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --cards data/lore_cards_ru.json

# 5. Mirror back to patch_repo/
cp localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

- [ ] **Step 2: Verify binary integrity & recalculate sector checksums**
Confirm:
- File size: exactly `712,300,848` bytes.
- All Mode 2 Form 1 sectors pass CRC-32 EDC and Reed-Solomon L-EC checksum validation.
- Compute and record final SHA-256 hash.

- [ ] **Step 3: Run all test suites**
Run:
```bash
python3 -m pytest tools/ -v
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests -v
```
Expected: 100% tests pass (over 50 tests total).

- [ ] **Step 4: Spot-check room inspections across diverse locations**
Dump and inspect sample strings from:
- Lakewood Tavern (`0x05D`): «Подвесная лампа.», «Деревянный стол.»
- Lakewood Inn (`0x060`): «Стойка регистрации.», «Книга постояльцев.»
- Armory (`0x062`): «Оружейная витрина.», «Железный меч.»
- Item Shop (`0x063`): «Полки с зельями.», «Стеклянный флакон.»
- Magic Guild (`0x068`): «Магический свиток.», «Круг призыва.»
- Saillune Palace (`0x098`): «Мраморная колонна.», «Герб Сейруна.»
- Bandit Cave (`0x074`): «Костёр бандитов.», «Факел на стене.»
- Rezarium Ruins (`0x0E0`): «Эльфийский алтарь.», «Печать Резариума.»

- [ ] **Step 5: Verify automated launcher and document deliverable**
Run `./run_game.sh --dry-run`.
Write comprehensive execution report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/full-inspection-final-report.md`.
Commit all changes and report to Git.
