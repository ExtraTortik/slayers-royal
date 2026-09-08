# Final Report: Russian FMV Subtitles Integration & Disc Master Rebuild

- **Date:** 2026-09-08
- **Status:** Completed
- **Operator:** FMVMasterRebuilder
- **Target Files:**
  - `tools/fmv_pipeline.py`
  - `tools/test_fmv_pipeline.py`
  - `localization-output/ru/slayers_royal_ru.bin`
  - `localization-output/ru/slayers_royal_ru.cue`
  - `patch_repo/localization-output/ru/slayers_royal_ru.bin`
  - `patch_repo/localization-output/ru/slayers_royal_ru.cue`
  - `data/preview_fmv_s01_ru.png`
- **Output Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/russian-fmv-final-report.md`

---

## 1. Executive Summary

All 11 story FMV cutscenes (`s01`..`s11`) for the PlayStation 1 release of *Slayers Royal* have been hardsubbed with authentic Russian subtitles from *Slayers Royal: Ren'Py Edition*, encoded into native PlayStation 1 MDEC STR CD-XA streams using `psxavenc` and `ffmpeg`, padded to their exact sector allocations, and concatenated with the untouched opening cutscene (`s00`) into a 184,290-sector `MOVIE.STR` file (433,450,080 bytes).

The complete `MOVIE.STR` stream was injected into the target Russian disc image `localization-output/ru/slayers_royal_ru.bin` starting at LBA 127 and mirrored to `patch_repo/localization-output/ru/`.

The disc image size remains exactly **712,300,848 bytes**. A visual preview extracted directly from Movie 1 at 28.0s in the updated disc confirms that Russian subtitles (`«Цепляешься к таким мелочам.»`) are clearly rendered and visible. All 122 tests across both test suites pass 100%, and the launcher dry-run verification succeeded.

---

## 2. Pipeline Implementation Details

### Enhancements to `tools/fmv_pipeline.py`
1. **`batch_encode_all_movies(videos_dir, out_dir, source_bin_path, duration=None, force=False)`**:
   - Iterates through all 12 movies (`s00`..`s11`).
   - For `s00`: extracts 13,501 raw sectors directly from `downloads/sr.bin`.
   - For `s01`..`s11`: burns Russian `.srt` subtitles into 320x240 @ 15 fps uncompressed AVI with 18,900 Hz mono audio, encodes to PS1 STR with `psxavenc`, and pads to exact sector count via `pad_str_to_sectors`.
   - Supports intelligent caching: reuses existing matching `.str` files unless `--force` is specified.
   - Automatically concatenates the 12 movies into `MOVIE.STR`.

2. **`concat_movies_to_str(movie_paths, out_path)`**:
   - Streams movie STR files sequentially into unified `MOVIE.STR`.
   - Verifies total output is exactly `184,290` sectors (`433,450,080` bytes).

3. **`inject_movie_str_into_disc(disc_path, movies_dir)`**:
   - Accepts either a directory containing `s00.str`..`s11.str` / `MOVIE.STR`, or a direct path to `MOVIE.STR`.
   - Enforces target disc size of `712,300,848` bytes before injection.
   - Writes `433,450,080` bytes starting at LBA 127 (byte offset `298,704`).
   - Performs post-injection validation: verifies CD-ROM sync, Mode 2 indicators, valid CD-XA submodes (`0x48` video / `0x64` audio), and MDEC magic `60 01 01 80` in the video stream for all 12 cutscenes.
   - Confirms disc size remains exactly `712,300,848` bytes.

4. **CLI Options**:
   - `--all-movies`: batch encode all 12 cutscenes.
   - `--inject-disc`, `--disc`: target BIN disc image to patch.
   - `--videos-dir`: directory containing source `sXX.webm` and `sXX_ru.srt`.
   - `--movies-dir`: directory containing encoded `sXX.str` files.
   - `--force`: bypass cache and re-encode all movies.

---

## 3. Rebuilt Movie Stream Layout (`MOVIE_MAP`)

| Idx | Movie | Relative Sectors | Absolute LBA | Sectors | Size (Bytes) | Subbed | Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | `s00` | 0 .. 13500 | 127 .. 13627 | 13,501 | 31,754,352 | No | Reused Japanese opening |
| 1 | `s01` | 13501 .. 26300 | 13628 .. 26427 | 12,800 | 30,105,600 | **Yes** | Russian hardsub injected |
| 2 | `s02` | 26301 .. 49699 | 26428 .. 49826 | 23,399 | 55,034,448 | **Yes** | Russian hardsub injected |
| 3 | `s03` | 49700 .. 60007 | 49827 .. 60134 | 10,308 | 24,244,416 | **Yes** | Russian hardsub injected |
| 4 | `s04` | 60008 .. 72391 | 60135 .. 72518 | 12,384 | 29,127,168 | **Yes** | Russian hardsub injected |
| 5 | `s05` | 72392 .. 91961 | 72519 .. 92088 | 19,570 | 46,028,640 | **Yes** | Russian hardsub injected |
| 6 | `s06` | 91962 .. 101753 | 92089 .. 101880 | 9,792 | 23,030,784 | **Yes** | Russian hardsub injected |
| 7 | `s07` | 101754 .. 111673 | 101881 .. 111800 | 9,920 | 23,331,840 | **Yes** | Russian hardsub injected |
| 8 | `s08` | 111674 .. 123550 | 111801 .. 123677 | 11,877 | 27,934,704 | **Yes** | Russian hardsub injected |
| 9 | `s09` | 123551 .. 150352 | 123678 .. 150479 | 26,802 | 63,038,304 | **Yes** | Russian hardsub injected |
| 10 | `s10` | 150353 .. 153808 | 150480 .. 153935 | 3,456 | 8,128,512 | **Yes** | Russian hardsub injected |
| 11 | `s11` | 153809 .. 184289 | 153936 .. 184416 | 30,481 | 71,691,312 | **Yes** | Russian hardsub injected |
| **Total** | | **0 .. 184289** | **127 .. 184416** | **184,290** | **433,450,080** | | **Contiguous, 0 gaps** |

---

## 4. Disc Integrity & Checksums

- **File Size:** exactly `712,300,848` bytes (`302,849` sectors * `2,352` bytes/sector).
- **SHA-256 Checksums:**
  - `localization-output/ru/slayers_royal_ru.bin`:
    `18f3da6c096d6fbbdfce7819af248cbd6200c9873d03a3655ca1bd94a996dbe3`
  - `patch_repo/localization-output/ru/slayers_royal_ru.bin`:
    `18f3da6c096d6fbbdfce7819af248cbd6200c9873d03a3655ca1bd94a996dbe3`
- **Mirroring Status:** Identical byte copy between `localization-output/ru/` and `patch_repo/localization-output/ru/`.

---

## 5. Visual Verification

A sample frame was extracted directly from Movie 1 (`s01`) inside `localization-output/ru/slayers_royal_ru.bin` at timestamp 28.0s:
- **Output File:** `data/preview_fmv_s01_ru.png`
- **Resolution:** 320x240
- **Verified Subtitle Content:**
  > **«Цепляешься к таким мелочам.»**
- **Visual Inspection:** Text is rendered in white Cyrillic sans-serif glyphs centered at the bottom of the screen with a crisp black outline, providing high contrast against animated backgrounds on PlayStation 1 hardware.

---

## 6. Test Suite Results (122/122 Passed)

### Suite 1: Tools Tests (`python3 -m pytest tools/`)
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd
collected 112 items

tools/test_batch_inspection_patch.py ............                        [ 10%]
tools/test_extract_inspection.py .....                                   [ 15%]
tools/test_fmv_pipeline.py ............................................. [ 55%]
....                                                                     [ 58%]
tools/test_inspection_translations.py ..........                         [ 67%]
tools/test_patch_inspection.py .............                             [ 79%]
tools/test_patch_lore_cards.py .............                             [ 91%]
tools/test_text_wrapper.py ..........                                    [100%]

============================= 112 passed in 7.21s ==============================
```

### Suite 2: Localization Tests (`patch_repo/localization/tests`)
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd/patch_repo
collected 10 items

localization/tests/test_glyphs.py ..                                     [ 20%]
localization/tests/test_integration.py ..                                [ 40%]
localization/tests/test_po.py ..                                         [ 60%]
localization/tests/test_script.py ....                                   [100%]

============================== 10 passed in 0.92s ==============================
```

**Total: 122 passed / 122 total (100%)**

---

## 7. Launcher Dry-Run Verification

```text
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

## 8. Conclusion

Task 3 is complete. The Russian PlayStation 1 CD-ROM image for *Slayers Royal* has been rebuilt with all 11 story FMV cutscenes hardsubbed with Russian subtitles. Disc integrity, byte size, checksums, visual subtitles, regression test suites, and the automated launcher have all been verified.
