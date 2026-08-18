"""
Query functions backing both dashboards. Replaces the previous pattern of
re-reading and re-parsing entire JSON/GeoJSON files on every request.
"""

import json
from app.database.schema import get_connection


def _row_to_alert_dict(row):
    d = dict(row)
    d["location"] = {"latitude": d.pop("latitude"), "longitude": d.pop("longitude")}
    geom = d.pop("geometry_geojson")
    d["geometry"] = json.loads(geom) if geom else None
    return d


def get_alerts(branch, db_path=None):
    """Full list for a branch - used by the map (which needs every
    geometry to plot) and small enough datasets."""
    conn = get_connection(db_path)
    rows = conn.execute(
    """
    SELECT
        a.*,
        CASE
            WHEN e.alert_id IS NOT NULL THEN 1
            ELSE 0
        END AS evidence_available
    FROM alerts a
    LEFT JOIN evidence e
        ON e.alert_id = a.alert_id
    WHERE a.branch = ?
    ORDER BY a.alert_id
    """,
    (branch,),
).fetchall()
    conn.close()
    return [_row_to_alert_dict(r) for r in rows]


def get_alerts_page(branch, page, per_page, db_path=None):
    """Fetch paginated alerts with evidence availability."""
    conn = get_connection(db_path)

    total = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE branch = ?",
        (branch,),
    ).fetchone()[0]

    offset = (page - 1) * per_page

    rows = conn.execute(
        """
        SELECT
            a.*,
            CASE
                WHEN e.alert_id IS NOT NULL THEN 1
                ELSE 0
            END AS evidence_available
        FROM alerts a
        LEFT JOIN evidence e
            ON e.alert_id = a.alert_id
        WHERE a.branch = ?
        ORDER BY a.alert_id
        LIMIT ? OFFSET ?
        """,
        (branch, per_page, offset),
    ).fetchall()

    conn.close()

    return [_row_to_alert_dict(r) for r in rows], total


def get_alert_with_evidence_and_blockchain(alert_id, db_path=None):
    """O(1) indexed lookup by primary key, instead of loading every alert
    and scanning for a match."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)).fetchone()
    if row is None:
        conn.close()
        return None
    alert = _row_to_alert_dict(row)

    ev_row = conn.execute("SELECT * FROM evidence WHERE alert_id = ?", (alert_id,)).fetchone()
    alert["evidence_available"] = ev_row is not None
    alert["evidence"] = dict(ev_row) if ev_row else None

    bc_row = conn.execute("SELECT * FROM blockchain_blocks WHERE alert_id = ?", (alert_id,)).fetchone()
    alert["blockchain_available"] = bc_row is not None
    alert["blockchain"] = dict(bc_row) if bc_row else None

    conn.close()
    return alert


def get_summary(branch, db_path=None):
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(area_lost_ha), 0) as total_ha, "
        "MIN(base_year) as base_year, MIN(comparison_year) as comparison_year "
        "FROM alerts WHERE branch = ?",
        (branch,),
    ).fetchone()
    evidence_count = conn.execute(
        "SELECT COUNT(*) FROM evidence e JOIN alerts a ON e.alert_id = a.alert_id WHERE a.branch = ?",
        (branch,),
    ).fetchone()[0]
    conn.close()

    if row["cnt"] == 0:
        return None

    return {
        "total_alerts": row["cnt"],
        "total_area_ha": round(row["total_ha"], 4),
        "base_year": row["base_year"],
        "comparison_year": row["comparison_year"],
        "evidence_generated_count": evidence_count,
    }


def get_severity_counts(branch="inside_forest", db_path=None):
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT severity_level, COUNT(*) as cnt FROM alerts WHERE branch = ? GROUP BY severity_level",
        (branch,),
    ).fetchall()
    conn.close()
    return {r["severity_level"]: r["cnt"] for r in rows}


def get_region_counts(branch="inside_forest", top_n=10, db_path=None):
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT region_division, COUNT(*) as cnt FROM alerts WHERE branch = ? "
        "GROUP BY region_division ORDER BY cnt DESC LIMIT ?",
        (branch, top_n),
    ).fetchall()
    conn.close()
    return [(r["region_division"], r["cnt"]) for r in rows]


def get_area_type_counts_and_ha(branch="outside_forest", db_path=None):
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT region_area_type, COUNT(*) as cnt, COALESCE(SUM(area_lost_ha), 0) as total_ha "
        "FROM alerts WHERE branch = ? GROUP BY region_area_type",
        (branch,),
    ).fetchall()
    conn.close()
    counts = {r["region_area_type"]: r["cnt"] for r in rows}
    ha = {r["region_area_type"]: round(r["total_ha"], 4) for r in rows}
    return counts, ha


def get_top_by_area(branch, limit=15, db_path=None):
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM alerts WHERE branch = ? ORDER BY area_lost_ha DESC LIMIT ?",
        (branch, limit),
    ).fetchall()
    conn.close()
    return [_row_to_alert_dict(r) for r in rows]
