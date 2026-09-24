#!/usr/bin/env python3
"""Comprehensive test suite for tools/web_translation_editor.py.

Validates:
1. Hardware Limits Validation Engine (line limits, char limits, page break restrictions, NFC).
2. CatalogManager: loading all 11 catalogs, query filtering (search, scene, speaker, issues_only, pagination).
3. Atomic entry editing and disk persistence without corruption.
4. HTTP Server REST API:
   - GET / -> 200 OK (HTML Single Page Application)
   - GET /api/catalogs -> 200 OK (all catalogs metadata and issue counts)
   - GET /api/catalog/<cat_id> -> 200 OK (paginated entries, precomputed validation)
   - GET /api/issues -> 200 OK (all issues across catalogs)
   - GET /api/stats -> 200 OK (global statistics)
   - POST /api/entry -> 200 OK (atomic update and revalidation)
   - 404 handling on unknown routes.
"""

from __future__ import annotations

import copy
import json
import shutil
import socketserver
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from tools.web_translation_editor import (
    CATALOG_DEFS,
    CatalogManager,
    MANAGER,
    TranslationEditorHandler,
    clean_length,
    validate_text,
)


class TestHardwareLimitsValidation(unittest.TestCase):
    """Test validation engine rules and hardware limit enforcement."""

    def test_story_dialogues_limits(self):
        limits = CATALOG_DEFS["story_dialogues"]["limits"]

        # Valid text: 2 lines, <= 15 chars each
        v_ok = validate_text("Лина:\nПривет!", limits)
        self.assertTrue(v_ok["is_valid"])
        self.assertFalse(v_ok["exceeds_limits"])
        self.assertEqual(len(v_ok["errors"]), 0)

        # Exceeds 15 chars on a line
        v_long = validate_text("Строка текста длиннее 15 символов", limits)
        self.assertFalse(v_long["is_valid"])
        self.assertTrue(v_long["exceeds_limits"])
        self.assertTrue(any("макс. 15" in err for err in v_long["errors"]))

        # Exceeds 3 lines on a page
        v_lines = validate_text("Строка 1\nСтрока 2\nСтрока 3\nСтрока 4", limits)
        self.assertFalse(v_lines["is_valid"])
        self.assertTrue(any("максимум 3" in err for err in v_lines["errors"]))

        # Disallow page break when allow_page_break=False
        lim_no_pb = dict(limits)
        lim_no_pb["allow_page_break"] = False
        v_pb = validate_text("Стр 1\fСтр 2", lim_no_pb)
        self.assertFalse(v_pb["is_valid"])
        self.assertTrue(any("Разделение на страницы (\\f) запрещено" in err for err in v_pb["errors"]))

        # Empty line prohibited in dialogue
        v_empty = validate_text("Строка 1\n\nСтрока 2", limits)
        self.assertFalse(v_empty["is_valid"])
        self.assertTrue(any("пустая" in err for err in v_empty["errors"]))

    def test_room_names_limits(self):
        limits = CATALOG_DEFS["room_names"]["limits"]

        # Valid: single line <= 10 chars
        v_ok = validate_text("ГЛ.УЛИЦА", limits)
        self.assertTrue(v_ok["is_valid"])

        # Exceeds 10 chars
        v_long = validate_text("ОЧЕНЬ ДЛИННАЯ УЛИЦА", limits)
        self.assertFalse(v_long["is_valid"])
        self.assertTrue(any("превышает лимит 10" in err for err in v_long["errors"]))

        # Prohibit newlines in single-line field
        v_nl = validate_text("Улица\nГорода", limits)
        self.assertFalse(v_nl["is_valid"])
        self.assertTrue(any("Переносы строк не допускаются" in err for err in v_nl["errors"]))

    def test_world_map_limits(self):
        limits = CATALOG_DEFS["world_map"]["limits"]

        # Valid: <= 14 chars
        v_ok = validate_text("ЛЕЙКВУД", limits)
        self.assertTrue(v_ok["is_valid"])

        # Exceeds 14 chars
        v_long = validate_text("В. ЛЕС БАРКЛЕНДА", limits)
        self.assertFalse(v_long["is_valid"])
        self.assertTrue(any("превышает лимит 14" in err for err in v_long["errors"]))

    def test_combat_dialogues_limits(self):
        limits = CATALOG_DEFS["combat_dialogues"]["limits"]

        # <= 21 chars/line, <= 3 lines/bubble
        v_ok = validate_text("Лина:\nВ атаку!\nПо коням!", limits)
        self.assertTrue(v_ok["is_valid"])

        v_long = validate_text("Эта строка существенно длиннее двадцати одного символа", limits)
        self.assertFalse(v_long["is_valid"])
        self.assertTrue(any("макс. 21" in err for err in v_long["errors"]))


class TestCatalogManager(unittest.TestCase):
    """Test CatalogManager operations and queries."""

    def test_all_11_catalogs_present(self):
        self.assertEqual(len(CATALOG_DEFS), 11)
        stats = MANAGER.get_stats()
        self.assertEqual(stats["total_catalogs"], 11)
        self.assertGreater(stats["total_entries"], 6000)

    def test_query_story_dialogues_with_pagination(self):
        res = MANAGER.query_catalog("story_dialogues", page=1, limit=20)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["limit"], 20)
        self.assertEqual(len(res["entries"]), 20)
        self.assertGreater(res["total_entries"], 4000)
        self.assertEqual(len(res["scenes"]), 30)

    def test_query_search_filter(self):
        res = MANAGER.query_catalog("story_dialogues", search="Лина", page=1, limit=10)
        self.assertGreater(res["filtered_entries"], 0)
        for e in res["entries"]:
            text_combo = (e["text_ru"] + e["speaker_ru"] + e["speaker"] + e["id"]).lower()
            self.assertIn("лина", text_combo)

    def test_get_all_issues(self):
        issues_res = MANAGER.get_all_issues()
        self.assertIn("total_issues", issues_res)
        self.assertIn("catalogs", issues_res)
        self.assertIn("issues", issues_res)
        # We know world_map and location_banners have known limit exceedances
        self.assertGreaterEqual(issues_res["total_issues"], 5)
        self.assertGreaterEqual(issues_res["catalogs"]["world_map"], 4)
        self.assertGreaterEqual(issues_res["catalogs"]["location_banners"], 1)

    def test_atomic_entry_update_and_restore(self):
        # Work in an isolated temp directory copy to guarantee zero side effects
        temp_dir = Path(tempfile.mkdtemp(prefix="test_trans_"))
        try:
            # Copy world_map_ru.json to temp
            src_file = MANAGER.translations_dir / "world_map_ru.json"
            dst_file = temp_dir / "world_map_ru.json"
            shutil.copy2(src_file, dst_file)

            custom_mgr = CatalogManager(translations_dir=temp_dir)
            entries_before = custom_mgr.get_all_entries("world_map")
            lakewood = next(e for e in entries_before if e["id"] == "LAKEWOOD")
            self.assertEqual(lakewood["text_ru"], "ЛЕЙКВУД")

            # Update entry
            updated = custom_mgr.update_entry("world_map", "LAKEWOOD", "НОВЫЙ ЛЕЙКВУД")
            self.assertEqual(updated["text_ru"], "НОВЫЙ ЛЕЙКВУД")

            # Verify saved on disk
            with open(dst_file, "r", encoding="utf-8") as fp:
                saved_json = json.load(fp)
            loc = next(l for l in saved_json["locations"] if l["id"] == "LAKEWOOD")
            self.assertEqual(loc["text_ru"], "НОВЫЙ ЛЕЙКВУД")
        finally:
            shutil.rmtree(temp_dir)

    def test_update_entries_batch_single_catalog(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="test_batch_single_"))
        try:
            src_file = MANAGER.translations_dir / "world_map_ru.json"
            dst_file = temp_dir / "world_map_ru.json"
            shutil.copy2(src_file, dst_file)

            custom_mgr = CatalogManager(translations_dir=temp_dir)
            items = [
                {"catalog_id": "world_map", "id": "LAKEWOOD", "text_ru": "НОВЫЙ ЛЕЙКВУД"},
                {"catalog_id": "world_map", "id": "BARKLAND", "text_ru": "НОВЫЙ БАРКЛЕНД"},
            ]
            res = custom_mgr.update_entries_batch(items)
            self.assertTrue(res["success"])
            self.assertEqual(res["updated_count"], 2)
            self.assertEqual(res["catalogs_updated"], ["world_map"])
            self.assertEqual(len(res["entries"]), 2)

            with open(dst_file, "r", encoding="utf-8") as fp:
                saved_json = json.load(fp)
            locs = {l["id"]: l["text_ru"] for l in saved_json["locations"]}
            self.assertEqual(locs["LAKEWOOD"], "НОВЫЙ ЛЕЙКВУД")
            self.assertEqual(locs["BARKLAND"], "НОВЫЙ БАРКЛЕНД")
        finally:
            shutil.rmtree(temp_dir)

    def test_update_entries_batch_multiple_catalogs(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="test_batch_multi_"))
        try:
            shutil.copy2(MANAGER.translations_dir / "world_map_ru.json", temp_dir / "world_map_ru.json")
            shutil.copy2(MANAGER.translations_dir / "room_names_ru.json", temp_dir / "room_names_ru.json")

            custom_mgr = CatalogManager(translations_dir=temp_dir)
            items = [
                {"catalog_id": "world_map", "id": "LAKEWOOD", "text_ru": "ПАКЕТ_ЛЕЙКВУД"},
                {"catalog_id": "room_names", "id": "0x059", "text_ru": "ВХОД ТЕСТ"},
            ]
            res = custom_mgr.update_entries_batch(items)
            self.assertTrue(res["success"])
            self.assertEqual(res["updated_count"], 2)
            self.assertIn("world_map", res["catalogs_updated"])
            self.assertIn("room_names", res["catalogs_updated"])

            with open(temp_dir / "world_map_ru.json", "r", encoding="utf-8") as fp:
                map_json = json.load(fp)
            with open(temp_dir / "room_names_ru.json", "r", encoding="utf-8") as fp:
                room_json = json.load(fp)

            lakewood = next(l for l in map_json["locations"] if l["id"] == "LAKEWOOD")
            self.assertEqual(lakewood["text_ru"], "ПАКЕТ_ЛЕЙКВУД")
            self.assertEqual(room_json["entries"]["0x059"]["name_ru"], "ВХОД ТЕСТ")
        finally:
            shutil.rmtree(temp_dir)

    def test_update_entries_batch_empty_and_unknown(self):
        temp_dir = Path(tempfile.mkdtemp(prefix="test_batch_empty_"))
        try:
            custom_mgr = CatalogManager(translations_dir=temp_dir)
            # Empty list
            res_empty = custom_mgr.update_entries_batch([])
            self.assertTrue(res_empty["success"])
            self.assertEqual(res_empty["updated_count"], 0)
            self.assertEqual(res_empty["catalogs_updated"], [])

            # Unknown catalog or entry
            res_unknown = custom_mgr.update_entries_batch([
                {"catalog_id": "nonexistent_catalog", "id": "FOO", "text_ru": "BAR"},
            ])
            self.assertTrue(res_unknown["success"])
            self.assertEqual(res_unknown["updated_count"], 0)
        finally:
            shutil.rmtree(temp_dir)


class TestHttpServer(unittest.TestCase):
    """Test HTTP Server REST API endpoints."""

    @classmethod
    def setUpClass(cls):
        # Start server in daemon background thread on an ephemeral port
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), TranslationEditorHandler)
        cls.server.allow_reuse_address = True
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = dict(resp.getheaders())
                body = resp.read()
                return resp.status, headers, body
        except urllib.error.HTTPError as exc:
            code = exc.code
            hdrs = dict(exc.headers)
            body = exc.read()
            exc.close()
            return code, hdrs, body

    def _post(self, path: str, data: dict) -> tuple[int, dict[str, str], bytes]:
        url = f"http://127.0.0.1:{self.port}{path}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = dict(resp.getheaders())
                body = resp.read()
                return resp.status, headers, body
        except urllib.error.HTTPError as exc:
            code = exc.code
            hdrs = dict(exc.headers)
            body = exc.read()
            exc.close()
            return code, hdrs, body

    def test_root_returns_html_spa(self):
        status, headers, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        html = body.decode("utf-8")
        self.assertIn("Slayers Royal", html)
        self.assertIn("Translation Studio", html)
        self.assertIn("ruEditorTextarea", html)
        self.assertIn("ps1-sim-container", html)
        self.assertIn("ps1PageIndicator", html)
        # Verify ps1PageIndicator is located after ps1-dialogue-window closing tag
        dialogue_idx = html.find('class="ps1-dialogue-window"')
        close_dialogue_idx = html.find('</div>', dialogue_idx)
        indicator_idx = html.find('id="ps1PageIndicator"')
        self.assertGreater(indicator_idx, close_dialogue_idx)

        # Verify arrow navigation, escape shortcut, and scrollIntoView features
        self.assertIn("selectNextEntry()", html)
        self.assertIn("selectPrevEntry()", html)
        self.assertIn("scrollIntoView", html)
        self.assertIn("ruEditorTextarea", html)
        self.assertIn("ArrowDown", html)
        self.assertIn("ArrowUp", html)
        self.assertIn("Escape", html)

    def test_api_catalogs(self):
        status, headers, body = self._get("/api/catalogs")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers.get("Content-Type", ""))
        data = json.loads(body.decode("utf-8"))
        self.assertIn("catalogs", data)
        self.assertEqual(data["total_catalogs"], 11)

    def test_api_catalog_entries(self):
        status, headers, body = self._get("/api/catalog/story_dialogues?limit=5")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(len(data["entries"]), 5)
        self.assertIn("limits", data["entries"][0])
        self.assertIn("validation", data["entries"][0])

    def test_api_issues(self):
        status, headers, body = self._get("/api/issues")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("total_issues", data)
        self.assertIn("issues", data)
        self.assertGreater(data["total_issues"], 0)

    def test_api_stats(self):
        status, headers, body = self._get("/api/stats")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("total_entries", data)
        self.assertGreater(data["total_entries"], 6000)

    def test_api_entry_update_and_restore(self):
        # Read current entry
        status, _, body = self._get("/api/catalog/room_names?limit=1")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        first_entry = data["entries"][0]
        orig_text = first_entry["text_ru"]
        cat_id = first_entry["catalog_id"]
        entry_id = first_entry["id"]

        # POST update
        status, _, post_body = self._post(
            "/api/entry",
            {"catalog_id": cat_id, "id": entry_id, "text_ru": "ТЕСТ_КОМН"},
        )
        self.assertEqual(status, 200)
        post_data = json.loads(post_body.decode("utf-8"))
        self.assertTrue(post_data["success"])
        self.assertEqual(post_data["entry"]["text_ru"], "ТЕСТ_КОМН")

        # Restore original text
        status, _, restore_body = self._post(
            "/api/entry",
            {"catalog_id": cat_id, "id": entry_id, "text_ru": orig_text},
        )
        self.assertEqual(status, 200)
        restore_data = json.loads(restore_body.decode("utf-8"))
        self.assertEqual(restore_data["entry"]["text_ru"], orig_text)


    def test_api_batch_save_and_restore(self):
        # Read two entries from room_names
        status, _, body = self._get("/api/catalog/room_names?limit=2")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        e1 = data["entries"][0]
        e2 = data["entries"][1]
        orig_text1 = e1["text_ru"]
        orig_text2 = e2["text_ru"]

        # POST batch_save
        status, _, post_body = self._post(
            "/api/batch_save",
            {
                "items": [
                    {"catalog_id": e1["catalog_id"], "id": e1["id"], "text_ru": "ТЕСТ_БАТЧ1"},
                    {"catalog_id": e2["catalog_id"], "id": e2["id"], "text_ru": "ТЕСТ_БАТЧ2"},
                ]
            },
        )
        self.assertEqual(status, 200)
        post_data = json.loads(post_body.decode("utf-8"))
        self.assertTrue(post_data["success"])
        self.assertEqual(post_data["updated_count"], 2)
        self.assertIn("room_names", post_data["catalogs_updated"])

        # Verify via GET
        status, _, verify_body = self._get("/api/catalog/room_names?limit=2")
        self.assertEqual(status, 200)
        verify_data = json.loads(verify_body.decode("utf-8"))
        self.assertEqual(verify_data["entries"][0]["text_ru"], "ТЕСТ_БАТЧ1")
        self.assertEqual(verify_data["entries"][1]["text_ru"], "ТЕСТ_БАТЧ2")

        # Restore original texts via batch_save
        status, _, restore_body = self._post(
            "/api/batch_save",
            {
                "items": [
                    {"catalog_id": e1["catalog_id"], "id": e1["id"], "text_ru": orig_text1},
                    {"catalog_id": e2["catalog_id"], "id": e2["id"], "text_ru": orig_text2},
                ]
            },
        )
        self.assertEqual(status, 200)
        restore_data = json.loads(restore_body.decode("utf-8"))
        self.assertTrue(restore_data["success"])
        self.assertEqual(restore_data["updated_count"], 2)

        # Confirm restored
        status, _, final_body = self._get("/api/catalog/room_names?limit=2")
        self.assertEqual(status, 200)
        final_data = json.loads(final_body.decode("utf-8"))
        self.assertEqual(final_data["entries"][0]["text_ru"], orig_text1)
        self.assertEqual(final_data["entries"][1]["text_ru"], orig_text2)

    def test_api_batch_save_empty_and_list_payload(self):
        # Test empty payload items
        status, _, body = self._post("/api/batch_save", {"items": []})
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["success"])
        self.assertEqual(data["updated_count"], 0)

        # Test direct list payload
        status, _, body2 = self._post("/api/batch_save", [])
        self.assertEqual(status, 200)
        data2 = json.loads(body2.decode("utf-8"))
        self.assertTrue(data2["success"])
        self.assertEqual(data2["updated_count"], 0)
    def test_not_found_route(self):
        status, _, body = self._get("/api/nonexistent")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
