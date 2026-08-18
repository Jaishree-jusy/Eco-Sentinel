"""
Module 8 pipeline orchestration.

run_evidence_generation() takes the latest Module 7 alert list (inside
forest only - Module 7A/outside-forest alerts explicitly skip evidence
generation and blockchain per the architecture) and produces, per alert:
a PDF report, JSON metadata, single-feature GeoJSON, and a true-color map
snapshot.
"""

import os
import json
import glob
import uuid
from datetime import datetime, timezone

import geopandas as gpd
import rasterio

from app.config import EVIDENCE_STORE_DIR, ALERTS_DIR
from app.boundary_check.config import BOUNDARY_CHECK_DIR
from app.acquisition.config import ACQUISITION_RUNS_DIR
from app.evidence.map_snapshot import generate_map_snapshot
from app.evidence.geojson_export import export_alert_geojson
from app.evidence.metadata import build_and_write_metadata
from app.evidence.pdf_report import generate_pdf_report


class EvidenceGenerationError(Exception):
    pass


def _find_latest(pattern, timestamp_key):
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


def _find_latest_alert_manifest():
    manifest = _find_latest(os.path.join(ALERTS_DIR, "alert_generation_*.json"), "generated_at")
    if manifest is None:
        raise EvidenceGenerationError(
            "No Module 7 alert-generation manifest found. Run Module 7 "
            "(python -m app.alerts.cli generate) first."
        )
    return manifest


def _find_latest_boundary_check_manifest():
    manifest = _find_latest(os.path.join(BOUNDARY_CHECK_DIR, "boundary_check_*.json"), "checked_at")
    if manifest is None:
        raise EvidenceGenerationError(
            "No Module 6 boundary-check manifest found. Run Module 6 first."
        )
    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"), "triggered_at")
    if manifest is None:
        raise EvidenceGenerationError(
            "No Module 2 acquisition manifest found. Run Module 2 first."
        )
    return manifest


def run_evidence_generation(alert_manifest=None, boundary_manifest=None, acquisition_manifest=None, limit=None):
    if alert_manifest is None:
        alert_manifest = _find_latest_alert_manifest()
    if boundary_manifest is None:
        boundary_manifest = _find_latest_boundary_check_manifest()
    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    inside_alerts_path = alert_manifest["inside_forest_alerts"]["path"]
    inside_geojson_path = boundary_manifest["inside_forest"]["path"]
    comparison_year = boundary_manifest["comparison_year"]

    raw_imagery_key = f"forest_sample_{comparison_year}"
    if raw_imagery_key not in acquisition_manifest["datasets"]:
        raise EvidenceGenerationError(f"Acquisition manifest missing '{raw_imagery_key}'.")
    raw_imagery_path = acquisition_manifest["datasets"][raw_imagery_key]["path"]

    if not os.path.exists(inside_alerts_path):
        raise EvidenceGenerationError(f"Inside-forest alerts file not found: {inside_alerts_path}")
    if not os.path.exists(inside_geojson_path):
        raise EvidenceGenerationError(f"Inside-forest GeoJSON not found: {inside_geojson_path}")

    with open(inside_alerts_path) as f:
        alerts = json.load(f)

    if limit is not None:
        alerts = alerts[:limit]

    if not alerts:
        raise EvidenceGenerationError("No inside-forest alerts to process.")

    polygons_gdf = gpd.read_file(inside_geojson_path)
    geometry_by_polygon_id = dict(zip(polygons_gdf["polygon_id"], polygons_gdf.geometry))
    crs = polygons_gdf.crs

    run_id = str(uuid.uuid4())
    os.makedirs(EVIDENCE_STORE_DIR, exist_ok=True)

    evidence_records = []
    failed = []
    skipped_already_done = 0
    total = len(alerts)
    progress_interval = max(1, total // 20)  # ~20 progress lines regardless of total size

    with rasterio.open(raw_imagery_path) as raster_src:
        for i, alert in enumerate(alerts, start=1):
            alert_id = alert["alert_id"]
            polygon_id = alert["polygon_id"]
            geometry = geometry_by_polygon_id.get(polygon_id)

            if geometry is None:
                failed.append({"alert_id": alert_id, "reason": f"No geometry found for polygon_id {polygon_id}"})
                continue

            alert_dir = os.path.join(EVIDENCE_STORE_DIR, alert_id)
            expected_files = [
                os.path.join(alert_dir, "map_snapshot.png"),
                os.path.join(alert_dir, "polygon.geojson"),
                os.path.join(alert_dir, "report.pdf"),
                os.path.join(alert_dir, "metadata.json"),
            ]

            # Resumability: if this alert's evidence was already fully
            # generated by a previous (possibly interrupted) run, skip it
            # rather than redoing expensive work.
            if all(os.path.exists(p) for p in expected_files):
                skipped_already_done += 1
                evidence_records.append({
                    "alert_id": alert_id,
                    "evidence_dir": alert_dir,
                    "map_snapshot": expected_files[0],
                    "geojson": expected_files[1],
                    "pdf_report": expected_files[2],
                    "metadata": expected_files[3],
                })
                continue

            os.makedirs(alert_dir, exist_ok=True)

            try:
                map_path = os.path.join(alert_dir, "map_snapshot.png")
                generate_map_snapshot(raster_src, geometry, map_path)

                geojson_path = os.path.join(alert_dir, "polygon.geojson")
                export_alert_geojson(alert, geometry, crs, geojson_path)

                pdf_path = os.path.join(alert_dir, "report.pdf")
                generate_pdf_report(alert, map_path, pdf_path)

                metadata_path = os.path.join(alert_dir, "metadata.json")
                build_and_write_metadata(
                    alert,
                    {"map_snapshot": map_path, "geojson": geojson_path, "pdf_report": pdf_path},
                    metadata_path,
                )

                evidence_records.append({
                    "alert_id": alert_id,
                    "evidence_dir": alert_dir,
                    "map_snapshot": map_path,
                    "geojson": geojson_path,
                    "pdf_report": pdf_path,
                    "metadata": metadata_path,
                })
            except Exception as e:
                failed.append({"alert_id": alert_id, "reason": str(e)})

            if i % progress_interval == 0 or i == total:
                print(f"  ...processed {i}/{total} alerts "
                      f"({len(evidence_records)} done, {len(failed)} failed, {skipped_already_done} skipped)")

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_alert_generation_run_id": alert_manifest.get("run_id"),
        "requested_limit": limit,
        "total_alerts_processed": len(alerts),
        "successful": len(evidence_records),
        "skipped_already_done": skipped_already_done,
        "failed": len(failed),
        "failures": failed,
        "evidence_records": evidence_records,
    }

    manifest_path = os.path.join(EVIDENCE_STORE_DIR, f"evidence_generation_{run_id}.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
