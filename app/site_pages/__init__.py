from flask import Blueprint

site_bp = Blueprint("site", __name__, template_folder="../templates/site")

from app.site_pages import routes
