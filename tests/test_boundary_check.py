"""
Tests for Module 6 - Forest Boundary Check.
"""

import os
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import Polygon, box, Point

from app.boundary_check.landcover_lookup import classify_points_by_landcover, BoundaryCheckError
from app.boundary_check.region_lookup import assign_regions
from app.boundary_check.config import FOREST_CLASS_VALUE


def _make_worldcover_tif(path, class_grid, origin_lon=74.75, origin_lat=13.0, pixel_size=0.01):
    height, width = class_grid.shape
    transform = from_origin(origin_lon, origin_lat, pixel_size, pixel_size)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(class_grid.astype("uint8"), 1)


def test_classify_points_forest_and_nonforest(tmp_path):
    # 10x10 grid: left half tree cover (10), right half cropland (40)
    grid = np.full((10, 10), 40, dtype="uint8")
    grid[:, :5] = FOREST_CLASS_VALUE

    path = os.path.join(tmp_path, "wc.tif")
    _make_worldcover_tif(path, grid)

    # Points: one clearly in the left (forest) half, one in the right (non-forest) half.
    # Grid spans lon 74.75-74.85 (10 cols x 0.01deg); right half = cols 5-9 = lon 74.80-74.85.
    lons = [74.76, 74.82]
    lats = [12.96, 12.96]

    result = classify_points_by_landcover(path, lons, lats)
    assert result == ["inside_forest", "outside_forest"]


def test_classify_points_out_of_extent(tmp_path):
    grid = np.full((5, 5), FOREST_CLASS_VALUE, dtype="uint8")
    path = os.path.join(tmp_path, "wc.tif")
    _make_worldcover_tif(path, grid, origin_lon=74.75, origin_lat=13.0, pixel_size=0.01)

    # Way outside the raster's small 5x5 extent
    result = classify_points_by_landcover(path, [80.0], [20.0])
    assert result == ["out_of_extent"]


def test_classify_points_raises_if_forest_class_absent(tmp_path):
    grid = np.full((5, 5), 40, dtype="uint8")  # only cropland, no tree cover anywhere
    path = os.path.join(tmp_path, "wc.tif")
    _make_worldcover_tif(path, grid)

    with pytest.raises(BoundaryCheckError):
        classify_points_by_landcover(path, [74.76], [12.96])


def test_assign_regions_uses_available_column(tmp_path):
    # Simulate a GADM-like layer with NAME_2 present
    admin_gdf = gpd.GeoDataFrame(
        {"NAME_1": ["Karnataka"], "NAME_2": ["TestDistrict"]},
        geometry=[box(74.0, 12.0, 76.0, 14.0)],
        crs="EPSG:4326",
    )
    gadm_path = os.path.join(tmp_path, "test.gpkg")
    admin_gdf.to_file(gadm_path, driver="GPKG", layer="ADM_ADM_2")

    points_gdf = gpd.GeoDataFrame(
        {"polygon_id": ["loss_00000"]},
        geometry=[Polygon([(74.5, 12.5), (74.5, 12.6), (74.6, 12.6), (74.6, 12.5)]).centroid],
        crs="EPSG:4326",
    )

    regions, column_used = assign_regions(points_gdf, gadm_path, layer="ADM_ADM_2")
    assert column_used == "NAME_2"
    assert regions == ["TestDistrict"]


def test_run_boundary_check_separates_unknown_from_outside(tmp_path):
    """Regression test for the real fix: 'out_of_extent' polygons must land
    in their own bucket, never silently merged into 'outside_forest'."""
    from app.boundary_check.pipeline import run_boundary_check

    # WorldCover raster: small 10x10 grid, left half forest, right half cropland.
    # Spans lon 74.75-74.85, lat 12.90-13.00.
    grid = np.full((10, 10), 40, dtype="uint8")
    grid[:, :5] = FOREST_CLASS_VALUE
    worldcover_path = os.path.join(tmp_path, "wc.tif")
    _make_worldcover_tif(worldcover_path, grid)

    # GADM boundary covering the raster's area
    admin_gdf = gpd.GeoDataFrame(
        {"NAME_2": ["TestDistrict"]}, geometry=[box(74.0, 12.0, 76.0, 14.0)], crs="EPSG:4326"
    )
    gadm_path = os.path.join(tmp_path, "gadm.gpkg")
    admin_gdf.to_file(gadm_path, driver="GPKG", layer="ADM_ADM_2")

    # Three loss polygons: one inside forest, one outside forest (still
    # within raster extent), one FAR outside the raster's extent entirely.
    loss_gdf = gpd.GeoDataFrame(
        {
            "polygon_id": ["LOSS-aaa", "LOSS-bbb", "LOSS-ccc"],
            "centroid_lon": [74.76, 74.82, 80.0],
            "centroid_lat": [12.96, 12.96, 20.0],
            "area_ha": [1.0, 1.0, 1.0],
            "severity_level": ["mild", "mild", "mild"],
        },
        geometry=[Point(74.76, 12.96), Point(74.82, 12.96), Point(80.0, 20.0)],
        crs="EPSG:4326",
    )
    geojson_path = os.path.join(tmp_path, "loss_polygons.geojson")
    loss_gdf.to_file(geojson_path, driver="GeoJSON")

    polygon_manifest = {
        "geojson_path": geojson_path, "base_year": 2023, "comparison_year": 2025, "run_id": "fake",
    }
    acquisition_manifest = {
        "datasets": {
            "worldcover_2021": {"path": worldcover_path},
            "gadm_forest_boundary": {"path": gadm_path},
        }
    }

    import app.boundary_check.pipeline as bc_pipeline
    monkeypatch_dir = os.path.join(tmp_path, "boundary_check_out")

    original_dir = bc_pipeline.BOUNDARY_CHECK_DIR
    bc_pipeline.BOUNDARY_CHECK_DIR = monkeypatch_dir
    try:
        manifest = run_boundary_check(polygon_manifest, acquisition_manifest)
    finally:
        bc_pipeline.BOUNDARY_CHECK_DIR = original_dir

    assert manifest["inside_forest"]["count"] == 1
    assert manifest["outside_forest"]["count"] == 1
    assert manifest["unknown_classification"]["count"] == 1

    # Confirm the outside-forest file does NOT contain the out-of-extent polygon
    outside_gdf = gpd.read_file(manifest["outside_forest"]["path"])
    assert "LOSS-ccc" not in outside_gdf["polygon_id"].values

    unknown_gdf = gpd.read_file(manifest["unknown_classification"]["path"])
    assert list(unknown_gdf["polygon_id"]) == ["LOSS-ccc"]
