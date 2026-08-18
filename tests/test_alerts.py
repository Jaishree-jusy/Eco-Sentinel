"""
Tests for Module 7 / 7A - Alert Generation.
"""

import os
import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.alerts.alert_builder import build_inside_forest_alert, build_outside_forest_alert
from app.alerts.area_type import classify_area_types
from app.alerts.config import ALERT_ID_PREFIX_INSIDE, ALERT_ID_PREFIX_OUTSIDE


def test_build_inside_forest_alert_fields():
    row = {
        "centroid_lat": 12.85,
        "centroid_lon": 74.90,
        "area_ha": 3.25,
        "severity_level": "moderate",
        "region_division": "TestDistrict",
        "polygon_id": "LOSS-abc123def456",
    }
    alert = build_inside_forest_alert(row, generated_at="2026-08-04T00:00:00")

    assert alert["alert_id"].startswith(f"{ALERT_ID_PREFIX_INSIDE}-")
    assert alert["location"]["latitude"] == 12.85
    assert alert["location"]["longitude"] == 74.90
    assert alert["area_lost_ha"] == 3.25
    assert alert["severity_level"] == "moderate"
    assert alert["region_division"] == "TestDistrict"
    assert "region_area_type" not in alert  # Box 7 shouldn't have Box 7A's field


def test_build_outside_forest_alert_fields():
    row = {
        "centroid_lat": 12.85,
        "centroid_lon": 74.90,
        "area_ha": 1.10,
        "polygon_id": "LOSS-xyz789uvw012",
    }
    alert = build_outside_forest_alert(row, area_type="Urban", generated_at="2026-08-04T00:00:00")

    assert alert["alert_id"].startswith(f"{ALERT_ID_PREFIX_OUTSIDE}-")
    assert alert["region_area_type"] == "Urban"
    assert "severity_level" not in alert  # Box 7A shouldn't have Box 7's field


def test_alert_id_is_stable_across_calls():
    """The whole point of the fix: same polygon_id -> same alert_id, every
    single time, regardless of when/how many times it's generated."""
    row = {
        "centroid_lat": 12.85, "centroid_lon": 74.90, "area_ha": 3.25,
        "severity_level": "moderate", "region_division": "TestDistrict",
        "polygon_id": "LOSS-abc123def456",
    }
    alert1 = build_inside_forest_alert(row, generated_at="2026-08-04T00:00:00")
    alert2 = build_inside_forest_alert(row, generated_at="2026-08-05T00:00:00")  # different timestamp
    assert alert1["alert_id"] == alert2["alert_id"]


def test_alert_id_differs_by_branch():
    """The same polygon_id must produce different alert_ids for the
    inside-forest vs outside-forest branch, so IDs never collide across
    the two alert lists even in an edge case where the same polygon_id
    input were somehow reused."""
    row_inside = {
        "centroid_lat": 12.85, "centroid_lon": 74.90, "area_ha": 3.25,
        "severity_level": "moderate", "region_division": "TestDistrict",
        "polygon_id": "LOSS-abc123def456",
    }
    row_outside = {
        "centroid_lat": 12.85, "centroid_lon": 74.90, "area_ha": 3.25,
        "polygon_id": "LOSS-abc123def456",
    }
    alert_in = build_inside_forest_alert(row_inside)
    alert_out = build_outside_forest_alert(row_outside, area_type="Urban")
    assert alert_in["alert_id"] != alert_out["alert_id"]


def test_alert_carries_ai_and_legality_fields_when_present():
    row = {
        "centroid_lat": 12.85, "centroid_lon": 74.90, "area_ha": 3.25,
        "severity_level": "moderate", "region_division": "TestDistrict",
        "polygon_id": "LOSS-abc123def456",
        "mean_anomaly_score": 0.82, "detection_class": "high_confidence_loss",
        "legality_status": "no_authorization_found", "matched_authorization_id": None,
    }
    alert = build_inside_forest_alert(row)
    assert alert["ai_disturbance_score"] == 0.82
    assert alert["detection_class"] == "high_confidence_loss"
    assert alert["legality_status"] == "no_authorization_found"
    # Safeguard: real detection + confirmed no-authorization -> escalates
    assert alert["final_category"] == "potential_illegal_deforestation"


def test_alert_never_escalates_from_unknown_legal_status():
    """The safeguard, tested at the actual alert-construction level: a
    polygon with high-confidence loss but UNKNOWN legal status (the
    honest default with no authorization dataset) must never be labeled
    illegal."""
    row = {
        "centroid_lat": 12.85, "centroid_lon": 74.90, "area_ha": 3.25,
        "severity_level": "severe", "region_division": "TestDistrict",
        "polygon_id": "LOSS-xyz",
        "mean_anomaly_score": 0.95, "detection_class": "high_confidence_loss",
        # legality_status column absent entirely - simulates Module 6B never having run
    }
    alert = build_inside_forest_alert(row)
    assert alert["legality_status"] == "legal_status_unknown"
    assert alert["final_category"] == "legal_status_unknown"
    assert alert["final_category"] != "potential_illegal_deforestation"


def test_classify_area_types(tmp_path):
    # 6x6 grid: col 0-1 built-up(50)=Urban, col 2-3 cropland(40)=Rural, col 4-5 water(80)=Others
    grid = np.zeros((6, 6), dtype="uint8")
    grid[:, 0:2] = 50
    grid[:, 2:4] = 40
    grid[:, 4:6] = 80

    path = os.path.join(tmp_path, "wc.tif")
    transform = from_origin(74.75, 13.0, 0.01, 0.01)
    with rasterio.open(
        path, "w", driver="GTiff", height=6, width=6, count=1,
        dtype="uint8", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(grid, 1)

    # points landing in each column-band
    lons = [74.755, 74.775, 74.795]  # col ~0, col ~2, col ~4
    lats = [12.965, 12.965, 12.965]

    result = classify_area_types(path, lons, lats)
    assert result == ["Urban", "Rural", "Others"]
