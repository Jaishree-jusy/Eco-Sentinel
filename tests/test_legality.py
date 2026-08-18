"""
Tests for Module 6B - Legality / Authorization Check.

The most important tests here are the safeguard ones: absence of legal
data must never be treated as evidence of illegality.
"""

import os
import geopandas as gpd
import pytest
from shapely.geometry import box, Point

from app.boundary_check.legality import (
    load_authorization_dataset, check_legality, derive_final_alert_category,
    LEGAL_STATUS_AUTHORIZED, LEGAL_STATUS_NO_AUTHORIZATION_FOUND,
    LEGAL_STATUS_UNKNOWN, LEGAL_STATUS_POTENTIAL_ILLEGAL,
    REQUIRED_AUTHORIZATION_COLUMNS,
)


def _make_authorization_gdf(rows):
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


# ---------------------------------------------------------------------
# The critical safeguard
# ---------------------------------------------------------------------

def test_no_dataset_configured_returns_unknown_not_missing():
    result = check_legality(Point(74.9, 12.85).buffer(0.001), "2025-06-01", None)
    assert result["legality_status"] == LEGAL_STATUS_UNKNOWN
    assert result["matched_authorization_id"] is None


def test_load_authorization_dataset_returns_none_when_no_path():
    assert load_authorization_dataset(None) is None
    assert load_authorization_dataset("/nonexistent/path.gpkg") is None


def test_unknown_never_becomes_potential_illegal():
    """The safeguard rule, tested directly: no matter the detection class,
    'unknown' must stay 'unknown', never escalate to illegal."""
    for detection_class in ["vegetation_loss", "high_confidence_loss", "potential_disturbance", "no_detection"]:
        result = derive_final_alert_category(detection_class, LEGAL_STATUS_UNKNOWN)
        assert result == LEGAL_STATUS_UNKNOWN
        assert result != LEGAL_STATUS_POTENTIAL_ILLEGAL


def test_no_authorization_found_plus_detection_becomes_potential_illegal():
    result = derive_final_alert_category("vegetation_loss", LEGAL_STATUS_NO_AUTHORIZATION_FOUND)
    assert result == LEGAL_STATUS_POTENTIAL_ILLEGAL


def test_no_authorization_found_without_detection_does_not_escalate():
    result = derive_final_alert_category("no_detection", LEGAL_STATUS_NO_AUTHORIZATION_FOUND)
    assert result == LEGAL_STATUS_NO_AUTHORIZATION_FOUND  # no detection at all -> nothing to escalate


# ---------------------------------------------------------------------
# Real matching logic, once a dataset IS supplied
# ---------------------------------------------------------------------

def test_matched_active_authorization():
    detected = box(74.90, 12.85, 74.905, 12.855)
    auth_gdf = _make_authorization_gdf([{
        "authorization_id": "AUTH-001", "holder_name": "Test Holder",
        "authorization_type": "clear-felling", "issuing_authority": "Forest Dept",
        "issue_date": "2024-01-01", "valid_from": "2024-01-01", "valid_until": "2026-12-31",
        "max_authorized_area_ha": 5.0, "status": "active", "document_reference": "DOC-001",
        "geometry": box(74.89, 12.84, 74.91, 12.86),  # fully covers detected
    }])

    result = check_legality(detected, "2025-06-01", auth_gdf)
    assert result["legality_status"] == LEGAL_STATUS_AUTHORIZED
    assert result["matched_authorization_id"] == "AUTH-001"


def test_coverage_exists_but_outside_validity_window():
    detected = box(74.90, 12.85, 74.905, 12.855)
    auth_gdf = _make_authorization_gdf([{
        "authorization_id": "AUTH-002", "holder_name": "Test Holder",
        "authorization_type": "clear-felling", "issuing_authority": "Forest Dept",
        "issue_date": "2020-01-01", "valid_from": "2020-01-01", "valid_until": "2021-12-31",  # expired
        "max_authorized_area_ha": 5.0, "status": "active", "document_reference": "DOC-002",
        "geometry": box(74.89, 12.84, 74.91, 12.86),
    }])

    result = check_legality(detected, "2025-06-01", auth_gdf)
    assert result["legality_status"] == LEGAL_STATUS_NO_AUTHORIZATION_FOUND


def test_revoked_authorization_does_not_count():
    detected = box(74.90, 12.85, 74.905, 12.855)
    auth_gdf = _make_authorization_gdf([{
        "authorization_id": "AUTH-003", "holder_name": "Test Holder",
        "authorization_type": "clear-felling", "issuing_authority": "Forest Dept",
        "issue_date": "2024-01-01", "valid_from": "2024-01-01", "valid_until": "2026-12-31",
        "max_authorized_area_ha": 5.0, "status": "revoked", "document_reference": "DOC-003",
        "geometry": box(74.89, 12.84, 74.91, 12.86),
    }])

    result = check_legality(detected, "2025-06-01", auth_gdf)
    assert result["legality_status"] == LEGAL_STATUS_NO_AUTHORIZATION_FOUND


def test_no_spatial_coverage_at_all_is_unknown_not_negative():
    """A dataset exists but has zero records anywhere near this polygon -
    that's a gap in records, not a confirmed 'no authorization'."""
    detected = box(74.90, 12.85, 74.905, 12.855)
    auth_gdf = _make_authorization_gdf([{
        "authorization_id": "AUTH-004", "holder_name": "Elsewhere",
        "authorization_type": "clear-felling", "issuing_authority": "Forest Dept",
        "issue_date": "2024-01-01", "valid_from": "2024-01-01", "valid_until": "2026-12-31",
        "max_authorized_area_ha": 5.0, "status": "active", "document_reference": "DOC-004",
        "geometry": box(80.0, 20.0, 80.1, 20.1),  # nowhere near the detected polygon
    }])

    result = check_legality(detected, "2025-06-01", auth_gdf)
    assert result["legality_status"] == LEGAL_STATUS_UNKNOWN


def test_partial_overlap_below_threshold_is_no_authorization_found():
    detected = box(74.90, 12.85, 74.91, 12.86)  # larger area
    auth_gdf = _make_authorization_gdf([{
        "authorization_id": "AUTH-005", "holder_name": "Test Holder",
        "authorization_type": "clear-felling", "issuing_authority": "Forest Dept",
        "issue_date": "2024-01-01", "valid_from": "2024-01-01", "valid_until": "2026-12-31",
        "max_authorized_area_ha": 5.0, "status": "active", "document_reference": "DOC-005",
        "geometry": box(74.90, 12.85, 74.901, 12.851),  # tiny corner overlap only
    }])

    result = check_legality(detected, "2025-06-01", auth_gdf, overlap_threshold=0.70)
    assert result["legality_status"] == LEGAL_STATUS_NO_AUTHORIZATION_FOUND


def test_load_authorization_dataset_missing_required_columns(tmp_path):
    bad_gdf = gpd.GeoDataFrame({"some_column": [1]}, geometry=[box(0, 0, 1, 1)], crs="EPSG:4326")
    path = os.path.join(tmp_path, "bad_auth.gpkg")
    bad_gdf.to_file(path, driver="GPKG")

    with pytest.raises(ValueError, match="missing required columns"):
        load_authorization_dataset(path)
