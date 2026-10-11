
"""
Alert record construction - Module 7 (Inside Forest) and Module 7A
(Outside Forest).
"""

import pandas as pd
from datetime import datetime, timezone

from app.alerts.config import (
    ALERT_ID_PREFIX_INSIDE,
    ALERT_ID_PREFIX_OUTSIDE,
)
from app.common.content_id import stable_id
from app.boundary_check.legality import (
    derive_final_alert_category,
    LEGAL_STATUS_UNKNOWN,
)


def _safe_get(row, key, default=None):
    """Safely read a value from a pandas Series or dictionary."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default

    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass

    return value


def build_inside_forest_alert(row, generated_at=None):
    """Build an alert for a polygon classified inside the forest context."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    polygon_id = row["polygon_id"]

    ml_confidence = _safe_get(row, "mean_ml_probability", None)
    detection_class = _safe_get(
        row, "detection_class", "vegetation_loss"
    )
    legality_status = _safe_get(
        row, "legality_status", LEGAL_STATUS_UNKNOWN
    )

    return {
        "alert_id": stable_id(
            polygon_id,
            "inside_forest",
            prefix=f"{ALERT_ID_PREFIX_INSIDE}-",
        ),
        "date_time": generated_at,
        "location": {
            "latitude": float(row["centroid_lat"]),
            "longitude": float(row["centroid_lon"]),
        },
        "area_lost_ha": float(row["area_ha"]),
        "severity_level": _safe_get(row, "severity_level", "unknown"),
        "region_division": _safe_get(row, "region_division", None),
        "polygon_id": polygon_id,
        "ai_disturbance_score": (
            float(_safe_get(row, "mean_anomaly_score", ml_confidence))
            if _safe_get(row, "mean_anomaly_score", ml_confidence) is not None
            else None
        ),
        "ml_confidence": (
            float(ml_confidence)
            if ml_confidence is not None
            else None
        ),
        "detection_class": detection_class,
        "legality_status": legality_status,
        "matched_authorization_id": _safe_get(
            row, "matched_authorization_id", None
        ),
        "final_category": derive_final_alert_category(
            detection_class, legality_status
        ),
    }


def build_outside_forest_alert(row, area_type, generated_at=None):
    """Build an outside-forest alert with explicit legality status."""
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    polygon_id = row["polygon_id"]

    ml_confidence = _safe_get(row, "mean_ml_probability", None)
    detection_class = _safe_get(
        row, "detection_class", "vegetation_loss"
    )
    legality_status = _safe_get(
        row, "legality_status", LEGAL_STATUS_UNKNOWN
    )

    return {
        "alert_id": stable_id(
            polygon_id,
            "outside_forest",
            prefix=f"{ALERT_ID_PREFIX_OUTSIDE}-",
        ),
        "date_time": generated_at,
        "location": {
            "latitude": float(row["centroid_lat"]),
            "longitude": float(row["centroid_lon"]),
        },
        "area_lost_ha": float(row["area_ha"]),
        "region_area_type": area_type,
        "polygon_id": polygon_id,
        "ml_confidence": (
            float(ml_confidence)
            if ml_confidence is not None
            else None
        ),
        "detection_class": detection_class,
        "legality_status": legality_status,
        "matched_authorization_id": _safe_get(
            row, "matched_authorization_id", None
        ),
        "final_category": derive_final_alert_category(
            detection_class, legality_status
        ),
    }