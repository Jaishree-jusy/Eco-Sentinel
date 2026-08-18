"""
Tests for Module 1 validators.

These use small synthetic files generated on the fly, so tests run without
needing your real NDVI/WorldCover/GADM/FIRMS datasets present. Run with:

    pytest tests/test_data_sources.py -v
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin
import geopandas as gpd
from shapely.geometry import Polygon
import pandas as pd

from app.data_sources.validators import validate_raster, validate_gpkg, validate_csv


def test_validate_raster_valid(tmp_path):
    path = os.path.join(tmp_path, "sample.tif")
    data = np.random.rand(1, 10, 10).astype("float32")
    transform = from_origin(76.0, 12.0, 0.01, 0.01)
    with rasterio.open(
        path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(data)

    result = validate_raster(path)
    assert result["valid"] is True
    assert result["metadata"]["crs"] == "EPSG:4326"


def test_validate_raster_missing_file():
    result = validate_raster("/nonexistent/path.tif")
    assert result["valid"] is False
    assert "not found" in result["errors"][0].lower()


def test_validate_gpkg_valid(tmp_path):
    path = os.path.join(tmp_path, "sample.gpkg")
    gdf = gpd.GeoDataFrame(
        {"name": ["test_boundary"]},
        geometry=[Polygon([(76, 12), (76, 13), (77, 13), (77, 12)])],
        crs="EPSG:4326",
    )
    gdf.to_file(path, driver="GPKG")

    result = validate_gpkg(path)
    assert result["valid"] is True
    assert result["metadata"]["feature_count"] == 1


def test_validate_csv_valid(tmp_path):
    path = os.path.join(tmp_path, "sample.csv")
    df = pd.DataFrame({
        "latitude": [12.3, 12.4],
        "longitude": [76.6, 76.7],
        "acq_date": ["2023-01-01", "2023-01-02"],
    })
    df.to_csv(path, index=False)

    result = validate_csv(path)
    assert result["valid"] is True
    assert result["metadata"]["row_count"] == 2


def test_validate_csv_missing_columns(tmp_path):
    path = os.path.join(tmp_path, "bad.csv")
    df = pd.DataFrame({"foo": [1, 2]})
    df.to_csv(path, index=False)

    result = validate_csv(path)
    assert result["valid"] is False
    assert "missing required columns" in result["errors"][0].lower()
