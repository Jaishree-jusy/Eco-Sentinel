"""
Tests for Module 6B pipeline (legality_pipeline.py).
"""

import os
import geopandas as gpd
from shapely.geometry import Point

from app.boundary_check.legality_pipeline import run_legality_check
from app.boundary_check.legality import LEGAL_STATUS_UNKNOWN, LEGAL_STATUS_AUTHORIZED


def _make_inside_forest_geojson(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "polygon_id": ["LOSS-aaa", "LOSS-bbb"],
            "area_ha": [1.0, 2.0],
            "severity_level": ["mild", "moderate"],
        },
        geometry=[Point(74.9, 12.85).buffer(0.001), Point(74.95, 12.90).buffer(0.001)],
        crs="EPSG:4326",
    )
    path = os.path.join(tmp_path, "inside_forest.geojson")
    gdf.to_file(path, driver="GeoJSON")
    return path


def test_run_legality_check_defaults_to_unknown_with_no_dataset(tmp_path, monkeypatch):
    import app.boundary_check.legality_pipeline as lp
    monkeypatch.setattr(lp, "BOUNDARY_CHECK_DIR", str(tmp_path))

    inside_path = _make_inside_forest_geojson(tmp_path)
    boundary_manifest = {
        "inside_forest": {"path": inside_path}, "base_year": 2023, "comparison_year": 2025, "run_id": "fake",
    }

    manifest = run_legality_check(boundary_manifest, authorization_dataset_path=None)

    assert manifest["authorization_dataset_configured"] is False
    assert manifest["status_counts"] == {LEGAL_STATUS_UNKNOWN: 2}

    result_gdf = gpd.read_file(manifest["output_path"])
    assert all(result_gdf["legality_status"] == LEGAL_STATUS_UNKNOWN)
    assert all(result_gdf["matched_authorization_id"].isna())


def test_run_legality_check_with_real_dataset(tmp_path, monkeypatch):
    import app.boundary_check.legality_pipeline as lp
    monkeypatch.setattr(lp, "BOUNDARY_CHECK_DIR", str(tmp_path))

    inside_path = _make_inside_forest_geojson(tmp_path)

    from shapely.geometry import box
    auth_gdf = gpd.GeoDataFrame([{
        "authorization_id": "AUTH-001", "holder_name": "Test", "authorization_type": "clear-felling",
        "issuing_authority": "Forest Dept", "issue_date": "2024-01-01",
        "valid_from": "2024-01-01", "valid_until": "2026-12-31",
        "max_authorized_area_ha": 5.0, "status": "active", "document_reference": "DOC-001",
        "geometry": box(74.89, 12.84, 74.91, 12.86),  # covers LOSS-aaa only
    }], crs="EPSG:4326")
    auth_path = os.path.join(tmp_path, "auth.gpkg")
    auth_gdf.to_file(auth_path, driver="GPKG")

    boundary_manifest = {
        "inside_forest": {"path": inside_path}, "base_year": 2023, "comparison_year": 2025, "run_id": "fake",
    }

    manifest = run_legality_check(boundary_manifest, authorization_dataset_path=auth_path)

    assert manifest["authorization_dataset_configured"] is True
    result_gdf = gpd.read_file(manifest["output_path"])
    statuses = dict(zip(result_gdf["polygon_id"], result_gdf["legality_status"]))
    assert statuses["LOSS-aaa"] == LEGAL_STATUS_AUTHORIZED
