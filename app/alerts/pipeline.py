"""
Module 7 / 7A pipeline orchestration.

Creates inside-forest and outside-forest alerts from a specified
Module 6 boundary-check manifest. Output files are unique per run
so historical alerts are not overwritten.
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
from app.alerts.alert_builder import (
    build_inside_forest_alert,
    build_outside_forest_alert,
)
from app.alerts.area_type import classify_area_types


class AlertGenerationError(Exception):
    pass


def _find_latest(pattern, timestamp_key):
    candidates = []

    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            candidates.append((data[timestamp_key], data))
        except (OSError, json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _find_latest_boundary_check_manifest():
    manifest = _find_latest(
        os.path.join(BOUNDARY_CHECK_DIR, "boundary_check_*.json"),
        "checked_at",
    )
    if manifest is None:
        raise AlertGenerationError("No Module 6 boundary-check manifest found.")
    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(
        os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"),
        "triggered_at",
    )
    if manifest is None:
        raise AlertGenerationError("No Module 2 acquisition manifest found.")
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

    for path in (inside_path, outside_path):
        if not os.path.isfile(path):
            raise AlertGenerationError(f"Boundary-check GeoJSON not found: {path}")

    # Use legality-enriched data only when a matching file is explicitly
    # available; otherwise the alert builder defaults legality to unknown.
    standard_legality_path = os.path.join(
        BOUNDARY_CHECK_DIR,
        f"legality_checked_{base_year}_{comparison_year}.geojson",
    )
    if os.path.isfile(standard_legality_path):
        inside_path = standard_legality_path

    inside_gdf = gpd.read_file(inside_path)
    outside_gdf = gpd.read_file(outside_path)

    generated_at = datetime.now(timezone.utc).isoformat()

    inside_alerts = [
        build_inside_forest_alert(row, generated_at=generated_at)
        for _, row in inside_gdf.iterrows()
    ]

    if not outside_gdf.empty:
        datasets = acquisition_manifest.get("datasets", {})
        if "worldcover_2021" not in datasets:
            raise AlertGenerationError(
                "Acquisition manifest is missing worldcover_2021."
            )

        worldcover_path = datasets["worldcover_2021"]["path"]
        if not os.path.isfile(worldcover_path):
            raise AlertGenerationError(
                f"WorldCover raster not found: {worldcover_path}"
            )

        area_types = classify_area_types(
            worldcover_path,
            outside_gdf["centroid_lon"].tolist(),
            outside_gdf["centroid_lat"].tolist(),
        )
    else:
        area_types = []

    outside_alerts = [
        build_outside_forest_alert(row, area_types[i], generated_at=generated_at)
        for i, (_, row) in enumerate(outside_gdf.iterrows())
    ]

    run_id = str(uuid.uuid4())
    os.makedirs(ALERTS_DIR, exist_ok=True)

    # Unique filenames prevent overwriting historical or previous runs.
    suffix = f"{base_year}_{comparison_year}_{run_id[:8]}"
    inside_alerts_path = os.path.join(
        ALERTS_DIR, f"alerts_inside_forest_{suffix}.json"
    )
    outside_alerts_path = os.path.join(
        ALERTS_DIR, f"alerts_outside_forest_{suffix}.json"
    )

    with open(inside_alerts_path, "x", encoding="utf-8") as f:
        json.dump(inside_alerts, f, indent=2)

    with open(outside_alerts_path, "x", encoding="utf-8") as f:
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

    manifest_path = os.path.join(
        ALERTS_DIR, f"alert_generation_{run_id}.json"
    )
    with open(manifest_path, "x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
