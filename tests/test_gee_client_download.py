"""
Tests for the tiled-download fix in gee_client.py.

The tile-grid math and mosaic assembly are tested for real (no mocking of
rasterio.merge - that's the actual logic that must be correct). Only the
network call (_download_single_tile) is mocked, since that's the one
piece requiring real GEE credentials.
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin
from unittest.mock import patch

from app.acquisition.gee_client import _compute_tile_bboxes, download_image, BAND_SET


def test_compute_tile_bboxes_grid_math():
    bbox = {"left": 0.0, "bottom": 0.0, "right": 6.0, "top": 6.0}
    tiles = _compute_tile_bboxes(bbox, grid=(3, 2))

    assert len(tiles) == 6
    assert all(abs((t["right"] - t["left"]) - 2.0) < 1e-9 for t in tiles)
    assert all(abs((t["top"] - t["bottom"]) - 3.0) < 1e-9 for t in tiles)

    assert min(t["left"] for t in tiles) == bbox["left"]
    assert max(t["right"] for t in tiles) == bbox["right"]
    assert min(t["bottom"] for t in tiles) == bbox["bottom"]
    assert max(t["top"] for t in tiles) == bbox["top"]


def test_compute_tile_bboxes_default_grid_produces_36_tiles():
    bbox = {"left": 74.75, "bottom": 12.60, "right": 75.10, "top": 13.00}
    tiles = _compute_tile_bboxes(bbox)
    assert len(tiles) == 36


def _make_fake_tile_bytes(left, bottom, right, top, width_px=10, height_px=10, fill_value=100.0):
    """Creates a real small GeoTIFF (as bytes) for one tile, matching what
    a real GEE tile response would look like: real georeferencing, real
    pixel data, correct band count."""
    transform = from_origin(left, top, (right - left) / width_px, (top - bottom) / height_px)
    with rasterio.io.MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff", height=height_px, width=width_px, count=len(BAND_SET),
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dataset:
            for i in range(1, len(BAND_SET) + 1):
                dataset.write(np.full((height_px, width_px), fill_value, dtype="float32"), i)
        return memfile.read()


def test_download_image_tiles_and_mosaics_correctly(tmp_path):
    """Real test of the actual fix: multiple tiles get correctly assembled
    into one larger, correctly-georeferenced mosaic - not just 'it runs'."""
    bbox = {"left": 74.0, "bottom": 12.0, "right": 74.02, "top": 12.02}

    call_count = {"n": 0}

    def fake_download_single_tile(image, tile_bbox, scale, session):
        call_count["n"] += 1
        return _make_fake_tile_bytes(
            tile_bbox["left"], tile_bbox["bottom"], tile_bbox["right"], tile_bbox["top"]
        )

    fake_image_info = {"_ee_image": type("FakeImage", (), {"select": lambda self, bands: self})()}

    output_path = os.path.join(tmp_path, "mosaic.tif")

    with patch("app.acquisition.gee_client._download_single_tile", side_effect=fake_download_single_tile):
        result_path = download_image(fake_image_info, bbox, output_path, tile_grid=(2, 2))

    assert call_count["n"] == 4
    assert os.path.exists(result_path)

    with rasterio.open(result_path) as src:
        assert src.count == len(BAND_SET)
        assert src.descriptions[0] == BAND_SET[0]
        assert src.descriptions[-1] == BAND_SET[-1]
        assert abs(src.bounds.left - bbox["left"]) < 0.001
        assert abs(src.bounds.right - bbox["right"]) < 0.001
        assert abs(src.bounds.bottom - bbox["bottom"]) < 0.001
        assert abs(src.bounds.top - bbox["top"]) < 0.001

        data = src.read(1)
        assert np.all(data == 100.0)
