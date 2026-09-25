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


def check_h2_22_block_tin_extent(station: Station, elements: list[Element], tins: list[TIN],
                                 p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_22", p)
    title = "Block TIN extended to BSLB / Advance Starter"
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
        want = "BSLB" if cfg in ("Double", "Multiple") else "Advance"
        cands = [e for e in elements if e.track_id == n.track_id and want in e.element_type
                 and (want != "Advance" or "Starter" in e.element_type)]
        best = min(cands, key=lambda e: abs(e.location_m - inner), default=None)
        ok = best is not None and abs(best.location_m - inner) <= tol
        target = "the BSLB" if want == "BSLB" else "the Advance Starter"
        out.append(CheckResult(
            "H2.22", title, "PASS" if ok else "FAIL",
            f"TIN {n.tin_no} ({cfg.lower()} line) ends at {inner:g} m; "
            + (f"{best.element_ref} at {best.location_m:g} m" if best else f"no {target} recorded on this line")
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
    p = _params("tan_after_a", p)
    reach = 0.5 * p["max_speed_kmph"] + 10
    need = int(p["normal_tags"])
    title = f"{need} Normal tags within {reach:g} m of an adjustment tag"
    out = []
    for a in tags:
        if a.tag_type != "A":
            continue
        near = [t for t in tags if t.tag_type == "N" and t.id != a.id
                and (a.track_id is None or t.track_id in (None, a.track_id))
                and (a.direction is None or t.direction in (None, a.direction))
                and 0 < abs(t.location_m - a.location_m) <= reach]
        ok = len(near) >= need
        out.append(CheckResult("TAN-3", title, "PASS" if ok else "FAIL",
                               f"{a.tag_ref}: {len(near)} Normal tag(s) within {reach:g} m"
                               + (f" ({', '.join(t.tag_ref for t in near[:4])})" if near else ""),
                               subject_ref=a.tag_ref))
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
