# Slayers Royal (PS1) Russian Translation Port Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download the original Japanese PS1 release of *Slayers Royal* (`SLPS-01363`), extract the Russian fan translation from *Slayers Royal: Ren'Py Edition* (GameJolt), align and format dialogue according to the PS1 localization toolchain (`gourry-hacks/slayers_royal_1_patch`), and compile a fully localized Russian PS1 CD-ROM image (`slayers_royal_ru.bin` / `slayers_royal_ru.cue`).

**Architecture:**
1. Clone and configure the localization patch repository `gourry-hacks/slayers_royal_1_patch`.
2. Download and verify the pristine Japanese PS1 disc dump (`SLPS-01363`) from Internet Archive, matching exact SHA-256 and size specifications.
3. Download the Russian fan adaptation (Ren'Py Edition v0.9.9) from GameJolt, decompress its archive, and extract/decompile the Ren'Py scenario scripts.
4. Build a Python extraction and alignment pipeline that parses the Ren'Py scripts and maps Russian dialogue strings to the PS1 `dialogue.po` catalog, enforcing PS1 screen/memory constraints (Unicode NFC, max 15 chars/line, 1-3 lines/page, conditional continuation `\f`).
5. Validate the translated catalog with `localize.py validate` and build the localized BIN/CUE disc image with `localize.py build`.

**Tech Stack:**
- Python 3.14 (standard library + Pillow, unrpyc / rpatool)
- Shell utilities (`curl`, `tar`, `unzip`, `sha256sum`)
- Slayers Royal Localization Engine (`localize.py`, `patch.py`, `localization/`)
- Fonts: Liberation Sans Bold (`/usr/share/fonts/liberation/LiberationSans-Bold.ttf`) or DejaVu Sans

## Global Constraints
- Target Disc: Slayers Royal (Japan) (PS1, `SLPS-01363`).
- Target BIN SHA-256: `89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe`, size: `712,300,848` bytes.
- Required CUE SHA-256: `0f93f45114b7fc88b8f57c5449af0828e59699a8780849540a670df7c3a0aa08`.
- Line length limit: $\le 15$ Unicode characters per line.
- Page limit: 1 to 3 lines per page (separated by `\n`).
- Page continuation `\f`: allowed only for segments with continuation permission in the source disc (`0x00FD` terminator).
- Text encoding: Unicode NFC normalization.
- Subagent delegation: The top-level agent orchestrates via subagents; each task is executed by a subagent with clear acceptance criteria.

---

### Task 1: Environment & Tooling Setup

**Files:**
- Create: `requirements.txt`
- Repository clone: `slayers_royal_1_patch/`

**Interfaces:**
- Consumes: System Python 3.14, pip, git, system fonts.
- Produces: Working virtualenv/environment with `Pillow`, `pytest`, `unrpyc`, and verified `slayers_royal_1_patch` repository.

- [ ] **Step 1: Clone patch repository**
Run:
```bash
git clone https://github.com/gourry-hacks/slayers_royal_1_patch.git patch_repo
```

- [ ] **Step 2: Install required Python dependencies**
Create `requirements.txt` with:
```text
pillow>=10.0.0
pytest>=8.0.0
unrpyc>=1.1.0
```
Run:
```bash
python3 -m pip install --break-system-packages -r requirements.txt
```

- [ ] **Step 3: Verify patch repository unit tests**
Run:
```bash
cd patch_repo && python3 -m pytest localization/tests
```
Expected: All localization unit tests pass.

---

### Task 2: Japanese PS1 Disc Dump Acquisition & Source Export

**Files:**
- Create: `downloads/sr.bin`, `downloads/sr.cue`
- Modify: `patch_repo/`
- Output: `patch_repo/localization-work/ru/dialogue.po`, `patch_repo/localization-work/ru/source_inventory.json`

**Interfaces:**
- Consumes: Internet Archive repository `slayers-royal-japan`.
- Produces: Verified `sr.bin`, `sr.cue`, and exported Russian baseline `dialogue.po` catalog (4,514 segments).

- [ ] **Step 1: Download Japanese PS1 BIN and CUE**
Run:
```bash
mkdir -p downloads
curl -L -o "downloads/sr.bin" "https://archive.org/download/slayers-royal-japan/Slayers%20Royal%20(Japan).bin"
curl -L -o "downloads/sr.cue" "https://archive.org/download/slayers-royal-japan/Slayers%20Royal%20(Japan).cue"
```

- [ ] **Step 2: Verify BIN size and SHA-256 hash**
Run:
```bash
echo "89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe  downloads/sr.bin" | sha256sum -c -
```
Expected: `downloads/sr.bin: OK`

- [ ] **Step 3: Ensure exact CUE file format**
Create exact CRLF CUE file if needed:
```bash
python3 -c 'from pathlib import Path; Path("downloads/sr.cue").write_bytes(b"FILE \"sr.bin\" BINARY\r\n  TRACK 01 MODE2/2352\r\n    INDEX 01 00:00:00\r\n")'
```

- [ ] **Step 4: Verify disc with patcher tool**
Run:
```bash
cd patch_repo && python3 patch.py --bin "../downloads/sr.bin" --cue "../downloads/sr.cue" --verify-only
```
Expected: `source and patch files are valid`

- [ ] **Step 5: Export Russian PO catalog workspace**
Run:
```bash
cd patch_repo && python3 localize.py export --bin "../downloads/sr.bin" --locale ru --output localization-work/ru --force
```
Expected: Generates `localization-work/ru/dialogue.po`, `language.json`, and `source_inventory.json` with 4,514 translatable segments.

---

### Task 3: Ren'Py Russian Game Acquisition & Script Extraction

**Files:**
- Create: `downloads/renpy_game.tar.gz`, `renpy_extracted/`
- Decompiled scripts: `renpy_extracted/game/*.rpy`

**Interfaces:**
- Consumes: GameJolt site-api build 2022557 (`https://gamejolt.com/site-api/web/discover/games/builds/get-download-url/2022557`).
- Produces: Decompiled Ren'Py Russian scenario scripts (`.rpy`) and audio/voice manifests.

- [ ] **Step 1: Obtain signed download URL from GameJolt**
Run:
```bash
DOWNLOAD_URL=$(curl -s -X POST -H "x-gj-client-version: 2.0.0" \
  https://gamejolt.com/site-api/web/discover/games/builds/get-download-url/2022557 \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["payload"]["url"])')
curl -L -o "downloads/renpy_game.tar.gz" "$DOWNLOAD_URL"
```

- [ ] **Step 2: Unpack tar.gz and game zip**
Run:
```bash
mkdir -p renpy_raw
tar -xzf "downloads/renpy_game.tar.gz" -C renpy_raw/
unzip -q renpy_raw/*.zip -d renpy_extracted/
```

- [ ] **Step 3: Extract RPA archives and decompile RPYC to RPY**
If scripts are packaged in `.rpa` or compiled as `.rpyc`:
Run:
```bash
python3 -m unrpyc --help || pip install unrpyc
find renpy_extracted/ -name "*.rpyc" -exec python3 -m unrpyc {} +
```
Expected: Plaintext `.rpy` scripts available for inspection and text extraction under `renpy_extracted/`.

- [ ] **Step 4: Inspect and catalog scenario scripts**
Document script files, character speech tags (e.g. `lina`, `gourry`), voice cue tags (`voice "..."`), and scene progression.

---

### Task 4: Text Formatter & Dialogue Alignment Engine

**Files:**
- Create: `tools/text_wrapper.py`
- Create: `tools/test_text_wrapper.py`
- Create: `tools/align_renpy_to_po.py`
- Test: `tools/test_text_wrapper.py`

**Interfaces:**
- Consumes: `renpy_extracted/game/*.rpy`, `patch_repo/localization-work/ru/dialogue.po`.
- Produces: Populated `msgstr` entries in `patch_repo/localization-work/ru/dialogue.po` respecting all line and page constraints.

- [ ] **Step 1: Write text wrapper adhering to PS1 constraints**
Implement `tools/text_wrapper.py`:
- Line limit: $\le 15$ Unicode characters per line.
- Page limit: 1 to 3 lines per page (separated by `\n`).
- Page continuation `\f`: only permitted if `allow_continuation=True`. If not permitted, truncate or compress text to fit within 3 lines.
- Unicode normalization: NFC.
- Smart word-wrapping without breaking mid-word unless a single word exceeds 15 characters (in which case hyphenate).

- [ ] **Step 2: Write tests for text wrapper**
Implement `tools/test_text_wrapper.py`:
```python
import pytest
from text_wrapper import wrap_dialogue

def test_short_line():
    assert wrap_dialogue("Привет, мир!", allow_continuation=False) == "Привет, мир!"

def test_multi_line_wrap():
    text = "Это длинный текст который должен быть разбит на строки по пятнадцать знаков"
    wrapped = wrap_dialogue(text, allow_continuation=True)
    lines = wrapped.replace("\f", "\n").split("\n")
    for line in lines:
        assert len(line) <= 15
```
Run:
```bash
python3 -m pytest tools/test_text_wrapper.py
```
Expected: PASS

- [ ] **Step 3: Implement Ren'Py to PO Alignment Script**
Implement `tools/align_renpy_to_po.py`:
- Parse Ren'Py dialogue statements: extract speaker, text, and voice audio filename/cue.
- Parse `dialogue.po` entries: extract `msgctxt` (e.g., `dialogue/03B/E000/000`), `msgid` (Japanese text), and continuation capability.
- Map dialogue:
  1. Match by voice audio clips where Ren'Py voice tags match original PS1 sound files.
  2. Match by scene flow and speaker name sequence.
  3. Format matched Russian text through `wrap_dialogue`.
  4. Write updated `msgstr` to `localization-work/ru/dialogue.po`.

- [ ] **Step 4: Execute alignment tool**
Run:
```bash
python3 tools/align_renpy_to_po.py \
  --renpy-dir renpy_extracted \
  --po patch_repo/localization-work/ru/dialogue.po \
  --out patch_repo/localization-work/ru/dialogue.po
```
Expected: `dialogue.po` updated with translated Russian dialogue.

---

### Task 5: Validation & Quality Control

**Files:**
- Modify: `patch_repo/localization-work/ru/dialogue.po`
- Output: `validation_report.json`

**Interfaces:**
- Consumes: `patch_repo/localization-work/ru/dialogue.po`, `downloads/sr.bin`.
- Produces: 100% valid PO catalog conforming to `localize.py validate`.

- [ ] **Step 1: Run localize.py validation**
Run:
```bash
cd patch_repo && python3 localize.py validate \
  --bin "../downloads/sr.bin" \
  --workspace localization-work/ru \
  --locale ru \
  --allow-incomplete
```
Expected: Report of valid segments and any violations (lines > 15 chars, invalid `\f`, etc.).

- [ ] **Step 2: Automated remediation of formatting violations**
If validation reports formatting or line length errors, refine `tools/text_wrapper.py` and re-run alignment / post-processing fixup script.
Re-run validation until 0 formatting errors remain.

- [ ] **Step 3: Coverage and completeness audit**
Check translated vs untranslated segments:
Run:
```bash
python3 -c '
import polib
po = polib.pofile("patch_repo/localization-work/ru/dialogue.po")
total = len([e for e in po if e.msgid])
translated = len([e for e in po if e.msgid and e.msgstr])
print(f"Coverage: {translated}/{total} ({translated/total*100:.1f}%)")
'
```

---

### Task 6: Compile Localized Disc Image & Verify Output

**Files:**
- Output: `patch_repo/localization-output/ru/slayers_royal_ru.bin`
- Output: `patch_repo/localization-output/ru/slayers_royal_ru.cue`
- Output: `patch_repo/localization-work/ru/build/build_report.json`
- Output: `patch_repo/localization-work/ru/build/runtime_font.png`
- Output: `patch_repo/localization-work/ru/build/locale_glyphs.png`

**Interfaces:**
- Consumes: `patch_repo/localization-work/ru/dialogue.po`, `downloads/sr.bin`.
- Produces: Bootable PS1 BIN/CUE disc image with Russian translation and English baseline.

- [ ] **Step 1: Run localize.py build**
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
Expected: Successful build completing with `slayers_royal_ru.bin` and `slayers_royal_ru.cue` written to `localization-output/ru/`.

- [ ] **Step 2: Verify generated CD image integrity**
Check that `slayers_royal_ru.bin` matches expected PlayStation sector size (`712,300,848` bytes) and `slayers_royal_ru.cue` references `slayers_royal_ru.bin`.
Inspect `build_report.json` to verify font capacity and replaced sector counts.

- [ ] **Step 3: Final verification and deliverable review**
Confirm all artifacts are generated, clean, and ready for use in PlayStation emulators (DuckStation, Mednafen, ePSXe, RetroArch).
