# Execution Report: Complete FMV Pipeline Fix (-L Physical MSF, -X Interleave) & Disc Master Injection

- **Date:** 2026-09-08
- **Status:** Completed
- **Operator:** FMVFixImplementer
- **Target Files:**
  - `tools/fmv_pipeline.py`
  - `tools/test_fmv_pipeline.py`
  - `localization-output/ru/slayers_royal_ru.bin`
  - `patch_repo/localization-output/ru/slayers_royal_ru.bin`
  - `data/preview_fmv_s01_ru.png`
  - `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/progress.md`
- **Output Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/fmv-fix-report.md`

---

## 1. Executive Summary

The Slayers Royal PS1 Russian FMV pipeline has been updated to achieve 100% CD-ROM physical sector header compliance and native Slayers Royal audio interleaving:
1. **Physical MSF Sector Headers (`-L {abs_lba}`)**: Every movie stream (`s01`..`s11`) is now encoded with `-L {abs_lba}`, embedding physical BCD MSF headers (with standard CD-ROM +150 pregap frame offset). Movie 1 (`s01`) sector 0 now starts at exactly `03:03:53, Mode 2`, bit-for-bit matching the original Japanese disc timing.
2. **1/32 Audio Interleave (`-X`)**: Passing `-X` places audio sectors after video sectors rather than ahead of them, producing the exact 1/32 interleave used by Slayers Royal: sectors 0..30 video (`submode 0x48`), sector 31 audio (`submode 0x64`).
3. **Accurate Padding Sectors (`lba_to_msf` + EDC/ECC)**: `pad_str_to_sectors` now accepts `start_lba` and writes continuous physical BCD MSF headers across all padding sectors, recalculating Mode 2 Form 1 EDC/ECC checksums.
4. **Disc Master Injection**: All 12 movies were batch-encoded and injected into `localization-output/ru/slayers_royal_ru.bin` and mirrored to `patch_repo/localization-output/ru/slayers_royal_ru.bin`. The disc size remains strictly **712,300,848 bytes**.
5. **Verification & Tests**: All 54 pipeline tests and all 117 tools tests pass cleanly. Disc dry-run validation succeeded.

---

## 2. Technical Implementation Details

### Enhancements to `tools/fmv_pipeline.py`

1. **`lba_to_msf(lba: int) -> bytes`**:
   - Implements standard CD-ROM LBA-to-MSF conversion with the +150 pregap offset (`lba + 150`).
   - Computes `Minute = (total_frames // 75) // 60`, `Second = (total_frames // 75) % 60`, and `Frame = total_frames % 75`.
   - Returns 3 BCD-encoded bytes: `(BCD_M, BCD_S, BCD_F)`.

2. **`make_padding_sector(sector_lba: int = 0) -> bytes`**:
   - Generates a 2,352-byte CD-XA Mode 2 Form 1 padding sector with:
     - 12-byte sync pattern (`00 FF..FF 00`)
     - 4-byte header: `lba_to_msf(sector_lba) + b"\x02"`
     - 8-byte subheader (`0x00 * 8`)
     - 2,048-byte user data payload (`0x00 * 2048`)
     - Mode 2 Form 1 EDC (4 bytes) and Reed-Solomon P/Q ECC (276 bytes) calculated via `CdChecksums.repair_mode2_form1`.

3. **`pad_str_to_sectors(str_bytes, target_sectors, start_lba=0) -> bytes`**:
   - Pads any partial sector and repairs its EDC/ECC if Mode 2 Form 1.
   - Appends valid padding sectors with sequential physical MSF addresses starting from `start_lba + current_sec_count`.

4. **`encode_avi_to_str(avi_path, out_str_path, start_lba=None) -> Path`**:
   - Passes `-L {start_lba}` to `psxavenc` when `start_lba` is provided.
   - Passes `-X` to place audio sectors after corresponding video sectors, ensuring 1/32 audio interleave matching original Slayers Royal CD-XA streams.

5. **`encode_movie(movie_idx, videos_dir, out_str_path, source_bin_path=None, duration=None) -> int`**:
   - Passes `start_lba=info.start_lba` to `encode_avi_to_str`.
   - Passes `start_lba=info.start_lba` to `pad_str_to_sectors`.

6. **`inject_movie_str_into_disc(disc_path, movies_dir) -> int`**:
   - Added validation enforcing that sector 0 of each movie on the disc matches `lba_to_msf(info.start_lba)` in addition to sync, Mode 2, valid CD-XA submodes (`0x48` / `0x64`), and MDEC stream magic (`60 01 01 80`).

---

## 3. Test Suite Enhancements (`tools/test_fmv_pipeline.py`)

- **`TestLbaToMsf` (new test class)**:
  - `test_lba_0_msf`: validates LBA 0 maps to `00:02:00`.
  - `test_movie_0_lba_127_msf`: validates Movie 0 start maps to `00:03:52`.
  - `test_movie_1_lba_13628_msf`: validates Movie 1 start maps to `03:03:53`.
  - `test_all_movie_msf_against_disc`: verifies that all 12 movies' start LBAs match the real Japanese disc (`downloads/sr.bin`) bit-for-bit.
- **`TestPadStrToSectors`**:
  - Validates `make_padding_sector` for both LBA 0 and Movie 1 (LBA 13628 -> `03:03:53, Mode 2`).
  - Added `test_padding_with_start_lba_writes_accurate_msf` verifying sequential physical MSF timestamps.
- **`TestEncodeAviToStrAndStreamValidation`**:
  - Encodes sample with `start_lba=150480`.
  - Validates physical MSF timing for all sectors (`150480 + i`).
  - Validates 1/32 audio interleave: sectors 0..30 video (`0x48`), sector 31 audio (`0x64`).
- **`TestEncodeMoviePipeline`**:
  - Validates that `encode_movie` starts at `lba_to_msf(info.start_lba)` and ends at `lba_to_msf(info.start_lba + info.sectors - 1)`.
- **`TestInjectMovieStrIntoDisc`**:
  - Updates mock disc sectors with `lba_to_msf(info.start_lba)` to validate MSF enforcement.

---

## 4. Rebuilt Movie Stream Layout & Verified MSF Headers

| Idx | Movie | Relative Sectors | Absolute LBA | Start MSF (BCD) | Sectors | Size (Bytes) | Subbed | Interleave |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | `s00` | 0 .. 13500 | 127 .. 13627 | `00:03:52` | 13,501 | 31,754,352 | No | Pristine original |
| 1 | `s01` | 13501 .. 26300 | 13628 .. 26427 | `03:03:53` | 12,800 | 30,105,600 | **Yes** | 1/32 (-X) |
| 2 | `s02` | 26301 .. 49699 | 26428 .. 49826 | `05:54:28` | 23,399 | 55,034,448 | **Yes** | 1/32 (-X) |
| 3 | `s03` | 49700 .. 60007 | 49827 .. 60134 | `11:06:27` | 10,308 | 24,244,416 | **Yes** | 1/32 (-X) |
| 4 | `s04` | 60008 .. 72391 | 60135 .. 72518 | `13:23:60` | 12,384 | 29,127,168 | **Yes** | 1/32 (-X) |
| 5 | `s05` | 72392 .. 91961 | 72519 .. 92088 | `16:08:69` | 19,570 | 46,028,640 | **Yes** | 1/32 (-X) |
| 6 | `s06` | 91962 .. 101753 | 92089 .. 101880 | `20:29:64` | 9,792 | 23,030,784 | **Yes** | 1/32 (-X) |
| 7 | `s07` | 101754 .. 111673 | 101881 .. 111800 | `22:40:31` | 9,920 | 23,331,840 | **Yes** | 1/32 (-X) |
| 8 | `s08` | 111674 .. 123550 | 111801 .. 123677 | `24:52:51` | 11,877 | 27,934,704 | **Yes** | 1/32 (-X) |
| 9 | `s09` | 123551 .. 150352 | 123678 .. 150479 | `27:31:03` | 26,802 | 63,038,304 | **Yes** | 1/32 (-X) |
| 10 | `s10` | 150353 .. 153808 | 150480 .. 153935 | `33:28:30` | 3,456 | 8,128,512 | **Yes** | 1/32 (-X) |
| 11 | `s11` | 153809 .. 184289 | 153936 .. 184416 | `34:14:36` | 30,481 | 71,691,312 | **Yes** | 1/32 (-X) |
| **Total** | | **0 .. 184289** | **127 .. 184416** | | **184,290** | **433,450,080** | | **Contiguous, 0 gaps** |

---

## 5. Disc Integrity & Checksums

- **File Size:** exactly `712,300,848` bytes (`302,849` sectors * `2,352` bytes/sector).
- **SHA-256 Checksums:**
  - `localization-output/ru/slayers_royal_ru.bin`:
    `ed86a33bd44fc1896d6e359b05a5713e1e937fee9ff195d4bb21313b1df8003b`
  - `patch_repo/localization-output/ru/slayers_royal_ru.bin`:
    `ed86a33bd44fc1896d6e359b05a5713e1e937fee9ff195d4bb21313b1df8003b`
- **Mirroring Status:** 100% identical byte copy between `localization-output/ru/` and `patch_repo/localization-output/ru/`.

---

## 6. Verification Results

### 1. Unit & Regression Tests (`tools/test_fmv_pipeline.py`)
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd
collected 54 items

tools/test_fmv_pipeline.py ............................................. [ 83%]
.........                                                                [100%]

============================= 54 passed in 19.21s ==============================
```

### 2. Full Tools Test Suite (`python3 -m pytest tools/`)
```text
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd
collected 117 items

tools/test_batch_inspection_patch.py ............                        [ 10%]
tools/test_extract_inspection.py .....                                   [ 14%]
tools/test_fmv_pipeline.py ............................................. [ 52%]
.........                                                                [ 60%]
tools/test_inspection_translations.py ..........                         [ 69%]
tools/test_patch_inspection.py .............                             [ 80%]
tools/test_patch_lore_cards.py .............                             [ 91%]
tools/test_text_wrapper.py ..........                                    [100%]

============================= 117 passed in 25.13s =============================
```

### 3. Launcher Dry-Run Verification (`./run_game.sh --dry-run`)
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

### 4. Visual Subtitle Verification
A frame was extracted directly from Movie 1 (`s01`) at 28.0s:
- **Output:** `data/preview_fmv_s01_ru.png`
- **Verified Text:** `«Цепляешься к таким мелочам.»`
- **Rendering:** White Cyrillic typography with solid black outline, centered near bottom of screen.

---

## 7. Conclusion

The FMV pipeline fix is complete. All 11 Russian story cutscenes now feature accurate physical BCD MSF sector headers, authentic 1/32 audio interleave (`-X`), and valid Mode 2 Form 1 EDC/ECC padding sectors. Disc image size and integrity are verified, and all test suites pass with zero errors.
