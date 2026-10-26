"""Step 4 of the Annexure-H plan: checks the line (track) model makes possible, plus
the New-TAN rules from the QFTL process deck and manual verification tool.

  H2.8   TIN demarcation: a demarcation tag at each boundary between TINs on a line
  H2.17  one colour per TIN; neighbouring TINs in different colours
  H2.20  exit tags where a train can leave KAVACH territory or be stabled (sidings)
  H2.22  block TIN extended to the BSLB (double line) / Advance Starter (single line)
  H2.26  "not drawn to scale" note when the layout isn't to scale
  TAN-1  dead stop tag 25-35 m from the facing points
  TAN-2  adjacent line (L) tag about 100 m after the last stop signal
  TAN-3  two Normal tags within (0.5 x max section speed + 10) m of an adjustment tag

Pure functions over the domain dataclasses, same contract as engine.py. Where the
data needed to judge a case is missing (no lines recorded, a TIN not placed on a
line) the check says so rather than guessing.
"""
from __future__ import annotations

from ..domain import LC_GATE, POINTS, Element, Station, Tag, TIN
from .engine import CheckResult, _params


def _tins_by_track(tins: list[TIN]) -> dict[int, list[TIN]]:
    out: dict[int, list[TIN]] = {}
    for n in tins:
        if n.track_id is not None:
            out.setdefault(n.track_id, []).append(n)
    for lst in out.values():
        lst.sort(key=lambda n: min(n.start_m, n.end_m))
    return out


def _lo(n: TIN) -> float:
    return min(n.start_m, n.end_m)


def _hi(n: TIN) -> float:
    return max(n.start_m, n.end_m)


def _track_name(station: Station, tid: int | None) -> str:
    return next((t.name for t in station.tracks if t.id == tid), f"line {tid}")


def _no_lines(clause: str, title: str, station: Station) -> list[CheckResult] | None:
    if not station.tracks:
        return [CheckResult(clause, title, "NA", "No lines recorded for this station -- record its lines "
                            "(Registers tab) so this can be checked")]
    return None


# ---------------------------------------------------------------------------
# H2.17
# ---------------------------------------------------------------------------
def neighbouring_tins(station: Station, elements: list[Element], tins: list[TIN],
                      gap_m: float) -> list[tuple[TIN, TIN, str]]:
    """Pairs of TIN sections that touch: consecutive on the same line (gap <= gap_m),
    or on two lines joined by points that lie within both sections."""
    pairs: list[tuple[TIN, TIN, str]] = []
    by_track = _tins_by_track(tins)
    for tid, lst in by_track.items():
        for a, b in zip(lst, lst[1:]):
            if a.tin_no != b.tin_no and _lo(b) - _hi(a) <= gap_m:
                pairs.append((a, b, f"consecutive on {_track_name(station, tid)}"))
    for e in elements:
        if e.element_type != POINTS or e.track_id is None or e.to_track_id is None:
            continue
        here = [n for n in by_track.get(e.track_id, []) if _lo(n) - gap_m <= e.location_m <= _hi(n) + gap_m]
        there = [n for n in by_track.get(e.to_track_id, []) if _lo(n) - gap_m <= e.location_m <= _hi(n) + gap_m]
        for a in here:
            for b in there:
                if a.tin_no != b.tin_no:
                    pairs.append((a, b, f"joined by points {e.element_ref}"))
    return pairs


def check_h2_17_tin_colours(station: Station, elements: list[Element], tins: list[TIN],
                            p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_17", p)
    out: list[CheckResult] = []
    colours: dict[int, set[str]] = {}
    for n in tins:
        if n.is_non_kavach_territory:
            continue   # non-KAVACH is white by H2.18, whatever it touches
        colours.setdefault(n.tin_no, set()).add((n.color or "").strip().lower())
    for no, cs in sorted(colours.items()):
        if "" in cs:
            out.append(CheckResult("H2.17", "TIN colour recorded", "FAIL", f"TIN {no}: colour not recorded",
                                   subject_ref=str(no)))
        elif len(cs) > 1:
            out.append(CheckResult("H2.17", "One colour per TIN", "FAIL",
                                   f"TIN {no} is shown in more than one colour: {', '.join(sorted(cs))}",
                                   subject_ref=str(no)))
    if (na := _no_lines("H2.17", "Neighbouring TINs in different colours", station)) is not None:
        return out + na
    seen = set()
    for a, b, how in neighbouring_tins(station, elements, [n for n in tins if not n.is_non_kavach_territory],
                                       p["touch_gap_m"]):
        key = tuple(sorted((a.tin_no, b.tin_no)))
        if key in seen:
            continue
        seen.add(key)
        ca, cb = (a.color or "").strip().lower(), (b.color or "").strip().lower()
        if not ca or not cb:
            continue   # reported above
        ok = ca != cb
        out.append(CheckResult("H2.17", "Neighbouring TINs in different colours", "PASS" if ok else "FAIL",
                               f"TIN {a.tin_no} ({a.color}) and TIN {b.tin_no} ({b.color}), {how}"
                               + ("" if ok else " -- same colour"), subject_ref=f"{key[0]}/{key[1]}"))
    return out


# ---------------------------------------------------------------------------
# H2.8
# ---------------------------------------------------------------------------
def check_h2_8_tin_demarcation(station: Station, tags: list[Tag], tins: list[TIN],
                               p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_8", p)
    title = "TIN boundary marked by a tag"
    if (na := _no_lines("H2.8", title, station)) is not None:
        return na
    out = []
    types, tol = set(p["tag_types"]), p["max_distance_m"]
    for tid, lst in _tins_by_track(tins).items():
        on_line = [t for t in tags if t.track_id == tid and t.tag_type in types]
        for a, b in zip(lst, lst[1:]):
            if a.tin_no == b.tin_no:
                continue
            boundary = (_hi(a) + _lo(b)) / 2
            near = sorted(on_line, key=lambda t: abs(t.location_m - boundary))
            ok = bool(near) and abs(near[0].location_m - boundary) <= tol
            where = f"TIN {a.tin_no} | TIN {b.tin_no} at {boundary:g} m on {_track_name(station, tid)}"
            out.append(CheckResult(
                "H2.8", title, "PASS" if ok else "FAIL",
                f"{where}: " + (f"{near[0].tag_ref} ({near[0].tag_type}) {abs(near[0].location_m - boundary):.0f} m away"
                                if ok else f"no {'/'.join(sorted(types))} tag within {tol:g} m"),
                subject_ref=f"{a.tin_no}/{b.tin_no}"))
    return out


# ---------------------------------------------------------------------------
# H2.20
# ---------------------------------------------------------------------------
def check_h2_20_exit_at_sidings(station: Station, elements: list[Element], tags: list[Tag],
                                p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_20", p)
    title = "Exit tag where a train can leave KAVACH or be stabled"
    if (na := _no_lines("H2.20", title, station)) is not None:
        return na
    out = []
    dist = p["max_distance_m"]
    exits = [t for t in tags if t.tag_type == "X"]
    for tr in station.tracks:
        if tr.track_type != "Siding" and tr.is_kavach:
            continue
        why = "siding" if tr.track_type == "Siding" else "non-KAVACH line"
        on_it = [t for t in exits if t.track_id == tr.id]
        entries = [e for e in elements if e.element_type == POINTS and tr.id in (e.track_id, e.to_track_id)]
        near = [t for t in exits for e in entries
                if t.track_id in (e.track_id, e.to_track_id) and abs(t.location_m - e.location_m) <= dist]
        found = on_it or near
        msg = (f"{tr.name} ({why}): exit tag {found[0].tag_ref}" if found else
               f"{tr.name} ({why}): no exit (X) tag on it or within {dist:g} m of the points leading to it"
               + ("" if entries else " -- and no points leading to it are recorded"))
        out.append(CheckResult("H2.20", title, "PASS" if found else "FAIL", msg, subject_ref=tr.name))
    return out


# ---------------------------------------------------------------------------
# H2.22
# ---------------------------------------------------------------------------
def _side_config(station: Station, below_centre: bool) -> str | None:
    """Line configuration of the section on one side of the station."""
    want = "lower" if below_centre else "higher"
    for a in station.adjacent:
        if want in (a.side or "").lower() and a.line_config:
            return a.line_config
    configs = {a.line_config for a in station.adjacent if a.line_config}
    return configs.pop() if len(configs) == 1 else None


def _line_travel(track_id, tags, station) -> str | None:
    """Direction of travel on a line: the track's own direction if recorded, else the
    direction most of its tags carry (Nominal / Reverse)."""
    tr = next((t for t in station.tracks if t.id == track_id), None)
    if tr is not None and tr.direction in ("Nominal", "Reverse"):
        return tr.direction
    votes = [t.direction for t in tags or [] if t.track_id == track_id and t.direction in ("Nominal", "Reverse")]
    if not votes:
        return None
    nom = votes.count("Nominal")
    return None if nom * 2 == len(votes) else ("Nominal" if nom * 2 > len(votes) else "Reverse")


def check_h2_22_block_tin_extent(station: Station, elements: list[Element], tins: list[TIN],
                                 p: dict | None = None, tags: list[Tag] | None = None) -> list[CheckResult]:
    p = _params("h2_22", p)
    title = "Block TIN from Advanced Starter to Home / BSLB"
    blocks = [n for n in tins if (n.section_type or "").lower() == "block" and not n.is_non_kavach_territory]
    if not blocks:
        return []
    if (na := _no_lines("H2.22", title, station)) is not None:
        return na
    if station.centre_line_m is None:
        return [CheckResult("H2.22", title, "NA", "Station centre line not recorded -- needed to tell "
                            "which end of a block TIN faces the station")]
    out, tol = [], p["tolerance_m"]
    for n in blocks:
        if n.track_id is None:
            out.append(CheckResult("H2.22", title, "NA", f"TIN {n.tin_no}: not placed on a line",
                                   subject_ref=str(n.tin_no)))
            continue
        # side of the station by the TIN's midpoint: a block TIN can reach just past the
        # centre line (Aler's TIN 222 ends at 262.910, centre 262.750) and still be the
        # lower-km block section
        below = (_lo(n) + _hi(n)) / 2 < station.centre_line_m
        inner = _hi(n) if below else _lo(n)
        cfg = _side_config(station, below)
        if cfg is None:
            out.append(CheckResult("H2.22", title, "NA",
                                   f"TIN {n.tin_no}: single/double line not recorded for the adjacent station "
                                   f"on the {'lower' if below else 'higher'} km side", subject_ref=str(n.tin_no)))
            continue
        # One TIN per block section: it starts at the Advanced Starter (last stop signal)
        # of the dispatching station and ends at the Home signal or BSLB of the
        # receiving station (QFTL, 26.09.2026). So the station-side end is the Home/BSLB
        # where trains ARRIVE through it and the Advanced Starter where they DEPART.
        # Aler: TIN 222 ends at the DN BSLB 261.978, TIN 217 starts at S6, TIN 221 at S25.
        # Which applies depends on the line's direction of travel (Nominal = increasing
        # km); when that is unknown, fall back to BSLB/Home (double) or Advance Starter
        # (single line), as before.
        travel = _line_travel(n.track_id, tags, station)
        arriving = None if travel is None else (travel == "Nominal") == below
        if arriving is None:
            arriving = cfg in ("Double", "Multiple")
            side = ""
        else:
            side = ", arrival end" if arriving else ", departure end"
        if arriving:
            cands = [e for e in elements if e.track_id == n.track_id
                     and ("BSLB" in e.element_type or "Home" in e.element_type)]
            target = "Home signal / BSLB"
        else:
            cands = [e for e in elements if e.track_id == n.track_id
                     and "Advance" in e.element_type and "Starter" in e.element_type]
            target = "Advanced Starter"
        best = min(cands, key=lambda e: abs(e.location_m - inner), default=None)
        ok = best is not None and abs(best.location_m - inner) <= tol
        out.append(CheckResult(
            "H2.22", title, "PASS" if ok else "FAIL",
            f"TIN {n.tin_no} ({cfg.lower()} line{side}) ends at {inner:g} m; "
            + (f"{best.element_type} {best.element_ref} at {best.location_m:g} m" if best else f"no {target} recorded on this line")
            + ("" if ok or best is None else f" -- more than {tol:g} m apart"),
            subject_ref=str(n.tin_no)))
    return out


# ---------------------------------------------------------------------------
# H2.26
# ---------------------------------------------------------------------------
def check_h2_26_not_to_scale(station: Station) -> list[CheckResult]:
    if station.drawn_to_scale:
        return [CheckResult("H2.26", "'Not drawn to scale' note", "PASS", "Layout drawn to scale")]
    ok = station.not_to_scale_note_present
    return [CheckResult("H2.26", "'Not drawn to scale' note", "PASS" if ok else "FAIL",
                        "Layout not drawn to scale; note " + ("present" if ok else "missing"))]


# ---------------------------------------------------------------------------
# New-TAN rules
# ---------------------------------------------------------------------------
def check_tan_dead_stop(tags: list[Tag], elements: list[Element], p: dict | None = None) -> list[CheckResult]:
    p = _params("tan_dead_stop", p)
    lo, hi = p["min_m"], p["max_m"]
    title = f"Dead stop tag {lo:g}-{hi:g} m from facing points"
    points = [e for e in elements if e.element_type == POINTS]
    els = {e.id: e for e in elements}
    out = []
    for t in tags:
        if t.tag_type != "D":
            continue
        linked = els.get(t.linked_element_id)
        if linked is not None and linked.element_type == POINTS:
            pt = linked
        else:
            same = [e for e in points if t.track_id is None or e.track_id in (None, t.track_id)]
            pt = min(same, key=lambda e: abs(e.location_m - t.location_m), default=None)
        if pt is None:
            out.append(CheckResult("TAN-1", title, "FAIL", f"{t.tag_ref}: no points recorded to measure from",
                                   subject_ref=t.tag_ref))
            continue
        gap = abs(pt.location_m - t.location_m)
        ok = lo <= gap <= hi
        out.append(CheckResult("TAN-1", title, "PASS" if ok else "FAIL",
                               f"{t.tag_ref} is {gap:.0f} m from points {pt.element_ref}", subject_ref=t.tag_ref))
    return out


def check_tan_adjacent_line_tag(tags: list[Tag], elements: list[Element], p: dict | None = None) -> list[CheckResult]:
    p = _params("tan_l_tag", p)
    lo, hi = p["min_m"], p["max_m"]
    title = f"Adjacent line tag {lo:g}-{hi:g} m after the last stop signal"
    els = {e.id: e for e in elements}
    out = []
    for t in tags:
        if t.tag_type != "L":
            continue
        el = els.get(t.linked_element_id)
        if el is None:
            out.append(CheckResult("TAN-2", title, "FAIL", f"{t.tag_ref}: link it to its last stop signal "
                                   "(Linked element) so the distance can be checked", subject_ref=t.tag_ref))
            continue
        gap = abs(el.location_m - t.location_m)
        ok = lo <= gap <= hi
        out.append(CheckResult("TAN-2", title, "PASS" if ok else "FAIL",
                               f"{t.tag_ref} is {gap:.0f} m from {el.element_ref}", subject_ref=t.tag_ref))
    return out


def check_tan_after_adjustment(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    """After an adjustment (A) tag, the next tags in the direction of travel must follow
    at no more than (0.5 x max section speed + 10) m each: the first within that
    distance of the A tag, each later one within that distance of the one before
    (QFTL 26.09.2026 -- Aler: R-862 at 261.083 (ABS-1, the physical location),
    R-864 14 m on, R-866 75 m after that). All tag types count."""
    p = _params("tan_after_a", p)
    reach = 0.5 * p["max_speed_kmph"] + 10
    need = int(p["normal_tags"])
    title = f"Next {need} tags each within {reach:g} m after an adjustment tag"
    out = []
    for a in tags:
        if a.tag_type != "A":
            continue
        same = [t for t in tags if t.id != a.id
                and (a.track_id is None or t.track_id in (None, a.track_id))
                and (a.direction is None or t.direction in (None, a.direction))]
        if a.direction == "Reverse":        # travel towards decreasing km
            ahead = sorted((t for t in same if t.location_m < a.location_m), key=lambda t: -t.location_m)
        elif a.direction == "Nominal":
            ahead = sorted((t for t in same if t.location_m > a.location_m), key=lambda t: t.location_m)
        else:
            ahead = sorted((t for t in same if t.location_m != a.location_m),
                           key=lambda t: abs(t.location_m - a.location_m))
        chain, prev, bad = [], a, None
        for t in ahead[:need]:
            gap = abs(t.location_m - prev.location_m)
            chain.append(f"{t.tag_ref} +{gap:g} m")
            if gap > reach and bad is None:
                bad = f"{t.tag_ref} is {gap:g} m after {prev.tag_ref}"
            prev = t
        ok = len(chain) >= need and bad is None
        why = bad or ("" if len(chain) >= need else f"only {len(chain)} tag(s) follow it on this line")
        out.append(CheckResult("TAN-3", title, "PASS" if ok else "FAIL",
                               f"{a.tag_ref}: " + (", ".join(chain) if chain else "no tags follow it")
                               + (f" -- {why}" if why else ""), subject_ref=a.tag_ref))
    return out


# ---------------------------------------------------------------------------
# Zone direction convention: SIP Up/Down vs KAVACH Nominal/Reverse
# ---------------------------------------------------------------------------
def sip_to_kavach(sip_direction: str | None, dn_direction: str) -> str | None:
    """'Down'/'DN' -> the zone's dn_direction; 'Up' -> the other one. None if the
    value isn't a SIP direction (already Nominal/Reverse, blank, ...)."""
    d = (sip_direction or "").strip().lower()
    other = "Reverse" if dn_direction == "Nominal" else "Nominal"
    if d in ("down", "dn", "d"):
        return dn_direction
    if d in ("up", "u"):
        return other
    return None


def check_direction_convention(station: Station, elements: list[Element], tags: list[Tag]) -> list[CheckResult]:
    """A tag linked to a signal must run in that signal's direction, translated with
    the workspace's convention (SCR: SIP Down = Nominal; ECR: SIP Up = Nominal)."""
    title = "Tag direction matches its signal"
    conv = (f"{station.workspace_code + ': ' if station.workspace_code else ''}SIP Down = "
            f"{station.dn_direction}")
    els = {e.id: e for e in elements}
    out = []
    for t in tags:
        el = els.get(t.linked_element_id)
        if el is None or not t.direction:
            continue
        want = sip_to_kavach(el.direction, station.dn_direction)
        if want is None:
            continue
        ok = t.direction == want
        out.append(CheckResult(
            "DIR-CONV", title, "PASS" if ok else "FAIL",
            f"{t.tag_ref} ({t.direction}) linked to {el.element_ref} ({el.direction})"
            + ("" if ok else f" -- expected {want} ({conv})"), subject_ref=t.tag_ref))
    # a line's direction against its line type (DN MAIN / DN LOOP run the zone's DN
    # direction, UP lines the other one, COMMON LOOP both ways)
    from ..domain import expected_line_direction
    for tr in station.tracks:
        want = expected_line_direction(getattr(tr, "line_type", None), station.dn_direction)
        if want is None or not tr.direction:
            continue
        ok = tr.direction == want
        out.append(CheckResult(
            "DIR-CONV", "Line direction matches its line type", "PASS" if ok else "FAIL",
            f"{tr.name} ({tr.line_type}) runs {tr.direction}"
            + ("" if ok else f" -- a {tr.line_type} line normally runs {want} ({conv})"), subject_ref=tr.name))
    return out


def gate_tag_wl_alternative(tag: Tag, gate: Element, elements: list[Element], reach_m: float) -> Element | None:
    """H2.9 alternative: a Whistle Board (W/L) on the approach to the LC gate, on the
    same side of the gate as the gate tag."""
    side = 1 if tag.location_m >= gate.location_m else -1
    for e in elements:
        if e.element_type != "Whistle Board (W/L)":
            continue
        if gate.track_id is not None and e.track_id not in (None, gate.track_id):
            continue
        d = (e.location_m - gate.location_m) * side
        if 0 < d <= reach_m:
            return e
    return None


__all__ = ["check_h2_8_tin_demarcation", "check_h2_17_tin_colours", "check_h2_20_exit_at_sidings",
           "check_h2_22_block_tin_extent", "check_h2_26_not_to_scale", "check_tan_dead_stop",
           "check_tan_adjacent_line_tag", "check_tan_after_adjustment", "gate_tag_wl_alternative",
           "neighbouring_tins", "LC_GATE"]


# ---------------------------------------------------------------------------
# Turnout tags: every points / turnout has its TIN-discrimination (T) tag on it, and
# every T tag lies on a turnout -- between the A-end and B-end of points (the one it
# is linked to, if linked). Catches a T tag entered at the wrong chainage, which
# otherwise just goes missing from its turnout on the drawing.
# ---------------------------------------------------------------------------
def check_turnout_t_tags(tags: list[Tag], elements: list[Element], p: dict | None = None) -> list[CheckResult]:
    p = _params("turnout_t_tags", p)
    tol = float(p.get("tolerance_m", 5.0))
    title = "Turnout (T) tag between the A-end and B-end of its points"
    points = [e for e in elements if e.element_type == POINTS]
    els = {e.id: e for e in elements}
    out = []

    def span(e):
        b = e.b_end_m if getattr(e, "b_end_m", None) is not None else e.location_m
        return min(e.location_m, b) - tol, max(e.location_m, b) + tol

    def desc(e):
        b = getattr(e, "b_end_m", None)
        return (f"{e.element_ref} (A {e.location_m / 1000:.3f}" +
                (f" / B {b / 1000:.3f})" if b is not None else ", B-end not recorded)"))
    t_tags = [t for t in tags if t.tag_type == "T"]
    used: dict[int, list] = {}
    for t in t_tags:
        linked = els.get(t.linked_element_id)
        if linked is not None and linked.element_type == POINTS:
            lo, hi = span(linked)
            ok = lo <= t.location_m <= hi
            out.append(CheckResult("DATA-TURNOUT", title, "PASS" if ok else "FAIL",
                                   f"{t.tag_ref} at {t.location_m / 1000:.3f} " +
                                   ("is on " if ok else "is not between the ends of ") + desc(linked),
                                   subject_ref=t.tag_ref))
            used.setdefault(linked.id, []).append(t)
            continue
        on = [e for e in points if span(e)[0] <= t.location_m <= span(e)[1]]
        if not on:
            near = min(points, key=lambda e: min(abs(t.location_m - x) for x in span(e)), default=None)
            hint = f" -- nearest is {desc(near)}" if near is not None else ""
            out.append(CheckResult("DATA-TURNOUT", title, "WARN",
                                   f"{t.tag_ref} at {t.location_m / 1000:.3f} is not on any turnout{hint}. "
                                   "Check its chainage, or link it to its points (Linked element)",
                                   subject_ref=t.tag_ref))
            continue
        # the turnout it belongs to: one whose lines include the tag's line, then the nearest middle
        best = min(on, key=lambda e: (t.track_id is not None and t.track_id not in (e.track_id, e.to_track_id),
                                      abs(t.location_m - sum(span(e)) / 2)))
        used.setdefault(best.id, []).append(t)
    for e in points:
        if e.to_track_id is None:
            continue                       # leads off the KAVACH lines (siding): no T tag needed
        mine = used.get(e.id, [])
        if not mine:
            out.append(CheckResult("DATA-TURNOUT", title, "WARN",
                                   f"No T tag between the ends of {desc(e)}", subject_ref=e.element_ref))
        elif len(mine) > 1 and len({round(t.location_m) for t in mine}) < len(mine):
            out.append(CheckResult("DATA-TURNOUT", title, "WARN",
                                   f"{' and '.join(t.tag_ref for t in mine)} are at the same chainage on "
                                   f"{e.element_ref} -- one of them is probably entered at the wrong place",
                                   subject_ref=e.element_ref))
    return out


# ---------------------------------------------------------------------------
# Two different TINs overlapping on one line: one of them is usually a turnout piece
# entered as a TIN row on a loop (QFTL, Oct 2026: N-171 rows on COMMON LOOP painted
# over N-186). Turnouts take their colours from the lines' own TINs, so such rows
# should be deleted. Says which row looks like the stray one.
# ---------------------------------------------------------------------------
def check_tin_overlaps(station: Station, tins: list[TIN], tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    from ..drawing.layout import tin_doubt
    title = "No two TINs overlap on one line"
    names = {t.id: t.name for t in station.tracks}
    t_tags = [t for t in tags if t.tag_type == "T"]
    doubt = tin_doubt(tins, [t.location_m for t in t_tags])
    out = []

    def ext(n):
        return min(n.start_m, n.end_m), max(n.start_m, n.end_m)

    def why(n):
        r = []
        for t in t_tags:
            if abs(n.start_m - t.location_m) <= 2 or abs(n.end_m - t.location_m) <= 2:
                r.append(f"ends at turnout tag {t.tag_ref}")
                break
        others = sorted({names.get(o.track_id, "?") for o in tins if o.tin_no == n.tin_no and o.track_id != n.track_id})
        if others:
            r.append(f"TIN {n.tin_no} is also on {', '.join(others)}")
        return "; ".join(r)
    def rank(n):
        a0, a1 = ext(n)
        return (doubt[id(n)], a1 - a0)

    for r in tins:
        if r.track_id is None:
            continue
        r0, r1 = ext(r)
        same_line = [o for o in tins if o is not r and o.track_id == r.track_id]
        # entered twice: lies inside another row of the same TIN on the same line
        dup = next((o for o in same_line if o.tin_no == r.tin_no and ext(o)[0] <= r0 and r1 <= ext(o)[1]
                    and (ext(o) != (r0, r1) or id(o) < id(r))), None)
        if dup is not None:
            out.append(CheckResult("DATA-TIN", title, "WARN",
                                   f"TIN {r.tin_no} is entered twice on {names.get(r.track_id, '?')}: "
                                   f"{r0 / 1000:.3f}-{r1 / 1000:.3f} lies within {ext(dup)[0] / 1000:.3f}-"
                                   f"{ext(dup)[1] / 1000:.3f}" + (f" ({why(r)})" if why(r) else "")
                                   + " -- delete the shorter row", subject_ref=f"TIN {r.tin_no}"))
            continue
        over = [o for o in same_line if o.tin_no != r.tin_no and min(r1, ext(o)[1]) - max(r0, ext(o)[0]) > 1]
        if not over or not any(rank(o) < rank(r) for o in over):
            continue                       # nothing overlaps it, or it is the line's own TIN there
        mid = (max(r0, min(ext(o)[0] for o in over)) + min(r1, max(ext(o)[1] for o in over))) / 2
        shown = min([o for o in tins if o.track_id == r.track_id and ext(o)[0] - 1 <= mid <= ext(o)[1] + 1],
                    key=rank)
        reason = why(r)
        out.append(CheckResult(
            "DATA-TIN", title, "WARN",
            f"TIN {r.tin_no} ({r0 / 1000:.3f}-{r1 / 1000:.3f}) overlaps "
            f"{', '.join(sorted({f'TIN {o.tin_no}' for o in over}))} on {names.get(r.track_id, '?')}"
            + (f"; it looks like a turnout piece ({reason})" if reason else "")
            + f". The drawing shows TIN {shown.tin_no} there. Turnouts take their colours from the lines' "
              f"TINs -- delete this row.", subject_ref=f"TIN {r.tin_no}"))
    return out


# ---------------------------------------------------------------------------
# The same signal entered on two lines (QFTL, Oct 2026: S26/S27 on UP MAIN as well as
# COMMON LOOP / UP LOOP, S5/SH8 and SH22 on DN MAIN as well as COMMON LOOP, a second SB
# on UP MAIN). Shared by the drawing (draw one copy) and the data check (say which row
# to delete).
# ---------------------------------------------------------------------------
def _ref_parts(ref: str) -> set:
    import re
    return {p for p in re.split(r"[/\s,]+", (ref or "").upper()) if p}


def duplicate_elements(items: list, s_tags: list, line_type: dict, window_m: float = 60.0) -> dict:
    """items: [(key, ref, element_type, location_m, track_id)]; s_tags: [(ref, location_m,
    track_id)] signal-foot tags; line_type: track id -> line type. Returns {key: (kept
    item, why)} for each copy that should not be drawn: there is a copy of the same
    signal on another line within window_m that fits better -- a loop-line starter on a
    loop / a main-line starter on a main line, then nearer its signal-foot tag."""
    def fit(it):
        t, lt = (it[2] or "").lower(), (line_type.get(it[4]) or "").upper()
        if "loopline" in t or "loop line" in t:
            return 0 if "LOOP" in lt else 1
        if "mainline" in t or "main line" in t:
            return 0 if "MAIN" in lt else 1
        return 0

    def foot(it):
        near = [(abs(m - it[3]), r) for r, m, tid in s_tags if tid == it[4]]
        return min(near) if near else (999.0, None)

    def score(it):
        return (fit(it), round(foot(it)[0], 1))
    out = {}
    for it in items:
        if "points" in (it[2] or "").lower() or "lc gate" in (it[2] or "").lower():
            continue
        parts = _ref_parts(it[1])
        better = [o for o in items if o is not it and o[4] != it[4] and o[4] is not None
                  and _ref_parts(o[1]) & parts and abs(o[3] - it[3]) <= window_m and score(o) < score(it)]
        if better:
            kept = min(better, key=score)
            why = []
            if fit(kept) < fit(it):
                why.append(f"{kept[2]} belongs on a {'loop' if 'loop' in (kept[2] or '').lower() else 'main'} line")
            f = foot(kept)
            if f[1] is not None and f[0] <= 10:
                why.append(f"its signal-foot tag {f[1]} is there")
            out[it[0]] = (kept, "; ".join(why))
    return out


def check_duplicate_elements(station: Station, elements: list[Element], tags: list[Tag],
                             p: dict | None = None) -> list[CheckResult]:
    title = "Each signal entered on one line only"
    names = {t.id: t.name for t in station.tracks}
    lt = {t.id: getattr(t, "line_type", "") for t in station.tracks}
    items = [(e.id, e.element_ref, e.element_type, e.location_m, e.track_id) for e in elements]
    s_tags = [(t.tag_ref, t.location_m, t.track_id) for t in tags if t.tag_type == "S"]
    dups = duplicate_elements(items, s_tags, lt)
    out = []
    for e in elements:
        if e.id not in dups:
            continue
        kept, why = dups[e.id]
        out.append(CheckResult(
            "DATA-DUP", title, "WARN",
            f"{e.element_ref} is entered on {names.get(e.track_id, '?')} ({e.location_m / 1000:.3f}) and as "
            f"{kept[1]} on {names.get(kept[4], '?')} ({kept[3] / 1000:.3f}); the drawing shows the "
            f"{names.get(kept[4], '?')} one" + (f" ({why})" if why else "") +
            f". Delete the {names.get(e.track_id, '?')} row if it is the same signal.",
            subject_ref=e.element_ref))
    return out
