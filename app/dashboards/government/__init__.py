from flask import Blueprint

gov_bp = Blueprint("government", __name__, url_prefix="/government")

from app.dashboards.government import routes  # noqa: E402,F401
