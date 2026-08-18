"""
Module 4B - AI Disturbance Detection.

Isolation Forest, unsupervised - deliberately no labels of any kind, real
or pseudo. This sidesteps the "no verified ground truth exists" problem
entirely rather than training against Module 4's own NDVI-threshold
output (which would be circular - the model would just re-learn the
threshold rule, not add independent information).

Two windowed passes, so this never needs the full raster's feature matrix
in memory at once:
  1. sample_training_features(): a bounded random sample of change-vectors
     across the whole AOI, used to fit the model.
  2. score_raster(): re-reads the raster window by window, scores each
     pixel with the already-fitted model, writes a single-band anomaly
     score raster.
"""

import os
import numpy as np
import rasterio
from rasterio.windows import Window
from sklearn.ensemble import IsolationForest

from app.loss_detection.ai_features import (
    read_window_features, resolve_required_band_indices, N_FEATURES,
)

DEFAULT_N_SAMPLES = 200_000
DEFAULT_BLOCK_SIZE = 512
DEFAULT_CONTAMINATION = 0.05  # expected fraction of "anomalous" change, a modeling assumption, not a label
ANOMALY_NODATA = -1.0


def _iter_blocks(width, height, block_size):
    for row_off in range(0, height, block_size):
        for col_off in range(0, width, block_size):
            w = min(block_size, width - col_off)
            h = min(block_size, height - row_off)
            yield Window(col_off, row_off, w, h)


def sample_training_features(base_path, comp_path, n_samples=DEFAULT_N_SAMPLES, block_size=DEFAULT_BLOCK_SIZE, seed=42):
    """Windowed random sampling of change-vectors across the whole AOI,
    bounded to ~n_samples total regardless of raster size."""
    rng = np.random.default_rng(seed)

    with rasterio.open(base_path) as base_src, rasterio.open(comp_path) as comp_src:
        if base_src.width != comp_src.width or base_src.height != comp_src.height:
            raise ValueError(
                f"Base and comparison rasters have mismatched dimensions: "
                f"{base_src.width}x{base_src.height} vs {comp_src.width}x{comp_src.height}"
            )

        base_idx, base_scl = resolve_required_band_indices(base_src)
        comp_idx, comp_scl = resolve_required_band_indices(comp_src)

        windows = list(_iter_blocks(base_src.width, base_src.height, block_size))
        per_block_quota = max(1, n_samples // max(1, len(windows)))

        samples = []
        for window in windows:
            base_features, base_valid = read_window_features(base_src, window, base_idx, base_scl)
            comp_features, comp_valid = read_window_features(comp_src, window, comp_idx, comp_scl)

            valid = base_valid & comp_valid
            delta = (comp_features - base_features)[valid]

            if delta.shape[0] == 0:
                continue
            take = min(per_block_quota, delta.shape[0])
            chosen = rng.choice(delta.shape[0], size=take, replace=False)
            samples.append(delta[chosen])

        if not samples:
            raise ValueError("No valid (cloud-free, in-bounds) pixels found to sample for AI training.")

        return np.concatenate(samples, axis=0)


def train_isolation_forest(training_features, contamination=DEFAULT_CONTAMINATION, seed=42):
    model = IsolationForest(contamination=contamination, random_state=seed, n_jobs=-1)
    model.fit(training_features)
    return model


def score_raster(base_path, comp_path, model, output_path, block_size=DEFAULT_BLOCK_SIZE):
    """Second windowed pass: scores every pixel with the already-fitted
    model, writes a single-band float32 anomaly-score raster in [0, 1]
    (1 = most anomalous change), ANOMALY_NODATA where invalid/cloud-masked."""
    with rasterio.open(base_path) as base_src, rasterio.open(comp_path) as comp_src:
        base_idx, base_scl = resolve_required_band_indices(base_src)
        comp_idx, comp_scl = resolve_required_band_indices(comp_src)

        profile = comp_src.profile.copy()
        profile.update(count=1, dtype="float32", nodata=ANOMALY_NODATA)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        total_pixels = 0
        anomalous_pixels = 0
        all_scores = []

        with rasterio.open(output_path, "w", **profile) as dst:
            for window in _iter_blocks(comp_src.width, comp_src.height, block_size):
                base_features, base_valid = read_window_features(base_src, window, base_idx, base_scl)
                comp_features, comp_valid = read_window_features(comp_src, window, comp_idx, comp_scl)
                valid = base_valid & comp_valid

                delta = (comp_features - base_features).reshape(-1, N_FEATURES)
                flat_valid = valid.reshape(-1)

                score_block = np.full(flat_valid.shape[0], ANOMALY_NODATA, dtype="float32")

                if flat_valid.any():
                    # decision_function: higher = more normal. Flip and
                    # normalize to [0, 1] where 1 = most anomalous, so a
                    # bigger number consistently means "more unusual" -
                    # matches the intuitive direction of NDVI-diff severity.
                    raw = model.decision_function(delta[flat_valid])
                    normalized = np.clip((0.5 - raw), 0, None)
                    normalized = normalized / (normalized.max() + 1e-9)
                    score_block[flat_valid] = normalized.astype("float32")

                    total_pixels += flat_valid.sum()
                    anomalous_pixels += int((normalized > 0.5).sum())
                    all_scores.append(normalized)

                dst.write(score_block.reshape(valid.shape), 1, window=window)

    all_scores = np.concatenate(all_scores) if all_scores else np.array([])
    return {
        "output_path": output_path,
        "total_valid_pixels": int(total_pixels),
        "anomalous_pixel_count": anomalous_pixels,
        "anomaly_score_mean": float(all_scores.mean()) if all_scores.size else None,
        "anomaly_score_max": float(all_scores.max()) if all_scores.size else None,
    }


def run_ai_disturbance_detection(base_path, comp_path, output_path, n_samples=DEFAULT_N_SAMPLES, contamination=DEFAULT_CONTAMINATION):
    """Full Module 4B run: sample -> train -> score. No labels used
    anywhere in this function - purely unsupervised."""
    training_features = sample_training_features(base_path, comp_path, n_samples=n_samples)
    model = train_isolation_forest(training_features, contamination=contamination)
    stats = score_raster(base_path, comp_path, model, output_path)
    stats["training_sample_size"] = int(training_features.shape[0])
    stats["contamination_param"] = contamination
    return stats
