"""Builds the RFID Tag / TIN layout sheet (A3 landscape) as a Scene.

What goes on the sheet (Annexure-H):
  lines with TIN sections in their colours (H2.17, non-KAVACH white H2.18), tags with
  their legend shape and number (H2.15, H2.21), absolute locations of tags, signals,
  LC gates, points, BSLB and stop boards (H2.27), the station centre line (H2.28),
  border lines with their tags (H2.16), distances between tags, legend (H2.25),
  "not drawn to scale" (H2.26), revision and signature blocks (H2.24), the Tag / TIN
  allotment with spares (H2.23) and the title block with the drawing number, SIP
  drawing number and X.Y.Z version (H2.1, H2.2).

The chainage axis is deliberately NOT to scale: features keep their true order, but
the gap between neighbours is compressed logarithmically so that a 5 m duplicate pair
and a 3 km block section are both legible on one sheet. True distances are written
on the sheet, as on a hand-drawn layout.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .scene import FAINT, INK, Line, Poly, Rect, Scene, Text, colour

W, H = 420.0, 297.0          # A3 landscape, mm
MARGIN = 8.0
X0, X1 = 30.0, 400.0         # drawing area
Y_TOP, Y_BOTTOM = 262.0, 118.0
BAND = 2.4                   # TIN band height
TAG = 3.2                    # tag symbol size


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------
@dataclass
class DTrack:
    id: int
    name: str
    start_m: float
    end_m: float
    is_kavach: bool = True
    line_type: str = "OTHER"
    sort_order: int = 0


# Top-to-bottom order of lines on the sheet, as on the manual layouts (Aler V2.0.3):
# COMMON LOOP and DN LOOP above DN MAIN, then UP MAIN, then UP LOOP; other lines
# (sidings etc.) at the bottom. Within a line type the line's sort order decides.
LINE_ORDER = {"COMMON LOOP": 0, "DN LOOP": 1, "DN MAIN": 2, "UP MAIN": 3, "UP LOOP": 4, "OTHER": 5}


def ordered_tracks(tracks: list) -> list:
    return sorted(tracks, key=lambda t: (LINE_ORDER.get(getattr(t, "line_type", "OTHER") or "OTHER", 5),
                                         getattr(t, "sort_order", 0) or 0, t.id))


@dataclass
class DTin:
    tin_no: int
    start_m: float
    end_m: float
    track_id: int | None
    color: str | None = None
    section_type: str = "Station"
    non_kavach: bool = False


@dataclass
class DTag:
    ref: str
    tag_type: str
    location_m: float
    track_id: int | None
    number: int | None = None
    direction: str | None = None
    legend_shape: str | None = None
    pair_group: str | None = None
    is_border: bool = False
    abs2_m: float | None = None


@dataclass
class DElement:
    ref: str
    element_type: str
    location_m: float
    track_id: int | None
    to_track_id: int | None = None


@dataclass
class DBorder:
    neighbour: str
    side: str
    line_label: str
    location_m: float
    tag_ref: str = ""
    track_id: int | None = None


@dataclass
class DAllotRow:
    label: str
    tag_range: str
    tags_used: int | None
    tags_free: int | None
    tin_range: str
    tins_used: int | None
    tins_free: int | None


@dataclass
class DrawingData:
    station_name: str
    kavach_station_id: str
    sip_drawing_number: str = ""
    layout_version: str = ""
    zone: str = ""                     # "SCR - South Central Railway"
    dn_direction: str = "Nominal"
    drawn_to_scale: bool = False
    centre_line_m: float | None = None
    tracks: list = field(default_factory=list)
    tins: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    elements: list = field(default_factory=list)
    borders: list = field(default_factory=list)
    neighbours: list = field(default_factory=list)       # [(name, side)]
    revisions: list = field(default_factory=list)        # [(rev, date, description)]
    signatures: dict = field(default_factory=dict)       # role -> (name, date)
    allotment: list = field(default_factory=list)        # [DAllotRow]
    allotment_ref: str = ""
    generated_at: str = ""
    generated_by: str = ""


def km(m: float | None) -> str:
    return "-" if m is None else f"{m / 1000:.3f}"


def drawing_number(d: DrawingData) -> str:
    name = "".join(c if c.isalnum() else "_" for c in d.station_name.upper()).strip("_")
    return f"RFID_TAG_LAYOUT_{name}_{d.layout_version}"


# ---------------------------------------------------------------------------
# Chainage -> x (ordered, compressed, not to scale)
# ---------------------------------------------------------------------------
class Axis:
    def __init__(self, points: list[float], x0: float = X0, x1: float = X1):
        pts = sorted({round(p, 1) for p in points if p is not None})
        if not pts:
            pts = [0.0, 1.0]
        if len(pts) == 1:
            pts = [pts[0] - 1, pts[0] + 1]
        gaps = [4.2 + 7.0 * math.log10(1 + (b - a) / 8.0) for a, b in zip(pts, pts[1:])]
        total = sum(gaps)
        k = (x1 - x0) / total
        xs = [x0]
        for g in gaps:
            xs.append(xs[-1] + g * k)
        self.pts, self.xs = pts, xs

    def __call__(self, m: float) -> float:
        pts, xs = self.pts, self.xs
        if m <= pts[0]:
            return xs[0]
        if m >= pts[-1]:
            return xs[-1]
        lo, hi = 0, len(pts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if pts[mid] <= m:
                lo = mid
            else:
                hi = mid
        a, b = pts[lo], pts[hi]
        return xs[lo] + (xs[hi] - xs[lo]) * ((m - a) / (b - a) if b > a else 0)


def _fit(text: str, width_mm: float, size: float) -> str:
    n = max(3, int(width_mm / (0.6 * size)))
    return text if len(text) <= n else text[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Sheet
# ---------------------------------------------------------------------------
def build(d: DrawingData) -> Scene:
    s = Scene(W, H, title=f"RFID Tag / TIN Layout - {d.station_name}")
    s.add(Rect(MARGIN, MARGIN, W - 2 * MARGIN, H - 2 * MARGIN, layer="FRAME", width=0.5))
    s.add(Text(W / 2, H - MARGIN - 7, f"RFID TAG / TIN LAYOUT : {d.station_name.upper()}", 5, "TITLE",
               anchor="middle", bold=True))
    s.add(Text(W / 2, H - MARGIN - 12.5, f"Stationary KAVACH ID {d.kavach_station_id}   ·   SIP drawing "
               f"{d.sip_drawing_number or '-'}   ·   Layout version {d.layout_version}", 2.6, "TITLE", anchor="middle"))
    if not d.drawn_to_scale:
        s.add(Text(X1, H - MARGIN - 7, "NOT DRAWN TO SCALE", 3.2, "TITLE", anchor="end", bold=True))

    _plan(s, d)
    _blocks(s, d)
    return s


def _plan(s: Scene, d: DrawingData) -> None:
    tracks = ordered_tracks(d.tracks or [])
    if not tracks:
        s.add(Text((X0 + X1) / 2, (Y_TOP + Y_BOTTOM) / 2, "No lines recorded for this station -- record its "
                   "lines (Registers tab) to draw the layout", 3.5, anchor="middle", rgb=FAINT))
        return
    pts = [t.start_m for t in tracks] + [t.end_m for t in tracks]
    pts += [t.location_m for t in d.tags] + [e.location_m for e in d.elements]
    pts += [n.start_m for n in d.tins] + [n.end_m for n in d.tins] + [b.location_m for b in d.borders]
    if d.centre_line_m is not None:
        pts.append(d.centre_line_m)
    ax = Axis(pts)

    usable = Y_TOP - Y_BOTTOM - 44          # room for tag labels above the first line / below the last
    step = min(50.0, usable / (len(tracks) - 1)) if len(tracks) > 1 else 0
    first = (Y_TOP + Y_BOTTOM) / 2 + step * (len(tracks) - 1) / 2
    y_of = {t.id: first - i * step for i, t in enumerate(tracks)}

    # centre line (H2.28)
    if d.centre_line_m is not None:
        x = ax(d.centre_line_m)
        s.add(Line(x, Y_BOTTOM - 4, x, Y_TOP + 4, "CENTRE", rgb=(200, 0, 0), width=0.35, dash=True),
              Text(x, Y_BOTTOM - 8, f"STATION CENTRE LINE  km {km(d.centre_line_m)}", 2.4, "CENTRE", (200, 0, 0),
                   anchor="middle", bold=True))

    # neighbours at the ends
    sides: dict[bool, list] = {True: [], False: []}
    for name, side in d.neighbours:
        low = "lower" in (side or "").lower() or "reverse" in (side or "").lower()
        if name not in sides[low]:
            sides[low].append(name)
    for low, names in sides.items():
        if not names:
            continue
        x, anchor = (X0 - 2, "start") if low else (X1 + 2, "end")
        label = " / ".join(names)
        s.add(Text(x, Y_BOTTOM - 12, f"<< {label}" if low else f"{label} >>", 2.6, "TEXT", anchor=anchor, bold=True))

    for t in tracks:
        y = y_of[t.id]
        xa, xb = ax(t.start_m), ax(t.end_m)
        s.add(Line(xa, y, xb, y, "TRACKS", width=0.5),
              Text(xa, y + 9.5, t.name + ("" if t.is_kavach else "  (non-KAVACH)"), 2.8, "TRACKS", bold=True),
              Text(xa, y - 5.5, f"km {km(t.start_m)}", 1.8, "TRACKS", FAINT),
              Text(xb, y - 5.5, f"km {km(t.end_m)}", 1.8, "TRACKS", FAINT, anchor="end"))

    # TIN sections (H2.17 / H2.18)
    unknown = set()
    for n in d.tins:
        if n.track_id not in y_of:
            continue
        y = y_of[n.track_id]
        rgb = (255, 255, 255) if n.non_kavach else colour(n.color)
        if rgb is None:
            unknown.add(n.color or "(blank)")
            rgb = (190, 190, 190)
        xa, xb = ax(min(n.start_m, n.end_m)), ax(max(n.start_m, n.end_m))
        label = f"N-{n.tin_no}" + (" Block" if (n.section_type or "").lower() == "block" else "") \
            + f" ({'White' if n.non_kavach else n.color or '-'})"
        # full caption when it fits between the boundary tags, else just the number
        if len(label) * 0.62 * 1.9 > xb - xa - 5:
            label = f"N-{n.tin_no}"
        s.add(Rect(xa, y - BAND / 2, xb - xa, BAND, "TINS", stroke=INK, fill=rgb, width=0.15),
              Text((xa + xb) / 2, y + 2.4, label, 1.9, "TINS", anchor="middle", bold=True))
    if unknown:
        s.add(Text(X0, Y_BOTTOM - 17, "TIN colour(s) not recognised, drawn grey: " + ", ".join(sorted(unknown)),
                   2, "TINS", (200, 0, 0)))

    # border lines (H2.16)
    for b in d.borders:
        x = ax(b.location_m)
        if b.track_id in y_of:
            y = y_of[b.track_id]
            y1, y2 = y - 8, y + 8
        else:
            y1, y2 = Y_BOTTOM - 6, Y_TOP
        s.add(Line(x, y1, x, y2, "BORDER", rgb=(0, 90, 200), width=0.35, dash=True),
              Text(x - 1, y2 + 1, f"BORDER {b.tag_ref} km {km(b.location_m)}", 1.8, "BORDER", (0, 90, 200),
                   angle=90))

    # elements (H2.27)
    for e in d.elements:
        if e.track_id not in y_of:
            continue
        _element(s, e, ax(e.location_m), y_of[e.track_id], y_of.get(e.to_track_id))

    # tags (H2.15, H2.21, H2.27) with distances between consecutive tags
    groups: dict[str, list] = {}
    for t in d.tags:
        if t.pair_group:
            groups.setdefault(t.pair_group, []).append(t)
    for tid, y in y_of.items():
        on = sorted([t for t in d.tags if t.track_id == tid], key=lambda t: t.location_m)
        drawn: list = []          # one symbol per location: a co-located main + duplicate share it
        for t in on:
            mates = [g for g in groups.get(t.pair_group or "", []) if g is not t]
            if any(abs(g.location_m - t.location_m) < 0.5 and g in drawn for g in mates):
                continue
            together = [t] + [g for g in mates if abs(g.location_m - t.location_m) < 0.5]
            _tag(s, t, ax(t.location_m), y, groups.get(t.pair_group or "", []), " / ".join(g.ref for g in together))
            drawn.append(t)
        for a, b in zip(on, on[1:]):
            gap = abs(b.location_m - a.location_m)
            if gap < 0.5:
                continue
            xa, xb = ax(a.location_m), ax(b.location_m)
            s.add(Line(xa, y + 7.2, xb, y + 7.2, "DIMENSIONS", FAINT, 0.15),
                  Text((xa + xb) / 2, y + 8, f"{gap:.0f} m", 1.7, "DIMENSIONS", FAINT, anchor="middle"))

    unplaced = [t.ref for t in d.tags if t.track_id not in y_of]
    if unplaced:
        s.add(Text(X0, Y_BOTTOM - 20, _fit("Not placed on a line, not drawn: " + ", ".join(unplaced), X1 - X0, 2),
                   2, "TEXT", (200, 0, 0)))


def _element(s: Scene, e: DElement, x: float, y: float, y_to: float | None) -> None:
    t = e.element_type
    lab = f"{e.ref}  km {km(e.location_m)}"
    if t == "Points / Turnout":
        if y_to is not None:
            s.add(Line(x, y, x + 8, y_to, "POINTS", width=0.45))
        s.add(Text(x - 1.2, y - 3.5, lab, 1.8, "POINTS", angle=-90))
    elif t == "LC Gate":
        s.add(Line(x - 1.2, y - 5, x - 1.2, y + 1.8, "LC", width=0.5), Line(x + 1.2, y - 5, x + 1.2, y + 1.8, "LC", width=0.5),
              Text(x, y - 7, lab, 1.8, "LC", angle=-90))
    elif "BSLB" in t or "Stop Board" in t or "Berthing" in t:
        s.add(Line(x, y, x, y - 5, "BOARDS", width=0.35), Rect(x - 2.2, y - 6.4, 4.4, 1.6, "BOARDS", fill=(255, 255, 255)),
              Text(x + 1, y - 8, f"{'BSLB' if 'BSLB' in t else 'STOP' if 'Stop' in t else 'END'} {lab}", 1.8,
                   "BOARDS", angle=-90))
    elif t in ("Fouling Mark", "Marker Board", "Axle Counter", "Whistle Board (W/L)"):
        short = {"Fouling Mark": "FM", "Marker Board": "MB", "Axle Counter": "AC", "Whistle Board (W/L)": "W/L"}[t]
        s.add(Line(x, y - 1, x, y - 4, "MARKERS", width=0.3), Text(x + 1, y - 5, f"{short} {lab}", 1.8, "MARKERS", angle=-90))
    else:   # signals
        s.add(Line(x, y, x, y - 6, "SIGNALS", width=0.35), Line(x, y - 6, x + 3, y - 6, "SIGNALS", width=0.35),
              Poly(_circle(x + 4.2, y - 6, 1.2), "SIGNALS", fill=(255, 255, 255), width=0.3),
              Text(x + 1, y - 8.5, lab, 1.8, "SIGNALS", angle=-90))


def _circle(cx: float, cy: float, r: float, n: int = 12) -> list:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _tag(s: Scene, t: DTag, x: float, y: float, group: list, refs: str) -> None:
    above = t.direction != "Reverse"
    base = y + 1.6 if above else y - 1.6 - TAG
    others = [g for g in group if g is not t]
    colocated = bool(others) and all(abs(g.location_m - t.location_m) < 0.5 for g in others)
    shape = t.legend_shape or ("Rectangle" if colocated or not others else "Triangle")
    fill = (255, 230, 120) if t.is_border else (255, 255, 255)
    if shape == "Triangle":
        # tip points to the duplicate (H2.15); with no duplicate, in the direction of travel
        ahead = (others[0].location_m > t.location_m) if others else (t.direction != "Reverse")
        tip = x + TAG / 2 if ahead else x - TAG / 2
        back = x - TAG / 2 if ahead else x + TAG / 2
        s.add(Poly([(back, base), (back, base + TAG), (tip, base + TAG / 2)], "TAGS", fill=fill, width=0.3))
    else:
        s.add(Rect(x - TAG / 2, base, TAG, TAG, "TAGS", fill=fill, width=0.3))
    s.add(Text(x, base + TAG / 2 - 0.8, t.tag_type, 1.6, "TAGS", anchor="middle", bold=True))
    direction = f"{t.direction[:3].upper()}" if t.direction else ""
    where = (f"ABS-1 {km(t.location_m)} / ABS-2 {km(t.abs2_m)}" if t.tag_type == "A" and t.abs2_m is not None
             else km(t.location_m))
    label = f"{refs}{' #' + str(t.number) if t.number is not None and str(t.number) not in t.ref else ''}" \
            f"  {where}  {direction}"
    if above:
        s.add(Text(x + 0.7, base + TAG + 5.5, label, 1.8, "TAGS", angle=90))
    else:
        s.add(Text(x + 0.7, base - 1.2, label, 1.8, "TAGS", angle=90, anchor="end"))


# ---------------------------------------------------------------------------
# Blocks along the bottom
# ---------------------------------------------------------------------------
def _table(s: Scene, x: float, y_top: float, widths: list, rows: list, size: float = 1.9,
           row_h: float = 4.2, header: bool = True, layer: str = "BLOCKS") -> float:
    w = sum(widths)
    y = y_top
    for i, row in enumerate(rows):
        s.add(Line(x, y, x + w, y, layer, width=0.2))
        cx = x
        for cw, cell in zip(widths, row):
            s.add(Text(cx + 1, y - row_h + 1.2, _fit(str(cell), cw - 1.5, size), size, layer,
                       bold=header and i == 0))
            cx += cw
        y -= row_h
    s.add(Line(x, y, x + w, y, layer, width=0.2))
    cx = x
    for cw in [0] + widths:
        cx += cw
        s.add(Line(cx, y_top, cx, y, layer, width=0.2))
    return y


def _heading(s: Scene, x: float, y: float, text: str) -> None:
    s.add(Text(x, y + 1.2, text, 2.4, "BLOCKS", bold=True))


def _blocks(s: Scene, d: DrawingData) -> None:
    top = 96.0
    s.add(Line(MARGIN, top + 6, W - MARGIN, top + 6, "FRAME", width=0.4))

    # Legend (H2.25)
    x = MARGIN + 3
    _heading(s, x, top, "LEGEND")
    types = [("N", "Normal / inline"), ("S", "Signal foot"), ("T", "TIN discrimination / turnout"),
             ("X", "Exit"), ("D", "Dead stop"), ("G", "LC gate"), ("L", "Adjacent line info"), ("A", "Adjustment")]
    y = top - 5
    for code, text in types:
        s.add(Rect(x, y - 0.4, 2.6, 2.6, "BLOCKS", fill=(255, 255, 255), width=0.2),
              Text(x + 1.3, y + 0.35, code, 1.5, "BLOCKS", anchor="middle", bold=True),
              Text(x + 4, y + 0.3, text, 1.8, "BLOCKS"))
        y -= 4
    s.add(Rect(x, y - 0.4, 2.6, 2.6, "BLOCKS", fill=(255, 255, 255), width=0.2),
          Text(x + 4, y + 0.3, "Main & duplicate co-located", 1.8, "BLOCKS"))
    y -= 4
    s.add(Poly([(x, y - 0.4), (x, y + 2.2), (x + 2.6, y + 0.9)], "BLOCKS", fill=(255, 255, 255), width=0.2),
          Text(x + 4, y + 0.3, "Not co-located; tip towards duplicate", 1.8, "BLOCKS"))
    y -= 4
    s.add(Rect(x, y - 0.4, 2.6, 2.6, "BLOCKS", fill=(255, 230, 120), width=0.2),
          Text(x + 4, y + 0.3, "Border tag", 1.8, "BLOCKS"))
    y -= 4
    s.add(Rect(x, y, 6, 1.6, "BLOCKS", fill=(255, 255, 255), width=0.2),
          Text(x + 8, y + 0.2, "Non-KAVACH territory (white)", 1.8, "BLOCKS"))
    y -= 4
    other = "Reverse" if d.dn_direction == "Nominal" else "Nominal"
    s.add(Text(x, y, f"SIP Down = {d.dn_direction}, SIP Up = {other}", 1.8, "BLOCKS"),
          Text(x, y - 3.5, "Nominal tags above the line, Reverse below", 1.8, "BLOCKS"),
          Text(x, y - 7, "Locations in km", 1.8, "BLOCKS"))

    # Allotment (H2.23)
    x = 75.0
    _heading(s, x, top, "RFID TAG / TIN ALLOTMENT")
    rows = [["Section", "Tag range", "Used", "Spare", "TIN range", "Used", "Spare"]]
    for r in d.allotment:
        rows.append([r.label, r.tag_range or "-", "-" if r.tags_used is None else r.tags_used,
                     "-" if r.tags_free is None else r.tags_free, r.tin_range or "-",
                     "-" if r.tins_used is None else r.tins_used, "-" if r.tins_free is None else r.tins_free])
    if len(rows) == 1:
        rows.append(["No allotment chart loaded", "", "", "", "", "", ""])
    yb = _table(s, x, top - 2, [30, 26, 9, 10, 24, 9, 10], rows)
    if d.allotment_ref:
        s.add(Text(x, yb - 3.5, _fit(f"As per {d.allotment_ref}", 118, 1.7), 1.7, "BLOCKS", FAINT))
    s.add(Text(x, yb - 7, f"Total tags on this layout: {len(d.tags)}   ·   TINs: {len({n.tin_no for n in d.tins})}",
               1.9, "BLOCKS", bold=True))

    # Revision history (H2.24)
    x = 198.0
    _heading(s, x, top, "REVISION HISTORY")
    rows = [["Rev", "Date", "Description"]] + [[r, dt or "-", desc] for r, dt, desc in d.revisions[-8:]]
    if len(rows) == 1:
        rows.append(["-", "-", "No revisions recorded"])
    _table(s, x, top - 2, [10, 18, 55], rows)

    # Signatures (H2.24)
    x = 285.0
    _heading(s, x, top, "SIGNATURES")
    rows = [["", "Name", "Date"]]
    for role in ("Prepared", "Checked", "Validated", "Approved"):
        name, date = d.signatures.get(role, ("", ""))
        rows.append([role, name, date])
    _table(s, x, top - 2, [15, 22, 16], rows, row_h=7)

    # Title block
    x = 342.0
    s.add(Rect(x, MARGIN + 2, W - MARGIN - 2 - x, top - MARGIN - 0.5, "BLOCKS", width=0.4))
    lines = [("RFID TAG / TIN LAYOUT", 3.0, True), (d.station_name.upper(), 3.4, True),
             (f"KAVACH station ID  {d.kavach_station_id}", 2.0, False),
             (f"SIP drawing  {d.sip_drawing_number or '-'}", 2.0, False),
             (f"Version (X.Y.Z)  {d.layout_version}", 2.0, False),
             (f"Zone  {d.zone or '-'}", 2.0, False),
             ("", 1.0, False),
             ("Drawing no.", 1.8, False), (drawing_number(d), 2.0, True),
             ("", 1.0, False),
             ("NOT DRAWN TO SCALE" if not d.drawn_to_scale else "Drawn to scale", 2.2, True),
             ("Ref: RDSO/SPN/196/2020 Annexure-H (Amdt-5)", 1.6, False),
             (f"Generated {d.generated_at[:16].replace('T', ' ')} by {d.generated_by}", 1.6, False),
             ("Sheet 1 of 1", 1.8, False)]
    y = top - 5
    for text, size, bold in lines:
        if text:
            s.add(Text(x + 2.5, y, _fit(text, W - MARGIN - x - 6, size), size, "BLOCKS", bold=bold))
        y -= size + 2.4
