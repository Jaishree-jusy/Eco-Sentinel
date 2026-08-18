"""
Tests for app.database - schema, sync, and queries.

Builds small synthetic JSON/GeoJSON files matching the real pipeline's
output shapes, syncs them into a temp SQLite database, and verifies the
query functions return correct results.
"""

import os
import json
import pytest

from app.database.schema import init_db, get_connection
from app.database.sync import sync_database
import app.database.sync as sync_module
from app.database.queries import (
    get_alerts, get_alerts_page, get_alert_with_evidence_and_blockchain,
    get_summary, get_severity_counts, get_region_counts,
    get_area_type_counts_and_ha, get_top_by_area,
)


@pytest.fixture
def synced_db(tmp_path, monkeypatch):
    """Builds a full synthetic pipeline output tree (boundary_check,
    alerts, evidence, blockchain ledger) and syncs it into a temp DB."""
    boundary_dir = tmp_path / "boundary_check"
    alerts_dir = tmp_path / "alerts"
    evidence_dir = tmp_path / "evidence_store"
    for d in (boundary_dir, alerts_dir, evidence_dir):
        d.mkdir()

    inside_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [74.9, 12.85]},
            "properties": {"polygon_id": "LOSS-in1", "area_ha": 2.5, "severity_level": "moderate"},
        }],
    }
    outside_geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [74.85, 12.90]},
            "properties": {"polygon_id": "LOSS-out1", "area_ha": 1.2},
        }],
    }
    (boundary_dir / "inside.geojson").write_text(json.dumps(inside_geojson))
    (boundary_dir / "outside.geojson").write_text(json.dumps(outside_geojson))

    boundary_manifest = {
        "checked_at": "2026-08-06T00:00:00",
        "base_year": 2023, "comparison_year": 2025,
        "inside_forest": {"path": str(boundary_dir / "inside.geojson")},
        "outside_forest": {"path": str(boundary_dir / "outside.geojson")},
    }
    (boundary_dir / "boundary_check_1.json").write_text(json.dumps(boundary_manifest))

    inside_alerts = [{
        "alert_id": "ALERT-IN-aaa111", "polygon_id": "LOSS-in1",
        "date_time": "2026-08-06T00:00:00",
        "location": {"latitude": 12.85, "longitude": 74.9},
        "area_lost_ha": 2.5, "severity_level": "moderate", "region_division": "TestDistrict",
    }]
    outside_alerts = [{
        "alert_id": "ALERT-OUT-bbb222", "polygon_id": "LOSS-out1",
        "date_time": "2026-08-06T00:00:00",
        "location": {"latitude": 12.90, "longitude": 74.85},
        "area_lost_ha": 1.2, "region_area_type": "Urban",
    }]
    (alerts_dir / "inside_alerts.json").write_text(json.dumps(inside_alerts))
    (alerts_dir / "outside_alerts.json").write_text(json.dumps(outside_alerts))

    alert_manifest = {
        "generated_at": "2026-08-06T00:01:00",
        "inside_forest_alerts": {"path": str(alerts_dir / "inside_alerts.json")},
        "outside_forest_alerts": {"path": str(alerts_dir / "outside_alerts.json")},
    }
    (alerts_dir / "alert_generation_1.json").write_text(json.dumps(alert_manifest))

    evidence_manifest = {
        "generated_at": "2026-08-06T00:02:00",
        "evidence_records": [{
            "alert_id": "ALERT-IN-aaa111", "evidence_dir": str(evidence_dir / "ALERT-IN-aaa111"),
            "map_snapshot": "map.png", "geojson": "poly.geojson",
            "pdf_report": "report.pdf", "metadata": "meta.json",
        }],
    }
    (evidence_dir / "evidence_generation_1.json").write_text(json.dumps(evidence_manifest))

    ledger_path = tmp_path / "ledger.jsonl"
    block = {
        "block_index": 0, "alert_id": "ALERT-IN-aaa111",
        "content_hash": "abc", "previous_block_hash": "0" * 64,
        "block_hash": "def", "timestamp": "2026-08-06T00:03:00",
    }
    ledger_path.write_text(json.dumps(block) + "\n")

    monkeypatch.setattr(sync_module, "BOUNDARY_CHECK_DIR", str(boundary_dir))
    monkeypatch.setattr(sync_module, "ALERTS_DIR", str(alerts_dir))
    monkeypatch.setattr(sync_module, "EVIDENCE_STORE_DIR", str(evidence_dir))
    monkeypatch.setattr(sync_module, "LEDGER_PATH", str(ledger_path))

    db_path = str(tmp_path / "test.db")
    stats = sync_database(db_path=db_path)
    return db_path, stats


def test_sync_produces_expected_counts(synced_db):
    db_path, stats = synced_db
    assert stats["alerts_synced"] == 2
    assert stats["evidence_synced"] == 1
    assert stats["blocks_synced"] == 1


def test_get_alerts_by_branch(synced_db):
    db_path, _ = synced_db
    inside = get_alerts("inside_forest", db_path=db_path)
    outside = get_alerts("outside_forest", db_path=db_path)
    assert len(inside) == 1
    assert len(outside) == 1
    assert inside[0]["alert_id"] == "ALERT-IN-aaa111"
    assert inside[0]["geometry"]["type"] == "Point"  # geometry correctly joined in


def test_get_alerts_page_pagination(synced_db):
    db_path, _ = synced_db
    page1, total = get_alerts_page("inside_forest", page=1, per_page=100, db_path=db_path)
    assert total == 1
    assert len(page1) == 1


def test_get_alert_with_evidence_and_blockchain(synced_db):
    db_path, _ = synced_db
    alert = get_alert_with_evidence_and_blockchain("ALERT-IN-aaa111", db_path=db_path)
    assert alert is not None
    assert alert["evidence_available"] is True
    assert alert["blockchain_available"] is True
    assert alert["blockchain"]["timestamp"] == "2026-08-06T00:03:00"  # exact key template expects

    no_evidence_alert = get_alert_with_evidence_and_blockchain("ALERT-OUT-bbb222", db_path=db_path)
    assert no_evidence_alert["evidence_available"] is False
    assert no_evidence_alert["blockchain_available"] is False


def test_get_alert_not_found(synced_db):
    db_path, _ = synced_db
    assert get_alert_with_evidence_and_blockchain("NONEXISTENT", db_path=db_path) is None


def test_get_summary(synced_db):
    db_path, _ = synced_db
    summary = get_summary("inside_forest", db_path=db_path)
    assert summary["total_alerts"] == 1
    assert summary["total_area_ha"] == 2.5
    assert summary["evidence_generated_count"] == 1


def test_get_summary_empty_branch_returns_none(tmp_path):
    db_path = str(tmp_path / "empty.db")
    init_db(db_path)
    assert get_summary("inside_forest", db_path=db_path) is None


def test_get_severity_counts(synced_db):
    db_path, _ = synced_db
    counts = get_severity_counts("inside_forest", db_path=db_path)
    assert counts == {"moderate": 1}


def test_get_region_counts(synced_db):
    db_path, _ = synced_db
    regions = get_region_counts("inside_forest", db_path=db_path)
    assert regions == [("TestDistrict", 1)]


def test_get_area_type_counts_and_ha(synced_db):
    db_path, _ = synced_db
    counts, ha = get_area_type_counts_and_ha("outside_forest", db_path=db_path)
    assert counts == {"Urban": 1}
    assert ha == {"Urban": 1.2}


def test_get_top_by_area(synced_db):
    db_path, _ = synced_db
    top = get_top_by_area("inside_forest", limit=5, db_path=db_path)
    assert len(top) == 1
    assert top[0]["alert_id"] == "ALERT-IN-aaa111"


def test_sync_is_idempotent(synced_db):
    """Running sync twice against the same source data must not duplicate
    rows - INSERT OR REPLACE keyed by primary key."""
    db_path, _ = synced_db
    sync_database(db_path=db_path)  # run again
    conn = get_connection(db_path)
    count = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    conn.close()
    assert count == 2  # still just 2, not 4


def test_schema_migration_preserves_existing_alert_rows(tmp_path):
    """Critical non-destructive test: adding new columns (AI/legality) must
    never lose or corrupt existing alert rows - required since the real
    database already has 5,078 real records before this migration."""
    from app.database.schema import get_connection

    db_path = str(tmp_path / "existing.db")
    conn = get_connection(db_path)
    conn.execute(
        """INSERT INTO alerts (alert_id, polygon_id, branch, base_year, comparison_year,
           date_time, latitude, longitude, area_lost_ha, severity_level, region_division, synced_at)
           VALUES ('ALERT-IN-test', 'LOSS-test', 'inside_forest', 2023, 2025,
           '2026-01-01', 12.8, 74.9, 1.5, 'mild', 'TestDist', '2026-01-01')"""
    )
    conn.commit()
    conn.close()

    # Reconnect - simulates the app restarting after this schema change
    conn2 = get_connection(db_path)
    row = conn2.execute("SELECT * FROM alerts WHERE alert_id = ?", ("ALERT-IN-test",)).fetchone()
    conn2.close()

    assert row is not None
    assert row["area_lost_ha"] == 1.5
    assert row["severity_level"] == "mild"
    # New columns exist and are NULL for pre-existing rows, not an error
    assert row["ai_disturbance_score"] is None
    assert row["detection_class"] is None
    assert row["legality_status"] is None
