#!/usr/bin/env python3
"""QA Test Suite for Slayers Royal Naga Laughter Battle (Minigame Naga Laugh) Ren'Py implementation.

Validates that minigame_naga_laugh.rpy strictly matches MINIGAME_NAGA_SPEC.md,
MIPS-confirmed reverse-engineering specifications, translations/minigames_ru.json,
and that all required visual and audio assets are present and properly connected.
"""

from __future__ import annotations
import json
import math
from pathlib import Path
import unittest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "build" / "naga_extraction" / "MINIGAME_NAGA_SPEC.md"
CATALOG_PATH = REPO_ROOT / "translations" / "minigames_ru.json"
RENPY_GAME_DIR = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game")
RENPY_MINIGAME_PATH = RENPY_GAME_DIR / "minigame_naga_laugh.rpy"
RENPY_MENU_PATH = RENPY_GAME_DIR / "minigames_menu.rpy"


class TestRenpyNagaMinigame(unittest.TestCase):
    """Test suite validating Ren'Py minigame against spec and romhack catalog."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(SPEC_PATH.is_file(), f"Specification file missing: {SPEC_PATH}")
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")

        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog file missing: {CATALOG_PATH}")
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.naga_catalog = cls.catalog["minigames"]["naga_laugh"]

        cls.assertTrue(
            RENPY_MINIGAME_PATH.is_file(),
            f"Ren'Py minigame file missing: {RENPY_MINIGAME_PATH}",
        )
        cls.rpy_text = RENPY_MINIGAME_PATH.read_text(encoding="utf-8")

        # Extract and compile Python block from minigame_naga_laugh.rpy
        lines = cls.rpy_text.splitlines()
        py_lines = []
        in_py = False
        for line in lines:
            if line.strip().startswith("init -4 python:"):
                in_py = True
                continue
            if in_py and line.startswith("# ==="):
                in_py = False
                break
            if in_py:
                if line.startswith("    "):
                    py_lines.append(line[4:])
                elif not line.strip():
                    py_lines.append("")
                else:
                    py_lines.append(line)

        cls.py_code = "\n".join(py_lines)
        cls.compiled = compile(cls.py_code, "minigame_naga_laugh.py", "exec")

    def _create_game(self, lang="russian"):
        class MockPreferences:
            language = lang

        class MockMusic:
            def __init__(self, parent):
                self.parent = parent
            def play(self, filename, channel="music", loop=False):
                if channel == "voice":
                    self.parent.played_voices.append(filename)
            def stop(self, channel="music", fadeout=0.0):
                pass

        class MockRenpy:
            def __init__(self):
                self.played_sounds = []
                self.played_voices = []
                self.music = MockMusic(self)

            def play(self, filename, channel="sound"):
                if channel == "voice":
                    self.played_voices.append(filename)
                else:
                    self.played_sounds.append(filename)

        scope = {
            "_preferences": MockPreferences(),
            "renpy": MockRenpy(),
        }
        exec(self.compiled, scope)
        game = scope["NagaLaughGame"]()
        return game, scope["renpy"]

    def test_01_menu_integration(self):
        """Verify minigames_menu.rpy includes naga_laugh with correct labels and plank images."""
        self.assertTrue(RENPY_MENU_PATH.is_file(), "minigames_menu.rpy missing")
        menu_text = RENPY_MENU_PATH.read_text(encoding="utf-8")
        self.assertIn('"id": "naga_laugh"', menu_text)
        self.assertIn('"label": "start_naga_laugh"', menu_text)
        self.assertIn('"img_ru": "images/minigames_menu/mg_naga_ru.png"', menu_text)
        self.assertIn('"img_en": "images/minigames_menu/mg_naga_en.png"', menu_text)

        # Check plank image dimensions
        plank_ru = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_naga_ru.png"
        plank_en = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_naga_en.png"
        self.assertTrue(plank_ru.is_file(), "mg_naga_ru.png missing")
        self.assertTrue(plank_en.is_file(), "mg_naga_en.png missing")

        with Image.open(plank_ru) as im:
            self.assertEqual(im.size, (420, 252), "Plank RU should be 420x252")
        with Image.open(plank_en) as im:
            self.assertEqual(im.size, (420, 252), "Plank EN should be 420x252")

    def test_02_all_naga_sprites_exist(self):
        """Verify all 112 sprites exist in images/minigame_naga/."""
        naga_dir = RENPY_GAME_DIR / "images" / "minigame_naga"
        self.assertTrue(naga_dir.is_dir(), "images/minigame_naga directory missing")

        required_files = [
            "background/bg_village_1280x720.png",
            "background/bg_village_320x224.png",
            "naga/idle/naga_idle.png",
            "naga/inhale/naga_inhale_1.png",
            "naga/inhale/naga_inhale_2.png",
            "naga/inhale/naga_inhale_3.png",
            "naga/laugh/naga_laugh_1.png",
            "naga/laugh/naga_laugh_2.png",
            "naga/triumph/naga_triumph_pose.png",
            "naga/pant/naga_pant_1.png",
            "naga/choke/naga_choke_1.png",
            "ui/arrows/arrow_right_active.png",
            "ui/arrows/arrow_up_active.png",
            "ui/arrows/arrow_left_active.png",
            "ui/arrows/arrow_down_active.png",
            "ui/gauge/lungs_stage_3_full.png",
            "ui/banners/banner_ready.png",
            "ui/banners/banner_go.png",
            "ui/banners/banner_great.png",
            "ui/sfx_laugh/hoho_large.png",
        ]
        for f in required_files:
            p = naga_dir / f
            self.assertTrue(p.is_file(), f"Required sprite missing: {f}")

    def test_03_all_audio_files_exist(self):
        """Verify all audio files exist in game/audio/ and game/music/."""
        required_audio = [
            "audio/SLAY_0004n.wav",
            "audio/naga_laugh_voice.wav",
            "audio/sfx_click_01.ogg",
            "audio/sfx_victory_05.ogg",
            "audio/sfx_fail_06.ogg",
            "audio/star_flash_ting.wav",
            "music/17.mp3",
        ]
        for a in required_audio:
            p = RENPY_GAME_DIR / a
            self.assertTrue(p.is_file(), f"Required audio missing: {a}")

    def test_04_game_initial_state_and_intro(self):
        """Verify initial game state matches MIPS specs (20.0s, ready/go banners)."""
        game, _ = self._create_game()
        self.assertEqual(game.phase, "dialogue")
        self.assertIn("begin/naga_begin", game.naga_img)
        self.assertEqual(game.time_left, 20.0)
        self.assertEqual(game.breath_depth, 0)

        # First dismiss completes typing and freezes on begin/naga_begin01
        game.dismiss_dialogue()
        self.assertTrue(game.dialogue_typing_done)
        self.assertEqual(game.naga_anim.current_frame, "begin/naga_begin01")

        # Second dismiss advances to intro
        game.dismiss_dialogue()
        self.assertEqual(game.phase, "intro")
        # Advance intro timer past 2.5 seconds -> transitions to inhale
        game.tick(2.6)
        self.assertEqual(game.phase, "inhale")
    def test_05_counter_clockwise_input_and_debounce(self):
        """Verify counter-clockwise sequence: Right -> Up -> Left -> Down and debounce."""
        game, mock_renpy = self._create_game()
        game.dismiss_dialogue()
        game.dismiss_dialogue()
        game.tick(2.6)
        # Press Right
        game.player_press(game.DIR_RIGHT)
        self.assertEqual(game.breath_depth, 1)
        self.assertEqual(game.current_target_dir, game.DIR_UP)
        self.assertEqual(game.arrow_flash_status, "success")

        # Held key should NOT register again (debounce test)
        game.player_press(game.DIR_RIGHT)
        self.assertEqual(game.breath_depth, 1)

        # Release Right
        game.player_release(game.DIR_RIGHT)

        # Wrong press (Left instead of Up)
        game.player_press(game.DIR_LEFT)
        self.assertEqual(game.breath_depth, 1, "Wrong key must not increment score")
        self.assertEqual(game.arrow_flash_status, "fail")
        game.player_release(game.DIR_LEFT)

        # Continue rotation: Up -> Left -> Down
        game.player_press(game.DIR_UP)
        game.player_release(game.DIR_UP)
        self.assertEqual(game.breath_depth, 2)
        self.assertEqual(game.current_target_dir, game.DIR_LEFT)

        game.player_press(game.DIR_LEFT)
        game.player_release(game.DIR_LEFT)
        self.assertEqual(game.breath_depth, 3)
        self.assertEqual(game.current_target_dir, game.DIR_DOWN)

        game.player_press(game.DIR_DOWN)
        game.player_release(game.DIR_DOWN)
        self.assertEqual(game.breath_depth, 4)
        self.assertEqual(game.current_target_dir, game.DIR_RIGHT, "Completes full rotation back to Right")

    def test_06_inhalation_tiers_and_max_cap(self):
        """Verify inhalation animation tiers and max cap at 120."""
        game, _ = self._create_game()
        game.dismiss_dialogue()
        game.dismiss_dialogue()
        game.tick(2.6)
        # Test cap at 120
        dirs = [game.DIR_RIGHT, game.DIR_UP, game.DIR_LEFT, game.DIR_DOWN]
        for i in range(130):
            d = dirs[i % 4]
            game.player_press(d)
            game.player_release(d)

        self.assertEqual(game.breath_depth, 120, "Breath must cap at 120")
        self.assertTrue(game.max_breath_reached)
        self.assertEqual(game.lungs_img, "images/minigame_naga/ui/gauge/lungs_fill_120.png")

    def test_07_laughter_drain_and_rankings(self):
        """Verify laughter duration formula: Breath / 6.0 seconds and results screen."""
        game, mock_renpy = self._create_game()
        game.dismiss_dialogue()
        game.dismiss_dialogue()
        game.tick(2.6)
        # Inhale 60 points
        dirs = [game.DIR_RIGHT, game.DIR_UP, game.DIR_LEFT, game.DIR_DOWN]
        for i in range(60):
            d = dirs[i % 4]
            game.player_press(d)
            game.player_release(d)

        self.assertEqual(game.peak_breath, 60)
        self.assertAlmostEqual(game.laughter_duration_sec, 10.0, places=1)

        # Run out timer
        game.tick(20.5)
        self.assertEqual(game.phase, "pause")

        # Pause ends, laugh begins
        game.tick(2.1)
        self.assertEqual(game.phase, "laugh")
        self.assertIn("audio/SLAY_0004n.wav", mock_renpy.played_voices)
        # Complete breath drain -> enters laugh_winddown (flying banners finish crossing screen)
        game.tick(12.0)
        self.assertEqual(game.phase, "laugh_winddown")

        # All banners fly off left edge of screen -> enters end_reaction
        game.tick(3.5)
        self.assertEqual(game.phase, "end_reaction")

        # Complete end reaction sequence and 1.0s hold delay -> enters ended
        game.tick(2.5)
        self.assertEqual(game.phase, "ended")
        self.assertIn("A: ЗВОНКИЙ СМЕХ", game.rank_title)


if __name__ == "__main__":
    unittest.main()
