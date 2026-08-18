"""
PDF Report generation - Module 8.
"""

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch


def generate_pdf_report(alert, map_snapshot_path, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("ECO-SENTINEL Vegetation Loss Alert Report", styles["Title"]))
    story.append(Spacer(1, 12))

    rows = [
        ["Alert ID", alert["alert_id"]],
        ["Date & Time", alert["date_time"]],
        ["Latitude", f"{alert['location']['latitude']:.6f}"],
        ["Longitude", f"{alert['location']['longitude']:.6f}"],
        ["Area Lost (ha)", f"{alert['area_lost_ha']:.4f}"],
        ["Severity Level", alert["severity_level"].capitalize()],
        ["Region / Division", alert["region_division"]],
        ["Polygon ID", alert["polygon_id"]],
    ]
    table = Table(rows, colWidths=[2 * inch, 3.5 * inch])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#2E5339")),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 20))

    story.append(Paragraph("Satellite Snapshot of Affected Area", styles["Heading2"]))
    story.append(Spacer(1, 8))
    story.append(Image(map_snapshot_path, width=4 * inch, height=4 * inch))

    doc.build(story)
    return output_path
