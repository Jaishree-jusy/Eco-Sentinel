"""

Routes for the Government Dashboard (Module 10).

"""



import os

import glob

import json
import traceback



from shapely.geometry import shape



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
from app.acquisition.scheduler import is_scheduler_running
from app.orchestration.pipeline_runner import run_full_pipeline, PipelineRunError

from app.acquisition.config import (

    DEFAULT_REGION,

    DEFAULT_YEAR_PAIR,

    ACQUISITION_RUNS_DIR,

    GEE_ACQUISITION_WINDOW_DAYS,

    GEE_CLOUD_COVER_THRESHOLD,

    REGIONS,

)





ALERTS_PER_PAGE = 100

# Cache for processed ML detection GeoJSON
ML_DETECTIONS_CACHE = None





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

# ALERT LIST

# ============================================================



@gov_bp.route("/alerts")

def alerts_list():

    """

    Paginated inside-forest alert list.



    Uses the SQLite-backed query layer through

    get_alerts_page_data() rather than loading every alert

    into memory for each page request.

    """



    meta = get_summary("inside_forest")



    if meta is None:

        return render_template("government/no_data.html")



    page = max(1, request.args.get("page", 1, type=int))



    total_pages = max(

        1,

        (meta["total_alerts"] + ALERTS_PER_PAGE - 1)

        // ALERTS_PER_PAGE,

    )



    page = min(page, total_pages)



    alerts, _ = get_alerts_page_data(

        page,

        ALERTS_PER_PAGE,

    )



    return render_template(

        "government/alerts_list.html",

        alerts=alerts,

        meta=meta,

        page=page,

        total_pages=total_pages,

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

# ML DEFORESTATION GEOJSON

# ============================================================



@gov_bp.route("/api/ml-detections.geojson")
def ml_detections_geojson():
    """Return ML detection polygons with frontend-ready properties."""

    global ML_DETECTIONS_CACHE

    if ML_DETECTIONS_CACHE is not None:
        return jsonify(ML_DETECTIONS_CACHE)

    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(__file__)
            )
        )
    )

    ml_geojson_path = os.path.join(
        project_root,
        "data",
        "supervised",
        "deforestation_polygons_ml_2023_2025_filtered_1000m2.geojson",
    )

    if not os.path.exists(ml_geojson_path):
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
            "error": "ML detection layer not found",
        })

    try:
        with open(ml_geojson_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        updated_features = []

        for index, feature in enumerate(data.get("features", [])):
            geometry = feature.get("geometry")

            if not geometry:
                continue

            try:
                properties = (feature.get("properties", {}) or {}).copy()

                properties["polygon_id"] = properties.get(
                    "polygon_id",
                    f"ML-DETECTION-{index + 1:05d}",
                )

                properties["prediction"] = properties.get(
                    "prediction",
                    properties.get("class", 1),
                )

                # Only calculate the centroid when it is missing.
                if (
                    properties.get("centroid_lat") is None
                    or properties.get("centroid_lon") is None
                ):
                    polygon = shape(geometry)

                    if polygon.is_empty:
                        continue

                    centroid = polygon.centroid
                    properties["centroid_lat"] = round(centroid.y, 6)
                    properties["centroid_lon"] = round(centroid.x, 6)

                updated_features.append({
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": properties,
                })

            except Exception as feature_error:
                print(
                    f"Error processing ML feature {index}: {feature_error}"
                )
                continue

        result = {
            "type": "FeatureCollection",
            "features": updated_features,
        }

        # Cache the processed response for subsequent requests.
        ML_DETECTIONS_CACHE = result

        return jsonify(result)

    except (OSError, json.JSONDecodeError) as file_error:
        print(f"ML GeoJSON file error: {file_error}")
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
            "error": "Unable to read ML detection layer",
        }), 500

    except Exception as error:
        print(f"ML detection processing error: {error}")
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
            "error": "Unable to process ML detection layer",
        }), 500


# ============================================================

# RANDOM FOREST PREDICTIONS GEOJSON
# ============================================================

@gov_bp.route("/api/rf-detections.geojson")
def rf_detections_geojson():
    """
    Return saved RF test alerts as GeoJSON point features.
    The source records contain coordinates, not polygon boundaries.
    """
    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(__file__)
            )
        )
    )

    rf_json_path = os.path.join(
        project_root,
        "data",
        "supervised",
        "live_runs",
        "alerts_inside_rf-test-ed15535c.json",
    )

    if not os.path.isfile(rf_json_path):
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
            "message": "Existing RF test alert JSON was not found.",
        }), 404

    try:
        with open(rf_json_path, "r", encoding="utf-8") as file:
            alerts = json.load(file)

        if not isinstance(alerts, list):
            return jsonify({
                "type": "FeatureCollection",
                "features": [],
                "message": "RF test alert file must contain a JSON array.",
            }), 500

        features = []
        for alert in alerts:
            if not isinstance(alert, dict):
                continue

            location = alert.get("location") or {}
            latitude = location.get("latitude")
            longitude = location.get("longitude")
            if latitude is None or longitude is None:
                continue

            try:
                latitude = float(latitude)
                longitude = float(longitude)
                confidence = float(alert.get("ml_confidence", 0))
            except (TypeError, ValueError):
                continue

            properties = dict(alert)
            properties.update({
                "latitude": latitude,
                "longitude": longitude,
                "polygon_id": alert.get("polygon_id", alert.get("alert_id")),
                "prediction": 1,
                "deforestation_probability": confidence,
                "is_rf_test": True,
            })

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [longitude, latitude],
                },
                "properties": properties,
            })

        return jsonify({
            "type": "FeatureCollection",
            "features": features,
            "source": "existing_rf_test_alerts",
            "is_test_data": True,
        })

    except (OSError, json.JSONDecodeError) as error:
        traceback.print_exc()
        return jsonify({
            "type": "FeatureCollection",
            "features": [],
            "message": "Unable to read the existing RF test alert file.",
            "details": str(error),
        }), 500


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



@gov_bp.route("/evidence/<alert_id>/<filename>")

def serve_evidence_file(alert_id, filename):

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

        os.path.abspath(EVIDENCE_STORE_DIR)

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



    severity_counts, top_regions = get_analytics_data()



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



@gov_bp.route("/api/live-monitoring/status")

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



    comp_year = (
        latest.get("comparison_year", DEFAULT_YEAR_PAIR["comparison_year"])
        if latest
        else DEFAULT_YEAR_PAIR["comparison_year"]
    )
    comp_key = f"forest_sample_{comp_year}"
    local_path = (
        gee_metadata.get("local_path")
        or (
            latest.get("datasets", {})
            .get(comp_key, {})
            .get("path")
            if latest
            else None
        )
    )

    scheduler_active = is_scheduler_running()

    return jsonify({
        "monitoring": {
            "mode": "live",
            "enabled": scheduler_active,
            "scheduler_running": scheduler_active,
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

            "local_path": local_path,

            "error_message": (
                latest.get("error_message")
                if latest
                else None
            ),
        },
    })






@gov_bp.route(

    "/api/live-monitoring/fetch",

    methods=["POST"],

)

def fetch_live_data():
    """
    Trigger one real live-GEE acquisition and full pipeline cycle.

    This endpoint is called by the dashboard's 'FETCH NEW LIVE DATA' button.
    If acquisition returns no_new_data, downstream processing is safely skipped.
    """
    try:
        pipeline_result = run_full_pipeline(
            region_key=DEFAULT_REGION,
            base_year=DEFAULT_YEAR_PAIR["base_year"],
            comparison_year=DEFAULT_YEAR_PAIR["comparison_year"],
            trigger_mode="manual_dashboard",
            use_live_gee=True,
        )

        status = pipeline_result.get("status")
        gee_metadata = pipeline_result.get("gee_metadata") or {}
        acq_manifest = pipeline_result.get("acquisition_manifest") or {}
        stage_run_ids = pipeline_result.get("stage_run_ids") or {}
        pipeline_run_id = pipeline_result.get("pipeline_run_id")

        if status == "success":
            message = "New Sentinel-2 imagery acquired and full monitoring pipeline completed successfully."
        elif status == "no_new_data":
            message = pipeline_result.get(
                "message",
                "No new Sentinel-2 imagery available - downstream pipeline not rerun, previous results preserved.",
            )
        else:
            message = f"Pipeline finished with status: {status}"

        comp_key = f"forest_sample_{DEFAULT_YEAR_PAIR['comparison_year']}"
        local_path = (
            gee_metadata.get("local_path")
            or acq_manifest.get("datasets", {}).get(comp_key, {}).get("path")
        )

        return jsonify({
            "success": True,
            "status": status,
            "pipeline_run_id": pipeline_run_id,
            "run_id": stage_run_ids.get("acquisition") or pipeline_run_id,
            "stage_run_ids": stage_run_ids,
            "sync_stats": pipeline_result.get("sync_stats"),
            "message": message,
            "gee": {
                "image_id": gee_metadata.get("gee_image_id"),
                "acquisition_date": gee_metadata.get("acquisition_date"),
                "cloud_cover_pct": gee_metadata.get("cloud_cover_pct"),
                "was_new_download": gee_metadata.get("was_new_download"),
                "was_realigned": gee_metadata.get("was_realigned"),
                "local_path": local_path,
            },
        })

    except PipelineRunError as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "status": "failed",
            "failed_stage": e.stage,
            "message": f"Pipeline failed during {e.stage}: {str(e.original_error)}",
            "error": str(e.original_error),
        }), 500

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "success": False,
            "status": "failed",
            "message": str(e),
            "error": str(e),
        }), 500
