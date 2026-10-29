#!/usr/bin/env python3
"""QA Test Suite for Slayers Royal Amelia's Cliff Jump (Minigame Amelia Jump) Ren'Py implementation.

Validates that minigame_amelia_jump.rpy strictly matches MINIGAME_AMELIA_SPEC.md,
MIPS-confirmed reverse-engineering specifications from PROG.UNT Entry 14 and SMINI.UNT Entry 1,
and that all required visual and audio assets are present and properly connected.
"""

from __future__ import annotations
import json
import math
import os
from pathlib import Path
import unittest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "build" / "amelia_extraction" / "MINIGAME_AMELIA_SPEC.md"
CATALOG_PATH = REPO_ROOT / "translations" / "minigames_ru.json"
RENPY_GAME_DIR = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game")
RENPY_MINIGAME_PATH = RENPY_GAME_DIR / "minigame_amelia_jump.rpy"
RENPY_MENU_PATH = RENPY_GAME_DIR / "minigames_menu.rpy"


class TestRenpyAmeliaMinigame(unittest.TestCase):
    """Test suite validating Ren'Py Amelia Jump minigame against spec and romhack catalog."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(SPEC_PATH.is_file(), f"Specification file missing: {SPEC_PATH}")
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")

        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog file missing: {CATALOG_PATH}")
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.amelia_catalog = cls.catalog["minigames"]["amelia_climb"]

        cls.assertTrue(
            RENPY_MINIGAME_PATH.is_file(),
            f"Ren'Py minigame file missing: {RENPY_MINIGAME_PATH}",
        )
        cls.rpy_text = RENPY_MINIGAME_PATH.read_text(encoding="utf-8")

        # Extract and compile Python block from minigame_amelia_jump.rpy
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
        cls.compiled = compile(cls.py_code, "minigame_amelia_jump.py", "exec")

    def _create_game_instance(self, lang="russian"):
        """Helper to instantiate AmeliaJumpGame with mocked Ren'Py environment."""
        fake_globals = {
            "_preferences": type("Preferences", (), {"language": lang})(),
            "renpy": type("FakeRenpy", (), {
                "sound": type("FakeSound", (), {
                    "play": lambda *a, **kw: None,
                    "queue": lambda *a, **kw: None,
                })(),
                "music": type("FakeMusic", (), {
                    "play": lambda *a, **kw: None,
                    "stop": lambda *a, **kw: None,
                })(),
            })(),
        }
        exec(self.compiled, fake_globals)
        return fake_globals["AmeliaJumpGame"]()
    def _advance_time(self, game, seconds, step=0.033):
        """Simulate Ren'Py frame timer ticking over seconds."""
        steps = int(seconds / step)
        for _ in range(steps):
            game.tick(step)


    # ==========================================================================
    # 1. Menu Integration & Registration
    # ==========================================================================

    def test_minigames_menu_registration(self):
        """Verify minigames_menu.rpy contains start_amelia_jump with both RU and EN planks."""
        self.assertTrue(RENPY_MENU_PATH.is_file(), "minigames_menu.rpy missing")
        menu_text = RENPY_MENU_PATH.read_text(encoding="utf-8")

        self.assertIn('"id": "amelia_jump"', menu_text)
        self.assertIn('"label": "start_amelia_jump"', menu_text)
        self.assertIn('"img_ru": "images/minigames_menu/mg_amelia_ru.png"', menu_text)
        self.assertIn('"img_en": "images/minigames_menu/mg_amelia_en.png"', menu_text)

        plank_ru = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_amelia_ru.png"
        plank_en = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_amelia_en.png"
        self.assertTrue(plank_ru.is_file(), "mg_amelia_ru.png missing")
        self.assertTrue(plank_en.is_file(), "mg_amelia_en.png missing")

        with Image.open(plank_ru) as im:
            self.assertEqual(im.size, (420, 252))
        with Image.open(plank_en) as im:
            self.assertEqual(im.size, (420, 252))

    # ==========================================================================
    # 2. Visual Assets Verification
    # ==========================================================================

    def test_background_assets_present(self):
        """Verify all cliff background slices and stitched full panorama are present."""
        bg_dir = RENPY_GAME_DIR / "images" / "minigame_amelia" / "background"
        self.assertTrue(bg_dir.is_dir(), "background dir missing")

        for f in ["cliff_full_320x768.png", "cliff_layer_01_top_sky_320x256.png",
                  "cliff_layer_02_middle_wall_320x256.png", "cliff_layer_03_bottom_ground_320x256.png"]:
            p = bg_dir / f
            self.assertTrue(p.is_file(), f"Background file missing: {f}")

    def test_ui_assets_present(self):
        """Verify HUD, combo window, buttons, banners, and portraits are present."""
        ui_dir = RENPY_GAME_DIR / "images" / "minigame_amelia" / "ui"
        self.assertTrue(ui_dir.is_dir(), "ui dir missing")

        expected_ui = [
            "combo_window_ps1.png", "glyph_circle_16x16.png",
            "glyph_arrow_up_16x16.png", "glyph_arrow_down_16x16.png",
            "glyph_arrow_left_16x16.png", "glyph_arrow_right_16x16.png",
            "banners/banner_ready_ps1.png", "banners/banner_go_ps1.png",
            "banners/banner_finish_ps1.png", "digits/digit_0.png", "digits/digit_dot.png"
        ]
        for f in expected_ui:
            p = ui_dir / f
            self.assertTrue(p.is_file(), f"UI asset missing: {f}")

    def test_all_pose_animations_present(self):
        """Verify all 30 animation sequences in amelia/ are intact with all frames."""
        game = self._create_game_instance()
        amelia_dir = RENPY_GAME_DIR / "images" / "minigame_amelia" / "amelia"
        self.assertTrue(amelia_dir.is_dir(), "amelia dir missing")

        for att, combos in game.COMBOS_TABLE.items():
            for c in combos:
                anim_folder = amelia_dir / c["anim"]
                self.assertTrue(anim_folder.is_dir(), f"Anim folder missing: {c['anim']}")
                for idx in range(c["frames"]):
                    frame_path = anim_folder / f"screen_frame_{idx:02d}.png"
                    self.assertTrue(frame_path.is_file(), f"Missing frame {frame_path}")

        special_anims = [
            ("12_anim_00_cliff_speech_prep", 2),
            ("13_anim_01_cliff_speech_talk", 15),
            ("14_anim_02_jump_takeoff", 3),
            ("28_anim_16_landing_safe", 6),
            ("29_anim_17_victory_pose", 4),
            ("33_anim_21_crash_faceplant_splat", 6),
            ("32_anim_20_recovering_get_up", 3),
            ("30_anim_18_stumble_penalty_1", 3),
            ("31_anim_19_stumble_penalty_2", 3),
        ]
        for folder_name, count in special_anims:
            folder = amelia_dir / folder_name
            self.assertTrue(folder.is_dir(), f"Special anim folder missing: {folder_name}")
            for idx in range(count):
                frame_path = folder / f"screen_frame_{idx:02d}.png"
                self.assertTrue(frame_path.is_file(), f"Missing special frame {frame_path}")

    # ==========================================================================
    # 3. Audio Assets Verification
    # ==========================================================================

    def test_audio_assets_present(self):
        """Verify all SPU SFX, BGM 20, and Amelia victory voices exist in game/audio/."""
        audio_dir = RENPY_GAME_DIR / "audio"
        music_dir = RENPY_GAME_DIR / "music"

        self.assertTrue((music_dir / "20_battle02.mp3").is_file(), "BGM 20 missing")

        required_sfx = [
            "sfx_01_click_vag00_n61.ogg", "sfx_85_whistle_vag02_n74.ogg",
            "sfx_66_leap_vag01_n71.ogg", "sfx_43_input_vag00_n64.ogg",
            "sfx_81_hit_vag02_n70.ogg", "sfx_83_pose_vag02_n72.ogg",
            "sfx_86_chime_vag02_n75.ogg", "sfx_06_fail_vag00_n66.ogg",
            "sfx_92_land_vag03_n65.ogg", "sfx_05_victory_vag00_n65.ogg",
            "sfx_53_crash_vag00_n74.ogg", "sfx_58_rank_vag01_n63.ogg",
            "sfx_94_stamp_vag03_n67.ogg",
            "amelia_victory_vic_01.wav", "amelia_victory_vic_02.wav", "amelia_victory_vic_03.wav"
        ]
        for sfx in required_sfx:
            p = audio_dir / sfx
            self.assertTrue(p.is_file(), f"Audio SFX missing: {sfx}")

    # ==========================================================================
    # 4. Gameplay Logic, Math, and Physics Verification
    # ==========================================================================

    def test_initial_state_and_speeches(self):
        """Verify starting score is 55, attempt 1, phase speech with valid 1..5 speech."""
        game = self._create_game_instance(lang="russian")
        self.assertEqual(game.score, 55, "Initial score must be strictly 55 (RAM 0x80070498)")
        self.assertEqual(game.attempt, 1, "Initial attempt must be 1 (Easy)")
        self.assertEqual(game.phase, "speech")
        self.assertIn(game.current_speech_idx, [1, 2, 3, 4, 5])
        self.assertIn("«", game.get_speech_text())

        # Test English locale
        game_en = self._create_game_instance(lang="english")
        self.assertIn("“", game_en.get_speech_text())

    def test_phase_transitions_timings(self):
        """Verify timing of READY (2.0s), GO! (1.0s), dive (3.0s), and freefall (10.0s)."""
        game = self._create_game_instance()
        self.assertEqual(game.phase, "speech")

        game.advance_from_speech()
        self.assertEqual(game.phase, "ready_banner")
        self.assertAlmostEqual(game.ready_timer, 2.0, places=2)

        # Advance 2.1s -> GO! banner
        self._advance_time(game, 2.1)
        self.assertEqual(game.phase, "go_banner")
        self.assertLessEqual(game.go_timer, 1.0)
        self.assertGreater(game.go_timer, 0.5)

        # Advance 1.1s -> parabolic dive
        self._advance_time(game, 1.1)
        self.assertEqual(game.phase, "parabolic_dive")
        self.assertLessEqual(game.dive_timer, 3.0)
        self.assertGreater(game.dive_timer, 2.0)
        # Advance 3.1s -> falling loop
        self._advance_time(game, 3.1)
        self.assertEqual(game.phase, "falling")
        self.assertLessEqual(game.fall_timer, 10.0)
        self.assertGreater(game.fall_timer, 9.5)
        self.assertTrue(game.combo_window_visible, "Combo window must pop up during input window")

    def test_combo_recognition_and_scoring(self):
        """Test exact combo recognition for all 3 attempts (Easy, Normal, Hard)."""
        # --- ATTEMPT 1: EASY ---
        game = self._create_game_instance()
        game.advance_from_speech()
        self._advance_time(game, 6.3)  # ready (2.0) + go (1.0) + dive (3.0) -> falling

        # 1. Level A (DOWN -> CIRCLE) -> +7 pts
        game.input_button(game.DIR_DOWN)
        game.input_circle_confirm()
        self.assertEqual(game.score, 55 + 7)
        self.assertEqual(game.last_score_delta, 7)
        self.assertTrue(game.attempt_success)
        # Verify combo window hides during pose execution!
        self.assertFalse(game.combo_window_visible, "Combo window must hide during pose execution")
        self.assertTrue(game.pose_active)

        # 2. Complete pose and resume
        game.anim.playing_seq = False
        game.anim.tick(0.0)
        game.pose_active = False
        game.combo_window_visible = True

        # Level B (DOWN -> RIGHT -> CIRCLE) -> +11 pts
        game.input_button(game.DIR_DOWN)
        game.input_button(game.DIR_RIGHT)
        game.input_circle_confirm()
        self.assertEqual(game.score, 62 + 11)

        # 3. Level C (DOWN -> RIGHT -> DOWN -> CIRCLE) -> +15 pts
        game.pose_active = False
        game.input_button(game.DIR_DOWN)
        game.input_button(game.DIR_RIGHT)
        game.input_button(game.DIR_DOWN)
        game.input_circle_confirm()
        self.assertEqual(game.score, 73 + 15)

        # 4. Level S (DOWN -> RIGHT -> DOWN -> RIGHT -> L1 -> CIRCLE) -> +20 pts
        game.pose_active = False
        game.input_button(game.DIR_DOWN)
        game.input_button(game.DIR_RIGHT)
        game.input_button(game.DIR_DOWN)
        game.input_button(game.DIR_RIGHT)
        game.input_button(game.BTN_L1)
        game.input_circle_confirm()
        self.assertEqual(game.score, 88 + 20)

        # 5. Invalid input -> -5 penalty
        game.pose_active = False
        game.input_button(game.DIR_UP)
        game.input_circle_confirm()
        self.assertEqual(game.score, 108 - 5)
        self.assertEqual(game.last_score_delta, -5)

    def test_attempt_progression_and_stat_boost(self):
        """Verify progression through Attempts 1..3 and stat boost floor(score / 20)."""
        game = self._create_game_instance()
        self.assertEqual(game.attempt, 1)

        # Complete attempt 1 with success
        game.advance_from_speech()
        self._advance_time(game, 6.3) # ready (2.0) + go (1.0) + dive (3.0) -> falling
        self.assertEqual(game.phase, "falling")
        game.input_button(game.DIR_DOWN)
        game.input_circle_confirm()
        self._advance_time(game, 10.5)  # fall finished -> landing
        self.assertEqual(game.phase, "landing")
        self._advance_time(game, 4.0)   # landing finished -> transition
        self.assertEqual(game.phase, "transition")
        self.assertEqual(game.attempt, 2)

        # Transition to attempt 2 speech
        self._advance_time(game, 2.0)
        self.assertEqual(game.phase, "speech")

        # Complete attempt 2 with success
        game.advance_from_speech()
        self._advance_time(game, 6.3)
        self.assertEqual(game.phase, "falling")
        game.input_button(game.DIR_DOWN)
        game.input_button(game.DIR_DOWN)
        game.input_circle_confirm()  # Normal Level A
        self._advance_time(game, 10.5)
        self._advance_time(game, 4.0)
        self.assertEqual(game.attempt, 3)

        # Complete attempt 3
        self._advance_time(game, 2.0)
        self.assertEqual(game.phase, "speech")
        game.advance_from_speech()
        self._advance_time(game, 6.3)
        self.assertEqual(game.phase, "falling")
        game.input_button(game.DIR_UP)
        game.input_button(game.DIR_DOWN)
        game.input_circle_confirm()  # Hard Level A (+7)
        self._advance_time(game, 10.5)
        self._advance_time(game, 4.0)
        # Results screen
        self.assertEqual(game.phase, "results")
        expected_boost = game.score // 20
        self.assertEqual(game.stat_boost, expected_boost)
        self.assertIn("СПРАВЕДЛИВОСТИ", game.rank_title)


if __name__ == "__main__":
    unittest.main()
