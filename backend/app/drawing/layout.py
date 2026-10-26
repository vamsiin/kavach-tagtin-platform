"""Builds the RFID Tag / TIN layout sheet as a Scene, in the style of the approved
manual layouts (Aler V2.0.3, RDSO / SCR).

What goes on the sheet (Annexure-H):
  lines drawn as bands in their TIN colours with the TIN boundaries marked (H2.17,
  non-KAVACH white H2.18) and the TIN number in a red box beside the band; tags ON
  their line with their legend shape and letter (H2.15, H2.21), each with its tag
  number in a blue box and its absolute location stacked under it (H2.27); turnouts
  as bands joining the two lines, coloured by the TIN at each end and split at the
  turnout (T) tag, with the A-end and B-end ABS; signals with their aspects, shunt
  signals, boards, LC gates with class and location; the station centre line
  (H2.28); border lines (H2.16); the reference distances (signal to the tag in rear,
  gate tag to LC gate, L / D tags); legend (H2.25), "not drawn to scale" (H2.26),
  revision and signature blocks (H2.24), the Tag / TIN allotment with allotted and
  spare ranges per section (H2.23) and the title block (H2.1, H2.2).

Layout rules (QFTL observations, Oct 2026):
  * Nothing is written on a line: every label sits in a lane beside its line, and a
    label never covers a line, a turnout or another label. Where labels would
    touch they move to the next row out, with a leader back to their tag.
  * Signals stand on the left of the running direction (Nominal above the line,
    Reverse below); tag labels go on the other side.
  * The chainage axis is NOT to scale (features keep their order, gaps are
    compressed); the sheet grows until everything fits rather than shrinking text.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .scene import FAINT, INK, Line, Poly, Rect, Scene, Text, colour, text_len

W, H = 420.0, 297.0          # A3 landscape, mm (the smallest sheet)
SHEETS = [("A3", 420.0, 297.0), ("A2", 594.0, 420.0), ("A1", 841.0, 594.0), ("A0", 1189.0, 841.0)]
MARGIN = 8.0
X0, X1 = 30.0, 400.0         # chainage axis on an A3 sheet (line names are written on the lines)
NAME_W = X0 - MARGIN - 4
BLOCKS_TOP = 96.0            # bottom blocks (legend, allotment, revisions, signatures, title)
TITLE_H = 20.0
BAND = 2.6                   # line band (TIN colour)
TAG = 3.4                    # tag symbol, drawn on the line
LAMP = 1.15                  # signal lamp radius
ARM = 6.0                    # first signal tier: arm height out from the line
TIER = 6.2                   # next tier out, when two signal heads would touch
LBL = 1.8                    # label text size
ROW_GAP = 1.0
BLUE = (0, 60, 200)
RED = (210, 0, 0)
LEADER = (140, 140, 140)
POINTS = "Points / Turnout"
LAMP_RGB = {"R": (220, 30, 30), "Y": (245, 195, 0), "YY": (245, 195, 0), "G": (0, 150, 60)}
GREY = (190, 190, 190)
UNIT_MM = 1.25               # wanted mm per axis unit (labels are written across, so need room)


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
    linked_ref: str | None = None      # element the tag is placed for (a turnout tag -> its points)


@dataclass
class DElement:
    ref: str
    element_type: str
    location_m: float                  # points: the A-end
    track_id: int | None
    to_track_id: int | None = None
    direction: str | None = None       # Nominal / Reverse / Up / Down as entered
    aspects: str | None = None         # as stated, or the default for the type
    aspects_default: bool = False      # True when `aspects` came from the type default
    b_end_m: float | None = None       # points: B-end, on to_track
    lc_class: str | None = None
    lc_manning: str | None = None


@dataclass
class DTower:
    ref: str
    location_m: float
    owner: str = ""          # "" = this station
    side: str = ""


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
    station_id: str = ""
    tags_allotted: str = ""            # numbers used on this layout, compacted ("775-798, 800, 802")
    tags_spare: str = ""
    tins_allotted: str = ""
    tins_spare: str = ""
    border_tags: str = ""


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
    towers: list = field(default_factory=list)           # [DTower]
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
    """Positions as close as possible to `wanted` (sorted), keeping the order and at
    least `pitch` apart, inside [lo, hi] where there is room."""
    clusters: list[list] = []          # [start, count, sum of (wanted - offset)]
    for w in wanted:
        clusters.append([w, 1, w])
        while len(clusters) > 1:
            a, b = clusters[-2], clusters[-1]
            if a[0] + a[1] * pitch <= b[0] + 1e-9:
                break
            n = a[1] + b[1]
            total = a[2] + b[2] - b[1] * a[1] * pitch
            clusters[-2:] = [[total / n, n, total]]
        c = clusters[-1]
        c[0] = min(max(c[0], lo), max(lo, hi - (c[1] - 1) * pitch))
    out = []
    for start, n, _ in clusters:
        out.extend(start + i * pitch for i in range(n))
    for i in range(1, len(out)):
        out[i] = max(out[i], out[i - 1] + pitch)
    return out


def _circle(cx: float, cy: float, r: float, n: int = 12) -> list:
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]


def _travel(direction: str | None, dn_direction: str) -> str | None:
    """'Down' / 'DN' / 'Up' / 'Nominal' / 'Reverse' / 'Nominal (DN)' -> Nominal | Reverse."""
    low = (direction or "").strip().lower()
    if low.startswith(("nom",)):
        return "Nominal"
    if low.startswith("rev"):
        return "Reverse"
    other = "Reverse" if dn_direction == "Nominal" else "Nominal"
    if low.startswith(("dn", "down")):
        return dn_direction
    if low.startswith("up"):
        return other
    return None


def _sig_side(travel: str | None) -> int:
    """Signals stand on the left of the running direction: Nominal (to higher km)
    above the line, Reverse below."""
    return -1 if travel == "Reverse" else 1


def _aspect_list(text: str | None) -> tuple[list, bool]:
    t = (text or "").upper()
    route = "+RI" in t
    lamps = [p for p in t.replace("+RI", "").split("/") if p]
    return lamps, route


# ---------------------------------------------------------------------------
# Labels: blocks of text in a lane beside a line, packed into rows
# ---------------------------------------------------------------------------
@dataclass
class _Lab:
    x: float                   # anchor (symbol) x
    lines: list                # [(text, size, rgb, bold, boxed)] nearest-the-line first
    anchor_off: float = 1.4    # where the leader starts, mm out from the line centre
    px: float = 0.0            # placed centre x
    row: int = 0
    off: float = 0.0           # placed: distance from line centre to the label's inner edge

    @property
    def w(self) -> float:
        return max(text_len(t, sz, b) + (1.6 if box else 0) for t, sz, _, b, box in self.lines) + 0.6 + \
            (7.0 if getattr(self, "arrow", 0) else 0)

    @property
    def h(self) -> float:
        return sum(sz + (1.7 if box else 1.0) for _, sz, _, _, box in self.lines)


def _tag_lab(x: float, ref: str, where: list[str], rgb=BLUE) -> _Lab:
    lines = [(ref, LBL, rgb, False, True)] + [(w, LBL, INK, False, False) for w in where]
    return _Lab(x, lines)


class _Lane:
    """One side of one line: rows of labels outward from `start` (mm from the line)."""

    def __init__(self):
        self.labs: list[_Lab] = []
        self.obstacles: list = []      # (x_lo, x_hi, off_lo, off_hi): turnouts crossing this lane
        self.start = 0.0
        self.rows: list[float] = []    # height of each row

    def pack(self, x_lo: float, x_hi: float) -> None:
        """Place labels: each at its own x in the first row where it fits; otherwise
        shifted a little; otherwise the next row out. A label in an outer row keeps a
        clear path for its leader through the inner rows."""
        placed: list[_Lab] = []
        self.rows = []
        row_h = 0.0
        for lb in sorted(self.labs, key=lambda q: (bool(getattr(q, 'arrow', 0)), q.x)):
            w = lb.w
            done = False
            # a line's name may slide along its line to find room; tag labels stay near their tag
            shifts = ([i * 3.0 for i in range(60)] if getattr(lb, "arrow", 0)
                      else (0, -1.5, 1.5, -3, 3, -4.5, 4.5, -6, 6, -9, 9, -12, 12))
            for row in range(12):
                while len(self.rows) <= row:
                    self.rows.append(0.0)
                for shift in shifts:
                    cx = min(max(lb.x + shift, x_lo + w / 2), x_hi - w / 2)
                    if self._fits(cx, w, row, lb, placed):
                        lb.px, lb.row = cx, row
                        self.rows[row] = max(self.rows[row], lb.h)
                        placed.append(lb)
                        done = True
                        break
                if done:
                    break
            if not done:
                lb.px, lb.row = lb.x, len(self.rows)
                self.rows.append(lb.h)
                placed.append(lb)
        del row_h

    def _row_off(self, row: int) -> tuple[float, float]:
        off = self.start + sum(h + ROW_GAP for h in self.rows[:row] if h > 0)     # empty rows take no room
        return off, off + (self.rows[row] if row < len(self.rows) else 6.0)

    def _fits(self, cx: float, w: float, row: int, lb: _Lab, placed: list) -> bool:
        lo, hi = cx - w / 2 - 0.6, cx + w / 2 + 0.6
        o_lo, o_hi = self._row_off(row)
        o_hi = max(o_hi, o_lo + lb.h)
        for q in placed:
            qlo, qhi = q.px - q.w / 2, q.px + q.w / 2
            if q.row == row and qlo < hi and lo < qhi:
                return False
            if q.row > row and lo < q.x < hi:                      # would sit on q's leader
                return False
        for x_lo, x_hi, f_lo, f_hi in self.obstacles:
            if x_lo < hi and lo < x_hi and f_lo < o_hi and o_lo < f_hi:
                return False
        return True

    def depth(self) -> float:
        if not self.labs:
            return 0.0
        return sum(h + ROW_GAP for h in self.rows if h > 0)

    def place_offsets(self) -> None:
        for lb in self.labs:
            lb.off = self._row_off(lb.row)[0]


# ---------------------------------------------------------------------------
# Everything along one line
# ---------------------------------------------------------------------------
@dataclass
class _Sig:
    kind: str                 # signal | shunt | board
    m: float
    side: int
    travel: int               # +1 trains run to higher km, -1 to lower
    names: list = field(default_factory=list)     # main signal name(s)
    calling: list = field(default_factory=list)   # calling-on name(s) on the same post
    aspects: list = field(default_factory=list)
    route: bool = False
    board: str = ""
    default: bool = False
    tier: int = 0
    x: float = 0.0

    def head_w(self) -> float:
        if self.kind == "board":
            return 7.0 if self.board == "BSLB" else 6.0
        if self.kind == "shunt":
            return 3.6
        n = max(1, len(self.aspects))
        return 1.0 + (1.7 * len(self.calling)) + 2 * LAMP * n + (1.4 if self.route else 0)

    def extent(self) -> tuple[float, float]:
        """x range the head and its name take."""
        w = self.head_w()
        name_w = text_len(" ".join(self.calling + self.names) + ("*" if self.default else ""), LBL, True)
        w = max(w, name_w * 0.7)
        if self.kind == "board":
            return self.x - w / 2, self.x + w / 2 + 2
        return (self.x - 0.8, self.x + w + 0.8) if self.travel > 0 else (self.x - w - 0.8, self.x + 0.8)

    def top(self) -> float:
        """Outer edge, mm from the line centre."""
        return ARM + self.tier * TIER + LAMP + 0.6 + LBL + 1.0


@dataclass
class _Dim:
    a: float
    b: float
    side: int
    row: int = 0


class _LinePlan:
    def __init__(self, track: DTrack):
        self.t = track
        self.lanes = {1: _Lane(), -1: _Lane()}
        self.sigs: list[_Sig] = []
        self.dims: list[_Dim] = []
        self.dim_rows = {1: 0, -1: 0}
        self.tags: list = []            # (DTag, refs, colocated_mates, group)
        self.y = 0.0
        self.x_from = self.x_to = 0.0
        self.lc_top = 0.0               # room above the line for an LC gate caption (top line only)

    def sig_top(self, side: int) -> float:
        top = BAND / 2 + (TAG / 2 if self.tags else 0)
        for s in self.sigs:
            if s.side == side:
                top = max(top, s.top())
        return top + 0.8

    def dim_off(self, side: int, row: int) -> float:
        return self.sig_top(side) + 1.6 + row * 3.4

    def lane_start(self, side: int) -> float:
        return self.sig_top(side) + (self.dim_rows[side] * 3.4 + 1.6 if self.dim_rows[side] else 0) + 0.6

    def extent(self, side: int) -> float:
        return max(self.lane_start(side) + self.lanes[side].depth(), 6.0) + (self.lc_top if side > 0 else 0)


# ---------------------------------------------------------------------------
# Collecting what goes where (positions in chainage; x comes from the axis)
# ---------------------------------------------------------------------------
def tin_doubt(tins: list, t_tag_m: list) -> dict:
    """How doubtful each TIN row is as *the line's own* TIN, for when two rows overlap
    on one line (higher = less likely; the likelier one is drawn on top):
      +2  an end of it is at a turnout (T) tag -- it describes a turnout piece
      +1  the same TIN number also runs on another line (it is that line's TIN)
    Turnouts take their colours from the lines' TINs, so turnout pieces entered as
    TIN rows on a loop must not repaint the loop (e.g. N-171 over N-186 on COMMON LOOP)."""
    lines_of: dict = {}
    for n in tins:
        lines_of.setdefault(n.tin_no, set()).add(n.track_id)
    out = {}
    for n in tins:
        dbt = 0
        if any(abs(n.start_m - m) <= 2 or abs(n.end_m - m) <= 2 for m in t_tag_m):
            dbt += 2
        if len(lines_of[n.tin_no]) > 1:
            dbt += 1
        out[id(n)] = dbt
    return out


def _doubt(d: DrawingData) -> dict:
    if getattr(d, "_doubt", None) is None:
        d._doubt = tin_doubt(d.tins, [t.location_m for t in d.tags if t.tag_type == "T"])
    return d._doubt


def _tin_rank(d: DrawingData, n) -> tuple:
    return (_doubt(d).get(id(n), 0), abs(n.end_m - n.start_m))


PIECE = 3     # doubt at which a TIN row is taken as a turnout piece and not drawn on the line


def _is_piece(d: DrawingData, n) -> bool:
    """Ends at a turnout tag AND is another line's TIN: a turnout piece entered as a
    TIN row on this line. The turnout itself already shows that colour."""
    return _doubt(d).get(id(n), 0) >= PIECE


def _tin_at(d: DrawingData, track_id: int, m: float):
    cands = [n for n in d.tins if n.track_id == track_id and
             min(n.start_m, n.end_m) - 1 <= m <= max(n.start_m, n.end_m) + 1]
    real = [n for n in cands if not _is_piece(d, n)] or cands
    return min(real, key=lambda n: _tin_rank(d, n), default=None)


def _visible(d: DrawingData, n, lo: float, hi: float) -> float:
    """Length of [lo, hi] of row n not covered by a likelier TIN row on its line."""
    better = sorted((max(lo, min(o.start_m, o.end_m)), min(hi, max(o.start_m, o.end_m))) for o in d.tins
                    if o is not n and o.track_id == n.track_id and o.tin_no != n.tin_no
                    and _tin_rank(d, o) < _tin_rank(d, n))
    covered, cur = 0.0, lo
    for a, b in better:
        if b <= cur:
            continue
        a = max(a, cur)
        if a < b:
            covered += b - a
            cur = b
    return (hi - lo) - covered


def _tin_rgb(n) -> tuple:
    if n is None:
        return GREY
    if n.non_kavach:
        return (255, 255, 255)
    return colour(n.color) or GREY


class _Turnout:
    def __init__(self, e: DElement, ta: int, tb: int | None, a_m: float, b_m: float, b_given: bool):
        self.e, self.ta, self.tb, self.a_m, self.b_m, self.b_given = e, ta, tb, a_m, b_m, b_given
        self.tag: DTag | None = None
        self.stub = 0
        self.xa = self.xb = self.ya = self.yb = 0.0


def _turnouts(d: DrawingData, plans: dict, order: list) -> list[_Turnout]:
    """Points with their A-end (on their line) and B-end (on the line they lead to).
    Without a stated B-end: the facing points of a crossover on the other line, else
    the nearer end of a loop, else 60 m along."""
    pts = [e for e in d.elements if e.element_type == POINTS and e.track_id in plans]
    out, used = [], set()
    for e in sorted(pts, key=lambda e: e.location_m):
        if id(e) in used:
            continue
        used.add(id(e))
        if e.to_track_id in plans:
            if e.b_end_m is not None:
                out.append(_Turnout(e, e.track_id, e.to_track_id, e.location_m, e.b_end_m, True))
                continue
            mate = next((q for q in pts if id(q) not in used and q.track_id == e.to_track_id
                         and q.to_track_id == e.track_id and abs(q.location_m - e.location_m) <= 250), None)
            if mate is not None:
                used.add(id(mate))
                to = _Turnout(e, e.track_id, e.to_track_id, e.location_m, mate.location_m, True)
                to.mate = mate
                out.append(to)
                continue
            pb = plans[e.to_track_id].t
            lo, hi = min(pb.start_m, pb.end_m), max(pb.start_m, pb.end_m)
            near = lo if abs(lo - e.location_m) <= abs(hi - e.location_m) else hi
            b = near if abs(near - e.location_m) <= 250 else e.location_m + (60 if (lo + hi) / 2 > e.location_m else -60)
            out.append(_Turnout(e, e.track_id, e.to_track_id, e.location_m, b, False))
        else:
            to = _Turnout(e, e.track_id, None, e.location_m, e.location_m + 40, False)
            idx = [p.t.id for p in order].index(e.track_id)
            to.stub = 1 if idx == 0 else -1
            out.append(to)
    # turnout (T) tags: the one placed for (linked to) the points first; else a T tag
    # whose chainage lies between the turnout's A-end and B-end -- preferably on one of
    # its two lines, but on any line if that is the only one (a T tag is often entered
    # against the loop it leads to).
    for to in out:
        to.tag = next((t for t in d.tags if t.tag_type == "T" and t.linked_ref
                       and t.linked_ref in (to.e.ref, getattr(to, "mate", to.e).ref)), None)
    claimed = {id(to.tag) for to in out if to.tag is not None}
    for to in sorted([o for o in out if o.tag is None and o.tb is not None], key=lambda o: abs(o.b_m - o.a_m)):
        lo, hi = min(to.a_m, to.b_m) - 5, max(to.a_m, to.b_m) + 5
        cands = [t for t in d.tags if t.tag_type == "T" and id(t) not in claimed and not t.linked_ref
                 and lo <= t.location_m <= hi]
        if cands:
            mid = (to.a_m + to.b_m) / 2
            to.tag = min(cands, key=lambda t: (t.track_id not in (to.ta, to.tb), abs(t.location_m - mid)))
            claimed.add(id(to.tag))
    return out


def _collect(d: DrawingData, tracks: list) -> tuple[dict, list]:
    plans = {t.id: _LinePlan(t) for t in tracks}
    order = [plans[t.id] for t in tracks]
    turnouts = _turnouts(d, plans, order)
    on_turnout = {id(to.tag) for to in turnouts if to.tag is not None}

    # tags on their line: one symbol per location (a co-located main + duplicate share it)
    groups: dict[str, list] = {}
    for t in d.tags:
        if t.pair_group:
            groups.setdefault(t.pair_group, []).append(t)
    for p in order:
        on = sorted([t for t in d.tags if t.track_id == p.t.id and id(t) not in on_turnout],
                    key=lambda t: t.location_m)
        drawn: list = []
        for t in on:
            mates = [g for g in groups.get(t.pair_group or "", []) if g is not t]
            if any(abs(g.location_m - t.location_m) < 0.5 and g in drawn for g in mates):
                continue
            together = [t] + [g for g in mates if abs(g.location_m - t.location_m) < 0.5]
            p.tags.append((t, " / ".join(g.ref for g in together), groups.get(t.pair_group or "", [])))
            drawn.append(t)

    # signals, shunt signals and boards on posts -- one copy of a signal entered on two lines
    from ..rules.layout_rules import duplicate_elements
    dups = duplicate_elements([(id(e), e.ref, e.element_type, e.location_m, e.track_id) for e in d.elements],
                              [(t.ref, t.location_m, t.track_id) for t in d.tags if t.tag_type == "S"],
                              {t.id: t.line_type for t in tracks})
    extra_names: dict = {}       # names only on a dropped copy (SH8 of "S5/SH8") go to the kept one
    from ..rules.layout_rules import _ref_parts
    for e in d.elements:
        if id(e) in dups:
            kept = dups[id(e)][0]
            missing = [x for x in e.ref.replace(" ", "").split("/") if x and x.upper() not in _ref_parts(kept[1])]
            extra_names.setdefault(kept[0], []).extend(missing)
    posts: dict = {}
    for e in sorted(d.elements, key=lambda e: e.location_m):
        if id(e) in dups:
            continue
        p = plans.get(e.track_id)
        if p is None or e.element_type in (POINTS, "LC Gate", "Fouling Mark", "Marker Board", "Axle Counter",
                                           "Whistle Board (W/L)"):
            continue
        trav = _travel(e.direction, d.dn_direction)
        if trav is None:
            foot = [t for t, _, _ in p.tags if t.tag_type == "S" and abs(t.location_m - e.location_m) <= 3]
            trav = _travel(foot[0].direction, d.dn_direction) if foot else None
        if trav is None:
            from ..domain import expected_line_direction
            trav = expected_line_direction(p.t.line_type, d.dn_direction) or "Nominal"
        side, tv = _sig_side(trav), (1 if trav == "Nominal" else -1)
        et = e.element_type
        key = (p.t.id, side, round(e.location_m))
        lamps, route = _aspect_list(e.aspects)
        if "BSLB" in et or "Stop Board" in et or "Berthing" in et:
            board = "BSLB" if "BSLB" in et else "SB" if "Stop" in et else "BTE"
            sig = _Sig("board", e.location_m, side, tv, names=[e.ref], board=board)
        elif et == "Calling-on Signal" or lamps == ["C"]:
            sig = _Sig("signal", e.location_m, side, tv, calling=[e.ref])
        elif et == "Shunt Signal" or lamps == ["SH"]:
            sig = _Sig("shunt", e.location_m, side, tv, names=[e.ref])
        else:
            sig = _Sig("signal", e.location_m, side, tv, names=[e.ref], aspects=lamps, route=route,
                       default=e.aspects_default)
        for nm in extra_names.get(id(e), []):
            if nm not in sig.names and nm not in sig.calling:
                sig.names.append(nm)
        old = posts.get(key)
        if old is None:
            posts[key] = sig
            p.sigs.append(sig)
            continue
        # a second element on the same post: combine (home + calling-on, or a row entered twice)
        if sig.kind == "board" or (old.kind == "signal" and sig.kind == "shunt"):
            if sig.kind == "shunt":       # a shunt on a main signal post: keep it, as a second symbol
                p.sigs.append(sig)
            continue
        if old.kind in ("board", "shunt") and sig.kind == "signal":
            sig.calling += old.calling
            old.__dict__.update(sig.__dict__)
            continue
        old.calling += [c for c in sig.calling if c not in old.calling]
        if sig.aspects and (len(sig.aspects) + sig.route > len(old.aspects) + old.route):
            old.aspects, old.route, old.default = sig.aspects, sig.route, sig.default
        for n in sig.names:
            if n not in old.names and not any(n == f"{a}/{b}" for a in old.names for b in old.calling + old.names):
                # "S1/S1A" next to "S1" and "S1A" adds nothing
                parts = n.replace(" ", "").split("/")
                if not all(any(q.replace(" ", "") == pp for q in old.names + old.calling) for pp in parts):
                    old.names.append(n)
    return plans, turnouts


def _dims(d: DrawingData, plans: dict) -> None:
    """Reference distances only (QFTL obs. 8): a signal-foot (S) tag to the tag in its
    rear, a gate (G) tag to its LC gate, an adjacent-line (L) or dead-stop (D) tag
    to the nearest signal-foot tag."""
    lcs = [e for e in d.elements if e.element_type == "LC Gate"]
    for p in plans.values():
        tags = sorted([t for t, _, _ in p.tags], key=lambda t: t.location_m)
        seen = set()

        def add(a, b, side):
            k = (round(min(a, b)), round(max(a, b)))
            if abs(b - a) >= 1 and k not in seen:
                seen.add(k)
                p.dims.append(_Dim(min(a, b), max(a, b), side))
        for i, t in enumerate(tags):
            trav = _travel(t.direction, d.dn_direction) or "Nominal"
            side = _sig_side(trav)
            bslb = any(sg.kind == "board" and sg.board == "BSLB" and abs(sg.m - t.location_m) <= 3 for sg in p.sigs)
            if t.tag_type == "S" and not bslb:
                rear = tags[i - 1] if trav == "Nominal" and i > 0 else (tags[i + 1] if trav == "Reverse" and
                                                                         i + 1 < len(tags) else None)
                if rear is not None and abs(rear.location_m - t.location_m) <= 1000:
                    add(rear.location_m, t.location_m, side)
            elif t.tag_type == "G" and lcs:
                lc = min(lcs, key=lambda e: abs(e.location_m - t.location_m))
                if abs(lc.location_m - t.location_m) <= 2000:
                    add(t.location_m, lc.location_m, side)
            elif t.tag_type in ("L", "D"):
                s_tags = [q for q in tags if q.tag_type == "S"]
                if s_tags:
                    q = min(s_tags, key=lambda q: abs(q.location_m - t.location_m))
                    if abs(q.location_m - t.location_m) <= 600:
                        add(q.location_m, t.location_m, side)


# ---------------------------------------------------------------------------
# Sheet
# ---------------------------------------------------------------------------
def build(d: DrawingData) -> Scene:
    d._doubt = None
    tracks = ordered_tracks(d.tracks or [])
    if not tracks:
        w = max(W, _blocks_width(d) + 2 * MARGIN)
        s = _sheet(d, w, H)
        s.add(Text((X0 + w - 20) / 2, (H + BLOCKS_TOP) / 2, "No lines recorded for this station -- record its "
                   "lines (Registers tab) to draw the layout", 3.5, anchor="middle", rgb=FAINT))
        _blocks(s, d, w)
        return s
    plans, turnouts = _collect(d, tracks)
    _dims(d, plans)
    order = [plans[t.id] for t in tracks]

    # sheet width: the axis at UNIT_MM per unit, and room for the blocks
    probe = Axis(_axis_points(d, tracks, turnouts))
    need_w = max(probe.units * UNIT_MM + X0 + 20 + 2 * END_W, _blocks_width(d) + 2 * MARGIN, W)
    w = need_w
    for _ in range(2):
        need_h = _arrange(d, order, turnouts, w, measure=True)
        w, h = _pick_sheet(need_w, need_h)
    _arrange(d, order, turnouts, w, measure=False, h=h)
    s = _sheet(d, w, h)
    _draw(s, d, order, plans, turnouts, w, h)
    _blocks(s, d, w)
    return s


def _pick_sheet(need_w: float, need_h: float) -> tuple[float, float]:
    for _, sw, sh in SHEETS:
        if need_w <= sw and need_h <= sh and sh <= max(need_h * 1.7, 297):
            return sw, sh
    return math.ceil(max(need_w, W) / 10) * 10, math.ceil(max(need_h, H) / 10) * 10


def _axis_points(d: DrawingData, tracks: list, turnouts: list) -> list:
    pts = [t.start_m for t in tracks] + [t.end_m for t in tracks]
    pts += [t.location_m for t in d.tags] + [e.location_m for e in d.elements]
    pts += [n.start_m for n in d.tins] + [n.end_m for n in d.tins] + [b.location_m for b in d.borders]
    pts += [to.b_m for to in turnouts] + [tw.location_m for tw in d.towers]
    if d.centre_line_m is not None:
        pts.append(d.centre_line_m)
    return pts


END_W = 48.0               # each end of the plan: main lines run on, adjacent station named


def _x_range(w: float, ends: bool = True) -> tuple[float, float]:
    return (X0 + END_W, w - 20.0 - END_W) if ends else (X0, w - 20.0)


def _arrange(d: DrawingData, order: list, turnouts: list, w: float, measure: bool, h: float = 0.0) -> float:
    """Positions everything for a sheet `w` wide; returns the height it needs. With
    measure=False, also sets the y of each line on a sheet `h` high."""
    x0, x1 = _x_range(w)
    tracks = [p.t for p in order]
    ax = Axis(_axis_points(d, tracks, turnouts), x0, x1)
    d._ax = ax
    idx = {p.t.id: i for i, p in enumerate(order)}
    plans = {p.t.id: p for p in order}

    # signal tiers: two heads (with their names) that would touch go on different tiers
    for p in order:
        for side in (1, -1):
            placed = []
            for sg in sorted([s for s in p.sigs if s.side == side], key=lambda s: s.m):
                sg.x = ax(sg.m)
                lo, hi = sg.extent()
                tier = 0
                while any(t == tier and lo < h2 + 1.0 and l2 < hi + 1.0 for l2, h2, t in placed):
                    tier += 1
                sg.tier = tier
                placed.append((lo, hi, tier))
        # reference distances: rows so their captions don't touch
        for side in (1, -1):
            ends: list = []
            for dm in sorted([q for q in p.dims if q.side == side], key=lambda q: q.a):
                xa, xb = ax(dm.a), ax(dm.b)
                for r, right in enumerate(ends):
                    if xa > right + 1.0:
                        dm.row, ends[r] = r, xb
                        break
                else:
                    dm.row = len(ends)
                    ends.append(xb)
            p.dim_rows[side] = len(ends)

    # labels
    for p in order:
        for side in (1, -1):
            p.lanes[side].labs = []
            p.lanes[side].obstacles = []
        for t, refs, group in p.tags:
            trav = _travel(t.direction, d.dn_direction) or "Nominal"
            side = -_sig_side(trav)                # tag labels opposite their signals
            if t.tag_type == "A" and t.abs2_m is not None:
                where = [f"ABS-1 {km(t.location_m)}", f"ABS-2 {km(t.abs2_m)}"]
            else:
                where = [km(t.location_m)]
            num = f" #{t.number}" if t.number is not None and str(t.number) not in refs else ""
            lb = _tag_lab(ax(t.location_m), refs + num, where, (170, 110, 0) if t.is_border else BLUE)
            lb.anchor_off = TAG / 2
            p.lanes[side].labs.append(lb)
        # TIN numbers in a red box beside the band (never on it), once per TIN per line
        spans: dict = {}
        for n in d.tins:
            if n.track_id != p.t.id:
                continue
            lo, hi = _clip(n, p.t)
            if hi - lo < 0.5:
                continue
            vis = _visible(d, n, lo, hi)
            if _is_piece(d, n) or (vis < 0.3 * (hi - lo) and vis < 30):
                continue                   # hidden under the line's own TIN: don't label it
            a, b = spans.get(n.tin_no, (lo, hi))
            spans[n.tin_no] = (min(a, lo), max(b, hi))
        for no, (lo, hi) in spans.items():
            lb = _Lab((ax(lo) + ax(hi)) / 2, [(f"N-{no}", 2.1, RED, False, True)], BAND / 2)
            p.lanes[1].labs.append(lb)
        # signal names are drawn with the head; LC gates get their caption at the top
    for b in d.borders:
        p = plans.get(b.track_id)
        if p is not None:
            side, texts_ = _comm_texts(d, b)
            lb = _Lab(ax(b.location_m), [(f"{texts_[0]}      |      {texts_[1]}", 1.7, INK, False, False)],
                      _border_box_top(p, b, side))
            lb.comm = texts_
            p.lanes[side].labs.append(lb)
    # turnout ends: points name and the A-end / B-end ABS beside each end
    for to in turnouts:
        pa = plans[to.ta]
        if to.tb is not None:
            pb = plans[to.tb]
            sa = 1 if idx[to.tb] < idx[to.ta] else -1
            pa.lanes[sa].labs.append(_Lab(ax(to.a_m), [(to.e.ref, LBL, INK, True, False),
                                                       (f"A {km(to.a_m)}", 1.6, INK, False, False)], BAND / 2))
            mate = getattr(to, "mate", None)
            bname = mate.ref if mate is not None else to.e.ref
            pb.lanes[-sa].labs.append(_Lab(ax(to.b_m), [(bname, LBL, INK, True, False),
                                                        (("B " if to.b_given else "B ~") + km(to.b_m), 1.6,
                                                         INK if to.b_given else FAINT, False, False)], BAND / 2))
        else:
            pa.lanes[to.stub].labs.append(_Lab(ax(to.a_m), [(to.e.ref + " (siding)", LBL, INK, True, False),
                                                            (f"A {km(to.a_m)}", 1.6, INK, False, False)], BAND / 2))
    # LC gate caption beside the topmost line it crosses (QFTL obs. 3)
    for e in [e for e in d.elements if e.element_type == "LC Gate"]:
        crossed = _lc_crossed(e, order)
        lines = [(t, 2.0 if i == 0 else 1.8, (0, 0, 140), i == 0, False) for i, t in enumerate(_lc_caption(e))]
        lines.reverse()                     # above the line: the title on top
        crossed[0].lanes[1].labs.append(_Lab(ax(e.location_m), lines, 6.0))
    order[0].lc_top = TOWER_H if d.towers else 0.0
    # each line's name (with its running direction) at its start, beside the band
    from ..domain import expected_line_direction
    for p in order:
        nm = p.t.name + ("" if p.t.is_kavach else " (non-KAVACH)")
        w = text_len(nm, 2.4, True) + 8
        lb = _Lab(ax(min(p.t.start_m, p.t.end_m)) + w / 2 + 4, [(nm, 2.4, INK, True, False)], BAND / 2)
        lb.arrow = {"Nominal": 1, "Reverse": -1}.get(expected_line_direction(p.t.line_type, d.dn_direction) or "", 0)
        p.lanes[1].labs.append(lb)

    # pack labels once without turnouts in the way, to size the gaps between lines
    for p in order:
        for side in (1, -1):
            ln = p.lanes[side]
            ln.start = p.lane_start(side)
            ln.pack(x0, x1)
            ln.place_offsets()
    gaps = [a.extent(-1) + b.extent(1) + 3 for a, b in zip(order, order[1:])]
    gaps = [max(g, 22.0) for g in gaps]
    top_room = order[0].extent(1) + 9.0          # + the running-direction legend
    bottom_room = order[-1].extent(-1)
    need_plan = top_room + sum(gaps) + bottom_room
    need_h = need_plan + BLOCKS_TOP + 6 + 22 + TITLE_H + MARGIN + 6
    if measure:
        return need_h

    # y of each line
    top = h - MARGIN - TITLE_H - 4
    bottom = BLOCKS_TOP + 6 + 22
    spare = max(0.0, (top - bottom) - need_plan)
    extra = min(spare / (len(order) + 1), 4.0)          # keep the lines close, as on the manual layouts
    y = top - extra - top_room
    for i, p in enumerate(order):
        if i:
            y -= gaps[i - 1] + extra
        p.y = y
    # turnout geometry, then pack again with the turnouts as obstacles
    for p in order:
        p.x_from, p.x_to = ax(min(p.t.start_m, p.t.end_m)), ax(max(p.t.start_m, p.t.end_m))
    for to in turnouts:
        pa = plans[to.ta]
        to.xa, to.ya = ax(to.a_m), pa.y
        if to.tb is not None:
            pb = plans[to.tb]
            to.xb, to.yb = ax(to.b_m), pb.y
            if abs(to.xb - to.xa) < 6:
                to.xb = to.xa + (6 if to.b_m >= to.a_m else -6)
            pb.x_from, pb.x_to = min(pb.x_from, to.xb), max(pb.x_to, to.xb)
        else:
            to.xb, to.yb = to.xa + 8, pa.y + to.stub * 8
        pa.x_from, pa.x_to = min(pa.x_from, to.xa), max(pa.x_to, to.xa)
        to.path = _turnout_path(to)
    for p in order:
        for side in (1, -1):
            ln = p.lanes[side]
            for to in turnouts:
                (xa, ya), (xb, yb) = to.path[1], to.path[2]
                for _ in [0]:
                    # where the turnout band passes through this lane, as an obstacle
                    lo_y, hi_y = sorted((ya, yb))
                    for f0 in range(0, 60, 2):
                        yy = p.y + side * (ln.start + f0)
                        if lo_y <= yy <= hi_y and hi_y > lo_y:
                            xx = xa + (xb - xa) * (yy - ya) / (yb - ya)
                            ln.obstacles.append((xx - 2.2, xx + 2.2, ln.start + f0 - 1, ln.start + f0 + 3))
                    if to.tag is not None:
                        # the T tag's caption sits beside the band, mid-way
                        pass
            ln.pack(x0, x1)
            ln.place_offsets()
    return need_h


def _clip(n: DTin, t: DTrack) -> tuple[float, float]:
    lo, hi = min(n.start_m, n.end_m), max(n.start_m, n.end_m)
    tlo, thi = min(t.start_m, t.end_m), max(t.start_m, t.end_m)
    return max(lo, tlo), min(hi, thi)


def _station_id(d: DrawingData) -> str:
    sid = (d.kavach_station_id or "").strip()
    return sid.zfill(5) if sid.isdigit() else sid


def _sheet(d: DrawingData, w: float, h: float) -> Scene:
    """Frame and the heading as on the manual layouts: station name, station ID and
    the absolute location of the station (centre line)."""
    s = Scene(w, h, title=f"RFID Tag / TIN Layout - {d.station_name}")
    s.add(Rect(MARGIN, MARGIN, w - 2 * MARGIN, h - 2 * MARGIN, layer="FRAME", width=0.5))
    name = d.station_name.upper()
    nw = text_len(name, 6.0, False)
    y = h - MARGIN - 9
    s.add(Text(w / 2, y, name, 6.0, "TITLE", anchor="middle"),
          Line(w / 2 - nw / 2 * 0.85, y - 1.6, w / 2 + nw / 2 * 0.85, y - 1.6, "TITLE", width=0.35),
          Text(w / 2, y - 5.6, f"STATION ID-{_station_id(d)}", 2.6, "TITLE", anchor="middle"))
    if d.centre_line_m is not None:
        s.add(Text(w / 2, y - 9.6, f"ABSOLUTE LOCATION: {km(d.centre_line_m)}", 2.6, "TITLE", anchor="middle"))
    return s


def _draw(s: Scene, d: DrawingData, order: list, plans: dict, turnouts: list, w: float, h: float) -> None:
    ax = d._ax
    x0, x1 = _x_range(w)
    y_of = {p.t.id: p.y for p in order}
    plan_top = order[0].y + order[0].extent(1)
    plan_bottom = order[-1].y - order[-1].extent(-1)

    # centre line (H2.28)
    if d.centre_line_m is not None:
        x = ax(d.centre_line_m)
        s.add(Line(x, plan_bottom - 4, x, plan_top + 2, "CENTRE", rgb=(200, 0, 0), width=0.3),
              Text(x, plan_top + 3.2, km(d.centre_line_m), 2.6, "CENTRE", (200, 0, 0), anchor="middle"))

    # running directions, as on the manual layouts: "<- UP / DOWN ->", "<- REVERSE / NOMINAL ->"
    up_left = d.dn_direction == "Nominal"        # DN runs to higher km (left to right)
    for xc in (x0 + 22, x1 - 22):
        for i, (a, b) in enumerate((("UP", "DOWN") if up_left else ("DOWN", "UP"), ("REVERSE", "NOMINAL"))):
            yy = plan_top + 4 - i * 4.2
            txt = f"{a} / {b}"
            hw = text_len(txt, 2.0) / 2
            s.add(Text(xc, yy - 0.7, txt, 2.0, "TEXT", anchor="middle"),
                  Line(xc - hw - 1, yy, xc - hw - 7, yy, "TEXT", width=0.25),
                  Poly([(xc - hw - 7.5, yy), (xc - hw - 5.9, yy + 0.6), (xc - hw - 5.9, yy - 0.6)], "TEXT",
                       fill=INK, width=0.05),
                  Line(xc + hw + 1, yy, xc + hw + 7, yy, "TEXT", width=0.25),
                  Poly([(xc + hw + 7.5, yy), (xc + hw + 5.9, yy + 0.6), (xc + hw + 5.9, yy - 0.6)], "TEXT",
                       fill=INK, width=0.05))

    # main lines run on to the sheet edge at both ends; the adjacent stations named there
    _line_ends(s, d, order, w)

    # turnouts first: the line bands are drawn over their ends
    for to in turnouts:
        _turnout(s, d, to, plans)

    # lines as bands in their TIN colours, TIN boundaries marked
    unknown = set()
    for p in order:
        y = p.y
        s.add(Rect(p.x_from, y - BAND / 2, p.x_to - p.x_from, BAND, "TRACKS", stroke=INK,
                   fill=(255, 255, 255), width=0.2))
        bounds = set()
        # least likely first, so the line's own TIN ends up on top where rows overlap
        tins = sorted([n for n in d.tins if n.track_id == p.t.id and not _is_piece(d, n)],
                      key=lambda n: tuple(-v for v in _tin_rank(d, n)))
        for n in tins:
            lo, hi = _clip(n, p.t)
            if hi - lo < 0.5:
                continue
            rgb = (255, 255, 255) if n.non_kavach else colour(n.color)
            if rgb is None:
                unknown.add(n.color or "(blank)")
                rgb = GREY
            xa, xb = ax(lo), ax(hi)
            if abs(lo - min(p.t.start_m, p.t.end_m)) < 1:
                xa = p.x_from
            if abs(hi - max(p.t.start_m, p.t.end_m)) < 1:
                xb = p.x_to
            s.add(Rect(xa, y - BAND / 2, xb - xa, BAND, "TINS", stroke=None, fill=rgb))
            bounds.update({round(xa, 2), round(xb, 2)})
        s.add(Rect(p.x_from, y - BAND / 2, p.x_to - p.x_from, BAND, "TRACKS", stroke=INK, fill=None, width=0.2))
        for bx in sorted(bounds):
            if p.x_from + 0.5 < bx < p.x_to - 0.5:
                s.add(Line(bx, y - BAND / 2 - 1.0, bx, y + BAND / 2 + 1.0, "TINS", width=0.45))
    if unknown:
        s.add(Text(x0, plan_bottom - 19, "TIN colour(s) not recognised, drawn grey: " + ", ".join(sorted(unknown)),
                   2, "TINS", (200, 0, 0)))

    # T tags on the turnouts (over the line bands)
    for to in turnouts:
        _turnout_tag(s, to)

    # borders (H2.16): a red box round the border tag and its signal, and the
    # "COMM. EXIT FOR ... <- | -> COMM. ENTRY FOR ..." note, as on the manual layouts
    for b in d.borders:
        x = ax(b.location_m)
        if b.track_id in y_of:
            p = plans[b.track_id]
            side, _ = _comm_texts(d, b)
            top = _border_box_top(p, b, side)
            sg = next((g for g in p.sigs if g.side == side and abs(g.m - b.location_m) <= 3), None)
            lo, hi = x - TAG / 2 - 1.2, x + TAG / 2 + 1.2
            if sg is not None:
                a, c = sg.extent()
                lo, hi = min(lo, a - 0.6), max(hi, c + 0.6)
            y = p.y
            y0, y1 = y - side * (BAND / 2 + 2.2), y + side * top
            s.add(Rect(lo, min(y0, y1), hi - lo, abs(y1 - y0), "BORDER", stroke=RED, fill=None, width=0.35))
        else:
            s.add(Line(x, plan_bottom - 4, x, plan_top, "BORDER", rgb=(0, 90, 200), width=0.35, dash=True),
                  Text(x - 0.8, plan_top - 1, f"BORDER {b.tag_ref} km {km(b.location_m)}", LBL, "BORDER",
                       (0, 90, 200), angle=90, anchor="end"))

    # LC gates: across the lines, with class / gate no. / manning and location
    _lc_gates(s, d, order, plan_top)
    # Stationary KAVACH towers (input 5), along the top
    _towers(s, d, order[0].y + order[0].extent(1) - TOWER_H + 1.0, x0, x1)

    # signals, tags, distances, labels
    for p in order:
        for sg in p.sigs:
            _signal(s, sg, p.y)
        for t, refs, group in p.tags:
            _tag_symbol(s, t, ax(t.location_m), p.y, group, d.dn_direction)
        for dm in p.dims:
            _dim(s, ax(dm.a), ax(dm.b), p.y, dm.side, p.dim_off(dm.side, dm.row), abs(dm.b - dm.a))
    for p in order:
        for side in (1, -1):
            _leaders(s, p, side)
    for p in order:
        for side in (1, -1):
            _labels(s, p, side)

    unplaced = [t.ref for t in d.tags if t.track_id not in y_of]
    if unplaced:
        s.add(Text(x0, plan_bottom - 23, _fit("Not placed on a line, not drawn: " + ", ".join(unplaced), x1 - x0, 2),
                   2, "TEXT", (200, 0, 0)))


def _comm_texts(d: DrawingData, b: DBorder) -> tuple[int, tuple[str, str]]:
    """(side of the line, (left text, right text)) for a border: a train crossing it
    leaves one station's KAVACH and enters the other's."""
    # the border tag: by its ref, else the border tag on that line at the border; the
    # border's "tag" is sometimes the border signal's name -- then the signal's direction
    tag = next((t for t in d.tags if t.ref == b.tag_ref), None) or min(
        [t for t in d.tags if t.is_border and t.track_id == b.track_id and abs(t.location_m - b.location_m) <= 10],
        key=lambda t: abs(t.location_m - b.location_m), default=None)
    trav = _travel(tag.direction, d.dn_direction) if tag is not None else None
    if trav is None:
        el = next((e for e in d.elements if e.ref == b.tag_ref), None)
        trav = _travel(el.direction, d.dn_direction) if el is not None else None
    trav = trav or "Nominal"
    low = "lower" in (b.side or "").lower() or "reverse" in (b.side or "").lower()
    left, right = (b.neighbour, d.station_name) if low else (d.station_name, b.neighbour)
    if trav == "Nominal":            # running left to right
        txt = (f"COMM. EXIT FOR {left}", f"COMM. ENTRY FOR {right}")
    else:
        txt = (f"COMM. ENTRY FOR {left}", f"COMM. EXIT FOR {right}")
    return _sig_side(trav), (txt[0].upper(), txt[1].upper())


def _border_box_top(p, b: DBorder, side: int) -> float:
    sg = next((g for g in p.sigs if g.side == side and abs(g.m - b.location_m) <= 3), None)
    return (sg.top() if sg is not None else TAG / 2 + 2.0) + 0.6


def _line_ends(s: Scene, d: DrawingData, order: list, w: float) -> None:
    """As on the manual layouts, the main lines run on past the station's last feature
    to the edge of the plan (in the colour of their end TIN), and the adjacent station
    on each side is named between them."""
    ax = d._ax
    x0, x1 = _x_range(w)
    e0, e1 = X0 + 2, w - 22.0
    mains = [p for p in order if p.t.line_type in ("DN MAIN", "UP MAIN")] or order[:1]
    for p in mains:
        lo_m, hi_m = min(p.t.start_m, p.t.end_m), max(p.t.start_m, p.t.end_m)
        for xa, xb, m in ((e0, p.x_from, lo_m), (p.x_to, e1, hi_m)):
            if xb - xa < 1:
                continue
            rgb = _tin_rgb(_tin_at(d, p.t.id, m))
            s.add(Rect(xa, p.y - BAND / 2, xb - xa, BAND, "TRACKS", stroke=INK, fill=rgb, width=0.2))
    sides: dict[bool, list] = {True: [], False: []}
    for name, side in d.neighbours:
        low = "lower" in (side or "").lower() or "reverse" in (side or "").lower()
        if name not in sides[low]:
            sides[low].append(name)
    ys = sorted(p.y for p in mains)
    ymid = (ys[0] + ys[-1]) / 2 if len(ys) > 1 else ys[0] - 8
    for low, names in sides.items():
        for i, name in enumerate(names):
            xt = e0 + 1 if low else e1 - 1
            s.add(Text(xt, ymid + 1.5 - i * 4.0 - (len(names) - 1) * 2.0, name.upper(), 2.4, "TEXT",
                       anchor="start" if low else "end", bold=True))


def _band_poly(xa, ya, xb, yb, width) -> list:
    dx, dy = xb - xa, yb - ya
    ln = math.hypot(dx, dy) or 1
    nx, ny = -dy / ln * width / 2, dx / ln * width / 2
    return [(xa + nx, ya + ny), (xb + nx, yb + ny), (xb - nx, yb - ny), (xa - nx, ya - ny)]


def _turnout_path(to) -> list:
    """Centre line of a turnout as on the manual layouts: a short tab alongside each
    line (just clear of its band), and the diagonal between them."""
    xa, ya, xb, yb = to.xa, to.ya, to.xb, to.yb
    if to.tb is None:
        return [(xa, ya), (xa, ya), (xb, yb), (xb, yb)]
    dy = 1 if yb > ya else -1
    sx = 1 if xb >= xa else -1
    c = min(3.0, abs(xb - xa) / 4)
    off = BAND / 2 + BAND * 0.45
    a0, b0 = (xa, ya + dy * off), (xb, yb - dy * off)
    return [a0, (xa + sx * c, a0[1]), (xb - sx * c, b0[1]), b0]


def _split(to: _Turnout) -> float:
    if to.tag is None or abs(to.b_m - to.a_m) < 0.5:
        return 0.5
    return min(max((to.tag.location_m - to.a_m) / (to.b_m - to.a_m), 0.2), 0.8)


def _turnout(s: Scene, d: DrawingData, to: _Turnout, plans: dict) -> None:
    """The turnout as a band from its A-end to its B-end, each half in the colour of
    the TIN at that end, split at the turnout tag (QFTL obs. 2); cranked like the
    manual layouts, with a tab alongside each line."""
    ca = _tin_rgb(_tin_at(d, to.ta, to.a_m))
    cb = _tin_rgb(_tin_at(d, to.tb, to.b_m)) if to.tb is not None else (255, 255, 255)
    (p0, p1, p2, p3) = to.path
    f = _split(to)
    pm = (p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f)
    wd = BAND * 0.9
    segs = [(p0, p1, ca), (p1, pm, ca), (pm, p2, cb), (p2, p3, cb)]
    for a, b, rgb in segs:
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.05:
            s.add(Poly(_band_poly(a[0], a[1], b[0], b[1], wd), "POINTS", stroke=None, fill=rgb))
    for a, b in ((p0, p1), (p1, p2), (p2, p3)):
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 0.05:
            s.add(Poly(_band_poly(a[0], a[1], b[0], b[1], wd), "POINTS", stroke=INK, fill=None, width=0.2))
    if to.tb is not None:
        # a square end on each tab, closing it against the line
        for q in (p0, p3):
            s.add(Line(q[0], q[1] - wd / 2, q[0], q[1] + wd / 2, "POINTS", width=0.2))
    s.add(Poly(_circle(to.xa, to.ya, 0.6, 8), "POINTS", fill=INK, width=0.1))


def _turnout_tag(s: Scene, to: _Turnout) -> None:
    if to.tag is None:
        if to.tb is not None:          # flag it on the drawing rather than leave it silently blank
            (p0, p1, p2, p3) = to.path
            xm, ym = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            s.add(Rect(xm - TAG / 2, ym - TAG / 2, TAG, TAG, "TAGS", stroke=RED, fill=(255, 255, 255), width=0.3),
                  Text(xm, ym - 0.75, "?", 1.7, "TAGS", RED, anchor="middle", bold=True),
                  Text(xm + TAG / 2 + 1, ym - 0.6, f"no T tag on {to.e.ref}", 1.6, "TAGS", RED))
        return
    f = _split(to)
    (p0, p1, p2, p3) = to.path
    xm, ym = p1[0] + (p2[0] - p1[0]) * f, p1[1] + (p2[1] - p1[1]) * f
    t = to.tag
    s.add(Rect(xm - TAG / 2, ym - TAG / 2, TAG, TAG, "TAGS", fill=(255, 255, 255), width=0.3),
          Text(xm, ym - 0.75, "T", 1.7, "TAGS", anchor="middle", bold=True))
    # its number and ABS along the band, beside it
    ang = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
    if ang > 90:
        ang -= 180
    if ang < -90:
        ang += 180
    r = math.radians(ang)
    nx, ny = -math.sin(r), math.cos(r)            # normal, pointing "up" the text
    side = 1 if (to.xb - to.xa) * (to.yb - to.ya) < 0 else -1   # the open side of the slope
    off = TAG / 2 + 1.4
    cx, cy = xm + side * nx * off, ym + side * ny * off
    ref = f"{t.ref}  {km(t.location_m)}"
    s.add(Text(cx, cy - (0 if side > 0 else 1.6), ref, 1.7, "LABELS", BLUE, angle=ang, anchor="middle"))


_LC_CLASS_SHORT = {"SPECIAL": "SPL"}


def _lc_caption(e: DElement) -> list[str]:
    cls = (e.lc_class or "").strip().upper()
    num = e.ref.upper().replace("LC-", "").replace("LC", "").strip(" -")
    title = (f"'{_LC_CLASS_SHORT.get(cls, cls)}' CLASS " if cls else "") + f"LC GATE NO. {num or e.ref}"
    return [title] + ([e.lc_manning] if e.lc_manning else [])


def _lc_crossed(e: DElement, order: list) -> list:
    """The lines an LC gate crosses: those running past its chainage (top first)."""
    crossed = [p for p in order if min(p.t.start_m, p.t.end_m) - 1 <= e.location_m <= max(p.t.start_m, p.t.end_m) + 1]
    return crossed or [p for p in order if p.t.id == e.track_id] or order[:1]


def _lc_gates(s: Scene, d: DrawingData, order: list, plan_top: float) -> None:
    """LC gate as on the manual layouts: the road crossing the lines as two dashed
    edges with a centre line, a gate boom (blue, white gate panel) beyond the outer
    lines on each side, and the gate's ABS written along the road."""
    ax = d._ax
    road = (0, 0, 120)
    for e in [e for e in d.elements if e.element_type == "LC Gate"]:
        x = ax(e.location_m)
        crossed = _lc_crossed(e, order)
        y_hi = max(p.y for p in crossed) + BAND / 2 + 4.5
        y_lo = min(p.y for p in crossed) - BAND / 2 - 4.5
        for dx in (-2.0, 2.0):
            s.add(Line(x + dx, y_lo - 1.5, x + dx, y_hi + 1.5, "LC", rgb=INK, width=0.25, dash=True))
        s.add(Line(x, y_lo - 1.5, x, y_hi + 1.5, "LC", rgb=INK, width=0.2))
        for yb, sg in ((y_hi + 1.5, 1), (y_lo - 1.5, -1)):
            s.add(Poly([(x - 7.5, yb), (x - 2.0, yb + 1.3), (x - 2.0, yb - 1.3)], "LC", stroke=INK,
                       fill=(50, 50, 235), width=0.15),
                  Rect(x - 2.0, yb - 1.3, 4.0, 2.6, "LC", stroke=INK, fill=(255, 255, 255), width=0.15),
                  Poly([(x + 2.0, yb + 1.3), (x + 2.0, yb - 1.3), (x + 7.5, yb)], "LC", stroke=INK,
                       fill=(50, 50, 235), width=0.15),
                  Line(x + 7.5, yb, x + 7.5, yb + sg * 1.8, "LC", width=0.2))
        # ABS along the road, between the top two lines it crosses
        if len(crossed) > 1:
            ys = sorted((p.y for p in crossed), reverse=True)
            ym = (ys[0] + ys[1]) / 2
        else:
            ym = crossed[0].y - 8
        s.add(Text(x + 4.6, ym, km(e.location_m), 1.9, "LC", road, angle=90, anchor="middle"))


TOWER_H = 13.0
TOWER_RGB = (120, 0, 140)


def _towers(s: Scene, d: DrawingData, y: float, x0: float, x1: float) -> None:
    """Each tower as a lattice mast with its ref, km and (for an adjacent station's
    tower) the station; captions that would touch are spread apart."""
    if not d.towers:
        return
    ax = d._ax
    tws = sorted(d.towers, key=lambda t: t.location_m)
    caps = []
    for t in tws:
        lines = [t.ref, f"km {km(t.location_m)}"] + ([t.owner] if t.owner else [])
        caps.append((t, lines, max(text_len(x, 1.7, True) for x in lines) + 1.5))
    xs = [ax(t.location_m) for t in tws]
    widths = [c[2] for c in caps]
    pitch = max(widths) + 2 if widths else 10
    cx = spread([x + 4 + pitch / 2 for x in xs], pitch, x0, x1 + pitch)
    s.add(Text(x0 - 3, y + 3.5, "TOWERS", 2.2, "TOWERS", TOWER_RGB, anchor="end", bold=True))
    for (t, lines, w), x, c in zip(caps, xs, cx):
        # mast: two legs, cross-bracing, antenna
        s.add(Line(x - 1.6, y, x, y + 8, "TOWERS", TOWER_RGB, 0.35),
              Line(x + 1.6, y, x, y + 8, "TOWERS", TOWER_RGB, 0.35),
              Line(x - 1.07, y + 2.7, x + 1.07, y + 2.7, "TOWERS", TOWER_RGB, 0.2),
              Line(x - 1.07, y + 2.7, x + 0.53, y + 5.3, "TOWERS", TOWER_RGB, 0.2),
              Line(x + 1.07, y + 2.7, x - 0.53, y + 5.3, "TOWERS", TOWER_RGB, 0.2),
              Line(x, y + 8, x, y + 9.5, "TOWERS", TOWER_RGB, 0.3),
              Poly(_circle(x, y + 9.8, 0.5, 8), "TOWERS", stroke=TOWER_RGB, fill=TOWER_RGB, width=0.1),
              Line(x, y - 0.5, x, y - 2.5, "TOWERS", TOWER_RGB, 0.15, dash=True))
        left = c - w / 2
        if left - x > 3:
            s.add(Line(x + 1.2, y + 6, left - 0.4, y + 6, "TOWERS", LEADER, 0.12))
        for i, ln in enumerate(lines):
            s.add(Text(left, y + 7.6 - i * 2.6, ln, 1.7, "TOWERS", TOWER_RGB if i == 0 else INK, bold=i == 0))


def _leaders(s: Scene, p: _LinePlan, side: int) -> None:
    """Leaders first (all lanes), so every label block is drawn over them."""
    for lb in p.lanes[side].labs:
        if getattr(lb, "arrow", 0):
            continue
        if abs(lb.px - lb.x) > 0.3 or lb.row > 0 or lb.off - lb.anchor_off > 1.2:
            a = p.y + side * lb.anchor_off
            bend = p.y + side * (lb.off - 0.6)
            s.add(Line(lb.x, a, lb.x, bend, "LEADERS", LEADER, 0.12),
                  Line(lb.x, bend, lb.px, p.y + side * lb.off, "LEADERS", LEADER, 0.12))


def _labels(s: Scene, p: _LinePlan, side: int) -> None:
    ln = p.lanes[side]
    for lb in ln.labs:
        arrow = getattr(lb, "arrow", 0)
        cx = lb.px
        if arrow:
            tw = lb.w - 7.0
            cx = lb.px - arrow * 3.5
            ya = p.y + side * (lb.off + 1.3)
            xa = cx + arrow * (tw / 2 + 0.3)
            xb = xa + arrow * 6
            s.add(Line(xa, ya, xb, ya, "TRACKS", width=0.3),
                  Poly([(xb, ya), (xb - arrow * 1.6, ya + 0.6), (xb - arrow * 1.6, ya - 0.6)], "TRACKS",
                       fill=INK, width=0.05))
        comm = getattr(lb, "comm", None)
        if comm:               # "COMM. EXIT FOR A <-+-> COMM. ENTRY FOR B"
            yy = p.y + side * (lb.off + 1.2)
            s.add(Line(cx - 6, yy, cx + 6, yy, "BORDER", width=0.25),
                  Poly([(cx - 6.5, yy), (cx - 4.9, yy + 0.6), (cx - 4.9, yy - 0.6)], "BORDER", fill=INK, width=0.05),
                  Poly([(cx + 6.5, yy), (cx + 4.9, yy + 0.6), (cx + 4.9, yy - 0.6)], "BORDER", fill=INK, width=0.05),
                  Line(cx, yy, cx, p.y + side * lb.off, "BORDER", width=0.25),
                  Text(cx - 7.2, yy - 0.6, comm[0], 1.7, "BORDER", anchor="end"),
                  Text(cx + 7.2, yy - 0.6, comm[1], 1.7, "BORDER", anchor="start"))
            continue
        # a white backing behind the block, so leaders of outer labels pass behind it
        if not arrow:
            yb0 = p.y + side * lb.off
            yb1 = p.y + side * (lb.off + lb.h)
            s.add(Rect(lb.px - lb.w / 2, min(yb0, yb1), lb.w, abs(yb1 - yb0), "LABELS", stroke=None,
                       fill=(255, 255, 255)))
        # lines stacked outward from the line: the first one nearest
        o = lb.off
        for text, size, rgb, bold, boxed in lb.lines:
            hgt = size + (1.7 if boxed else 1.0)
            y_base = p.y + side * (o + (0.85 if boxed else 0.5)) if side > 0 else p.y - (o + hgt - (0.85 if boxed else 0.5))
            if boxed:
                bw = text_len(text, size, bold) + 1.6
                yb = (p.y + side * o) if side > 0 else (p.y - o - hgt + 0.3)
                s.add(Rect(cx - bw / 2, yb, bw, hgt - 0.3, "LABELS", stroke=rgb, fill=(255, 255, 255), width=0.2))
            s.add(Text(cx, y_base, text, size, "LABELS", rgb, anchor="middle", bold=bold))
            o += hgt


def _dim(s: Scene, xa: float, xb: float, y: float, side: int, off: float, metres: float) -> None:
    yy = y + side * off
    s.add(Line(xa, y + side * (BAND / 2 + 0.5), xa, yy + side * 0.8, "DIMENSIONS", INK, 0.12),
          Line(xb, y + side * (BAND / 2 + 0.5), xb, yy + side * 0.8, "DIMENSIONS", INK, 0.12),
          Line(xa, yy, xb, yy, "DIMENSIONS", INK, 0.15),
          Poly([(xa, yy), (xa + 1.2, yy + 0.4), (xa + 1.2, yy - 0.4)], "DIMENSIONS", fill=INK, width=0.05),
          Poly([(xb, yy), (xb - 1.2, yy + 0.4), (xb - 1.2, yy - 0.4)], "DIMENSIONS", fill=INK, width=0.05),
          Text((xa + xb) / 2, yy + 0.5, f"{metres:.0f}m", 1.6, "DIMENSIONS", anchor="middle"))


def _signal(s: Scene, sg: _Sig, y: float) -> None:
    sd, tv, x = sg.side, sg.travel, sg.x
    arm = ARM + sg.tier * TIER
    ya = y + sd * arm
    # post from the line, arrow at the foot
    s.add(Line(x, y + sd * (BAND / 2 + 0.2), x, ya + sd * 1.0, "SIGNALS", width=0.3),
          Poly([(x, y + sd * (BAND / 2 + 0.1)), (x - 0.5, y + sd * (BAND / 2 + 1.3)),
                (x + 0.5, y + sd * (BAND / 2 + 1.3))], "SIGNALS", fill=INK, width=0.05))
    name_y = ya + sd * (LAMP + 0.9) - (0 if sd > 0 else LBL)
    if sg.kind == "board":
        bw = 6.0 if sg.board == "SB" else 7.0
        cx = x + tv * (bw / 2 + 0.6)
        s.add(Line(x, ya, cx - tv * bw / 2, ya, "BOARDS", width=0.3),
              Rect(cx - bw / 2, ya - 1.4, bw, 2.8, "BOARDS", fill=(255, 255, 255), width=0.3))
        if sg.board == "BSLB":
            s.add(Line(cx - bw / 2, ya - 1.4, cx + bw / 2, ya + 1.4, "BOARDS", width=0.2),
                  Line(cx - bw / 2, ya + 1.4, cx + bw / 2, ya - 1.4, "BOARDS", width=0.2))
            s.add(Text(cx, ya + sd * 2.2 - (0 if sd > 0 else LBL), "BSLB", LBL, "SIGNALS", anchor="middle", bold=True))
        else:
            s.add(Text(cx, ya - 0.7, sg.board, 1.7, "BOARDS", anchor="middle", bold=True))
        return
    if sg.kind == "shunt":
        # position-light shunt signal: a quarter disc with its lamps
        cx = x + tv * 0.4
        r = 3.0
        pts = [(cx, ya - r / 2)] + [(cx + tv * r * math.cos(a), ya - r / 2 + r * math.sin(a))
                                    for a in [i * math.pi / 2 / 8 for i in range(9)]]
        s.add(Poly(pts, "SIGNALS", fill=(255, 255, 255), width=0.25))
        for dx, dy in ((0.7, 0.2), (1.5, 0.9), (1.5, -0.4)):
            s.add(Poly(_circle(cx + tv * dx, ya - r / 2 + dy + 0.3, 0.3, 8), "SIGNALS", fill=INK, width=0.05))
        s.add(Text(x - tv * 0.8, ya - 0.6, sg.names[0] if sg.names else "", LBL, "SIGNALS",
                   anchor="end" if tv > 0 else "start", bold=True))
        return
    # main signal: arm along the line in the running direction; calling-on lamps first,
    # then the main lamps (R / Y / YY / G), then the route indicator
    cur = x + tv * 0.8
    s.add(Line(x, ya, cur, ya, "SIGNALS", width=0.3))
    for name in sg.calling:
        cx = cur + tv * 0.85
        s.add(Poly(_circle(cx, ya, 0.75, 12), "SIGNALS", fill=(245, 195, 0), width=0.2),
              Text(cx, ya - 0.38, "C", 0.9, "SIGNALS", anchor="middle", bold=True),
              Text(cx, name_y, name, LBL, "SIGNALS", anchor="middle", bold=True))
        cur += tv * 1.7
        s.add(Line(cur - tv * 0.1, ya, cur + tv * 0.2, ya, "SIGNALS", width=0.3))
    lamps = sg.aspects or ["?"]
    start = cur
    for i, lamp in enumerate(lamps):
        cx = cur + tv * LAMP
        rgb = LAMP_RGB.get(lamp, (255, 255, 255))
        s.add(Poly(_circle(cx, ya, LAMP, 16), "SIGNALS", fill=rgb, width=0.22))
        s.add(Text(cx, ya - 0.45, lamp, 0.95 if lamp == "YY" else 1.2, "SIGNALS",
                   INK if lamp in ("Y", "YY", "?") else (255, 255, 255), anchor="middle", bold=True))
        cur += tv * 2 * LAMP
    if sg.route:
        s.add(Line(cur, ya, cur + tv * 0.5, ya, "SIGNALS", width=0.3),
              Line(cur + tv * 0.5, ya, cur + tv * 1.6, ya + sd * 1.1, "SIGNALS", width=0.45),
              Line(cur + tv * 0.5, ya, cur + tv * 1.6, ya - sd * 1.1, "SIGNALS", width=0.45))
        cur += tv * 1.6
    if sg.names:
        label = " / ".join(sg.names) + ("*" if sg.default else "")
        s.add(Text((start + cur) / 2, name_y, label, LBL, "SIGNALS", anchor="middle", bold=True))


def _tag_symbol(s: Scene, t: DTag, x: float, y: float, group: list, dn_direction: str = "Nominal") -> None:
    """A tag ON its line (QFTL obs. 5): legend shape with the tag-type letter inside."""
    others = [g for g in group if g is not t]
    colocated = bool(others) and all(abs(g.location_m - t.location_m) < 0.5 for g in others)
    shape = t.legend_shape or ("Rectangle" if colocated or t.tag_type == "T" else "Triangle")
    fill = (255, 230, 120) if t.is_border else (255, 255, 255)
    base = y - TAG / 2
    if shape == "Triangle":
        trav = _travel(t.direction, dn_direction)
        ahead = (others[0].location_m > t.location_m) if others else (trav != "Reverse")
        tip = x + TAG / 2 if ahead else x - TAG / 2
        back = x - TAG / 2 if ahead else x + TAG / 2
        s.add(Poly([(back, base), (back, base + TAG), (tip, base + TAG / 2)], "TAGS", fill=fill, width=0.3))
        tx = x - (0.35 if ahead else -0.35)
    else:
        s.add(Rect(x - TAG / 2, base, TAG, TAG, "TAGS", fill=fill, width=0.3))
        tx = x
    s.add(Text(tx, y - 0.65, t.tag_type, 1.5, "TAGS", anchor="middle", bold=True))


def _tag(s: Scene, t: DTag, x: float, y: float, group: list, refs: str) -> None:
    """One tag with its number and location stacked beside it (used on its own)."""
    _tag_symbol(s, t, x, y, group)
    where = ([f"ABS-1 {km(t.location_m)}", f"ABS-2 {km(t.abs2_m)}"] if t.tag_type == "A" and t.abs2_m is not None
             else [km(t.location_m)])
    s.add(Text(x, y - 5, refs, LBL, "TAGS", BLUE, anchor="middle"))
    for i, w in enumerate(where):
        s.add(Text(x, y - 8 - i * 3, w, LBL, "TAGS", anchor="middle"))


# ---------------------------------------------------------------------------
# Blocks along the bottom
# ---------------------------------------------------------------------------
def _wrap(text: str, width: float, size: float) -> list[str]:
    """Split at ", " to fit a cell; very long single items are cut."""
    parts = [p.strip() for p in str(text).split(",")]
    lines, cur = [], ""
    for p in parts:
        cand = f"{cur}, {p}" if cur else p
        if text_len(cand, size) <= width or not cur:
            cur = cand
        else:
            lines.append(cur + ",")
            cur = p
    lines.append(cur)
    return [x if "," in x.rstrip(",") else _fit(x, width + 2, size) for x in lines]


def _grid(s: Scene, x: float, y_top: float, widths: list, rows: list, size: float = 1.7,
          header_rows: int = 1, layer: str = "BLOCKS", min_h: float = 4.0) -> float:
    """A table whose cells wrap; returns the y of its bottom edge."""
    total = sum(widths)
    y = y_top
    for i, row in enumerate(rows):
        cells = [_wrap(c, cw - 1.6, size) for cw, c in zip(widths, row)]
        hgt = max(min_h, max(len(c) for c in cells) * (size + 1.1) + 1.2)
        s.add(Line(x, y, x + total, y, layer, width=0.2))
        cx = x
        for cw, lines in zip(widths, cells):
            for j, ln in enumerate(lines):
                s.add(Text(cx + 0.8, y - 1.0 - (j + 1) * (size + 1.1) + 0.9, ln, size, layer, bold=i < header_rows))
            cx += cw
        top = y
        y -= hgt
        cx = x
        for cw in [0] + widths:
            cx += cw
            s.add(Line(cx, top, cx, y, layer, width=0.2))
    s.add(Line(x, y, x + total, y, layer, width=0.2))
    return y


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


LEGEND_W, LEGEND2_W, REV_W, TITLE_W = 58.0, 70.0, 120.0, 78.0
TS_W = 112.0                 # station title & signatures block (bottom left, as on the manual layouts)


def _allot_widths(d: DrawingData) -> list:
    n = max(1, len(d.allotment))
    return [16.0, 15.0] + [36.0] * n


def _blocks_width(d: DrawingData) -> float:
    return TS_W + 5 + REV_W + 5 + LEGEND_W + LEGEND2_W + sum(_allot_widths(d)) + 6 + TITLE_W + 8


def _blocks(s: Scene, d: DrawingData, w: float = W) -> None:
    top = BLOCKS_TOP
    s.add(Line(MARGIN, top + 6, w - MARGIN, top + 6, "FRAME", width=0.4))

    _title_and_signatures(s, d, MARGIN + 3, top)
    _revisions(s, d, MARGIN + 3 + TS_W + 5, top)

    # Legend (H2.25): tags
    x = MARGIN + 3 + TS_W + 5 + REV_W + 5
    _heading(s, x, top, "LEGEND")
    types = [("N", "Normal tag"), ("S", "Signal foot tag"), ("T", "TIN discrimination / turnout tag"),
             ("G", "Gate tag"), ("X", "Exit tag"), ("L", "Adjacent line tag"), ("A", "Adjustment / junction tag"),
             ("D", "Dead stop tag")]
    y = top - 5
    for code, text in types:
        if code == "T":
            s.add(Rect(x, y - 0.6, 3.0, 3.0, "BLOCKS", fill=(255, 255, 255), width=0.2))
        else:
            s.add(Poly([(x, y - 0.6), (x, y + 2.4), (x + 3.0, y + 0.9)], "BLOCKS", fill=(255, 255, 255), width=0.2))
        s.add(Text(x + (1.5 if code == "T" else 1.1), y + 0.3, code, 1.3, "BLOCKS", anchor="middle", bold=True),
              Text(x + 5, y + 0.3, text, 1.8, "BLOCKS"))
        y -= 3.9
    s.add(Rect(x, y - 0.6, 3.0, 3.0, "BLOCKS", fill=(255, 255, 255), width=0.2),
          Text(x + 5, y + 0.3, "Main & duplicate co-located", 1.8, "BLOCKS"))
    y -= 3.9
    s.add(Rect(x, y - 0.6, 3.0, 3.0, "BLOCKS", fill=(255, 230, 120), width=0.2),
          Text(x + 5, y + 0.3, "Border tag", 1.8, "BLOCKS"))
    y -= 3.9
    bw = text_len("R-775", 1.6) + 1.6
    s.add(Rect(x, y - 0.5, bw, 2.8, "BLOCKS", stroke=BLUE, fill=(255, 255, 255), width=0.2),
          Text(x + bw / 2, y + 0.2, "R-775", 1.6, "BLOCKS", BLUE, anchor="middle"),
          Text(x + bw + 2, y + 0.2, "tag no. / ABS (km) under it", 1.7, "BLOCKS"))
    y -= 3.9
    other = "Reverse" if d.dn_direction == "Nominal" else "Nominal"
    s.add(Text(x, y, f"SIP Down = {d.dn_direction}, SIP Up = {other}", 1.7, "BLOCKS"),
          Text(x, y - 3.1, "Signals: Nominal above the line, Reverse below", 1.7, "BLOCKS"),
          Text(x, y - 6.2, "Line colours = TIN colours; | = TIN boundary", 1.7, "BLOCKS"))

    # Legend: signals, turnouts, boards, LC gates
    x2 = x + LEGEND_W
    y = top - 3.2
    s.add(Text(x2, y, "Signals (head points in the running direction)", 1.7, "BLOCKS", bold=True))
    y -= 4.6
    for lamps, text in ((["R", "Y", "YY", "G"], "R red · Y yellow · YY double yellow · G green"),
                        (["G", "YY", "Y"], "Distant: no red (permissive)")):
        s.add(Line(x2, y - 1.4, x2, y + 1.4, "BLOCKS", width=0.3), Line(x2, y, x2 + 0.8, y, "BLOCKS", width=0.3))
        for i, lamp in enumerate(lamps):
            cx = x2 + 0.8 + LAMP + i * 2 * LAMP
            s.add(Poly(_circle(cx, y, LAMP, 14), "BLOCKS", fill=LAMP_RGB[lamp], width=0.2))
        s.add(Text(x2 + 12, y - 0.6, text, 1.6, "BLOCKS"))
        y -= 4.2
    s.add(Line(x2, y - 1.4, x2, y + 1.4, "BLOCKS", width=0.3), Line(x2, y, x2 + 0.8, y, "BLOCKS", width=0.3),
          Poly(_circle(x2 + 1.65, y, 0.75, 12), "BLOCKS", fill=(245, 195, 0), width=0.2),
          Poly(_circle(x2 + 2.5 + LAMP, y, LAMP, 14), "BLOCKS", fill=LAMP_RGB["R"], width=0.2),
          Line(x2 + 2.5 + 2 * LAMP, y, x2 + 3.0 + 2 * LAMP, y, "BLOCKS", width=0.3),
          Line(x2 + 3.0 + 2 * LAMP, y, x2 + 4.1 + 2 * LAMP, y + 1.1, "BLOCKS", width=0.4),
          Line(x2 + 3.0 + 2 * LAMP, y, x2 + 4.1 + 2 * LAMP, y - 1.1, "BLOCKS", width=0.4),
          Text(x2 + 12, y - 0.6, "C calling-on (before the main head) · > route indicator", 1.6, "BLOCKS"))
    y -= 4.2
    r = 2.4
    s.add(Poly([(x2 + 0.4, y - r / 2)] + [(x2 + 0.4 + r * math.cos(a), y - r / 2 + r * math.sin(a))
                                          for a in [i * math.pi / 16 for i in range(9)]], "BLOCKS",
               fill=(255, 255, 255), width=0.2),
          Text(x2 + 12, y - 0.6, "Shunt signal (position light)", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Text(x2, y - 0.6, "*  aspects by signal type (not stated in the inputs)", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Rect(x2, y - 1.6, 7, 2.8, "BLOCKS", fill=(255, 255, 255), width=0.25),
          Line(x2, y - 1.6, x2 + 7, y + 1.2, "BLOCKS", width=0.2), Line(x2, y + 1.2, x2 + 7, y - 1.6, "BLOCKS", width=0.2),
          Text(x2 + 12, y - 0.6, "BSLB board;  SB stop board", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Poly(_band_poly(x2, y - 1.2, x2 + 4, y - 1.2, 1.6), "BLOCKS", stroke=None, fill=(245, 195, 0)),
          Poly(_band_poly(x2 + 1.5, y - 1.2, x2 + 4.5, y + 1.6, 1.4), "BLOCKS", stroke=INK, fill=(110, 190, 245),
               width=0.15),
          Text(x2 + 12, y - 0.6, "Turnout: TIN colour at each end; A-end / B-end ABS", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Poly([(x2 + 4, y), (x2 + 0.5, y + 1.2), (x2 + 0.5, y - 0.2)], "BLOCKS", fill=(40, 40, 220), width=0.15),
          Poly([(x2 + 4, y), (x2 + 7.5, y + 1.2), (x2 + 7.5, y - 0.2)], "BLOCKS", fill=(40, 40, 220), width=0.15),
          Text(x2 + 12, y - 0.6, "LC gate (class, gate no., location)", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Line(x2 + 1.5, y - 1.4, x2 + 2.6, y + 1.6, "BLOCKS", TOWER_RGB, 0.3),
          Line(x2 + 3.7, y - 1.4, x2 + 2.6, y + 1.6, "BLOCKS", TOWER_RGB, 0.3),
          Text(x2 + 12, y - 0.6, "Stationary KAVACH tower", 1.6, "BLOCKS"))
    y -= 4.2
    s.add(Line(x2, y + 0.5, x2 + 8, y + 0.5, "BLOCKS", width=0.15),
          Text(x2 + 4, y + 1.0, "200m", 1.4, "BLOCKS", anchor="middle"),
          Text(x2 + 12, y - 0.6, "Reference distance (signal / G / L / D tag)", 1.6, "BLOCKS"))

    # Allotment (H2.23), as on the approved layouts: allotted and spare per section
    x = x2 + LEGEND2_W
    widths = _allot_widths(d)
    _heading(s, x, top, "RFID TAG / TIN ALLOTMENT")
    cols = d.allotment or [DAllotRow("No allotment chart loaded", "", None, None, "", None, None)]
    rows = [["", ""] + [c.label for c in cols],
            ["STATION ID", ""] + [c.station_id or "-" for c in cols],
            ["RFID", "RANGE"] + [c.tag_range or "-" for c in cols],
            ["", "ALLOTTED"] + [c.tags_allotted or "-" for c in cols],
            ["", "SPARE"] + [c.tags_spare or "-" for c in cols],
            ["TIN", "RANGE"] + [c.tin_range or "-" for c in cols],
            ["", "ALLOTTED"] + [c.tins_allotted or "-" for c in cols],
            ["", "SPARE"] + [c.tins_spare or "-" for c in cols],
            ["BORDER", "TAGS"] + [c.border_tags or "-" for c in cols]]
    yb = _grid(s, x, top - 2, widths, rows, size=1.6, header_rows=1, min_h=3.8)
    s.add(Text(x + sum(widths) / 2, yb - 3.4, f"TOTAL NO. OF TAGS - {len(d.tags):03d}   ·   TINs: "
               f"{len({n.tin_no for n in d.tins})}", 1.9, "BLOCKS", BLUE, anchor="middle", bold=True))
    if d.allotment_ref:
        s.add(Text(x, yb - 7, _fit(f"As per {d.allotment_ref}", sum(widths), 1.5), 1.5, "BLOCKS", FAINT))

    # S&T title block, at the right-hand edge
    x = w - MARGIN - 2 - 76
    s.add(Rect(x, MARGIN + 2, 76, top - MARGIN - 0.5, "BLOCKS", width=0.4))
    lines = [("SIGNAL & TELECOMMUNICATIONS", 2.4, True), ("KAVACH", 2.2, False),
             (d.station_name.upper(), 3.8, True), ("KAVACH RFID TAG / TIN LAYOUT", 2.2, False),
             ("", 1.0, False),
             (f"REF. SIG. PLAN NO.  {d.sip_drawing_number or '-'}", 2.0, False),
             (f"KAVACH station ID  {_station_id(d)}", 2.0, False),
             (f"Version (X.Y.Z)  {d.layout_version}", 2.0, False),
             (f"Zone  {d.zone or '-'}", 2.0, False),
             ("", 1.0, False),
             ("DRG. No.", 1.8, False), (drawing_number(d), 2.0, True),
             ("", 1.0, False),
             ("NOT DRAWN TO SCALE" if not d.drawn_to_scale else "Drawn to scale", 2.2, True),
             ("Ref: RDSO/SPN/196/2020 Annexure-H (Amdt-5)", 1.6, False),
             (f"Generated {d.generated_at[:16].replace('T', ' ')} by {d.generated_by}", 1.6, False),
             (f"SHEET 01 OF 01  ·  {_sheet_name(w, s.height)}", 1.8, False)]
    y = top - 2.5
    for text, size, bold in lines:
        y -= size
        if text:
            s.add(Text(x + 38, y, _fit(text, 72, size), size, "BLOCKS", bold=bold, anchor="middle"))
        y -= 2.0


def _title_and_signatures(s: Scene, d: DrawingData, x: float, top: float) -> None:
    """Bottom-left block of the manual layouts: station, layout title, SIP and drawing
    number, and who prepared / checked / validated / approved it (H2.24)."""
    W_ = TS_W
    yt = top - 2
    rows_h = [14.0, 5.5, 5.5, 5.0, 6.0, 6.0]
    ys = [yt]
    for hgt in rows_h:
        ys.append(ys[-1] - hgt)
    s.add(Rect(x, ys[-1], W_, yt - ys[-1], "BLOCKS", width=0.35))
    for yy in ys[1:-1]:
        s.add(Line(x, yy, x + W_, yy, "BLOCKS", width=0.2))
    xm = x + W_ * 0.56
    s.add(Line(xm, ys[0], xm, ys[3], "BLOCKS", width=0.2))
    s.add(Text(x + W_ * 0.28, ys[0] - 6.0, d.station_name.upper(), 3.4, "BLOCKS", RED, anchor="middle", bold=True),
          Text(x + W_ * 0.28, ys[0] - 10.5, _fit(d.zone or "", W_ * 0.54, 1.8), 1.8, "BLOCKS", anchor="middle"),
          Text(xm + 2, ys[0] - 5.0, f"REF. SIP :  {d.sip_drawing_number or '-'}", 2.0, "BLOCKS"),
          Text(xm + 2, ys[0] - 10.0, f"VERSION :  {d.layout_version}", 2.0, "BLOCKS"),
          Text(x + W_ * 0.28, ys[1] - 3.9, "RFID TAG / TIN LAYOUT", 2.0, "BLOCKS", anchor="middle"),
          Text(xm + 2, ys[1] - 3.9, "DRG NO:", 1.9, "BLOCKS"),
          Text(x + W_ * 0.28, ys[2] - 3.9, "NOT DRAWN TO SCALE" if not d.drawn_to_scale else "DRAWN TO SCALE", 2.0,
               "BLOCKS", anchor="middle"),
          Text(xm + (W_ - (xm - x)) / 2, ys[2] - 3.9, _fit(drawing_number(d), W_ - (xm - x) - 2, 1.9), 1.9,
               "BLOCKS", RED, anchor="middle"))
    # prepared / checked / validated / approved
    lab_w = 12.0
    cw = (W_ - lab_w) / 4
    s.add(Line(x + lab_w, ys[3], x + lab_w, ys[6], "BLOCKS", width=0.2))
    for i in range(1, 4):
        s.add(Line(x + lab_w + i * cw, ys[3], x + lab_w + i * cw, ys[6], "BLOCKS", width=0.2))
    s.add(Text(x + lab_w / 2, ys[4] - 4.0, "DATE", 1.7, "BLOCKS", anchor="middle"),
          Text(x + lab_w / 2, ys[5] - 4.0, "NAME", 1.7, "BLOCKS", anchor="middle"))
    for i, role in enumerate(("Prepared", "Checked", "Validated", "Approved")):
        cx = x + lab_w + i * cw + cw / 2
        name, date = d.signatures.get(role, ("", ""))
        s.add(Text(cx, ys[3] - 3.5, f"{role.upper()} BY", 1.7, "BLOCKS", anchor="middle"),
              Text(cx, ys[4] - 4.0, date or "", 1.7, "BLOCKS", anchor="middle"),
              Text(cx, ys[5] - 4.0, _fit(name or "", cw - 1.5, 1.7), 1.7, "BLOCKS", anchor="middle"))


def _revisions(s: Scene, d: DrawingData, x: float, top: float) -> None:
    """Revision history as on the manual layouts: REV. NO / REVISION HISTORY / DATE."""
    rows = [["REV. NO", "REVISION HISTORY", "DATE"]] + [[r, desc, dt or "-"] for r, dt, desc in d.revisions[-6:]]
    if len(rows) == 1:
        rows.append(["-", "No revisions recorded", "-"])
    _grid(s, x, top - 2, [14.0, REV_W - 36.0, 22.0], rows, size=1.7, header_rows=1, min_h=4.4)


def _sheet_name(w: float, h: float = 0) -> str:
    for name, sw, sh in SHEETS:
        if abs(sw - w) < 1 and (not h or abs(sh - h) < 1):
            return name
    return f"{w:.0f} x {h:.0f} mm" if h else f"{w:.0f} mm long"
