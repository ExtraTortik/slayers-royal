#!/usr/bin/env python3
"""QA Test Suite for Slayers Royal Eating Contest (Minigame Lunch) Ren'Py implementation.

Validates that minigame_eating.rpy strictly matches MINIGAME_LUNCH_SPEC.md,
MIPS-confirmed reverse-engineering specifications, and translations/minigames_ru.json.
"""

from __future__ import annotations
import json
import math
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = REPO_ROOT / "MINIGAME_LUNCH_SPEC.md"
CATALOG_PATH = REPO_ROOT / "translations" / "minigames_ru.json"
RENPY_MINIGAME_PATH = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/minigame_eating.rpy")


class TestRenpyEatingMinigame(unittest.TestCase):
    """Test suite validating Ren'Py minigame against spec and romhack catalog."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(SPEC_PATH.is_file(), f"Specification file missing: {SPEC_PATH}")
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")

        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog file missing: {CATALOG_PATH}")
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.eating_catalog = cls.catalog["minigames"]["eating_contest"]

        cls.assertTrue(
            RENPY_MINIGAME_PATH.is_file(),
            f"Ren'Py minigame file missing: {RENPY_MINIGAME_PATH}",
        )
        cls.rpy_text = RENPY_MINIGAME_PATH.read_text(encoding="utf-8")

        # Extract and compile Python block from minigame_eating.rpy
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
        cls.compiled = compile(cls.py_code, "minigame_eating.py", "exec")

    def _create_game(self):
        class MockRenpy:
            def play(self, *args, **kwargs):
                pass

        scope = {"renpy": MockRenpy()}
        exec(self.compiled, scope)
        return scope["EatingContestGame"]()

    def test_spec_sections(self):
        """Verify MINIGAME_LUNCH_SPEC.md contains all 4 mandatory sections."""
        self.assertIn("## 1. Подтверждено кодом", self.spec_text)
        self.assertIn("## 2. Подтверждено текстом правил", self.spec_text)
        self.assertIn("## 3. Неизвестно — требует проверки человеком", self.spec_text)
        self.assertIn("## 4. Расхождения с текущей реализацией", self.spec_text)

        # Check key confirmed values in spec
        self.assertIn("3600 кадров", self.spec_text)
        self.assertIn("60.0 секунд", self.spec_text)
        self.assertIn("0x80055A1C", self.spec_text)
        self.assertIn("0x80055A64", self.spec_text)
        self.assertIn("0x80055A80", self.spec_text)
        self.assertIn("17", self.spec_text)

    def test_round_duration_and_intro(self):
        """Verify round duration is 60.0s (3600 frames) and intro is 2.0s (120 frames)."""
        game = self._create_game()
        self.assertEqual(game.total_time, 60.0)
        self.assertEqual(game.time_left, 60.0)
        self.assertEqual(game.time_seconds, 60)
        self.assertEqual(game.intro_timer, 2.0)
        self.assertEqual(game.phase, "intro")
    def test_rules_text_verbatim_catalog(self):
        """Verify restored rules screen text and title per user instructions."""
        self.assertIn('"Обед в таверне: Правила"', self.rpy_text)
        self.assertIn("Съешьте больше блюд, чем Гаури, пока не истекло время!", self.rpy_text)
        self.assertIn("Опасайтесь красного перца", self.rpy_text)
        self.assertIn("Спор за тарелку", self.rpy_text)
        # Verify battle music
        self.assertIn("19_battle02.mp3", self.rpy_text)
        # Verify lowered plates on table surface
        self.assertIn("585 - i * 11", self.rpy_text)
    def test_status_messages_verbatim_catalog(self):
        """Verify end-of-game status messages match lina_morale, gourry_satiated, combined_status."""
        status_msgs = self.eating_catalog["status_messages"]
        for msg_id in ("lina_morale", "gourry_satiated", "combined_status"):
            msg = status_msgs[msg_id]
            for line in msg.splitlines():
                self.assertIn(line, self.rpy_text)

    def test_struggle_mashing_threshold(self):
        """Verify struggle threshold is 17 mashes and resolves properly."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[1] = {"dish": "dish_meat", "is_pepper": False}
        game.gourry_reach(1)
        game.player_act(1)
        for _ in range(8):
            game.tick(0.05)
        self.assertEqual(game.phase, "struggle")
        self.assertEqual(game.struggle_mashes, 0)
        self.assertEqual(game.struggle_threshold, 17)
        self.assertTrue(2.5 <= game.struggle_timer <= 3.0)

        # Mash 16 times -> still in struggle
        for _ in range(16):
            game.player_act(1)
            self.assertEqual(game.phase, "struggle")
        self.assertEqual(game.struggle_mashes, 16)

        # 17th mash -> Lina wins!
        game.player_act(1)
        self.assertEqual(game.phase, "playing")
        self.assertEqual(game.lina_score, 1)
        self.assertIsNone(game.plates[1])

    def test_struggle_timeout_gourry_wins(self):
        """Verify that running out of struggle time (< 17 mashes) gives plate to Gourry."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[1] = {"dish": "dish_fish", "is_pepper": False}
        game.gourry_reach(1)
        game.player_act(1)
        for _ in range(8):
            game.tick(0.05)
        self.assertEqual(game.phase, "struggle")
        game.struggle_timer = 0.05
        game.tick(0.06)
        self.assertEqual(game.phase, "playing")
        self.assertEqual(game.gourry_score, 1)
        self.assertEqual(game.lina_score, 0)
        self.assertIsNone(game.plates[1])

    def test_struggle_game_timer_runs(self):
        """Verify that game total timer continues decrementing during struggle."""
        game = self._create_game()
        game.phase = "playing"
        game.time_left = 40.0
        game.plates[2] = {"dish": "dish_steak", "is_pepper": False}
        game.gourry_reach(2)
        game.player_act(2)
        for _ in range(8):
            game.tick(0.05)
        self.assertEqual(game.phase, "struggle")
        self.assertAlmostEqual(game.time_left, 39.6, places=2)

    def test_pepper_no_score_and_stun(self):
        """Verify pepper gives 0 score and causes stun."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[0] = {"dish": "dish_pepper", "is_pepper": True, "gourry_timer": 999.0}

        game.player_act(0)
        for _ in range(6):
            game.tick(0.05)
        self.assertEqual(game.lina_score, 0)
        self.assertEqual(game.lina_pose, "pepper")
        self.assertTrue(game.lina_stun > 0.0)
        self.assertIsNone(game.plates[0])
        # Verify authentic pepper burn sound is used instead of Lark's fireball voice
        self.assertNotIn("lark_fireball", self.rpy_text)
        self.assertIn("minigame_pepper_burn.wav", self.rpy_text)
        pepper_wav = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/audio/minigame_pepper_burn.wav")
        self.assertTrue(pepper_wav.is_file(), f"Missing {pepper_wav}")

    def test_gourry_eats_pepper_when_only_peppers_remain(self):
        """Verify that when only peppers remain, Gourry eats one, gets stunned, and clears slot."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[0] = {"dish": "dish_pepper", "is_pepper": True}
        game.plates[1] = {"dish": "dish_pepper", "is_pepper": True}
        game.plates[2] = {"dish": "dish_pepper", "is_pepper": True}
        game.gourry_decision_timer = 0.05
        game.spawn_timer = 10.0
        for _ in range(10):
            game.tick(0.05)
        cleared_plates = sum(1 for p in game.plates if p is None)
        self.assertEqual(cleared_plates, 1, "Exactly one pepper plate must be cleared by Gourry")
        self.assertEqual(game.gourry_score, 0, "Pepper must grant 0 score")
        self.assertEqual(game.gourry_pose, "pepper", "Gourry must enter pepper pose")
        self.assertGreater(game.gourry_stun, 0.0, "Gourry must be stunned after eating pepper")

    def test_dish_spawn_puff_and_sound(self):
        """Verify that dish spawn puff animation frames exist and calculate properly."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[0] = {
            "dish": "dish_meat",
            "is_pepper": False,
            "gourry_timer": 0.50,
            "spawn_anim": 0.24,
        }

        # Frame 0 (small puff)
        self.assertEqual(game.get_spawn_puff(0), "images/minigame_eating/spawn_puff_0.png")
        puff0 = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/images/minigame_eating/spawn_puff_0.png")
        self.assertTrue(puff0.is_file(), f"Missing {puff0}")

        # Frame 1 (medium expanding puff)
        game.plates[0]["spawn_anim"] = 0.12
        self.assertEqual(game.get_spawn_puff(0), "images/minigame_eating/spawn_puff_1.png")
        puff1 = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/images/minigame_eating/spawn_puff_1.png")
        self.assertTrue(puff1.is_file(), f"Missing {puff1}")

        # Frame 2 (large dissipating puff)
        game.plates[0]["spawn_anim"] = 0.05
        self.assertEqual(game.get_spawn_puff(0), "images/minigame_eating/spawn_puff_2.png")
        puff2 = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/images/minigame_eating/spawn_puff_2.png")
        self.assertTrue(puff2.is_file(), f"Missing {puff2}")

        # Animation finished
        game.plates[0]["spawn_anim"] = 0.0
        self.assertIsNone(game.get_spawn_puff(0))

    def test_score_format_no_japanese_dish_kanji(self):
        """Verify that the score strings do not contain Japanese '皿' kanji."""
        game = self._create_game()
        game.lina_score = 5
        game.gourry_score = 7
        self.assertEqual(game.lina_score_str, "05")
        self.assertEqual(game.gourry_score_str, "07")
        self.assertNotIn("皿", game.lina_score_str)
        self.assertNotIn("皿", game.gourry_score_str)

    def test_gamepad_icons_present_in_screen(self):
        """Verify screen template contains gamepad directional icons ←, ↓, →."""
        self.assertIn("←", self.rpy_text)
        self.assertIn("↓", self.rpy_text)
        self.assertIn("→", self.rpy_text)

    def test_win_and_lose_animations_freeze(self):
        """Rule 1: win plays win01 -> win02 and freezes; loose plays loose01 -> loose02 and freezes."""
        game = self._create_game()
        game.phase = "playing"
        game.lina_score = 10
        game.gourry_score = 5
        game.time_left = 0.05
        game.tick(0.06)  # Game ends: Lina wins, Gourry loses

        self.assertEqual(game.phase, "ended")
        self.assertEqual(game.lina_anim.current_frame, "win01")
        self.assertEqual(game.gourry_anim.current_frame, "loose01")

        # Advance past 0.18s
        game.tick(0.20)
        self.assertEqual(game.lina_anim.current_frame, "win02")
        self.assertTrue(game.lina_anim.frozen)
        self.assertEqual(game.gourry_anim.current_frame, "loose02")
        self.assertTrue(game.gourry_anim.frozen)

        # Tick 2 more seconds: must remain frozen on win02 and loose02
        game.tick(2.0)
        self.assertEqual(game.lina_anim.current_frame, "win02")
        self.assertEqual(game.gourry_anim.current_frame, "loose02")

    def test_idle_animation_cycles(self):
        """Rule 2: idle animation cycles between idle01 and idle02."""
        game = self._create_game()
        game.phase = "playing"
        self.assertEqual(game.lina_anim.current_frame, "idle01")
        game.tick(0.27)
        self.assertEqual(game.lina_anim.current_frame, "idle02")
        game.tick(0.27)
        self.assertEqual(game.lina_anim.current_frame, "idle01")

    def test_prepare_and_plate_sequences(self):
        """Rules 3, 4, 5: Any plate plays prepare first, plate 1 plays plate01, plate 2/3 play 01..03."""
        # Test Plate 1 (Slot 0)
        g1 = self._create_game()
        g1.phase = "playing"
        g1.plates[0] = {"dish": "dish_meat", "is_pepper": False, "gourry_timer": 5.0}
        g1.player_act(0)
        self.assertEqual(g1.lina_anim.current_frame, "prepare")
        g1.tick(0.09)
        self.assertEqual(g1.lina_anim.current_frame, "plate01")

        # Test Plate 2 (Slot 1)
        g2 = self._create_game()
        g2.phase = "playing"
        g2.plates[1] = {"dish": "dish_steak", "is_pepper": False, "gourry_timer": 5.0}
        g2.player_act(1)
        self.assertEqual(g2.lina_anim.current_frame, "prepare")
        g2.tick(0.09)
        self.assertEqual(g2.lina_anim.current_frame, "plate02_01")
        g2.tick(0.09)
        self.assertEqual(g2.lina_anim.current_frame, "plate02_02")
        g2.tick(0.09)
        self.assertEqual(g2.lina_anim.current_frame, "plate02_03")

    def test_empty_plate_aborts_on_frame_02(self):
        """Rule 6: Empty plates 2 & 3 abort on frame 02 and reset to idle."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[1] = None  # Empty plate 2
        game.player_act(1)

        self.assertEqual(game.lina_anim.current_frame, "prepare")
        game.tick(0.09)
        self.assertEqual(game.lina_anim.current_frame, "plate02_01")
        game.tick(0.09)
        self.assertEqual(game.lina_anim.current_frame, "plate02_02")
        game.tick(0.14)
        # Must NOT play plate02_03; must reset back to idle01!
        self.assertEqual(game.lina_anim.current_frame, "idle01")

    def test_all_sprites_have_zero_red_pixels(self):
        """Rule 8: Verify red reference pixels (255, 0, 0) are removed from all active sprites."""
        from PIL import Image
        img_dir = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/images/minigame_eating")
        char_pngs = list(img_dir.glob("lina_*.png")) + list(img_dir.glob("gourry_*.png"))
        for p in char_pngs:
            im = Image.open(p).convert("RGBA")
            data = im.load()
            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, a = data[x, y]
                    self.assertFalse(
                        r == 255 and g == 0 and b == 0 and a > 0,
                        f"Red pixel found in {p.name} at ({x}, {y})",
                    )

    def test_ui_sprites_and_digits_exist(self):
        """Rule 9: Verify all UI sprites, timer background, banners, and digits exist on disk."""
        img_dir = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game/images/minigame_eating")
        expected_files = [
            "timer_background.png",
            "ready.png",
            "go.png",
            "ui_clash.png",
            "push01.png",
            "push02.png",
            "draw.png",
            "lina_win.png",
            "lina_loose.png",
        ] + [f"digit_{d}.png" for d in range(10)]

        for name in expected_files:
            f_path = img_dir / name
            self.assertTrue(f_path.is_file(), f"Missing UI asset: {name}")
        self.assertIn("ui_clash.png", self.rpy_text)
    def test_struggle_loser_transitions_to_idle_not_loose(self):
        """Verify that when struggle resolves, loser transitions to idle, NOT loose."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[1] = {"dish": "dish_meat", "is_pepper": False}
        game.gourry_reach(1)
        game.player_act(1)
        for _ in range(8):
            game.tick(0.05)
        self.assertEqual(game.phase, "struggle")
        # Lina wins struggle (reaches 17 mashes)
        for _ in range(17):
            game.player_act(1)

        self.assertEqual(game.phase, "playing")
        # Loser (Gourry) must NOT play loose01/loose02, must play idle
        self.assertNotIn("loose", game.gourry_anim.current_frame)
        self.assertIn("idle", game.gourry_anim.current_frame)

    def test_spicy_animation_non_looping_holds_on_03(self):
        """Verify spicy animation: spicy01 -> spicy02 -> holds on 03 for main duration -> 04 -> idle."""
        game = self._create_game()
        game.phase = "playing"
        game.plates[0] = {"dish": "dish_pepper", "is_pepper": True, "gourry_timer": 5.0}
        game.player_act(0)
        # Complete reach
        for _ in range(5):
            game.tick(0.05)

        # After reach completes, spicy starts:
        self.assertEqual(game.lina_anim.current_frame, "spicy01")
        game.tick(0.16)
        self.assertEqual(game.lina_anim.current_frame, "spicy02")
        game.tick(0.16)
        # Main debuff duration: holds on spicy03
        self.assertEqual(game.lina_anim.current_frame, "spicy03")
        game.tick(1.0)
        self.assertEqual(game.lina_anim.current_frame, "spicy03")
        game.tick(0.50)
        # Near the end: switches to spicy04
        self.assertEqual(game.lina_anim.current_frame, "spicy04")
        game.tick(0.30)
        # Returns to idle
        self.assertEqual(game.lina_anim.current_frame, "idle01")

    def test_2d_anchor_sprite_shift_plates_2_and_3(self):
        """Verify 2D table anchors in screen definition for Lina and Gourry."""
        self.assertIn("anchor (148, 304)", self.rpy_text)
        self.assertIn("anchor (280, 343)", self.rpy_text)
        self.assertIn("pos (340, 494)", self.rpy_text)
        self.assertIn("pos (940, 494)", self.rpy_text)

    def test_struggle_fullscreen_click_and_space_key(self):
        """Verify that fullscreen click button and extra mash keys exist during struggle."""
        self.assertIn("xfill True", self.rpy_text)
        self.assertIn("yfill True", self.rpy_text)
        self.assertIn('key "K_SPACE"', self.rpy_text)
        self.assertIn('key "K_RETURN"', self.rpy_text)


if __name__ == "__main__":
    unittest.main()
