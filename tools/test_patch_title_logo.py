"""Unit tests for tools/patch_title_logo.py."""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
from PIL import Image
import numpy as np
import sys
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.patch_title_logo import (
    CLUT0_RGB,
    CLUT1_RGB,
    DEFAULT_LOGO_RU_PATH,
    DEFAULT_TARGET_BIN,
    extract_and_render_sprites,
    indices_to_bytes,
    patch_disc_title_logo,
    quantize_to_palette,
    verify_disc_title_logo,
)


class TestTitleLogoExtraction:
    """Test sprite extraction, scaling, and quantization."""

    def test_logo_artwork_exists(self):
        assert DEFAULT_LOGO_RU_PATH.is_file(), f"Missing {DEFAULT_LOGO_RU_PATH}"

    def test_extract_and_render_sprite_dimensions(self):
        p1, p2, sub, preview = extract_and_render_sprites()
        # Part 1: 136x54 px = 68 bytes/row * 54 rows = 3672 bytes
        assert len(p1) == 3672
        # Part 2: 136x54 px = 68 bytes/row * 54 rows = 3672 bytes
        assert len(p2) == 3672
        # Subtitle: 176x43 px = 88 bytes/row * 43 rows = 3784 bytes
        assert len(sub) == 3784
        # Preview dimensions
        assert preview.size == (320, 240)

    def test_quantize_palette_bounds(self):
        test_img = Image.new("RGBA", (10, 10), (255, 200, 0, 255))
        indices = quantize_to_palette(test_img, CLUT0_RGB)
        assert indices.shape == (10, 10)
        assert np.all(indices >= 0) and np.all(indices <= 15)

    def test_indices_to_bytes_roundtrip(self):
        arr = np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.uint8)
        raw = indices_to_bytes(arr)
        assert len(raw) == 4
        # Byte 0: (1) | (2 << 4) = 0x21
        assert raw[0] == 0x21
        # Byte 1: (3) | (4 << 4) = 0x43
        assert raw[1] == 0x43


    def test_rubaki_sprite_centering_and_seamless_seam(self):
        p1, p2, _, _ = extract_and_render_sprites()
        # Verify Part 1 (136x54) has left padding (first 20 pixels have no text)
        # In 4bpp, 10 bytes = 20 pixels
        for r in range(54):
            row_p1 = p1[r * 68 : (r + 1) * 68]
            # First 10 bytes (20 pixels) should be transparent (0x00)
            assert row_p1[:10] == b"\x00" * 10, f"Part 1 row {r} has non-zero pixels at far-left edge!"

        # Verify Part 2 (136x54) has right padding (last 10 bytes = 20 pixels)
        for r in range(54):
            row_p2 = p2[r * 68 : (r + 1) * 68]
            assert row_p2[-10:] == b"\x00" * 10, f"Part 2 row {r} has non-zero pixels at far-right edge!"

        # Verify seam continuity: in rows 10..45, neither side of the seam is empty
        p1_seam_active = sum(1 for r in range(10, 45) if p1[r * 68 + 67] != 0)
        p2_seam_active = sum(1 for r in range(10, 45) if p2[r * 68] != 0)
        assert p1_seam_active > 15, "Part 1 seam edge is unexpectedly empty"
        assert p2_seam_active > 15, "Part 2 seam edge is unexpectedly empty"

    def test_korolevskie_dimensions_and_position(self):
        _, _, sub, _ = extract_and_render_sprites()
        # 176x43 px = 88 bytes/row * 43 rows = 3784 bytes
        assert len(sub) == 3784
        # Subtitle should have content in central rows
        active_rows = sum(1 for r in range(43) if any(b != 0 for b in sub[r * 88 : (r + 1) * 88]))
        assert active_rows >= 25
class TestDiscTitleLogoPatching:
    """Test disc patching and EDC/ECC verification."""

    def test_verify_on_target_bin(self):
        if not DEFAULT_TARGET_BIN.is_file():
            pytest.skip("Target disc image not present")
        p1, p2, sub, _ = extract_and_render_sprites()
        assert verify_disc_title_logo(DEFAULT_TARGET_BIN, p1, p2, sub) is True


class TestSavestateTitleLogoSync:
    """Test DuckStation savestate RAM and VRAM synchronization."""

    def test_sync_mock_savestate(self, tmp_path):
        from tools.patch_title_logo import sync_savestate_title_logo
        import subprocess

        # Construct mock decomp with Bus chunk and VRAM chunk
        mock_decomp = bytearray(0x350000)
        # Bus chunk
        bus_name = b"Bus"
        mock_decomp[0x1000 : 0x1004] = len(bus_name).to_bytes(4, "little")
        mock_decomp[0x1004 : 0x1004 + len(bus_name)] = bus_name
        mock_decomp[0x1004 + len(bus_name) : 0x1004 + len(bus_name) + 4] = (0x200000).to_bytes(4, "little")
        # ram_start is at 0x1008 + len(bus_name) = 0x100B

        # VRAM chunk
        vram_idx = 0x220000
        mock_decomp[vram_idx : vram_idx + 4] = b"VRAM"
        res1 = subprocess.run(["zstd", "-1"], input=b"\x00" * (256 * 192 * 4), capture_output=True, check=True)
        res2 = subprocess.run(["zstd", "-1"], input=bytes(mock_decomp), capture_output=True, check=True)

        # Mock sav file with header + stream 1 (screenshot) + stream 2 (state)
        mock_sav = tmp_path / "SLPS-01363_1.sav"
        mock_sav.write_bytes(b"\x00" * 277 + res1.stdout + res2.stdout)

        p1, p2, sub, _ = extract_and_render_sprites()
        ok = sync_savestate_title_logo(mock_sav, p1, p2, sub, backup=False)
        assert ok is True

        # Decompress and verify VRAM
        updated_data = mock_sav.read_bytes()
        idx1 = updated_data.find(b"\x28\xb5\x2f\xfd")
        idx2 = updated_data.find(b"\x28\xb5\x2f\xfd", idx1 + 4)
        res_d = subprocess.run(["zstd", "-d"], input=updated_data[idx2:], capture_output=True, check=True)
        decomp_res = res_d.stdout

        vram_start = vram_idx + 8
        # Part 1 row 0
        assert decomp_res[vram_start + 512 * 2 : vram_start + 512 * 2 + 68] == p1[:68]
        # Part 2 row 0
        assert decomp_res[vram_start + 576 * 2 : vram_start + 576 * 2 + 68] == p2[:68]
