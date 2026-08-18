"""
Module 6B pipeline orchestration.

Sits between Module 6 (forest boundary) and Module 7 (alerts). Reads
Module 6's inside-forest polygons, applies the legality check to each,
writes a new GeoJSON with legality_status/matched_authorization_id
attached. With no authorization dataset configured (the current, honest
default), every polygon gets "legal_status_unknown".
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

import geopandas as gpd

from app.boundary_check.config import BOUNDARY_CHECK_DIR, AUTHORIZATION_DATASET_PATH
from app.boundary_check.legality import load_authorization_dataset, check_legality, LEGAL_STATUS_UNKNOWN


class LegalityCheckError(Exception):
    pass


def _find_latest_boundary_check_manifest():
    pattern = os.path.join(BOUNDARY_CHECK_DIR, "boundary_check_*.json")
    candidates = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            candidates.append((data["checked_at"], path, data))
        except (json.JSONDecodeError, KeyError):
            continue
    if not candidates:
        raise LegalityCheckError("No Module 6 boundary-check manifest found. Run Module 6 first.")
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def run_legality_check(boundary_manifest=None, authorization_dataset_path=AUTHORIZATION_DATASET_PATH):
    if boundary_manifest is None:
        boundary_manifest = _find_latest_boundary_check_manifest()

    inside_path = boundary_manifest["inside_forest"]["path"]
    base_year = boundary_manifest["base_year"]
    comparison_year = boundary_manifest["comparison_year"]

    if not os.path.exists(inside_path):
        raise LegalityCheckError(f"Inside-forest GeoJSON not found: {inside_path}")

    gdf = gpd.read_file(inside_path)

    try:
        authorization_gdf = load_authorization_dataset(authorization_dataset_path)
    except ValueError as e:
        raise LegalityCheckError(str(e))

    detection_date = f"{comparison_year}-01-01"  # best available granularity right now

    legality_statuses = []
    matched_ids = []
    for _, row in gdf.iterrows():
        result = check_legality(row.geometry, detection_date, authorization_gdf)
        legality_statuses.append(result["legality_status"])
        matched_ids.append(result["matched_authorization_id"])

    gdf = gdf.copy()
    gdf["legality_status"] = legality_statuses
    gdf["matched_authorization_id"] = matched_ids

    run_id = str(uuid.uuid4())
    os.makedirs(BOUNDARY_CHECK_DIR, exist_ok=True)
    output_path = os.path.join(BOUNDARY_CHECK_DIR, f"legality_checked_{base_year}_{comparison_year}.geojson")
    gdf.to_file(output_path, driver="GeoJSON")

    status_counts = gdf["legality_status"].value_counts().to_dict()

    manifest = {
        "run_id": run_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_boundary_check_run_id": boundary_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "authorization_dataset_configured": authorization_gdf is not None,
        "output_path": output_path,
        "status_counts": status_counts,
    }

    manifest_path = os.path.join(BOUNDARY_CHECK_DIR, f"legality_check_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
