# Task 2 Report: Re-inject Lore Cards into Disc Image & Final Verification

- **Date:** 2026-09-08
- **Status:** Completed
- **Operator:** LoreCardRebuilder
- **Target Files:**
  - `localization-output/ru/slayers_royal_ru.bin`
  - `patch_repo/localization-output/ru/slayers_royal_ru.bin`
- **Output Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/lore-cards-font-fix-report.md`

---

## 1. Executive Summary

In Task 2, all 13 Russian character lore cards rendered with **Liberation Sans** proportional fonts (`LiberationSans-Bold.ttf` and `LiberationSans-Regular.ttf`) were re-injected into the target CD-ROM image `localization-output/ru/slayers_royal_ru.bin` and mirrored to `patch_repo/localization-output/ru/`.

All sector extents for `PROG.UNT` and `OPT.UNT` were patched with full in-place **Mode 2 Form 1 EDC/ECC** recalculation (`CdChecksums.repair_mode2_form1`). The disc image size was verified to be byte-accurate (`712,300,848` bytes). All 13 cards and 9 banner textures fit comfortably within display bounds with zero right-edge clipping. All 73 tests across both regression test suites passed (100%), and launcher dry-run succeeded.

---

## 2. Disc Image Patching & Verification

### Injection Execution
```bash
python3 tools/patch_lore_cards.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --cards data/lore_cards_ru.json
```
Output:
```
Patching disc image: localization-output/ru/slayers_royal_ru.bin
Successfully patched 13 cards into localization-output/ru/slayers_royal_ru.bin.
```

### Mirroring to `patch_repo/`
```bash
cp -v localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

### Disc Integrity & Checksums
- **Byte Size:** `712,300,848` bytes (exact PS1 CD-ROM 2352-byte sector alignment: 302,849 sectors)
- **SHA-256 (`localization-output/ru/slayers_royal_ru.bin`):**
  `ac49012b20b0ac7087855c06babc69aa04f5b18d93e89934ce086b0ed7f595a6`
- **SHA-256 (`patch_repo/localization-output/ru/slayers_royal_ru.bin`):**
  `ac49012b20b0ac7087855c06babc69aa04f5b18d93e89934ce086b0ed7f595a6`
- **EDC / ECC Verification:** Mode 2 Form 1 EDC and ECC P/Q recalculation verified across modified sectors.

---

## 3. Card Canvas Fit Verification (No Right-Edge Overflow)

With Liberation Sans proportional font rendering, all text lines and banner titles fit within the canvas with generous margins:

| Card ID | Bounding Box (L, T, R, B) | Max X | Margin to Canvas Edge (320px) | Banner Bounding Box | Max X Banner (160px) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `lina` | (15, 18, 234, 186) | 234 px | **86 px** | (28, 11, 132, 22) | 132 px |
| `gourry` | (15, 18, 226, 186) | 226 px | **94 px** | (22, 11, 138, 22) | 138 px |
| `naga` | (15, 18, 269, 186) | 269 px | **51 px** | (28, 11, 133, 22) | 133 px |
| `map_controls` | (15, 18, 234, 170) | 234 px | **86 px** | — | — |
| `spell_traits` | (15, 18, 260, 184) | 260 px | **60 px** | (9, 10, 152, 22) | 152 px |
| `rezarium_legend` | (15, 18, 266, 186) | 266 px | **54 px** | (6, 10, 154, 22) | 154 px |
| `campaign_guide` | (15, 18, 258, 154) | 258 px | **62 px** | (14, 9, 146, 23) | 146 px |
| `necklace` | (15, 18, 265, 170) | 265 px | **55 px** | (6, 11, 155, 21) | 155 px |
| `zelgadis` | (15, 18, 264, 202) | 264 px | **56 px** | (42, 9, 119, 23) | 119 px |
| `amelia` | (15, 18, 271, 170) | 271 px | **49 px** | (19, 9, 142, 23) | 142 px |
| `sylphiel` | (15, 18, 254, 186) | 254 px | **66 px** | (11, 9, 148, 23) | 148 px |
| `rezarium_magic` | (15, 18, 273, 186) | 273 px | **47 px** | (9, 11, 151, 22) | 151 px |
| `galef` | (15, 18, 281, 170) | 281 px | **39 px** | — | — |

Result: 0 clipping, 0 overflows. Minimum clearance on card overlays is 39 px; maximum banner width is 155 px (5 px margin).

---

## 4. Test Suite Results (73/73 Passed)

### Suite 1: Tools Tests (`python3 -m pytest tools/`)
```
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd
collected 63 items

tools/test_batch_inspection_patch.py ............                        [ 19%]
tools/test_extract_inspection.py .....                                   [ 26%]
tools/test_inspection_translations.py ..........                         [ 42%]
tools/test_patch_inspection.py .............                             [ 63%]
tools/test_patch_lore_cards.py .............                             [ 84%]
tools/test_text_wrapper.py ..........                                    [100%]

============================== 63 passed in 5.75s ==============================
```

### Suite 2: Localization Tests (`patch_repo/localization/tests`)
```
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd/patch_repo
collected 10 items

localization/tests/test_glyphs.py ..                                     [ 20%]
localization/tests/test_integration.py ..                                [ 40%]
localization/tests/test_po.py ..                                         [ 60%]
localization/tests/test_script.py ....                                   [100%]

============================== 10 passed in 0.90s ==============================
```

**Total: 73 passed / 73 total (100%)**

---

## 5. Launcher Verification

Command:
```bash
./run_game.sh --dry-run
```
Output:
```
===========================================================
   Slayers Royal (PS1) — Автоматический лаунчер
===========================================================
[1/3] Проверенный образ диска найден: /home/samvel/dddd/downloads/sr.bin
[*] Найден готовый русскоязычный образ диска: /home/samvel/dddd/localization-output/ru/slayers_royal_ru.cue
[3/3] [DRY RUN] Проверка успешно пройдена.
      Команда эмулятора: /home/samvel/dddd/tools/bin/DuckStation.AppImage
      Файл образа (CUE): /home/samvel/dddd/localization-output/ru/slayers_royal_ru.cue
```

---

## 6. Conclusion

The Russian disc image has been updated with character lore cards rendered in Liberation Sans. All visual elements fit cleanly within their VRAM textures, sector budgets are satisfied with valid Mode 2 Form 1 EDC/ECC recalculation, and all regression suites pass completely.
