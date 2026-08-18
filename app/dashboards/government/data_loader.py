"""
Data loader for the Government Dashboard (Module 10).

Backed by SQLite (app/database/) rather than re-reading JSON/GeoJSON files
on every request. Function names/signatures are unchanged from the
original JSON-based version, so routes.py mostly didn't need to change.
"""

from app.database.queries import (
    get_alerts,
    get_alerts_page,
    get_alert_with_evidence_and_blockchain,
    get_summary,
    get_severity_counts,
    get_region_counts,
)


def load_dashboard_data():
    """Returns (alerts, meta). alerts is the full inside-forest list
    (needed for the map, which must plot every geometry). Returns
    (None, None) if the pipeline hasn't been run/synced yet."""
    meta = get_summary("inside_forest")
    if meta is None:
        return None, None
    alerts = get_alerts("inside_forest")
    return alerts, meta


def get_alert_by_id(alert_id):
    return get_alert_with_evidence_and_blockchain(alert_id)


def get_alerts_page_data(page, per_page):
    """True paginated fetch - only queries the rows needed for this page."""
    return get_alerts_page("inside_forest", page, per_page)


def get_analytics_data():
    """Severity/region breakdowns computed via SQL GROUP BY, not by
    loading every alert into Python and counting."""
    severity_counts = get_severity_counts("inside_forest")
    top_regions = get_region_counts("inside_forest", top_n=10)
    return severity_counts, top_regions
