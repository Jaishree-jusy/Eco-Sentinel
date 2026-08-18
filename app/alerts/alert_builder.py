"""
Alert record construction - Module 7 (Inside Forest) and Module 7A (Outside Forest).

Field sets match the architecture diagram exactly:
  Box 7:  Alert ID, Date & Time, Location (Lat/Long), Area Lost (ha), Severity Level, Region/Division
  Box 7A: Alert ID, Date & Time, Location (Lat/Long), Area Lost (ha), Region/Area Type
"""

import pandas as pd
from datetime import datetime, timezone
from app.alerts.config import ALERT_ID_PREFIX_INSIDE, ALERT_ID_PREFIX_OUTSIDE
from app.common.content_id import stable_id
from app.boundary_check.legality import derive_final_alert_category, LEGAL_STATUS_UNKNOWN


def _safe_get(row, key, default=None):
    """row can be a dict or a pandas Series - handles both, and columns
    that may not exist yet if an upstream optional stage (AI/legality)
    hasn't been run, or exist but hold NaN (geopandas' representation of
    a missing value for that row)."""
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass  # value isn't NaN-checkable (e.g. a string) - that's fine, keep it
    return value


def build_inside_forest_alert(row, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    polygon_id = row["polygon_id"]

    detection_class = _safe_get(row, "detection_class", "vegetation_loss")
    legality_status = _safe_get(row, "legality_status", LEGAL_STATUS_UNKNOWN)
    final_category = derive_final_alert_category(detection_class, legality_status)

    return {
        # Derived from polygon_id + branch, not row position: the same
        # loss polygon always gets the same alert_id, on any rerun.
        "alert_id": stable_id(polygon_id, "inside_forest", prefix=f"{ALERT_ID_PREFIX_INSIDE}-"),
        "date_time": generated_at,
        "location": {
            "latitude": float(row["centroid_lat"]),
            "longitude": float(row["centroid_lon"]),
        },
        "area_lost_ha": float(row["area_ha"]),
        "severity_level": row["severity_level"],
        "region_division": row["region_division"],
        "polygon_id": polygon_id,
        "ai_disturbance_score": _safe_get(row, "mean_anomaly_score", None),
        "detection_class": detection_class,
        "legality_status": legality_status,
        "matched_authorization_id": _safe_get(row, "matched_authorization_id", None),
        "final_category": final_category,
    }


def build_outside_forest_alert(row, area_type, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    polygon_id = row["polygon_id"]
    return {
        "alert_id": stable_id(polygon_id, "outside_forest", prefix=f"{ALERT_ID_PREFIX_OUTSIDE}-"),
        "date_time": generated_at,
        "location": {
            "latitude": float(row["centroid_lat"]),
            "longitude": float(row["centroid_lon"]),
        },
        "area_lost_ha": float(row["area_ha"]),
        "region_area_type": area_type,
        "polygon_id": polygon_id,
    }
