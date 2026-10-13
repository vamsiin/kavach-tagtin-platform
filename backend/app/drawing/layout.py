"""Builds the RFID Tag / TIN layout sheet as a Scene.

What goes on the sheet (Annexure-H):
  lines with TIN sections in their colours (H2.17, non-KAVACH white H2.18), tags with
  their legend shape and number (H2.15, H2.21), absolute locations of tags, signals
  (with their aspects), LC gates, points / turnouts, BSLB and stop boards (H2.27), the
  station centre line (H2.28), border lines with their tags (H2.16), distances between
  tags, legend (H2.25), "not drawn to scale" (H2.26), revision and signature blocks
  (H2.24), the Tag / TIN allotment with spares (H2.23) and the title block with the
  drawing number, SIP drawing number and X.Y.Z version (H2.1, H2.2).

Layout (QFTL review, Oct 2026: no overlapping text, turnouts drawn, aspects shown):
  * The chainage axis is NOT to scale: features keep their true order, but gaps are
    compressed logarithmically, so a 5 m duplicate pair and a 3 km block section are
    both legible. True distances are written on the sheet.
  * Each line has lanes on both sides, outwards from the line: TIN band (with its
    number inside), tag symbols, signal / board symbols, the distance row (above
    only), then a label lane. Nominal tags and signals for Nominal running are above
    the line, Reverse below (signals stand on the left of the running direction).
  * Every tag / element label goes in the label lane, written vertically. Labels are
    spread apart so no two overlap, and a leader joins each to its symbol.
  * The sheet grows (A3 -> A2 -> A1 -> A0, then longer) until everything fits with
    that spacing, instead of shrinking the text.
  * Points are drawn as the diverging line from the switch toe to the line they lead
    to; a pair of points between the same two lines is drawn as one crossover.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .scene import FAINT, INK, Line, Poly, Rect, Scene, Text, colour, text_len

W, H = 420.0, 297.0          # A3 landscape, mm (the smallest sheet)
SHEETS = [("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0)]
MARGIN = 8.0
X0, X1 = 52.0, 400.0         # chainage axis on an A3 sheet (line names to the left of X0)
NAME_W = X0 - MARGIN - 4
BLOCKS_TOP = 96.0            # bottom blocks (legend, allotment, revisions, signatures, title)
TITLE_H = 20.0
BAND = 3.0                   # TIN band height
TAG = 3.2                    # tag symbol size
TAG_IN = BAND / 2 + 0.5      # tag symbols: from TAG_IN to TAG_IN + TAG, out from the line
SIG_ARM = TAG_IN + TAG + 3.4  # first signal tier: arm height out from the line
TIER = 3.4                   # next tier, when two signal heads would touch
LAMP = 1.15                  # signal lamp radius
LBL = 1.8                    # label text size
PITCH = 2.9                  # minimum distance between two vertical labels
DIM = 1.6                    # distance text size
LEADER = (150, 150, 150)
POINTS = "Points / Turnout"
LAMP_RGB = {"R": (220, 30, 30), "Y": (245, 195, 0), "YY": (245, 195, 0), "G": (0, 150, 60)}


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
    direction: str | None = None       # Nominal / Reverse (already resolved from Up / Down)
    aspects: str | None = None         # as stated; None -> default for the type
    aspects_default: bool = False      # True when `aspects` came from the type default


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
def _gap_units(a: float, b: float) -> float:
    return 4.2 + 7.0 * math.log10(1 + (b - a) / 8.0)


class Axis:
    def __init__(self, points: list[float], x0: float = X0, x1: float = X1):
        pts = sorted({round(p, 1) for p in points if p is not None})
        if not pts:
            pts = [0.0, 1.0]
        if len(pts) == 1:
            pts = [pts[0] - 1, pts[0] + 1]
        gaps = [_gap_units(a, b) for a, b in zip(pts, pts[1:])]
        self.units = sum(gaps)
        k = (x1 - x0) / self.units
        xs = [x0]
        for g in gaps:
            xs.append(xs[-1] + g * k)
        self.pts, self.xs, self.k = pts, xs, k

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
    n = max(3, int(width_mm / (0.8 * size)))
    return text if len(text) <= n else text[: n - 1] + "…"


def spread(wanted: list[float], pitch: float, lo: float, hi: float) -> list[float]:
    """Positions as close as possible to `wanted` (which must be sorted), keeping the
    order and at least `pitch` apart, inside [lo, hi] where there is room. Clusters of
    labels that would touch are merged and centred on their symbols."""
    clusters: list[list] = []          # [start, count, sum of (wanted - offset)]
    for w in wanted:
        clusters.append([w, 1, w])
        while len(clusters) > 1:
            a, b = clusters[-2], clusters[-1]
            if a[0] + a[1] * pitch <= b[0] + 1e-9:
                break
            n = a[1] + b[1]
            total = a[2] + b[2] - b[1] * a[1] * pitch      # shift b's members by a's length
            start = total / n
            clusters[-2:] = [[start, n, total]]
            # clamp to the sheet, then re-check against the cluster before
        c = clusters[-1]
        c[0] = min(max(c[0], lo), max(lo, hi - (c[1] - 1) * pitch))
    out = []
    for start, n, _ in clusters:
        out.extend(start + i * pitch for i in range(n))
    # clamping a cluster can push it into the previous one: one forward pass fixes it
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1] + pitch)
    return out


# ---------------------------------------------------------------------------
# What sits along each line, before positions are known
# ---------------------------------------------------------------------------
@dataclass
class _Label:
    m: float                  # chainage of the symbol it belongs to
    top: float                # symbol's outer edge, mm out from the line
    text: str
    rgb: tuple = INK
    bold: bool = False
    x: float = 0.0            # symbol x, set once the axis is known
    refs: list = field(default_factory=list)   # several elements on one post
    tail: str = ""

    def merge(self, ref: str, tail: str = "") -> None:
        if ref not in self.refs:
            self.refs.append(ref)
        if tail and not self.tail:
            self.tail = tail
        self.text = " / ".join(self.refs) + f"  {km(self.m)}" + (f"  {self.tail}" if self.tail else "")


@dataclass
class _Sym:                   # a signal / board drawn on a post, needs a tier
    kind: str                 # signal | shunt | board
    m: float
    side: int
    travel: int               # +1 trains run to higher km, -1 to lower
    aspects: list = field(default_factory=list)
    route: bool = False
    calling_on: bool = False
    board: str = ""
    tier: int = 0


def _side(direction: str | None) -> int:
    return -1 if (direction or "").lower().startswith("rev") else 1


def _aspect_list(text: str | None) -> tuple[list, bool]:
    t = (text or "").upper()
    route = "+RI" in t
    lamps = [p for p in t.replace("+RI", "").split("/") if p]
    return lamps, route


def _head_width(sym: _Sym) -> float:
    if sym.kind == "board":
        return 5.0
    if sym.kind == "shunt":
        return 2.6
    return 1.0 + 2 * LAMP * max(1, len([a for a in sym.aspects if a not in ("C", "SH")]))


def _tag_label(t: DTag, refs: str) -> str:
    where = (f"ABS-1 {km(t.location_m)} / ABS-2 {km(t.abs2_m)}" if t.tag_type == "A" and t.abs2_m is not None
             else km(t.location_m))
    number = f" #{t.number}" if t.number is not None and str(t.number) not in t.ref else ""
    return f"{refs}{number}  {where}"


class _LinePlan:
    """Everything along one line, by side (+1 above, -1 below)."""

    def __init__(self, track: DTrack):
        self.t = track
        self.labels = {1: [], -1: []}
        self.extra = {1: [], -1: []}   # labels that depend on the axis (TINs, borders, points)
        self.syms: list[_Sym] = []
        self.tags: list = []           # (DTag, side, refs, group)
        self.dims: list = []           # (m_a, m_b, text, row)
        self.dim_rows = 0
        self.y = 0.0
        self.x_from = self.x_to = 0.0

    def sym_top(self, side: int) -> float:
        top = TAG_IN + TAG if any(s == side for _, s, _, _ in self.tags) else BAND / 2
        for s in self.syms:
            if s.side == side:
                top = max(top, SIG_ARM + s.tier * TIER + LAMP + 0.6)
        return top

    def dim_base(self) -> float:
        return max(self.sym_top(1), TAG_IN + TAG) + 1.4

    def label0(self, side: int) -> float:
        if side == 1 and self.dims:
            return self.dim_base() + 0.8 + self.dim_rows * 2.5 + 1.6
        return self.sym_top(side) + 2.6

    def all_labels(self, side: int) -> list:
        return self.labels[side] + self.extra[side]

    def extent(self, side: int) -> float:
        labs = self.all_labels(side)
        longest = max((text_len(lb.text, LBL, lb.bold) for lb in labs), default=0)
        return self.label0(side) + longest + (1.5 if labs else 0)


def _collect(d: DrawingData, tracks: list) -> dict:
    plans = {t.id: _LinePlan(t) for t in tracks}
    other = "Reverse" if d.dn_direction == "Nominal" else "Nominal"

    # tags: one symbol per location (a co-located main + duplicate share it)
    groups: dict[str, list] = {}
    for t in d.tags:
        if t.pair_group:
            groups.setdefault(t.pair_group, []).append(t)
    for p in plans.values():
        on = sorted([t for t in d.tags if t.track_id == p.t.id], key=lambda t: t.location_m)
        drawn: list = []
        for t in on:
            mates = [g for g in groups.get(t.pair_group or "", []) if g is not t]
            if any(abs(g.location_m - t.location_m) < 0.5 and g in drawn for g in mates):
                continue
            together = [t] + [g for g in mates if abs(g.location_m - t.location_m) < 0.5]
            refs = " / ".join(g.ref for g in together)
            side = _side(t.direction)
            p.tags.append((t, side, refs, groups.get(t.pair_group or "", [])))
            p.labels[side].append(_Label(t.location_m, TAG_IN + TAG, _tag_label(t, refs),
                                         (150, 110, 0) if t.is_border else INK))
            drawn.append(t)
        # distances between consecutive tags (both directions), written above the line
        for a, b in zip(on, on[1:]):
            if abs(b.location_m - a.location_m) >= 0.5:
                p.dims.append([a.location_m, b.location_m, f"{abs(b.location_m - a.location_m):.0f} m", 0])

    # elements
    def travel_of(e: DElement, p: _LinePlan) -> str:
        dirn = (e.direction or "").strip()
        low = dirn.lower()
        if low.startswith(("dn", "down")):
            return d.dn_direction
        if low.startswith("up"):
            return other
        if low.startswith(("nom", "rev")):
            return "Reverse" if low.startswith("rev") else "Nominal"
        # not stated: the signal-foot tag at the same place, else the line's usual direction
        foot = [t for t, _, _, _ in p.tags if t.tag_type == "S" and abs(t.location_m - e.location_m) <= 3]
        if foot and foot[0].direction in ("Nominal", "Reverse"):
            return foot[0].direction
        from ..domain import expected_line_direction
        return expected_line_direction(p.t.line_type, d.dn_direction) or "Nominal"

    posts: dict = {}
    for e in sorted(d.elements, key=lambda e: e.location_m):
        p = plans.get(e.track_id)
        if p is None or e.element_type == POINTS:
            continue
        et = e.element_type
        if et == "LC Gate":
            p.labels[1].append(_Label(e.location_m, 6.0, f"{e.ref}  km {km(e.location_m)}", bold=True))
            p.syms.append(_Sym("lc", e.location_m, 1, 1))
            continue
        if et in ("Fouling Mark", "Marker Board", "Axle Counter", "Whistle Board (W/L)"):
            short = {"Fouling Mark": "FM", "Marker Board": "MB", "Axle Counter": "AC", "Whistle Board (W/L)": "W/L"}[et]
            p.labels[1].append(_Label(e.location_m, TAG_IN + 1.5, f"{short} {e.ref}  {km(e.location_m)}"))
            p.syms.append(_Sym("marker", e.location_m, 1, 1))
            continue
        travel = travel_of(e, p)
        side = _side(travel)
        tv = 1 if travel == "Nominal" else -1
        key = (p.t.id, side, round(e.location_m))
        if "BSLB" in et or "Stop Board" in et or "Berthing" in et:
            board = "BSLB" if "BSLB" in et else "STOP" if "Stop" in et else "BTE"
            sym = _Sym("board", e.location_m, side, tv, board=board)
            tail = ""
        else:
            lamps, route = _aspect_list(e.aspects)
            if e.element_type == "Calling-on Signal" or lamps == ["C"]:
                kind = "calling"
            elif e.element_type == "Shunt Signal" or lamps == ["SH"]:
                kind = "shunt"
            else:
                kind = "signal"
            sym = _Sym(kind, e.location_m, side, tv, aspects=lamps, route=route)
            tail = "" if kind == "calling" else (e.aspects or "?") + ("*" if e.aspects_default else "")
        # signals on one post (home + calling-on, or a row entered twice) share one symbol
        old = posts.get(key)
        if old is not None:
            o_sym, o_lab = old
            if sym.kind == "calling":
                o_sym.calling_on = True
            elif o_sym.kind == "calling":
                sym.calling_on = True
                o_sym.__dict__.update(sym.__dict__)
            elif o_sym.kind == "board" and sym.kind != "board":
                o_sym.__dict__.update(sym.__dict__)
            if sym.kind not in ("calling", "board") and o_lab.tail and sym.aspects and \
                    len(sym.aspects) + sym.route > len(_aspect_list(o_lab.tail.rstrip("*"))[0]):
                o_lab.tail = ""          # the fuller head's aspects win
            o_lab.merge(e.ref, tail)
            if sym.calling_on or o_sym.calling_on:
                o_sym.calling_on = True
            continue
        if sym.kind == "calling":
            sym.kind, sym.aspects, sym.calling_on = "signal", [], True
        lab = _Label(e.location_m, 0.0, "", bold=sym.kind == "signal")
        lab.merge(e.ref, tail)
        p.syms.append(sym)
        p.labels[side].append(lab)
        posts[key] = (sym, lab)
    return plans


def _assign_tiers(p: _LinePlan, ax) -> None:
    """Two heads that would touch go on different tiers (the later one further out)."""
    for side in (1, -1):
        placed: list = []                 # (x_lo, x_hi, tier)
        for s in sorted([s for s in p.syms if s.side == side and s.kind in ("signal", "shunt", "board")],
                        key=lambda s: s.m):
            x = ax(s.m)
            w = _head_width(s)
            lo, hi = (x - 0.6, x + w) if s.travel > 0 else (x - w, x + 0.6)
            if s.kind == "board":
                lo, hi = x - w / 2, x + w / 2
            tier = 0
            while any(t == tier and lo < h + 0.6 and l < hi + 0.6 for l, h, t in placed):
                tier += 1
            s.tier = tier
            placed.append((lo, hi, tier))


def _assign_dims(p: _LinePlan, ax) -> None:
    rows: list = []                         # right edge of the last text in each row
    for dm in p.dims:
        xa, xb = ax(dm[0]), ax(dm[1])
        w = text_len(dm[2], DIM) + 1.0
        cx = (xa + xb) / 2
        lo, hi = cx - w / 2, cx + w / 2
        for r, right in enumerate(rows):
            if lo >= right:
                dm[3] = r
                rows[r] = hi
                break
        else:
            dm[3] = len(rows)
            rows.append(hi)
    p.dim_rows = len(rows)


# ---------------------------------------------------------------------------
# Sheet
# ---------------------------------------------------------------------------
def build(d: DrawingData) -> Scene:
    tracks = ordered_tracks(d.tracks or [])
    if not tracks:
        s = _sheet(d, W, H)
        s.add(Text((X0 + X1) / 2, (H + BLOCKS_TOP) / 2, "No lines recorded for this station -- record its "
                   "lines (Registers tab) to draw the layout", 3.5, anchor="middle", rgb=FAINT))
        _blocks(s, d, W)
        return s
    plans = _collect(d, tracks)
    sizes = list(SHEETS)
    for i in range(12):
        if i < len(sizes):
            _, w, h = sizes[i]
        else:   # longer than A0: extend the A0 sheet
            w, h = SHEETS[-1][1] * (1 + 0.5 * (i - len(sizes) + 1)), SHEETS[-1][2]
        need_w, need_h = _measure(d, tracks, plans, w)
        if need_w <= w and need_h <= h:
            break
        if i >= len(sizes) - 1 and need_w <= w:
            h = max(h, need_h)
            break
    s = _sheet(d, w, h)
    _plan(s, d, tracks, plans, w, h)
    _blocks(s, d, w)
    return s


def _axis_points(d: DrawingData, tracks: list) -> list:
    pts = [t.start_m for t in tracks] + [t.end_m for t in tracks]
    pts += [t.location_m for t in d.tags] + [e.location_m for e in d.elements]
    pts += [n.start_m for n in d.tins] + [n.end_m for n in d.tins] + [b.location_m for b in d.borders]
    if d.centre_line_m is not None:
        pts.append(d.centre_line_m)
    return pts


def _x_range(w: float) -> tuple[float, float]:
    return X0, w - 20.0


def _measure(d: DrawingData, tracks: list, plans: dict, w: float) -> tuple[float, float]:
    """(width, height) the plan needs on a sheet `w` wide."""
    x0, x1 = _x_range(w)
    ax = Axis(_axis_points(d, tracks), x0, x1)
    need_w = w if ax.k >= 0.95 else ax.units * 0.95 + x0 + 20
    for p in plans.values():
        _assign_tiers(p, ax)
        _assign_dims(p, ax)
    order = [plans[t.id] for t in tracks]
    _axis_labels(d, plans, order, ax)
    for p in order:
        for side in (1, -1):
            n = len(p.all_labels(side))
            if n * PITCH > (x1 - x0):
                need_w = max(need_w, n * PITCH + x0 + 20)
    plan_h = order[0].extent(1) + order[-1].extent(-1)
    for a, b in zip(order, order[1:]):
        plan_h += a.extent(-1) + b.extent(1) + 4
    return need_w, plan_h + BLOCKS_TOP + 6 + 20 + TITLE_H + MARGIN


def _sheet(d: DrawingData, w: float, h: float) -> Scene:
    s = Scene(w, h, title=f"RFID Tag / TIN Layout - {d.station_name}")
    s.add(Rect(MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN, layer="FRAME", width=0.5))
    s.add(Text(w / 2, h - MARGIN - 7, f"RFID TAG / TIN LAYOUT : {d.station_name.upper()}", 5, "TITLE",
               anchor="middle", bold=True))
    s.add(Text(w / 2, h - MARGIN - 12.5, f"Stationary KAVACH ID {d.kavach_station_id}   ·   SIP drawing "
               f"{d.sip_drawing_number or '-'}   ·   Layout version {d.layout_version}", 2.6, "TITLE", anchor="middle"))
    if not d.drawn_to_scale:
        s.add(Text(w - 20, h - MARGIN - 7, "NOT DRAWN TO SCALE", 3.2, "TITLE", anchor="end", bold=True))
    return s


def _plan(s: Scene, d: DrawingData, tracks: list, plans: dict, w: float, h: float) -> None:
    x0, x1 = _x_range(w)
    ax = Axis(_axis_points(d, tracks), x0, x1)
    order = [plans[t.id] for t in tracks]
    for p in order:
        _assign_tiers(p, ax)
        _assign_dims(p, ax)

    tin_draw, turnouts = _axis_labels(d, plans, order, ax)
    for p in order:
        for side in (1, -1):
            for lb in p.all_labels(side):
                lb.x = ax(lb.m)

    # vertical positions: each line gets the room its lanes need
    top = h - MARGIN - TITLE_H
    bottom = BLOCKS_TOP + 6 + 20
    need = order[0].extent(1) + order[-1].extent(-1) + sum(
        a.extent(-1) + b.extent(1) + 4 for a, b in zip(order, order[1:]))
    spare = max(0.0, (top - bottom) - need)
    extra = min(spare / (len(order) + 1), 30.0)
    y = top - extra - order[0].extent(1)
    for i, p in enumerate(order):
        if i:
            y -= order[i - 1].extent(-1) + p.extent(1) + 4 + extra
        p.y = y
    y_of = {p.t.id: p.y for p in order}
    plan_top = order[0].y + order[0].extent(1)
    plan_bottom = order[-1].y - order[-1].extent(-1)

    # points / turnouts: the lines they join are extended to meet them
    for p in order:
        p.x_from, p.x_to = ax(min(p.t.start_m, p.t.end_m)), ax(max(p.t.start_m, p.t.end_m))
    for xa, ta, xb, tb, stub in turnouts:
        if tb is not None and stub == 0:
            pb = plans[tb]
            pb.x_from, pb.x_to = min(pb.x_from, xb), max(pb.x_to, xb)

    # centre line (H2.28)
    if d.centre_line_m is not None:
        x = ax(d.centre_line_m)
        s.add(Line(x, plan_bottom - 4, x, plan_top + 2, "CENTRE", rgb=(200, 0, 0), width=0.35, dash=True),
              Text(x, plan_bottom - 8, f"STATION CENTRE LINE  km {km(d.centre_line_m)}", 2.4, "CENTRE", (200, 0, 0),
                   anchor="middle", bold=True, halo=True))

    # neighbours at the ends
    sides: dict[bool, list] = {True: [], False: []}
    for name, side in d.neighbours:
        low = "lower" in (side or "").lower() or "reverse" in (side or "").lower()
        if name not in sides[low]:
            sides[low].append(name)
    for low, names in sides.items():
        if names:
            label = " / ".join(names)
            s.add(Text(x0 if low else x1, plan_bottom - 14, f"<< {label}" if low else f"{label} >>", 2.6, "TEXT",
                       anchor="start" if low else "end", bold=True))

    # lines, names in the left column
    for p in order:
        y = p.y
        s.add(Line(p.x_from, y, p.x_to, y, "TRACKS", width=0.5))
        if p.x_from > x0 + 2:
            s.add(Line(x0 - 1, y, p.x_from - 1.5, y, "TRACKS", rgb=(200, 200, 200), width=0.15, dash=True))
        s.add(Text(x0 - 3, y + 0.9, _fit(p.t.name + ("" if p.t.is_kavach else " (non-KAVACH)"), NAME_W, 2.8), 2.8,
                   "TRACKS", anchor="end", bold=True),
              Text(x0 - 3, y - 3.2, f"km {km(min(p.t.start_m, p.t.end_m))} - {km(max(p.t.start_m, p.t.end_m))}",
                   1.6, "TRACKS", FAINT, anchor="end"))

    # TIN bands (H2.17 / H2.18) with their number inside
    unknown = set()
    for n, p, xa, xb, inside in tin_draw:
        y = p.y
        rgb = (255, 255, 255) if n.non_kavach else colour(n.color)
        if rgb is None:
            unknown.add(n.color or "(blank)")
            rgb = (190, 190, 190)
        s.add(Rect(xa, y - BAND / 2, xb - xa, BAND, "TINS", stroke=INK, fill=rgb, width=0.15))
        if inside:
            dark = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) < 140
            s.add(Text((xa + xb) / 2, y - 0.75, inside, 1.7, "TINS", (255, 255, 255) if dark else INK,
                       anchor="middle", bold=True))
    if unknown:
        s.add(Text(x0, plan_bottom - 19, "TIN colour(s) not recognised, drawn grey: " + ", ".join(sorted(unknown)),
                   2, "TINS", (200, 0, 0)))

    # borders (H2.16)
    for b in d.borders:
        x = ax(b.location_m)
        if b.track_id in y_of:
            y = y_of[b.track_id]
            y1, y2 = y - 7.5, y + 7.5
        else:
            y1, y2 = plan_bottom - 4, plan_top
            s.add(Text(x - 0.8, y2 - 1, f"BORDER {b.tag_ref} km {km(b.location_m)}", LBL, "BORDER", (0, 90, 200),
                       angle=90, anchor="end", halo=True))
        s.add(Line(x, y1, x, y2, "BORDER", rgb=(0, 90, 200), width=0.35, dash=True))

    # turnouts
    for xa, ta, xb, tb, stub in turnouts:
        ya = y_of[ta]
        yb = y_of[tb] if tb is not None else ya + stub * 6
        s.add(Line(xa, ya, xb, yb, "POINTS", width=0.5),
              Poly(_circle(xa, ya, 0.55, 8), "POINTS", fill=INK, width=0.1))

    # elements, tags, distances, labels
    for p in order:
        for sym in p.syms:
            _draw_sym(s, sym, ax(sym.m), p.y)
        for t, side, refs, group in p.tags:
            _tag_symbol(s, t, ax(t.location_m), p.y, side, group)
        if p.dims:
            yb = p.y + p.dim_base()
            xs = sorted({ax(m) for dm in p.dims for m in dm[:2]})
            s.add(Line(xs[0], yb, xs[-1], yb, "DIMENSIONS", FAINT, 0.12))
            for x in xs:
                s.add(Line(x, yb - 0.6, x, yb + 0.6, "DIMENSIONS", FAINT, 0.12))
            for a, b, text, row in p.dims:
                s.add(Text((ax(a) + ax(b)) / 2, yb + 0.8 + row * 2.5, text, DIM, "DIMENSIONS", FAINT,
                           anchor="middle", halo=True))
        for side in (1, -1):
            _labels(s, p, side, x0, x1)

    unplaced = [t.ref for t in d.tags if t.track_id not in y_of]
    if unplaced:
        s.add(Text(x0, plan_bottom - 23, _fit("Not placed on a line, not drawn: " + ", ".join(unplaced), x1 - x0, 2),
                   2, "TEXT", (200, 0, 0)))


def _axis_labels(d: DrawingData, plans: dict, order: list, ax) -> tuple[list, list]:
    """Labels whose need depends on the axis: TIN numbers too long for their band,
    borders and points. Rebuilt on every call (the sheet size is tried several times)."""
    for p in order:
        p.extra = {1: [], -1: []}
    tin_draw = []
    for n in d.tins:
        p = plans.get(n.track_id)
        if p is None:
            continue
        xa, xb = ax(min(n.start_m, n.end_m)), ax(max(n.start_m, n.end_m))
        full = f"N-{n.tin_no}" + (" Block" if (n.section_type or "").lower() == "block" else "") \
            + f" ({'White' if n.non_kavach else n.color or '-'})"
        short = f"N-{n.tin_no}"
        if text_len(full, 1.7, True) <= xb - xa - 2:
            inside = full
        elif text_len(short, 1.7, True) <= xb - xa - 1:
            inside = short
        else:
            inside = ""
            p.extra[-1].append(_Label((n.start_m + n.end_m) / 2, BAND / 2, full, bold=True))
        tin_draw.append((n, p, xa, xb, inside))
    for b in d.borders:
        p = plans.get(b.track_id)
        if p is not None:
            p.extra[1].append(_Label(b.location_m, 8.0, f"BORDER {b.tag_ref} km {km(b.location_m)}".replace("  ", " "),
                                     (0, 90, 200)))
    return tin_draw, _turnouts(d, plans, order, ax)


def _turnouts(d: DrawingData, plans: dict, order: list, ax) -> list:
    """[(x_toe, line, x_join, line joined | None, stub)]. Points on line A leading to B
    and points on B leading to A within 250 m are one crossover; points leading to a
    loop join it at the loop's nearer end; otherwise the turnout runs 8 mm along. Points
    leading off the KAVACH lines get a short stub (stub = +1 up / -1 down)."""
    idx = {p.t.id: i for i, p in enumerate(order)}
    pts = [e for e in d.elements if e.element_type == POINTS and e.track_id in plans]
    out, used = [], set()
    for e in sorted(pts, key=lambda e: e.location_m):
        if id(e) in used:
            continue
        used.add(id(e))
        pa = plans[e.track_id]
        xa = ax(e.location_m)
        if e.to_track_id in plans:
            pb = plans[e.to_track_id]
            side = 1 if idx[pb.t.id] < idx[pa.t.id] else -1
            mate = next((q for q in pts if id(q) not in used and q.track_id == e.to_track_id
                         and q.to_track_id == e.track_id and abs(q.location_m - e.location_m) <= 250), None)
            if mate is not None:
                used.add(id(mate))
                xb = ax(mate.location_m)
                if abs(xb - xa) < 4:
                    xb = xa + 6
                out.append((xa, pa.t.id, xb, pb.t.id, None))
                _point_label(pa, e, side)
                _point_label(pb, mate, -side)
                continue
            lo, hi = min(pb.t.start_m, pb.t.end_m), max(pb.t.start_m, pb.t.end_m)
            near = lo if abs(lo - e.location_m) <= abs(hi - e.location_m) else hi
            if abs(near - e.location_m) <= 250:
                xb = ax(near)
                if abs(xb - xa) < 4:
                    xb = xa + (6 if near == lo else -6)
            else:
                xb = xa + (8 if (lo + hi) / 2 > e.location_m else -8)
            out.append((xa, pa.t.id, xb, pb.t.id, 0))
            _point_label(pa, e, side)
        else:
            sgn = 1 if idx[pa.t.id] == 0 else -1
            out.append((xa, pa.t.id, xa + 6, None, sgn))
            _point_label(pa, e, sgn, " (to siding)")
    return out


def _point_label(p: _LinePlan, e: DElement, side: int, note: str = "") -> None:
    p.extra[side].append(_Label(e.location_m, BAND / 2 + 0.5, f"{e.ref}{note}  {km(e.location_m)}", bold=True))


def _labels(s: Scene, p: _LinePlan, side: int, x0: float, x1: float) -> None:
    labs = sorted(p.all_labels(side), key=lambda lb: (lb.x, lb.m))
    if not labs:
        return
    xs = spread([lb.x for lb in labs], PITCH, x0, x1)
    l0 = p.label0(side)
    for lb, xl in zip(labs, xs):
        y_sym = p.y + side * (lb.top + 0.4)
        y_bend = p.y + side * (l0 - 1.4)
        y_lab = p.y + side * (l0 - 0.2)
        if abs(xl - lb.x) < 0.05:
            s.add(Line(lb.x, y_sym, lb.x, y_lab, "LEADERS", LEADER, 0.1))
        else:
            s.add(Line(lb.x, y_sym, lb.x, y_bend, "LEADERS", LEADER, 0.1),
                  Line(lb.x, y_bend, xl, y_lab, "LEADERS", LEADER, 0.1))
        tx = xl + LBL * 0.36          # centre the rotated text on its slot
        if side > 0:
            s.add(Text(tx, p.y + l0, lb.text, LBL, "LABELS", lb.rgb, angle=90, bold=lb.bold, halo=True))
        else:
            s.add(Text(tx, p.y - l0, lb.text, LBL, "LABELS", lb.rgb, angle=90, anchor="end", bold=lb.bold, halo=True))


def _circle(cx: float, cy: float, r: float, n: int = 12) -> list:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _draw_sym(s: Scene, sym: _Sym, x: float, y: float) -> None:
    sd, tv = sym.side, sym.travel
    if sym.kind == "lc":
        for dx in (-1.1, 1.1):
            s.add(Line(x + dx, y - 5, x + dx, y + 5, "LC", width=0.5))
        return
    if sym.kind == "marker":
        s.add(Line(x, y + BAND / 2, x, y + TAG_IN + 1.5, "MARKERS", width=0.3))
        return
    arm = SIG_ARM + sym.tier * TIER
    ya = y + sd * arm
    if sym.kind == "board":
        s.add(Line(x, y + sd * BAND / 2, x, ya - sd * 1.2, "BOARDS", width=0.35),
              Rect(x - 2.5, ya - 1.2, 5.0, 2.4, "BOARDS", fill=(255, 255, 255), width=0.3),
              Text(x, ya - 0.5, sym.board, 1.3, "BOARDS", anchor="middle", bold=True))
        return
    s.add(Line(x, y + sd * BAND / 2, x, ya, "SIGNALS", width=0.35))
    if sym.kind == "shunt":
        # position-light shunt signal: two white lamps on a diagonal
        s.add(Line(x, ya, x + tv * 0.7, ya, "SIGNALS", width=0.35),
              Poly(_circle(x + tv * 1.3, ya - 0.55, 0.55, 10), "SIGNALS", fill=(255, 255, 255), width=0.25),
              Poly(_circle(x + tv * 2.2, ya + 0.55, 0.55, 10), "SIGNALS", fill=(255, 255, 255), width=0.25))
        return
    lamps = [a for a in sym.aspects if a not in ("C", "SH")] or ["?"]
    s.add(Line(x, ya, x + tv * 0.8, ya, "SIGNALS", width=0.35))
    for i, lamp in enumerate(lamps):
        cx = x + tv * (0.8 + LAMP + i * 2 * LAMP)
        rgb = LAMP_RGB.get(lamp, (255, 255, 255))
        s.add(Poly(_circle(cx, ya, LAMP, 14), "SIGNALS", fill=rgb, width=0.2))
        letter = {"YY": "YY", "?": "?"}.get(lamp, lamp)
        s.add(Text(cx, ya - 0.45, letter, 0.95 if lamp == "YY" else 1.2, "SIGNALS",
                   INK if lamp in ("Y", "YY", "?") else (255, 255, 255), anchor="middle", bold=True))
    if sym.route:      # junction-type route indicator: a feather at 45 degrees off the post
        s.add(Line(x, ya, x - tv * 1.8, ya + sd * 1.8, "SIGNALS", width=0.45))
    if sym.calling_on:  # calling-on: miniature yellow lamp on the post below the main head
        cy = ya - sd * 1.9
        s.add(Line(x, cy, x + tv * 0.6, cy, "SIGNALS", width=0.3),
              Poly(_circle(x + tv * 1.25, cy, 0.62, 12), "SIGNALS", fill=(245, 195, 0), width=0.2),
              Text(x + tv * 1.25, cy - 0.32, "C", 0.75, "SIGNALS", anchor="middle", bold=True))


def _tag_symbol(s: Scene, t: DTag, x: float, y: float, side: int, group: list) -> None:
    base = y + TAG_IN if side > 0 else y - TAG_IN - TAG
    others = [g for g in group if g is not t]
    colocated = bool(others) and all(abs(g.location_m - t.location_m) < 0.5 for g in others)
    shape = t.legend_shape or ("Rectangle" if colocated or not others else "Triangle")
    fill = (255, 230, 120) if t.is_border else (255, 255, 255)
    if shape == "Triangle":
        # tip points to the duplicate (H2.15); with no duplicate, in the direction of travel
        ahead = (others[0].location_m > t.location_m) if others else (side > 0)
        tip = x + TAG / 2 if ahead else x - TAG / 2
        back = x - TAG / 2 if ahead else x + TAG / 2
        s.add(Poly([(back, base), (back, base + TAG), (tip, base + TAG / 2)], "TAGS", fill=fill, width=0.3))
    else:
        s.add(Rect(x - TAG / 2, base, TAG, TAG, "TAGS", fill=fill, width=0.3))
    s.add(Text(x, base + TAG / 2 - 0.8, t.tag_type, 1.6, "TAGS", anchor="middle", bold=True))


def _tag(s: Scene, t: DTag, x: float, y: float, group: list, refs: str) -> None:
    """One tag with its label next to it (used on its own, outside the sheet plan)."""
    side = _side(t.direction)
    _tag_symbol(s, t, x, y, side, group)
    s.add(Text(x + 0.7, y + side * (TAG_IN + TAG + 1), _tag_label(t, refs), LBL, "TAGS", angle=90,
               anchor="start" if side > 0 else "end"))


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


def _blocks(s: Scene, d: DrawingData, w: float = W) -> None:
    top = BLOCKS_TOP
    s.add(Line(MARGIN, top + 6, w - MARGIN, top + 6, "FRAME", width=0.4))

    # Legend (H2.25), two columns
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
    y -= 4.5
    other = "Reverse" if d.dn_direction == "Nominal" else "Nominal"
    s.add(Text(x, y, f"SIP Down = {d.dn_direction}, SIP Up = {other}", 1.8, "BLOCKS"),
          Text(x, y - 3.3, "Nominal tags & signals above the line, Reverse below", 1.8, "BLOCKS"),
          Text(x, y - 6.6, "Locations in km; distances between tags in m", 1.8, "BLOCKS"))

    # second legend column: signals, points, boards
    x2 = x + 64
    y = top - 3.2
    s.add(Text(x2, y, "Signals (head points in the running direction)", 1.8, "BLOCKS", bold=True))
    y -= 4.5
    for lamps, text in ((["R", "Y", "YY", "G"], "R red · Y yellow · YY double yellow · G green"),
                        (["G", "YY", "Y"], "Distant: no red (permissive)")):
        s.add(Line(x2, y - 1.2, x2, y + 1.2, "BLOCKS", width=0.3), Line(x2, y, x2 + 0.8, y, "BLOCKS", width=0.3))
        for i, lamp in enumerate(lamps):
            cx = x2 + 0.8 + LAMP + i * 2 * LAMP
            s.add(Poly(_circle(cx, y, LAMP, 14), "BLOCKS", fill=LAMP_RGB[lamp], width=0.2))
        s.add(Text(x2 + 12, y - 0.6, text, 1.7, "BLOCKS"))
        y -= 4
    s.add(Line(x2, y - 1.2, x2, y + 1.6, "BLOCKS", width=0.3),
          Poly(_circle(x2 + 1.3, y - 0.6, 0.62, 12), "BLOCKS", fill=(245, 195, 0), width=0.2),
          Line(x2, y + 1.6, x2 - 1.4, y + 3.0, "BLOCKS", width=0.4),
          Text(x2 + 12, y - 0.6, "C calling-on (on the post) · feather = route indicator", 1.7, "BLOCKS"))
    y -= 4
    s.add(Poly(_circle(x2 + 1.3, y - 0.5, 0.55, 10), "BLOCKS", fill=(255, 255, 255), width=0.2),
          Poly(_circle(x2 + 2.2, y + 0.6, 0.55, 10), "BLOCKS", fill=(255, 255, 255), width=0.2),
          Text(x2 + 12, y - 0.6, "SH shunt signal (position light)", 1.7, "BLOCKS"))
    y -= 4
    s.add(Text(x2, y - 0.6, "*  aspects by signal type (not stated on the SIP)", 1.7, "BLOCKS"))
    y -= 4
    s.add(Rect(x2, y - 1.4, 5, 2.4, "BLOCKS", fill=(255, 255, 255), width=0.25),
          Text(x2 + 2.5, y - 0.7, "BSLB", 1.2, "BLOCKS", anchor="middle", bold=True),
          Text(x2 + 12, y - 0.6, "BSLB / STOP board", 1.7, "BLOCKS"))
    y -= 4
    s.add(Line(x2, y - 1, x2 + 8, y - 1, "BLOCKS", width=0.4), Line(x2 + 2, y - 1, x2 + 7, y + 1.5, "BLOCKS", width=0.4),
          Poly(_circle(x2 + 2, y - 1, 0.5, 8), "BLOCKS", fill=INK, width=0.1),
          Text(x2 + 12, y - 0.6, "Points: dot at the switch toe", 1.7, "BLOCKS"))
    y -= 4
    s.add(Line(x2 + 2.9, y - 1.9, x2 + 2.9, y + 1.6, "BLOCKS", width=0.4),
          Line(x2 + 5.1, y - 1.9, x2 + 5.1, y + 1.6, "BLOCKS", width=0.4),
          Line(x2, y - 0.2, x2 + 8, y - 0.2, "BLOCKS", width=0.4),
          Text(x2 + 12, y - 0.6, "LC gate", 1.7, "BLOCKS"))

    # Allotment (H2.23)
    x = 142.0
    _heading(s, x, top, "RFID TAG / TIN ALLOTMENT")
    rows = [["Section", "Tag range", "Used", "Spare", "TIN range", "Used", "Spare"]]
    for r in d.allotment:
        rows.append([r.label, r.tag_range or "-", "-" if r.tags_used is None else r.tags_used,
                     "-" if r.tags_free is None else r.tags_free, r.tin_range or "-",
                     "-" if r.tins_used is None else r.tins_used, "-" if r.tins_free is None else r.tins_free])
    if len(rows) == 1:
        rows.append(["No allotment chart loaded", "", "", "", "", "", ""])
    yb = _table(s, x, top - 2, [28, 22, 8, 9, 22, 8, 9], rows, size=1.7)
    if d.allotment_ref:
        s.add(Text(x, yb - 3.5, _fit(f"As per {d.allotment_ref}", 106, 1.6), 1.6, "BLOCKS", FAINT))
    s.add(Text(x, yb - 7, f"Total tags on this layout: {len(d.tags)}   ·   TINs: {len({n.tin_no for n in d.tins})}",
               1.9, "BLOCKS", bold=True))

    # Revision history (H2.24) and signatures under it
    x = 252.0
    _heading(s, x, top, "REVISION HISTORY")
    rows = [["Rev", "Date", "Description"]] + [[r, dt or "-", desc] for r, dt, desc in d.revisions[-5:]]
    if len(rows) == 1:
        rows.append(["-", "-", "No revisions recorded"])
    yb = _table(s, x, top - 2, [9, 17, 54], rows, size=1.7)
    yb -= 6
    _heading(s, x, yb, "SIGNATURES")
    rows = [["", "Name", "Date"]]
    for role in ("Prepared", "Checked", "Validated", "Approved"):
        name, date = d.signatures.get(role, ("", ""))
        rows.append([role, name, date])
    _table(s, x, yb - 2, [16, 40, 24], rows, size=1.7, row_h=5.2)

    # Title block, at the right-hand edge
    x = w - MARGIN - 2 - 76
    s.add(Rect(x, MARGIN + 2, 76, top - MARGIN - 0.5, "BLOCKS", width=0.4))
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
             (f"Sheet 1 of 1  ·  {_sheet_name(w)}", 1.8, False)]
    y = top - 5
    for text, size, bold in lines:
        if text:
            s.add(Text(x + 2.5, y, _fit(text, 70, size), size, "BLOCKS", bold=bold))
        y -= size + 2.4


def _sheet_name(w: float) -> str:
    for name, sw, _ in SHEETS:
        if abs(sw - w) < 1:
            return name
    return f"{w:.0f} mm long"
