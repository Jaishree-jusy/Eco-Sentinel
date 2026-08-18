"""
Tests for Module 10 - Government Dashboard.

Uses monkeypatching to inject synthetic data into the dashboard routes,
so we can verify every page actually renders (catches Jinja2 template
errors, broken url_for() references, missing context variables) without
needing your real multi-GB pipeline output or a real SQLite database.
"""

import pytest
from app import create_app
import app.dashboards.government.routes as routes_module


SAMPLE_ALERT = {
    "alert_id": "ALERT-IN-00001",
    "date_time": "2026-08-04T00:00:00",
    "location": {"latitude": 12.85, "longitude": 74.90},
    "area_lost_ha": 2.5,
    "severity_level": "moderate",
    "region_division": "Dakshina Kannada",
    "polygon_id": "LOSS-abc123def456",
    "geometry": {"type": "Polygon", "coordinates": [[[74.9, 12.85], [74.91, 12.85], [74.91, 12.86], [74.9, 12.85]]]},
    "evidence_available": False,
    "evidence": None,
    "blockchain_available": False,
    "blockchain": None,
}

SAMPLE_META = {
    "base_year": 2023, "comparison_year": 2025, "total_alerts": 1,
    "total_area_ha": 2.5, "evidence_generated_count": 0,
}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_dashboard_no_data(client, monkeypatch):
    monkeypatch.setattr(routes_module, "load_dashboard_data", lambda: (None, None))
    response = client.get("/government/")
    assert response.status_code == 200
    assert b"No data available" in response.data


def test_dashboard_with_data(client, monkeypatch):
    monkeypatch.setattr(routes_module, "load_dashboard_data", lambda: ([SAMPLE_ALERT], SAMPLE_META))
    response = client.get("/government/")
    assert response.status_code == 200
    assert b"2023" in response.data


def test_alerts_geojson_endpoint(client, monkeypatch):
    monkeypatch.setattr(routes_module, "load_dashboard_data", lambda: ([SAMPLE_ALERT], SAMPLE_META))
    response = client.get("/government/api/alerts.geojson")
    assert response.status_code == 200
    data = response.get_json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert data["features"][0]["properties"]["alert_id"] == "ALERT-IN-00001"


def test_alerts_list_page(client, monkeypatch):
    # alerts_list() now queries get_summary + get_alerts_page_data directly
    # (SQL-level pagination), not load_dashboard_data - mock those instead.
    monkeypatch.setattr(routes_module, "get_summary", lambda branch: SAMPLE_META)
    monkeypatch.setattr(routes_module, "get_alerts_page_data", lambda page, per_page: ([SAMPLE_ALERT], 1))
    response = client.get("/government/alerts")
    assert response.status_code == 200
    assert b"ALERT-IN-00001" in response.data


def test_alerts_list_no_data(client, monkeypatch):
    monkeypatch.setattr(routes_module, "get_summary", lambda branch: None)
    response = client.get("/government/alerts")
    assert response.status_code == 200
    assert b"No data available" in response.data


def test_alert_detail_page_found(client, monkeypatch):
    monkeypatch.setattr(routes_module, "get_alert_by_id", lambda aid: SAMPLE_ALERT if aid == "ALERT-IN-00001" else None)
    response = client.get("/government/alerts/ALERT-IN-00001")
    assert response.status_code == 200
    assert b"Dakshina Kannada" in response.data
    assert b"Evidence not yet generated" in response.data  # honest state, not faked


def test_alert_detail_page_not_found(client, monkeypatch):
    monkeypatch.setattr(routes_module, "get_alert_by_id", lambda aid: None)
    response = client.get("/government/alerts/NONEXISTENT")
    assert response.status_code == 404


def test_analytics_page(client, monkeypatch):
    # analytics() now queries get_summary + get_analytics_data directly
    # (SQL GROUP BY), not load_dashboard_data - mock those instead.
    monkeypatch.setattr(routes_module, "get_summary", lambda branch: SAMPLE_META)
    monkeypatch.setattr(
        routes_module, "get_analytics_data",
        lambda: ({"mild": 0, "moderate": 1, "severe": 0}, [("Dakshina Kannada", 1)]),
    )
    response = client.get("/government/analytics")
    assert response.status_code == 200
    assert b"Dakshina Kannada" in response.data


def test_analytics_no_data(client, monkeypatch):
    monkeypatch.setattr(routes_module, "get_summary", lambda branch: None)
    response = client.get("/government/analytics")
    assert response.status_code == 200
    assert b"No data available" in response.data


def test_blockchain_page_no_ledger(client, monkeypatch, tmp_path):
    fake_ledger = str(tmp_path / "nonexistent_ledger.jsonl")
    monkeypatch.setattr(routes_module, "LEDGER_PATH", fake_ledger)
    response = client.get("/government/blockchain")
    assert response.status_code == 200
    assert b"No blockchain ledger found" in response.data


def test_evidence_file_path_traversal_blocked(client):
    response = client.get("/government/evidence/ALERT-IN-00001/../../../etc/passwd")
    assert response.status_code in (403, 404)
