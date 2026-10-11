
"""
PDF Report generation - Module 8.
Includes satellite acquisition metadata separately from alert generation time.
"""

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch


def generate_pdf_report(
    alert,
    map_snapshot_path,
    output_path,
    source_metadata=None,
):
    """Generate a one-page PDF evidence report for one alert."""
    source_metadata = source_metadata or {}

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.35 * inch,
        leftMargin=0.35 * inch,
        topMargin=0.25 * inch,
        bottomMargin=0.25 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CompactTitle", parent=styles["Title"],
        fontSize=13, leading=14, spaceAfter=4,
    )
    heading_style = ParagraphStyle(
        "CompactHeading", parent=styles["Heading2"],
        fontSize=9, leading=10, spaceBefore=3, spaceAfter=3,
    )

    ml_confidence = alert.get("ml_confidence")
    ml_confidence_text = (
        f"{float(ml_confidence):.4f}"
        if ml_confidence is not None else "Not available"
    )
    legality_status = alert.get("legality_status", "legal_status_unknown")

    image_id = source_metadata.get("image_id") or "Not available"
    if len(image_id) > 65:
        image_id = "…" + image_id[-64:]

    rows = [
        ["Alert ID", str(alert.get("alert_id", "Unknown"))],
        ["Alert Generated At", str(alert.get("date_time", "Unknown"))],
        ["Satellite Acquisition Date", str(
            source_metadata.get("acquisition_date", "Not available")
        )],
        ["Comparison Period", str(
            source_metadata.get("comparison_period", "2025 vs 2026-09-27")
        )],
        ["Satellite Image ID", str(image_id)],
        ["Cloud Cover (image metadata)", str(
            source_metadata.get("cloud_cover_pct", "Not available")
        )],
        ["Latitude", f"{float(alert['location']['latitude']):.6f}"],
        ["Longitude", f"{float(alert['location']['longitude']):.6f}"],
        ["Area Lost (ha)", f"{float(alert['area_lost_ha']):.4f}"],
        ["Severity Level", str(alert.get("severity_level", "unknown")).capitalize()],
        ["Region / Division", str(alert.get("region_division", "Unknown"))],
        ["Polygon ID", str(alert.get("polygon_id", "Unknown"))],
        ["ML Confidence", ml_confidence_text],
        ["Detection Method", str(alert.get("detection_class", "vegetation_loss"))],
        ["Legality Status", str(legality_status)],
        ["Final Category", str(alert.get("final_category", legality_status))],
        ["Cloud Masking", str(
            source_metadata.get("cloud_masking", "Not recorded")
        )],
    ]

    story = [
        Paragraph("ECO-SENTINEL Vegetation Loss Alert Report", title_style),
    ]

    table = Table(
        rows,
        colWidths=[2.05 * inch, 4.35 * inch],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#2E5339")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    story.extend([
        table,
        Spacer(1, 4),
        Paragraph("Satellite Snapshot of Affected Area", heading_style),
        Image(map_snapshot_path, width=1.9 * inch, height=1.9 * inch,
              hAlign="CENTER"),
    ])

    doc.build(story)
    return output_path
