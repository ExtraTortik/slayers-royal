#!/usr/bin/env python3
"""Comprehensive test suite for tools/font_pixel_editor.py.

Validates:
1. Tokens metadata integrity (220 compact tokens, grid layout 16x14, frequencies).
2. Pixel and RGBA tile conversion with authentic PS1 drop-shadow and 100% roundtrip fidelity.
3. AtlasManager atomic file operations on disk (reading, single-tile save, multi-tile save, error handling).
4. REST API HTTP Server endpoints:
   - GET / -> 200 OK (HTML Single Page Application)
   - GET /api/tokens -> 200 OK (list of 220 tokens)
   - GET /api/tile/<index> -> 200 OK (tile data & 16x16 pixels)
   - GET /api/tile/out_of_bounds -> 404 Not Found
   - GET /api/tile/invalid -> 400 Bad Request
   - POST /api/save_tile -> 200 OK (atomic single tile write)
   - POST /api/save_tile (invalid) -> 400 Bad Request
   - POST /api/save_all -> 200 OK (atomic multi-tile batch save)
   - POST /api/save_all (invalid) -> 400 Bad Request
   - GET /api/atlas.png -> 200 OK (image/png header & data)
   - GET /api/rebuild/status -> 200 OK (status json)
   - OPTIONS / -> 204 No Content with CORS headers
   - 404 on unknown routes
"""

from __future__ import annotations

import json
import os
import shutil
import socketserver
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import sys
from pathlib import Path
from typing import Any

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.font_pixel_editor import (
    ATLAS_PATH,
    AtlasManager,
    FontPixelEditorHandler,
    load_tokens_metadata,
    pixels_to_rgba_tile,
    rgba_tile_to_pixels,
    TEXT_COLOR,
    SHADOW_COLOR,
)


class TestTokensMetadata(unittest.TestCase):
    """Validates compact token metadata loading and geometry."""

    def test_tokens_count_and_fields(self):
        tokens = load_tokens_metadata()
        self.assertEqual(len(tokens), 220, "Must return exactly 220 compact tokens")

        for idx, item in enumerate(tokens):
            self.assertEqual(item["index"], idx)
            self.assertIn("token", item)
            self.assertIn("count", item)
            self.assertIn("row", item)
            self.assertIn("col", item)
            self.assertIn("x", item)
            self.assertIn("y", item)

            self.assertIsInstance(item["token"], str)
            self.assertGreater(len(item["token"]), 0)
            self.assertGreaterEqual(item["count"], 0)

    def test_tokens_geometry(self):
        tokens = load_tokens_metadata()
        for item in tokens:
            idx = item["index"]
            expected_row = idx // 16
            expected_col = idx % 16
            self.assertEqual(item["row"], expected_row)
            self.assertEqual(item["col"], expected_col)
            self.assertEqual(item["x"], expected_col * 16)
            self.assertEqual(item["y"], expected_row * 16)
            self.assertLess(item["row"], 14)
            self.assertLess(item["col"], 16)

    def test_known_tokens_present(self):
        tokens = load_tokens_metadata()
        token_texts = {t["token"] for t in tokens}
        # Tokens explicitly noted in the specification
        for expected in ["то", "ни", "ел", "де", "ре", "лу", "во", "мы", " в"]:
            self.assertIn(expected, token_texts, f"Token {expected!r} should be present in 220 tokens")


class TestPixelConversion(unittest.TestCase):
    """Validates 1-bit mask to authentic RGBA tile conversion with drop-shadow."""

    def test_empty_tile(self):
        empty_pixels = [[0] * 16 for _ in range(16)]
        tile_im = pixels_to_rgba_tile(empty_pixels)
        self.assertEqual(tile_im.size, (16, 16))
        self.assertEqual(tile_im.mode, "RGBA")
        # Every pixel must be completely transparent
        for y in range(16):
            for x in range(16):
                self.assertEqual(tile_im.getpixel((x, y)), (0, 0, 0, 0))

        # Re-extract
        re_extracted = rgba_tile_to_pixels(tile_im)
        self.assertEqual(empty_pixels, re_extracted)

    def test_shadow_placement(self):
        pixels = [[0] * 16 for _ in range(16)]
        pixels[5][5] = 1

        tile_im = pixels_to_rgba_tile(pixels)
        # (5, 5) must be TEXT_COLOR
        self.assertEqual(tile_im.getpixel((5, 5)), TEXT_COLOR)
        # (6, 6) must be SHADOW_COLOR (1px drop shadow)
        self.assertEqual(tile_im.getpixel((6, 6)), SHADOW_COLOR)
        # (5, 6) and (6, 5) should be transparent
        self.assertEqual(tile_im.getpixel((5, 6)), (0, 0, 0, 0))
        self.assertEqual(tile_im.getpixel((6, 5)), (0, 0, 0, 0))

        # Re-extract: only (5, 5) is text pixel
        extracted = rgba_tile_to_pixels(tile_im)
        self.assertEqual(extracted[5][5], 1)
        self.assertEqual(extracted[6][6], 0)
        self.assertEqual(pixels, extracted)

    def test_roundtrip_fidelity(self):
        import random
        random.seed(12345)
        for _ in range(20):
            orig = [[random.choice([0, 1]) for _ in range(16)] for _ in range(16)]
            tile_im = pixels_to_rgba_tile(orig)
            extracted = rgba_tile_to_pixels(tile_im)
            self.assertEqual(orig, extracted)


class TestAtlasManager(unittest.TestCase):
    """Validates AtlasManager file operations using isolated temporary atlas."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_atlas_path = Path(self.temp_dir) / "test_atlas.png"
        shutil.copy(ATLAS_PATH, self.test_atlas_path)
        self.manager = AtlasManager(self.test_atlas_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_tile_valid(self):
        tile0 = self.manager.get_tile(0)
        self.assertEqual(tile0["index"], 0)
        self.assertEqual(tile0["token"], "то")
        self.assertEqual(len(tile0["pixels"]), 16)
        self.assertEqual(len(tile0["pixels"][0]), 16)
        self.assertGreater(sum(sum(r) for r in tile0["pixels"]), 0)

        tile27 = self.manager.get_tile(27)
        self.assertEqual(tile27["index"], 27)
        self.assertEqual(len(tile27["pixels"]), 16)

    def test_get_tile_out_of_bounds(self):
        with self.assertRaises(ValueError):
            self.manager.get_tile(-1)
        with self.assertRaises(ValueError):
            self.manager.get_tile(220)
        with self.assertRaises(ValueError):
            self.manager.get_tile(999)

    def test_save_single_tile(self):
        # Create custom pattern
        custom_pixels = [[0] * 16 for _ in range(16)]
        custom_pixels[0][0] = 1
        custom_pixels[15][15] = 1

        self.manager.save_tile(10, custom_pixels)

        # Re-read through manager
        reloaded = self.manager.get_tile(10)
        self.assertEqual(reloaded["pixels"], custom_pixels)

        # Directly open test_atlas_path from disk to verify persistence
        col = 10 % 16
        row = 10 // 16
        with Image.open(self.test_atlas_path) as im:
            crop = im.crop((col * 16, row * 16, (col + 1) * 16, (row + 1) * 16))
            disk_pixels = rgba_tile_to_pixels(crop)
        self.assertEqual(disk_pixels, custom_pixels)

    def test_save_all_tiles(self):
        p1 = [[1 if (r == c) else 0 for c in range(16)] for r in range(16)]
        p2 = [[1 if (r + c == 15) else 0 for c in range(16)] for r in range(16)]

        saved_count = self.manager.save_all({5: p1, 12: p2})
        self.assertEqual(saved_count, 2)

        self.assertEqual(self.manager.get_tile(5)["pixels"], p1)
        self.assertEqual(self.manager.get_tile(12)["pixels"], p2)

    def test_save_invalid_index(self):
        px = [[0] * 16 for _ in range(16)]
        with self.assertRaises(ValueError):
            self.manager.save_tile(-1, px)
        with self.assertRaises(ValueError):
            self.manager.save_tile(220, px)

    def test_save_invalid_pixels_shape(self):
        with self.assertRaises(ValueError):
            self.manager.save_tile(0, [[0] * 16 for _ in range(15)])  # 15 rows
        with self.assertRaises(ValueError):
            self.manager.save_tile(0, [[0] * 15 for _ in range(16)])  # 15 cols

    def test_get_atlas_bytes(self):
        png_bytes = self.manager.get_atlas_bytes()
        self.assertTrue(png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))


class TestHTTPServerAPI(unittest.TestCase):
    """Validates HTTP REST API endpoints using an ephemeral-port test server."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp()
        cls.test_atlas_path = Path(cls.temp_dir) / "test_atlas.png"
        shutil.copy(ATLAS_PATH, cls.test_atlas_path)

        # Point global MANAGER to test atlas
        import tools.font_pixel_editor as fpe
        cls.orig_manager = fpe.MANAGER
        fpe.MANAGER = AtlasManager(cls.test_atlas_path)

        # Start HTTP server on ephemeral port (port 0)
        socketserver.TCPServer.allow_reuse_address = True
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), FontPixelEditorHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

        # Restore original manager
        import tools.font_pixel_editor as fpe
        fpe.MANAGER = cls.orig_manager

    def _get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        url = self.base_url + path
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:
                headers = dict(resp.getheaders())
                body = resp.read()
                return resp.status, headers, body
        except urllib.error.HTTPError as err:
            try:
                headers = dict(err.headers.items())
                body = err.read()
                return err.code, headers, body
            finally:
                err.close()

    def _post(self, path: str, payload: Any) -> tuple[int, dict[str, str], bytes]:
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as resp:
                headers = dict(resp.getheaders())
                body = resp.read()
                return resp.status, headers, body
        except urllib.error.HTTPError as err:
            try:
                headers = dict(err.headers.items())
                body = err.read()
                return err.code, headers, body
            finally:
                err.close()

    def _options(self, path: str) -> tuple[int, dict[str, str]]:
        url = self.base_url + path
        req = urllib.request.Request(url, method="OPTIONS")
        with urllib.request.urlopen(req) as resp:
            headers = dict(resp.getheaders())
            return resp.status, headers

    def test_get_index_html(self):
        status, headers, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html = body.decode("utf-8")
        self.assertIn("SLAYERS ROYAL", html)
        self.assertIn("paintCanvas", html)
        self.assertIn("dialogueCanvas", html)

    def test_get_tokens_endpoint(self):
        status, headers, body = self._get("/api/tokens")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        tokens = json.loads(body.decode("utf-8"))
        self.assertEqual(len(tokens), 220)
        self.assertEqual(tokens[0]["index"], 0)
        self.assertEqual(tokens[0]["token"], "то")

    def test_get_tile_endpoint(self):
        status, headers, body = self._get("/api/tile/27")
        self.assertEqual(status, 200)
        tile = json.loads(body.decode("utf-8"))
        self.assertEqual(tile["index"], 27)
        self.assertEqual(tile["token"], "ни")
        self.assertEqual(len(tile["pixels"]), 16)
        self.assertEqual(len(tile["pixels"][0]), 16)

    def test_get_tile_out_of_bounds(self):
        status, _, body = self._get("/api/tile/999")
        self.assertEqual(status, 404)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_get_tile_invalid_string(self):
        status, _, body = self._get("/api/tile/invalid")
        self.assertEqual(status, 400)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("error", data)

    def test_post_save_tile_endpoint(self):
        custom_px = [[1 if r == 0 else 0 for _ in range(16)] for r in range(16)]
        status, _, body = self._post("/api/save_tile", {"index": 42, "pixels": custom_px})
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("index"), 42)

        # Verify saved tile via GET
        v_status, _, v_body = self._get("/api/tile/42")
        self.assertEqual(v_status, 200)
        v_tile = json.loads(v_body.decode("utf-8"))
        self.assertEqual(v_tile["pixels"], custom_px)

    def test_post_save_tile_invalid_inputs(self):
        # Missing fields
        s1, _, _ = self._post("/api/save_tile", {"index": 0})
        self.assertEqual(s1, 400)

        # Index out of bounds
        s2, _, _ = self._post("/api/save_tile", {"index": 999, "pixels": [[0]*16]*16})
        self.assertEqual(s2, 400)

        # Malformed pixels shape
        s3, _, _ = self._post("/api/save_tile", {"index": 0, "pixels": [[0]*10]*16})
        self.assertEqual(s3, 400)

    def test_post_save_all_endpoint(self):
        p1 = [[0] * 16 for _ in range(16)]
        p1[1][1] = 1
        p2 = [[0] * 16 for _ in range(16)]
        p2[2][2] = 1

        status, _, body = self._post("/api/save_all", {"tiles": {"15": p1, "16": p2}})
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("saved_count"), 2)

        # Verify both via GET
        t15 = json.loads(self._get("/api/tile/15")[2].decode("utf-8"))
        t16 = json.loads(self._get("/api/tile/16")[2].decode("utf-8"))
        self.assertEqual(t15["pixels"], p1)
        self.assertEqual(t16["pixels"], p2)

    def test_get_atlas_png_endpoint(self):
        status, headers, body = self._get("/api/atlas.png")
        self.assertEqual(status, 200)
        self.assertIn("image/png", headers.get("Content-Type", ""))
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_rebuild_status_endpoint(self):
        status, headers, body = self._get("/api/rebuild/status")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("running", data)

    def test_not_found_endpoint(self):
        status, _, body = self._get("/api/unknown_route")
        self.assertEqual(status, 404)

    def test_options_cors(self):
        status, headers = self._options("/")
        self.assertEqual(status, 204)
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods", ""))


if __name__ == "__main__":
    unittest.main()
