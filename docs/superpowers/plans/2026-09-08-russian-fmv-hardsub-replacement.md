# Slayers Royal PS1: Russian FMV Subtitles Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the English hardsubbed FMV cutscenes in `MOVIE.STR` on the PlayStation 1 disc image (`slayers_royal_ru.bin`) with high-quality Russian hardsubbed FMVs using the official Russian subtitle files (`renpy_extracted/game/videos/s01_ru.srt`..`s11_ru.srt`), encoded in native PlayStation 1 MDEC STR format (320×240 @ 15 fps, CD-XA ADPCM audio, 2,352-byte sectors), with full Mode 2 Form 1 EDC/ECC sector checksum verification.

**Architecture:**
1. **Toolchain:** Build and install `psxavenc` into `tools/bin/psxavenc` from `https://github.com/WonderfulToolchain/psxavenc.git` to handle native PS1 MDEC video encoding and CD-XA multiplexing.
2. **Video Asset Pipeline (`tools/fmv_pipeline.py`):**
   - Demux/map the 12 movies in `MOVIE.STR` (LBA 127, 184,290 sectors total) with exact sector bounds:
     - `s00` (Movie 0, LBA 127, 13,501 sectors): Opening movie (unsubbed music) — keep original.
     - `s01`..`s11` (Movies 1 to 11): Story cutscenes with voice acting.
   - For each cutscene $1..11$:
     - Use clean video source from `renpy_extracted/game/videos/sXX.webm`.
     - Burn `sXX_ru.srt` subtitles with `ffmpeg` (Liberation Sans Bold, white with 1.5px black outline, 320×240 @ 15 fps, 18,900 Hz mono audio).
     - Encode to PS1 STR format with `psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001`.
     - Pad/truncate to match the exact sector bounds of the movie on the CD-ROM.
3. **Disc Injection & Sector Checksums:**
   - Inject the re-encoded Russian movie streams into `MOVIE.STR` in `localization-output/ru/slayers_royal_ru.bin`.
   - Recalculate Mode 2 Form 1 EDC (CRC-32) and L-EC (Reed-Solomon P/Q) checksums across all replaced sectors.
   - Maintain 100% integrity of dialogue, room inspection, and lore cards.
4. **Verification:**
   - Verify all test suites pass.
   - Extract sample frames from each movie on the disc and verify Russian subtitles are present.
   - Verify launcher dry run.

## Global Constraints
- Target Disc: `localization-output/ru/slayers_royal_ru.bin` (712,300,848 bytes) and `slayers_royal_ru.cue`.
- Total Movie Sectors in `MOVIE.STR`: exactly 184,290 sectors starting at LBA 127.
- Video Format: MDEC BS v2, 320×240, 15 fps, CD-XA 18.9 kHz mono audio, Mode 2 Form 1 / 2,352-byte sectors.
- Subtitle Source: `renpy_extracted/game/videos/s01_ru.srt`..`s11_ru.srt`.
- All tasks executed via subagents.

---

### Task 1: Video Toolchain Setup & Movie Stream Mapping

**Files:**
- Create: `tools/bin/psxavenc`
- Create: `tools/fmv_pipeline.py`
- Test: `tools/test_fmv_pipeline.py`

**Interfaces:**
- Consumes: `https://github.com/WonderfulToolchain/psxavenc.git`, `downloads/sr.bin`.
- Produces: Compiled `psxavenc` binary in `tools/bin/`, movie stream sector map.

- [ ] **Step 1: Clone and build psxavenc**
Clone `https://github.com/WonderfulToolchain/psxavenc.git`, fix missing `#include <libavutil/mem.h>` in `mdec.c`, build with meson/ninja, and install binary to `tools/bin/psxavenc`.
Verify:
```bash
./tools/bin/psxavenc -t strcd -h
```

- [ ] **Step 2: Implement movie stream sector mapping in `tools/fmv_pipeline.py`**
Formalize the exact starting sector and length of each movie:
```python
MOVIE_MAP = {
    0:  {"name": "s00", "rel_sec": 0,      "sectors": 13501, "subbed": False},
    1:  {"name": "s01", "rel_sec": 13501,  "sectors": 12800, "subbed": True},
    2:  {"name": "s02", "rel_sec": 26301,  "sectors": 23399, "subbed": True},
    3:  {"name": "s03", "rel_sec": 49700,  "sectors": 10308, "subbed": True},
    4:  {"name": "s04", "rel_sec": 60008,  "sectors": 12384, "subbed": True},
    5:  {"name": "s05", "rel_sec": 72392,  "sectors": 19570, "subbed": True},
    6:  {"name": "s06", "rel_sec": 91962,  "sectors": 9792,  "subbed": True},
    7:  {"name": "s07", "rel_sec": 101754, "sectors": 9920,  "subbed": True},
    8:  {"name": "s08", "rel_sec": 111674, "sectors": 11877, "subbed": True},
    9:  {"name": "s09", "rel_sec": 123551, "sectors": 26802, "subbed": True},
    10: {"name": "s10", "rel_sec": 150353, "sectors": 3456,  "subbed": True},
    11: {"name": "s11", "rel_sec": 153809, "sectors": 30481, "subbed": True},
}
```

- [ ] **Step 3: Implement unit tests in `tools/test_fmv_pipeline.py`**
Verify sector map sums to 184,290 and `psxavenc` tool runs.
Run:
```bash
python3 -m pytest tools/test_fmv_pipeline.py
```

---

### Task 2: Subtitle Burning & PS1 STR Encoding Engine

**Files:**
- Modify: `tools/fmv_pipeline.py`
- Test: `tools/test_fmv_pipeline.py`

**Interfaces:**
- Consumes: `renpy_extracted/game/videos/s*.webm`, `renpy_extracted/game/videos/s*_ru.srt`, `tools/bin/psxavenc`.
- Produces: Encoded Russian PS1 STR movie streams matching exact sector bounds.

- [ ] **Step 1: Implement subtitle burn and encode function**
In `tools/fmv_pipeline.py`:
- `encode_movie(movie_idx, webm_path, srt_path, out_str_path)`:
  - Run `ffmpeg` to hardcode `srt_path` onto `webm_path` at 320x240, 15fps, 18900Hz mono audio into intermediate uncompressed AVI.
  - Run `psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001` to generate `.str`.
  - Ensure output file is padded with null sectors or trimmed to match `MOVIE_MAP[idx]["sectors"]`.

- [ ] **Step 2: Test encoding on a sample movie (e.g. s01)**
Verify that `s01` encodes to exactly 12,800 sectors (30,105,600 bytes) and that subtitles are visible on decoded frames.

- [ ] **Step 3: Commit pipeline changes**
```bash
git add tools/fmv_pipeline.py tools/test_fmv_pipeline.py
git commit -m "feat(fmv): implement Russian subtitle burning and PS1 STR encoding pipeline"
```

---

### Task 3: Disc Rebuild with Russian MOVIE.STR & Final Verification

**Files:**
- Modify: `localization-output/ru/slayers_royal_ru.bin`
- Modify: `localization-output/ru/slayers_royal_ru.cue`
- Output: `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/russian-fmv-final-report.md`

**Interfaces:**
- Consumes: Re-encoded movie streams, `localization-output/ru/slayers_royal_ru.bin`.
- Produces: Final bootable PS1 disc image with 100% Russian FMVs, 100% Russian dialogue, 149 Russian rooms, and 13 lore cards.

- [ ] **Step 1: Batch encode and inject all 11 subtitled movies into disc**
Run:
```bash
python3 tools/fmv_pipeline.py \
  --disc localization-output/ru/slayers_royal_ru.bin \
  --videos-dir renpy_extracted/game/videos \
  --all-movies
```

- [ ] **Step 2: Recalculate Mode 2 Form 1 EDC/ECC checksums**
Recalculate checksums for all modified sectors in `MOVIE.STR` (LBA 127..184416).

- [ ] **Step 3: Mirror to `patch_repo/localization-output/ru/`**
Sync binary and CUE files.

- [ ] **Step 4: Verify disc integrity and test suites**
- Verify file size is exactly `712,300,848` bytes.
- Run all unit and integration tests (over 70 tests).
- Verify launcher: `./run_game.sh --dry-run`.
- Extract a frame from Movie 1 at 28.0s and verify the Russian subtitle *«Цепляешься к таким мелочам. / Тебе ещё расти и расти.»* is clearly rendered on the frame.
- Write report to `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/russian-fmv-final-report.md`.
- Commit changes.
