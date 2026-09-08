# SDD ledger — plan: docs/superpowers/plans/2026-09-08-slayers-royal-russian-port.md

## Pre-flight scan
| Tasks | Interface / Shared State | Scan Finding |
|---|---|---|
| Task 1 & 2 | patch_repo setup -> disc export in patch_repo | Compatible: Task 1 prepares patch_repo, Task 2 exports into patch_repo/localization-work/ru |
| Task 2 & 3 | PS1 disc dump & Ren'Py game | Independent downloads and unpackings |
| Task 2 & 4 | dialogue.po -> alignment engine | Task 2 produces clean Japanese dialogue.po; Task 4 populates msgstr |
| Task 3 & 4 | Ren'Py extracted scripts -> alignment engine | Task 3 extracts .rpy; Task 4 reads .rpy |
| Task 4 & 5 | Updated dialogue.po -> validation | Task 4 wraps text to <=15 chars; Task 5 validates via localize.py validate |
| Task 5 & 6 | Validated workspace -> disc builder | Task 5 ensures zero errors; Task 6 builds bootable BIN/CUE |

All tasks agree with global constraints. Scan clean.
- Task 1: complete (commit 2580ce5, patch_repo cloned, dependencies verified)
- Task 3: complete (renpy_game.tar.gz downloaded, extracted, decompiled, report written)
- Task 2: complete (sr.bin verified SHA256 89760d728f0580dba1c6176f024d3cd6f8fc105b79bd1c27a819208fa0b4d0fe, patcher verified, 4514 segments exported to dialogue.po, 10/10 tests pass)
- Task 3: complete (GameJolt Ren'Py package downloaded, 16 .rpy files decompiled, 3431 dialogue lines analyzed, discovered 3333 lines with direct #(JP) source annotations and 659 voice cues)
- Task 4: complete (commit a93b5cd, text_wrapper.py and align_renpy_to_po.py implemented, 8/8 tests pass, 2924 segments translated into dialogue.po with 0 validation errors)
- Task 5: complete (localize.py validate passes with 0 errors, 2923 translated / 1591 untranslated / 4514 total, 10/10 pytest tests pass, coverage & character audit documented in task-5-report.md)
- Task 5: complete (localize.py validate passed with 0 errors, 10/10 tests pass, 100% PS1 hardware compliance, identified scene byte capacity budget for Task 6)
- Task 6: complete (fit_dialogue_budget.py implemented, 30/30 scenes fitted to sector budgets, slayers_royal_ru.bin 712,300,848 B & cue built and verified SHA256 c5d82a8fb957d283d15d89f154a44258838342c8feab14077ee80dfa6a10693d, report written)
- Task 6: complete (commit a368b70, fit_dialogue_budget.py implemented, slayers_royal_ru.bin (712300848 bytes, SHA256 c5d82a8fb957d283d15d89f154a44258838342c8feab14077ee80dfa6a10693d) compiled and verified with cue and build reports)
- Lore Cards Task 1: complete (discovered lore cards are pre-rendered 4bpp TIM textures in PROG.UNT entries 32, 34, 36, 38, 40, 41, 43, 45, 47, 49, 51, 53 with LZ mode 1 compression)
- Lore Cards Task 2: complete (commit 31266d6, data/lore_cards_ru.json created with 13 Russian lore cards)
- Lore Cards Task 3: complete (commit 40ebe9e, tools/patch_lore_cards.py implemented, 13/13 unit tests pass, all 13 cards within sector budgets)
- Lore Cards Task 4: complete (slayers_royal_ru.bin patched with 13 cards & 11 banners, 712,300,848 B, SHA256 53f99a52f204300b7dd1d73111be2e78b7e1549a7f4d9cd122a2a3fa5452ddc9, EDC/ECC recalculated, Naga composite verified, 33/33 tests pass)
- Lore Cards Task 4: complete (commit 40a9e6b, all 13 Russian cards injected into disc, Mode 2 Form 1 EDC/ECC recalculated, 33/33 tests pass, visual composite preview verified)
- Mojibake Task 1: complete (commit e5f77d6, 196 choices and 03B turns translated, 03B is 100% translated, 0 validation errors)
- Mojibake Task 2: complete (tools/patch_inspection.py and data/inspection_ru.json implemented, 0x05D 31/31 translated including Подвесная лампа., 13/13 tests pass)
- Mojibake Task 2: complete (commit 6e87538, tools/patch_inspection.py and data/inspection_ru.json implemented, 31/31 tavern strings translated including 'Подвесная лампа', 13/13 tests pass)
- Mojibake Task 3: complete (rebuilt slayers_royal_ru.bin 712,300,848 B, SHA256 d6239fa6ed143098ca3581c6992963f17851628aaca8ee40e279d8e41c738efe, choices & inspection & lore cards integrated, 46/46 tests pass, launcher verified)
- Mojibake & Inspection Task 3: complete (commit 5d73270, full rebuild with zero mojibake choices, Russian room inspection, and lore cards; 46/46 tests pass)
- Full Inspection Task 1: complete (commit e7bf227, translations/room_inspection_ru.json created with 734 unique strings, 18/18 tests pass)
- Full Inspection Task 2: complete (tools/build_inspection_translations.py and tools/test_inspection_translations.py implemented, 734/734 inspection strings translated, <=15 chars/line & 1-3 lines enforced, 49/49 tests pass)
- Full Inspection Task 2: complete (commit 7a145b4, 100% of 734 strings translated in translations/room_inspection_ru.json, 0 lines > 15 chars, 49/49 tests pass)
- Full Inspection Task 3: complete (tools/patch_inspection.py batch mode implemented with sector budget enforcement & progressive condensation, tools/test_batch_inspection_patch.py implemented, 29/29 tests pass, 149/149 rooms patched with 0 sector overflows)
- Full Inspection Task 3: complete (commit 7ab1ddc, batch injection engine implemented in tools/patch_inspection.py, 149/149 rooms patched with 0 overflows, 29/29 tests pass)
- Full Inspection Task 4: complete (rebuilt slayers_royal_ru.bin 712,300,848 B, SHA256 ed2be479585c8d428e0c5dcd2602caa41e4b95c01a7e5ee621d98f06523966f4, 149/149 rooms patched, 13 lore cards injected, Mode 2 Form 1 EDC/ECC recalculated, 67/67 tests pass, launcher dry-run verified)
- Full Inspection Task 4: complete (commit 9f4fa47, master rebuild complete, 149/149 rooms patched, 67/67 tests pass, disc verified with SHA256 ed2be479585c8d428e0c5dcd2602caa41e4b95c01a7e5ee621d98f06523966f4)
- Unabridge Task 1: complete (commits c39af14, d64e8b1; 4514/4514 dialogue entries translated, 03C 100% translated, validated without --allow-incomplete)
- Unabridge Task 2: complete (all 143 truncated inspection strings re-authored into complete sentences, 0 lines > 15 chars, 9/9 pytest pass)
- Unabridge Task 2: complete (commit 90d52ee, all 143 truncated strings re-authored into complete sentences, 0 lines > 15 chars, 9/9 tests pass)
- Unabridge Task 3: complete (master rebuild executed without --allow-incomplete, 149/149 rooms batch-patched with unabridged catalog, 13 lore cards injected, disc size 712,300,848 B verified, 68/68 tests pass, launcher dry-run verified, report written)
- Unabridge Task 3: complete (commit cdca4fb, master rebuild without --allow-incomplete, 4514/4514 dialogue translated, 149/149 rooms unabridged, 68/68 tests pass, SHA256 29b8327bce3d6a4a4d84db397e2f4d0377c1ba0b8bbb6ad56ab5344c96a606c9)
- Press Start Task 1: complete (commits 3ab4b3e, e8fb16a; PressStart2P.ttf integrated at 11pt baseline y=12, all 33 tests pass)
- Press Start Task 2: complete (master rebuild with Press Start 2P font atlas, 149 rooms patched, 13 lore cards injected, 712,300,848 B, SHA256 ce279b9c8c2203c2780f5bd6811ac05461e36a832b6ef452fd7a2bea2bb50d97, 68/68 tests pass)
