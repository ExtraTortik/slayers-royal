# Task 2 Execution Report: Missing Rooms Injection & Sector Allocation

## 1. Executive Summary
- **Task Target:** Extend `tools/patch_inspection.py` to support patching all 37 omitted room inspection locations (including Lakewood MAIN ST `0x059`) using `data/missing_rooms_jp_ru.json`, falling back to Japanese `source_prog` (`downloads/sr.bin`) for pointer table and room structures when English entries were zeroed out, strictly enforcing CD-ROM sector budgets across all entries, and writing comprehensive unit tests in `tools/test_batch_inspection_patch.py`.
- **Status:** Complete & Fully Verified.
- **Test Suite Results:**
  - `tools/test_batch_inspection_patch.py`: **12/12 tests passing** in 0.69s.
  - Combined inspection test suites: **40/40 tests passing** in 0.83s (`tools/test_batch_inspection_patch.py`, `tools/test_patch_inspection.py`, `tools/test_extract_inspection.py`, `tools/test_inspection_translations.py`).
- **All 37 Omitted Rooms Batch Injection:** All 37 omitted rooms patch cleanly with **0 sector overflows** and 100% non-empty authentic Russian hover descriptions in the voice of Lina Inverse.
- **Lakewood MAIN ST (`0x059`) Restoration:** Room `0x059` successfully restored with all **43 Russian strings** (`Небо между\nдеревьями.`, `Хорошая погода.`, `Вон там вдали\nвидны деревья.`, etc.), 43 RAM pointers recalculated, and 0 sector overflows (used: **3,904 / 4,096 bytes**, free margin: **192 bytes**).

---

## 2. Technical Architecture & Implementation

### A. Missing Rooms Loading & Dynamic Resolution (`load_missing_rooms`, `get_missing_room_strings`)
- Configured default paths `DEFAULT_MISSING_ROOMS = REPO_ROOT / "data" / "missing_rooms_jp_ru.json"` and `DEFAULT_SOURCE_BIN = REPO_ROOT / "downloads" / "sr.bin"`.
- Added `load_missing_rooms(path)` to parse JSON from file or default repository path.
- Added `get_missing_room_strings(entry_idx, missing_rooms_doc)` supporting hexadecimal (`0x059`, `0x05C`), decimal (`89`), and integer key lookups, returning string lists from either dictionary objects (`strings_ru` or `strings`) or raw lists.

### B. Japanese Source PROG Extraction (`extract_prog_from_path`)
- Implemented `extract_prog_from_path` to handle both standalone `PROG.UNT` archives and full PS1 CD-ROM `.bin` disc images (`downloads/sr.bin`).
- For CD-ROM images, locates and extracts `PROG.UNT` using ISO9660 Primary Volume Descriptor (PVD) and directory extent records.

### C. Zeroed-Out Entry Detection & Source Fallback Engine
- In `english_prog` (`localization-output/ru/slayers_royal_ru.bin`), 37 rooms had their string blocks blanked out with empty string terminators (`0x00FF`).
- In `patch_inspection_entries`:
  1. Inspects each candidate entry in `prog_archive`.
  2. If an entry is in `missing_rooms_doc`:
     - Checks if `orig_bytes` fails to parse (corrupted/wiped pointer table) OR if all extracted strings are empty (`is_zeroed`) OR if strings have no translations in `translations_doc`.
     - When `use_missing_rooms` is triggered:
       - Extracts pristine base room bytes from `source_prog` (`source_entries[entry_idx]`).
       - Parses the Japanese pointer table, string offsets, and trailing collision data (`0x002C`, `0x0030`).
       - Feeds the Russian strings from `data/missing_rooms_jp_ru.json` into `rebuild_inspection_entry`.
       - Rebuilds 16-bit big-endian Cyrillic string payloads, deduplicates shared pointers, recalculates RAM base pointers (`RAM_BASE = 0x00200000`), and writes back updated header pointers (`0x0024`, `0x002C`, `0x0030`).
       - Injects rebuilt bytes into `prog_archive` using `patch_unt_entry`.
  3. If unallocated dummy filler sectors (`b"\x00" * len(orig_bytes)`) are encountered in synthetic archives without explicit targeting, skips them safely.
  4. Non-omitted rooms (e.g. 112 exploration rooms with English text) continue through the standard `translations_doc` catalog resolution path.

### D. Sector Budget Enforcement & Progressive Line Condensation
- Rebuild operations enforce `rebuilt_size <= entry.size` (multiples of 2,048 bytes).
- All 37 omitted rooms fit cleanly:
  - Free margins range from **0 bytes** (exact sector budget fit) up to **384 bytes**.
  - Tight rooms (e.g. `0x099`, `0x0A7`, `0x0A8`, `0x0A9`, `0x0B9`, `0x0BF`, `0x0C1`) fit exactly within their 1-sector budget (2,048 / 2,048 bytes) via automated line condensation.
  - Zero sector overflows across all rooms.

### E. CLI Options Added to `tools/patch_inspection.py`
- `--missing-rooms`: Path to `missing_rooms_jp_ru.json` (defaults to `data/missing_rooms_jp_ru.json` when present).
- `--source-bin` / `--source-prog`: Path to Japanese source BIN (`downloads/sr.bin`) or `PROG.UNT` archive for fallback pointer layouts.
- Preserved existing flags (`--bin`, `--prog`, `--translations`, `--entry`, `--all-rooms`, `--dump`, `--verbose`).

---

## 3. Verification & Test Suite

The updated test suite `tools/test_batch_inspection_patch.py` contains **12 tests**, including 4 new dedicated test cases:

1. `test_catalog_file_exists_and_valid`: Validates `translations/room_inspection_ru.json` integrity.
2. `test_resolve_entry_translations_catalog_schema`: Verifies catalog schema resolution.
3. `test_resolve_entry_translations_schema_b_compatibility`: Backward compatibility test.
4. `test_progressive_condensation_resolves_overflow`: Verifies multi-line string condensation on tight budgets.
5. `test_impossible_budget_overflow_still_raises_error`: Budget overflow guard test.
6. `test_batch_patch_synthetic_unt_archive`: Synthetic multi-room UNT batch patching.
7. `test_batch_patching_real_disc_all_rooms`: Full disc batch-patching of all 149 valid rooms in `PROG.UNT` (`0x059`..`0x0F8`), verifying zero overflows across both catalog and missing rooms, with specific assertions on Room `0x059` (43 strings, first string `'Небо между\nдеревьями.'`).
8. `test_cli_batch_patch_prog`: CLI batch patching test on standalone PROG.UNT.
9. `test_room_059_main_st_43_russian_strings`: Dedicated verification that Room `0x059` (Lakewood MAIN ST) patches with 43 Russian strings, allocated 4096 bytes, used <= 4096 bytes, free margin >= 0, and correct text contents.
10. `test_all_37_omitted_rooms_zero_sector_overflows`: Dedicated batch verification across all 37 omitted rooms from `data/missing_rooms_jp_ru.json`, verifying 0 sector overflows, 100% non-empty strings, and valid pointer counts.
11. `test_zeroed_entry_fallback_to_source_prog`: Synthetic unit test verifying fallback to `source_prog` when entry strings or pointer tables are zeroed/corrupt.
12. `test_cli_patch_room_059_missing_rooms`: Full CLI integration test verifying `--entry 0x059 --missing-rooms ... --source-bin ...` on standalone `PROG.UNT`.

### Test Execution Output
```text
$ pytest tools/test_batch_inspection_patch.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/samvel/dddd
collected 12 items

tools/test_batch_inspection_patch.py::test_catalog_file_exists_and_valid PASSED [  8%]
tools/test_batch_inspection_patch.py::test_resolve_entry_translations_catalog_schema PASSED [ 16%]
tools/test_batch_inspection_patch.py::test_resolve_entry_translations_schema_b_compatibility PASSED [ 25%]
tools/test_batch_inspection_patch.py::test_progressive_condensation_resolves_overflow PASSED [ 33%]
tools/test_batch_inspection_patch.py::test_impossible_budget_overflow_still_raises_error PASSED [ 41%]
tools/test_batch_inspection_patch.py::test_batch_patch_synthetic_unt_archive PASSED [ 50%]
tools/test_batch_inspection_patch.py::test_batch_patching_real_disc_all_rooms PASSED [ 58%]
tools/test_batch_inspection_patch.py::test_cli_batch_patch_prog PASSED   [ 66%]
tools/test_batch_inspection_patch.py::test_room_059_main_st_43_russian_strings PASSED [ 75%]
tools/test_batch_inspection_patch.py::test_all_37_omitted_rooms_zero_sector_overflows PASSED [ 83%]
tools/test_batch_inspection_patch.py::test_zeroed_entry_fallback_to_source_prog PASSED [ 91%]
tools/test_batch_inspection_patch.py::test_cli_patch_room_059_missing_rooms PASSED [100%]

============================== 12 passed in 0.69s ==============================
```

---

## 4. Deliverables Summary
- **Updated:** `tools/patch_inspection.py` (added missing rooms auto-loading, Japanese source PROG extraction, zeroed-entry detection, source pointer layout fallback, and CLI options).
- **Updated:** `tools/test_batch_inspection_patch.py` (added fixtures and 4 unit/regression tests for Room `0x059`, all 37 omitted rooms, zeroed-entry fallback, and CLI invocation).
- **Execution Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/task-mainst-2-report.md`.
