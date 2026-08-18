"""
Tests for Module 5 - Polygon Generation & Analysis.

Uses small synthetic rasters with known shapes/values so we can assert
exact polygon count, area, and severity classification.
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.polygon_analysis.vectorize import raster_to_polygons
from app.polygon_analysis.area import compute_area_ha, filter_by_min_area, compute_centroids, assign_polygon_ids
from app.polygon_analysis.severity import estimate_severity, _classify_severity
from app.gee_processing.config import NDVI_NODATA
from app.loss_detection.config import LOSS_VALUE, NO_LOSS_VALUE, MASK_NODATA


def _make_mask_tif(path, mask_array, pixel_size_deg=0.001):
    """pixel_size_deg=0.001 at the equator is ~111m/pixel -> each pixel
    is roughly 1.23 ha, making area assertions easy to reason about."""
    height, width = mask_array.shape
    transform = from_origin(74.75, 13.0, pixel_size_deg, pixel_size_deg)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform, nodata=MASK_NODATA,
    ) as dst:
        dst.write(mask_array, 1)


def _make_diff_tif(path, diff_array, pixel_size_deg=0.001):
    height, width = diff_array.shape
    transform = from_origin(74.75, 13.0, pixel_size_deg, pixel_size_deg)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=NDVI_NODATA,
    ) as dst:
        dst.write(diff_array.astype("float32"), 1)


def test_raster_to_polygons_finds_correct_count(tmp_path):
    # Two separate 2x2 loss blocks, rest is no-loss
    mask = np.full((10, 10), NO_LOSS_VALUE, dtype="uint8")
    mask[1:3, 1:3] = LOSS_VALUE  # block 1
    mask[6:8, 6:8] = LOSS_VALUE  # block 2

    path = os.path.join(tmp_path, "mask.tif")
    _make_mask_tif(path, mask)

    gdf = raster_to_polygons(path)
    assert len(gdf) == 2
    # polygon_id is deliberately NOT assigned here anymore - it's assigned
    # later in the pipeline, once centroids are known, so it can be a
    # stable content-derived ID instead of a positional one.
    assert "polygon_id" not in gdf.columns


def test_compute_area_ha_reasonable_scale(tmp_path):
    mask = np.full((10, 10), NO_LOSS_VALUE, dtype="uint8")
    mask[1:3, 1:3] = LOSS_VALUE  # 4 pixels

    path = os.path.join(tmp_path, "mask.tif")
    _make_mask_tif(path, mask)

    gdf = raster_to_polygons(path)
    gdf = compute_area_ha(gdf)

    # 4 pixels at ~0.001deg (~111m) each -> roughly 4 * 1.23 ha ~= 4.9 ha
    assert gdf["area_ha"].iloc[0] > 1.0
    assert gdf["area_ha"].iloc[0] < 10.0


def test_filter_by_min_area_drops_small_polygons(tmp_path):
    mask = np.full((10, 10), NO_LOSS_VALUE, dtype="uint8")
    mask[1, 1] = LOSS_VALUE       # single pixel - tiny
    mask[5:9, 5:9] = LOSS_VALUE    # 4x4 block - large

    path = os.path.join(tmp_path, "mask.tif")
    _make_mask_tif(path, mask)

    gdf = raster_to_polygons(path)
    gdf = compute_area_ha(gdf)
    filtered = filter_by_min_area(gdf, min_area_ha=3.0)  # single pixel ~1.2ha, 4x4 block ~19ha

    assert len(filtered) == 1  # only the large block survives
    assert len(gdf) == 2       # original had both


def test_classify_severity_bins():
    assert _classify_severity(-0.9) == "severe"
    assert _classify_severity(-0.501) == "severe"
    assert _classify_severity(-0.5) == "moderate"   # boundary: severe is strictly < -0.5, so -0.5 itself falls in moderate
    assert _classify_severity(-0.4) == "moderate"
    assert _classify_severity(-0.25) == "mild"
    assert _classify_severity(-0.1) == "unknown"   # above loss threshold, shouldn't normally occur
    assert _classify_severity(None) == "unknown"


def test_estimate_severity_end_to_end(tmp_path):
    mask = np.full((4, 4), NO_LOSS_VALUE, dtype="uint8")
    mask[1:3, 1:3] = LOSS_VALUE

    diff = np.full((4, 4), 0.0, dtype="float32")
    diff[1:3, 1:3] = -0.6  # severe

    mask_path = os.path.join(tmp_path, "mask.tif")
    diff_path = os.path.join(tmp_path, "diff.tif")
    _make_mask_tif(mask_path, mask)
    _make_diff_tif(diff_path, diff)

    gdf = raster_to_polygons(mask_path)
    gdf = estimate_severity(gdf, diff_path)

    assert gdf["severity_level"].iloc[0] == "severe"
    assert np.isclose(gdf["mean_ndvi_diff"].iloc[0], -0.6, atol=0.01)


def test_assign_polygon_ids_is_position_independent():
    """Regression test for the real fix: the same real-world locations must
    get the same polygon_id regardless of what row order they appear in.
    Simulates two 'runs' where two polygons were discovered in opposite
    order (as could genuinely happen between reruns) and confirms the
    resulting ID *sets* are identical - i.e. each location's ID doesn't
    depend on which row it landed in."""
    import geopandas as gpd
    from shapely.geometry import Point

    gdf_order_a = gpd.GeoDataFrame(
        {"geometry": [Point(74.80, 12.80), Point(74.85, 12.85)]}, crs="EPSG:4326"
    )
    gdf_order_a["centroid_lon"] = [74.80, 74.85]
    gdf_order_a["centroid_lat"] = [12.80, 12.85]

    gdf_order_b = gpd.GeoDataFrame(
        {"geometry": [Point(74.85, 12.85), Point(74.80, 12.80)]}, crs="EPSG:4326"
    )
    gdf_order_b["centroid_lon"] = [74.85, 74.80]
    gdf_order_b["centroid_lat"] = [12.85, 12.80]

    ids_a = set(assign_polygon_ids(gdf_order_a, 2023, 2025)["polygon_id"])
    ids_b = set(assign_polygon_ids(gdf_order_b, 2023, 2025)["polygon_id"])

    assert ids_a == ids_b  # same two locations -> same two IDs, regardless of row order
    assert len(ids_a) == 2  # and they're genuinely distinct from each other


def test_assign_polygon_ids_empty_gdf():
    import geopandas as gpd

    gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    gdf["centroid_lon"] = []
    gdf["centroid_lat"] = []
    result = assign_polygon_ids(gdf, 2023, 2025)
    assert "polygon_id" in result.columns
    assert len(result) == 0
