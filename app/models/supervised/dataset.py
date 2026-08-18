"""
Training dataset builder for the supervised deforestation model.

Labels are independent of ECO-SENTINEL's existing NDVI/Isolation-Forest
detector.

Reference:
    Hansen Global Forest Change
    - treecover2000 -> identifies reference forest
    - lossyear      -> identifies forest-loss year

Target:
    0 = reference forest with no 2024/2025 Hansen loss
    1 = reference forest with Hansen loss in 2024 or 2025

Features:
    12 Sentinel-2 spectral-band changes
    + NDVI, NBR, NDWI, NDMI changes
    = 16 features

The existing SCL cloud-mask implementation is reused.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import ee
import numpy as np
import pandas as pd
import rasterio

from app.acquisition.config import (
    DEFAULT_REGION,
    DEFAULT_YEAR_PAIR,
    REGIONS,
)
from app.config import (
    FOREST_SAMPLES_DIR,
    DATA_DIR,
)
from app.gee_processing.cloud_mask import build_cloud_mask
from app.gee_processing.config import CLOUD_SCL_CODES


HANSEN_DATASET = "UMD/hansen/global_forest_change_2025_v1_13"

# Hansen is ~30 m.
HANSEN_SCALE = 30

# Reference forest threshold.
# Pixels with at least this percentage tree cover in 2000 are considered
# reference forest for supervised training.
TREE_COVER_THRESHOLD = 30

# Maximum number of samples retained from each class.
DEFAULT_SAMPLES_PER_CLASS = 25_000

# Random seed makes dataset generation reproducible.
RANDOM_SEED = 42

# Sentinel-2 spectral features used by the existing AI pipeline.
SPECTRAL_BANDS = [
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "B6",
    "B7",
    "B8",
    "B8A",
    "B9",
    "B11",
    "B12",
]

FEATURE_COLUMNS = [
    *[f"delta_{band}" for band in SPECTRAL_BANDS],
    "delta_ndvi",
    "delta_nbr",
    "delta_ndwi",
    "delta_ndmi",
]

OUTPUT_DIR = os.path.join(DATA_DIR, "supervised")
TRAINING_CSV = os.path.join(OUTPUT_DIR, "training_samples.csv")
METADATA_JSON = os.path.join(OUTPUT_DIR, "dataset_metadata.json")
REFERENCE_RASTER = os.path.join(OUTPUT_DIR, "hansen_reference.tif")


class SupervisedDatasetError(Exception):
    """Raised when supervised training data cannot be created."""


def _initialize_ee() -> None:
    """Initialize Earth Engine using the project's existing credentials."""

    try:
        ee.Initialize()
    except Exception as exc:
        raise SupervisedDatasetError(
            "Earth Engine initialization failed. "
            "Run 'earthengine authenticate' first."
        ) from exc


def _bbox_to_geometry(bbox: dict) -> ee.Geometry:
    return ee.Geometry.Rectangle(
        [
            bbox["left"],
            bbox["bottom"],
            bbox["right"],
            bbox["top"],
        ]
    )


def download_hansen_reference(
    output_path: str = REFERENCE_RASTER,
    region_key: str = DEFAULT_REGION,
) -> str:
    """
    Download Hansen tree-cover and loss-year reference data for the project AOI.

    The downloaded raster contains:
        band 1 = treecover2000
        band 2 = lossyear
    """

    _initialize_ee()

    if region_key not in REGIONS:
        raise SupervisedDatasetError(
            f"Unknown region '{region_key}'."
        )

    bbox = REGIONS[region_key]["bbox"]
    geometry = _bbox_to_geometry(bbox)

    image = (
        ee.Image(HANSEN_DATASET)
        .select(["treecover2000", "lossyear"])
    )

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        url = image.getDownloadURL(
            {
                "region": geometry,
                "scale": HANSEN_SCALE,
                "crs": "EPSG:4326",
                "format": "GEO_TIFF",
            }
        )
    except Exception as exc:
        raise SupervisedDatasetError(
            f"Could not create Hansen download URL: {exc}"
        ) from exc

    import requests

    response = requests.get(url, timeout=300)

    if response.status_code != 200:
        raise SupervisedDatasetError(
            "Hansen download failed: "
            f"HTTP {response.status_code}: "
            f"{response.text[:300]}"
        )

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path


def _read_sentinel_raster(path: str) -> tuple[np.ndarray, dict]:
    """
    Read the 26-band Sentinel-2 raster.

    Returns:
        array: shape (bands, rows, cols)
        profile: rasterio profile
    """

    with rasterio.open(path) as src:
        array = src.read()
        profile = src.profile.copy()
        descriptions = src.descriptions

    expected = tuple(
        [
            "B1",
            "B2",
            "B3",
            "B4",
            "B5",
            "B6",
            "B7",
            "B8",
            "B8A",
            "B9",
            "B11",
            "B12",
            "AOT",
            "WVP",
            "SCL",
            "TCI_R",
            "TCI_G",
            "TCI_B",
            "MSK_CLDPRB",
            "MSK_SNWPRB",
            "QA10",
            "QA20",
            "QA60",
            "MSK_CLASSI_OPAQUE",
            "MSK_CLASSI_CIRRUS",
            "MSK_CLASSI_SNOW_ICE",
        ]
    )

    if tuple(descriptions) != expected:
        raise SupervisedDatasetError(
            "Unexpected Sentinel-2 band order in "
            f"{path}. Expected {expected}, got {descriptions}."
        )

    return array, profile


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Compute a ratio while avoiding division-by-zero."""

    result = np.zeros_like(numerator, dtype=np.float32)

    valid = np.abs(denominator) > 1e-8

    np.divide(
        numerator,
        denominator,
        out=result,
        where=valid,
    )

    return result


def _compute_indices(
    array: np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Compute vegetation/water indices from a Sentinel-2 array.

    Band positions are based on the project's validated 26-band layout.
    """

    # 0-based positions.
    b2 = array[1].astype(np.float32)
    b4 = array[3].astype(np.float32)
    b8 = array[7].astype(np.float32)
    b11 = array[10].astype(np.float32)
    b12 = array[11].astype(np.float32)

    ndvi = _safe_ratio(
        b8 - b4,
        b8 + b4,
    )

    nbr = _safe_ratio(
        b8 - b12,
        b8 + b12,
    )

    ndwi = _safe_ratio(
        b3 := array[2].astype(np.float32),
        b8 + b3,
    )

    ndmi = _safe_ratio(
        b8 - b11,
        b8 + b11,
    )

    return {
        "ndvi": ndvi,
        "nbr": nbr,
        "ndwi": ndwi,
        "ndmi": ndmi,
    }


def _build_change_features(
    base: np.ndarray,
    comparison: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build 16-dimensional Sentinel-2 change features.

    Returns:
        feature_array:
            shape (16, rows, cols)
        valid_mask:
            True where both observations are cloud-valid.
    """

    base_scl = base[14]
    comparison_scl = comparison[14]

    base_cloud = build_cloud_mask(base_scl)
    comparison_cloud = build_cloud_mask(comparison_scl)

    valid_mask = ~(
        base_cloud | comparison_cloud
    )

    base_indices = _compute_indices(base)
    comparison_indices = _compute_indices(comparison)

    features = []

    band_indices = {
        name: i
        for i, name in enumerate(SPECTRAL_BANDS)
    }

    for band_name in SPECTRAL_BANDS:
        index = band_indices[band_name]

        delta = (
            comparison[index].astype(np.float32)
            - base[index].astype(np.float32)
        )

        features.append(delta)

    for index_name in [
        "ndvi",
        "nbr",
        "ndwi",
        "ndmi",
    ]:
        delta = (
            comparison_indices[index_name]
            - base_indices[index_name]
        )

        features.append(delta.astype(np.float32))

    feature_array = np.stack(features).astype(np.float32)

    return feature_array, valid_mask


def _reproject_reference_to_sentinel_grid(
    reference_path: str,
    sentinel_profile: dict,
    sentinel_shape: tuple[int, int],
) -> np.ndarray:
    """
    Reproject Hansen reference data onto the Sentinel-2 grid.

    Nearest-neighbour is used because tree-cover and loss-year are
    categorical/reference values, not continuous measurements.
    """

    from rasterio.warp import reproject
    from rasterio.enums import Resampling

    output = np.zeros(
        (2, sentinel_shape[0], sentinel_shape[1]),
        dtype=np.float32,
    )

    with rasterio.open(reference_path) as src:
        for band_index in range(1, 3):
            reproject(
                source=rasterio.band(src, band_index),
                destination=output[band_index - 1],
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=sentinel_profile["transform"],
                dst_crs=sentinel_profile["crs"],
                dst_width=sentinel_shape[1],
                dst_height=sentinel_shape[0],
                resampling=Resampling.nearest,
            )

    return output


def _sample_training_pixels(
    features: np.ndarray,
    valid_mask: np.ndarray,
    reference: np.ndarray,
    samples_per_class: int,
) -> pd.DataFrame:
    """
    Create a balanced supervised dataset.

    Positive:
        treecover2000 >= threshold AND lossyear in 2024/2025

    Negative:
        treecover2000 >= threshold AND lossyear == 0

    Existing ECO-SENTINEL detection_class is deliberately NOT used.
    """

    tree_cover = reference[0]
    loss_year = reference[1]

    reference_forest = (
        tree_cover >= TREE_COVER_THRESHOLD
    )

    positive_mask = (
        valid_mask
        & reference_forest
        & np.isin(loss_year, [24, 25])
    )

    negative_mask = (
        valid_mask
        & reference_forest
        & (loss_year == 0)
    )

    positive_indices = np.flatnonzero(
        positive_mask.ravel()
    )

    negative_indices = np.flatnonzero(
        negative_mask.ravel()
    )

    rng = np.random.default_rng(RANDOM_SEED)

    positive_count = min(
        len(positive_indices),
        samples_per_class,
    )

    negative_count = min(
        len(negative_indices),
        samples_per_class,
    )

    if positive_count == 0:
        raise SupervisedDatasetError(
            "No positive Hansen forest-loss samples were found "
            "for 2024/2025 inside the project AOI."
        )

    if negative_count == 0:
        raise SupervisedDatasetError(
            "No negative reference-forest samples were found "
            "for the project AOI."
        )

    positive_indices = rng.choice(
        positive_indices,
        size=positive_count,
        replace=False,
    )

    negative_indices = rng.choice(
        negative_indices,
        size=negative_count,
        replace=False,
    )

    selected_indices = np.concatenate(
        [
            positive_indices,
            negative_indices,
        ]
    )

    rows, cols = np.unravel_index(
        selected_indices,
        valid_mask.shape,
    )

    X = features[
        :,
        rows,
        cols,
    ].T

    labels = np.concatenate(
        [
            np.ones(positive_count, dtype=np.int8),
            np.zeros(negative_count, dtype=np.int8),
        ]
    )

    return pd.DataFrame(
        X,
        columns=FEATURE_COLUMNS,
    ).assign(label=labels)


def build_training_dataset(
    base_path: str | None = None,
    comparison_path: str | None = None,
    output_csv: str = TRAINING_CSV,
    reference_path: str = REFERENCE_RASTER,
    samples_per_class: int = DEFAULT_SAMPLES_PER_CLASS,
    region_key: str = DEFAULT_REGION,
) -> dict:
    """
    Build the supervised Random Forest training dataset.

    The Sentinel-2 rasters are the model inputs.
    Hansen is the independent reference label source.
    """

    if base_path is None:
        base_path = os.path.join(
            FOREST_SAMPLES_DIR,
            "Forest_Sample_2023.tif",
        )

    if comparison_path is None:
        comparison_path = os.path.join(
            FOREST_SAMPLES_DIR,
            "Forest_Sample_2025.tif",
        )

    if not os.path.exists(base_path):
        raise SupervisedDatasetError(
            f"Base raster not found: {base_path}"
        )

    if not os.path.exists(comparison_path):
        raise SupervisedDatasetError(
            f"Comparison raster not found: {comparison_path}"
        )

    if not os.path.exists(reference_path):
        download_hansen_reference(
            output_path=reference_path,
            region_key=region_key,
        )

    base, base_profile = _read_sentinel_raster(
        base_path
    )

    comparison, comparison_profile = _read_sentinel_raster(
        comparison_path
    )

    if base.shape != comparison.shape:
        raise SupervisedDatasetError(
            "Base and comparison rasters do not have "
            "the same shape."
        )

    if (
        base_profile["transform"]
        != comparison_profile["transform"]
        or base_profile["crs"]
        != comparison_profile["crs"]
    ):
        raise SupervisedDatasetError(
            "Base and comparison rasters are not aligned."
        )

    features, valid_mask = _build_change_features(
        base,
        comparison,
    )

    reference = _reproject_reference_to_sentinel_grid(
        reference_path,
        base_profile,
        base.shape[1:],
    )

    dataframe = _sample_training_pixels(
        features,
        valid_mask,
        reference,
        samples_per_class,
    )

    os.makedirs(
        os.path.dirname(output_csv),
        exist_ok=True,
    )

    dataframe.to_csv(
        output_csv,
        index=False,
    )

    metadata = {
        "base_year": DEFAULT_YEAR_PAIR["base_year"],
        "comparison_year": DEFAULT_YEAR_PAIR["comparison_year"],
        "region": REGIONS[region_key],
        "reference_dataset": HANSEN_DATASET,
        "reference_treecover_threshold": TREE_COVER_THRESHOLD,
        "positive_loss_years": [2024, 2025],
        "feature_columns": FEATURE_COLUMNS,
        "samples_per_class": samples_per_class,
        "total_samples": int(len(dataframe)),
        "positive_samples": int(
            (dataframe["label"] == 1).sum()
        ),
        "negative_samples": int(
            (dataframe["label"] == 0).sum()
        ),
        "output_csv": output_csv,
        "reference_raster": reference_path,
        "cloud_scl_codes": sorted(CLOUD_SCL_CODES),
    }

    with open(
        METADATA_JSON,
        "w",
    ) as f:
        json.dump(
            metadata,
            f,
            indent=2,
        )

    return metadata


if __name__ == "__main__":
    result = build_training_dataset()

    print(
        json.dumps(
            result,
            indent=2,
        )
    )