"""Checks from the QFTL design & verification deck that the first rule set left manual:

  H2.14  repeated tag / TIN numbers beyond the 25 / 10 / 50 km limits
  H2.7   a Normal, gate (merged) or shunt-signal tag 150-250 m before every main signal
  TAN-4  a shunt signal's foot tag that is a main signal's approach tag is N, not S
  H2.6   a virtual BSLB (S tag) where a block section ends with no BSLB board
  H2.21  TIN bifurcated between a shunt signal and the advance starter (common loop reception)

Pure functions over the domain dataclasses, same contract as layout_rules.py.
"""
from __future__ import annotations

from ..domain import Element, Station, Tag, TIN, is_starter_signal_eligible_for_h2_7_exception, requires_signal_foot_tag
from .engine import CheckResult, _params
from .layout_rules import _hi, _line_travel, _lo, _no_lines, _side_config, _track_name, _tins_by_track


# ---------------------------------------------------------------------------
# H2.14  A tag number may not repeat within 25 km; a station-section TIN may repeat after
# 10 km, a block-section TIN after 50 km. Needs the other layouts in range
# (Station.nearby: workspace stations linked to this one). The same tag shown on two
# neighbouring layouts (same number, same chainage) and the same block section shown on
# both (overlapping TIN extent) are one thing, not a repeat.
# ---------------------------------------------------------------------------
def check_h2_14_repeat_limits(station: Station, tags: list[Tag], tins: list[TIN],
                              p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_14_repeat", p)
    title = "Tag / TIN numbers not repeated within the limits"
    if not station.nearby:
        why = ("no other station's layout in the workspace is linked to this one within range"
               if station.centre_line_m is not None else
               "this station's centre line is not recorded, so nearby layouts cannot be found")
        return [CheckResult("H2.14", title, "NA", f"Not checked: {why}")]
    tag_lim, tin_stn, tin_blk = p["tag_radius_m"], p["tin_station_m"], p["tin_block_m"]
    out: list[CheckResult] = []
    for t in tags:
        if t.tag_number is None:
            continue
        for o in station.nearby:
            for ref, num, loc in o.tags:
                gap = abs(loc - t.location_m)
                if num == t.tag_number and 1 < gap < tag_lim:
                    out.append(CheckResult(
                        "H2.14", title, "FAIL",
                        f"Tag number {num}: {t.tag_ref} here and {ref} at {o.name} are {gap / 1000:.1f} km "
                        f"apart (a tag number may not repeat within {tag_lim / 1000:g} km)", subject_ref=t.tag_ref))
    seen = set()
    for n in tins:
        for o in station.nearby:
            for no, sec, lo, hi in o.tins:
                if no != n.tin_no or (_lo(n) <= hi and lo <= _hi(n)):
                    continue                      # other TIN, or the same section drawn on both layouts
                gap = max(lo - _hi(n), _lo(n) - hi)
                block = (n.section_type or "").lower() == "block" or (sec or "").lower() == "block"
                lim = tin_blk if block else tin_stn
                if gap < lim and (n.tin_no, o.name) not in seen:
                    seen.add((n.tin_no, o.name))
                    out.append(CheckResult(
                        "H2.14", title, "FAIL",
                        f"TIN {n.tin_no} here and at {o.name} are {gap / 1000:.1f} km apart "
                        f"({'block' if block else 'station'}-section TINs may repeat only after "
                        f"{lim / 1000:g} km)", subject_ref=str(n.tin_no)))
    if not out:
        out.append(CheckResult(
            "H2.14", title, "PASS",
            f"No tag number repeats within {tag_lim / 1000:g} km and no TIN within {tin_stn / 1000:g} km "
            f"(station) / {tin_blk / 1000:g} km (block), checked against "
            f"{', '.join(o.name for o in station.nearby)}"))
    return out


# ---------------------------------------------------------------------------
# Approach / merged tags and shunt-signal foot tags
# ---------------------------------------------------------------------------
_NOT_MAIN = ("Shunt", "Calling-on", "Calling on", "BSLB", "Stop Board", "Buffer Stop", "Berthing")


def is_main_signal(element_type: str) -> bool:
    return requires_signal_foot_tag(element_type) and not any(k in element_type for k in _NOT_MAIN)


def _behind(ref: Tag, t: Tag) -> float | None:
    """How far t lies behind ref in ref's direction of travel (Nominal = towards higher
    km); the plain distance when ref has no direction. None when t runs the other way
    or is on another line."""
    if ref.track_id is not None and t.track_id not in (None, ref.track_id):
        return None
    if ref.direction and t.direction not in (None, ref.direction):
        return None
    if ref.direction == "Nominal":
        return ref.location_m - t.location_m
    if ref.direction == "Reverse":
        return t.location_m - ref.location_m
    return abs(ref.location_m - t.location_m)


def _main_foot_tags(tags: list[Tag], elements: list[Element]) -> list[tuple[Tag, Element]]:
    els = {e.id: e for e in elements}
    return [(t, els[t.linked_element_id]) for t in tags
            if t.tag_type == "S" and t.linked_element_id in els and is_main_signal(els[t.linked_element_id].element_type)]


def shunt_approach_target(tag: Tag, tags: list[Tag], elements: list[Element], lo: float, hi: float):
    """The main signal's foot tag that `tag` (at a shunt signal) serves as the approach
    tag for: one lying lo..hi m ahead of it. None if there is none."""
    for s, el in _main_foot_tags(tags, elements):
        d = _behind(s, tag)
        if d is not None and lo <= d <= hi:
            return s, el
    return None


def check_merged_approach(station: Station, tags: list[Tag], elements: list[Element],
                          p: dict | None = None) -> list[CheckResult]:
    """Every main signal has a Normal, LC-gate (merged) or shunt-signal tag 150-250 m
    (preferably 200 m) before its foot tag. A signal with a linked N tag is judged by
    H2.7; this covers the ones without -- notably where a G tag doubles as the approach tag."""
    p = _params("h2_7_merged", p)
    lo, hi, pref = p["min_m"], p["max_m"], p["preferred_m"]
    title = f"Approach tag ({lo:g}-{hi:g} m, preferably {pref:g} m) for every main signal"
    linked_n = {t.linked_element_id for t in tags if t.tag_type == "N" and t.linked_element_id}
    els = {e.id: e for e in elements}
    out = []
    for s, el in _main_foot_tags(tags, elements):
        if el.id in linked_n:
            continue
        starter = p["starter_exception"] and is_starter_signal_eligible_for_h2_7_exception(el.element_type)
        best = None
        for t in tags:
            if t is s or t.tag_type not in ("N", "G", "S", "L"):
                continue
            if t.tag_type == "S":                 # only a shunt signal's foot tag can double as an approach tag
                e2 = els.get(t.linked_element_id)
                if e2 is None or "Shunt" not in e2.element_type:
                    continue
            d = _behind(s, t)
            if d is None or not (0 < d <= hi) or (d < lo and not starter):
                continue
            if best is None or abs(d - pref) < abs(best[0] - pref):
                best = (d, t)
        if best is None:
            out.append(CheckResult("H2.7", title, "FAIL",
                                   f"{el.element_ref} ({s.tag_ref}): no Normal, gate or shunt-signal tag "
                                   f"{lo:g}-{hi:g} m before its Signal Foot Tag", subject_ref=el.element_ref))
            continue
        d, t = best
        kind = {"G": "merged approach / gate tag", "S": "shunt-signal tag acting as the approach tag"}.get(
            t.tag_type, "approach tag")
        note = f" (preferably {pref:g} m)" if t.tag_type == "G" and abs(d - pref) > 25 else ""
        out.append(CheckResult("H2.7", title, "PASS",
                               f"{el.element_ref} ({s.tag_ref}): {t.tag_ref} ({t.tag_type}) is {d:.0f} m before it "
                               f"-- {kind}{note}", subject_ref=el.element_ref))
    return out


def check_shunt_foot_as_normal(station: Station, tags: list[Tag], elements: list[Element],
                               p: dict | None = None) -> list[CheckResult]:
    """Where a shunt signal's foot tag is the approach tag for the next main signal it is
    designated N (Normal), not S. Flags an S tag in that position, and an N tag linked to a
    shunt signal that is not in that position."""
    p = _params("tan_shunt_n", p)
    lo, hi = p["min_m"], p["max_m"]
    title = "Shunt-signal tag serving as a main signal's approach tag is a Normal tag"
    els = {e.id: e for e in elements}
    out = []
    for t in tags:
        el = els.get(t.linked_element_id)
        if el is None or "Shunt" not in el.element_type or t.tag_type not in ("S", "N"):
            continue
        target = shunt_approach_target(t, tags, elements, lo, hi)
        if t.tag_type == "S" and target is not None:
            s, main = target
            out.append(CheckResult("TAN-4", title, "FAIL",
                                   f"{t.tag_ref} (S) at shunt signal {el.element_ref} is {abs(s.location_m - t.location_m):.0f} m "
                                   f"before the foot tag of {main.element_ref} -- it is that signal's approach tag, so "
                                   f"designate it N", subject_ref=t.tag_ref))
        elif t.tag_type == "N" and target is None:
            out.append(CheckResult("TAN-4", title, "WARN",
                                   f"{t.tag_ref} (N) is linked to shunt signal {el.element_ref} but is not "
                                   f"{lo:g}-{hi:g} m before any main signal's foot tag -- a shunt signal that is not "
                                   f"an approach tag takes an S tag", subject_ref=t.tag_ref))
        else:
            out.append(CheckResult("TAN-4", title, "PASS",
                                   f"{t.tag_ref} ({t.tag_type}) at shunt signal {el.element_ref}", subject_ref=t.tag_ref))
    return out


# ---------------------------------------------------------------------------
# Virtual BSLB: where a block section ends with no BSLB board (nor a home signal) a
# virtual BSLB -- an S tag -- is provided at the end of the block TIN.
# ---------------------------------------------------------------------------
def check_virtual_bslb(station: Station, elements: list[Element], tags: list[Tag], tins: list[TIN],
                       p: dict | None = None) -> list[CheckResult]:
    tol = _params("virtual_bslb", p)["tolerance_m"]
    title = "BSLB board, or a virtual BSLB (S tag), at the arrival end of a block TIN"
    blocks = [n for n in tins if (n.section_type or "").lower() == "block" and not n.is_non_kavach_territory
              and n.track_id is not None]
    if not blocks or not station.tracks or station.centre_line_m is None:
        return []
    out = []
    for n in blocks:
        below = (_lo(n) + _hi(n)) / 2 < station.centre_line_m
        inner = _hi(n) if below else _lo(n)
        cfg = _side_config(station, below)
        travel = _line_travel(n.track_id, tags, station)
        arriving = (cfg in ("Double", "Multiple")) if travel is None else (travel == "Nominal") == below
        if not arriving or cfg not in ("Double", "Multiple"):
            continue
        board = next((e for e in elements if e.track_id == n.track_id and abs(e.location_m - inner) <= tol
                      and ("BSLB" in e.element_type or "Home" in e.element_type)), None)
        if board is not None:
            continue                                    # a real board: H2.6 / H2.22 judge it
        s_tag = next((t for t in tags if t.tag_type == "S" and t.track_id in (None, n.track_id)
                      and abs(t.location_m - inner) <= tol), None)
        if s_tag is not None:
            out.append(CheckResult("H2.6", title, "PASS",
                                   f"TIN {n.tin_no}: no BSLB board at {inner:g} m; {s_tag.tag_ref} (S) acts as the "
                                   f"virtual BSLB", subject_ref=str(n.tin_no)))
        else:
            out.append(CheckResult("H2.6", title, "FAIL",
                                   f"TIN {n.tin_no} ends at {inner:g} m with no BSLB board and no virtual BSLB "
                                   f"(S tag) within {tol:g} m", subject_ref=str(n.tin_no)))
    return out


# ---------------------------------------------------------------------------
# TIN bifurcation for common-loop reception: a loco standing between a shunt signal and
# the advance starter must be in a TIN of its own, so a TIN boundary lies between them.
# ---------------------------------------------------------------------------
def check_tin_bifurcation(station: Station, elements: list[Element], tins: list[TIN],
                          p: dict | None = None) -> list[CheckResult]:
    p = _params("tin_bifurcation", p)
    title = "TIN bifurcated between a shunt signal and the advance starter"
    if not tins or _no_lines("H2.21", title, station) is not None:
        return []
    tol, span = p["tolerance_m"], p["max_span_m"]
    by_track = _tins_by_track([n for n in tins if not n.is_non_kavach_territory])
    out = []
    for a in elements:
        if not ("Advance" in a.element_type and "Starter" in a.element_type) or a.track_id not in by_track:
            continue
        sh = [e for e in elements if "Shunt" in e.element_type and e.track_id == a.track_id
              and 0 < abs(e.location_m - a.location_m) <= span]
        if not sh:
            continue
        s = min(sh, key=lambda e: abs(e.location_m - a.location_m))
        lo, hi = sorted((s.location_m, a.location_m))
        lst = by_track[a.track_id]
        cut = any(x.tin_no != y.tin_no and lo - tol <= (_hi(x) + _lo(y)) / 2 <= hi + tol
                  for x, y in zip(lst, lst[1:]))
        out.append(CheckResult("H2.21", title, "PASS" if cut else "FAIL",
                               f"{s.element_ref} ({s.location_m:g} m) to {a.element_ref} ({a.location_m:g} m) on "
                               f"{_track_name(station, a.track_id)}: "
                               + ("a TIN boundary lies between them" if cut else
                                  "one TIN runs across both -- split it so a loco standing between them has its own TIN"),
                               subject_ref=a.element_ref))
    return out
