"""PDF rendering for A.R.E.S. Med Earth transmission reports."""

from __future__ import annotations

from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Mapping


def _pdf_safe_text(value: str) -> str:
    """Map a few common clinical symbols to printable ASCII for built-in PDF fonts."""
    return (
        value.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2265", ">=")
        .replace("\u2264", "<=")
        .replace("\u00b0", " degrees")
        .replace("\u00b5", "u")
        .replace("\u03bc", "u")
        .replace("\u2022", "-")
    )


def render_earth_report_pdf(report: Mapping[str, Any]) -> bytes:
    """Render the report's existing text into a readable, paginated PDF attachment."""
    try:
        import reportlab
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import KeepInFrame, Paragraph, SimpleDocTemplate
    except ImportError as exc:  # Other monitoring endpoints remain available.
        raise RuntimeError(
            "PDF export requires ReportLab in the Python environment running this backend. "
            "Run: python -m pip install -r backend/requirements.txt, then restart the backend."
        ) from exc

    font_dir = Path(reportlab.__file__).parent / "fonts"
    font_faces = {
        "AresVera": font_dir / "Vera.ttf",
        "AresVera-Bold": font_dir / "VeraBd.ttf",
    }
    for font_name, font_path in font_faces.items():
        if font_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))

    report_text = str(report.get("report_text") or "").strip()
    if not report_text:
        raise ValueError("The Earth report has no report_text to render.")

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "EarthReportTitle",
        parent=styles["Title"],
        fontName="AresVera-Bold",
        fontSize=14,
        leading=17,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#102a43"),
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "EarthReportSection",
        parent=styles["Heading2"],
        fontName="AresVera-Bold",
        fontSize=8.5,
        leading=10,
        textColor=colors.HexColor("#135e83"),
        spaceBefore=5,
        spaceAfter=2,
        keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "EarthReportBody",
        parent=styles["BodyText"],
        fontName="AresVera",
        fontSize=8.2,
        leading=10.2,
        alignment=TA_LEFT,
        textColor=colors.HexColor("#202b36"),
        spaceAfter=1,
        splitLongWords=True,
    )
    bullet_style = ParagraphStyle(
        "EarthReportBullet",
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=1.5,
    )

    story = []
    title_written = False
    omitted_pdf_fields = {"decision mode", "75% gate passed", "certified abstain"}
    for raw_line in report_text.splitlines():
        line = _pdf_safe_text(raw_line).strip()
        if not line or (set(line) <= {"=", "-"}):
            continue
        field_name = line.split(":", 1)[0].strip().casefold()
        if field_name in omitted_pdf_fields:
            continue

        safe_line = escape(line)
        is_section_heading = ":" not in line and line.upper() == line and len(line) > 3
        if not title_written and ("EARTH TRANSMISSION REPORT" in line or "A.R.E.S. MED" in line):
            story.append(Paragraph(safe_line, title_style))
            title_written = True
        elif is_section_heading:
            story.append(Paragraph(safe_line, section_style))
        elif line.startswith("-"):
            story.append(Paragraph(f"&#8226; {safe_line[1:].strip()}", bullet_style))
        elif line[:1].isdigit() and ". " in line[:5]:
            story.append(Paragraph(safe_line, bullet_style))
        elif ":" in line:
            label, value = line.split(":", 1)
            story.append(Paragraph(f"<b>{escape(label.strip())}:</b>{escape(value)}", body_style))
        else:
            story.append(Paragraph(safe_line, body_style))

    output = BytesIO()
    report_id = _pdf_safe_text(str(report.get("report_id") or "A.R.E.S. Med Earth Report"))
    document = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.58 * inch,
        leftMargin=0.58 * inch,
        topMargin=0.58 * inch,
        bottomMargin=0.56 * inch,
        title=report_id,
        author="A.R.E.S. Med",
        subject="Earth transmission clinical report",
    )

    def draw_page_footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#d5dee7"))
        canvas.setLineWidth(0.5)
        canvas.line(0.68 * inch, 0.48 * inch, letter[0] - 0.68 * inch, 0.48 * inch)
        canvas.setFont("AresVera", 7.5)
        canvas.setFillColor(colors.HexColor("#607080"))
        canvas.drawString(0.68 * inch, 0.32 * inch, "A.R.E.S. Med | Earth transmission report")
        canvas.drawRightString(letter[0] - 0.68 * inch, 0.32 * inch, f"Page {doc.page}")
        canvas.restoreState()

    bounded_story = KeepInFrame(
        document.width,
        document.height,
        story,
        mode="shrink",
        hAlign="LEFT",
        vAlign="TOP",
    )
    document.build([bounded_story], onFirstPage=draw_page_footer, onLaterPages=draw_page_footer)
    return output.getvalue()
