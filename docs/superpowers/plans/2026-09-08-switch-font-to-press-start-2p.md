# Slayers Royal PS1: Switch Font to Press Start 2P Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch the in-game font across the entire PlayStation 1 release of *Slayers Royal* (dialogue, choices, room object inspection, and lore cards) to the retro 8-bit pixel font *Press Start 2P* from `/home/samvel/Downloads/press-start-2p.zip`, re-rasterize the VRAM runtime font atlas, and recompile `slayers_royal_ru.bin`.

**Architecture:**
1. **Font Extraction & Assets:** Extract `PressStart2P.ttf` from `/home/samvel/Downloads/press-start-2p.zip` into `fonts/PressStart2P.ttf`.
2. **Glyph Generator Configuration:**
   - Update `patch_repo/localization/glyphs.py`:
     - Add `fonts/PressStart2P.ttf` as the top-priority font in `_font_path()`.
     - Configure `_render_mask` with optimal pixel font parameters: `font_size = 11`, fixed baseline `y = 12`, `anchor = "ls"`, horizontal centering.
     - Verify all Russian uppercase, lowercase, digits, and punctuation characters fit cleanly inside the $16 \times 16$ tile cell with 0 clipping.
   - Update `tools/patch_lore_cards.py` to use `fonts/PressStart2P.ttf` for lore card text overlays and title banners.
3. **Rebuild & Re-rasterization:**
   - Run `localize.py build` in `patch_repo` to generate the new VRAM font texture atlas with *Press Start 2P* pixel glyphs.
   - Batch-patch all 149 room inspection entries using `tools/patch_inspection.py`.
   - Inject lore cards rendered with *Press Start 2P*.
   - Recalculate Mode 2 Form 1 EDC/ECC checksums.
4. **Verification:**
   - Run all 68 unit and integration tests.
   - Verify disc size (712,300,848 bytes) and launcher dry-run.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Source Font: `/home/samvel/Downloads/press-start-2p.zip` -> `fonts/PressStart2P.ttf`.
- Pixel Grid: $16 \times 16$ per character cell, 15 max width, 14 max height, baseline $y = 12$.
- All tasks executed via subagents.

---

### Task 1: Font Integration & Typography Engine Configuration

**Files:**
- Create: `fonts/PressStart2P.ttf`
- Modify: `patch_repo/localization/glyphs.py`
- Modify: `tools/patch_lore_cards.py`
- Test: `patch_repo/localization/tests`, `tools/test_patch_lore_cards.py`

**Interfaces:**
- Consumes: `/home/samvel/Downloads/press-start-2p.zip`.
- Produces: Working font rasterizer using Press Start 2P with 0 clipping across all Cyrillic glyphs.

- [x] **Step 1: Extract font archive**
Extract `PressStart2P.ttf` to `fonts/PressStart2P.ttf`:
```bash
mkdir -p fonts
python3 -c "import zipfile; zipfile.ZipFile('/home/samvel/Downloads/press-start-2p.zip').extract('PressStart2P.ttf', 'fonts')"
```

- [x] **Step 2: Update `patch_repo/localization/glyphs.py`**
- In `_font_path()`: add `REPO_ROOT / "fonts" / "PressStart2P.ttf"` and `Path("/home/samvel/dddd/fonts/PressStart2P.ttf")` at the top of candidate list.
- In `_render_mask()`: configure pixel font rendering:
  ```python
  canvas = Image.new("L", (16, 16), 0)
  draw = ImageDraw.Draw(canvas)
  path = _font_path()
  font = ImageFont.truetype(str(path), 11)
  bbox = draw.textbbox((0, 12), text, font=font, anchor="ls")
  w = bbox[2] - bbox[0]
  if w <= 15:
      x = max(0, (16 - w) // 2)
      draw.text((x, 12), text, font=font, anchor="ls", fill=255)
      return canvas
  for size in range(10, 6, -1):
      candidate = ImageFont.truetype(str(path), size)
      candidate_box = draw.textbbox((0, 12), text, font=candidate, anchor="ls")
      width = candidate_box[2] - candidate_box[0]
      if width <= 15:
          x = max(0, (16 - width) // 2)
          draw.text((x, 12), text, font=candidate, anchor="ls", fill=255)
          return canvas
  ```

- [x] **Step 3: Update `tools/patch_lore_cards.py`**
In `DEFAULT_FONT_SEARCH`: add `fonts/PressStart2P.ttf` at the top of both `"bold"` and `"regular"` lists.

- [x] **Step 4: Run unit tests**
Run:
```bash
python3 -m pytest tools/test_patch_lore_cards.py tools/test_text_wrapper.py
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests
```
Expected: 100% tests pass.

- [x] **Step 5: Commit changes**
```bash
git add fonts/PressStart2P.ttf patch_repo/localization/glyphs.py tools/patch_lore_cards.py
git commit -m "feat(font): integrate Press Start 2P pixel font for Russian localization"
```

---

### Task 2: Rebuild Disc Image & Full System Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/press-start-2p-report.md`

**Interfaces:**
- Consumes: Reconfigured glyph renderer, `translations/room_inspection_ru.json`, `data/lore_cards_ru.json`.
- Produces: Final bootable PS1 disc image with *Press Start 2P* pixel font.

- [ ] **Step 1: Execute master build with Press Start 2P font**
Run:
```bash
# 1. Rebuild base disc with new font atlas
cd patch_repo && python3 localize.py build \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru \
  --output-dir localization-output/ru \
  --force
cd ..

# 2. Mirror base disc
cp patch_repo/localization-output/ru/slayers_royal_ru.* localization-output/ru/

# 3. Batch-patch all 149 room inspection entries
python3 tools/patch_inspection.py \
  --bin localization-output/ru/slayers_royal_ru.bin \
  --translations translations/room_inspection_ru.json \
  --all-rooms

# 4. Inject lore cards rendered with Press Start 2P
python3 tools/patch_lore_cards.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --cards data/lore_cards_ru.json

# 5. Mirror final disc
cp localization-output/ru/slayers_royal_ru.* patch_repo/localization-output/ru/
```

- [ ] **Step 2: Verify disc integrity & checksums**
- Verify file size: exactly `712,300,848` bytes.
- Record new SHA-256 hash.

- [ ] **Step 3: Run all regression test suites**
Run:
```bash
python3 -m pytest tools/ -v
cd patch_repo && SLAYERS_ROYAL_BIN="$(realpath ../downloads/sr.bin)" python3 -m pytest localization/tests -v
```
Expected: All 68 tests pass.

- [ ] **Step 4: Verify launcher dry-run & write final report**
Run `./run_game.sh --dry-run`.
Write execution report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/press-start-2p-report.md`.
Commit all changes to Git.
