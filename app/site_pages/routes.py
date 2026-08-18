"""
Routes for the public-facing site shell: landing, about, how-it-works,
role selection. These pull real summary numbers from the database where
available, and degrade gracefully (shows "--" / a note, not a crash or a
fake number) if the pipeline hasn't been run/synced yet.
"""

from flask import render_template
from app.site_pages import site_bp
from app.database.queries import get_summary


def _combined_stats():
    inside = get_summary("inside_forest")
    outside = get_summary("outside_forest")

    if inside is None and outside is None:
        return None

    total_alerts = (inside["total_alerts"] if inside else 0) + (outside["total_alerts"] if outside else 0)
    total_area = round((inside["total_area_ha"] if inside else 0) + (outside["total_area_ha"] if outside else 0), 2)
    base_year = (inside or outside)["base_year"]
    comparison_year = (inside or outside)["comparison_year"]

    return {
        "total_alerts": total_alerts,
        "total_area_ha": total_area,
        "inside_count": inside["total_alerts"] if inside else 0,
        "outside_count": outside["total_alerts"] if outside else 0,
        "base_year": base_year,
        "comparison_year": comparison_year,
    }


@site_bp.route("/")
def landing():
    stats = _combined_stats()
    return render_template("site/landing.html", stats=stats)


@site_bp.route("/about")
def about():
    return render_template("site/about.html")


@site_bp.route("/how-it-works")
def how_it_works():
    return render_template("site/how_it_works.html")


@site_bp.route("/get-started")
def get_started():
    stats = _combined_stats()
    return render_template("site/role_select.html", stats=stats)
