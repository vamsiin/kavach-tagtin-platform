"""PDF renderer for app.reports.model.Report (reportlab platypus, A4)."""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak as RLPageBreak, PageTemplate,
    Paragraph, Spacer, Table as RLTable, TableStyle,
)

from . import model as m

NAVY = colors.HexColor("#1f3864")
TEAL = colors.HexColor("#0f6e56")
BORDER = colors.HexColor("#d8dde3")
ZEBRA = colors.HexColor("#f5f6f8")
TONE_BG = {"ok": colors.HexColor("#eaf7ee"), "fail": colors.HexColor("#fdecea"),
           "warn": colors.HexColor("#fdf6e3"), "info": colors.HexColor("#eef2f7")}
TONE_FG = {"ok": colors.HexColor("#1e7d3c"), "fail": colors.HexColor("#c0392b"),
           "warn": colors.HexColor("#8a6116"), "info": colors.HexColor("#1f3864")}

# The built-in Helvetica only covers WinAnsi; map the few non-Latin-1 glyphs the
# app uses so they don't render as black boxes.
_GLYPHS = {"→": "->", "←": "<-", "≤": "<=", "≥": ">=", "✓": "OK", "✗": "X", "•": "-",
           "…": "...", "×": "x"}


def _t(text: str) -> str:
    s = str(text if text is not None else "")
    for k, v in _GLYPHS.items():
        s = s.replace(k, v)
    return escape(s).replace("\n", "<br/>")


def _styles():
    ss = getSampleStyleSheet()
    base = ParagraphStyle("base", parent=ss["Normal"], fontName="Helvetica", fontSize=9,
                          leading=12, alignment=TA_LEFT)
    return {
        "base": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=colors.HexColor("#6b7280")),
        "small": ParagraphStyle("small", parent=base, fontSize=7.5, leading=9.5),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10),
        "head": ParagraphStyle("head", parent=base, fontSize=8, leading=10,
                               textColor=colors.white, fontName="Helvetica-Bold"),
        "h1": ParagraphStyle("h1", parent=base, fontName="Helvetica-Bold", fontSize=12.5,
                             leading=16, textColor=NAVY, spaceBefore=10, spaceAfter=5, keepWithNext=1),
        "h2": ParagraphStyle("h2", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
                             leading=13, textColor=NAVY, spaceBefore=7, spaceAfter=3, keepWithNext=1),
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=17,
                                leading=21, textColor=NAVY),
        "banner": ParagraphStyle("banner", parent=base, fontName="Helvetica-Bold", fontSize=9.5),
    }


def render_pdf(report: m.Report, wide: bool = False) -> bytes:
    buf = io.BytesIO()
    pagesize = landscape(A4) if wide else A4
    W, H = pagesize
    margin = 15 * mm
    st = _styles()
    avail = W - 2 * margin

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, H - 11 * mm, W, 11 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawString(margin, H - 7 * mm, f"KAVACH RFID Tag/TIN Layout  |  {report.title}")
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(W - margin, H - 7 * mm,
                               f"{report.station_name} ({report.station_code})  |  Layout {report.layout_version}")
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(margin, 8 * mm,
                          f"{report.report_id}  |  Generated {report.generated_at[:16].replace('T', ' ')} UTC "
                          f"by {report.generated_by}  |  Uncontrolled when printed")
        canvas.drawRightString(W - margin, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=pagesize, leftMargin=margin, rightMargin=margin,
                          topMargin=18 * mm, bottomMargin=16 * mm, title=report.title,
                          author=report.generated_by, subject=report.report_id)
    frame = Frame(margin, 16 * mm, avail, H - 34 * mm, id="f", leftPadding=0, rightPadding=0)
    doc.addPageTemplates([PageTemplate(id="p", frames=[frame], onPage=on_page)])

    story = [
        Paragraph(_t(report.title), st["title"]),
        Spacer(1, 2 * mm),
        _kv_table([("Station", f"{report.station_name} (KAVACH ID {report.station_code})"),
                   ("Layout version", report.layout_version),
                   ("Workflow status", report.station_status),
                   ("Report ID", report.report_id)], st, avail),
        Spacer(1, 3 * mm),
    ]
    for b in report.blocks:
        story.extend(_block(b, st, avail))
    doc.build(story)
    return buf.getvalue()


def _kv_table(rows, st, avail):
    data = [[Paragraph(f"<b>{_t(k)}</b>", st["cell"]), Paragraph(_t(v), st["cell"])] for k, v in rows]
    t = RLTable(data, colWidths=[avail * 0.28, avail * 0.72])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), ZEBRA),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def _block(b, st, avail):
    if isinstance(b, m.Heading):
        return [Paragraph(_t(b.text), st["h1" if b.level == 1 else "h2"])]
    if isinstance(b, m.Para):
        return [Paragraph(_t(b.text), st.get(b.style, st["base"])), Spacer(1, 1.5 * mm)]
    if isinstance(b, m.Banner):
        p = Paragraph(_t(b.text), ParagraphStyle("bn", parent=st["banner"], textColor=TONE_FG[b.tone]))
        t = RLTable([[p]], colWidths=[avail])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), TONE_BG[b.tone]),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6),
                               ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return [t, Spacer(1, 2 * mm)]
    if isinstance(b, m.KeyValues):
        return [_kv_table(b.rows, st, avail), Spacer(1, 2 * mm)]
    if isinstance(b, m.Bullets):
        return [Paragraph("- " + _t(i), st["base"]) for i in b.items] + [Spacer(1, 1.5 * mm)]
    if isinstance(b, m.PageBreak):
        return [RLPageBreak()]
    if isinstance(b, m.SignOff):
        data = [[Paragraph(x, st["head"]) for x in ("Role", "Name", "Date", "Signature")]]
        data += [[Paragraph(_t(r), st["cell"]), Paragraph(_t(n), st["cell"]),
                  Paragraph(_t(d), st["cell"]), ""] for r, n, d in b.rows]
        t = RLTable(data, colWidths=[avail * w for w in (0.22, 0.28, 0.2, 0.3)],
                    rowHeights=[None] + [12 * mm] * len(b.rows))
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
                               ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        return [KeepTogether([t]), Spacer(1, 2 * mm)]
    if isinstance(b, m.Table):
        if not b.rows:
            return [Paragraph(_t(b.empty_text), st["muted"]), Spacer(1, 1.5 * mm)]
        widths = b.widths or [1] * len(b.columns)
        total = sum(widths)
        col_w = [avail * w / total for w in widths]
        data = [[Paragraph(_t(c), st["head"]) for c in b.columns]]
        def cell(ci, v):
            if ci == b.status_col:
                tone = m.tone_for(v)
                if tone:
                    return Paragraph(f'<font color="#{TONE_FG[tone].hexval()[2:]}"><b>{_t(v)}</b></font>',
                                     st["cell"])
            return Paragraph(_t(v), st["cell"])
        data += [[cell(ci, v) for ci, v in enumerate(row)] for row in b.rows]
        t = RLTable(data, colWidths=col_w, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), NAVY),
                 ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
            if b.status_col is not None:
                tone = m.tone_for(b.rows[i - 1][b.status_col])
                if tone:
                    style.append(("BACKGROUND", (b.status_col, i), (b.status_col, i), TONE_BG[tone]))
        t.setStyle(TableStyle(style))
        return [t, Spacer(1, 2.5 * mm)]
    return []
