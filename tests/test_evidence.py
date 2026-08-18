"""
Tests for Module 8 - Evidence Generation.

Uses a small synthetic 18-band raster (enough to cover TCI_R=16, TCI_G=17,
TCI_B=18) and a known polygon to verify each evidence artifact generates
correctly, without needing your real 700MB files.
"""

import os
import json
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from app.evidence.map_snapshot import generate_map_snapshot, _compute_adaptive_buffer
from app.evidence.geojson_export import export_alert_geojson
from app.evidence.metadata import build_and_write_metadata
from app.evidence.pdf_report import generate_pdf_report


SAMPLE_ALERT = {
    "alert_id": "ALERT-IN-00001",
    "date_time": "2026-08-04T00:00:00",
    "location": {"latitude": 12.85, "longitude": 74.90},
    "area_lost_ha": 2.5,
    "severity_level": "moderate",
    "region_division": "TestDistrict",
    "polygon_id": "loss_00001",
}


def _make_synthetic_raster(path, height=100, width=100, pixel_size=0.0001):
    transform = from_origin(74.89, 12.86, pixel_size, pixel_size)
    band_names = {16: "TCI_R", 17: "TCI_G", 18: "TCI_B"}
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=18,
        dtype="float64", crs="EPSG:4326", transform=transform,
    ) as dst:
        for band_num in range(1, 19):
            if band_num == 16:
                data = np.full((height, width), 150.0)  # TCI_R
            elif band_num == 17:
                data = np.full((height, width), 180.0)  # TCI_G
            elif band_num == 18:
                data = np.full((height, width), 100.0)  # TCI_B
            else:
                data = np.zeros((height, width))
            dst.write(data, band_num)
            if band_num in band_names:
                dst.set_band_description(band_num, band_names[band_num])


def _make_synthetic_gee_style_raster(path, height=100, width=100, pixel_size=0.0001):
    """A leaner, live-GEE-style raster: only B2/B3/B4 (no TCI), to test the
    fallback path Module 8 needs for freshly-acquired imagery."""
    transform = from_origin(74.89, 12.86, pixel_size, pixel_size)
    band_names = {1: "B2", 2: "B3", 3: "B4"}  # Blue, Green, Red
    with rasterio.open(
        path, "w", driver="GTiff", height=height, width=width, count=3,
        dtype="float64", crs="EPSG:4326", transform=transform,
    ) as dst:
        values = {1: 900.0, 2: 1100.0, 3: 850.0}  # realistic-scale raw reflectance
        for band_num in range(1, 4):
            dst.write(np.full((height, width), values[band_num]), band_num)
            dst.set_band_description(band_num, band_names[band_num])


def test_compute_adaptive_buffer_grows_for_tiny_polygon():
    tiny = box(74.895, 12.855, 74.8951, 12.8551)  # ~0.0001 deg wide
    buf_x, buf_y = _compute_adaptive_buffer(tiny, pixel_size=0.0001, min_pixels=60)
    # buffer should be large enough that final window >= 60 pixels wide
    assert buf_x > 0.001


def test_generate_map_snapshot_creates_file(tmp_path):
    raster_path = os.path.join(tmp_path, "raw.tif")
    _make_synthetic_raster(raster_path)

    geometry = box(74.895, 12.855, 74.896, 12.856)
    output_path = os.path.join(tmp_path, "snapshot.png")

    with rasterio.open(raster_path) as src:
        result_path = generate_map_snapshot(src, geometry, output_path)

    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 0


def test_export_alert_geojson(tmp_path):
    geometry = box(74.895, 12.855, 74.896, 12.856)
    output_path = os.path.join(tmp_path, "polygon.geojson")

    export_alert_geojson(SAMPLE_ALERT, geometry, "EPSG:4326", output_path)

    assert os.path.exists(output_path)
    with open(output_path) as f:
        data = json.load(f)
    props = data["features"][0]["properties"]
    assert props["alert_id"] == "ALERT-IN-00001"
    assert props["latitude"] == 12.85   # flattened from nested location dict
    assert props["longitude"] == 74.90
    assert "location" not in props      # nested dict should not survive


def test_build_and_write_metadata(tmp_path):
    output_path = os.path.join(tmp_path, "metadata.json")
    evidence_paths = {"map_snapshot": "x.png", "geojson": "x.geojson", "pdf_report": "x.pdf"}

    build_and_write_metadata(SAMPLE_ALERT, evidence_paths, output_path)

    with open(output_path) as f:
        data = json.load(f)
    assert data["alert_id"] == "ALERT-IN-00001"
    assert data["evidence_files"]["pdf_report"] == "x.pdf"
    assert "evidence_generated_at" in data


def test_generate_pdf_report(tmp_path):
    raster_path = os.path.join(tmp_path, "raw.tif")
    _make_synthetic_raster(raster_path)
    geometry = box(74.895, 12.855, 74.896, 12.856)
    map_path = os.path.join(tmp_path, "snapshot.png")

    with rasterio.open(raster_path) as src:
        generate_map_snapshot(src, geometry, map_path)

    pdf_path = os.path.join(tmp_path, "report.pdf")
    generate_pdf_report(SAMPLE_ALERT, map_path, pdf_path)

    assert os.path.exists(pdf_path)
    assert os.path.getsize(pdf_path) > 0


def test_generate_map_snapshot_gee_style_fallback(tmp_path):
    """Regression test: a live-GEE-acquired file has no TCI bands, only
    raw B2/B3/B4 - map snapshot generation must fall back to those and
    correctly rescale raw reflectance for visualization."""
    raster_path = os.path.join(tmp_path, "gee_raw.tif")
    _make_synthetic_gee_style_raster(raster_path)
    geometry = box(74.895, 12.855, 74.896, 12.856)
    output_path = os.path.join(tmp_path, "snapshot_gee.png")

    with rasterio.open(raster_path) as src:
        result_path = generate_map_snapshot(src, geometry, output_path)

    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 0
