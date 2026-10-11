"""
ECO-SENTINEL Flask application factory.
"""

from flask import Flask, render_template
from flask_cors import CORS


def create_app(start_background_scheduler=False):
    app = Flask(__name__)
    CORS(app)

    # Existing Government dashboard
    from app.dashboards.government import gov_bp
    app.register_blueprint(gov_bp)

    # Existing NGO dashboard
    from app.dashboards.ngo import ngo_bp
    app.register_blueprint(ngo_bp)

    # Existing site pages
    from app.site_pages import site_bp
    app.register_blueprint(site_bp)

    # API blueprints
    from app.api import dashboard_api
    app.register_blueprint(dashboard_api)

    # Export API
    from app.api.export import export_api
    app.register_blueprint(export_api)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    if start_background_scheduler and not app.config.get("TESTING"):
        from app.acquisition.scheduler import start_scheduler
        start_scheduler()

    return app