"""
Module 5 pipeline orchestration.

run_polygon_analysis() takes a Module 4 loss-detection manifest (or finds
the latest one automatically), converts the loss mask to polygons,
computes area and severity for each, and writes a GeoJSON + manifest that
Module 6 (Forest Boundary Check) will consume.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

from app.config import NDVI_PROCESSED_DIR, POLYGON_ANALYSIS_DIR
from app.polygon_analysis.config import MIN_POLYGON_AREA_HA
from app.polygon_analysis.vectorize import raster_to_polygons
from app.polygon_analysis.area import compute_area_ha, filter_by_min_area, compute_centroids, assign_polygon_ids
from app.polygon_analysis.severity import estimate_severity
from app.polygon_analysis.ai_scoring import estimate_ai_disturbance, default_detection_class_no_ai


class PolygonAnalysisError(Exception):
    pass


def _find_latest_loss_detection_manifest():
    pattern = os.path.join(NDVI_PROCESSED_DIR, "loss_detection_*.json")
    candidates = []
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)
            candidates.append((data["detected_at"], path, data))
        except (json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        raise PolygonAnalysisError(
            "No Module 4 loss-detection manifest found. Run Module 4 "
            "(python -m app.loss_detection.cli detect) first."
        )

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def run_polygon_analysis(loss_detection_manifest=None, min_area_ha=MIN_POLYGON_AREA_HA):
    if loss_detection_manifest is None:
        loss_detection_manifest = _find_latest_loss_detection_manifest()

    base_year = loss_detection_manifest["base_year"]
    comparison_year = loss_detection_manifest["comparison_year"]
    mask_path = loss_detection_manifest["loss_mask_path"]

    # Reconstructed via Module 3's fixed naming convention (same directory).
    diff_path = os.path.join(NDVI_PROCESSED_DIR, f"ndvi_diff_{base_year}_{comparison_year}.tif")

    if not os.path.exists(mask_path):
        raise PolygonAnalysisError(f"Loss mask raster not found: {mask_path}")
    if not os.path.exists(diff_path):
        raise PolygonAnalysisError(f"NDVI diff raster not found: {diff_path}")

    gdf = raster_to_polygons(mask_path)
    raw_polygon_count = len(gdf)

    gdf = compute_area_ha(gdf)
    gdf = filter_by_min_area(gdf, min_area_ha)
    filtered_polygon_count = len(gdf)

    gdf = estimate_severity(gdf, diff_path)

    # AI disturbance scoring (Module 4B) is optional - if it hasn't been
    # run, every polygon defaults to 'vegetation_loss', identical to this
    # project's behavior before Module 4B existed. Nothing breaks if only
    # the original NDVI-only flow (Module 4 -> 5) has been run.
    ai_anomaly_path = os.path.join(NDVI_PROCESSED_DIR, f"ai_anomaly_score_{base_year}_{comparison_year}.tif")
    ai_scoring_applied = os.path.exists(ai_anomaly_path)
    if ai_scoring_applied:
        gdf = estimate_ai_disturbance(gdf, ai_anomaly_path)
    else:
        gdf = default_detection_class_no_ai(gdf)

    if not gdf.empty:
        gdf = compute_centroids(gdf)
        gdf = assign_polygon_ids(gdf, base_year, comparison_year)
    else:
        # Keep the column present even with zero rows, so downstream
        # modules (Module 6) that expect a polygon_id column don't break
        # on a legitimate "no vegetation loss detected" run.
        gdf["polygon_id"] = []

    run_id = str(uuid.uuid4())
    os.makedirs(POLYGON_ANALYSIS_DIR, exist_ok=True)
    geojson_path = os.path.join(
        POLYGON_ANALYSIS_DIR, f"loss_polygons_{base_year}_{comparison_year}.geojson"
    )
    gdf.to_file(geojson_path, driver="GeoJSON")

    severity_counts = gdf["severity_level"].value_counts().to_dict() if not gdf.empty else {}

    manifest = {
        "run_id": run_id,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "source_loss_detection_run_id": loss_detection_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "region": loss_detection_manifest.get("region"),
        "geojson_path": geojson_path,
        "stats": {
            "raw_polygon_count": raw_polygon_count,
            "filtered_polygon_count": filtered_polygon_count,
            "min_area_ha_filter": min_area_ha,
            "total_loss_area_ha": round(float(gdf["area_ha"].sum()), 4) if not gdf.empty else 0.0,
            "severity_counts": severity_counts,
            "ai_scoring_applied": ai_scoring_applied,
            "detection_class_counts": gdf["detection_class"].value_counts().to_dict() if not gdf.empty else {},
        },
    }

    manifest_path = os.path.join(POLYGON_ANALYSIS_DIR, f"polygon_analysis_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
