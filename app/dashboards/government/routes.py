"""
Routes for the Government Dashboard (Module 10).
"""

import os
import glob
import json

from flask import render_template, jsonify, abort, send_file, request

from app.dashboards.government import gov_bp
from app.dashboards.government.data_loader import (
    load_dashboard_data,
    get_alert_by_id,
    get_alerts_page_data,
    get_analytics_data,
)
from app.database.queries import get_summary
from app.config import EVIDENCE_STORE_DIR
from app.blockchain.config import LEDGER_PATH
from app.blockchain.contract import SmartContractSimulator
from app.blockchain.pipeline import (
    _evidence_file_lookup_from_manifest,
    _find_latest_evidence_manifest,
    BlockchainError,
)

from app.acquisition.runner import run_acquisition
from app.acquisition.config import (
    DEFAULT_REGION,
    DEFAULT_YEAR_PAIR,
    ACQUISITION_RUNS_DIR,
    GEE_ACQUISITION_WINDOW_DAYS,
    GEE_CLOUD_COVER_THRESHOLD,
    REGIONS,
)


ALERTS_PER_PAGE = 100


# ============================================================
# GOVERNMENT DASHBOARD
# ============================================================

@gov_bp.route("/")
def dashboard():
    alerts, meta = load_dashboard_data()

    if alerts is None:
        return render_template("government/no_data.html")

    return render_template(
        "government/dashboard.html",
        meta=meta,
    )


# ============================================================
# ALERT GEOJSON
# ============================================================

@gov_bp.route("/api/alerts.geojson")
def alerts_geojson():
    alerts, meta = load_dashboard_data()

    if alerts is None:
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
        })

    features = []

    for a in alerts:
        if a["geometry"] is None:
            continue

        features.append({
            "type": "Feature",
            "geometry": a["geometry"],
            "properties": {
                "alert_id": a["alert_id"],
                "severity_level": a["severity_level"],
                "area_lost_ha": a["area_lost_ha"],
                "region_division": a["region_division"],
                "evidence_available": a.get(
                    "evidence_available",
                    False,
                ),
                "latitude": a["location"]["latitude"],
                "longitude": a["location"]["longitude"],
            },
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": features,
    })


# ============================================================
# ALERT LIST
# ============================================================

@gov_bp.route("/alerts")
def alerts_list():
    meta = get_summary("inside_forest")

    if meta is None:
        return render_template(
            "government/no_data.html"
        )

    page = max(
        1,
        request.args.get(
            "page",
            1,
            type=int,
        ),
    )

    total_pages = max(
        1,
        (
            meta["total_alerts"]
            + ALERTS_PER_PAGE
            - 1
        )
        // ALERTS_PER_PAGE,
    )

    page = min(
        page,
        total_pages,
    )

    # True SQL-level pagination.
    page_alerts, _ = get_alerts_page_data(
        page,
        ALERTS_PER_PAGE,
    )

    return render_template(
        "government/alerts_list.html",
        alerts=page_alerts,
        meta=meta,
        page=page,
        total_pages=total_pages,
    )


# ============================================================
# ALERT DETAIL
# ============================================================

@gov_bp.route("/alerts/<alert_id>")
def alert_detail(alert_id):
    alert = get_alert_by_id(alert_id)

    if alert is None:
        abort(404)

    return render_template(
        "government/alert_detail.html",
        alert=alert,
    )


# ============================================================
# EVIDENCE FILE
# ============================================================

@gov_bp.route(
    "/evidence/<alert_id>/<filename>"
)
def serve_evidence_file(
    alert_id,
    filename,
):
    """
    Serves an evidence file for viewing/download.

    Validates that the resolved path remains
    inside EVIDENCE_STORE_DIR to prevent
    path traversal.
    """

    alert_dir = os.path.abspath(
        os.path.join(
            EVIDENCE_STORE_DIR,
            alert_id,
        )
    )

    file_path = os.path.abspath(
        os.path.join(
            alert_dir,
            filename,
        )
    )

    if not file_path.startswith(
        os.path.abspath(
            EVIDENCE_STORE_DIR
        )
    ):
        abort(403)

    if not os.path.exists(file_path):
        abort(404)

    return send_file(file_path)


# ============================================================
# ANALYTICS
# ============================================================

@gov_bp.route("/analytics")
def analytics():
    meta = get_summary("inside_forest")

    if meta is None:
        return render_template(
            "government/no_data.html"
        )

    # Computed using SQL GROUP BY.
    severity_counts, top_regions = (
        get_analytics_data()
    )

    return render_template(
        "government/analytics.html",
        meta=meta,
        severity_counts=severity_counts,
        top_regions=top_regions,
    )


# ============================================================
# BLOCKCHAIN
# ============================================================

@gov_bp.route("/blockchain")
def blockchain_view():
    if not os.path.exists(LEDGER_PATH):
        return render_template(
            "government/blockchain.html",
            chain_exists=False,
        )

    contract = SmartContractSimulator(
        LEDGER_PATH
    )

    try:
        evidence_manifest = (
            _find_latest_evidence_manifest()
        )

        file_lookup = (
            _evidence_file_lookup_from_manifest(
                evidence_manifest
            )
        )

    except BlockchainError:
        file_lookup = {}

    issues = contract.verify_chain(
        evidence_file_lookup=file_lookup
    )

    return render_template(
        "government/blockchain.html",
        chain_exists=True,
        chain=contract.chain,
        valid=(len(issues) == 0),
        issues=issues,
    )


# ============================================================
# LIVE MONITORING
# ============================================================

@gov_bp.route(
    "/api/live-monitoring/status"
)
def live_monitoring_status():
    """
    Return the latest live-GEE acquisition
    information for the government dashboard.
    """

    pattern = os.path.join(
        ACQUISITION_RUNS_DIR,
        "run_*.json",
    )

    manifests = []

    for path in glob.glob(pattern):
        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as f:
                data = json.load(f)

            manifests.append(data)

        except (
            OSError,
            json.JSONDecodeError,
        ):
            continue

    manifests.sort(
        key=lambda item: item.get(
            "triggered_at",
            "",
        ),
        reverse=True,
    )

    latest = (
        manifests[0]
        if manifests
        else None
    )

    gee_metadata = (
        latest.get("gee_metadata")
        if latest
        else None
    )

    if gee_metadata is None:
        gee_metadata = {}

    region_config = REGIONS.get(
        DEFAULT_REGION,
        {},
    )

    return jsonify({
        "monitoring": {
            "mode": "live",
            "enabled": True,
            "region": DEFAULT_REGION,
            "region_name": region_config.get(
                "name",
                DEFAULT_REGION,
            ),
            "search_window_days": (
                GEE_ACQUISITION_WINDOW_DAYS
            ),
            "cloud_cover_threshold_pct": (
                GEE_CLOUD_COVER_THRESHOLD
            ),
        },

        "latest_acquisition": {
            "run_id": (
                latest.get("run_id")
                if latest
                else None
            ),

            "status": (
                latest.get("status")
                if latest
                else None
            ),

            "triggered_at": (
                latest.get("triggered_at")
                if latest
                else None
            ),

            "gee_image_id": (
                gee_metadata.get(
                    "gee_image_id"
                )
            ),

            "acquisition_date": (
                gee_metadata.get(
                    "acquisition_date"
                )
            ),

            "cloud_cover_pct": (
                gee_metadata.get(
                    "cloud_cover_pct"
                )
            ),

            "was_new_download": (
                gee_metadata.get(
                    "was_new_download"
                )
            ),

            "was_realigned": (
                gee_metadata.get(
                    "was_realigned"
                )
            ),
        },
    })


@gov_bp.route(
    "/api/live-monitoring/fetch",
    methods=["POST"],
)
def fetch_live_data():
    """
    Trigger one real live-GEE acquisition cycle.

    This endpoint is called by the dashboard's
    'FETCH NEW LIVE DATA' button.
    """

    try:
        manifest = run_acquisition(
            region_key=DEFAULT_REGION,
            base_year=DEFAULT_YEAR_PAIR[
                "base_year"
            ],
            comparison_year=DEFAULT_YEAR_PAIR[
                "comparison_year"
            ],
            trigger_mode="manual_dashboard",
            use_live_gee=True,
        )

        gee_metadata = (
            manifest.get(
                "gee_metadata"
            )
            or {}
        )

        was_new = gee_metadata.get(
            "was_new_download",
            False,
        )

        if was_new:
            message = (
                "New Sentinel-2 imagery "
                "was acquired successfully."
            )
        else:
            message = (
                "No new Sentinel-2 imagery "
                "was acquired."
            )

        return jsonify({
            "success": True,

            "status": manifest.get(
                "status"
            ),

            "run_id": manifest.get(
                "run_id"
            ),

            "message": message,

            "gee": {
                "image_id": gee_metadata.get(
                    "gee_image_id"
                ),

                "acquisition_date": (
                    gee_metadata.get(
                        "acquisition_date"
                    )
                ),

                "cloud_cover_pct": (
                    gee_metadata.get(
                        "cloud_cover_pct"
                    )
                ),

                "was_new_download": (
                    gee_metadata.get(
                        "was_new_download"
                    )
                ),

                "was_realigned": (
                    gee_metadata.get(
                        "was_realigned"
                    )
                ),
            },
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "status": "failed",
            "message": str(e),
        }), 500