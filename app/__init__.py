"""
ECO-SENTINEL Flask application factory.
"""

from flask import Flask, render_template


def create_app():
    app = Flask(__name__)

    from app.dashboards.government import gov_bp
    app.register_blueprint(gov_bp)
    from app.dashboards.ngo import ngo_bp
    app.register_blueprint(ngo_bp)
    from app.site_pages import site_bp
    app.register_blueprint(site_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    return app
