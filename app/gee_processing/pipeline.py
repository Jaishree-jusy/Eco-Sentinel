"""
Module 3 pipeline orchestration.

run_gee_processing() takes a Module 2 acquisition manifest (or finds the
latest successful one automatically), computes NDVI for both years from the
raw Sentinel-2 imagery, computes the NDVI difference, and writes a
processing manifest that Module 4 will read.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

from app.config import NDVI_PROCESSED_DIR
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.gee_processing.ndvi import compute_ndvi_from_raw
from app.gee_processing.ndvi_diff import compute_ndvi_diff


class GeeProcessingError(Exception):
    pass


def _find_latest_successful_manifest():
    """Scans data/acquisition_runs/ for the most recent successful run manifest."""
    pattern = os.path.join(ACQUISITION_RUNS_DIR, "run_*.json")
    candidates = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            if data.get("status") == "success":
                candidates.append((data["triggered_at"], path, data))
        except (json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        raise GeeProcessingError(
            "No successful acquisition run found. Run Module 2 "
            "(python -m app.acquisition.cli run) first."
        )

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]  # manifest dict of the most recent run


def run_gee_processing(acquisition_manifest=None):
    """Runs the full Module 3 pipeline. If acquisition_manifest is None,
    automatically uses the latest successful Module 2 run."""

    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_successful_manifest()

    base_year = acquisition_manifest["base_year"]
    comparison_year = acquisition_manifest["comparison_year"]
    datasets = acquisition_manifest["datasets"]

    base_key = f"forest_sample_{base_year}"
    comp_key = f"forest_sample_{comparison_year}"

    if base_key not in datasets or comp_key not in datasets:
        raise GeeProcessingError(
            f"Acquisition manifest is missing raw imagery for this year pair. "
            f"Expected keys '{base_key}' and '{comp_key}' in manifest['datasets']."
        )

    base_raw_path = datasets[base_key]["path"]
    comp_raw_path = datasets[comp_key]["path"]

    run_id = str(uuid.uuid4())
    os.makedirs(NDVI_PROCESSED_DIR, exist_ok=True)

    base_ndvi_path = os.path.join(NDVI_PROCESSED_DIR, f"ndvi_computed_{base_year}.tif")
    comp_ndvi_path = os.path.join(NDVI_PROCESSED_DIR, f"ndvi_computed_{comparison_year}.tif")
    diff_path = os.path.join(NDVI_PROCESSED_DIR, f"ndvi_diff_{base_year}_{comparison_year}.tif")

    base_stats = compute_ndvi_from_raw(base_raw_path, base_ndvi_path)
    comp_stats = compute_ndvi_from_raw(comp_raw_path, comp_ndvi_path)
    diff_stats = compute_ndvi_diff(base_ndvi_path, comp_ndvi_path, diff_path)

    processing_manifest = {
        "run_id": run_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "source_acquisition_run_id": acquisition_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "region": acquisition_manifest.get("region"),
        "ndvi_base": {"path": base_ndvi_path, **base_stats},
        "ndvi_comparison": {"path": comp_ndvi_path, **comp_stats},
        "ndvi_diff": {"path": diff_path, **diff_stats},
    }

    manifest_path = os.path.join(NDVI_PROCESSED_DIR, f"processing_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(processing_manifest, f, indent=2)

    processing_manifest["manifest_path"] = manifest_path
    return processing_manifest
