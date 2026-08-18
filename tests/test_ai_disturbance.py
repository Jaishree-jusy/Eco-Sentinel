"""
Tests for Module 4B - AI Disturbance Detection.

Uses small synthetic base/comparison raster pairs so tests don't need
your real 700MB Forest_Sample files. Includes a real correctness check:
a region with a deliberately unusual spectral change must score higher
than a region with no change - not just "the code runs without crashing."
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin
import pytest

from app.loss_detection.ai_features import compute_feature_stack, FEATURE_NAMES, N_FEATURES
from app.loss_detection.ai_disturbance import (
    sample_training_features, train_isolation_forest, score_raster,
    run_ai_disturbance_detection, ANOMALY_NODATA,
)

SPECTRAL_BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]


def _make_raster(path, height, width, band_values_fn, scl_value=4):
    """band_values_fn(band_name) -> 2D array for that band."""
    transform = from_origin(74.75, 13.0, 0.0001, 0.0001)
    band_names = SPECTRAL_BANDS + ["SCL"]
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=len(band_names),
        dtype="float64", crs="EPSG:4326", transform=transform,
    ) as dst:
        for i, name in enumerate(band_names, start=1):
            if name == "SCL":
                data = np.full((height, width), scl_value, dtype="float64")
            else:
                data = band_values_fn(name)
            dst.write(data, i)
            dst.set_band_description(i, name)


def test_compute_feature_stack_shape():
    band_values = {b: np.full((5, 5), 1000.0) for b in SPECTRAL_BANDS}
    band_values["B8"] = np.full((5, 5), 3000.0)
    band_values["B4"] = np.full((5, 5), 1000.0)
    stack = compute_feature_stack(band_values)
    assert stack.shape == (5, 5, N_FEATURES)
    ndvi_idx = FEATURE_NAMES.index("NDVI")
    expected_ndvi = (3000.0 - 1000.0) / (3000.0 + 1000.0)
    assert np.isclose(stack[0, 0, ndvi_idx], expected_ndvi)


def test_sample_training_features_shape(tmp_path):
    height, width = 40, 40

    def stable_values(band):
        return np.full((height, width), 1000.0)

    base_path = os.path.join(tmp_path, "base.tif")
    comp_path = os.path.join(tmp_path, "comp.tif")
    _make_raster(base_path, height, width, stable_values)
    _make_raster(comp_path, height, width, stable_values)

    samples = sample_training_features(base_path, comp_path, n_samples=500, block_size=16)
    assert samples.shape[1] == N_FEATURES
    assert samples.shape[0] > 0
    # No change anywhere -> all deltas should be ~zero
    assert np.allclose(samples, 0.0, atol=1e-6)


def test_ai_disturbance_flags_real_anomalous_region(tmp_path):
    """Real correctness test: a region where B8 (NIR) drops sharply between
    base and comparison (mimicking vegetation loss) must score as more
    anomalous than a region with no change at all."""
    height, width = 60, 60

    def base_values(band):
        return np.full((height, width), 1000.0)

    def comp_values_with_anomaly(band):
        arr = np.full((height, width), 1000.0)
        if band == "B8":
            arr[20:30, 20:30] = 200.0  # sharp NIR drop in one region
        return arr

    base_path = os.path.join(tmp_path, "base.tif")
    comp_path = os.path.join(tmp_path, "comp.tif")
    _make_raster(base_path, height, width, base_values)
    _make_raster(comp_path, height, width, comp_values_with_anomaly)

    output_path = os.path.join(tmp_path, "anomaly_score.tif")
    stats = run_ai_disturbance_detection(base_path, comp_path, output_path, n_samples=2000, contamination=0.1)

    assert os.path.exists(output_path)
    assert stats["anomaly_score_max"] is not None

    with rasterio.open(output_path) as src:
        scores = src.read(1)

    anomalous_region_score = scores[20:30, 20:30].mean()
    stable_region_score = scores[0:10, 0:10].mean()

    assert anomalous_region_score > stable_region_score


def test_sample_training_features_raises_when_all_cloud_masked(tmp_path):
    height, width = 20, 20

    def base_values(band):
        return np.full((height, width), 1000.0)

    base_path = os.path.join(tmp_path, "base.tif")
    comp_path = os.path.join(tmp_path, "comp.tif")
    _make_raster(base_path, height, width, base_values, scl_value=4)
    _make_raster(comp_path, height, width, base_values, scl_value=9)  # entirely cloud

    with pytest.raises(ValueError, match="No valid"):
        sample_training_features(base_path, comp_path, n_samples=100, block_size=10)


def test_dimension_mismatch_raises(tmp_path):
    def values(band):
        return np.full((20, 20), 1000.0)

    base_path = os.path.join(tmp_path, "base.tif")
    comp_path = os.path.join(tmp_path, "comp.tif")
    _make_raster(base_path, 20, 20, values)
    _make_raster(comp_path, 30, 30, lambda b: np.full((30, 30), 1000.0))

    with pytest.raises(ValueError, match="mismatched dimensions"):
        sample_training_features(base_path, comp_path)
