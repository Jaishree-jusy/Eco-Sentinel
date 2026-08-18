"""
Tests for Module 7B - NGO Dashboard.
"""

import pytest
from app import create_app
import app.dashboards.ngo.routes as ngo_routes


SAMPLE_ALERT = {
    "alert_id": "ALERT-OUT-00001",
    "date_time": "2026-08-04T00:00:00",
    "location": {"latitude": 12.90, "longitude": 74.85},
    "area_lost_ha": 1.2,
    "region_area_type": "Urban",
    "polygon_id": "LOSS-xyz789uvw012",
    "geometry": {"type": "Polygon", "coordinates": [[[74.85, 12.90], [74.86, 12.90], [74.86, 12.91], [74.85, 12.90]]]},
}

SAMPLE_META = {
    "base_year": 2023, "comparison_year": 2025, "total_alerts": 1,
    "total_area_ha": 1.2, "evidence_generated_count": 0,
}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_ngo_dashboard_no_data(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "load_ngo_dashboard_data", lambda: (None, None))
    response = client.get("/ngo/")
    assert response.status_code == 200
    assert b"No data available" in response.data


def test_ngo_dashboard_with_data(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "load_ngo_dashboard_data", lambda: ([SAMPLE_ALERT], SAMPLE_META))
    response = client.get("/ngo/")
    assert response.status_code == 200
    assert b"awareness and community action" in response.data


def test_ngo_alerts_geojson(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "load_ngo_dashboard_data", lambda: ([SAMPLE_ALERT], SAMPLE_META))
    response = client.get("/ngo/api/alerts.geojson")
    data = response.get_json()
    assert data["features"][0]["properties"]["region_area_type"] == "Urban"


def test_ngo_alerts_list(client, monkeypatch):
    # alerts_list() now queries get_summary + get_ngo_alerts_page_data
    # directly (SQL-level pagination), not load_ngo_dashboard_data.
    monkeypatch.setattr(ngo_routes, "get_summary", lambda branch: SAMPLE_META)
    monkeypatch.setattr(ngo_routes, "get_ngo_alerts_page_data", lambda page, per_page: ([SAMPLE_ALERT], 1))
    response = client.get("/ngo/alerts")
    assert response.status_code == 200
    assert b"ALERT-OUT-00001" in response.data


def test_ngo_alert_detail_no_evidence_note(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "get_ngo_alert_by_id", lambda aid: SAMPLE_ALERT)
    response = client.get("/ngo/alerts/ALERT-OUT-00001")
    assert response.status_code == 200
    assert b"No evidence package" in response.data  # honest architecture note


def test_ngo_alert_detail_not_found(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "get_ngo_alert_by_id", lambda aid: None)
    response = client.get("/ngo/alerts/NONEXISTENT")
    assert response.status_code == 404


def test_ngo_trends_page(client, monkeypatch):
    # trends() now queries get_summary + get_ngo_trends_data directly
    # (SQL GROUP BY), not load_ngo_dashboard_data.
    monkeypatch.setattr(ngo_routes, "get_summary", lambda branch: SAMPLE_META)
    monkeypatch.setattr(ngo_routes, "get_ngo_trends_data", lambda: ({"Urban": 1}, {"Urban": 1.2}))
    response = client.get("/ngo/trends")
    assert response.status_code == 200
    assert b"Urban" in response.data
    assert b"only one acquisition run exists" in response.data


def test_ngo_awareness_page(client, monkeypatch):
    monkeypatch.setattr(ngo_routes, "get_summary", lambda branch: SAMPLE_META)
    monkeypatch.setattr(ngo_routes, "get_ngo_top_by_area", lambda limit=15: [SAMPLE_ALERT])
    response = client.get("/ngo/awareness")
    assert response.status_code == 200
    assert b"ALERT-OUT-00001" in response.data


def test_both_dashboards_coexist(client):
    """Confirms government and NGO blueprints don't conflict with each other."""
    gov_response = client.get("/government/")
    ngo_response = client.get("/ngo/")
    assert gov_response.status_code == 200
    assert ngo_response.status_code == 200
