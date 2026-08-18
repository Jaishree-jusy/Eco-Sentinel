"""
Module 6B - Legality / Authorization Check.

CRITICAL SAFEGUARD: no authorization dataset exists in this project right
now, and none is fabricated here. When AUTHORIZATION_DATASET_PATH is None
(the default) or the configured file doesn't exist, every single polygon
gets "legal_status_unknown" - deliberately, not as a fallback bug. This
is the only honest answer the system can give without real permit/legal
records, and "unknown" must never be treated as evidence of illegality.
"""

import os
import geopandas as gpd

LEGAL_STATUS_AUTHORIZED = "authorized_forest_change"
LEGAL_STATUS_NO_AUTHORIZATION_FOUND = "no_authorization_found"
LEGAL_STATUS_UNKNOWN = "legal_status_unknown"
LEGAL_STATUS_POTENTIAL_ILLEGAL = "potential_illegal_deforestation"

REQUIRED_AUTHORIZATION_COLUMNS = [
    "authorization_id", "holder_name", "authorization_type", "issuing_authority",
    "issue_date", "valid_from", "valid_until", "max_authorized_area_ha",
    "status", "document_reference",
]

DEFAULT_OVERLAP_THRESHOLD = 0.70  # fraction of detected polygon area that must be covered


def load_authorization_dataset(path):
    """Returns a GeoDataFrame, or None if no real dataset is configured.
    Never generates or fabricates authorization records - only reads a
    real file if one has been explicitly supplied."""
    if not path or not os.path.exists(path):
        return None

    gdf = gpd.read_file(path)
    missing_cols = [c for c in REQUIRED_AUTHORIZATION_COLUMNS if c not in gdf.columns]
    if missing_cols:
        raise ValueError(
            f"Authorization dataset at {path} is missing required columns: {missing_cols}"
        )
    return gdf


def check_legality(geometry, detection_date, authorization_gdf, overlap_threshold=DEFAULT_OVERLAP_THRESHOLD):
    """Returns {"legality_status": ..., "matched_authorization_id": ...}.

    detection_date: a comparable date/string for temporal matching (e.g.
    the comparison_year's acquisition date).
    """
    if authorization_gdf is None or authorization_gdf.empty:
        # No dataset at all, or an empty one - genuinely no information
        # available. This is the expected, honest state right now.
        return {"legality_status": LEGAL_STATUS_UNKNOWN, "matched_authorization_id": None}

    detected_area = geometry.area
    if detected_area == 0:
        return {"legality_status": LEGAL_STATUS_UNKNOWN, "matched_authorization_id": None}

    any_spatial_coverage = False
    best_match = None

    for _, row in authorization_gdf.iterrows():
        if not row.geometry.intersects(geometry):
            continue

        any_spatial_coverage = True
        overlap_area = row.geometry.intersection(geometry).area
        overlap_fraction = overlap_area / detected_area

        temporally_valid = _date_in_range(detection_date, row["valid_from"], row["valid_until"])
        is_active = str(row["status"]).lower() == "active"

        if overlap_fraction >= overlap_threshold and temporally_valid and is_active:
            best_match = row["authorization_id"]
            break

    if best_match is not None:
        return {"legality_status": LEGAL_STATUS_AUTHORIZED, "matched_authorization_id": best_match}

    if any_spatial_coverage:
        # The dataset has records for this area, none of them cover this
        # specific event - a real negative result, not a data gap.
        return {"legality_status": LEGAL_STATUS_NO_AUTHORIZATION_FOUND, "matched_authorization_id": None}

    # The dataset exists, but has zero coverage here - a gap in records,
    # not evidence of anything.
    return {"legality_status": LEGAL_STATUS_UNKNOWN, "matched_authorization_id": None}


def _date_in_range(check_date, valid_from, valid_until):
    try:
        return str(valid_from) <= str(check_date) <= str(valid_until)
    except TypeError:
        return False


def derive_final_alert_category(detection_class, legality_status):
    """The safeguard rule explicitly required: 'potential illegal
    deforestation' is assigned ONLY from a genuine loss/disturbance
    detection combined with a confirmed 'no_authorization_found' result -
    NEVER from 'unknown'. Absence of legal information is never treated
    as suspicion of illegality."""
    has_detection = detection_class in ("vegetation_loss", "high_confidence_loss", "potential_disturbance")

    if has_detection and legality_status == LEGAL_STATUS_NO_AUTHORIZATION_FOUND:
        return LEGAL_STATUS_POTENTIAL_ILLEGAL
    return legality_status
