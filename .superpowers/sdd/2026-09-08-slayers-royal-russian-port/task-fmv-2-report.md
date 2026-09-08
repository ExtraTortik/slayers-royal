# Task 2 Execution Report: Subtitle Burning & PS1 STR Encoding Engine

- **Date:** 2026-09-08
- **Status:** Completed
- **Operator:** FMVEncodingImplementer
- **Target Files:**
  - `tools/fmv_pipeline.py`
  - `tools/test_fmv_pipeline.py`
- **Output Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/task-fmv-2-report.md`

---

## 1. Executive Summary

Task 2 of the Russian FMV Subtitles Integration implemented the video processing and encoding pipeline in `tools/fmv_pipeline.py`:
1. Hardsubbing of Russian `.srt` subtitles onto `sXX.webm` cutscenes via FFmpeg into raw uncompressed 320x240 @ 15fps AVI with 18,900 Hz mono PCM audio.
2. Conversion of raw AVI streams into PlayStation 1 MDEC STR CD-XA streams using `tools/bin/psxavenc` with interleaved 2,352-byte Mode 2 Form 1 sectors.
3. Accurate sector padding and truncation via `pad_str_to_sectors`, guaranteeing that each cutscene matches its exact sector allocation in `MOVIE_MAP`.
4. High-level orchestrator `encode_movie()`, handling untouched source extraction for `s00` (opening animation) and burning, encoding, and padding for `s01`..`s11`.
5. Addition of 20 unit tests to `tools/test_fmv_pipeline.py` (totaling 42 tests), verifying FFmpeg video/audio specs, MDEC headers (`0x80010160`), CD-XA audio submode (`0x64`), padding sector structures, and full pipeline integration.

All 42 unit tests passed in under 1 second.

---

## 2. Technical Implementation Details

### Subtitle Burning (`burn_subtitles_to_avi`)
- Input: `sXX.webm` (960x720 source video) and `sXX_ru.srt` (Russian subtitle).
- Video Filter:
  ```text
  scale=320:240,subtitles='{escaped_srt}':force_style='FontName=Liberation Sans,FontSize=15,Outline=1.8,OutlineColor=&H00000000,PrimaryColour=&H00FFFFFF,MarginV=12'
  ```
  - Subtitle path colons and backslashes are escaped for FFmpeg filtergraph compatibility.
  - Subtitles are rendered after scaling to 320x240 to ensure proportional, crisp, and readable text on PS1 hardware.
- Format: Uncompressed AVI (`-c:v rawvideo -pix_fmt yuv420p -r 15`).
- Audio: 18,900 Hz, 1 channel (mono), 16-bit signed PCM (`-ar 18900 -ac 1 -c:a pcm_s16le`).
- Supports optional `duration` parameter for rapid smoke testing and unit tests.

### PlayStation 1 STR Encoding (`encode_avi_to_str`)
- Invokes `tools/bin/psxavenc` with:
  ```bash
  tools/bin/psxavenc -t strcd -f 18900 -c 1 -F 1 -C 1 -r 15 -x 2 -T 0x8001 {temp_avi} {temp_str}
  ```
- Output Stream Architecture:
  - Container format: CD-XA Mode 2 Form 1 interleaved audio/video stream (2,352 bytes per sector).
  - Video stream: MDEC BS v2 compressed frames, 320x240 @ 15 fps, tagged with type ID `0x8001` (magic `60 01 01 80`).
  - Audio stream: XA-ADPCM 4-bit mono audio at 18,900 Hz, File 1, Channel 1, submode `0x64`, coding `0x04`.

### Sector Padding & Bounds Enforcement (`pad_str_to_sectors` & `make_padding_sector`)
- Generates valid CD-XA Mode 2 Form 1 zero-padding sectors:
  - Bytes 0..11: CD-ROM Sync pattern (`\x00\xff...\xff\x00`).
  - Bytes 12..15: Mode 2 sector header with accurate BCD minute/second/frame timing starting at LBA 150 (00:02:00 CD-ROM pregap).
  - Bytes 16..23: CD-XA subheader set to 8 zero bytes (`\x00` * 8).
  - Bytes 24..2351: Zero-filled payload (2,328 zero bytes).
- Behavior:
  - If stream size < `target_sectors * 2352`: pads unaligned sector boundaries with zeros, then appends valid padding sectors up to `target_sectors * 2352`.
  - If stream size > `target_sectors * 2352`: cleanly truncates trailing silence/padding bytes to fit.
  - If stream size == `target_sectors * 2352`: returns byte stream untouched.

### High-Level Movie Pipeline (`encode_movie`)
- Movie 0 (`s00`): Unsubbed opening animation. Extracts exactly 13,501 raw sectors (31,754,352 bytes) directly from `downloads/sr.bin` starting at LBA 127.
- Movies 1..11 (`s01`..`s11`): Russian subtitled cutscenes.
  1. Validates presence of `sXX.webm` and `sXX_ru.srt`.
  2. Burns subtitles to intermediate AVI in an isolated temporary directory.
  3. Encodes intermediate AVI to `.str` with `psxavenc`.
  4. Pads `.str` to exact sector count from `MOVIE_MAP[idx]["sectors"]`.
  5. Writes output STR to specified destination.

---

## 3. CLI Interface

Added `--encode`, `--out`, `--duration`, and `--bin` options to `tools/fmv_pipeline.py`:
```text
usage: fmv_pipeline.py [-h] [--verify] [--list] [--info IDX] [--encode IDX]
                       [--out OUT_STR] [--duration SECS] [--bin BIN]

options:
  -h, --help       show this help message and exit
  --verify         Verify MOVIE_MAP and psxavenc
  --list           List all 12 movies and sector bounds
  --info IDX       Show details for movie index (0..11)
  --encode IDX     Encode movie index (0..11) to PS1 STR
  --out OUT_STR    Output STR file path for --encode
  --duration SECS  Limit encoding duration in seconds
  --bin BIN        Source disc image BIN path (for s00)
```

Example CLI runs verified:
- Extracting s00:
  `python3 tools/fmv_pipeline.py --encode 0 --out /tmp/s00.str` -> 31,754,352 bytes (13,501 sectors).
- Encoding s01 test:
  `python3 tools/fmv_pipeline.py --encode 1 --duration 1.0 --out /tmp/s01.str` -> 30,105,600 bytes (12,800 sectors).

---

## 4. Test Suite Execution & Verification

Run command:
```bash
pytest -v tools/test_fmv_pipeline.py
```

### Results
```text
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_binary_exists_and_executable PASSED [  2%]
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_version_output PASSED [  4%]
tools/test_fmv_pipeline.py::TestPsxavencToolchain::test_help_strcd_format_available PASSED [  7%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_count PASSED [  9%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_subbed_flags PASSED [ 11%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_sector_continuity_and_sum PASSED [ 14%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_relative_sector_offsets PASSED [ 16%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_info_helper PASSED [ 19%]
tools/test_fmv_pipeline.py::TestMovieStreamMapping::test_movie_info_out_of_bounds PASSED [ 21%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[0] PASSED [ 23%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[1] PASSED [ 26%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[2] PASSED [ 28%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[3] PASSED [ 30%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[4] PASSED [ 33%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[5] PASSED [ 35%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[6] PASSED [ 38%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[7] PASSED [ 40%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[8] PASSED [ 42%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[9] PASSED [ 45%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[10] PASSED [ 47%]
tools/test_fmv_pipeline.py::TestSourceAssetsAvailability::test_video_assets_exist[11] PASSED [ 50%]
tools/test_fmv_pipeline.py::TestDiscImageAlignment::test_all_movie_stream_headers_in_disc PASSED [ 52%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_make_padding_sector_format PASSED [ 54%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_exact_length[0] PASSED [ 57%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_exact_length[1] PASSED [ 59%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_exact_length[5] PASSED [ 61%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_exact_length[128] PASSED [ 64%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_exact_length[12800] PASSED [ 66%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_padding_preserves_exact_size PASSED [ 69%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_truncation_when_exceeding_target PASSED [ 71%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_unaligned_input_padding PASSED [ 73%]
tools/test_fmv_pipeline.py::TestPadStrToSectors::test_negative_target_sectors_raises PASSED [ 76%]
tools/test_fmv_pipeline.py::TestSubtitleBurning::test_burn_subtitles_to_avi_output_spec PASSED [ 78%]
tools/test_fmv_pipeline.py::TestSubtitleBurning::test_burn_without_subtitles PASSED [ 80%]
tools/test_fmv_pipeline.py::TestSubtitleBurning::test_burn_missing_input_video_raises PASSED [ 83%]
tools/test_fmv_pipeline.py::TestSubtitleBurning::test_burn_missing_srt_raises PASSED [ 85%]
tools/test_fmv_pipeline.py::TestEncodeAviToStrAndStreamValidation::test_encode_and_validate_mdec_and_xa_sectors PASSED [ 88%]
tools/test_fmv_pipeline.py::TestEncodeAviToStrAndStreamValidation::test_encode_missing_avi_raises PASSED [ 90%]
tools/test_fmv_pipeline.py::TestEncodeMoviePipeline::test_encode_movie_0_extract_from_disc PASSED [ 92%]
tools/test_fmv_pipeline.py::TestEncodeMoviePipeline::test_encode_movie_with_subtitles_and_padding PASSED [ 95%]
tools/test_fmv_pipeline.py::TestEncodeMoviePipeline::test_encode_movie_invalid_index_raises PASSED [ 97%]
tools/test_fmv_pipeline.py::TestEncodeMoviePipeline::test_encode_movie_missing_video_raises PASSED [100%]

============================== 42 passed in 0.97s ==============================
```

---

## 5. Next Steps

Task 2 is complete, tested, and verified.
Ready to proceed to **Task 3: Batch Movie Encoder & MOVIE.STR Rebuilder**:
- Batch encoding of all 12 movies (`s00`..`s11`) into `build/movies/sXX.str`.
- Concatenation of the 12 movies into the rebuilt `MOVIE.STR` file (184,290 sectors / 433,450,080 bytes).
- Patching `MOVIE.STR` back into the final PS1 ISO/BIN image.
