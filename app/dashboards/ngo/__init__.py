from flask import Blueprint

ngo_bp = Blueprint("ngo", __name__, url_prefix="/ngo")

from app.dashboards.ngo import routes  # noqa: E402,F401
