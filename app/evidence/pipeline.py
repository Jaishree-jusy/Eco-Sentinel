
"""
Module 8 evidence pipeline.

Supports explicit source imagery and writes each run to a separate folder.
Does not modify acquisition manifests, existing evidence, alerts, or blockchain.
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
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            candidates.append((data[timestamp_key], data))
        except (OSError, json.JSONDecodeError, KeyError):
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _find_latest_alert_manifest():
    manifest = _find_latest(
        os.path.join(ALERTS_DIR, "alert_generation_*.json"),
        "generated_at",
    )
    if manifest is None:
        raise EvidenceGenerationError("No alert-generation manifest found.")
    return manifest


def _find_latest_boundary_check_manifest():
    manifest = _find_latest(
        os.path.join(BOUNDARY_CHECK_DIR, "boundary_check_*.json"),
        "checked_at",
    )
    if manifest is None:
        raise EvidenceGenerationError("No boundary-check manifest found.")
    return manifest


def _find_latest_acquisition_manifest():
    manifest = _find_latest(
        os.path.join(ACQUISITION_RUNS_DIR, "run_*.json"),
        "triggered_at",
    )
    if manifest is None:
        raise EvidenceGenerationError("No acquisition manifest found.")
    return manifest


def run_evidence_generation(
    alert_manifest=None,
    boundary_manifest=None,
    acquisition_manifest=None,
    limit=None,
    raw_imagery_path=None,
    source_metadata=None,
    output_root=None,
):
    """
    Generate evidence for inside-forest alerts.

    raw_imagery_path:
        Optional explicit raster path. When supplied, the historical
        acquisition manifest is read but never modified.

    source_metadata:
        Optional verified acquisition/comparison metadata for PDFs and JSON.

    output_root:
        Optional parent folder for isolated evidence output. A unique
        subfolder is created for every run.
    """
    if alert_manifest is None:
        alert_manifest = _find_latest_alert_manifest()
    if boundary_manifest is None:
        boundary_manifest = _find_latest_boundary_check_manifest()
    if acquisition_manifest is None:
        acquisition_manifest = _find_latest_acquisition_manifest()

    inside_alerts_path = alert_manifest["inside_forest_alerts"]["path"]
    inside_geojson_path = boundary_manifest["inside_forest"]["path"]

    comparison_year = str(boundary_manifest["comparison_year"])
    base_year = str(boundary_manifest.get("base_year", "Unknown"))

    # Only use the explicit raster when the caller has supplied one.
    # Otherwise retain the original manifest-key lookup behavior.
    if raw_imagery_path is None:
        raw_imagery_key = f"forest_sample_{comparison_year}"
        if raw_imagery_key not in acquisition_manifest.get("datasets", {}):
            raise EvidenceGenerationError(
                f"Acquisition manifest missing '{raw_imagery_key}'. "
                "Supply raw_imagery_path explicitly for a verified source raster."
            )
        raw_imagery_path = acquisition_manifest["datasets"][
            raw_imagery_key
        ]["path"]

    if not os.path.isfile(inside_alerts_path):
        raise EvidenceGenerationError(
            f"Inside-forest alerts file not found: {inside_alerts_path}"
        )
    if not os.path.isfile(inside_geojson_path):
        raise EvidenceGenerationError(
            f"Inside-forest GeoJSON not found: {inside_geojson_path}"
        )
    if not os.path.isfile(raw_imagery_path):
        raise EvidenceGenerationError(
            f"Source raster not found: {raw_imagery_path}"
        )

    with open(inside_alerts_path, encoding="utf-8") as f:
        alerts = json.load(f)

    if limit is not None:
        if not isinstance(limit, int) or limit < 1:
            raise EvidenceGenerationError("limit must be a positive integer.")
        alerts = alerts[:limit]

    if not alerts:
        raise EvidenceGenerationError("No inside-forest alerts to process.")

    polygons_gdf = gpd.read_file(inside_geojson_path)
    geometry_by_polygon_id = dict(
        zip(polygons_gdf["polygon_id"], polygons_gdf.geometry)
    )
    crs = polygons_gdf.crs

    # Keep all outputs isolated from historical evidence folders.
    run_id = str(uuid.uuid4())
    parent_dir = output_root or EVIDENCE_STORE_DIR
    run_evidence_root = os.path.join(parent_dir, f"evidence_run_{run_id}")
    os.makedirs(run_evidence_root, exist_ok=False)

    source_info = dict(source_metadata or {})
    source_info.setdefault("base_year", base_year)
    source_info.setdefault("comparison_year", comparison_year)
    source_info.setdefault(
        "comparison_period", f"{base_year} vs {comparison_year}"
    )
    source_info.setdefault(
        "source_acquisition_run_id", acquisition_manifest.get("run_id")
    )
    source_info["source_raster_path"] = os.path.abspath(raw_imagery_path)

    evidence_records = []
    failed = []
    skipped_already_done = 0
    total = len(alerts)
    progress_interval = max(1, total // 20)

    with rasterio.open(raw_imagery_path) as raster_src:
        for i, alert in enumerate(alerts, start=1):
            alert_id = alert["alert_id"]
            polygon_id = alert["polygon_id"]
            geometry = geometry_by_polygon_id.get(polygon_id)

            if geometry is None:
                failed.append({
                    "alert_id": alert_id,
                    "reason": f"No geometry found for polygon_id {polygon_id}",
                })
                continue

            # New folder per run; never reuse or overwrite old alert evidence.
            alert_dir = os.path.join(run_evidence_root, str(alert_id))
            os.makedirs(alert_dir, exist_ok=False)

            try:
                map_path = os.path.join(alert_dir, "map_snapshot.png")
                generate_map_snapshot(raster_src, geometry, map_path)

                geojson_path = os.path.join(alert_dir, "polygon.geojson")
                export_alert_geojson(alert, geometry, crs, geojson_path)

                pdf_path = os.path.join(alert_dir, "report.pdf")
                generate_pdf_report(
                    alert,
                    map_path,
                    pdf_path,
                    source_metadata=source_info,
                )

                metadata_path = os.path.join(alert_dir, "metadata.json")
                build_and_write_metadata(
                    alert,
                    {
                        "map_snapshot": map_path,
                        "geojson": geojson_path,
                        "pdf_report": pdf_path,
                    },
                    metadata_path,
                    source_metadata=source_info,
                )

                evidence_records.append({
                    "alert_id": alert_id,
                    "evidence_dir": alert_dir,
                    "map_snapshot": map_path,
                    "geojson": geojson_path,
                    "pdf_report": pdf_path,
                    "metadata": metadata_path,
                })

            except Exception as exc:
                failed.append({
                    "alert_id": alert_id,
                    "reason": str(exc),
                })

            if i % progress_interval == 0 or i == total:
                print(
                    f"  ...processed {i}/{total} alerts "
                    f"({len(evidence_records)} done, "
                    f"{len(failed)} failed, "
                    f"{skipped_already_done} skipped)"
                )

    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_alert_generation_run_id": alert_manifest.get("run_id"),
        "source_boundary_check_run_id": boundary_manifest.get("run_id"),
        "source_acquisition_run_id": acquisition_manifest.get("run_id"),
        "source_imagery": source_info,
        "requested_limit": limit,
        "total_alerts_processed": len(alerts),
        "successful": len(evidence_records),
        "skipped_already_done": skipped_already_done,
        "failed": len(failed),
        "failures": failed,
        "evidence_root": run_evidence_root,
        "evidence_records": evidence_records,
    }

    manifest_path = os.path.join(
        run_evidence_root, f"evidence_generation_{run_id}.json"
    )
    with open(manifest_path, "x", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    manifest["manifest_path"] = manifest_path
    return manifest
