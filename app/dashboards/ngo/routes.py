"""
Routes for the NGO Dashboard (Module 7B).
"""

from flask import render_template, jsonify, abort, request

from app.dashboards.ngo import ngo_bp
from app.dashboards.ngo.data_loader import (
    load_ngo_dashboard_data, get_ngo_alert_by_id, get_ngo_alerts_page_data,
    get_ngo_trends_data, get_ngo_top_by_area,
)
from app.database.queries import get_summary

ALERTS_PER_PAGE = 100


@ngo_bp.route("/")
def dashboard():
    alerts, meta = load_ngo_dashboard_data()
    if alerts is None:
        return render_template("ngo/no_data.html")
    return render_template("ngo/dashboard.html", meta=meta)


@ngo_bp.route("/api/alerts.geojson")
def alerts_geojson():
    alerts, meta = load_ngo_dashboard_data()
    if alerts is None:
        return jsonify({"type": "FeatureCollection", "features": []})

    features = []
    for a in alerts:
        if a["geometry"] is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": a["geometry"],
            "properties": {
                "alert_id": a["alert_id"],
                "area_lost_ha": a["area_lost_ha"],
                "region_area_type": a["region_area_type"],
                "latitude": a["location"]["latitude"],
                "longitude": a["location"]["longitude"],
            },
        })

    return jsonify({"type": "FeatureCollection", "features": features})


@ngo_bp.route("/alerts")
def alerts_list():
    meta = get_summary("outside_forest")
    if meta is None:
        return render_template("ngo/no_data.html")

    page = max(1, request.args.get("page", 1, type=int))
    total_pages = max(1, (meta["total_alerts"] + ALERTS_PER_PAGE - 1) // ALERTS_PER_PAGE)
    page = min(page, total_pages)

    page_alerts, _ = get_ngo_alerts_page_data(page, ALERTS_PER_PAGE)

    return render_template(
        "ngo/alerts_list.html",
        alerts=page_alerts, meta=meta, page=page, total_pages=total_pages,
    )


@ngo_bp.route("/alerts/<alert_id>")
def alert_detail(alert_id):
    alert = get_ngo_alert_by_id(alert_id)
    if alert is None:
        abort(404)
    return render_template("ngo/alert_detail.html", alert=alert)


@ngo_bp.route("/trends")
def trends():
    meta = get_summary("outside_forest")
    if meta is None:
        return render_template("ngo/no_data.html")

    area_type_counts, area_type_ha = get_ngo_trends_data()

    return render_template(
        "ngo/trends.html",
        meta=meta, area_type_counts=area_type_counts, area_type_ha=area_type_ha,
    )


@ngo_bp.route("/awareness")
def awareness():
    meta = get_summary("outside_forest")
    if meta is None:
        return render_template("ngo/no_data.html")

    top_by_area = get_ngo_top_by_area(limit=15)

    return render_template("ngo/awareness.html", meta=meta, top_by_area=top_by_area)
