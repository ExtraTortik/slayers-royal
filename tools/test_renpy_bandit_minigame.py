#!/usr/bin/env python3
"""QA Test Suite for Slayers Royal Bandit Bullying (Minigame Bandit) Ren'Py implementation.

Validates that minigame_bandit_bullying.rpy strictly matches MINIGAME_BANDIT_SPEC.md,
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
SPEC_PATH = REPO_ROOT / "build" / "bandit_extraction" / "MINIGAME_BANDIT_SPEC.md"
CATALOG_PATH = REPO_ROOT / "translations" / "minigames_ru.json"
RENPY_GAME_DIR = Path("/home/samvel/Downloads/Telegram Desktop/Slayers Royal/game")
RENPY_MINIGAME_PATH = RENPY_GAME_DIR / "minigame_bandit_bullying.rpy"
RENPY_MENU_PATH = RENPY_GAME_DIR / "minigames_menu.rpy"


class TestRenpyBanditMinigame(unittest.TestCase):
    """Test suite validating Ren'Py minigame against spec and romhack catalog."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(SPEC_PATH.is_file(), f"Specification file missing: {SPEC_PATH}")
        cls.spec_text = SPEC_PATH.read_text(encoding="utf-8")

        cls.assertTrue(CATALOG_PATH.is_file(), f"Catalog file missing: {CATALOG_PATH}")
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.bandit_catalog = cls.catalog["minigames"]["bandit_bullying"]

        cls.assertTrue(
            RENPY_MINIGAME_PATH.is_file(),
            f"Ren'Py minigame file missing: {RENPY_MINIGAME_PATH}",
        )
        cls.rpy_text = RENPY_MINIGAME_PATH.read_text(encoding="utf-8")

        # Extract and compile Python block from minigame_bandit_bullying.rpy
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
        cls.compiled = compile(cls.py_code, "minigame_bandit_bullying.py", "exec")

    def _create_game(self):
        class MockSound:
            def __init__(self, parent):
                self.parent = parent
            def play(self, filename, channel="sound", loop=False):
                self.parent.played_sounds.append(filename)

        class MockRenpy:
            def __init__(self):
                self.played_sounds = []
                self.sound = MockSound(self)

        scope = {"renpy": MockRenpy()}
        exec(self.compiled, scope)
        game = scope["BanditBullyingGame"]()
        game.use_fixed_dt = True
        return game, scope

    def test_01_spec_sections(self):
        """Verify MINIGAME_BANDIT_SPEC.md contains all mandatory reverse-engineered sections."""
        self.assertIn("## 1. Подтверждено кодом", self.spec_text)
        self.assertIn("## 2. Подтверждено текстом правил", self.spec_text)
        self.assertIn("## 3. Неизвестно — требует проверки человеком", self.spec_text)
        self.assertIn("## 4. Звуковые эффекты и музыка", self.spec_text)

        # Check key confirmed values in spec
        self.assertIn("99.0 секунд", self.spec_text)
        self.assertIn("6 игровых дорожек", self.spec_text)
        self.assertIn("0x8004E5B0", self.spec_text)
        self.assertIn("1411", self.spec_text)
        self.assertIn("Flare Arrow", self.spec_text)
        self.assertIn("31", self.spec_text)

    def test_02_rules_text_verbatim_catalog(self):
        """Verify rules text and time bonus match translations/minigames_ru.json."""
        self.assertEqual(self.bandit_catalog["time_bonus"], "Время!")
        rules = self.bandit_catalog["rules_ru"]
        for line in rules.splitlines():
            self.assertIn(line, self.rpy_text)

    def test_03_menu_integration(self):
        """Verify minigames_menu.rpy includes bandit_bullying with correct labels and plank images."""
        self.assertTrue(RENPY_MENU_PATH.is_file(), "minigames_menu.rpy missing")
        menu_text = RENPY_MENU_PATH.read_text(encoding="utf-8")
        self.assertIn('"id": "bandit_bullying"', menu_text)
        self.assertIn('"label": "start_bandit_bullying"', menu_text)
        self.assertIn('"img_ru": "images/minigames_menu/mg_bandit_ru.png"', menu_text)
        self.assertIn('"img_en": "images/minigames_menu/mg_bandit_en.png"', menu_text)

        # Check plank image dimensions (420x252)
        plank_ru = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_bandit_ru.png"
        plank_en = RENPY_GAME_DIR / "images" / "minigames_menu" / "mg_bandit_en.png"
        self.assertTrue(plank_ru.is_file(), "mg_bandit_ru.png missing")
        self.assertTrue(plank_en.is_file(), "mg_bandit_en.png missing")

        with Image.open(plank_ru) as im:
            self.assertEqual(im.size, (420, 252), "Plank RU must be 420x252")
        with Image.open(plank_en) as im:
            self.assertEqual(im.size, (420, 252), "Plank EN must be 420x252")

    def test_04_all_bandit_sprites_exist(self):
        """Verify essential sprites exist in images/minigame_bandit/."""
        bandit_dir = RENPY_GAME_DIR / "images" / "minigame_bandit"
        self.assertTrue(bandit_dir.is_dir(), "images/minigame_bandit missing")

        required = [
            "background/background_woodland_camp.png",
            "background/background_defense_line.png",
            "lina/cast/frame_00.png",
            "lina/walk_up/frame_00.png",
            "lina/walk_down/frame_00.png",
            "lina/idle_down/frame_00.png",
            "lina/portraits/portrait_lina_victory.png",
            "lina/portraits/portrait_lina_defeat.png",
            "bandits/bandit_1/run/frame_00.png",
            "bandits/bandit_1/hit/frame_00.png",
            "bandits/bandit_2/run/frame_00.png",
            "bandits/bandit_2/hit/frame_00.png",
            "barrels/roll_a/frame_00.png",
            "barrels/roll_b/frame_00.png",
            "barrels/barrel_standing_intact.png",
            "effects/flare_arrow/frame_00.png",
            "effects/fire_burst_a/frame_00.png",
            "effects/barrel_smoke/frame_00.png",
            "effects/mega_explosion/frame_00.png",
            "ui/digits/digit_0.png",
            "ui/digits/digit_9.png",
            "ui/banners/ready.png",
            "ui/banners/banner_go.png",
            "ui/banners/banner_game_over.png",
            "ui/banners/banner_game_clear.png",
            "ui/labels/label_lv.png",
            "ui/labels/label_hits_hit_rate.png",
        ]
        for f in required:
            p = bandit_dir / f
            self.assertTrue(p.is_file(), f"Required sprite missing: {f}")
        # Verify that removed glitch frames are not present
        self.assertFalse((bandit_dir / "effects/mega_explosion/frame_10.png").is_file())
        self.assertFalse((bandit_dir / "effects/barrel_smoke/frame_09.png").is_file())

    def test_05_game_initialization(self):
        """Verify game constants and initial state."""
        game, _ = self._create_game()
        self.assertEqual(game.TOTAL_TIME, 99.0)
        self.assertEqual(game.LANES_COUNT, 6)
        self.assertEqual(game.DEFENSE_LINE_X, 1411.0)
        self.assertEqual(game.ARROW_SPEED, 900.0)
        self.assertEqual(game.ARROW_COOLDOWN, 0.20)
        self.assertEqual(game.MAX_ARROWS, 3)
        self.assertEqual(game.SCORE_PER_KILL, 100)

        self.assertEqual(game.phase, "intro")
        self.assertEqual(game.lina_lane, 2)
        self.assertEqual(game.time_left, 99.0)
        self.assertEqual(game.kills, 0)
        self.assertEqual(game.score, 0)

    def test_06_lina_movement_bounds_and_continuous_hold(self):
        """Verify Lina moves between 6 lanes with continuous movement while holding key."""
        game, _ = self._create_game()
        game.phase = "playing"

        # Initial lane is 2
        self.assertEqual(game.lina_lane, 2)
        game.move_up()
        self.assertEqual(game.lina_lane, 1)
        game.move_up()
        self.assertEqual(game.lina_lane, 0)
        game.move_up()  # Boundary protection
        self.assertEqual(game.lina_lane, 0)

        # Test continuous movement when holding "down"
        game.player_press("down")
        self.assertIn("down", game.held_keys)
        # Tick through 5 lane transitions (5 * 0.20s = 1.0s)
        for _ in range(40):
            game.tick(0.033)
        self.assertEqual(game.lina_lane, 5)  # Bottom boundary reached continuously!
        game.player_release("down")
        self.assertNotIn("down", game.held_keys)

        # Test continuous movement when holding "up" back to 0
        game.player_press("up")
        for _ in range(40):
            game.tick(0.033)
        self.assertEqual(game.lina_lane, 0)  # Top boundary reached continuously!
        game.player_release("up")
    def test_07_lina_animation_states_mapping(self):
        """Verify Lina animation mapping strictly matches user PS1 specification."""
        game, _ = self._create_game()
        game.phase = "playing"

        # 1. Default/always stance must be cast_flare_arrow
        self.assertIn("lina/cast/", game.lina_sprite)

        # 2. Fire casting (on shoot) must be walk_up
        game.shoot()
        self.assertIn("lina/walk_up/", game.lina_sprite)

        # 3. Defeat/Game Over must be idle_down
        game.phase = "game_over"
        self.assertIn("lina/idle_down/", game.lina_sprite)

        # 4. Victory/Game Clear must be walk_down
        game.phase = "game_clear"
        self.assertIn("lina/walk_down/", game.lina_sprite)

    def test_08_shooting_and_cooldown(self):
        """Verify Flare Arrow shooting, 10-frame cooldown, and 3-arrow limit."""
        game, _ = self._create_game()
        game.phase = "playing"
        game.lina_cast_timer = 0.0
        game.shoot()
        self.assertEqual(len(game.arrows), 1)
        self.assertEqual(game.arrows[0].lane, game.lina_lane)
        self.assertEqual(game.arrows[0].progress, 1410.0)

        # Immediate second shot should be blocked by cooldown
        game.shoot()
        self.assertEqual(len(game.arrows), 1)

        # Tick through cooldown (0.167s)
        game.tick(0.20)
        game.shoot()
        self.assertEqual(len(game.arrows), 2)

        game.tick(0.20)
        game.shoot()
        self.assertEqual(len(game.arrows), 3)

        # 4th shot blocked by MAX_ARROWS limit
        game.tick(0.20)
        game.shoot()
        self.assertEqual(len(game.arrows), 3)

    def test_09_collision_and_scoring(self):
        """Verify arrow hits target, awards 100 points, and removes projectile."""
        game, scope = self._create_game()
        game.phase = "playing"
        game.lina_lane = 1

        game.shoot()
        self.assertEqual(len(game.arrows), 1)

        # Spawn bandit in front of arrow
        BanditEntity = scope["BanditEntity"]
        bandit = BanditEntity(BanditEntity.TYPE_REGULAR, lane=1, speed=120.0)
        bandit.progress = 1000.0
        game.entities.append(bandit)

        # Tick until hit
        hit = False
        for _ in range(40):
            game.tick(0.033)
            if game.kills > 0:
                hit = True
                break

        self.assertTrue(hit, "Arrow should hit bandit")
        self.assertEqual(game.kills, 1)
        self.assertEqual(game.score, 100)
        self.assertFalse(bandit.active)

    def test_10_barrel_explosion_and_chain_reaction(self):
        """Verify barrel AoE radius (+-480 X, +-1 lane) and recursive chain detonation."""
        game, scope = self._create_game()
        game.phase = "playing"
        BanditEntity = scope["BanditEntity"]
        barrel1 = BanditEntity(BanditEntity.TYPE_BARREL_REGULAR, lane=2, speed=120.0)
        barrel1.progress = 800.0
        barrel2 = BanditEntity(BanditEntity.TYPE_BARREL_REGULAR, lane=3, speed=120.0)
        barrel2.progress = 850.0  # within radius
        bandit = BanditEntity(BanditEntity.TYPE_FAST, lane=4, speed=420.0)
        bandit.progress = 900.0  # within barrel2 radius

        game.entities.extend([barrel1, barrel2, bandit])
        game.detonate_barrel(barrel1)

        self.assertFalse(barrel1.active)
        self.assertFalse(barrel2.active)
        self.assertFalse(bandit.active)
        self.assertEqual(game.kills, 3)
        self.assertEqual(game.score, 300)

    def test_11_red_barrel_mega_explosion_wipes_field(self):
        """Verify red barrel (roll_b) triggers mega explosion and wipes out all enemies."""
        game, scope = self._create_game()
        game.phase = "playing"
        BanditEntity = scope["BanditEntity"]

        red_barrel = BanditEntity(BanditEntity.TYPE_BARREL_RED, lane=1, speed=120.0)
        red_barrel.progress = 500.0
        bandit1 = BanditEntity(BanditEntity.TYPE_REGULAR, lane=0, speed=120.0)
        bandit1.progress = 100.0  # far away
        bandit2 = BanditEntity(BanditEntity.TYPE_FAST, lane=5, speed=420.0)
        bandit2.progress = 1200.0  # far away on different lane

        game.entities.extend([red_barrel, bandit1, bandit2])
        game.detonate_barrel(red_barrel)

        self.assertFalse(red_barrel.active)
        self.assertFalse(bandit1.active)
        self.assertFalse(bandit2.active)
        self.assertEqual(game.kills, 3)
        self.assertEqual(game.score, 300)
        mega_exps = [exp for exp in game.explosions if exp.eff_type == "mega"]
        self.assertTrue(len(mega_exps) > 0, "Mega explosion must be created by red barrel")

    def test_12_defense_line_breach_and_defeat_animation_advancement(self):
        """Verify bandit breach triggers game_over and defeat animation advances smoothly."""
        game, scope = self._create_game()
        game.phase = "playing"
        BanditEntity = scope["BanditEntity"]

        bandit = BanditEntity(BanditEntity.TYPE_REGULAR, lane=2, speed=500.0)
        bandit.progress = 1410.0
        game.entities.append(bandit)

        game.tick(0.033)  # Progress exceeds 1411.0
        self.assertEqual(game.phase, "game_over")
        self.assertFalse(game.victory)

        # Tick during game_over and verify lina_anim_timer advances and doesn't get stuck!
        initial_timer = game.lina_anim_timer
        game.tick(0.05)
        self.assertGreater(game.lina_anim_timer, initial_timer, "Defeat animation timer must advance!")
        self.assertIn("lina/idle_down/", game.lina_sprite)

        # Tick until end of game_over and verify it freezes on frame_04 and stays in ended phase!
        for _ in range(80):
            game.tick(0.05)
        self.assertEqual(game.phase, "ended")
        self.assertIn("lina/idle_down/frame_04.png", game.lina_sprite)
    def test_13_game_clear_victory_and_time_bonus(self):
        """Verify surviving 99 seconds with line intact triggers game_clear with Time Bonus."""
        game, _ = self._create_game()
        game.phase = "playing"
        game.time_left = 0.05
        game.kills = 15
        game.score = 1500
        game.tick(0.10)
        self.assertEqual(game.phase, "game_clear")
        self.assertTrue(game.victory)
        self.assertTrue(game.time_bonus)

    def test_14_difficulty_speed_tables(self):
        """Verify 10 phases of speed tables and enemy caps."""
        game, _ = self._create_game()
        self.assertEqual(len(game.SPEED_TABLE_STANDARD), 10)
        game.time_left = 95.0
        self.assertEqual(game.get_phase_index(), 0)
        game.time_left = 5.0
        self.assertEqual(game.get_phase_index(), 9)

        self.assertLess(game.SPEED_TABLE_STANDARD[0], game.SPEED_TABLE_STANDARD[9])
        self.assertLess(game.SPEED_TABLE_FAST[0], game.SPEED_TABLE_FAST[9])
        self.assertLess(game.MAX_ENEMIES_TABLE[0], game.MAX_ENEMIES_TABLE[9])

    def test_15_barrel_alignment_and_banner_bounds(self):
        """Verify barrel Y-alignment with lane ground and modest Game Over banner size."""
        self.assertIn("ey + 56", self.rpy_text)
        self.assertNotIn('add Transform("images/minigame_bandit/ui/banners/banner_game_over.png", zoom=2.6', self.rpy_text)
        self.assertIn('add "images/minigame_bandit/ui/banners/banner_game_over.png":', self.rpy_text)

    def test_16_sprite_integrity(self):
        """Verify character and barrel sprites are valid RGBA images with correct dimensions."""
        with Image.open(RENPY_GAME_DIR / "images" / "minigame_bandit" / "bandits" / "bandit_1" / "run" / "frame_00.png") as b_bandit:
            self.assertEqual(b_bandit.size, (168, 224))
            self.assertEqual(b_bandit.mode, "RGBA")

        with Image.open(RENPY_GAME_DIR / "images" / "minigame_bandit" / "barrels" / "roll_a" / "frame_00.png") as b_barrel:
            self.assertEqual(b_barrel.size, (168, 224))
            self.assertEqual(b_barrel.mode, "RGBA")

    def test_17_z_ordering_perspective(self):
        """Verify lower bandit on screen is drawn after upper bandit (overlaps in front)."""
        game, scope = self._create_game()
        game.phase = "playing"
        BanditEntity = scope["BanditEntity"]

        b_upper = BanditEntity(BanditEntity.TYPE_REGULAR, lane=0, speed=120.0)
        b_upper.progress = 600.0
        b_lower = BanditEntity(BanditEntity.TYPE_REGULAR, lane=3, speed=120.0)
        b_lower.progress = 600.0

        game.entities = [b_lower, b_upper]
        sorted_objects = game.get_sorted_render_objects()

        # Find indices in sorted_objects
        idx_upper = next(i for i, obj in enumerate(sorted_objects) if obj["y"] == game.get_entity_screen_pos(0, 600.0)[1])
        idx_lower = next(i for i, obj in enumerate(sorted_objects) if obj["y"] == game.get_entity_screen_pos(3, 600.0)[1])

        self.assertLess(idx_upper, idx_lower, "Upper bandit (smaller Y) must be drawn BEFORE lower bandit (larger Y) so lower bandit overlaps in front!")

if __name__ == "__main__":
    unittest.main()
