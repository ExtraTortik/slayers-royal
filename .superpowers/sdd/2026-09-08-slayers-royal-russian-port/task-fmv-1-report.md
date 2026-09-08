# Task 1 Execution Report: Video Toolchain Setup & Movie Stream Mapping

- **Date:** 2026-09-08
- **Status:** Completed
- **Operator:** FMVToolchainImplementer
- **Target Files:**
  - `tools/bin/psxavenc`
  - `tools/fmv_pipeline.py`
  - `tools/test_fmv_pipeline.py`
- **Output Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/task-fmv-1-report.md`

---

## 1. Executive Summary

In Task 1 of the Russian FMV Subtitles Integration, the native PlayStation 1 MDEC video and CD-XA encoder `psxavenc` was successfully built, patched, and installed into `tools/bin/psxavenc`.

Furthermore, the complete 12-movie stream sector map in `MOVIE.STR` (starting at LBA 127, spanning exactly 184,290 sectors / 433,450,080 raw bytes / 377,425,920 user bytes) was formalized and verified in `tools/fmv_pipeline.py`.

A comprehensive test suite of 22 unit tests was implemented in `tools/test_fmv_pipeline.py`, validating toolchain execution, sector bounds, stream continuity, asset availability (`s00.webm`..`s11.webm` and `s01_ru.srt`..`s11_ru.srt`), and physical alignment with the original PS1 disc image (`downloads/sr.bin`).

---

## 2. Toolchain Compilation & Installation (`psxavenc`)

1. **Source Acquisition:** Cloned `https://github.com/WonderfulToolchain/psxavenc.git` to `/tmp/psxavenc`.
2. **Modern Toolchain Compatibility Patch:**
   - In modern FFmpeg (libavutil 61+ / libavcodec 63+), memory allocation functions require `<libavutil/mem.h>`.
   - Patched `psxavenc/mdec.c` at line 1 to include `<libavutil/mem.h>`.
3. **Build & Linking:**
   - Built via `meson setup build && ninja -C build`.
   - Linked against system `libavformat` (63.1.101), `libavcodec` (63.1.101), `libavutil` (61.1.101), `libswresample` (7.1.101), `libswscale` (10.1.101), and `libm`.
4. **Installation:**
   - Copied binary to `tools/bin/psxavenc` and marked executable (`chmod +x`).
   - File size: 207 KB.
   - Version: `psxavenc v0.3.1-1-g82f3871`.
5. **CLI Verification:**
   - Verified `./tools/bin/psxavenc -t strcd -h` successfully reports Mode 2 Form 1 CD-XA 2,352-byte sector support and MDEC BS v2 encoding options.

---

## 3. Movie Stream Sector Mapping (`MOVIE_MAP`)

`MOVIE.STR` resides at LBA 127 in the original disc image. The 12 FMV movies are contiguous streams with no padding gaps:

| Movie Idx | Name | Start LBA | End LBA | Relative Sectors | Sector Count | Raw Bytes (2,352 B/sec) | Subbed | Role / Scene |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| 0 | `s00` | 127 | 13,628 | 0 .. 13,500 | 13,501 | 31,754,352 | No | Opening Animation (Music only) |
| 1 | `s01` | 13,628 | 26,428 | 13,501 .. 26,300 | 12,800 | 30,105,600 | Yes | Story Scene 1 |
| 2 | `s02` | 26,428 | 49,827 | 26,301 .. 49,699 | 23,399 | 55,034,448 | Yes | Story Scene 2 |
| 3 | `s03` | 49,827 | 60,135 | 49,700 .. 60,007 | 10,308 | 24,244,416 | Yes | Story Scene 3 |
| 4 | `s04` | 60,135 | 72,519 | 60,008 .. 72,391 | 12,384 | 29,127,168 | Yes | Story Scene 4 |
| 5 | `s05` | 72,519 | 92,089 | 72,392 .. 91,961 | 19,570 | 46,028,640 | Yes | Story Scene 5 |
| 6 | `s06` | 92,089 | 101,881 | 91,962 .. 101,753 | 9,792 | 23,030,784 | Yes | Story Scene 6 |
| 7 | `s07` | 101,881 | 111,801 | 101,754 .. 111,673 | 9,920 | 23,331,840 | Yes | Story Scene 7 |
| 8 | `s08` | 111,801 | 123,678 | 111,674 .. 123,550 | 11,877 | 27,934,704 | Yes | Story Scene 8 |
| 9 | `s09` | 123,678 | 150,480 | 123,551 .. 150,352 | 26,802 | 63,038,304 | Yes | Story Scene 9 |
| 10 | `s10` | 150,480 | 153,936 | 150,353 .. 153,808 | 3,456 | 8,128,512 | Yes | Story Scene 10 |
| 11 | `s11` | 153,936 | 184,417 | 153,809 .. 184,289 | 30,481 | 71,691,312 | Yes | Ending Movie / Credits |
| **Total** | | **127** | **184,417** | **0 .. 184,289** | **184,290** | **433,450,080** | | |

### Physical Stream Verification on `downloads/sr.bin`:
- Every movie sector 0 begins with CD-XA submode `0x48` and STR payload magic `60 01 01 80` (`0x80010160`), chunk index `00 00`, and frame index `01 00`.
- The final sector of Movie 11 (LBA 184,416) ends with submode `0xC8` (audio/video with EOF bit set).
- LBA 184,417 immediately transitions to the next ISO data file (submode `0x64`).

---

## 4. Test Execution & Verification

Run command:
```bash
python3 -m pytest -v tools/test_fmv_pipeline.py
```

### Results
```text
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_binary_exists_and_executable PASSED [  4%]
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_version_output PASSED [  9%]
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_help_strcd_format_available PASSED [ 13%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_count PASSED [ 18%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_subbed_flags PASSED [ 22%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_sector_continuity_and_sum PASSED [ 27%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_relative_sector_offsets PASSED [ 31%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_info_helper PASSED [ 36%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_info_out_of_bounds PASSED [ 40%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[0] PASSED [ 45%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[1] PASSED [ 50%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[2] PASSED [ 54%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[3] PASSED [ 59%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[4] PASSED [ 63%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[5] PASSED [ 68%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[6] PASSED [ 72%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[7] PASSED [ 77%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[8] PASSED [ 81%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[9] PASSED [ 86%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[10] PASSED [ 90%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[11] PASSED [ 95%]
tools/test_fmv_pipeline.py::TestDiscImageAlignment::test_all_movie_stream_headers_in_disc PASSED [100%]

============================== 22 passed in 0.11s ==============================
```

---

## 5. Next Steps

Task 1 is complete and verified. Ready to proceed to **Task 2: Subtitle Burning & PS1 STR Encoding Engine**:
- Implement `encode_movie()` in `tools/fmv_pipeline.py`.
- Burn `sXX_ru.srt` onto `sXX.webm` with FFmpeg.
- Multiplex video and audio via `psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001`.
- Verify encoding and sector budget for `s01`.
