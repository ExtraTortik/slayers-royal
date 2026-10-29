import math
import random


class SlotMachineGame:
    """Authentic Slayers Royal (PS1) Slot Machine Game Logic for Python / Ren'Py.

    Reverse-engineered from PS1 MIPS disassembly (0x800568FA / OPT.UNT Entry 218).
    Supports independent reel braking, authentic paytable evaluation, continuous
    physical scrolling with magnetic notch snapping, coin particle physics,
    and multiple play modes (limited tokens vs unlimited).
    """

    # --------------------------------------------------------------------------
    # 1. Reel Symbols (0..6)
    # --------------------------------------------------------------------------
    SYMBOL_SYLPHIEL = 0
    SYMBOL_LINA = 1
    SYMBOL_LARK = 2
    SYMBOL_NAGA = 3
    SYMBOL_AMELIA = 4
    SYMBOL_GOURRY = 5
    SYMBOL_ZELGADIS = 6

    SYMBOL_NAMES = [
        "sylphiel",  # 0
        "lina",      # 1
        "lark",      # 2
        "naga",      # 3
        "amelia",    # 4
        "gourry",    # 5
        "zelgadis",  # 6
    ]

    SYMBOLS = {idx: name for idx, name in enumerate(SYMBOL_NAMES)}

    # --------------------------------------------------------------------------
    # Reel Geometry and Physics Constants
    # --------------------------------------------------------------------------
    SYMBOL_HEIGHT = 40.0  # Height of one symbol in pixels
    STRIP_LENGTH = 21     # Exact symbol count per reel strip
    TOTAL_REEL_HEIGHT = STRIP_LENGTH * SYMBOL_HEIGHT  # 840.0 px (loop boundary)

    DEFAULT_SPEED = 600.0         # Initial spinning speed in px/s
    DEFAULT_DECELERATION = 850.0  # Braking deceleration in px/s^2

    # Balanced 21-symbol strips for each of the 3 reels:
    # Rare symbols (Lina=1, Naga=3) appear 1-2 times.
    # Frequent symbols (Sylphiel=0, Lark=2, Amelia=4, Gourry=5, Zelgadis=6) appear 3-4 times.
    # No duplicate symbols are placed consecutively (including wraparound).
    DEFAULT_STRIPS = [
        # Reel 0 (Square): Lina:1, Naga:2, Sylphiel:4, Lark:3, Amelia:4, Gourry:3, Zelgadis:4 (Total: 21)
        [1, 4, 0, 6, 2, 5, 3, 0, 4, 6, 2, 5, 4, 0, 6, 3, 2, 5, 4, 0, 6],
        # Reel 1 (Cross):  Lina:2, Naga:1, Sylphiel:4, Lark:4, Amelia:3, Gourry:3, Zelgadis:4 (Total: 21)
        [3, 6, 0, 2, 4, 5, 1, 6, 0, 2, 5, 4, 6, 0, 2, 1, 5, 4, 6, 0, 2],
        # Reel 2 (Circle): Lina:1, Naga:2, Sylphiel:3, Lark:4, Amelia:4, Gourry:4, Zelgadis:3 (Total: 21)
        [5, 0, 2, 6, 4, 1, 5, 2, 3, 4, 0, 6, 5, 2, 4, 0, 3, 6, 5, 2, 4],
    ]

    class Reel:
        """Physical model of a single slot reel with continuous scrolling and magnetic snapping."""

        def __init__(
            self,
            strip: list[int],
            initial_speed: float = 600.0,
            deceleration: float = 850.0,
            symbol_height: float = 40.0,
        ):
            self.strip = list(strip)
            self.strip_len = len(self.strip)
            self.symbol_height = float(symbol_height)
            self.total_height = float(self.strip_len * self.symbol_height)
            self.initial_speed = float(initial_speed)
            self.deceleration = float(deceleration)

            self.pos_y = 0.0
            self.speed = 0.0
            self.state = "stopped"  # "stopped", "spinning", "stopping"
            self.distance_remaining = 0.0
            self.target_symbol_index = 0

        def start_spin(self):
            """Begin continuous scrolling at nominal speed."""
            self.state = "spinning"
            self.speed = self.initial_speed
            self.distance_remaining = 0.0

        def stop(self):
            """Initiate smooth deceleration and calculate exact landing target on payline."""
            if self.state != "spinning":
                return
            self.state = "stopping"

            # Physics stopping distance: S = v^2 / (2 * a)
            nominal_dist = (self.speed ** 2) / (2.0 * self.deceleration)
            min_symbols = 4  # Minimum travel distance for visual realism
            steps = max(min_symbols, math.ceil(nominal_dist / self.symbol_height))

            current_idx = int(round(self.pos_y / self.symbol_height)) % self.strip_len
            self.target_symbol_index = (current_idx + steps) % self.strip_len

            # Exact pixel distance to center of target symbol on payline
            target_pos = self.target_symbol_index * self.symbol_height
            fwd_dist = (target_pos - self.pos_y) % self.total_height
            while fwd_dist < (steps - 0.5) * self.symbol_height:
                fwd_dist += self.total_height

            self.distance_remaining = fwd_dist

        def tick(self, dt: float):
            """Update scroll position, deceleration curve, and magnetic snap."""
            if self.state == "stopped":
                return

            if self.state == "spinning":
                self.pos_y = (self.pos_y + self.speed * dt) % self.total_height

            elif self.state == "stopping":
                if self.distance_remaining <= 0.5:
                    self.pos_y = (self.target_symbol_index * self.symbol_height) % self.total_height
                    self.speed = 0.0
                    self.state = "stopped"
                    self.distance_remaining = 0.0
                    return

                # Smooth deceleration curve with magnetic spring pull towards notch
                if self.distance_remaining > 25.0:
                    ideal_speed = math.sqrt(2.0 * self.deceleration * self.distance_remaining)
                    self.speed = min(self.speed, ideal_speed)
                    self.speed = max(self.speed - self.deceleration * dt, ideal_speed * 0.9)
                    move = min(self.speed * dt, self.distance_remaining)
                else:
                    # Magnetic notch lock: smooth exponential attraction to symbol center
                    magnetic_speed = max(30.0, self.distance_remaining * 8.0)
                    self.speed = magnetic_speed
                    move = min(magnetic_speed * dt, self.distance_remaining)

                self.pos_y = (self.pos_y + move) % self.total_height
                self.distance_remaining -= move

                # Strict snap when arriving at the center of the payline
                if self.distance_remaining <= 0.5 or (self.distance_remaining < 2.0 and self.speed < 10.0):
                    self.pos_y = (self.target_symbol_index * self.symbol_height) % self.total_height
                    self.speed = 0.0
                    self.state = "stopped"
                    self.distance_remaining = 0.0

        @property
        def current_symbol_index(self) -> int:
            """Index (0..20) of the symbol currently aligned with the payline."""
            return int(round(self.pos_y / self.symbol_height)) % self.strip_len

        @property
        def current_symbol(self) -> int:
            """Symbol ID (0..6) centered on the payline."""
            return self.strip[self.current_symbol_index]

    # --------------------------------------------------------------------------
    # Initialization and State Management
    # --------------------------------------------------------------------------
    def __init__(
        self,
        unlimited_mode: bool = False,
        tokens: int = 10,
        inn_chips: int | None = None,
        strips: list[list[int]] | None = None,
        speed: float = 600.0,
        deceleration: float = 850.0,
    ):
        self.unlimited_mode = bool(unlimited_mode)
        self.tokens = int(inn_chips if inn_chips is not None else tokens)
        self.current_win = 0
        self.total_gold = 0

        # Game phases:
        # "ready" -> "spinning" -> "stopping" -> "evaluating" -> "payout" -> "game_over" / "replay_ready"
        self.phase = "game_over" if (not self.unlimited_mode and self.tokens <= 0) else "ready"

        # Instantiate 3 reels
        reel_strips = strips if strips is not None else self.DEFAULT_STRIPS
        self.reels = [
            self.Reel(
                strip=reel_strips[i],
                initial_speed=speed,
                deceleration=deceleration,
                symbol_height=self.SYMBOL_HEIGHT,
            )
            for i in range(3)
        ]

        # Win results
        self.is_jackpot = False
        self.is_replay = False
        self.win_name = "none"
        self.last_combination: tuple[int, int, int] = (0, 0, 0)

        # Timers
        self.payout_timer = 0.0
        self.payout_duration = 3.0
        self.eval_timer = 0.0
        self.eval_duration = 0.20  # Brief authentic suspense before win declaration

        # Visual FX & particles
        self.coin_particles: list[dict] = []
        self.star_active = False
        self.star_frame = 0       # 0..15 frames
        self.star_angle = 0.0     # Degrees
        self.star_timer = 0.0
        self.victory_sound = False

    @property
    def inn_chips(self) -> int:
        """Alias for tokens counter (inn chips in Slayers Royal)."""
        return self.tokens

    @inn_chips.setter
    def inn_chips(self, value: int):
        self.tokens = int(value)

    @property
    def payline_symbols(self) -> tuple[int, int, int]:
        """Tuple of the 3 symbol IDs currently aligned on the payline."""
        return (
            self.reels[0].current_symbol,
            self.reels[1].current_symbol,
            self.reels[2].current_symbol,
        )

    @property
    def payline_symbol_names(self) -> tuple[str, str, str]:
        """Tuple of symbol name strings currently aligned on the payline."""
        syms = self.payline_symbols
        return (
            self.SYMBOL_NAMES[syms[0]],
            self.SYMBOL_NAMES[syms[1]],
            self.SYMBOL_NAMES[syms[2]],
        )

    @property
    def can_spin(self) -> bool:
        """True if the machine is ready to accept a spin/start command."""
        if self.phase == "replay_ready":
            return True
        if self.phase == "ready":
            return self.unlimited_mode or (self.tokens > 0)
        return False

    @property
    def is_spinning(self) -> bool:
        """True if any reel is actively spinning or decelerating."""
        return any(r.state in ("spinning", "stopping") for r in self.reels)

    # --------------------------------------------------------------------------
    # Player Controls
    # --------------------------------------------------------------------------
    def start_spin(self) -> bool:
        """Start spinning all 3 reels. Deducts 1 token unless in unlimited or replay mode."""
        if self.phase not in ("ready", "replay_ready"):
            return False

        # Token handling
        if self.phase == "replay_ready":
            # Free game replay! Does not consume a token
            self.is_replay = False
        else:
            if not self.unlimited_mode:
                if self.tokens <= 0:
                    self.phase = "game_over"
                    return False
                self.tokens -= 1

        # Reset per-round win states
        self.current_win = 0
        self.is_jackpot = False
        self.win_name = "none"
        self.victory_sound = False
        self.star_active = False
        self.coin_particles.clear()

        # Spin all 3 reels
        for reel in self.reels:
            reel.start_spin()

        self.phase = "spinning"
        return True

    def stop_reel(self, index: int) -> bool:
        """Independently stop reel 0 (Square), reel 1 (Cross), or reel 2 (Circle)."""
        if not (0 <= index < 3):
            return False

        reel = self.reels[index]
        if reel.state == "spinning":
            reel.stop()
            self.phase = "stopping"
            return True
        return False

    def press_square(self) -> bool:
        """PlayStation Square (Квадрат) button: Stop Reel 0."""
        return self.stop_reel(0)

    def press_cross(self) -> bool:
        """PlayStation Cross (Крест) button: Stop Reel 1."""
        return self.stop_reel(1)

    def press_circle(self) -> bool:
        """PlayStation Circle (Круг) button: Stop Reel 2."""
        return self.stop_reel(2)

    def press_start(self) -> bool:
        """PlayStation Start button: Start spin or trigger replay."""
        return self.start_spin()

    def stop_all(self):
        """Emergency or auto-stop for all active reels."""
        for i in range(3):
            self.stop_reel(i)

    def handle_input(self, event_or_btn: str | int) -> bool:
        """Unified input handler for Ren'Py / gamepad / keyboard bindings."""
        btn = str(event_or_btn).lower().strip()
        if btn in ("start", "btn_start", "enter", "space", "k_return", "k_space"):
            return self.press_start()
        elif btn in ("square", "btn_square", "k_a", "k_1", "0", "sq"):
            return self.press_square()
        elif btn in ("cross", "btn_cross", "k_s", "k_2", "1", "cr"):
            return self.press_cross()
        elif btn in ("circle", "btn_circle", "k_d", "k_3", "2", "ci"):
            return self.press_circle()
        return False

    # --------------------------------------------------------------------------
    # 2. Authentic Paytable Evaluation (MIPS 0x800568FA / OPT.UNT Entry 218)
    # --------------------------------------------------------------------------
    def evaluate_payline(self, symbols: tuple[int, int, int]) -> dict:
        """Evaluate a 3-symbol payline combination according to PS1 ROM rules.

        Combinations:
        - 3 Lina (1, 1, 1): 2000 gold, jackpot
        - 3 Naga (3, 3, 3): 1000 gold
        - 3 Gourry (5, 5, 5): 500 gold
        - 3 Zelgadis (6, 6, 6): 200 gold + replay
        - 3 Amelia (4, 4, 4): 100 gold + replay
        - 2 Zelgadis + Lark (any order): 100 gold + replay
        - 2 Amelia + Lark (any order): 50 gold + replay
        - 3 Sylphiel (0, 0, 0) or 2 Sylphiel + Lark (any order): replay (free game)
        """
        s = tuple(symbols)

        # 3 Lina (1, 1, 1): 2000 gold, jackpot
        if s == (self.SYMBOL_LINA, self.SYMBOL_LINA, self.SYMBOL_LINA):
            return {
                "name": "3 Lina (Jackpot)",
                "gold": 2000,
                "replay": False,
                "jackpot": True,
            }

        # 3 Naga (3, 3, 3): 1000 gold
        if s == (self.SYMBOL_NAGA, self.SYMBOL_NAGA, self.SYMBOL_NAGA):
            return {
                "name": "3 Naga",
                "gold": 1000,
                "replay": False,
                "jackpot": False,
            }

        # 3 Gourry (5, 5, 5): 500 gold
        if s == (self.SYMBOL_GOURRY, self.SYMBOL_GOURRY, self.SYMBOL_GOURRY):
            return {
                "name": "3 Gourry",
                "gold": 500,
                "replay": False,
                "jackpot": False,
            }

        # 3 Zelgadis (6, 6, 6): 200 gold + replay
        if s == (self.SYMBOL_ZELGADIS, self.SYMBOL_ZELGADIS, self.SYMBOL_ZELGADIS):
            return {
                "name": "3 Zelgadis",
                "gold": 200,
                "replay": True,
                "jackpot": False,
            }

        # 3 Amelia (4, 4, 4): 100 gold + replay
        if s == (self.SYMBOL_AMELIA, self.SYMBOL_AMELIA, self.SYMBOL_AMELIA):
            return {
                "name": "3 Amelia",
                "gold": 100,
                "replay": True,
                "jackpot": False,
            }

        # 2 Zelgadis + Lark (any order): 100 gold + replay
        if s.count(self.SYMBOL_ZELGADIS) == 2 and s.count(self.SYMBOL_LARK) == 1:
            return {
                "name": "2 Zelgadis + Lark",
                "gold": 100,
                "replay": True,
                "jackpot": False,
            }

        # 2 Amelia + Lark (any order): 50 gold + replay
        if s.count(self.SYMBOL_AMELIA) == 2 and s.count(self.SYMBOL_LARK) == 1:
            return {
                "name": "2 Amelia + Lark",
                "gold": 50,
                "replay": True,
                "jackpot": False,
            }

        # 3 Sylphiel (0, 0, 0): replay (free game)
        if s == (self.SYMBOL_SYLPHIEL, self.SYMBOL_SYLPHIEL, self.SYMBOL_SYLPHIEL):
            return {
                "name": "3 Sylphiel",
                "gold": 0,
                "replay": True,
                "jackpot": False,
            }

        # 2 Sylphiel + Lark (any order): replay (free game)
        if s.count(self.SYMBOL_SYLPHIEL) == 2 and s.count(self.SYMBOL_LARK) == 1:
            return {
                "name": "2 Sylphiel + Lark",
                "gold": 0,
                "replay": True,
                "jackpot": False,
            }

        # No winning combination
        return {
            "name": "none",
            "gold": 0,
            "replay": False,
            "jackpot": False,
        }

    # --------------------------------------------------------------------------
    # 6. Coin Particle Physics & Win FX
    # --------------------------------------------------------------------------
    def _spawn_coins(self, gold: int, jackpot: bool):
        """Generate coin particle bursts based on win amount."""
        self.coin_particles.clear()
        if gold <= 0:
            return

        if jackpot:
            count = 55
            p_gold, p_silver = 0.75, 0.20
        elif gold >= 1000:
            count = 42
            p_gold, p_silver = 0.60, 0.30
        elif gold >= 500:
            count = 32
            p_gold, p_silver = 0.40, 0.45
        elif gold >= 100:
            count = 22
            p_gold, p_silver = 0.20, 0.50
        else:  # 50 gold
            count = 14
            p_gold, p_silver = 0.10, 0.35

        for _ in range(count):
            r = random.random()
            if r < p_gold:
                c_type = "gold"
            elif r < p_gold + p_silver:
                c_type = "silver"
            else:
                c_type = "bronze"

            # Center hopper area of the 320x224 screen
            x = 160.0 + random.uniform(-65.0, 65.0)
            y = 105.0 + random.uniform(-20.0, 20.0)
            vx = random.uniform(-140.0, 140.0)
            vy = random.uniform(-280.0, -90.0)  # Upward burst trajectory
            bounce = random.uniform(0.50, 0.72)

            self.coin_particles.append({
                "x": x,
                "y": y,
                "vx": vx,
                "vy": vy,
                "bounce": bounce,
                "type": c_type,
            })

    def _process_evaluation(self):
        """Execute payline evaluation and branch game phase."""
        syms = self.payline_symbols
        self.last_combination = syms
        result = self.evaluate_payline(syms)

        self.win_name = result["name"]
        gold = result["gold"]
        replay = result["replay"]
        jackpot = result["jackpot"]

        self.current_win = gold
        self.total_gold += gold
        self.is_jackpot = jackpot
        self.is_replay = replay

        if gold > 0:
            # Payout win animation phase
            self.phase = "payout"
            self.payout_timer = 0.0
            self.payout_duration = 3.5 if jackpot else 2.5
            self.star_active = True
            self.star_frame = 0
            self.star_angle = 0.0
            self.victory_sound = True
            self._spawn_coins(gold, jackpot)

        elif replay:
            # Replay (free spin) awarded with no direct gold
            self.phase = "replay_ready"
            self.star_active = True
            self.victory_sound = True

        else:
            # Loss
            if not self.unlimited_mode and self.tokens <= 0:
                self.phase = "game_over"
            else:
                self.phase = "ready"

    def skip_payout(self):
        """Fast-forward / dismiss the payout animation immediately."""
        if self.phase == "payout":
            self.star_active = False
            self.victory_sound = False
            if self.is_replay:
                self.phase = "replay_ready"
            elif not self.unlimited_mode and self.tokens <= 0:
                self.phase = "game_over"
            else:
                self.phase = "ready"

    # --------------------------------------------------------------------------
    # Main Loop Tick
    # --------------------------------------------------------------------------
    def tick(self, dt: float):
        """Update game loop, physics, animations, and particles."""
        # 1. Update individual reels
        for reel in self.reels:
            reel.tick(dt)

        # 2. Check transition from spinning/stopping -> evaluating
        if self.phase in ("spinning", "stopping"):
            if all(r.state == "stopped" for r in self.reels):
                self.phase = "evaluating"
                self.eval_timer = 0.0

        # 3. Handle evaluating phase (short suspense before payout)
        elif self.phase == "evaluating":
            self.eval_timer += dt
            if self.eval_timer >= self.eval_duration:
                self._process_evaluation()

        # 4. Handle payout animation phase
        elif self.phase == "payout":
            self.payout_timer += dt

            # Star rotation & frame animation (16 frames at 16 fps, 180 deg/s rotation)
            self.star_timer += dt
            if self.star_timer >= 0.0625:  # 1/16s per frame
                self.star_timer -= 0.0625
                self.star_frame = (self.star_frame + 1) % 16
            self.star_angle = (self.star_angle + 180.0 * dt) % 360.0

            if self.payout_timer >= self.payout_duration:
                self.skip_payout()

        # 5. Coin particles 2D gravity & bounce physics
        if self.coin_particles:
            gravity = 750.0  # px/s^2
            floor_y = 212.0  # Just above the cabinet rim on 320x224 PS1 screen
            for coin in self.coin_particles:
                coin["vy"] += gravity * dt
                coin["x"] += coin["vx"] * dt
                coin["y"] += coin["vy"] * dt

                # Floor collision and dampening
                if coin["y"] >= floor_y:
                    coin["y"] = floor_y
                    coin["vy"] = -coin["vy"] * coin["bounce"]
                    coin["vx"] *= 0.78  # Floor friction
                    if abs(coin["vy"]) < 30.0:
                        coin["vy"] = 0.0

                # Screen boundary bounces
                if coin["x"] < 8.0:
                    coin["x"] = 8.0
                    coin["vx"] = -coin["vx"] * 0.5
                elif coin["x"] > 312.0:
                    coin["x"] = 312.0
                    coin["vx"] = -coin["vx"] * 0.5

    # --------------------------------------------------------------------------
    # Rendering Helpers
    # --------------------------------------------------------------------------
    def get_visible_symbols(self, reel_index: int) -> list[int]:
        """Return [symbol_above, symbol_center, symbol_below] for 3 visible rows."""
        if not (0 <= reel_index < 3):
            return []
        reel = self.reels[reel_index]
        idx = reel.current_symbol_index
        n = reel.strip_len
        above = reel.strip[(idx - 1) % n]
        center = reel.strip[idx]
        below = reel.strip[(idx + 1) % n]
        return [above, center, below]

    def add_tokens(self, count: int):
        """Add tokens to current pool and revive from game_over if needed."""
        self.tokens += int(count)
        if self.phase == "game_over" and self.tokens > 0:
            self.phase = "ready"

    def reset(self, tokens: int = 10, reset_gold: bool = False):
        """Reset machine state for a new game session."""
        self.tokens = int(tokens)
        self.current_win = 0
        if reset_gold:
            self.total_gold = 0
        self.is_jackpot = False
        self.is_replay = False
        self.win_name = "none"
        self.star_active = False
        self.victory_sound = False
        self.coin_particles.clear()
        for reel in self.reels:
            reel.state = "stopped"
            reel.speed = 0.0
            reel.pos_y = 0.0
        self.phase = "game_over" if (not self.unlimited_mode and self.tokens <= 0) else "ready"