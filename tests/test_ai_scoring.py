"""
Tests for app.polygon_analysis.ai_scoring.
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import box

from app.polygon_analysis.ai_scoring import estimate_ai_disturbance, default_detection_class_no_ai
from app.loss_detection.ai_disturbance import ANOMALY_NODATA


def _make_anomaly_raster(path, value_grid):
    height, width = value_grid.shape
    transform = from_origin(74.75, 13.0, 0.0001, 0.0001)
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform, nodata=ANOMALY_NODATA,
    ) as dst:
        dst.write(value_grid.astype("float32"), 1)


def test_estimate_ai_disturbance_high_confidence_when_ai_agrees(tmp_path):
    grid = np.full((10, 10), 0.9, dtype="float32")  # high anomaly everywhere
    raster_path = os.path.join(tmp_path, "anomaly.tif")
    _make_anomaly_raster(raster_path, grid)

    gdf = gpd.GeoDataFrame(
        {"polygon_id": ["LOSS-001"]},
        geometry=[box(74.7501, 12.9991, 74.7509, 12.9999)],
        crs="EPSG:4326",
    )

    result = estimate_ai_disturbance(gdf, raster_path)
    assert result["detection_class"].iloc[0] == "high_confidence_loss"
    assert result["mean_anomaly_score"].iloc[0] > 0.5


def test_estimate_ai_disturbance_vegetation_loss_when_ai_disagrees(tmp_path):
    grid = np.full((10, 10), 0.1, dtype="float32")  # low anomaly everywhere
    raster_path = os.path.join(tmp_path, "anomaly.tif")
    _make_anomaly_raster(raster_path, grid)

    gdf = gpd.GeoDataFrame(
        {"polygon_id": ["LOSS-001"]},
        geometry=[box(74.7501, 12.9991, 74.7509, 12.9999)],
        crs="EPSG:4326",
    )

    result = estimate_ai_disturbance(gdf, raster_path)
    assert result["detection_class"].iloc[0] == "vegetation_loss"


def test_default_detection_class_no_ai():
    gdf = gpd.GeoDataFrame({"polygon_id": ["LOSS-001", "LOSS-002"]}, geometry=[box(0, 0, 1, 1), box(1, 1, 2, 2)], crs="EPSG:4326")
    result = default_detection_class_no_ai(gdf)
    assert all(result["detection_class"] == "vegetation_loss")
    assert all(result["mean_anomaly_score"].isna())


def test_estimate_ai_disturbance_empty_gdf():
    gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:4326")
    result = estimate_ai_disturbance(gdf, "/nonexistent.tif")
    assert "detection_class" in result.columns
    assert len(result) == 0
