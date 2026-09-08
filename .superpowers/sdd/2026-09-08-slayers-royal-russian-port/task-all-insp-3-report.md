# Task 3 Execution Report: Automated Batch Injection Pipeline & Sector Budget Enforcer

## 1. Executive Summary
- **Task Target:** Extend `tools/patch_inspection.py` to batch-patch all room inspection entries in `PROG.UNT` using `translations/room_inspection_ru.json`, strictly enforce CD-ROM sector budgets across all rooms via automated progressive line condensation, and build a unit test suite in `tools/test_batch_inspection_patch.py`.
- **Status:** Complete & Fully Verified.
- **Test Suite Results:** 29/29 tests passing (`tools/test_batch_inspection_patch.py`, `tools/test_patch_inspection.py`, `tools/test_inspection_translations.py`).
- **All Rooms Batch Injection:** 149 / 149 valid room inspection entries in `PROG.UNT` (`0x059`..`0x0F8`) successfully patched into `localization-output/ru/slayers_royal_ru.bin` with Mode 2 Form 1 EDC/ECC checksum recalculation.
- **Sector Budget Violations:** **0 overflows** across all 149 rooms. Free margins range from 4 bytes to 2,752 bytes.

---

## 2. Technical Implementation Details

### A. Translation Schema Support (`resolve_entry_translations`)
`tools/patch_inspection.py` now seamlessly loads both translation formats:
1. **Master Catalog Schema (`translations/room_inspection_ru.json`):**
   - Direct string lookup with dictionary payload `{"russian": "...", "type": "...", ...}` or direct string format.
   - If an entry has a dictionary with a `"russian"` key, extracts the string.
   - If a translation is non-empty, replaces the room's English string with the Russian string.
   - If a translation is missing or empty `""`, preserves the existing string unchanged.
2. **Specific Entries Schema (`data/inspection_ru.json`):**
   - Preserves backward compatibility with `entries` maps (e.g. `0x05D`) and `common` dictionary fallbacks.

### B. Raw Glyph Escape Support (`encode_string`)
- Added support for `<XXXX>` hexadecimal escape sequences (e.g. `<0007>`) directly in `encode_string`.
- Guarantees complete round-trip fidelity between `decode_string` (which emits `<XXXX>` for unmapped hardware glyphs) and `encode_string`, preventing unhandled `KeyError` exceptions when processing previously-patched archives.

### C. Sector Budget Enforcement & Progressive Line Condensation
- Sector capacity rule: $rebuilt\_size \le entry.size$ (where $entry.size$ is a multiple of CD-ROM 2,048-byte sectors).
- Integrated `tools.text_wrapper.shorten_lines` into `rebuild_inspection_entry`:
  - **Pass 1 (3-line strings down to 2 lines):** Targets strings with $> 2$ lines sorted by length descending, applying `shorten_lines(s, max_lines=2)` until $new\_data\_end \le allocated$.
  - **Pass 2 (2-line strings down to 1 line):** If still overflowing, targets strings with $> 1$ line applying `shorten_lines(s, max_lines=1)`.
  - Duplicate target pointers (`orig_target`) are tracked and kept synchronized across all string occurrences.
  - If capacity still cannot be met after condensation, raises `ValueError`.

### D. Real-World Case: Sunburg Tavern (Room `0x0C5`)
- Uncompressed Russian translations in Room `0x0C5` required 2,068 bytes, which exceeded the 1-sector budget (2,048 bytes) by 20 bytes.
- The progressive condensation engine detected the overflow, shortened two 3-line strings down to 2 lines with ellipses, reducing the rebuilt size to 2,044 bytes.
- Rebuilt size: **2,044 / 2,048 bytes** (margin: **4 bytes**, 0 sector overflow).

### E. CLI Options Added to `tools/patch_inspection.py`
- `--all-rooms` / `--batch`: Iterate over all 160 entries (`0x059`..`0x0F8`) and batch patch every valid room inspection entry.
- `--verbose` / `-v`: Print detailed per-room patching statistics (strings count, used bytes, allocated bytes, free margin).
- Default translations file dynamically defaults to `translations/room_inspection_ru.json` when present.

---

## 3. Verification & Test Suite

The test suite in `tools/test_batch_inspection_patch.py` covers 8 test cases:
1. `test_catalog_file_exists_and_valid`: Validates `translations/room_inspection_ru.json` structure and non-empty translations.
2. `test_resolve_entry_translations_catalog_schema`: Verifies dict with `"russian"`, direct string, missing key, and empty string handling.
3. `test_resolve_entry_translations_schema_b_compatibility`: Verifies backward compatibility with `entries` and `common` dictionaries.
4. `test_progressive_condensation_resolves_overflow`: Tests synthetic entry that overflows without shortening, proving automatic line condensation resolves it with `progressive_shorten=True`, and raises `ValueError` with `progressive_shorten=False`.
5. `test_impossible_budget_overflow_still_raises_error`: Proves massive unresolvable strings still raise `ValueError`.
6. `test_batch_patch_synthetic_unt_archive`: Verifies multi-room synthetic UNT archive patching, header pointer relocation (offsets `0x0024`, `0x002C`, `0x0030`), sector boundary zero-padding, and round-trip readability.
7. `test_batch_patching_real_disc_all_rooms`: Tests batch patching all 149 valid rooms from real CD-ROM BIN image, verifying $0$ sector overflows, sector alignment, and Room `0x0C5` condensation.
8. `test_cli_batch_patch_prog`: Tests subprocess CLI invocation with `--prog`, `--translations`, `--all-rooms`, and `--verbose`.

### Test Execution Output
```bash
pytest tools/test_batch_inspection_patch.py tools/test_patch_inspection.py tools/test_inspection_translations.py -v
============================== 29 passed in 0.40s ==============================
```

### Full Disc Batch Injection Output
```bash
python3 tools/patch_inspection.py \
  --bin localization-output/ru/slayers_royal_ru.bin \
  --translations translations/room_inspection_ru.json \
  --all-rooms \
  --verbose
# Output:
# Successfully patched 149 inspection entries in localization-output/ru/slayers_royal_ru.bin
```

---

## 4. Deliverables Summary
- **Modified:** `tools/patch_inspection.py` (added batch patching engine, progressive condensation, schema support, CLI options).
- **Created:** `tools/test_batch_inspection_patch.py` (8 unit/regression tests for batch patching and sector budgets).
- **Report:** `.superpowers/sdd/2026-09-08-slayers-royal-russian-port/task-all-insp-3-report.md`.
