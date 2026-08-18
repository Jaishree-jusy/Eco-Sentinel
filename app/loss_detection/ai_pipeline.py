"""
Module 4B pipeline orchestration.

Runs alongside Module 4 (NDVI threshold), not instead of it. Reads the
same acquisition manifest Module 3 used (for the raw base/comparison
imagery paths - the AI features need the actual spectral bands, not just
the NDVI Module 3 already computed).
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

from app.config import NDVI_PROCESSED_DIR
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.loss_detection.ai_disturbance import run_ai_disturbance_detection, DEFAULT_N_SAMPLES, DEFAULT_CONTAMINATION


class AiDisturbanceError(Exception):
    pass


def _find_latest_acquisition_manifest():
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
        raise AiDisturbanceError(
            "No successful acquisition run found. Run Module 2 first."
        )
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def run_ai_disturbance_pipeline(acquisition_manifest=None, n_samples=DEFAULT_N_SAMPLES, contamination=DEFAULT_CONTAMINATION):
    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    base_year = acquisition_manifest["base_year"]
    comparison_year = acquisition_manifest["comparison_year"]
    datasets = acquisition_manifest["datasets"]

    base_key = f"forest_sample_{base_year}"
    comp_key = f"forest_sample_{comparison_year}"

    if base_key not in datasets or comp_key not in datasets:
        raise AiDisturbanceError(
            f"Acquisition manifest is missing raw imagery for this year pair "
            f"(expected '{base_key}' and '{comp_key}')."
        )

    base_path = datasets[base_key]["path"]
    comp_path = datasets[comp_key]["path"]

    run_id = str(uuid.uuid4())
    os.makedirs(NDVI_PROCESSED_DIR, exist_ok=True)
    output_path = os.path.join(NDVI_PROCESSED_DIR, f"ai_anomaly_score_{base_year}_{comparison_year}.tif")

    stats = run_ai_disturbance_detection(base_path, comp_path, output_path, n_samples=n_samples, contamination=contamination)

    manifest = {
        "run_id": run_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "source_acquisition_run_id": acquisition_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "anomaly_score": stats,
    }

    manifest_path = os.path.join(NDVI_PROCESSED_DIR, f"ai_disturbance_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
