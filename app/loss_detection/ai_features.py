"""
Feature engineering - Module 4B (AI disturbance detection).

Computes a 16-dimensional CHANGE vector per pixel (comparison_year minus
base_year, for each of 12 spectral bands + NDVI/NBR/NDWI/NDMI), not raw
spectral values in isolation. This is deliberate: a naturally bare/rocky
area would look spectrally "unusual" in a single image with zero actual
change, which would falsely flag it as disturbance. Scoring the CHANGE
vector means "anomalous" genuinely means "this pixel changed in an
unusual way" - directly analogous to what Module 4's NDVI-diff threshold
already does, just across a richer feature set instead of one scalar.
"""

import numpy as np

from app.gee_processing.band_resolver import resolve_band_indices
from app.gee_processing.cloud_mask import build_cloud_mask

SPECTRAL_BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B9", "B11", "B12"]
FEATURE_NAMES = SPECTRAL_BANDS + ["NDVI", "NBR", "NDWI", "NDMI"]
N_FEATURES = len(FEATURE_NAMES)


def _safe_index(a, b):
    denom = a + b
    with np.errstate(divide="ignore", invalid="ignore"):
        result = np.where(denom != 0, (a - b) / denom, 0.0)
    return np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)


def compute_feature_stack(band_values):
    """band_values: dict of band_name -> 2D array (a single window/read).
    Returns a (H, W, N_FEATURES) array in FEATURE_NAMES order."""
    b8, b4 = band_values["B8"], band_values["B4"]
    b3, b11, b12 = band_values["B3"], band_values["B11"], band_values["B12"]

    ndvi = _safe_index(b8, b4)
    nbr = _safe_index(b8, b12)
    ndwi = _safe_index(b3, b8)
    ndmi = _safe_index(b8, b11)

    layers = [band_values[b] for b in SPECTRAL_BANDS] + [ndvi, nbr, ndwi, ndmi]
    return np.stack(layers, axis=-1)


def read_window_features(src, window, band_indices, scl_index=None):
    """Reads one window from an open rasterio dataset and returns
    (feature_stack, valid_mask). valid_mask excludes cloud-masked pixels
    if an SCL band is available."""
    band_values = {name: src.read(idx, window=window).astype("float64") for name, idx in band_indices.items()}
    features = compute_feature_stack(band_values)

    if scl_index is not None:
        scl = src.read(scl_index, window=window)
        cloud_mask = build_cloud_mask(scl)
        valid_mask = ~cloud_mask
    else:
        valid_mask = np.ones(features.shape[:2], dtype=bool)

    return features, valid_mask


def resolve_required_band_indices(src):
    """Resolves the band indices needed for feature computation, by name -
    works identically for historical (26-band) and live-GEE (leaner) files."""
    needed = SPECTRAL_BANDS
    indices = resolve_band_indices(src, needed)
    scl_indices = resolve_band_indices(src, ["SCL"], required=False)
    scl_index = scl_indices.get("SCL")
    return indices, scl_index
