# Slayers Royal PS1: Restore Proportional Font on Lore Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the clean proportional font (*Liberation Sans*) on all character lore cards and banners in `tools/patch_lore_cards.py` so that long descriptive paragraphs fit neatly within the card boundaries without clipping or overflowing off the right edge of the screen, while keeping the retro pixel font (*Press Start 2P*) for in-game story dialogue, menus, and object inspection.

**Architecture:**
1. **Root Cause:**
   - In-game dialogue uses short lines ($\le 15$ characters per line on a 16x16 fixed-pitch tile grid), where *Press Start 2P* fits perfectly and looks authentically retro.
   - In contrast, character lore cards have paragraph-length descriptions ($30$ to $44$ characters per line on a 320x224 canvas).
   - A wide 8-bit pixel font cannot fit 40 characters on a 320px screen ($40 \times 10 = 400\text{px} > 320\text{px}$), causing the text to spill past the character portrait and off the right edge of the TV frame.
   - A proportional font like *Liberation Sans* (where narrow characters like `i`, `l`, `t` take 3–5px) fits all 44 characters easily in ~220px, keeping the text fully readable and within the left margin.
2. **Reconfiguration:**
   - Update `tools/patch_lore_cards.py` to prioritize `/usr/share/fonts/liberation/LiberationSans-Bold.ttf` and `/usr/share/fonts/liberation/LiberationSans-Regular.ttf`.
3. **Re-injection & Checksums:**
   - Re-render all 13 character lore cards and 11 title banners with *Liberation Sans*.
   - Inject into `localization-output/ru/slayers_royal_ru.bin` with Mode 2 Form 1 EDC/ECC checksum repair.
4. **Verification:**
   - Verify all unit and integration tests pass (73 tests).
   - Verify launcher dry run.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Dialogue font in VRAM atlas (`PROG.UNT 0x03A`): remains *Press Start 2P*.
- Lore cards font: *Liberation Sans* (Bold for titles, Regular with shadow for body lines).
- All tasks executed via subagents.

---

### Task 1: Reconfigure Lore Card Generator to Use Liberation Sans

**Files:**
- Modify: `tools/patch_lore_cards.py`
- Test: `tools/test_patch_lore_cards.py`

**Interfaces:**
- Consumes: `/usr/share/fonts/liberation/LiberationSans-Bold.ttf`, `/usr/share/fonts/liberation/LiberationSans-Regular.ttf`.
- Produces: Working card renderer using Liberation Sans with zero text clipping.

- [ ] **Step 1: Update `DEFAULT_FONT_SEARCH` in `tools/patch_lore_cards.py`**
In `tools/patch_lore_cards.py`:
Prioritize Liberation Sans in `DEFAULT_FONT_SEARCH`:
```python
DEFAULT_FONT_SEARCH = {
    "bold": [
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ...
    ],
    "regular": [
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ...
    ],
}
```

- [ ] **Step 2: Verify unit tests**
Run:
```bash
python3 -m pytest tools/test_patch_lore_cards.py -v
```
Expected: All 13 tests pass.

- [ ] **Step 3: Commit changes**
```bash
git add tools/patch_lore_cards.py
git commit -m "fix(lore-cards): restore proportional Liberation Sans font for character cards"
```

---

### Task 2: Re-inject Lore Cards into Disc Image & Final Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/lore-cards-font-fix-report.md`

**Interfaces:**
- Consumes: Reconfigured `tools/patch_lore_cards.py`, `data/lore_cards_ru.json`.
- Produces: Patched disc image with proportional text on all 13 lore cards.

- [ ] **Step 1: Inject re-rendered lore cards into disc**
Run:
```bash
python3 tools/patch_lore_cards.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --cards data/lore_cards_ru.json
```

- [ ] **Step 2: Mirror to `patch_repo/localization-output/ru/`**
Run:
```bash
cp -v localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

- [ ] **Step 3: Verify disc size and checksums**
Confirm file size is exactly `712,300,848` bytes and record new SHA-256.

- [ ] **Step 4: Run all regression test suites**
Run:
```bash
python3 -m pytest tools/ -v
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests -v
```
Expected: 73 / 73 tests pass (100%).

- [ ] **Step 5: Verify launcher dry-run and write execution report**
Run `./run_game.sh --dry-run`.
Write report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/lore-cards-font-fix-report.md`.
Commit changes to Git.
