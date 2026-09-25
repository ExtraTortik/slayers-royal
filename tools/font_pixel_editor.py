#!/usr/bin/env python3
"""Slayers Royal (PS1) — Dedicated Browser-based Pixel Font Editor.

Allows interactive inspection and editing of each of the 420 two-letter compact glyphs
in a 16x16 pixel canvas in the browser, saving changes directly into compact_font_atlas_raw.png.

Features:
- Complete self-contained Single Page Application (SPA) with sleek dark theme and PS1 retro aesthetic.
- 16x16 interactive drawing grid (~28px/cell) with pencil, eraser, shift, clear, invert, undo/redo.
- Alignment guides: Baseline (y=10, red), Waistline (y=4, blue), Center (x=8, gray).
- Real-time previews at 1X, 2X, and 4X with authentic drop-shadow and gold/white color toggle.
- Live in-game 3-line PS1 dialogue simulator that updates in real time as matching tokens are drawn.
- Token gallery with instant search, filters (All, Edited, Common >200 uses), and keyboard navigation.
- Atomic file writes directly to compact_font_atlas_raw.png to prevent file corruption.
- Background story build runner (./build.sh --story).
- Standard library Python (http.server, urllib.parse, json, socketserver) + PIL (Pillow).
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

# Repository root directory
REPO_ROOT = Path(__file__).resolve().parent.parent
ATLAS_PATH = REPO_ROOT / "compact_font_atlas_raw.png"

# Default baked list of 420 compact tokens and their scene 0x03E frequencies
DEFAULT_TOKENS: list[tuple[str, int]] = [
    ('то', 401), (', ', 329), ('о ', 256), (' в', 252), ('на', 249),
    ('ст', 243), (' н', 226), ('но', 222), ('ть', 216), ('е ', 215),
    (' т', 206), ('не', 206), ('по', 206), ('та', 199), ('ра', 188),
    ('ак', 187), ('ли', 170), ('а ', 161), ('пр', 158), ('го', 157),
    ('ел', 157), ('ро', 157), ('де', 153), ('ко', 148), ('ов', 148),
    (' с', 145), ('да', 139), ('ни', 136), ('во', 135), ('те', 134),
    ('ла', 132), ('ат', 131), ('ос', 131), ('ит', 130), ('ка', 129),
    ('и ', 128), ('ал', 124), ('же', 123), ('ль', 121), (' п', 119),
    ('ва', 118), ('ин', 118), ('ор', 118), ('ам', 115), ('ет', 115),
    ('ри', 115), ('ен', 111), ('ил', 109), ('ы ', 109), ('ес', 108),
    ('от', 107), ('чт', 104), ('од', 103), ('я ', 102), ('за', 98),
    ('ся', 97), ('ь ', 97), (' ч', 96), ('ог', 96), (' и', 95),
    ('ди', 94), ('ас', 93), ('у ', 92), ('ол', 90), (' м', 87),
    ('ве', 87), ('ер', 87), ('м ', 87), ('ло', 86), ('эт', 85),
    ('ти', 83), ('а,', 80), ('ав', 80), ('ем', 79), ('ма', 78),
    ('о,', 78), ('сл', 78), (' к', 76), ('ом', 76), (' д', 75),
    ('об', 75), ('он', 75), ('Ли', 73), ('че', 73), ('ад', 71),
    ('ре', 71), (' э', 68), ('вы', 68), ('мо', 68), ('ож', 68),
    (' б', 64), ('ме', 64), ('к ', 63), (' Л', 62), (' ж', 62),
    ('бы', 62), ('ой', 62), ('вс', 61), ('сь', 61), ('уд', 61),
    ('По', 60), ('ис', 60), ('ту', 60), (' з', 59), ('ар', 59),
    (' я', 58), ('аз', 58), ('в ', 57), ('ну', 57), ('оч', 57),
    (' е', 54), ('чи', 54), ('Ну', 53), ('ск', 53), ('т ', 53),
    ('ты', 53), ('ле', 52), ('зн', 50), (' у', 49), ('ай', 49),
    ('се', 49), ('хо', 49), ('шь', 48), ('… ', 48), ('-т', 47),
    ('ки', 47), ('ое', 47), (' о', 46), ('ае', 46), ('до', 46),
    ('из', 46), ('сп', 46), ('ут', 46), ('Ла', 45), ('ше', 45),
    ('ь?', 45), ('ку', 44), ('лу', 44), ('рк', 44), ('гд', 43),
    ('ег', 43), ('им', 43), ('со', 43), ('ь,', 43), ('ны', 42),
    ('у,', 42), ('? ', 41), ('а…', 41), ('ём', 41), ('А ', 40),
    ('ан', 40), ('ви', 40), ('ще', 40), (' г', 39), ('аг', 39),
    ('ду', 39), ('Да', 38), ('е…', 38), ('ед', 37), ('ия', 37),
    ('о.', 37), ('а!', 36), ('аж', 36), ('о-', 36), ('мы', 35),
    ('о…', 35), ('тв', 35), ('тс', 35), ('а.', 34), ('дн', 34),
    ('са', 34), ('га', 33), ('еб', 33), ('еш', 33), ('ьд', 33),
    (' л', 32), ('Я ', 32), ('бе', 32), ('бу', 32), ('ги', 32),
    ('е,', 32), ('ие', 32), ('ня', 32), ('сё', 32), ('тр', 32),
    ('х ', 32), ('бо', 31), ('дё', 31), ('о?', 31), ('рн', 31),
    ('т,', 31), ('уж', 31), ('ё ', 31), ('ей', 30), ('оз', 30),
    ('ош', 30), ('ру', 30), ('ча', 30), ('Не', 29), ('е?', 29),
    ('ев', 29), ('жн', 29), ('си', 29), ('ьс', 29), ('То', 28),
    ('е.', 28), ('ещ', 28), ('жа', 28), ('и,', 28), ('й,', 28),
    ('ок', 28), ('ур', 28), ('ую', 28), ('чн', 28), (' р', 27),
    ('За', 27), ('а?', 27), ('ик', 27), ('йт', 27), ('кр', 27),
    ('ля', 27), ('пе', 27), ('уч', 27), ('ыл', 27), ('ь…', 27),
    ('ят', 27), ('аш', 26), ('дь', 26), ('ич', 26), ('йд', 26),
    ('м,', 26), ('мн', 26), ('нн', 26), ('нь', 26), ('па', 26),
    ('с ', 26), ('сн', 26), ('ум', 26), ('ь.', 26), ('я,', 26),
    (' х', 25), ('! ', 25), ('. ', 25), ('аю', 25), ('зд', 25),
    ('Пр', 24), ('зв', 24), ('их', 24), ('иш', 24), ('й ', 24),
    ('лс', 24), ('му', 24), ('ус', 24), ('шл', 24), (' Н', 23),
    ('Зе', 23), ('Ка', 23), ('ив', 23), ('иг', 23), ('ми', 23),
    ('пи', 23), ('ьк', 23), ('я…', 23), ('Га', 22), ('ау', 22),
    ('ач', 22), ('ек', 22), ('и.', 22), ('щё', 22), (' —', 21),
    ('И ', 21), ('Чт', 21), ('Эт', 21), ('аб', 21), ('вд', 21),
    ('вр', 21), ('ее', 21), ('оп', 21), ('сс', 21), ('т.', 21),
    ('тн', 21), ('хр', 21), ('ша', 21), ('ых', 21), ('ю ', 21),
    ('Ты', 20), ('ап', 20), ('зе', 20), ('иб', 20), ('л ', 20),
    ('м.', 20), ('ря', 20), ('ёт', 20), (' а', 19), ('Но', 19),
    ('Ра', 19), ('ая', 19), ('бр', 19), ('еч', 19), ('м?', 19),
    ('ры', 19), ('уп', 19), ('уш', 19), ('-э', 18), ('жи', 18),
    ('и…', 18), ('я.', 18), ('я?', 18), ('В ', 17), ('На', 17),
    ('вк', 17), ('вл', 17), ('гу', 17), ('жд', 17), ('ии', 17),
    ('иц', 17), ('лг', 17), ('о!', 17), ('пл', 17), ('рт', 17),
    ('ву', 16), ('ез', 16), ('ид', 16), ('м…', 16), ('ох', 16),
    ('це', 16), ('ьн', 16), ('-о', 15), ('Вы', 15), ('Ги', 15),
    ('Та', 15), ('Э-', 15), ('вн', 15), ('др', 15), ('е!', 15),
    ('з ', 15), ('у.', 15), ('ул', 15), ('ух', 15), ('ый', 15),
    ('ыш', 15), ('ь!', 15), ('— ', 15), (' А', 14), ('-н', 14),
    ('Во', 14), ('би', 14), ('бл', 14), ('бщ', 14), ('бя', 14),
    ('зр', 14), ('и!', 14), ('и?', 14), ('л!', 14), ('н ', 14),
    ('чё', 14), ('щи', 14), ('ыс', 14), ('ыт', 14), ('ют', 14),
    ('ащ', 13), ('зо', 13), ('ию', 13), ('кн', 13), ('рь', 13),
    ('с…', 13), ('ща', 13), ('ьш', 13), ('я!', 13), ('ящ', 13),
    (' Г', 12), (' З', 12), ('Се', 12), ('гр', 12), ('её', 12),
    ('жу', 12), ('йс', 12), ('лы', 12), ('мс', 12), ('нч', 12),
    ('см', 12), ('т?', 12), ('ши', 12), ('ье', 12), ('яд', 12),
    (' Э', 11), ('Бо', 11), ('вя', 11), ('гл', 11), ('ий', 11),
    ('йр', 11), ('к,', 11), ('к?', 11), ('м-', 11), ('нё', 11),
    ('ои', 11), ('оо', 11), ('оя', 11), ('тк', 11), ('у!', 11),
    ('ун', 11), (' Т', 10), (' Я', 10), ('-м', 10), ('Ко', 10),
    ('вз', 10), ('дк', 10), ('дл', 10), ('е-', 10), ('еп', 10),
    ('к…', 10), ('л,', 10), ('пу', 10), ('пы', 10), ('св', 10),
    ('т!', 10), ('уй', 10), ('ук', 10), ('у…', 10), ('хн', 10),
]


def load_tokens_metadata() -> list[dict[str, Any]]:
    """Loads token metadata, preferring dynamic extraction with fallback to baked list."""
    token_pairs: list[tuple[str, int]] = []
    try:
        sys.path.insert(0, str(REPO_ROOT / "tools"))
        from generate_compact_font_preview import get_scene_03e_tokens

        tokens, counts, _ = get_scene_03e_tokens(420)
        token_pairs = [(t, counts[t]) for t in tokens[:420]]
    except Exception:
        token_pairs = DEFAULT_TOKENS

    if len(token_pairs) < 420:
        token_pairs = DEFAULT_TOKENS

    meta: list[dict[str, Any]] = []
    for idx, (tok, count) in enumerate(token_pairs[:420]):
        col = idx % 16
        row = idx // 16
        meta.append({
            "index": idx,
            "token": tok,
            "count": count,
            "row": row,
            "col": col,
            "x": col * 16,
            "y": row * 16,
        })
    return meta


# ---------------------------------------------------------------------------
# Pixel / Tile Conversion Helpers
# ---------------------------------------------------------------------------

TEXT_COLOR = (216, 192, 144, 255)
SHADOW_COLOR = (16, 16, 16, 255)


def pixels_to_rgba_tile(pixels: list[list[int]]) -> Image.Image:
    """Converts a 16x16 1-bit matrix (0/1) to authentic PS1 styled RGBA tile with 1px drop-shadow."""
    tile = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    putpixel = tile.putpixel
    for y in range(16):
        for x in range(16):
            if pixels[y][x]:
                putpixel((x, y), TEXT_COLOR)
            elif x > 0 and y > 0 and pixels[y - 1][x - 1]:
                putpixel((x, y), SHADOW_COLOR)
    return tile


def rgba_tile_to_pixels(tile: Image.Image) -> list[list[int]]:
    """Extracts a 16x16 1-bit matrix (0/1) from an RGBA tile."""
    pixels: list[list[int]] = []
    getpixel = tile.getpixel
    for y in range(16):
        row: list[int] = []
        for x in range(16):
            r, g, b, a = getpixel((x, y))
            # Text pixel is opaque and bright (R > 50), whereas shadow is (16, 16, 16)
            row.append(1 if (a > 0 and r > 50) else 0)
        pixels.append(row)
    return pixels


# ---------------------------------------------------------------------------
# Atlas Manager
# ---------------------------------------------------------------------------


class AtlasManager:
    """Thread-safe manager for reading, caching, and atomically saving compact_font_atlas_raw.png."""

    def __init__(self, atlas_path: Path = ATLAS_PATH):
        self.atlas_path = atlas_path
        self.lock = threading.Lock()
        self.tokens_meta = load_tokens_metadata()
        self._ensure_atlas_exists()

    def _ensure_atlas_exists(self) -> None:
        """Ensures the 256x432 raw atlas exists; creates a blank one if missing."""
        with self.lock:
            if not self.atlas_path.exists():
                im = Image.new("RGBA", (256, 432), (0, 0, 0, 0))
                im.save(self.atlas_path, format="PNG")

    def get_tokens(self) -> list[dict[str, Any]]:
        return self.tokens_meta

    def get_tile(self, index: int) -> dict[str, Any]:
        """Extracts 16x16 pixels for tile at given index."""
        if not (0 <= index < 420):
            raise ValueError(f"Tile index {index} out of range (0..419)")

        meta = self.tokens_meta[index]
        col = meta["col"]
        row = meta["row"]

        with self.lock:
            with Image.open(self.atlas_path) as atlas:
                crop = atlas.crop((col * 16, row * 16, (col + 1) * 16, (row + 1) * 16))
                pixels = rgba_tile_to_pixels(crop)

        return {
            "index": index,
            "token": meta["token"],
            "count": meta["count"],
            "row": row,
            "col": col,
            "x": col * 16,
            "y": row * 16,
            "pixels": pixels,
        }

    def save_tile(self, index: int, pixels: list[list[int]]) -> None:
        """Saves a single 16x16 tile atomically to the atlas."""
        self.save_all({index: pixels})

    def save_all(self, tiles: dict[int, list[list[int]]]) -> int:
        """Saves multiple 16x16 tiles atomically to the atlas in a single write operation."""
        if not tiles:
            return 0

        # Validate all tiles first
        validated: dict[int, Image.Image] = {}
        for idx_raw, px in tiles.items():
            try:
                idx = int(idx_raw)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid tile index: {idx_raw}")

            if not (0 <= idx < 420):
                raise ValueError(f"Tile index {idx} out of range (0..419)")

            if not isinstance(px, list) or len(px) != 16:
                raise ValueError(f"Tile {idx} pixels must be a 16-row list")
            for r, row in enumerate(px):
                if not isinstance(row, list) or len(row) != 16:
                    raise ValueError(f"Tile {idx} row {r} must have length 16")

            tile_im = pixels_to_rgba_tile(px)
            validated[idx] = tile_im

        with self.lock:
            with Image.open(self.atlas_path) as atlas:
                if atlas.size[0] < 256 or atlas.size[1] < 432:
                    expanded = Image.new("RGBA", (max(atlas.size[0], 256), max(atlas.size[1], 432)), (0, 0, 0, 0))
                    expanded.paste(atlas, (0, 0))
                    atlas_im = expanded
                else:
                    atlas_im = atlas.copy()

            for idx, tile_im in validated.items():
                col = idx % 16
                row = idx // 16
                atlas_im.paste(tile_im, (col * 16, row * 16))

            # Atomic file write using temporary file in same directory
            temp_path = self.atlas_path.with_suffix(".tmp.png")
            atlas_im.save(temp_path, format="PNG")
            os.replace(temp_path, self.atlas_path)

        return len(validated)

    def get_atlas_bytes(self) -> bytes:
        """Returns raw PNG bytes of the current atlas."""
        with self.lock:
            return self.atlas_path.read_bytes()


# Global Atlas Manager instance
MANAGER = AtlasManager()

# Background rebuild tracking
REBUILD_LOCK = threading.Lock()
REBUILD_STATUS = {"running": False, "last_output": "", "last_success": True}


def run_rebuild_task() -> None:
    global REBUILD_STATUS
    with REBUILD_LOCK:
        REBUILD_STATUS["running"] = True
    try:
        res = subprocess.run(
            ["./build.sh", "--story"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=120,
        )
        with REBUILD_LOCK:
            REBUILD_STATUS["last_output"] = res.stdout
            REBUILD_STATUS["last_success"] = res.returncode == 0
    except Exception as exc:
        with REBUILD_LOCK:
            REBUILD_STATUS["last_output"] = f"Rebuild failed: {exc}"
            REBUILD_STATUS["last_success"] = False
    finally:
        with REBUILD_LOCK:
            REBUILD_STATUS["running"] = False


# ---------------------------------------------------------------------------
# HTTP Server Handler
# ---------------------------------------------------------------------------


class FontPixelEditorHandler(http.server.BaseHTTPRequestHandler):
    """HTTP handler implementing REST API and serving the Single Page Application."""

    def _send_json(self, status: int, data: Any) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _send_html(self, status: int, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_bytes(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            if path == "/":
                self._send_html(200, EMBEDDED_SPA_HTML)
                return

            if path == "/api/tokens":
                tokens = MANAGER.get_tokens()
                self._send_json(200, tokens)
                return

            if path.startswith("/api/tile/"):
                idx_str = path[len("/api/tile/"):]
                try:
                    idx = int(idx_str)
                except ValueError:
                    self._send_json(400, {"error": f"Invalid tile index: {idx_str!r}"})
                    return

                if not (0 <= idx < 420):
                    self._send_json(404, {"error": f"Tile index {idx} out of range (0..419)"})
                    return

                tile_data = MANAGER.get_tile(idx)
                self._send_json(200, tile_data)
                return

            if path == "/api/atlas.png":
                png_bytes = MANAGER.get_atlas_bytes()
                self._send_bytes(200, "image/png", png_bytes)
                return

            if path == "/api/rebuild/status":
                with REBUILD_LOCK:
                    self._send_json(200, dict(REBUILD_STATUS))
                return

            self._send_json(404, {"error": f"Endpoint {path} not found"})

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_len) if content_len > 0 else b""
            body: Any = {}
            if body_bytes:
                try:
                    body = json.loads(body_bytes.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    self._send_json(400, {"error": f"Invalid JSON payload: {exc}"})
                    return

            if path == "/api/save_tile":
                index = body.get("index")
                pixels = body.get("pixels")

                if index is None or pixels is None:
                    self._send_json(400, {"error": "Missing 'index' or 'pixels' field in payload"})
                    return

                try:
                    MANAGER.save_tile(int(index), pixels)
                    self._send_json(200, {"success": True, "index": int(index)})
                except ValueError as ve:
                    self._send_json(400, {"error": str(ve)})
                return

            if path == "/api/save_all":
                tiles = body.get("tiles")
                if not isinstance(tiles, dict):
                    self._send_json(400, {"error": "'tiles' field must be a dictionary mapping index to pixels"})
                    return

                try:
                    saved_count = MANAGER.save_all(tiles)
                    self._send_json(200, {"success": True, "saved_count": saved_count})
                except ValueError as ve:
                    self._send_json(400, {"error": str(ve)})
                return

            if path == "/api/rebuild":
                with REBUILD_LOCK:
                    if REBUILD_STATUS["running"]:
                        self._send_json(200, {"status": "already_running", "message": "Rebuild is already in progress"})
                        return
                thread = threading.Thread(target=run_rebuild_task, daemon=True)
                thread.start()
                self._send_json(200, {"status": "started", "message": "Background rebuild started"})
                return

            self._send_json(404, {"error": f"Endpoint {path} not found"})

        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        """Silences standard logging in tests; logs to stdout otherwise."""
        if "unittest" not in sys.modules:
            super().log_message(format, *args)


# ---------------------------------------------------------------------------
# Embedded Single Page Application (HTML / CSS / JS)
# ---------------------------------------------------------------------------

EMBEDDED_SPA_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Slayers Royal (PS1) — Редактор пиксельных шрифтов</title>
  <style>
    :root {
      --bg-dark: #111215;
      --panel-bg: #181a20;
      --card-bg: #20232b;
      --border-color: #2c313d;
      --border-subtle: #222630;
      --text-main: #e2e4e9;
      --text-muted: #8e95a5;
      --gold: #D8C090;
      --gold-bright: #F0D8A8;
      --gold-dark: #8c7348;
      --amber: #f59e0b;
      --green: #4ade80;
      --danger: #ef4444;
      --blue: #38bdf8;
      --shadow-color: #101010;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-dark);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      font-size: 13px;
      line-height: 1.4;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      user-select: none;
    }

    /* Top App Header */
    header {
      background: var(--panel-bg);
      border-bottom: 1px solid var(--border-color);
      height: 52px;
      padding: 0 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .brand-icon {
      font-size: 20px;
      background: #2a2e3a;
      width: 34px;
      height: 34px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 6px;
      border: 1px solid var(--gold-dark);
    }

    .brand-title {
      font-weight: 700;
      font-size: 14px;
      color: var(--gold);
      letter-spacing: 0.5px;
    }

    .brand-subtitle {
      font-size: 11px;
      color: var(--text-muted);
    }

    .header-actions {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .btn {
      background: var(--card-bg);
      color: var(--text-main);
      border: 1px solid var(--border-color);
      padding: 6px 12px;
      border-radius: 5px;
      font-size: 12px;
      font-weight: 500;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }

    .btn:hover {
      background: #282c37;
      border-color: #3b4252;
    }

    .btn:active {
      transform: translateY(1px);
    }

    .btn-primary {
      background: #2c2820;
      border-color: var(--gold-dark);
      color: var(--gold);
    }

    .btn-primary:hover {
      background: #3a3324;
      border-color: var(--gold);
      color: var(--gold-bright);
    }

    .btn-save.dirty {
      background: var(--amber) !important;
      color: #111 !important;
      border-color: #d97706 !important;
      font-weight: 700;
      box-shadow: 0 0 12px rgba(245, 158, 11, 0.4);
      animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.02); }
    }

    .badge-dirty {
      background: rgba(245, 158, 11, 0.15);
      color: var(--amber);
      border: 1px solid var(--amber);
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 12px;
      display: none;
    }

    /* 3-Column Main Workspace */
    .workspace {
      display: flex;
      flex: 1;
      height: calc(100vh - 52px);
      overflow: hidden;
    }

    /* Column 1: Left Sidebar (Token Gallery) */
    .sidebar-left {
      width: 310px;
      background: var(--panel-bg);
      border-right: 1px solid var(--border-color);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }

    .gallery-search-box {
      padding: 12px;
      border-bottom: 1px solid var(--border-subtle);
    }

    .search-input {
      width: 100%;
      background: var(--bg-dark);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      padding: 7px 10px;
      border-radius: 5px;
      font-size: 12px;
      outline: none;
    }

    .search-input:focus {
      border-color: var(--gold-dark);
    }

    .gallery-tabs {
      display: flex;
      padding: 6px 12px;
      gap: 6px;
      border-bottom: 1px solid var(--border-subtle);
    }

    .tab-btn {
      flex: 1;
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-size: 11px;
      padding: 4px 6px;
      border-radius: 4px;
      cursor: pointer;
      text-align: center;
    }

    .tab-btn.active {
      background: var(--card-bg);
      color: var(--gold);
      font-weight: 600;
    }

    .gallery-list {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .token-card {
      background: var(--card-bg);
      border: 1px solid var(--border-subtle);
      border-radius: 5px;
      padding: 6px 10px;
      display: flex;
      align-items: center;
      gap: 10px;
      cursor: pointer;
      transition: all 0.12s ease;
    }

    .token-card:hover {
      background: #262b35;
      border-color: #3e4657;
    }

    .token-card.active {
      border-color: var(--gold);
      background: #252420;
    }

    .token-idx {
      font-family: monospace;
      font-size: 11px;
      color: var(--text-muted);
      width: 32px;
    }

    .token-preview-mini {
      width: 20px;
      height: 20px;
      background: #181818;
      border: 1px solid #333;
      border-radius: 2px;
      image-rendering: pixelated;
    }

    .token-text {
      font-family: monospace;
      font-size: 13px;
      font-weight: 700;
      color: var(--gold-bright);
      background: #15171d;
      padding: 2px 6px;
      border-radius: 3px;
      border: 1px solid #282d38;
      min-width: 38px;
      text-align: center;
    }

    .token-count {
      font-size: 11px;
      color: var(--text-muted);
      margin-left: auto;
    }

    .token-dirty-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--amber);
      display: none;
    }

    .token-card.dirty .token-dirty-dot {
      display: block;
    }

    /* Column 2: Center Panel (Drawing Canvas & Tools) */
    .editor-center {
      flex: 1;
      display: flex;
      flex-direction: column;
      background: var(--bg-dark);
      overflow-y: auto;
      align-items: center;
      padding: 16px;
      gap: 12px;
    }

    .toolbar-top {
      width: 100%;
      max-width: 520px;
      background: var(--panel-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 8px 12px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }

    .tool-group {
      display: flex;
      align-items: center;
      gap: 4px;
    }

    .tool-btn {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      color: var(--text-main);
      width: 30px;
      height: 30px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 13px;
      transition: all 0.1s ease;
    }

    .tool-btn:hover {
      background: #2b303d;
      border-color: #404758;
    }

    .tool-btn.active {
      background: #2f2a1e;
      border-color: var(--gold);
      color: var(--gold-bright);
    }

    /* Canvas Frame */
    .canvas-frame {
      background: var(--panel-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
    }

    .canvas-header {
      width: 448px;
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .token-badge-large {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 14px;
      font-weight: 700;
      color: var(--gold);
    }

    .canvas-grid {
      width: 448px;
      height: 448px;
      background: #14161c;
      border: 2px solid #2c3240;
      border-radius: 4px;
      cursor: crosshair;
      image-rendering: pixelated;
    }

    /* Canvas Guides Options */
    .guides-bar {
      width: 448px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11px;
      color: var(--text-muted);
      padding: 0 4px;
    }

    .guide-label {
      display: flex;
      align-items: center;
      gap: 5px;
      cursor: pointer;
    }

    .guide-box {
      width: 10px;
      height: 10px;
      border-radius: 2px;
      display: inline-block;
    }

    .guide-baseline { background: var(--danger); }
    .guide-waistline { background: var(--blue); }
    .guide-center { background: #94a3b8; }

    .canvas-footer {
      width: 448px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11px;
      color: var(--text-muted);
      border-top: 1px solid var(--border-subtle);
      padding-top: 8px;
    }

    /* Column 3: Right Sidebar (Previews & Dialogue Simulator) */
    .sidebar-right {
      width: 380px;
      background: var(--panel-bg);
      border-left: 1px solid var(--border-color);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      overflow-y: auto;
      padding: 16px;
      gap: 16px;
    }

    .preview-card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .preview-title {
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      display: flex;
      align-items: center;
      justify-content: space-between;
    }

    .tile-scales {
      display: flex;
      align-items: flex-end;
      gap: 16px;
      background: #141518;
      border: 1px solid #232731;
      padding: 14px;
      border-radius: 4px;
      justify-content: space-around;
    }

    .scale-box {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
    }

    .scale-label {
      font-size: 10px;
      color: var(--text-muted);
    }

    .preview-canvas {
      background: #181818;
      image-rendering: pixelated;
      border: 1px solid #2d3340;
    }

    /* PS1 In-Game Dialogue Box Mockup */
    .ps1-dialogue-card {
      background: var(--card-bg);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .ps1-dialogue-container {
      width: 100%;
      position: relative;
      background: #000;
      border-radius: 4px;
      overflow: hidden;
      display: flex;
      justify-content: center;
      padding: 8px 4px;
    }

    .dialogue-canvas {
      width: 100%;
      max-width: 350px;
      aspect-ratio: 276 / 84;
      image-rendering: pixelated;
      border: 1px solid #333;
    }

    .dialogue-token-hint {
      font-size: 11px;
      color: #a3e635;
      background: rgba(163, 230, 53, 0.1);
      border: 1px solid rgba(163, 230, 53, 0.2);
      padding: 4px 8px;
      border-radius: 4px;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    /* Toast Notification */
    .toast-container {
      position: fixed;
      bottom: 24px;
      right: 24px;
      display: flex;
      flex-direction: column;
      gap: 8px;
      z-index: 9999;
    }

    .toast {
      background: #1e293b;
      color: #fff;
      border: 1px solid #334155;
      padding: 10px 16px;
      border-radius: 6px;
      font-size: 12px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
      display: flex;
      align-items: center;
      gap: 8px;
      animation: slideIn 0.2s ease-out;
    }

    .toast.success {
      border-color: var(--green);
      background: #142e20;
      color: #86efac;
    }

    .toast.error {
      border-color: var(--danger);
      background: #3b1818;
      color: #fca5a5;
    }

    @keyframes slideIn {
      from { transform: translateY(20px); opacity: 0; }
      to { transform: translateY(0); opacity: 1; }
    }
  </style>
</head>
<body>

  <!-- Top App Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">🔤</div>
      <div>
        <div class="brand-title">SLAYERS ROYAL — РЕДАКТОР ШРИФТОВ</div>
        <div class="brand-subtitle">PROG.UNT 0x03A / 0x03E Компактные глифы (16×16 Pixel Engine)</div>
      </div>
    </div>

    <div class="header-actions">
      <span id="unsavedBadge" class="badge-dirty">● 0 токенов не сохранено</span>
      <button class="btn" onclick="triggerRebuild()" title="Собрать сюжет через build.sh --story">
        <span>⚙️ Сборка сюжета</span>
      </button>
      <button class="btn" onclick="saveAllDirty()" id="btnSaveAll" style="display:none;">
        <span>💾 Сохранить всё</span>
      </button>
      <button class="btn btn-primary btn-save" id="btnSaveCurrent" onclick="saveCurrentTile()">
        <span>💾 Сохранить (Ctrl+S)</span>
      </button>
    </div>
  </header>

  <!-- 3-Column Main Workspace -->
  <div class="workspace">

    <!-- Column 1: Left Sidebar (Token Gallery) -->
    <aside class="sidebar-left">
      <div class="gallery-search-box">
        <input type="text" id="gallerySearch" class="search-input" placeholder="🔍 Поиск по токену или ID (напр. 'ни' или '27')..." oninput="filterGallery()">
      </div>

      <div class="gallery-tabs">
        <button class="tab-btn active" id="tabAll" onclick="setGalleryFilter('all')">Все (420)</button>
        <button class="tab-btn" id="tabDirty" onclick="setGalleryFilter('dirty')">Изменённые (0)</button>
        <button class="tab-btn" id="tabCommon" onclick="setGalleryFilter('common')">Частые (&gt;200)</button>
      </div>

      <div class="gallery-list" id="galleryList">
        <!-- Rendered dynamically -->
      </div>
    </aside>

    <!-- Column 2: Center Panel (Drawing Canvas & Tools) -->
    <main class="editor-center">
      <div class="toolbar-top">
        <div class="tool-group">
          <button class="tool-btn active" id="toolPencil" onclick="setTool('pencil')" title="Карандаш (P)">✏️</button>
          <button class="tool-btn" id="toolEraser" onclick="setTool('eraser')" title="Ластик (E)">🧹</button>
        </div>

        <div class="tool-group">
          <button class="tool-btn" onclick="shiftPixels(0, -1)" title="Сдвиг Вверх">⬆️</button>
          <button class="tool-btn" onclick="shiftPixels(0, 1)" title="Сдвиг Вниз">⬇️</button>
          <button class="tool-btn" onclick="shiftPixels(-1, 0)" title="Сдвиг Влево">⬅️</button>
          <button class="tool-btn" onclick="shiftPixels(1, 0)" title="Сдвиг Вправо">➡️</button>
        </div>

        <div class="tool-group">
          <button class="tool-btn" onclick="invertColors()" title="Инвертировать цвета">🌓</button>
          <button class="tool-btn" onclick="clearTile()" title="Очистить плитку">🗑️</button>
        </div>

        <div class="tool-group">
          <button class="tool-btn" onclick="undo()" title="Отменить (Ctrl+Z)">↶</button>
          <button class="tool-btn" onclick="redo()" title="Повторить (Ctrl+Y)">↷</button>
        </div>
      </div>

      <div class="canvas-frame">
        <div class="canvas-header">
          <div class="token-badge-large">
            <span id="activeTokenId">#000</span>
            <span id="activeTokenText" class="token-text">то</span>
            <span id="activeTokenUsage" style="font-size:12px; font-weight:normal; color:var(--text-muted);">(401×)</span>
          </div>
          <button class="btn" style="padding:4px 8px; font-size:11px;" onclick="revertActiveTile()">
            <span>↺ Сбросить к оригиналу</span>
          </button>
        </div>

        <!-- Interactive 16x16 Canvas (448x448 px = 28px/cell) -->
        <canvas id="paintCanvas" class="canvas-grid" width="448" height="448"></canvas>

        <div class="guides-bar">
          <label class="guide-label">
            <input type="checkbox" id="chkBaseline" checked onchange="redrawCanvas()">
            <span class="guide-box guide-baseline"></span> Базовая линия (y=10)
          </label>
          <label class="guide-label">
            <input type="checkbox" id="chkWaistline" checked onchange="redrawCanvas()">
            <span class="guide-box guide-waistline"></span> Линия пояса (y=4)
          </label>
          <label class="guide-label">
            <input type="checkbox" id="chkCenter" checked onchange="redrawCanvas()">
            <span class="guide-box guide-center"></span> Центр (x=8)
          </label>
          <label class="guide-label">
            <input type="checkbox" id="chkGrid" checked onchange="redrawCanvas()"> Сетка
          </label>
        </div>

        <div class="canvas-footer">
          <span id="coordReadout">X: — , Y: —</span>
          <span>ЛКМ: Рисовать • ПКМ / E: Стирать • [ / ]: Токены</span>
          <span id="statusClean">На диске актуально</span>
        </div>
      </div>
    </main>

    <!-- Column 3: Right Sidebar (Previews & Dialogue Simulator) -->
    <aside class="sidebar-right">

      <!-- Tile Previews -->
      <div class="preview-card">
        <div class="preview-title">
          <span>ПРЕДПРОСМОТР ПЛИТКИ</span>
          <button class="btn" style="padding:2px 6px; font-size:10px;" onclick="toggleColorMode()" id="btnColorToggle">
            🎨 Золотой (#D8C090)
          </button>
        </div>

        <div class="tile-scales">
          <div class="scale-box">
            <canvas id="prev1x" class="preview-canvas" width="16" height="16" style="width:24px; height:24px;"></canvas>
            <span class="scale-label">1X (16px)</span>
          </div>
          <div class="scale-box">
            <canvas id="prev2x" class="preview-canvas" width="32" height="32" style="width:48px; height:48px;"></canvas>
            <span class="scale-label">2X (32px)</span>
          </div>
          <div class="scale-box">
            <canvas id="prev4x" class="preview-canvas" width="64" height="64" style="width:80px; height:80px;"></canvas>
            <span class="scale-label">4X (64px)</span>
          </div>
        </div>
      </div>

      <!-- In-Game Dialogue Simulator -->
      <div class="ps1-dialogue-card">
        <div class="preview-title">
          <span>СИМУЛЯТОР ДИАЛОГОВ PS1</span>
          <label style="font-size:10px; display:flex; align-items:center; gap:4px; cursor:pointer;">
            <input type="checkbox" id="chkScanlines" checked onchange="renderDialoguePreview()"> Scanlines CRT
          </label>
        </div>

        <div id="dialogueActiveHint" class="dialogue-token-hint" style="display:none;">
          <span>✨ Токен участвует в текущей реплике!</span>
        </div>

        <div class="ps1-dialogue-container">
          <canvas id="dialogueCanvas" class="dialogue-canvas" width="276" height="84"></canvas>
        </div>
        <div style="font-size:11px; color:var(--text-muted); line-height:1.3;">
          Окно 276×84 px со сжатыми глифами. Отрисовка обновляется в реальном времени при рисовании!
        </div>
      </div>

      <!-- Atlas Location Details -->
      <div class="preview-card">
        <div class="preview-title">ПОЗИЦИЯ В АТЛАСЕ (256×432)</div>
        <div style="font-size:11px; color:var(--text-muted); display:flex; flex-direction:column; gap:4px;">
          <div><b>Колонка:</b> <span id="infoCol">0</span> / 15</div>
          <div><b>Ряд:</b> <span id="infoRow">0</span> / 26</div>
          <div><b>Координаты:</b> <span id="infoXY">X: 0 px, Y: 0 px</span></div>
          <div><b>Файл:</b> <code>compact_font_atlas_raw.png</code></div>
        </div>
      </div>

    </aside>

  </div>

  <div class="toast-container" id="toastContainer"></div>

  <script>
    // -----------------------------------------------------------------------
    // Single Character Pixel Bitmaps for In-Game Dialogue Mockup
    // -----------------------------------------------------------------------
    const DIALOGUE_SINGLE_MASKS = {
      "Н": [
        "0000000000000000","0000000000000000","0000010000100000","0000010000100000",
        "0000010000100000","0000010000100000","0000011111100000","0000010000100000",
        "0000010000100000","0000010000100000","0000010000100000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "С": [
        "0000000000000000","0000000000000000","0000011111100000","0000100000000000",
        "0000100000000000","0000100000000000","0000100000000000","0000100000000000",
        "0000100000000000","0000100000000000","0000011111100000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "о": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000011110000000","0000100001000000","0000100001000000","0000100001000000",
        "0000100001000000","0000100001000000","0000011110000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "и": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000010000100000","0000010001100000","0000010010100000","0000010100100000",
        "0000011000100000","0000010000100000","0000010000100000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      ".": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000110000000","0000000110000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      " ": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "ш": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000100100100000","0000100100100000","0000100100100000","0000100100100000",
        "0000100100100000","0000100100100000","0000111111100000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "а": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000011110000000","0000100001000000","0000100001000000","0000111111000000",
        "0000100001000000","0000100001000000","0000100001000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "З": [
        "0000000000000000","0000000000000000","0000011111000000","0000000000100000",
        "0000000000100000","0000000000100000","0000001111000000","0000000000100000",
        "0000000000100000","0000000000100000","0000011111000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      ",": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000000110000000","0000000110000000","0000000010000000","0000000010000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "ж": [
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000",
        "0000100100100000","0000100100100000","0000010101000000","0000001110000000",
        "0000010101000000","0000100100100000","0000100100100000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ],
      "Л": [
        "0000000000000000","0000000000000000","0000000111100000","0000000100010000",
        "0000000100010000","0000000100010000","0000000100010000","0000000100010000",
        "0000000100010000","0000000100010000","0000011100010000","0000000000000000",
        "0000000000000000","0000000000000000","0000000000000000","0000000000000000"
      ]
    };

    // 3-Line PS1 Dialogue Token Structure
    const DIALOGUE_LINES = [
      // Line 1: "Ну вот мы и в"
      [
        { type: "single", char: "Н" },
        { type: "token", token: "у ", index: 62 },
        { type: "token", token: "во", index: 28 },
        { type: "token", token: "т ", index: 114 },
        { type: "token", token: "мы", index: 164 },
        { type: "token", token: " и", index: 59 },
        { type: "token", token: " в", index: 3 }
      ],
      // Line 2: "Сонии. Слушай,"
      [
        { type: "single", char: "С" },
        { type: "single", char: "о" },
        { type: "token", token: "ни", index: 27 },
        { type: "single", char: "и" },
        { type: "single", char: "." },
        { type: "single", char: " " },
        { type: "single", char: "С" },
        { type: "token", token: "лу", index: 137 },
        { type: "single", char: "ш" },
        { type: "single", char: "а" },
        { type: "token", token: "й,", index: 209 }
      ],
      // Line 3: "Зел, прежде чем"
      [
        { type: "single", char: "З" },
        { type: "token", token: "ел", index: 20 },
        { type: "single", char: "," },
        { type: "token", token: " п", index: 39 },
        { type: "token", token: "ре", index: 85 },
        { type: "single", char: "ж" },
        { type: "token", token: "де", index: 22 },
        { type: "token", token: " ч", index: 57 },
        { type: "token", token: "ем", index: 73 }
      ]
    ];

    // Global App State
    let tokensList = [];
    let activeTokenIndex = 0;
    let currentPixels = Array.from({ length: 16 }, () => Array(16).fill(0));
    let originalPixels = Array.from({ length: 16 }, () => Array(16).fill(0));
    const cachedTiles = {}; // index -> 16x16 matrix
    const dirtyTiles = {};  // index -> 16x16 matrix

    let currentTool = "pencil"; // 'pencil' | 'eraser'
    let isMouseDown = false;
    let paintVal = 1;
    let colorMode = "gold"; // 'gold' | 'white'
    let activeFilter = "all";

    // Undo / Redo stacks
    let undoStack = [];
    let redoStack = [];

    // Setup DOM Elements
    const paintCanvas = document.getElementById("paintCanvas");
    const paintCtx = paintCanvas.getContext("2d");
    const prev1x = document.getElementById("prev1x").getContext("2d");
    const prev2x = document.getElementById("prev2x").getContext("2d");
    const prev4x = document.getElementById("prev4x").getContext("2d");
    const dialogueCtx = document.getElementById("dialogueCanvas").getContext("2d");

    // Initialize App
    async function init() {
      await loadTokens();
      setupEvents();
      if (tokensList.length > 0) {
        await selectToken(0);
      }
    }

    async function loadTokens() {
      try {
        const res = await fetch("/api/tokens");
        tokensList = await res.json();
        renderGallery();
      } catch (err) {
        showToast("Ошибка загрузки токенов: " + err, "error");
      }
    }

    function renderGallery() {
      const container = document.getElementById("galleryList");
      container.innerHTML = "";
      const query = document.getElementById("gallerySearch").value.toLowerCase().trim();

      let visibleCount = 0;
      tokensList.forEach(t => {
        // Filter tabs
        if (activeFilter === "dirty" && !dirtyTiles[t.index]) return;
        if (activeFilter === "common" && t.count <= 200) return;

        // Search query
        if (query) {
          const matchTok = t.token.toLowerCase().includes(query);
          const matchIdx = String(t.index).includes(query);
          if (!matchTok && !matchIdx) return;
        }

        visibleCount++;
        const card = document.createElement("div");
        card.className = "token-card" + (t.index === activeTokenIndex ? " active" : "") + (dirtyTiles[t.index] ? " dirty" : "");
        card.id = `tokenCard_${t.index}`;
        card.onclick = () => selectToken(t.index);

        card.innerHTML = `
          <span class="token-idx">#${String(t.index).padStart(3, '0')}</span>
          <canvas class="token-preview-mini" id="miniPrev_${t.index}" width="16" height="16"></canvas>
          <span class="token-text">${escapeHtml(t.token)}</span>
          <span class="token-count">${t.count}×</span>
          <span class="token-dirty-dot"></span>
        `;
        container.appendChild(card);

        // Render mini preview if cached
        renderMiniPreview(t.index);
      });

      updateDirtyCounters();
    }

    function escapeHtml(str) {
      return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function setGalleryFilter(filter) {
      activeFilter = filter;
      document.getElementById("tabAll").classList.toggle("active", filter === "all");
      document.getElementById("tabDirty").classList.toggle("active", filter === "dirty");
      document.getElementById("tabCommon").classList.toggle("active", filter === "common");
      renderGallery();
    }

    function filterGallery() {
      renderGallery();
    }

    function updateDirtyCounters() {
      const dirtyCount = Object.keys(dirtyTiles).length;
      document.getElementById("tabDirty").innerText = `Изменённые (${dirtyCount})`;
      const badge = document.getElementById("unsavedBadge");
      const btnSaveAll = document.getElementById("btnSaveAll");
      if (dirtyCount > 0) {
        badge.style.display = "inline-block";
        badge.innerText = `● ${dirtyCount} не сохранено`;
        btnSaveAll.style.display = "inline-flex";
      } else {
        badge.style.display = "none";
        btnSaveAll.style.display = "none";
      }

      const isCurrentDirty = !!dirtyTiles[activeTokenIndex];
      const btnSave = document.getElementById("btnSaveCurrent");
      btnSave.classList.toggle("dirty", isCurrentDirty);
      document.getElementById("statusClean").innerText = isCurrentDirty ? "Есть несохранённые изменения" : "На диске актуально";
      document.getElementById("statusClean").style.color = isCurrentDirty ? "var(--amber)" : "var(--text-muted)";
    }

    async function selectToken(index) {
      // Save current in-memory modifications before switching
      if (isCurrentModified()) {
        dirtyTiles[activeTokenIndex] = currentPixels.map(row => [...row]);
      }

      activeTokenIndex = index;
      const meta = tokensList[index] || { token: "??", count: 0, row: 0, col: 0, x: 0, y: 0 };

      // Update UI Header
      document.getElementById("activeTokenId").innerText = `#${String(index).padStart(3, '0')}`;
      document.getElementById("activeTokenText").innerText = meta.token;
      document.getElementById("activeTokenUsage").innerText = `(${meta.count}×)`;

      document.getElementById("infoCol").innerText = meta.col;
      document.getElementById("infoRow").innerText = meta.row;
      document.getElementById("infoXY").innerText = `X: ${meta.x} px, Y: ${meta.y} px`;

      // Check if this token appears in dialogue simulation
      const inDialogue = DIALOGUE_LINES.some(line => line.some(it => it.type === "token" && it.index === index));
      document.getElementById("dialogueActiveHint").style.display = inDialogue ? "flex" : "none";

      // Reset Undo / Redo
      undoStack = [];
      redoStack = [];

      // Check if we have dirty pixels in memory or need to fetch from server
      if (dirtyTiles[index]) {
        currentPixels = dirtyTiles[index].map(row => [...row]);
      } else if (cachedTiles[index]) {
        currentPixels = cachedTiles[index].map(row => [...row]);
        originalPixels = cachedTiles[index].map(row => [...row]);
      } else {
        try {
          const res = await fetch(`/api/tile/${index}`);
          const data = await res.json();
          cachedTiles[index] = data.pixels;
          originalPixels = data.pixels.map(row => [...row]);
          currentPixels = data.pixels.map(row => [...row]);
        } catch (err) {
          showToast("Ошибка загрузки тайла: " + err, "error");
        }
      }

      // Highlight active card
      document.querySelectorAll(".token-card").forEach(el => el.classList.remove("active"));
      const card = document.getElementById(`tokenCard_${index}`);
      if (card) {
        card.classList.add("active");
        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }

      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      updateDirtyCounters();
    }

    function isCurrentModified() {
      for (let r = 0; r < 16; r++) {
        for (let c = 0; c < 16; c++) {
          if (currentPixels[r][c] !== originalPixels[r][c]) return true;
        }
      }
      return false;
    }

    // -----------------------------------------------------------------------
    // Canvas Drawing Grid Logic
    // -----------------------------------------------------------------------

    function redrawCanvas() {
      const cellSize = 28;
      paintCtx.clearRect(0, 0, 448, 448);

      const showGrid = document.getElementById("chkGrid").checked;
      const showBaseline = document.getElementById("chkBaseline").checked;
      const showWaistline = document.getElementById("chkWaistline").checked;
      const showCenter = document.getElementById("chkCenter").checked;

      // Draw pixels
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          const isSet = currentPixels[y][x];
          paintCtx.fillStyle = isSet ? (colorMode === "gold" ? "#D8C090" : "#FFFFFF") : "#14161c";
          paintCtx.fillRect(x * cellSize, y * cellSize, cellSize, cellSize);

          if (showGrid) {
            paintCtx.strokeStyle = "#222630";
            paintCtx.lineWidth = 1;
            paintCtx.strokeRect(x * cellSize + 0.5, y * cellSize + 0.5, cellSize - 1, cellSize - 1);
          }
        }
      }

      // Guides
      // Waistline (y=4): top of row 4
      if (showWaistline) {
        paintCtx.strokeStyle = "#38bdf8";
        paintCtx.lineWidth = 2;
        paintCtx.setLineDash([4, 4]);
        paintCtx.beginPath();
        paintCtx.moveTo(0, 4 * cellSize);
        paintCtx.lineTo(448, 4 * cellSize);
        paintCtx.stroke();
      }

      // Baseline (y=10): bottom of row 10
      if (showBaseline) {
        paintCtx.strokeStyle = "#ef4444";
        paintCtx.lineWidth = 2;
        paintCtx.setLineDash([4, 4]);
        paintCtx.beginPath();
        paintCtx.moveTo(0, 11 * cellSize);
        paintCtx.lineTo(448, 11 * cellSize);
        paintCtx.stroke();
      }

      // Center (x=8): between col 7 and col 8
      if (showCenter) {
        paintCtx.strokeStyle = "#94a3b8";
        paintCtx.lineWidth = 1.5;
        paintCtx.setLineDash([4, 4]);
        paintCtx.beginPath();
        paintCtx.moveTo(8 * cellSize, 0);
        paintCtx.lineTo(8 * cellSize, 448);
        paintCtx.stroke();
      }

      paintCtx.setLineDash([]);
    }

    function setupEvents() {
      // Mouse down on canvas
      paintCanvas.addEventListener("mousedown", (e) => {
        isMouseDown = true;
        paintVal = (e.button === 2 || currentTool === "eraser") ? 0 : 1;
        pushUndo();
        handleMouseDraw(e);
      });

      // Mouse move on canvas
      paintCanvas.addEventListener("mousemove", (e) => {
        const coords = getCanvasCoords(e);
        if (coords) {
          document.getElementById("coordReadout").innerText = `X: ${coords.x} , Y: ${coords.y}`;
        }
        if (isMouseDown) {
          handleMouseDraw(e);
        }
      });

      window.addEventListener("mouseup", () => {
        if (isMouseDown) {
          isMouseDown = false;
          checkDirtyState();
        }
      });

      paintCanvas.addEventListener("mouseleave", () => {
        document.getElementById("coordReadout").innerText = "X: — , Y: —";
      });

      // Prevent context menu
      paintCanvas.addEventListener("contextmenu", (e) => e.preventDefault());

      // Global keyboard shortcuts
      window.addEventListener("keydown", (e) => {
        // If typing in input, ignore shortcuts
        if (e.target.tagName === "INPUT") return;

        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
          e.preventDefault();
          saveCurrentTile();
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
          e.preventDefault();
          if (e.shiftKey) redo(); else undo();
        } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
          e.preventDefault();
          redo();
        } else if (e.key === "[" || e.key === "PageUp") {
          e.preventDefault();
          navToken(-1);
        } else if (e.key === "]" || e.key === "PageDown") {
          e.preventDefault();
          navToken(1);
        } else if (e.key.toLowerCase() === "p") {
          setTool("pencil");
        } else if (e.key.toLowerCase() === "e") {
          setTool("eraser");
        }
      });
    }

    function getCanvasCoords(e) {
      const rect = paintCanvas.getBoundingClientRect();
      const x = Math.floor((e.clientX - rect.left) / (rect.width / 16));
      const y = Math.floor((e.clientY - rect.top) / (rect.height / 16));
      if (x >= 0 && x < 16 && y >= 0 && y < 16) return { x, y };
      return null;
    }

    function handleMouseDraw(e) {
      const coords = getCanvasCoords(e);
      if (!coords) return;
      if (currentPixels[coords.y][coords.x] !== paintVal) {
        currentPixels[coords.y][coords.x] = paintVal;
        redrawCanvas();
        renderPreviews();
        renderDialoguePreview();
      }
    }

    function checkDirtyState() {
      const modified = isCurrentModified();
      if (modified) {
        dirtyTiles[activeTokenIndex] = currentPixels.map(row => [...row]);
      } else {
        delete dirtyTiles[activeTokenIndex];
      }
      updateDirtyCounters();
      const card = document.getElementById(`tokenCard_${activeTokenIndex}`);
      if (card) card.classList.toggle("dirty", modified);
      renderMiniPreview(activeTokenIndex);
    }

    function navToken(delta) {
      const newIdx = activeTokenIndex + delta;
      if (newIdx >= 0 && newIdx < tokensList.length) {
        selectToken(newIdx);
      }
    }

    // -----------------------------------------------------------------------
    // Drawing Tools & Operations
    // -----------------------------------------------------------------------

    function setTool(tool) {
      currentTool = tool;
      document.getElementById("toolPencil").classList.toggle("active", tool === "pencil");
      document.getElementById("toolEraser").classList.toggle("active", tool === "eraser");
    }

    function pushUndo() {
      undoStack.push(currentPixels.map(row => [...row]));
      if (undoStack.length > 50) undoStack.shift();
      redoStack = [];
    }

    function undo() {
      if (undoStack.length === 0) return;
      redoStack.push(currentPixels.map(row => [...row]));
      currentPixels = undoStack.pop();
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
    }

    function redo() {
      if (redoStack.length === 0) return;
      undoStack.push(currentPixels.map(row => [...row]));
      currentPixels = redoStack.pop();
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
    }

    function clearTile() {
      pushUndo();
      currentPixels = Array.from({ length: 16 }, () => Array(16).fill(0));
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
    }

    function invertColors() {
      pushUndo();
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          currentPixels[y][x] = 1 - currentPixels[y][x];
        }
      }
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
    }

    function shiftPixels(dx, dy) {
      pushUndo();
      const next = Array.from({ length: 16 }, () => Array(16).fill(0));
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          const nx = x + dx;
          const ny = y + dy;
          if (nx >= 0 && nx < 16 && ny >= 0 && ny < 16) {
            next[ny][nx] = currentPixels[y][x];
          }
        }
      }
      currentPixels = next;
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
    }

    function revertActiveTile() {
      currentPixels = originalPixels.map(row => [...row]);
      delete dirtyTiles[activeTokenIndex];
      undoStack = [];
      redoStack = [];
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
      checkDirtyState();
      showToast("Тайл сброшен к оригинальному состоянию", "success");
    }

    function toggleColorMode() {
      colorMode = colorMode === "gold" ? "white" : "gold";
      document.getElementById("btnColorToggle").innerText = colorMode === "gold" ? "🎨 Золотой (#D8C090)" : "⚪ Белый (#FFFFFF)";
      redrawCanvas();
      renderPreviews();
      renderDialoguePreview();
    }

    // -----------------------------------------------------------------------
    // Previews Rendering (1X, 2X, 4X, Mini, Dialogue)
    // -----------------------------------------------------------------------

    function renderPreviews() {
      const textColor = colorMode === "gold" ? "#D8C090" : "#FFFFFF";
      const shadowColor = "#101010";

      // 1X Preview (16x16)
      renderTileToCanvas(prev1x, currentPixels, 16, textColor, shadowColor);
      // 2X Preview (32x32)
      renderTileToCanvas(prev2x, currentPixels, 32, textColor, shadowColor);
      // 4X Preview (64x64)
      renderTileToCanvas(prev4x, currentPixels, 64, textColor, shadowColor);
    }

    function renderMiniPreview(index) {
      const canvas = document.getElementById(`miniPrev_${index}`);
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const pixels = (index === activeTokenIndex) ? currentPixels : (dirtyTiles[index] || cachedTiles[index]);
      if (!pixels) return;
      renderTileToCanvas(ctx, pixels, 16, "#D8C090", "#101010");
    }

    function renderTileToCanvas(ctx, pixels, size, textColor, shadowColor) {
      ctx.clearRect(0, 0, size, size);
      const scale = size / 16;

      // Pass 1: Drop-shadow layer (shifted down-right by 1px)
      ctx.fillStyle = shadowColor;
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          if (pixels[y][x]) {
            ctx.fillRect((x + 1) * scale, (y + 1) * scale, scale, scale);
          }
        }
      }

      // Pass 2: Text face layer
      ctx.fillStyle = textColor;
      for (let y = 0; y < 16; y++) {
        for (let x = 0; x < 16; x++) {
          if (pixels[y][x]) {
            ctx.fillRect(x * scale, y * scale, scale, scale);
          }
        }
      }
    }

    function renderDialoguePreview() {
      const textColor = colorMode === "gold" ? "#D8C090" : "#FFFFFF";
      const shadowColor = "#101010";

      // Dialogue Box: 276 x 84 px
      dialogueCtx.clearRect(0, 0, 276, 84);

      // Authentic PS1 beveled frame
      dialogueCtx.fillStyle = "#16181e";
      dialogueCtx.fillRect(4, 6, 268, 74);

      dialogueCtx.strokeStyle = "#32415f";
      dialogueCtx.strokeRect(4.5, 6.5, 267, 73);
      dialogueCtx.strokeStyle = "#6482b4";
      dialogueCtx.strokeRect(5.5, 7.5, 265, 71);
      dialogueCtx.strokeStyle = "#1e2637";
      dialogueCtx.strokeRect(6.5, 8.5, 263, 69);

      // Speaker Name Tag: "ЛИНА"
      const speakerChars = ["Л", "И", "Н", "А"];
      let sx = 14;
      speakerChars.forEach(ch => {
        const mask = DIALOGUE_SINGLE_MASKS[ch];
        if (mask) {
          drawDialogueTile(dialogueCtx, mask, sx, 4, "#F0D8A8", shadowColor);
        }
        sx += 14;
      });

      // 3 Dialogue Lines
      const lineY = [22, 40, 58];
      DIALOGUE_LINES.forEach((line, lineIdx) => {
        let x = 14;
        const y = lineY[lineIdx];

        line.forEach(item => {
          let mask = null;
          if (item.type === "token") {
            if (item.index === activeTokenIndex) {
              mask = currentPixels;
            } else if (dirtyTiles[item.index]) {
              mask = dirtyTiles[item.index];
            } else if (cachedTiles[item.index]) {
              mask = cachedTiles[item.index];
            } else {
              // Fetch asynchronously for background load
              fetchTileQuietly(item.index);
            }
          } else if (item.type === "single") {
            mask = DIALOGUE_SINGLE_MASKS[item.char];
          }

          if (mask) {
            drawDialogueTile(dialogueCtx, mask, x, y, textColor, shadowColor);
          }
          x += 16;
        });
      });

      // CRT Scanlines Effect
      if (document.getElementById("chkScanlines").checked) {
        dialogueCtx.fillStyle = "rgba(0, 0, 0, 0.22)";
        for (let sy = 0; sy < 84; sy += 2) {
          dialogueCtx.fillRect(0, sy, 276, 1);
        }
      }
    }

    function drawDialogueTile(ctx, mask, x, y, textColor, shadowColor) {
      // Pass 1: Drop-shadow
      ctx.fillStyle = shadowColor;
      for (let r = 0; r < 16; r++) {
        const row = mask[r];
        for (let c = 0; c < 16; c++) {
          const val = typeof row === "string" ? row[c] === "1" : row[c];
          if (val) {
            ctx.fillRect(x + c + 1, y + r + 1, 1, 1);
          }
        }
      }

      // Pass 2: Text pixel
      ctx.fillStyle = textColor;
      for (let r = 0; r < 16; r++) {
        const row = mask[r];
        for (let c = 0; c < 16; c++) {
          const val = typeof row === "string" ? row[c] === "1" : row[c];
          if (val) {
            ctx.fillRect(x + c, y + r, 1, 1);
          }
        }
      }
    }

    async function fetchTileQuietly(index) {
      if (cachedTiles[index]) return;
      try {
        const res = await fetch(`/api/tile/${index}`);
        const data = await res.json();
        cachedTiles[index] = data.pixels;
        renderDialoguePreview();
        renderMiniPreview(index);
      } catch (_) {}
    }

    // -----------------------------------------------------------------------
    // Saving & Rebuilding API Calls
    // -----------------------------------------------------------------------

    async function saveCurrentTile() {
      const btn = document.getElementById("btnSaveCurrent");
      btn.disabled = true;

      try {
        const res = await fetch("/api/save_tile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: activeTokenIndex, pixels: currentPixels })
        });
        const data = await res.json();
        if (data.success) {
          originalPixels = currentPixels.map(row => [...row]);
          cachedTiles[activeTokenIndex] = currentPixels.map(row => [...row]);
          delete dirtyTiles[activeTokenIndex];
          updateDirtyCounters();
          const card = document.getElementById(`tokenCard_${activeTokenIndex}`);
          if (card) card.classList.remove("dirty");
          renderMiniPreview(activeTokenIndex);

          showToast(`Токен #${String(activeTokenIndex).padStart(3, '0')} («${tokensList[activeTokenIndex].token}») сохранён в атлас!`, "success");
        } else {
          showToast(`Ошибка сохранения: ${data.error}`, "error");
        }
      } catch (err) {
        showToast("Ошибка сети при сохранении: " + err, "error");
      } finally {
        btn.disabled = false;
      }
    }

    async function saveAllDirty() {
      const keys = Object.keys(dirtyTiles);
      if (keys.length === 0) return;

      const btn = document.getElementById("btnSaveAll");
      btn.disabled = true;

      try {
        // Include current tile if modified
        if (isCurrentModified()) {
          dirtyTiles[activeTokenIndex] = currentPixels.map(row => [...row]);
        }

        const res = await fetch("/api/save_all", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tiles: dirtyTiles })
        });
        const data = await res.json();
        if (data.success) {
          originalPixels = currentPixels.map(row => [...row]);
          Object.keys(dirtyTiles).forEach(idx => {
            cachedTiles[idx] = dirtyTiles[idx];
            delete dirtyTiles[idx];
            const card = document.getElementById(`tokenCard_${idx}`);
            if (card) card.classList.remove("dirty");
            renderMiniPreview(idx);
          });
          updateDirtyCounters();
          showToast(`Все изменённые токены (${data.saved_count}) сохранены в атлас!`, "success");
        } else {
          showToast(`Ошибка пакетного сохранения: ${data.error}`, "error");
        }
      } catch (err) {
        showToast("Ошибка сети при сохранении: " + err, "error");
      } finally {
        btn.disabled = false;
      }
    }

    async function triggerRebuild() {
      showToast("Запущена пересборка сюжета (build.sh --story)...", "success");
      try {
        const res = await fetch("/api/rebuild", { method: "POST" });
        const data = await res.json();
        if (data.status === "already_running") {
          showToast("Сборка уже выполняется в фоне", "success");
        } else {
          pollRebuildStatus();
        }
      } catch (err) {
        showToast("Ошибка запуска сборки: " + err, "error");
      }
    }

    async function pollRebuildStatus() {
      const interval = setInterval(async () => {
        try {
          const res = await fetch("/api/rebuild/status");
          const status = await res.json();
          if (!status.running) {
            clearInterval(interval);
            if (status.last_success) {
              showToast("Сборка сюжета успешно завершена!", "success");
            } else {
              showToast("Ошибка при сборке сюжета!", "error");
            }
          }
        } catch (_) {
          clearInterval(interval);
        }
      }, 2000);
    }

    function showToast(message, type = "success") {
      const container = document.getElementById("toastContainer");
      const toast = document.createElement("div");
      toast.className = `toast ${type}`;
      toast.innerHTML = `<span>${type === 'success' ? '✓' : '⚠️'}</span><span>${escapeHtml(message)}</span>`;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = "0";
        toast.style.transform = "translateY(10px)";
        toast.style.transition = "all 0.3s ease";
        setTimeout(() => toast.remove(), 300);
      }, 3500);
    }

    // Start on DOM ready
    window.addEventListener("DOMContentLoaded", init);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slayers Royal (PS1) — Browser-based Pixel Font Editor for compact_font_atlas_raw.png"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host address to bind local server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Port to bind local server (default: 8766)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        default=False,
        help="Automatically open editor in default web browser upon launch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server_address = (args.host, args.port)

    # Allow immediate address reuse
    socketserver.TCPServer.allow_reuse_address = True

    try:
        httpd = socketserver.TCPServer(server_address, FontPixelEditorHandler)
    except OSError as exc:
        print(f"[ERROR] Failed to bind to {args.host}:{args.port}: {exc}", file=sys.stderr)
        print("[HINT] Make sure no other editor instance is running on this port.", file=sys.stderr)
        sys.exit(1)

    url = f"http://{args.host}:{args.port}/"
    print("=" * 68)
    print("  Slayers Royal (PS1) — Редактор пиксельных шрифтов (16x16 Canvas)")
    print("=" * 68)
    print(f"[*] Сервер запущен: {url}")
    print("[*] Для завершения нажмите Ctrl+C")
    print("=" * 68)

    if args.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Завершение работы сервера...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
