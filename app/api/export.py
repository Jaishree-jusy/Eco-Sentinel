import csv
import io
import json
from pathlib import Path

from flask import Blueprint, request, send_file, jsonify

from app.database.queries import get_alerts
from app.database.schema import get_connection


export_api = Blueprint("export_api", __name__)


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

# Known operational ML GeoJSON
OPERATIONAL_GEOJSON = (
    DATA_DIR
    / "supervised"
    / "deforestation_polygons_ml_2023_2025_filtered_1000m2.geojson"
)


def csv_response(rows, filename):
    output = io.StringIO()

    if not rows:
        writer = csv.writer(output)
        writer.writerow(["No data"])
    else:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(
            output,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    data = io.BytesIO(output.getvalue().encode("utf-8"))

    return send_file(
        data,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


def simple_pdf(title, rows):
    """
    Creates a simple text-based PDF using ReportLab.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        return None

    buffer = io.BytesIO()

    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, title)

    y -= 30
    pdf.setFont("Helvetica", 8)

    if not rows:
        pdf.drawString(40, y, "No records found.")
    else:
        # Print a compact representation of each record.
        for row in rows:
            text = " | ".join(
                f"{key}: {value}"
                for key, value in row.items()
            )

            # Keep long rows from overflowing horizontally.
            text = text[:180]

            pdf.drawString(40, y, text)
            y -= 12

            if y < 40:
                pdf.showPage()
                pdf.setFont("Helvetica", 8)
                y = height - 40

    pdf.save()
    buffer.seek(0)

    return buffer


def get_blockchain_rows():
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            block_index,
            alert_id,
            content_hash,
            previous_block_hash,
            block_hash,
            timestamp
        FROM blockchain_blocks
        ORDER BY block_index
        """
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_evidence_rows():
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            e.alert_id,
            a.polygon_id,
            a.date_time,
            a.latitude,
            a.longitude,
            a.area_lost_ha,
            a.severity_level,
            a.region_division,
            e.evidence_dir,
            e.map_snapshot,
            e.geojson,
            e.pdf_report,
            e.metadata
        FROM evidence e
        JOIN alerts a
            ON a.alert_id = e.alert_id
        ORDER BY e.alert_id
        """
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


@export_api.route("/api/reports/export", methods=["POST"])
def export_report():
    payload = request.get_json(silent=True) or {}

    export_type = payload.get("type")
    export_format = str(payload.get("format", "")).upper()

    # ---------------------------------------------------------
    # OPERATIONAL POLYGONS
    # ---------------------------------------------------------
    if export_type == "polygons-operational":

        if not OPERATIONAL_GEOJSON.exists():
            return jsonify({
                "error": "Operational GeoJSON file not found."
            }), 404

        if export_format == "GEOJSON":
            return send_file(
                OPERATIONAL_GEOJSON,
                mimetype="application/geo+json",
                as_attachment=True,
                download_name="operational_polygons.geojson",
            )

        if export_format == "CSV":
            with open(
                OPERATIONAL_GEOJSON,
                "r",
                encoding="utf-8",
            ) as f:
                geojson = json.load(f)

            rows = []

            for feature in geojson.get("features", []):
                properties = feature.get("properties") or {}

                row = dict(properties)

                row["geometry"] = json.dumps(
                    feature.get("geometry"),
                    separators=(",", ":"),
                )

                rows.append(row)

            return csv_response(
                rows,
                "operational_polygons.csv",
            )

    # ---------------------------------------------------------
    # RAW POLYGONS
    # ---------------------------------------------------------
    if export_type == "polygons-raw":
        return jsonify({
            "error": (
                "Raw polygon export is not configured yet. "
                "The source file for the 136,054 raw polygons "
                "has not been identified."
            )
        }), 501

    # ---------------------------------------------------------
    # ALERT REGISTER
    # ---------------------------------------------------------
    if export_type == "alerts":

        alerts = get_alerts("inside_forest")

        rows = []

        for alert in alerts:
            row = dict(alert)

            if isinstance(row.get("location"), dict):
                location = row.pop("location")
                row["latitude"] = location.get("latitude")
                row["longitude"] = location.get("longitude")

            if isinstance(row.get("geometry"), dict):
                row["geometry"] = json.dumps(
                    row["geometry"],
                    separators=(",", ":"),
                )

            rows.append(row)

        if export_format == "CSV":
            return csv_response(
                rows,
                "alert_register.csv",
            )

        if export_format == "PDF":
            pdf = simple_pdf(
                "ECO-SENTINEL Alert Register",
                rows,
            )

            if pdf is None:
                return jsonify({
                    "error": "ReportLab is not installed."
                }), 500

            return send_file(
                pdf,
                mimetype="application/pdf",
                as_attachment=True,
                download_name="alert_register.pdf",
            )

    # ---------------------------------------------------------
    # EVIDENCE INDEX
    # ---------------------------------------------------------
    if export_type == "evidence":

        rows = get_evidence_rows()

        if export_format == "CSV":
            return csv_response(
                rows,
                "evidence_package_index.csv",
            )

    # ---------------------------------------------------------
    # BLOCKCHAIN
    # ---------------------------------------------------------
    if export_type == "blockchain":

        rows = get_blockchain_rows()

        if export_format == "CSV":
            return csv_response(
                rows,
                "forest_loss_blockchain_records.csv",
            )

        if export_format == "PDF":
            pdf = simple_pdf(
                "ECO-SENTINEL Forest-Loss Blockchain Records",
                rows,
            )

            if pdf is None:
                return jsonify({
                    "error": "ReportLab is not installed."
                }), 500

            return send_file(
                pdf,
                mimetype="application/pdf",
                as_attachment=True,
                download_name="forest_loss_blockchain_records.pdf",
            )

    return jsonify({
        "error": "Unsupported export type or format."
    }), 400