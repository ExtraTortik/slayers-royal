# Localization guide: how the text pipeline stays consistent

This is the short version of what went wrong in the Russian port and how the
repository now prevents it. Read it before adding a language, a tool, or a
catalogue.

## 1. Glyph IDs are allocated, not fixed

The English toolkit (`patch_repo/`, unmodified upstream) builds the runtime
font (`PROG.UNT` entry `0x03A`) at story-build time. Every character that is
not an English base cell is sorted by code point and given the next free cell.
So the glyph ID of `А` depends on how many characters such as `(`, `)`, `/`,
`~`, `«`, `»` appear anywhere in the story text. Add one `/` to a single line
and every Cyrillic letter moves one cell.

Rules:

- Never write glyph IDs into code or catalogues. Use
  `tools/vram_charmap.py` (`load_vram_charmap()` / `assert_encodable()`).
- The map has two sources that must agree: the live build output
  `patch_repo/localization-work/ru/build/glyph_map.json` and the committed
  snapshot `translations/glyph_map_ru.json`. `tools/vram_charmap.py --check`
  fails on any difference; `build.sh` runs it after every story build and in
  `--validate`.
- If the story text legitimately changes the allocation, run
  `python3 tools/vram_charmap.py --refresh-snapshot`, commit the snapshot, and
  rebuild everything (`./build.sh`), because every menu, inspection, minigame
  and map string was encoded with the old map.
- Characters that only menus use (for example `/` in shop dialogue) must be
  listed in `required_characters` of `translations/language_ru.json`;
  otherwise they get no cell and the build stops with the offending character.
- Minigame fonts copy cells `0x0004..0x0056` out of the runtime font. If the
  locale ever needs more cells, `patch_minigames.py` stops the build instead of
  clobbering the controller icons at `0x0057..0x0077`.

## 2. Two fonts, two charmaps

| Where the text is shown | Font | Charmap |
| --- | --- | --- |
| Story, inspection, shops, world map, minigames, menus | `PROG.UNT 0x03A` | `tools/vram_charmap.py` (dynamic) |
| Everything inside the battle overlay (`PROG.UNT 0x007`: labels, prompts, cues, save browser) | `PROG.UNT 0x142` | `tools/combat_dialogue_charmap.py` (Cyrillic at `0x0150..0x0191`) |

Never encode battle text with the main-font map or vice versa.

## 3. Pointer tables of the battle overlay

Entry `0x007` is loaded contiguously at RAM `0x8004E5B0`. Verified against
the original disc:

| Table | Offset | Count | Meaning |
| --- | --- | --- | --- |
| descriptors | `0x05F1FC` | 23 | pointers to 16-byte descriptors at `0x05EDD8`; **not text, never rewrite** |
| UI labels | `0x05F470` | 37 | strings packed in `0x05F278..0x05F470`, no fixed slots |
| dialogue cues | `0x06286C` | 105 | each points at a speaker opcode inside `0x05F810..0x06286A` |
| spell names | `0x06F4D8` | 58 | fixed `0x5F`-padded slots |

`tools/patch_combat_dialogues.py` packs the 37 labels from
`translations/combat_ru.json` (`system_strings`, pointer-table order) and
rewrites the UI table; dialogue blocks are written in place at their catalogue
offsets so the cue table never changes. `tools/patch_combat.py` only restores
the font and writes the in-place auxiliary strings. Both tools verify every
pointer after writing.

## 4. RAM ceilings are separate from archive capacity

Story scenes are loaded at `0x80121000` and the next container (`0x058`) at
`0x8012A800`. A scene larger than 19 sectors (`0x9800` bytes) is overwritten
in RAM and the text scanner walks into garbage (the "inn hang"). The extra
sectors each scene borrows from donor entry `0x011` live in
`translations/scene_expansion_ru.json`; `tools/localize_ru.py measure --write`
recomputes them and `tools/verify_scene_budget.py` refuses a built image with a
scene above the ceiling. Scene `0x040` is currently at the ceiling: any growth
there must be paid for with shorter text.

## 5. Reproducible builds

- `patch_repo/` is the upstream toolkit and is never edited. Port-specific
  settings are applied by `tools/localize_ru.py`: `translations/language_ru.json`
  (required characters, compact glyphs, ISO preparer string) and the scene
  expansion table above. The PO workspace is generated from
  `translations/story_dialogues_ru.json` on first use.
- Every partial build mode that recreates the base image (`--story`) re-runs
  every downstream patcher; a partial mode that skips one leaves that feature
  in English.
- Every sector writer goes through `localization.disc.replace_extent_in_place`,
  which regenerates Mode 2 Form 1 EDC/ECC. Do not write raw sectors.
- Never truncate an encoded string to fit a slot: a cut 16-bit word or a
  missing `0x00FF` terminator hangs the renderer. Shorten the text instead
  (the tools now raise).

## 6. Checklist for a new language or a new tool

1. Add the language preset under `translations/` and point `tools/localize_ru.py`
   (or a copy) at it; include every non-Latin character the menus need in
   `required_characters`.
2. Build the story once, commit the resulting `glyph_map` snapshot.
3. Encode with `load_vram_charmap()` or the battle charmap, never a literal table.
4. Locate targets through pointer tables or the archive index, never through
   absolute sector numbers copied from another build.
5. After writing, decode what you wrote through the pointer table and compare
   it with the catalogue. Make `--verify` fail loudly.
6. Run `./build.sh --validate` and the pytest suite before publishing an image.
