
"""
Module 6 pipeline orchestration.

Classifies polygons as inside forest, outside forest, or unknown.
An optional output_suffix allows isolated test runs without overwriting
the standard year-based GeoJSON outputs.
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
from app.boundary_check.landcover_lookup import (
    classify_points_by_landcover,
    BoundaryCheckError,
)
from app.boundary_check.region_lookup import assign_regions


class BoundaryPipelineError(Exception):
    pass


def _find_latest(pattern, timestamp_key):
    candidates = []

    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            candidates.append((data[timestamp_key], path, data))
        except (OSError, json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][2]


def _find_latest_polygon_analysis_manifest():
    manifest = _find_latest(
        os.path.join(POLYGON_ANALYSIS_DIR, "polygon_analysis_*.json"),
        "analyzed_at",
    )

    if manifest is None:
        raise BoundaryPipelineError(
            "No Module 5 polygon analysis manifest found."
        )

    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(
        os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"),
        "triggered_at",
    )

    if manifest is None:
        raise BoundaryPipelineError(
            "No Module 2 acquisition manifest found."
        )

    return manifest


def run_boundary_check(
    polygon_manifest=None,
    acquisition_manifest=None,
    output_suffix=None,
):
    if polygon_manifest is None:
        polygon_manifest = _find_latest_polygon_analysis_manifest()

    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    geojson_path = polygon_manifest["geojson_path"]
    base_year = polygon_manifest["base_year"]
    comparison_year = polygon_manifest["comparison_year"]

    datasets = acquisition_manifest["datasets"]

    required_datasets = ("worldcover_2021", "gadm_forest_boundary")
    missing = [key for key in required_datasets if key not in datasets]

    if missing:
        raise BoundaryPipelineError(
            f"Acquisition manifest is missing datasets: {missing}"
        )

    worldcover_path = datasets["worldcover_2021"]["path"]
    gadm_path = datasets["gadm_forest_boundary"]["path"]

    if not os.path.exists(geojson_path):
        raise BoundaryPipelineError(
            f"Loss polygons GeoJSON not found: {geojson_path}"
        )

    gdf = gpd.read_file(geojson_path)

    if gdf.empty:
        raise BoundaryPipelineError(
            "No polygons to classify; input GeoJSON is empty."
        )

    required_columns = {
        "polygon_id",
        "centroid_lon",
        "centroid_lat",
        "area_ha",
        "geometry",
    }
    missing_columns = required_columns - set(gdf.columns)

    if missing_columns:
        raise BoundaryPipelineError(
            f"Polygon GeoJSON is missing fields: {sorted(missing_columns)}"
        )

    if gdf.crs is None:
        raise BoundaryPipelineError(
            "Polygon GeoJSON has no CRS; refusing to guess."
        )

    points_gdf = gpd.GeoDataFrame(
        gdf[["polygon_id"]].copy(),
        geometry=gpd.points_from_xy(
            gdf["centroid_lon"],
            gdf["centroid_lat"],
        ),
        crs="EPSG:4326",
    )

    try:
        classifications = classify_points_by_landcover(
            worldcover_path,
            gdf["centroid_lon"].tolist(),
            gdf["centroid_lat"].tolist(),
        )
    except BoundaryCheckError as exc:
        raise BoundaryPipelineError(str(exc)) from exc

    regions, region_column_used = assign_regions(points_gdf, gadm_path)

    classified = gdf.copy()
    classified["location_classification"] = classifications
    classified["region_division"] = regions

    inside_gdf = classified[
        classified["location_classification"] == "inside_forest"
    ].reset_index(drop=True)

    outside_gdf = classified[
        classified["location_classification"] == "outside_forest"
    ].reset_index(drop=True)

    unknown_gdf = classified[
        classified["location_classification"] == "out_of_extent"
    ].reset_index(drop=True)

    os.makedirs(BOUNDARY_CHECK_DIR, exist_ok=True)

    run_id = str(uuid.uuid4())

    # No suffix means the original filenames and behavior are preserved.
    suffix = f"_{output_suffix}" if output_suffix else ""

    inside_path = os.path.join(
        BOUNDARY_CHECK_DIR,
        f"inside_forest_{base_year}_{comparison_year}{suffix}.geojson",
    )
    outside_path = os.path.join(
        BOUNDARY_CHECK_DIR,
        f"outside_forest_{base_year}_{comparison_year}{suffix}.geojson",
    )
    unknown_path = os.path.join(
        BOUNDARY_CHECK_DIR,
        f"unknown_classification_{base_year}_{comparison_year}{suffix}.geojson",
    )

    inside_gdf.to_file(inside_path, driver="GeoJSON")
    outside_gdf.to_file(outside_path, driver="GeoJSON")
    unknown_gdf.to_file(unknown_path, driver="GeoJSON")

    manifest = {
        "run_id": run_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source_polygon_analysis_run_id": polygon_manifest.get("run_id"),
        "base_year": base_year,
        "comparison_year": comparison_year,
        "output_suffix": output_suffix,
        "region_column_used": region_column_used,
        "inside_forest": {
            "path": inside_path,
            "count": len(inside_gdf),
            "total_area_ha": (
                round(float(inside_gdf["area_ha"].sum()), 4)
                if not inside_gdf.empty else 0.0
            ),
        },
        "outside_forest": {
            "path": outside_path,
            "count": len(outside_gdf),
            "total_area_ha": (
                round(float(outside_gdf["area_ha"].sum()), 4)
                if not outside_gdf.empty else 0.0
            ),
        },
        "unknown_classification": {
            "path": unknown_path,
            "count": len(unknown_gdf),
            "total_area_ha": (
                round(float(unknown_gdf["area_ha"].sum()), 4)
                if not unknown_gdf.empty else 0.0
            ),
            "note": (
                "Polygons without WorldCover coverage are kept separate "
                "for manual review."
            ),
        },
    }

    manifest_path = os.path.join(
        BOUNDARY_CHECK_DIR,
        f"boundary_check_{run_id}.json",
    )

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest

