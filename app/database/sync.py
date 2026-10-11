"""
Database sync - loads Module 6/7/8/9 outputs into SQLite.

The JSON/GeoJSON files those modules write remain the actual source of
truth (kept for interoperability and debugging). This sync reads them
and populates the SQLite tables that dashboards query.

Uses INSERT OR REPLACE throughout, so running this multiple times only
adds/updates rows and does not create duplicate alert/evidence/blockchain
records.
"""

import os
import json
import glob
from datetime import datetime, timezone

import geopandas as gpd
from shapely.geometry import mapping

from app.config import POLYGON_ANALYSIS_DIR, ALERTS_DIR, EVIDENCE_STORE_DIR
from app.boundary_check.config import BOUNDARY_CHECK_DIR
from app.blockchain.config import LEDGER_PATH
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.database.schema import get_connection, init_db


def _find_latest(directory, prefix, timestamp_key):
    pattern = os.path.join(directory, f"{prefix}_*.json")
    candidates = []

    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                data = json.load(f)

            candidates.append((data[timestamp_key], path, data))

        except (json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[-1][2]


def _resolve_data_path(path, directory):
    """Resolve manifest paths across Windows and Linux deployments.

    Manifests may contain absolute paths from the machine that generated
    them. If that path does not exist here, try the filename in the expected
    data directory. Return None if neither path exists.
    """
    if not path:
        return None

    if os.path.exists(path):
        return path

    candidate = os.path.join(directory, os.path.basename(path))
    if os.path.exists(candidate):
        return candidate

    return None


def _load_geometry_lookup(boundary_manifest):
    """polygon_id -> GeoJSON geometry string, from both branches'
    boundary-check output (source of truth for shapes)."""

    lookup = {}

    for key in ("inside_forest", "outside_forest"):
        path = _resolve_data_path(
            boundary_manifest[key]["path"],
            BOUNDARY_CHECK_DIR,
        )

        if not path:
            continue

        gdf = gpd.read_file(path)

        for _, row in gdf.iterrows():
            lookup[row["polygon_id"]] = json.dumps(mapping(row.geometry))

    return lookup


def sync_database(db_path=None):
    init_db(db_path)

    conn = get_connection(db_path)
    cur = conn.cursor()

    synced_at = datetime.now(timezone.utc).isoformat()

    stats = {
        "alerts_synced": 0,
        "evidence_synced": 0,
        "blocks_synced": 0,
    }

    # ------------------------------------------------------------------
    # Module 6 + Module 7 -> alerts
    # ------------------------------------------------------------------

    boundary_manifest = _find_latest(
        BOUNDARY_CHECK_DIR,
        "boundary_check",
        "checked_at",
    )

    alert_manifest = _find_latest(
        ALERTS_DIR,
        "alert_generation",
        "generated_at",
    )

    if boundary_manifest and alert_manifest:

        base_year = boundary_manifest["base_year"]
        comparison_year = boundary_manifest["comparison_year"]

        geometry_lookup = _load_geometry_lookup(boundary_manifest)

        # --------------------------------------------------------------
        # Inside-forest alerts
        # --------------------------------------------------------------

        inside_path = _resolve_data_path(
            alert_manifest["inside_forest_alerts"]["path"],
            ALERTS_DIR,
        )

        if inside_path:

            with open(inside_path) as f:
                inside_alerts = json.load(f)

            for a in inside_alerts:

                cur.execute(
                    """
                    INSERT OR REPLACE INTO alerts
                    (
                        alert_id,
                        polygon_id,
                        branch,
                        base_year,
                        comparison_year,
                        date_time,
                        latitude,
                        longitude,
                        area_lost_ha,
                        severity_level,
                        region_division,
                        region_area_type,
                        geometry_geojson,
                        synced_at,

                        -- Legacy detection field
                        ai_disturbance_score,

                        -- Current Random Forest detection fields
                        detection_class,
                        ml_confidence,

                        -- Legality / final classification
                        legality_status,
                        matched_authorization_id,
                        final_category
                    )
                    VALUES
                    (
                        ?,
                        ?,
                        'inside_forest',
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        NULL,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        a["alert_id"],
                        a["polygon_id"],
                        base_year,
                        comparison_year,
                        a["date_time"],
                        a["location"]["latitude"],
                        a["location"]["longitude"],
                        a["area_lost_ha"],
                        a["severity_level"],
                        a["region_division"],
                        geometry_lookup.get(a["polygon_id"]),
                        synced_at,

                        # Legacy field retained for historical
                        # compatibility.
                        a.get("ai_disturbance_score"),

                        # Current RF fields.
                        a.get("detection_class"),
                        a.get("ml_confidence"),

                        # Legality fields.
                        a.get("legality_status"),
                        a.get("matched_authorization_id"),
                        a.get("final_category"),
                    ),
                )

                stats["alerts_synced"] += 1

        # --------------------------------------------------------------
        # Outside-forest alerts
        # --------------------------------------------------------------

        outside_path = _resolve_data_path(
            alert_manifest["outside_forest_alerts"]["path"],
            ALERTS_DIR,
        )

        if outside_path:

            with open(outside_path) as f:
                outside_alerts = json.load(f)

            for a in outside_alerts:

                cur.execute(
                    """
                    INSERT OR REPLACE INTO alerts
                    (
                        alert_id,
                        polygon_id,
                        branch,
                        base_year,
                        comparison_year,
                        date_time,
                        latitude,
                        longitude,
                        area_lost_ha,
                        severity_level,
                        region_division,
                        region_area_type,
                        geometry_geojson,
                        synced_at
                    )
                    VALUES
                    (
                        ?,
                        ?,
                        'outside_forest',
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        NULL,
                        NULL,
                        ?,
                        ?,
                        ?
                    )
                    """,
                    (
                        a["alert_id"],
                        a["polygon_id"],
                        base_year,
                        comparison_year,
                        a["date_time"],
                        a["location"]["latitude"],
                        a["location"]["longitude"],
                        a["area_lost_ha"],
                        a["region_area_type"],
                        geometry_lookup.get(a["polygon_id"]),
                        synced_at,
                    ),
                )

                stats["alerts_synced"] += 1

    # ------------------------------------------------------------------
    # Module 8 -> evidence
    # ------------------------------------------------------------------

    evidence_manifest = _find_latest(
        EVIDENCE_STORE_DIR,
        "evidence_generation",
        "generated_at",
    )

    if evidence_manifest:

        for r in evidence_manifest.get("evidence_records", []):

            cur.execute(
                """
                INSERT OR REPLACE INTO evidence
                (
                    alert_id,
                    evidence_dir,
                    map_snapshot,
                    geojson,
                    pdf_report,
                    metadata,
                    synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["alert_id"],
                    r["evidence_dir"],
                    r["map_snapshot"],
                    r["geojson"],
                    r["pdf_report"],
                    r["metadata"],
                    synced_at,
                ),
            )

            stats["evidence_synced"] += 1

    # ------------------------------------------------------------------
    # Module 9 -> blockchain blocks
    # ------------------------------------------------------------------

    if os.path.exists(LEDGER_PATH):

        with open(LEDGER_PATH) as f:

            for line in f:

                line = line.strip()

                if not line:
                    continue

                block = json.loads(line)

                cur.execute(
                    """
                    INSERT OR REPLACE INTO blockchain_blocks
                    (
                        block_index,
                        alert_id,
                        content_hash,
                        previous_block_hash,
                        block_hash,
                        timestamp,
                        synced_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        block["block_index"],
                        block["alert_id"],
                        block["content_hash"],
                        block["previous_block_hash"],
                        block["block_hash"],
                        block["timestamp"],
                        synced_at,
                    ),
                )

                stats["blocks_synced"] += 1

    # ------------------------------------------------------------------
    # GEE acquisition registry
    # ------------------------------------------------------------------

    gee_registry_path = os.path.join(
        ACQUISITION_RUNS_DIR,
        "gee_image_registry.json",
    )

    if os.path.exists(gee_registry_path):

        with open(gee_registry_path) as f:
            gee_registry = json.load(f)

        for gee_image_id, entry in gee_registry.items():

            cur.execute(
                """
                INSERT OR REPLACE INTO gee_acquisitions
                (
                    gee_image_id,
                    local_path,
                    sha256,
                    acquired_at,
                    cloud_cover_pct,
                    synced_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    gee_image_id,
                    entry["local_path"],
                    entry["sha256"],
                    entry["acquired_at"],
                    entry.get("cloud_cover_pct"),
                    synced_at,
                ),
            )

            stats["gee_acquisitions_synced"] = (
                stats.get("gee_acquisitions_synced", 0) + 1
            )

    # ------------------------------------------------------------------
    # Commit everything
    # ------------------------------------------------------------------

    conn.commit()
    conn.close()

    return stats
