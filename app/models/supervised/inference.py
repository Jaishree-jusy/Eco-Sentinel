"""
Supervised deforestation inference for ECO-SENTINEL.

Uses the trained Random Forest model to classify Sentinel-2 change
pixels as:

    0 = no deforestation
    1 = deforestation

The model expects the same 16 CHANGE features used during training:

    comparison_year feature - base_year feature

The existing Module 4B feature engineering is reused so the
mathematical definitions of NDVI/NBR/NDWI/NDMI and cloud masking
remain consistent.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import joblib
import numpy as np
import rasterio

from app.config import NDVI_PROCESSED_DIR
from app.loss_detection.ai_features import (
    FEATURE_NAMES,
    resolve_required_band_indices,
    read_window_features,
)
from app.models.supervised.random_forest import (
    FEATURE_COLUMNS,
)


class SupervisedInferenceError(Exception):
    pass


MODEL_PATH = os.path.join(
    NDVI_PROCESSED_DIR,
    "..",
    "supervised",
    "deforestation_random_forest.joblib",
)

MODEL_PATH = os.path.abspath(MODEL_PATH)


def _load_model(model_path: str = MODEL_PATH):
    """Load the trained Random Forest."""

    if not os.path.exists(model_path):
        raise SupervisedInferenceError(
            f"Trained supervised model not found: {model_path}"
        )

    try:
        model = joblib.load(model_path)
    except Exception as exc:
        raise SupervisedInferenceError(
            f"Could not load supervised model: {exc}"
        ) from exc

    if not hasattr(model, "predict"):
        raise SupervisedInferenceError(
            "Loaded object is not a valid classifier."
        )

    return model


def _build_delta_features(
    base_features: np.ndarray,
    comparison_features: np.ndarray,
) -> np.ndarray:
    """
    Convert the two 16-feature stacks into the exact 16 change
    features used during supervised training.

    Output ordering:

        delta_B1
        delta_B2
        ...
        delta_B12
        delta_ndvi
        delta_nbr
        delta_ndwi
        delta_ndmi
    """

    if base_features.shape != comparison_features.shape:
        raise SupervisedInferenceError(
            "Base and comparison feature stacks have different shapes."
        )

    # Existing FEATURE_NAMES order is:
    #
    # B1 ... B12, NDVI, NBR, NDWI, NDMI
    #
    # Therefore subtraction preserves exactly the same ordering.

    delta = (
        comparison_features.astype(np.float32)
        - base_features.astype(np.float32)
    )

    return delta


def _predict_window(
    model,
    base_features: np.ndarray,
    comparison_features: np.ndarray,
    valid_mask: np.ndarray,
):
    """
    Predict one raster window.

    Returns:
        prediction:
            0 = no deforestation
            1 = deforestation
            nodata = 255

        probability:
            probability of deforestation
            nodata = -9999
    """

    delta_features = _build_delta_features(
        base_features,
        comparison_features,
    )

    height, width, feature_count = delta_features.shape

    if feature_count != len(FEATURE_COLUMNS):
        raise SupervisedInferenceError(
            f"Expected {len(FEATURE_COLUMNS)} features, "
            f"got {feature_count}."
        )

    # Flatten pixels:
    #
    # H x W x 16
    #
    # becomes:
    #
    # N x 16

    flattened = delta_features.reshape(
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

    # ---------------------------------------------------------
    # Prediction
    # ---------------------------------------------------------

    predicted = model.predict(X)

    prediction[flattened_valid] = (
        predicted.astype(np.uint8)
    )

    # ---------------------------------------------------------
    # Deforestation probability
    # ---------------------------------------------------------

    if hasattr(model, "predict_proba"):

        probabilities = model.predict_proba(X)

        classes = list(
            model.classes_
        )

        if 1 not in classes:
            raise SupervisedInferenceError(
                "The trained model does not contain class 1 "
                "(deforestation)."
            )

        deforestation_index = classes.index(1)

        probability[flattened_valid] = (
            probabilities[:, deforestation_index]
            .astype(np.float32)
        )

    return (
        prediction.reshape(height, width),
        probability.reshape(height, width),
    )


def run_supervised_inference(
    base_path: str,
    comparison_path: str,
    prediction_output_path: str,
    probability_output_path: str,
    model_path: str = MODEL_PATH,
    window_size: int = 512,
) -> dict:
    """
    Run supervised Random Forest inference over the complete
    Sentinel-2 base/comparison raster pair.

    Creates:

        prediction raster
            0 = no deforestation
            1 = deforestation
            255 = nodata

        probability raster
            0.0 - 1.0 = probability of deforestation
            -9999 = nodata
    """

    model = _load_model(
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

    os.makedirs(
        os.path.dirname(prediction_output_path),
        exist_ok=True,
    )

    os.makedirs(
        os.path.dirname(probability_output_path),
        exist_ok=True,
    )

    total_valid_pixels = 0
    total_deforestation_pixels = 0

    with rasterio.open(base_path) as base_src, \
            rasterio.open(comparison_path) as comparison_src:

        # -----------------------------------------------------
        # Basic alignment validation
        # -----------------------------------------------------

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

        base_band_indices, base_scl_index = (
            resolve_required_band_indices(
                base_src
            )
        )

        comparison_band_indices, comparison_scl_index = (
            resolve_required_band_indices(
                comparison_src
            )
        )

        # -----------------------------------------------------
        # Output raster profiles
        # -----------------------------------------------------

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

            # -------------------------------------------------
            # Window-by-window inference
            # -------------------------------------------------

            for row_start in range(
                0,
                base_src.height,
                window_size,
            ):

                row_height = min(
                    window_size,
                    base_src.height - row_start,
                )

                for col_start in range(
                    0,
                    base_src.width,
                    window_size,
                ):

                    col_width = min(
                        window_size,
                        base_src.width - col_start,
                    )

                    window = rasterio.windows.Window(
                        col_start,
                        row_start,
                        col_width,
                        row_height,
                    )

                    base_features, base_valid = (
                        read_window_features(
                            base_src,
                            window,
                            base_band_indices,
                            base_scl_index,
                        )
                    )

                    comparison_features, comparison_valid = (
                        read_window_features(
                            comparison_src,
                            window,
                            comparison_band_indices,
                            comparison_scl_index,
                        )
                    )

                    # A pixel is usable only when BOTH years
                    # pass cloud masking.

                    valid_mask = (
                        base_valid
                        & comparison_valid
                    )

                    prediction, probability = (
                        _predict_window(
                            model,
                            base_features,
                            comparison_features,
                            valid_mask,
                        )
                    )

                    prediction_dst.write(
                        prediction,
                        1,
                        window=window,
                    )

                    probability_dst.write(
                        probability,
                        1,
                        window=window,
                    )

                    valid_count = int(
                        np.count_nonzero(
                            valid_mask
                        )
                    )

                    deforestation_count = int(
                        np.count_nonzero(
                            prediction == 1
                        )
                    )

                    total_valid_pixels += (
                        valid_count
                    )

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
        "feature_count": len(FEATURE_COLUMNS),
        "features": FEATURE_COLUMNS,
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