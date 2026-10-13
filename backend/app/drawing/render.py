"""Scene -> SVG / PDF / DXF. Each renderer draws exactly the same primitives."""
from __future__ import annotations

import io
import math
from xml.sax.saxutils import escape

from .scene import Line, Poly, Rect, Scene, Text

FONT = "Helvetica"


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


# ---------------------------------------------------------------------------
# SVG (in-app preview; no dependencies)
# ---------------------------------------------------------------------------
def to_svg(s: Scene) -> bytes:
    Y = lambda y: s.height - y  # noqa: E731  (flip to SVG's top-left origin)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {s.width} {s.height}" '
           f'width="{s.width}mm" height="{s.height}mm" font-family="Helvetica, Arial, sans-serif">',
           f'<title>{escape(s.title)}</title><rect width="100%" height="100%" fill="#ffffff"/>']
    for it in s.items:
        if isinstance(it, Line):
            dash = ' stroke-dasharray="2,1.2"' if it.dash else ""
            out.append(f'<line x1="{it.x1:.2f}" y1="{Y(it.y1):.2f}" x2="{it.x2:.2f}" y2="{Y(it.y2):.2f}" '
                       f'stroke="{_hex(it.rgb)}" stroke-width="{it.width}"{dash}/>')
        elif isinstance(it, Rect):
            out.append(f'<rect x="{it.x:.2f}" y="{Y(it.y + it.h):.2f}" width="{it.w:.2f}" height="{it.h:.2f}" '
                       f'fill="{_hex(it.fill) if it.fill else "none"}" '
                       f'stroke="{_hex(it.stroke) if it.stroke else "none"}" stroke-width="{it.width}"/>')
        elif isinstance(it, Poly):
            pts = " ".join(f"{x:.2f},{Y(y):.2f}" for x, y in it.points)
            tag = "polygon" if it.closed else "polyline"
            out.append(f'<{tag} points="{pts}" fill="{_hex(it.fill) if it.fill else "none"}" '
                       f'stroke="{_hex(it.stroke) if it.stroke else "none"}" stroke-width="{it.width}"/>')
        elif isinstance(it, Text):
            size = it.size * 1.38   # cap height -> font size
            rot = f' transform="rotate({-it.angle:.1f} {it.x:.2f} {Y(it.y):.2f})"' if it.angle else ""
            bold = ' font-weight="bold"' if it.bold else ""
            halo = (' stroke="#ffffff" stroke-width="0.7" stroke-linejoin="round" paint-order="stroke"'
                    if it.halo else "")
            out.append(f'<text x="{it.x:.2f}" y="{Y(it.y):.2f}" font-size="{size:.2f}" fill="{_hex(it.rgb)}" '
                       f'text-anchor="{it.anchor}"{bold}{halo}{rot}>{escape(it.text)}</text>')
    out.append("</svg>")
    return "\n".join(out).encode("utf-8")


# ---------------------------------------------------------------------------
# PDF (reportlab)
# ---------------------------------------------------------------------------
def to_pdf(s: Scene) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(s.width * mm, s.height * mm))
    c.setTitle(s.title)
    c.setAuthor("KAVACH RFID Tag/TIN Layout Platform")
    for it in s.items:
        if isinstance(it, Line):
            c.setStrokeColorRGB(*[v / 255 for v in it.rgb])
            c.setLineWidth(it.width * mm)
            c.setDash([2 * mm, 1.2 * mm] if it.dash else [])
            c.line(it.x1 * mm, it.y1 * mm, it.x2 * mm, it.y2 * mm)
        elif isinstance(it, (Rect, Poly)):
            c.setDash([])
            c.setLineWidth(it.width * mm)
            if it.stroke:
                c.setStrokeColorRGB(*[v / 255 for v in it.stroke])
            if it.fill:
                c.setFillColorRGB(*[v / 255 for v in it.fill])
            if isinstance(it, Rect):
                c.rect(it.x * mm, it.y * mm, it.w * mm, it.h * mm, stroke=1 if it.stroke else 0,
                       fill=1 if it.fill else 0)
            else:
                p = c.beginPath()
                (x0, y0), rest = it.points[0], it.points[1:]
                p.moveTo(x0 * mm, y0 * mm)
                for x, y in rest:
                    p.lineTo(x * mm, y * mm)
                if it.closed:
                    p.close()
                c.drawPath(p, stroke=1 if it.stroke else 0, fill=1 if it.fill else 0)
        elif isinstance(it, Text):
            font, size = FONT + ("-Bold" if it.bold else ""), it.size * 1.38 * mm
            c.saveState()
            c.translate(it.x * mm, it.y * mm)
            if it.angle:
                c.rotate(it.angle)
            w = c.stringWidth(it.text, font, size)
            x0 = {"middle": -w / 2, "end": -w}.get(it.anchor, 0)
            if it.halo:
                c.saveState()
                t = c.beginText(x0, 0)
                t.setFont(font, size)
                t.setTextRenderMode(1)
                c.setStrokeColorRGB(1, 1, 1)
                c.setLineWidth(0.7 * mm)
                c.setLineJoin(1)
                c.setDash([])
                t.textOut(it.text)
                c.drawText(t)
                c.restoreState()
            c.setFillColorRGB(*[v / 255 for v in it.rgb])
            c.setFont(font, size)
            c.drawString(x0, 0, it.text)
            c.restoreState()
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# DXF (ezdxf) -- one layer per primitive layer, so the sheet stays editable in AutoCAD
# ---------------------------------------------------------------------------
def to_dxf(s: Scene) -> bytes:
    import ezdxf
    from ezdxf.enums import TextEntityAlignment
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    layers = set()

    def layer(name):
        if name not in layers:
            if name not in doc.layers:
                doc.layers.add(name)
            layers.add(name)
        return name

    def attrs(it, rgb):
        a = {"layer": layer(it.layer)}
        if rgb is not None:
            a["true_color"] = ezdxf.colors.rgb2int(tuple(rgb))
        return a

    align = {"start": TextEntityAlignment.BOTTOM_LEFT, "middle": TextEntityAlignment.BOTTOM_CENTER,
             "end": TextEntityAlignment.BOTTOM_RIGHT}
    for it in s.items:
        if isinstance(it, Line):
            a = attrs(it, it.rgb)
            if it.dash:
                a["linetype"] = "DASHED"
            a["lineweight"] = max(13, int(round(it.width * 100)))
            msp.add_line((it.x1, it.y1), (it.x2, it.y2), dxfattribs=a)
        elif isinstance(it, (Rect, Poly)):
            pts = ([(it.x, it.y), (it.x + it.w, it.y), (it.x + it.w, it.y + it.h), (it.x, it.y + it.h)]
                   if isinstance(it, Rect) else it.points)
            closed = True if isinstance(it, Rect) else it.closed
            if it.fill and it.fill != (255, 255, 255):
                h = msp.add_hatch(dxfattribs=attrs(it, it.fill))
                h.paths.add_polyline_path(pts, is_closed=True)
            if it.stroke:
                msp.add_lwpolyline(pts, close=closed, dxfattribs=attrs(it, it.stroke))
        elif isinstance(it, Text):
            t = msp.add_text(it.text, height=it.size, rotation=it.angle, dxfattribs=attrs(it, it.rgb))
            t.set_placement((it.x, it.y), align=align.get(it.anchor, TextEntityAlignment.BOTTOM_LEFT))
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
