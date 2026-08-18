"""
SQLite schema for ECO-SENTINEL's persistent system database.

This is the "Data Stores (System Database)" component of the architecture,
which was previously entirely flat JSON/GeoJSON files. Those files remain
the source of truth written by each module's pipeline (kept for
interoperability, debugging, and re-syncing) - this database is a fast,
indexed, queryable copy built FROM them, used for dashboard queries.

Column names for the blockchain_blocks table deliberately match the raw
block dict keys used in ledger.jsonl (e.g. "timestamp", not
"block_timestamp") so the same dicts can be handed to templates that
already expect that shape.
"""

import os
import sqlite3

from app.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    polygon_id TEXT NOT NULL,
    branch TEXT NOT NULL CHECK(branch IN ('inside_forest', 'outside_forest')),
    base_year INTEGER NOT NULL,
    comparison_year INTEGER NOT NULL,
    date_time TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    area_lost_ha REAL NOT NULL,
    severity_level TEXT,       -- inside-forest only
    region_division TEXT,      -- inside-forest only
    region_area_type TEXT,     -- outside-forest only
    geometry_geojson TEXT,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_branch ON alerts(branch);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity_level);
CREATE INDEX IF NOT EXISTS idx_alerts_region ON alerts(region_division);
CREATE INDEX IF NOT EXISTS idx_alerts_area_type ON alerts(region_area_type);

CREATE TABLE IF NOT EXISTS evidence (
    alert_id TEXT PRIMARY KEY REFERENCES alerts(alert_id),
    evidence_dir TEXT NOT NULL,
    map_snapshot TEXT NOT NULL,
    geojson TEXT NOT NULL,
    pdf_report TEXT NOT NULL,
    metadata TEXT NOT NULL,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blockchain_blocks (
    block_index INTEGER PRIMARY KEY,
    alert_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    previous_block_hash TEXT NOT NULL,
    block_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blocks_alert ON blockchain_blocks(alert_id);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    pipeline_run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger_mode TEXT NOT NULL,       -- 'manual' or 'scheduled'
    overall_status TEXT NOT NULL,     -- 'running' / 'success' / 'failed' / 'no_new_data'
    failed_stage TEXT,
    error_message TEXT,
    acquisition_run_id TEXT,
    gee_processing_run_id TEXT,
    loss_detection_run_id TEXT,
    ai_disturbance_run_id TEXT,
    polygon_analysis_run_id TEXT,
    boundary_check_run_id TEXT,
    legality_check_run_id TEXT,
    alert_generation_run_id TEXT,
    evidence_generation_run_id TEXT,
    blockchain_run_id TEXT
);

CREATE TABLE IF NOT EXISTS gee_acquisitions (
    gee_image_id TEXT PRIMARY KEY,
    local_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    cloud_cover_pct REAL,
    synced_at TEXT NOT NULL
);
"""

# New nullable columns added to the existing `alerts` table for the
# AI/legality layers. Additive only - existing rows keep all their
# existing values; new columns are simply NULL until re-synced.
_NEW_ALERT_COLUMNS = [
    ("ai_disturbance_score", "REAL"),
    ("detection_class", "TEXT"),
    ("legality_status", "TEXT"),
    ("matched_authorization_id", "TEXT"),
]


def _apply_alert_column_migrations(conn):
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(alerts)").fetchall()}
    for column_name, column_type in _NEW_ALERT_COLUMNS:
        if column_name not in existing_columns:
            conn.execute(f"ALTER TABLE alerts ADD COLUMN {column_name} {column_type}")


def get_connection(db_path=None):
    db_path = db_path or DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Idempotent - CREATE TABLE IF NOT EXISTS is a cheap no-op once the
    # schema already exists. Guarantees every query sees existing tables,
    # even on a totally fresh database (e.g. the dashboard is started
    # before `python -m app.database.cli sync` has ever been run) -
    # without this, queries would crash with "no such table" instead of
    # gracefully returning "no data yet".
    conn.executescript(SCHEMA)
    _apply_alert_column_migrations(conn)
    return conn


def init_db(db_path=None):
    conn = get_connection(db_path)
    conn.commit()
    conn.close()
