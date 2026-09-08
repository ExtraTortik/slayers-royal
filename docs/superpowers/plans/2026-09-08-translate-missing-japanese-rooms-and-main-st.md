# Slayers Royal PS1: Restore & Translate Missing Rooms (Main St & 36 Others) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore and translate all 37 room inspection locations that were completely omitted (blanked out) by the English fan translation—specifically Lakewood MAIN ST (`0x059`, 43 strings) and 36 other exploration rooms across the game—directly from the original Japanese source ROM (`source_prog`) into authentic Russian, add them to `translations/room_inspection_ru.json`, and patch `slayers_royal_ru.bin` so that MAIN ST and all previously blank rooms have full, working Russian hover and inspection descriptions.

**Architecture:**
1. **Root Cause Analysis:**
   - In the Japanese original (`downloads/sr.bin`), Room `0x059` (Lakewood MAIN ST) and 36 other rooms have active, witty inspection strings (e.g. `建物や木々の間から空が見えるわ.`, `赤い屋根の家の向こうに,何かの塔がたってるみたいだけど.`, `なにか井戸のそばで話してるわね.`, `地面よ. だから,地面だって. 何も落ちてないわよ.`, `ただのじいさんね. 杖を持ってるから魔道士だ,なんて事はないと思うわよ.`).
   - The English fan translator completely blanked out all strings in these 37 rooms (filled with zeros / `""`).
   - Consequently, our previous English extraction saw empty strings and skipped them.
2. **Extraction from Japanese Source:**
   - Write `tools/extract_missing_japanese_rooms.py` to extract and decode all strings from the 37 omitted rooms in `source_prog` using `sr_charmap.py`.
   - Output structured Japanese inspection catalog for these 37 rooms.
3. **Translation & Linguistic Formatting:**
   - Translate all extracted strings into authentic Russian in the voice of Lina Inverse.
   - Enforce $\le 15$ characters per line, 1–3 lines per string, NFC normalization.
   - Integrate them into `translations/room_inspection_ru.json`.
4. **Batch Injection & Disc Rebuild:**
   - Extend `tools/patch_inspection.py` to support patching rooms from Japanese source pointers or directly re-allocating string blocks for previously zeroed rooms.
   - Patch all 37 missing rooms into `localization-output/ru/slayers_royal_ru.bin`.
   - Recalculate Mode 2 Form 1 EDC/ECC checksums.
5. **Verification:**
   - Verify `0x059` (MAIN ST) contains 43 non-empty Russian strings.
   - Run all regression tests.
   - Test launcher dry-run.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Scope: 37 previously blank rooms, including `0x059` (MAIN ST, 43 strings).
- Constraints: $\le 15$ characters per line, 1–3 lines per string, 16-bit Cyrillic charmap words.
- All tasks executed via subagents.

---

### Task 1: Extract & Translate Japanese Strings for All 37 Omitted Rooms

**Files:**
- Create: `tools/extract_missing_japanese_rooms.py`
- Modify: `translations/room_inspection_ru.json`
- Output: `data/missing_rooms_jp_ru.json`

**Interfaces:**
- Consumes: `source_prog` (`downloads/sr.bin`), `patch_repo/localization/sr_charmap.py`.
- Produces: Complete Russian translations for all 37 omitted rooms in `translations/room_inspection_ru.json`.

- [ ] **Step 1: Implement Japanese room extractor**
Write `tools/extract_missing_japanese_rooms.py`:
- Scan all entries `0x059`..`0x0F8` in `source_prog`.
- Identify the 37 rooms where Japanese has strings but English had `""`.
- Decode all Japanese strings using `CHARMAP`.
- Save raw Japanese strings to `data/missing_rooms_jp_ru.json`.

- [ ] **Step 2: Translate strings into authentic Russian**
Translate all strings into Russian in Lina Inverse's voice:
- Room `0x059` (Lakewood MAIN ST):
  - `0`: `Небо между\nдеревьями.`
  - `2`: `Хорошая погода.`
  - `3`: `Вон там вдали\nвидны деревья.`
  - `6`: `Горы виднеются.`
  - `8`: `За домом с\nкрасной крышей\nкакая-то башня.`
  - `10`: `Дерево на\nплощадке, а под\nним — колодец.`
  - `14`: `Около колодца\nболтают. Местное\nвече, не иначе.`
  - `20`: `Дом с красной\nкрышей. Похоже,\nкакая-то лавка.`
  - `22`: `Вывеска совсем\nоблезла, не\nразобрать.`
  - `25`: `Каменные\nступени.`
  - `27`: `Кустарник у\nдороги.`
  - `28`: `Какой-то мелкий\nпацан.`
  - `30`: `Вроде бы это\nтаверна. Днём\nзаперта.`
  - `33`: `Земля.`
  - `34`: `Да земля же,\nговорю тебе!`
  - `35`: `Ничего там не\nваляется, не\nнадейся.`
  - `40`: `Обычный старик.`
  - `41`: `Держит посох,\nно на мага явно\nне тянет.`
- And all remaining 36 rooms.
- Enforce $\le 15$ characters per line and 1–3 lines per string.
- Update `translations/room_inspection_ru.json` with per-room entries or direct keys.

- [ ] **Step 3: Commit extractor and translations**
```bash
git add tools/extract_missing_japanese_rooms.py translations/room_inspection_ru.json data/missing_rooms_jp_ru.json
git commit -m "feat(inspection): extract and translate 37 omitted rooms from Japanese source"
```

---

### Task 2: Implement Missing Rooms Injection & Sector Allocation

**Files:**
- Modify: `tools/patch_inspection.py`
- Test: `tools/test_batch_inspection_patch.py`

**Interfaces:**
- Consumes: `data/missing_rooms_jp_ru.json`, `translations/room_inspection_ru.json`.
- Produces: Patching engine capable of rebuilding rooms using Japanese source pointer layouts when English entries were zeroed.

- [ ] **Step 1: Extend `tools/patch_inspection.py` to support Japanese base layouts**
When a room in `english_prog` was zeroed out (empty strings):
- Fall back to the pointer table structure of `source_prog` for that room.
- Replace strings with the Russian translations.
- Encode into 16-bit Cyrillic words via `charmap`.
- Rebuild the string block and pointer table.
- Verify entry size does not exceed `entry.size`.

- [ ] **Step 2: Run tests**
Verify that all 37 rooms patch cleanly with zero overflows:
```bash
python3 -m pytest tools/test_batch_inspection_patch.py
```

- [ ] **Step 3: Commit changes**
```bash
git add tools/patch_inspection.py tools/test_batch_inspection_patch.py
git commit -m "feat(inspection): support patching omitted rooms from Japanese source pointer layout"
```

---

### Task 3: Full Disc Rebuild, Checksum Recalculation & Final Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/main-st-restoration-report.md`

**Interfaces:**
- Consumes: Patched inspection entries, `dialogue.po`, lore cards.
- Produces: Master PS1 disc image with 100% working hover descriptions on MAIN ST and all 37 previously blank rooms.

- [ ] **Step 1: Execute master build**
Run:
```bash
# Batch patch all rooms including the 37 restored rooms
python3 tools/patch_inspection.py \
  --bin localization-output/ru/slayers_royal_ru.bin \
  --all-rooms

# Mirror to patch_repo/
cp localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

- [ ] **Step 2: Spot check Room 0x059 (MAIN ST)**
Verify with `--dump --entry 0x059`:
Confirm all 43 strings are non-empty Russian strings (`Небо между деревьями.`, `Старик с посохом.`, etc.).

- [ ] **Step 3: Run all regression tests**
Run:
```bash
python3 -m pytest tools/ -v
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests -v
```
Expected: All tests pass.

- [ ] **Step 4: Verify launcher & document report**
Test `./run_game.sh --dry-run`.
Write report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/main-st-restoration-report.md`.
Commit all changes to Git.
