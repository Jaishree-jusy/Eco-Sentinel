
from flask import Blueprint, jsonify, request
import os
import json
from pathlib import Path

from app.database.queries import get_summary

from app.dashboards.government.data_loader import (
    get_alerts_page_data,
    get_analytics_data,
)

from app.blockchain.config import LEDGER_PATH
from app.blockchain.contract import SmartContractSimulator
from app.blockchain.pipeline import (
    _evidence_file_lookup_from_manifest,
    _find_latest_evidence_manifest,
    BlockchainError,
)


dashboard_api = Blueprint(
    "dashboard_api",
    __name__,
    url_prefix="/api/dashboard",
)


# ============================================================
# HELPERS
# ============================================================

def _project_root():
    return Path(__file__).resolve().parents[2]


def _load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _resolve_manifest_path(project_root, value):
    """Resolve paths saved by both the old and current project folders."""
    path = Path(value)

    # Keep the original file when it exists.
    if path.is_file():
        return path

    candidates = []

    if not path.is_absolute():
        candidates.append(project_root / path)

    # Old manifests may contain absolute paths from another project copy.
    # Resolve their filenames against the current project's data folders.
    candidates.extend([
        project_root / "data" / "alerts" / path.name,
        project_root / "data" / "boundary_check" / path.name,
    ])

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    checked = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        f"Manifest data file not found: {value}. Checked: {checked}"
    )


def _load_alert_list(path):
    data = _load_json(path)

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        alerts = data.get("alerts", [])
        return alerts if isinstance(alerts, list) else []

    return []


def _latest_alert_generation_manifest():
    alerts_dir = _project_root() / "data" / "alerts"

    if not alerts_dir.is_dir():
        return None, None

    valid_manifests = []

    for path in alerts_dir.glob("alert_generation_*.json"):
        try:
            manifest = _load_json(path)

            required = (
                "generated_at",
                "run_id",
                "base_year",
                "comparison_year",
                "inside_forest_alerts",
                "outside_forest_alerts",
            )

            if not all(key in manifest for key in required):
                continue

            valid_manifests.append((path, manifest))

        except (OSError, ValueError, TypeError):
            continue

    if not valid_manifests:
        return None, None

    return max(
        valid_manifests,
        key=lambda item: str(item[1]["generated_at"]),
    )


def _latest_evidence_count(project_root):
    # Preserve the existing verified evidence-generation run.
    evidence_run_id = "ffc07ec9-a46f-410c-917b-c6a617ce2467"

    evidence_run_dir = (
        project_root
        / "data"
        / "evidence_store"
        / f"evidence_run_{evidence_run_id}"
    )

    if not evidence_run_dir.is_dir():
        return 0

    return sum(
        1
        for report in evidence_run_dir.rglob("report.pdf")
        if report.is_file()
    )


# ============================================================
# GOVERNMENT DASHBOARD SUMMARY
# ============================================================

@dashboard_api.route("/summary", methods=["GET"])
def dashboard_summary():
    project_root = _project_root()
    manifest_path, manifest = _latest_alert_generation_manifest()

    if manifest is None:
        meta = get_summary("inside_forest")

        if meta is None:
            return jsonify({
                "error": "No government dashboard data available"
            }), 404

        return jsonify(meta)

    try:
        inside_info = manifest["inside_forest_alerts"]
        outside_info = manifest["outside_forest_alerts"]

        inside_path = _resolve_manifest_path(
            project_root,
            inside_info["path"],
        )

        inside_alerts = _load_alert_list(inside_path)

        total_area = sum(
            float(alert.get("area_lost_ha") or 0)
            for alert in inside_alerts
        )

        evidence_count = _latest_evidence_count(project_root)

        return jsonify({
            "base_year": manifest["base_year"],
            "comparison_year": manifest["comparison_year"],
            "total_alerts": inside_info["count"],
            "outside_forest_alerts": outside_info["count"],
            "total_area_ha": round(total_area, 4),
            "evidence_generated_count": evidence_count,
            "alert_generation_run_id": manifest["run_id"],
            "generated_at": manifest["generated_at"],
        })

    except (OSError, ValueError, TypeError, KeyError) as exc:
        return jsonify({
            "error": "Unable to load the latest alert-generation summary",
            "details": str(exc),
            "manifest": manifest_path.name,
        }), 500


# ============================================================
# COMPARISON PERIODS (READ-ONLY)
# ============================================================

@dashboard_api.route("/comparisons", methods=["GET"])
def dashboard_comparisons():
    project_root = _project_root()
    alerts_dir = project_root / "data" / "alerts"

    # Verified manifest IDs for the two comparison periods.
    preferred_runs = [
        "21e4fc94-7c04-40de-9bc3-a4924e2f67a8",
        "373e1bd1-7fbe-4693-9f2e-ad13c93e1b72",
    ]

    comparisons = []

    for run_id in preferred_runs:
        manifest_path = alerts_dir / f"alert_generation_{run_id}.json"

        try:
            manifest = _load_json(manifest_path)

            inside_info = manifest["inside_forest_alerts"]
            outside_info = manifest["outside_forest_alerts"]

            inside_path = _resolve_manifest_path(
                project_root,
                inside_info["path"],
            )
            outside_path = _resolve_manifest_path(
                project_root,
                outside_info["path"],
            )

            inside = _load_alert_list(inside_path)
            outside = _load_alert_list(outside_path)

            inside_area = sum(
                float(alert.get("area_lost_ha") or 0)
                for alert in inside
            )
            outside_area = sum(
                float(alert.get("area_lost_ha") or 0)
                for alert in outside
            )

            comparisons.append({
                "run_id": manifest["run_id"],
                "base_year": manifest["base_year"],
                "comparison_year": manifest["comparison_year"],
                "generated_at": manifest["generated_at"],
                "inside_forest_alerts": len(inside),
                "outside_forest_alerts": len(outside),
                "inside_forest_area_ha": round(inside_area, 4),
                "outside_forest_area_ha": round(outside_area, 4),
            })

        except (OSError, ValueError, TypeError, KeyError) as exc:
            return jsonify({
                "error": "Unable to load comparison period",
                "run_id": run_id,
                "details": str(exc),
            }), 500

    return jsonify({"comparisons": comparisons})


# ============================================================
# GOVERNMENT ALERTS
# ============================================================

@dashboard_api.route("/alerts", methods=["GET"])
def dashboard_alerts():
    page = max(
        1,
        request.args.get("page", 1, type=int),
    )

    per_page = min(
        100,
        max(
            1,
            request.args.get("per_page", 25, type=int),
        ),
    )

    alerts, total = get_alerts_page_data(page, per_page)

    formatted_alerts = []

    for alert in alerts:
        location = alert.get("location") or {}

        formatted_alerts.append({
            "alertId": alert.get("alert_id"),
            "polygonId": alert.get("polygon_id"),
            "detectedAt": alert.get("date_time"),
            "detectionClass": alert.get("detection_class"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            "region": alert.get("region_division"),
            "areaLostHa": alert.get("area_lost_ha", 0),
            "severity": alert.get("severity_level"),
            "mlConfidence": alert.get("ml_confidence"),
            "status": alert.get("status", "New"),
            "priority": alert.get("priority", "Unassessed"),
            "legalityStatus": alert.get("legality_status"),
            "matchedPermitId": alert.get(
                "matched_authorization_id"
            ),
            "finalCategory": alert.get("final_category"),
            "evidenceAvailable": alert.get(
                "evidence_available",
                False,
            ),
            "branch": "inside-forest",
        })

    return jsonify({
        "alerts": formatted_alerts,
        "page": page,
        "perPage": per_page,
        "total": total,
    })


# ============================================================
# GOVERNMENT ANALYTICS
# ============================================================

@dashboard_api.route("/analytics", methods=["GET"])
def dashboard_analytics():
    severity_counts, top_regions = get_analytics_data()

    return jsonify({
        "severityCounts": severity_counts,
        "topRegions": [
            {
                "region": region,
                "count": count,
            }
            for region, count in top_regions
        ],
    })


# ============================================================
# GOVERNMENT BLOCKCHAIN
# ============================================================

@dashboard_api.route("/blockchain", methods=["GET"])
def dashboard_blockchain():
    if not os.path.exists(LEDGER_PATH):
        return jsonify({
            "chain_exists": False,
            "valid": False,
            "issues": ["Blockchain ledger not found"],
            "chain": [],
        })

    contract = SmartContractSimulator(LEDGER_PATH)

    try:
        evidence_manifest = _find_latest_evidence_manifest()

        file_lookup = _evidence_file_lookup_from_manifest(
            evidence_manifest
        )

    except BlockchainError:
        file_lookup = {}

    issues = contract.verify_chain(
        evidence_file_lookup=file_lookup
    )

    return jsonify({
        "chain_exists": True,
        "valid": len(issues) == 0,
        "issues": issues,
        "chain": contract.chain,
    })
