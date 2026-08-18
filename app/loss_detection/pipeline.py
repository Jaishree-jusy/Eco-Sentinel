"""
Module 4 pipeline orchestration.

run_loss_detection() takes a Module 3 processing manifest (or finds the
latest one automatically), applies the NDVI-diff threshold, writes the
binary vegetation-loss mask raster, and writes a manifest for Module 5
(Polygon Generation & Analysis) to consume.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

import numpy as np
import rasterio

from app.config import NDVI_PROCESSED_DIR
from app.loss_detection.config import THRESHOLD, LOSS_VALUE, NO_LOSS_VALUE, MASK_NODATA
from app.loss_detection.threshold import apply_threshold


class LossDetectionError(Exception):
    pass


def _find_latest_processing_manifest():
    """Scans data/ndvi_processed/ for the most recent Module 3 processing manifest."""
    pattern = os.path.join(NDVI_PROCESSED_DIR, "processing_*.json")
    candidates = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            candidates.append((data["processed_at"], path, data))
        except (json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        raise LossDetectionError(
            "No Module 3 processing manifest found. Run Module 3 "
            "(python -m app.gee_processing.cli process) first."
        )

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def run_loss_detection(processing_manifest=None, threshold=THRESHOLD):
    if processing_manifest is None:
        processing_manifest = _find_latest_processing_manifest()

    diff_path = processing_manifest["ndvi_diff"]["path"]
    base_year = processing_manifest["base_year"]
    comparison_year = processing_manifest["comparison_year"]

    if not os.path.exists(diff_path):
        raise LossDetectionError(f"NDVI diff raster not found: {diff_path}")

    with rasterio.open(diff_path) as src:
        diff = src.read(1)
        profile = src.profile.copy()

        mask = apply_threshold(diff, threshold=threshold)

        profile.update(count=1, dtype="uint8", nodata=MASK_NODATA)

        run_id = str(uuid.uuid4())
        os.makedirs(NDVI_PROCESSED_DIR, exist_ok=True)
        mask_path = os.path.join(
            NDVI_PROCESSED_DIR, f"vegetation_loss_mask_{base_year}_{comparison_year}.tif"
        )

        with rasterio.open(mask_path, "w", **profile) as dst:
            dst.write(mask, 1)

    total_pixels = mask.size
    loss_pixels = int(np.sum(mask == LOSS_VALUE))
    no_loss_pixels = int(np.sum(mask == NO_LOSS_VALUE))
    nodata_pixels = int(np.sum(mask == MASK_NODATA))
    valid_pixels = loss_pixels + no_loss_pixels

    stats = {
        "threshold_used": threshold,
        "total_pixels": int(total_pixels),
        "valid_pixels": valid_pixels,
        "nodata_pixels": nodata_pixels,
        "loss_pixels": loss_pixels,
        "no_loss_pixels": no_loss_pixels,
        "loss_pct_of_valid": round(100 * loss_pixels / valid_pixels, 4) if valid_pixels else None,
    }

    manifest = {
        "run_id": run_id,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "source_processing_run_id": processing_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "region": processing_manifest.get("region"),
        "loss_mask_path": mask_path,
        "stats": stats,
    }

    manifest_path = os.path.join(NDVI_PROCESSED_DIR, f"loss_detection_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
