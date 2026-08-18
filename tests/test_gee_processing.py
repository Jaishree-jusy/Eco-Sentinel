"""
Tests for Module 3 - GEE Processing.

Uses a small synthetic 15-band raster (enough to cover B4=4, B8=8, SCL=15)
with known values, so we can assert exact expected NDVI/cloud-mask
behavior without needing your real 700MB files.
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.gee_processing.cloud_mask import build_cloud_mask, apply_mask
from app.gee_processing.ndvi import compute_ndvi_array, compute_ndvi_from_raw
from app.gee_processing.ndvi_diff import compute_ndvi_diff
from app.gee_processing.config import NDVI_NODATA, BAND_INDEX


def _make_synthetic_raw_tif(path, nir_value, red_value, scl_grid):
    """Creates a small 15-band GeoTIFF where every pixel has the same
    NIR/RED value, and SCL varies per-pixel per scl_grid (so we can test
    cloud masking precisely). Sets real band descriptions, matching how
    both historical and live-GEE files are actually structured, since
    bands are now resolved by name, not fixed position."""
    height, width = scl_grid.shape
    transform = from_origin(74.75, 13.0, 0.0001, 0.0001)
    band_names = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A",
                  "B9", "B11", "B12", "AOT", "WVP", "SCL"]

    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=15,
        dtype="float64", crs="EPSG:4326", transform=transform,
    ) as dst:
        for band_num in range(1, 16):
            name = band_names[band_num - 1]
            if name == "B8":
                data = np.full((height, width), nir_value, dtype="float64")
            elif name == "B4":
                data = np.full((height, width), red_value, dtype="float64")
            elif name == "SCL":
                data = scl_grid.astype("float64")
            else:
                data = np.zeros((height, width), dtype="float64")
            dst.write(data, band_num)
            dst.set_band_description(band_num, name)


def test_compute_ndvi_array_known_values():
    nir = np.array([[800.0, 200.0]])
    red = np.array([[200.0, 800.0]])
    cloud_mask = np.array([[False, False]])

    ndvi = compute_ndvi_array(nir, red, cloud_mask)

    # (800-200)/(800+200) = 0.6 ; (200-800)/(200+800) = -0.6
    assert np.isclose(ndvi[0, 0], 0.6, atol=1e-4)
    assert np.isclose(ndvi[0, 1], -0.6, atol=1e-4)


def test_compute_ndvi_array_masks_clouds():
    nir = np.array([[800.0, 800.0]])
    red = np.array([[200.0, 200.0]])
    cloud_mask = np.array([[False, True]])  # second pixel is cloud

    ndvi = compute_ndvi_array(nir, red, cloud_mask)

    assert np.isclose(ndvi[0, 0], 0.6, atol=1e-4)
    assert ndvi[0, 1] == NDVI_NODATA


def test_compute_ndvi_array_divide_by_zero_safe():
    nir = np.array([[0.0]])
    red = np.array([[0.0]])
    cloud_mask = np.array([[False]])

    ndvi = compute_ndvi_array(nir, red, cloud_mask)
    assert ndvi[0, 0] == NDVI_NODATA  # should not crash or produce NaN


def test_build_cloud_mask():
    scl = np.array([[4, 8], [9, 6]])  # vegetation, cloud-med, cloud-high, water
    mask = build_cloud_mask(scl)
    assert mask.tolist() == [[False, True], [True, False]]


def test_compute_ndvi_from_raw_end_to_end(tmp_path):
    # SCL: half vegetation (4), half cloud (9)
    scl_grid = np.array([[4, 9], [4, 9]])
    raw_path = os.path.join(tmp_path, "raw.tif")
    _make_synthetic_raw_tif(raw_path, nir_value=800.0, red_value=200.0, scl_grid=scl_grid)

    output_path = os.path.join(tmp_path, "ndvi_out.tif")
    stats = compute_ndvi_from_raw(raw_path, output_path)

    assert os.path.exists(output_path)
    assert stats["cloud_masked_pixels"] == 2  # two cloud pixels
    assert stats["valid_pixel_count"] == 2
    assert np.isclose(stats["ndvi_mean"], 0.6, atol=1e-4)

    with rasterio.open(output_path) as src:
        assert src.count == 1
        assert src.nodata == NDVI_NODATA


def test_compute_ndvi_diff(tmp_path):
    transform = from_origin(74.75, 13.0, 0.0001, 0.0001)
    base_path = os.path.join(tmp_path, "base.tif")
    comp_path = os.path.join(tmp_path, "comp.tif")
    diff_path = os.path.join(tmp_path, "diff.tif")

    base_data = np.array([[0.6, 0.5]], dtype="float32")
    comp_data = np.array([[0.2, NDVI_NODATA]], dtype="float32")  # vegetation loss + one nodata pixel

    for path, data in [(base_path, base_data), (comp_path, comp_data)]:
        with rasterio.open(
            path, "w", driver="GTiff", height=1, width=2, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform, nodata=NDVI_NODATA,
        ) as dst:
            dst.write(data, 1)

    stats = compute_ndvi_diff(base_path, comp_path, diff_path)

    with rasterio.open(diff_path) as src:
        result = src.read(1)

    assert np.isclose(result[0, 0], 0.2 - 0.6, atol=1e-4)  # vegetation loss = negative diff
    assert result[0, 1] == NDVI_NODATA  # nodata propagated
    assert stats["invalid_pixel_count"] == 1
