"""
Module 5 pipeline orchestration.

Consumes a Module 4 loss-detection manifest, finds the exact source
Module 3 processing manifest, converts the loss mask into polygons,
computes area and severity, and writes a unique GeoJSON and manifest.

Existing polygon-analysis outputs are preserved.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

from app.config import NDVI_PROCESSED_DIR, POLYGON_ANALYSIS_DIR
from app.polygon_analysis.config import MIN_POLYGON_AREA_HA
from app.polygon_analysis.vectorize import raster_to_polygons
from app.polygon_analysis.area import (
    compute_area_ha,
    filter_by_min_area,
    compute_centroids,
    assign_polygon_ids,
)
from app.polygon_analysis.severity import estimate_severity
from app.polygon_analysis.ai_scoring import (
    estimate_ai_disturbance,
    default_detection_class_no_ai,
)


class PolygonAnalysisError(Exception):
    pass


def _find_latest_loss_detection_manifest():
    pattern = os.path.join(NDVI_PROCESSED_DIR, "loss_detection_*.json")
    candidates = []

    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if "detected_at" in data and "loss_mask_path" in data:
                candidates.append((data["detected_at"], data))
        except (json.JSONDecodeError, OSError, KeyError):
            continue

    if not candidates:
        raise PolygonAnalysisError(
            "No Module 4 loss-detection manifest found. "
            "Run Module 4 first."
        )

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _find_source_processing_manifest(loss_detection_manifest):
    """Find the exact Module 3 manifest referenced by Module 4."""
    source_run_id = loss_detection_manifest.get("source_processing_run_id")

    if not source_run_id:
        raise PolygonAnalysisError(
            "Module 4 manifest has no source_processing_run_id. "
            "Cannot safely identify the correct NDVI difference raster."
        )

    pattern = os.path.join(NDVI_PROCESSED_DIR, "processing_*.json")

    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("run_id") == source_run_id:
            return data

    raise PolygonAnalysisError(
        "Could not find the Module 3 processing manifest with run ID "
        f"{source_run_id!r} in {NDVI_PROCESSED_DIR}. "
        "No polygon analysis was run."
    )


def run_polygon_analysis(
    loss_detection_manifest=None,
    min_area_ha=MIN_POLYGON_AREA_HA,
):
    if loss_detection_manifest is None:
        loss_detection_manifest = _find_latest_loss_detection_manifest()

    base_year = loss_detection_manifest["base_year"]
    comparison_year = loss_detection_manifest["comparison_year"]
    mask_path = loss_detection_manifest["loss_mask_path"]

    # Resolve the exact Module 3 run that produced this Module 4 result.
    processing_manifest = _find_source_processing_manifest(
        loss_detection_manifest
    )

    diff_path = processing_manifest.get("ndvi_diff", {}).get("path")

    if not diff_path:
        raise PolygonAnalysisError(
            "The source Module 3 manifest does not contain "
            "ndvi_diff.path. No polygon analysis was run."
        )

    if not os.path.isfile(mask_path):
        raise PolygonAnalysisError(
            f"Loss mask raster not found: {mask_path}"
        )

    if not os.path.isfile(diff_path):
        raise PolygonAnalysisError(
            f"NDVI difference raster not found: {diff_path}"
        )

    # Generate polygons from the loss mask.
    gdf = raster_to_polygons(mask_path)
    raw_polygon_count = len(gdf)

    gdf = compute_area_ha(gdf)
    gdf = filter_by_min_area(gdf, min_area_ha)
    filtered_polygon_count = len(gdf)

    # Compute severity from the exact difference raster.
    gdf = estimate_severity(gdf, diff_path)

    # Apply optional AI disturbance scoring when the corresponding raster exists.
    ai_anomaly_path = os.path.join(
        NDVI_PROCESSED_DIR,
        f"ai_anomaly_score_{base_year}_{comparison_year}.tif",
    )
    ai_scoring_applied = os.path.isfile(ai_anomaly_path)

    if ai_scoring_applied:
        gdf = estimate_ai_disturbance(gdf, ai_anomaly_path)
    else:
        gdf = default_detection_class_no_ai(gdf)

    if not gdf.empty:
        gdf = compute_centroids(gdf)
        gdf = assign_polygon_ids(gdf, base_year, comparison_year)
    else:
        gdf["polygon_id"] = []

    # Use a unique filename so a rerun cannot overwrite existing GeoJSON.
    run_id = str(uuid.uuid4())
    os.makedirs(POLYGON_ANALYSIS_DIR, exist_ok=True)

    comparison_label = str(comparison_year).replace(os.sep, "_")
    geojson_path = os.path.join(
        POLYGON_ANALYSIS_DIR,
        f"loss_polygons_{base_year}_{comparison_label}_{run_id[:8]}.geojson",
    )

    gdf.to_file(geojson_path, driver="GeoJSON")

    severity_counts = (
        gdf["severity_level"].value_counts().to_dict()
        if not gdf.empty
        else {}
    )

    detection_class_counts = (
        gdf["detection_class"].value_counts().to_dict()
        if not gdf.empty
        else {}
    )

    manifest = {
        "run_id": run_id,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source_loss_detection_run_id": loss_detection_manifest.get("run_id"),
        "source_processing_run_id": processing_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "region": loss_detection_manifest.get("region"),
        "source_diff_path": os.path.abspath(diff_path),
        "source_loss_mask_path": os.path.abspath(mask_path),
        "geojson_path": os.path.abspath(geojson_path),
        "stats": {
            "raw_polygon_count": raw_polygon_count,
            "filtered_polygon_count": filtered_polygon_count,
            "min_area_ha_filter": min_area_ha,
            "total_loss_area_ha": (
                round(float(gdf["area_ha"].sum()), 4)
                if not gdf.empty
                else 0.0
            ),
            "severity_counts": severity_counts,
            "ai_scoring_applied": ai_scoring_applied,
            "detection_class_counts": detection_class_counts,
        },
    }

    manifest_path = os.path.join(
        POLYGON_ANALYSIS_DIR,
        f"polygon_analysis_{run_id}.json",
    )

    with open(manifest_path, "x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = os.path.abspath(manifest_path)
    return manifest
