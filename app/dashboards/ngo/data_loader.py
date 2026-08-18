"""
Data loader for the NGO Dashboard (Module 7B).

Backed by SQLite (app/database/) rather than re-reading JSON/GeoJSON files
on every request. No evidence or blockchain lookups here - per the
architecture, those are explicitly Inside-Forest-only.
"""

from app.database.queries import (
    get_alerts,
    get_alerts_page,
    get_alert_with_evidence_and_blockchain,
    get_summary,
    get_area_type_counts_and_ha,
    get_top_by_area,
)


def load_ngo_dashboard_data():
    """Returns (alerts, meta). Returns (None, None) if the pipeline hasn't
    been run/synced yet."""
    meta = get_summary("outside_forest")
    if meta is None:
        return None, None
    alerts = get_alerts("outside_forest")
    return alerts, meta


def get_ngo_alert_by_id(alert_id):
    alert = get_alert_with_evidence_and_blockchain(alert_id)
    # NGO alerts have no evidence/blockchain by design - strip those keys
    # so the NGO template (which doesn't expect them) stays unaffected.
    if alert is not None:
        alert.pop("evidence_available", None)
        alert.pop("evidence", None)
        alert.pop("blockchain_available", None)
        alert.pop("blockchain", None)
    return alert


def get_ngo_alerts_page_data(page, per_page):
    return get_alerts_page("outside_forest", page, per_page)


def get_ngo_trends_data():
    """Area-type breakdown via SQL GROUP BY instead of a Python Counter
    over the full loaded list."""
    return get_area_type_counts_and_ha("outside_forest")


def get_ngo_top_by_area(limit=15):
    return get_top_by_area("outside_forest", limit=limit)
