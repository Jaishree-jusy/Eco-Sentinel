"""
ECO-SENTINEL — Supervised Random Forest inference using the final
12-feature spatial-context model.

Final model:
    data/supervised/deforestation_rf_spatial_selected.joblib

The saved model bundle contains:
    - trained RandomForestClassifier
    - feature_columns
    - decision threshold (0.45)

Inference-time features are computed from Sentinel-2 2023/2025 rasters.
Hansen GFC is NOT used during inference.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import joblib
import numpy as np
import rasterio
from rasterio.windows import Window
from scipy.ndimage import median_filter, uniform_filter

from app.config import NDVI_PROCESSED_DIR
from app.loss_detection.ai_features import (
    FEATURE_NAMES,
    read_window_features,
    resolve_required_band_indices,
)


class SupervisedInferenceError(Exception):
    """Raised when supervised inference cannot be completed."""


# ---------------------------------------------------------------------
# FINAL MODEL
# ---------------------------------------------------------------------

MODEL_PATH = os.path.abspath(
    os.path.join(
        NDVI_PROCESSED_DIR,
        "..",
        "supervised",
        "deforestation_rf_spatial_selected.joblib",
    )
)

# The training pipeline used a 15 x 15 spatial context window.
SPATIAL_WINDOW = 15
HALO = SPATIAL_WINDOW // 2

# Exact feature order used by the final 90.51% model.
SELECTED_FEATURES = [
    "delta_B12",
    "delta_nbr",
    "delta_B1",
    "delta_B9",
    "nbr_local_median_2023",
    "delta_snbr",
    "delta_B11",
    "nbr_local_median_2025",
    "delta_B5",
    "snbr_2025",
    "delta_ndmi",
    "nbr_change_zscore",
]


# ---------------------------------------------------------------------
# MODEL LOADING
# ---------------------------------------------------------------------

def _load_model(model_path: str = MODEL_PATH):
    """
    Load the final saved model bundle.

    Returns:
        model: trained RandomForestClassifier
        threshold: saved probability threshold
        feature_columns: saved feature order
    """

    if not os.path.exists(model_path):
        raise SupervisedInferenceError(
            f"Trained supervised model not found: {model_path}"
        )

    try:
        bundle = joblib.load(model_path)
    except Exception as exc:
        raise SupervisedInferenceError(
            f"Could not load supervised model: {exc}"
        ) from exc

    # The final model was saved as a dictionary/bundle.
    if isinstance(bundle, dict):
        model = bundle.get("model")
        threshold = float(bundle.get("threshold", 0.45))
        feature_columns = bundle.get(
            "feature_columns",
            SELECTED_FEATURES,
        )
    else:
        # Defensive fallback for a plain classifier artifact.
        model = bundle
        threshold = 0.45
        feature_columns = SELECTED_FEATURES

    if model is None or not hasattr(model, "predict"):
        raise SupervisedInferenceError(
            "Loaded object is not a valid classifier."
        )

    feature_columns = list(feature_columns)

    if feature_columns != SELECTED_FEATURES:
        raise SupervisedInferenceError(
            "Model feature order does not match the final selected "
            f"feature set.\nExpected: {SELECTED_FEATURES}\n"
            f"Loaded: {feature_columns}"
        )

    if not 0.0 < threshold < 1.0:
        raise SupervisedInferenceError(
            f"Invalid model decision threshold: {threshold}"
        )

    return model, threshold, feature_columns


# ---------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------

def _safe_ratio(
    numerator: np.ndarray,
    denominator: np.ndarray,
) -> np.ndarray:
    """Match the training pipeline's safe-ratio behaviour."""

    result = np.zeros_like(
        numerator,
        dtype=np.float32,
    )

    valid = np.abs(denominator) > 1e-8

    np.divide(
        numerator,
        denominator,
        out=result,
        where=valid,
    )

    return result


def _feature_index(name: str) -> int:
    """
    Find a feature in FEATURE_NAMES without assuming its exact
    capitalization.
    """

    normalized = [str(item).strip().lower() for item in FEATURE_NAMES]
    target = name.strip().lower()

    if target not in normalized:
        raise SupervisedInferenceError(
            f"Required feature '{name}' was not found in "
            f"FEATURE_NAMES: {FEATURE_NAMES}"
        )

    return normalized.index(target)


def _crop_halo(
    array: np.ndarray,
    core_row_offset: int,
    core_col_offset: int,
    core_height: int,
    core_width: int,
) -> np.ndarray:
    """Crop the central/core raster window from a halo-expanded array."""

    return array[
        core_row_offset:core_row_offset + core_height,
        core_col_offset:core_col_offset + core_width,
    ]


# ---------------------------------------------------------------------
# SPATIAL-CONTEXT FEATURE ENGINEERING
# ---------------------------------------------------------------------

def _build_selected_features(
    base_features: np.ndarray,
    comparison_features: np.ndarray,
) -> np.ndarray:
    """
    Build the exact 12 features expected by the final model.

    Input feature stacks are the existing 16-feature Sentinel-2
    feature stacks returned by app.loss_detection.ai_features.

    Output shape:
        (rows, cols, 12)

    The spatial calculations intentionally match the training
    implementation:
        - 15 x 15 local NBR median
        - sNBR = centre NBR / local median NBR
        - delta_sNBR
        - NBR change z-score using local standard deviation
    """

    if base_features.shape != comparison_features.shape:
        raise SupervisedInferenceError(
            "Base and comparison feature stacks have different shapes."
        )

    if base_features.ndim != 3:
        raise SupervisedInferenceError(
            "Expected feature stacks with shape (rows, cols, features), "
            f"got {base_features.shape}."
        )

    rows, cols, feature_count = base_features.shape

    if feature_count != 16:
        raise SupervisedInferenceError(
            "The Sentinel-2 inference feature stack must contain "
            f"16 base features before spatial-context engineering; "
            f"got {feature_count}."
        )

    # Locate the four index features from the existing feature module.
    nbr_idx = _feature_index("NBR")

    # Existing 16-feature change stack.
    delta = (
        comparison_features.astype(np.float32)
        - base_features.astype(np.float32)
    )

    # NBR arrays for the two years.
    base_nbr = base_features[:, :, nbr_idx].astype(np.float32)
    comparison_nbr = comparison_features[:, :, nbr_idx].astype(np.float32)

    # Local median NBR.
    base_local_median = median_filter(
        base_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    ).astype(np.float32)

    comparison_local_median = median_filter(
        comparison_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    ).astype(np.float32)

    # Local variance/std — same first/second-moment method as training.
    base_mean = uniform_filter(
        base_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    )

    comparison_mean = uniform_filter(
        comparison_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    )

    base_sq_mean = uniform_filter(
        base_nbr * base_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    )

    comparison_sq_mean = uniform_filter(
        comparison_nbr * comparison_nbr,
        size=SPATIAL_WINDOW,
        mode="nearest",
    )

    base_local_std = np.sqrt(
        np.maximum(
            base_sq_mean - base_mean * base_mean,
            0.0,
        )
    ).astype(np.float32)

    comparison_local_std = np.sqrt(
        np.maximum(
            comparison_sq_mean - comparison_mean * comparison_mean,
            0.0,
        )
    ).astype(np.float32)

    # Spatially normalized NBR.
    base_snbr = _safe_ratio(
        base_nbr,
        base_local_median,
    )

    comparison_snbr = _safe_ratio(
        comparison_nbr,
        comparison_local_median,
    )

    delta_snbr = (
        comparison_snbr - base_snbr
    ).astype(np.float32)

    nbr_change = (
        comparison_nbr - base_nbr
    ).astype(np.float32)

    local_std = np.sqrt(
        0.5 * (
            base_local_std * base_local_std
            + comparison_local_std * comparison_local_std
        )
    ).astype(np.float32)

    nbr_change_zscore = _safe_ratio(
        nbr_change,
        local_std + np.float32(1e-3),
    ).astype(np.float32)

    # Map the original 16 change features by name.
    delta_by_name = {}

    for index, name in enumerate(FEATURE_NAMES):
        delta_by_name[f"delta_{name}"] = delta[:, :, index]

    # The training feature order is:
    # 16 original change features + 6 spatial-context features.
    feature_map = {
        "delta_B12": delta_by_name["delta_B12"],
        "delta_nbr": delta_by_name["delta_NBR"],
        "delta_B1": delta_by_name["delta_B1"],
        "delta_B9": delta_by_name["delta_B9"],
        "nbr_local_median_2023": base_local_median,
        "delta_snbr": delta_snbr,
        "delta_B11": delta_by_name["delta_B11"],
        "nbr_local_median_2025": comparison_local_median,
        "delta_B5": delta_by_name["delta_B5"],
        "snbr_2025": comparison_snbr,
        "delta_ndmi": delta_by_name["delta_NDMI"],
        "nbr_change_zscore": nbr_change_zscore,
    }

    selected = np.stack(
        [
            feature_map[name]
            for name in SELECTED_FEATURES
        ],
        axis=2,
    ).astype(np.float32)

    if selected.shape != (rows, cols, len(SELECTED_FEATURES)):
        raise SupervisedInferenceError(
            "Unexpected selected-feature shape: "
            f"{selected.shape}"
        )

    return selected


# ---------------------------------------------------------------------
# WINDOW PREDICTION
# ---------------------------------------------------------------------

def _predict_window(
    model,
    threshold: float,
    base_features: np.ndarray,
    comparison_features: np.ndarray,
    valid_mask: np.ndarray,
):
    """
    Predict one core raster window.

    Returns:
        prediction:
            0 = no deforestation
            1 = deforestation
            255 = nodata

        probability:
            0.0–1.0 = deforestation probability
            -9999 = nodata
    """

    selected_features = _build_selected_features(
        base_features,
        comparison_features,
    )

    height, width, feature_count = selected_features.shape

    if feature_count != len(SELECTED_FEATURES):
        raise SupervisedInferenceError(
            f"Expected {len(SELECTED_FEATURES)} selected features, "
            f"got {feature_count}."
        )

    if valid_mask.shape != (height, width):
        raise SupervisedInferenceError(
            "Valid mask shape does not match feature shape."
        )

    flattened = selected_features.reshape(
        -1,
        feature_count,
    )

    flattened_valid = valid_mask.reshape(-1)

    prediction = np.full(
        height * width,
        255,
        dtype=np.uint8,
    )

    probability = np.full(
        height * width,
        -9999.0,
        dtype=np.float32,
    )

    if not np.any(flattened_valid):
        return (
            prediction.reshape(height, width),
            probability.reshape(height, width),
        )

    X = flattened[flattened_valid]

    if not hasattr(model, "predict_proba"):
        raise SupervisedInferenceError(
            "Final Random Forest must support predict_proba()."
        )

    probabilities = model.predict_proba(X)

    classes = list(model.classes_)

    if 1 not in classes:
        raise SupervisedInferenceError(
            "The trained model does not contain class 1 (deforestation)."
        )

    deforestation_index = classes.index(1)

    deforestation_probability = probabilities[
        :, deforestation_index
    ].astype(np.float32)

    # IMPORTANT:
    # Use the saved 0.45 threshold from the final evaluation rather
    # than model.predict(), whose default classifier threshold is 0.50.
    predicted = (
        deforestation_probability >= threshold
    ).astype(np.uint8)

    prediction[flattened_valid] = predicted
    probability[flattened_valid] = deforestation_probability

    return (
        prediction.reshape(height, width),
        probability.reshape(height, width),
    )


# ---------------------------------------------------------------------
# MAIN INFERENCE FUNCTION
# ---------------------------------------------------------------------

def run_supervised_inference(
    base_path: str,
    comparison_path: str,
    prediction_output_path: str,
    probability_output_path: str,
    model_path: str = MODEL_PATH,
    window_size: int = 512,
) -> dict:
    """
    Run the final 90.51% Random Forest over the complete
    Sentinel-2 base/comparison raster pair.

    The raster is processed window-by-window. Each 512x512 core window
    is read with a 7-pixel halo on every side so that the 15x15 spatial
    context calculation is not artificially cut at tile boundaries.

    Creates:
        prediction raster:
            0 = no deforestation
            1 = deforestation
            255 = nodata

        probability raster:
            0.0–1.0 = deforestation probability
            -9999 = nodata
    """

    if window_size <= 0:
        raise SupervisedInferenceError(
            f"window_size must be positive, got {window_size}."
        )

    model, threshold, feature_columns = _load_model(
        model_path
    )

    if not os.path.exists(base_path):
        raise SupervisedInferenceError(
            f"Base raster not found: {base_path}"
        )

    if not os.path.exists(comparison_path):
        raise SupervisedInferenceError(
            f"Comparison raster not found: {comparison_path}"
        )

    prediction_dir = os.path.dirname(
        os.path.abspath(prediction_output_path)
    )

    probability_dir = os.path.dirname(
        os.path.abspath(probability_output_path)
    )

    os.makedirs(
        prediction_dir,
        exist_ok=True,
    )

    os.makedirs(
        probability_dir,
        exist_ok=True,
    )

    total_valid_pixels = 0
    total_deforestation_pixels = 0

    with rasterio.open(base_path) as base_src, \
            rasterio.open(comparison_path) as comparison_src:

        # -------------------------------------------------------------
        # Raster alignment validation
        # -------------------------------------------------------------

        if base_src.width != comparison_src.width:
            raise SupervisedInferenceError(
                "Base and comparison raster widths differ."
            )

        if base_src.height != comparison_src.height:
            raise SupervisedInferenceError(
                "Base and comparison raster heights differ."
            )

        if base_src.crs != comparison_src.crs:
            raise SupervisedInferenceError(
                "Base and comparison CRS differ."
            )

        if base_src.transform != comparison_src.transform:
            raise SupervisedInferenceError(
                "Base and comparison transforms differ."
            )

        if base_src.bounds != comparison_src.bounds:
            raise SupervisedInferenceError(
                "Base and comparison bounds differ."
            )

        base_band_indices, base_scl_index = (
            resolve_required_band_indices(base_src)
        )

        comparison_band_indices, comparison_scl_index = (
            resolve_required_band_indices(comparison_src)
        )

        # -------------------------------------------------------------
        # Output raster profiles
        # -------------------------------------------------------------

        prediction_profile = base_src.profile.copy()

        prediction_profile.update(
            dtype="uint8",
            count=1,
            nodata=255,
            compress="deflate",
        )

        probability_profile = base_src.profile.copy()

        probability_profile.update(
            dtype="float32",
            count=1,
            nodata=-9999.0,
            compress="deflate",
        )

        with rasterio.open(
            prediction_output_path,
            "w",
            **prediction_profile,
        ) as prediction_dst, rasterio.open(
            probability_output_path,
            "w",
            **probability_profile,
        ) as probability_dst:

            # ---------------------------------------------------------
            # Window-by-window inference
            # ---------------------------------------------------------

            for row_start in range(
                0,
                base_src.height,
                window_size,
            ):

                core_height = min(
                    window_size,
                    base_src.height - row_start,
                )

                for col_start in range(
                    0,
                    base_src.width,
                    window_size,
                ):

                    core_width = min(
                        window_size,
                        base_src.width - col_start,
                    )

                    core_window = Window(
                        col_start,
                        row_start,
                        core_width,
                        core_height,
                    )

                    # -------------------------------------------------
                    # Expand by a 7-pixel halo.
                    #
                    # A 15x15 filter needs 7 pixels on either side.
                    # The expanded window is clipped to the raster
                    # boundaries.
                    # -------------------------------------------------

                    halo_row_start = max(
                        0,
                        row_start - HALO,
                    )

                    halo_col_start = max(
                        0,
                        col_start - HALO,
                    )

                    halo_row_end = min(
                        base_src.height,
                        row_start + core_height + HALO,
                    )

                    halo_col_end = min(
                        base_src.width,
                        col_start + core_width + HALO,
                    )

                    halo_window = Window(
                        halo_col_start,
                        halo_row_start,
                        halo_col_end - halo_col_start,
                        halo_row_end - halo_row_start,
                    )

                    base_features_halo, base_valid_halo = (
                        read_window_features(
                            base_src,
                            halo_window,
                            base_band_indices,
                            base_scl_index,
                        )
                    )

                    comparison_features_halo, comparison_valid_halo = (
                        read_window_features(
                            comparison_src,
                            halo_window,
                            comparison_band_indices,
                            comparison_scl_index,
                        )
                    )

                    # -------------------------------------------------
                    # Calculate spatial features over the halo, then
                    # crop the result back to the core window.
                    # -------------------------------------------------

                    core_row_offset = (
                        row_start - halo_row_start
                    )

                    core_col_offset = (
                        col_start - halo_col_start
                    )

                    base_features = _crop_halo(
                        base_features_halo,
                        core_row_offset,
                        core_col_offset,
                        core_height,
                        core_width,
                    )

                    comparison_features = _crop_halo(
                        comparison_features_halo,
                        core_row_offset,
                        core_col_offset,
                        core_height,
                        core_width,
                    )

                    base_valid = _crop_halo(
                        base_valid_halo,
                        core_row_offset,
                        core_col_offset,
                        core_height,
                        core_width,
                    )

                    comparison_valid = _crop_halo(
                        comparison_valid_halo,
                        core_row_offset,
                        core_col_offset,
                        core_height,
                        core_width,
                    )

                    valid_mask = (
                        base_valid
                        & comparison_valid
                    )

                    prediction, probability = _predict_window(
                        model,
                        threshold,
                        base_features,
                        comparison_features,
                        valid_mask,
                    )

                    prediction_dst.write(
                        prediction,
                        1,
                        window=core_window,
                    )

                    probability_dst.write(
                        probability,
                        1,
                        window=core_window,
                    )

                    valid_count = int(
                        np.count_nonzero(valid_mask)
                    )

                    deforestation_count = int(
                        np.count_nonzero(
                            prediction == 1
                        )
                    )

                    total_valid_pixels += valid_count
                    total_deforestation_pixels += (
                        deforestation_count
                    )

    total_pixels = (
        base_src.width
        * base_src.height
    )

    return {
        "model": "RandomForestClassifier",
        "model_path": model_path,
        "base_path": base_path,
        "comparison_path": comparison_path,
        "prediction_output": prediction_output_path,
        "probability_output": probability_output_path,
        "feature_count": len(feature_columns),
        "features": feature_columns,
        "threshold": float(threshold),
        "spatial_context_window": SPATIAL_WINDOW,
        "spatial_context_halo": HALO,
        "total_pixels": int(total_pixels),
        "valid_pixels": int(total_valid_pixels),
        "deforestation_pixels": int(
            total_deforestation_pixels
        ),
        "deforestation_pixel_ratio": (
            float(total_deforestation_pixels)
            / float(total_valid_pixels)
            if total_valid_pixels
            else 0.0
        ),
        "processed_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }
