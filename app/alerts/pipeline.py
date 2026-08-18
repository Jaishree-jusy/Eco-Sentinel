"""
Module 7 / 7A pipeline orchestration.

run_alert_generation() takes the latest Module 6 boundary-check manifest
(or finds it automatically), builds an Inside-Forest alert list (Box 7,
feeds Module 8 -> 9 -> 10) and an Outside-Forest alert list (Box 7A,
feeds Module 7B directly).
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

import geopandas as gpd

from app.config import ALERTS_DIR
from app.boundary_check.config import BOUNDARY_CHECK_DIR
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.alerts.alert_builder import build_inside_forest_alert, build_outside_forest_alert
from app.alerts.area_type import classify_area_types


class AlertGenerationError(Exception):
    pass


def _find_latest(pattern, timestamp_key):
    candidates = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            candidates.append((data[timestamp_key], path, data))
        except (json.JSONDecodeError, KeyError):
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def _find_latest_boundary_check_manifest():
    manifest = _find_latest(os.path.join(BOUNDARY_CHECK_DIR, "boundary_check_*.json"), "checked_at")
    if manifest is None:
        raise AlertGenerationError(
            "No Module 6 boundary-check manifest found. Run Module 6 "
            "(python -m app.boundary_check.cli check) first."
        )
    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"), "triggered_at")
    if manifest is None:
        raise AlertGenerationError(
            "No Module 2 acquisition manifest found. Run Module 2 "
            "(python -m app.acquisition.cli run) first."
        )
    return manifest


def run_alert_generation(boundary_manifest=None, acquisition_manifest=None):
    if boundary_manifest is None:
        boundary_manifest = _find_latest_boundary_check_manifest()
    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    base_year = boundary_manifest["base_year"]
    comparison_year = boundary_manifest["comparison_year"]

    inside_path = boundary_manifest["inside_forest"]["path"]
    outside_path = boundary_manifest["outside_forest"]["path"]

    # Module 6B (legality check) is optional - if it's been run, its
    # output (same polygons + legality_status/matched_authorization_id)
    # is what feeds alerts. If not, fall back to Module 6's plain output;
    # build_inside_forest_alert() handles the missing columns gracefully
    # (defaults to legal_status_unknown, never fabricates a verdict).
    legality_path = os.path.join(
        os.path.dirname(inside_path), f"legality_checked_{base_year}_{comparison_year}.geojson"
    )
    if os.path.exists(legality_path):
        inside_path = legality_path

    if not os.path.exists(inside_path):
        raise AlertGenerationError(f"Inside-forest GeoJSON not found: {inside_path}")
    if not os.path.exists(outside_path):
        raise AlertGenerationError(f"Outside-forest GeoJSON not found: {outside_path}")

    generated_at = datetime.now(timezone.utc).isoformat()

    # --- Inside Forest alerts (Box 7) ---
    inside_gdf = gpd.read_file(inside_path)
    inside_alerts = [
        build_inside_forest_alert(row, generated_at=generated_at)
        for _, row in inside_gdf.iterrows()
    ]

    # --- Outside Forest alerts (Box 7A) ---
    outside_gdf = gpd.read_file(outside_path)
    if not outside_gdf.empty:
        worldcover_path = acquisition_manifest["datasets"]["worldcover_2021"]["path"]
        area_types = classify_area_types(
            worldcover_path, outside_gdf["centroid_lon"].tolist(), outside_gdf["centroid_lat"].tolist()
        )
    else:
        area_types = []

    outside_alerts = [
        build_outside_forest_alert(row, area_types[i], generated_at=generated_at)
        for i, (_, row) in enumerate(outside_gdf.iterrows())
    ]

    run_id = str(uuid.uuid4())
    os.makedirs(ALERTS_DIR, exist_ok=True)

    inside_alerts_path = os.path.join(ALERTS_DIR, f"alerts_inside_forest_{base_year}_{comparison_year}.json")
    outside_alerts_path = os.path.join(ALERTS_DIR, f"alerts_outside_forest_{base_year}_{comparison_year}.json")

    with open(inside_alerts_path, "w") as f:
        json.dump(inside_alerts, f, indent=2)
    with open(outside_alerts_path, "w") as f:
        json.dump(outside_alerts, f, indent=2)

    manifest = {
        "run_id": run_id,
        "generated_at": generated_at,
        "source_boundary_check_run_id": boundary_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "inside_forest_alerts": {
            "path": inside_alerts_path,
            "count": len(inside_alerts),
        },
        "outside_forest_alerts": {
            "path": outside_alerts_path,
            "count": len(outside_alerts),
        },
    }

    manifest_path = os.path.join(ALERTS_DIR, f"alert_generation_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
