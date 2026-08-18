"""
Module 6 pipeline orchestration.

run_boundary_check() takes the latest Module 5 polygon analysis output and
the latest Module 2 acquisition manifest (for WorldCover + GADM paths),
classifies every loss polygon as inside or outside forest, assigns a
region/division label, and splits the result into two GeoJSON files -
one per branch of the architecture (Inside Forest -> Module 7,
Outside Forest -> Module 7A).
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

import geopandas as gpd

from app.config import POLYGON_ANALYSIS_DIR
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.boundary_check.config import BOUNDARY_CHECK_DIR
from app.boundary_check.landcover_lookup import classify_points_by_landcover, BoundaryCheckError
from app.boundary_check.region_lookup import assign_regions


class BoundaryPipelineError(Exception):
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


def _find_latest_polygon_analysis_manifest():
    manifest = _find_latest(os.path.join(POLYGON_ANALYSIS_DIR, "polygon_analysis_*.json"), "analyzed_at")
    if manifest is None:
        raise BoundaryPipelineError(
            "No Module 5 polygon analysis manifest found. Run Module 5 "
            "(python -m app.polygon_analysis.cli analyze) first."
        )
    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"), "triggered_at")
    if manifest is None:
        raise BoundaryPipelineError(
            "No Module 2 acquisition manifest found. Run Module 2 "
            "(python -m app.acquisition.cli run) first."
        )
    return manifest


def run_boundary_check(polygon_manifest=None, acquisition_manifest=None):
    if polygon_manifest is None:
        polygon_manifest = _find_latest_polygon_analysis_manifest()
    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    geojson_path = polygon_manifest["geojson_path"]
    base_year = polygon_manifest["base_year"]
    comparison_year = polygon_manifest["comparison_year"]

    datasets = acquisition_manifest["datasets"]
    if "worldcover_2021" not in datasets or "gadm_forest_boundary" not in datasets:
        raise BoundaryPipelineError(
            "Acquisition manifest is missing 'worldcover_2021' or 'gadm_forest_boundary'."
        )
    worldcover_path = datasets["worldcover_2021"]["path"]
    gadm_path = datasets["gadm_forest_boundary"]["path"]

    if not os.path.exists(geojson_path):
        raise BoundaryPipelineError(f"Loss polygons GeoJSON not found: {geojson_path}")

    gdf = gpd.read_file(geojson_path)

    if gdf.empty:
        raise BoundaryPipelineError("No loss polygons to classify - Module 5 output was empty.")

    points_gdf = gpd.GeoDataFrame(
        gdf[["polygon_id"]],
        geometry=gpd.points_from_xy(gdf["centroid_lon"], gdf["centroid_lat"]),
        crs=gdf.crs,
    )

    try:
        classifications = classify_points_by_landcover(
            worldcover_path, gdf["centroid_lon"].tolist(), gdf["centroid_lat"].tolist()
        )
    except BoundaryCheckError as e:
        raise BoundaryPipelineError(str(e))

    regions, region_column_used = assign_regions(points_gdf, gadm_path)

    gdf = gdf.copy()
    gdf["location_classification"] = classifications
    gdf["region_division"] = regions

    inside_gdf = gdf[gdf["location_classification"] == "inside_forest"].reset_index(drop=True)
    outside_gdf = gdf[gdf["location_classification"] == "outside_forest"].reset_index(drop=True)
    unknown_gdf = gdf[gdf["location_classification"] == "out_of_extent"].reset_index(drop=True)

    run_id = str(uuid.uuid4())
    os.makedirs(BOUNDARY_CHECK_DIR, exist_ok=True)

    inside_path = os.path.join(BOUNDARY_CHECK_DIR, f"inside_forest_{base_year}_{comparison_year}.geojson")
    outside_path = os.path.join(BOUNDARY_CHECK_DIR, f"outside_forest_{base_year}_{comparison_year}.geojson")
    unknown_path = os.path.join(BOUNDARY_CHECK_DIR, f"unknown_classification_{base_year}_{comparison_year}.geojson")

    inside_gdf.to_file(inside_path, driver="GeoJSON")
    outside_gdf.to_file(outside_path, driver="GeoJSON")
    # Written even if empty, so its existence/count is always checkable -
    # these are NOT alerts (neither Module 7 nor 7A reads this file). They
    # represent loss polygons we have no WorldCover coverage to classify at
    # all - a data gap, not a confirmed "outside forest" result - and are
    # kept separately for manual review rather than silently defaulted into
    # the outside-forest/NGO pathway.
    unknown_gdf.to_file(unknown_path, driver="GeoJSON")

    manifest = {
        "run_id": run_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_polygon_analysis_run_id": polygon_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "region_column_used": region_column_used,
        "inside_forest": {
            "path": inside_path,
            "count": len(inside_gdf),
            "total_area_ha": round(float(inside_gdf["area_ha"].sum()), 4) if len(inside_gdf) else 0.0,
        },
        "outside_forest": {
            "path": outside_path,
            "count": len(outside_gdf),
            "total_area_ha": round(float(outside_gdf["area_ha"].sum()), 4) if len(outside_gdf) else 0.0,
        },
        "unknown_classification": {
            "path": unknown_path,
            "count": len(unknown_gdf),
            "total_area_ha": round(float(unknown_gdf["area_ha"].sum()), 4) if len(unknown_gdf) else 0.0,
            "note": "Polygons with no WorldCover coverage to classify. Not routed to either "
                    "alert pathway - requires manual review.",
        },
    }

    manifest_path = os.path.join(BOUNDARY_CHECK_DIR, f"boundary_check_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
