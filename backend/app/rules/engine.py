"""
Codified checks against RDSO/SPN/196/2020 Annexure-H (Amdt-5), "KAVACH RFID Tag-TIN
Layout Guidelines". Each check function is named after and cites its clause, and
returns CheckResult objects so a Checker can verify the tool's reasoning by reading
the clause reference, not just trusting a pass/fail.

Design note: a few clauses (H2.3, H2.4, H2.17 partial, H2.19, H2.24-H2.26, H2.28) are
inherently about visual/topological judgement on the actual drawing (e.g. "does the
TIN layout permit all Table-of-Control movements") and are NOT checked here -- see
MANUAL_CLAUSES at the bottom. Silently skipping them would be worse than listing them;
a Checker still has to look, but knows exactly what the tool did and didn't verify.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..domain import (
    Element, Tag, TIN, Station, TAG_TYPES,
    requires_signal_foot_tag, is_starter_signal_eligible_for_h2_7_exception,
)

Status = Literal["PASS", "FAIL", "WARN", "NA"]


@dataclass
class CheckResult:
    clause: str            # e.g. "H2.5"
    title: str              # short human label
    status: Status
    message: str
    subject_ref: str | None = None  # tag_ref / element_ref this result is about, if any


@dataclass
class VerificationReport:
    results: list[CheckResult] = field(default_factory=list)

    def add(self, *results: CheckResult):
        self.results.extend(results)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    def by_clause(self) -> dict[str, list[CheckResult]]:
        out: dict[str, list[CheckResult]] = {}
        for r in self.results:
            out.setdefault(r.clause, []).append(r)
        return out

    def summary(self) -> dict:
        by_clause = self.by_clause()
        return {
            "total_checks": len(self.results),
            "fail_count": self.fail_count,
            "warn_count": self.warn_count,
            "clauses_checked": sorted(by_clause.keys()),
            "clauses_failing": sorted(c for c, rs in by_clause.items()
                                       if any(r.status == "FAIL" for r in rs)),
        }


def _params(key: str, p: dict | None) -> dict:
    """Defaults for a built-in rule, overlaid with configured params (FR-006)."""
    from .checklist import BUILTINS, _ensure
    _ensure()
    return {**BUILTINS[key]["defaults"], **(p or {})}


# ---------------------------------------------------------------------------
# H2.1 Version control
# ---------------------------------------------------------------------------
def check_h2_1_version_control(station: Station) -> list[CheckResult]:
    ok = station.layout_version != "INCOMPLETE"
    return [CheckResult(
        "H2.1", "Version control X.Y.Z complete",
        "PASS" if ok else "FAIL",
        f"Layout version: {station.layout_version}" if ok else
        "KAVACH/SIP/Guideline version fields incomplete -- X.Y.Z cannot be composed",
    )]


# ---------------------------------------------------------------------------
# H2.2 SIP drawing number + stationary KAVACH ID must be present
# ---------------------------------------------------------------------------
def check_h2_2_identifiers(station: Station) -> list[CheckResult]:
    results = []
    results.append(CheckResult(
        "H2.2", "Stationary KAVACH ID present",
        "PASS" if station.kavach_station_id else "FAIL",
        station.kavach_station_id or "Stationary KAVACH ID is blank",
    ))
    results.append(CheckResult(
        "H2.2", "Reference SIP drawing number present",
        "PASS" if station.sip_drawing_number else "FAIL",
        station.sip_drawing_number or "Reference SIP drawing number is blank",
    ))
    return results


# ---------------------------------------------------------------------------
# H2.5 Normal tag spacing <= 1000m between consecutive Normal tags
# ---------------------------------------------------------------------------
def check_h2_5_normal_tag_spacing(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_5", p)
    mx = p["max_gap_m"]
    title = f"Normal tag spacing <= {mx:g}m"
    results = []
    normals = sorted(
        [t for t in tags if t.tag_type in p["tag_types"]],
        key=lambda t: (t.direction or "", t.location_m),
    )
    by_dir: dict[str, list[Tag]] = {}
    for t in normals:
        by_dir.setdefault(t.direction or "?", []).append(t)

    for direction, group in by_dir.items():
        for prev, curr in zip(group, group[1:]):
            gap_m = abs(curr.location_m - prev.location_m)
            if gap_m > mx:
                results.append(CheckResult(
                    "H2.5", title, "FAIL",
                    f"{prev.tag_ref} -> {curr.tag_ref}: {gap_m:.0f}m apart (max {mx:g}m)",
                    subject_ref=curr.tag_ref,
                ))
            else:
                results.append(CheckResult(
                    "H2.5", title, "PASS",
                    f"{prev.tag_ref} -> {curr.tag_ref}: {gap_m:.0f}m", subject_ref=curr.tag_ref,
                ))
    return results


# ---------------------------------------------------------------------------
# H2.6 Every Main/Subsidiary signal, Stop board, berthing-track end, BSLB
# must have a Signal Foot Tag (S)
# ---------------------------------------------------------------------------
def check_h2_6_signal_foot_tags(elements: list[Element], tags: list[Tag]) -> list[CheckResult]:
    results = []
    linked_element_ids = {t.linked_element_id for t in tags if t.tag_type == "S" and t.linked_element_id}
    for el in elements:
        if not requires_signal_foot_tag(el.element_type):
            continue
        ok = el.id in linked_element_ids
        results.append(CheckResult(
            "H2.6", "Signal Foot Tag present", "PASS" if ok else "FAIL",
            f"{el.element_type} '{el.element_ref}' "
            + ("has a linked Signal Foot Tag" if ok else "has NO linked Signal Foot Tag"),
            subject_ref=el.element_ref,
        ))
    return results


# ---------------------------------------------------------------------------
# H2.7 Normal (Signal Approach) tag 150-250m before Main Signal's Signal Foot Tag.
# Exception: may be <150m for Advance Starter / Intermediate Starter (and their
# "...-cum-Starter..." combination signal variants -- see
# is_starter_signal_eligible_for_h2_7_exception() in domain.py).
# ---------------------------------------------------------------------------
def check_h2_7_approach_tag_distance(tags: list[Tag], elements: list[Element],
                                     p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_7", p)
    lo, hi = p["min_m"], p["max_m"]
    title = f"Approach tag {lo:g}-{hi:g}m before Signal Foot Tag"
    results = []
    elements_by_id = {e.id: e for e in elements}
    s_tags_by_element = {t.linked_element_id: t for t in tags if t.tag_type == "S" and t.linked_element_id}

    for t in tags:
        if t.tag_type != "N" or not t.linked_element_id:
            continue
        s_tag = s_tags_by_element.get(t.linked_element_id)
        if not s_tag:
            continue
        el = elements_by_id.get(t.linked_element_id)
        gap_m = abs(s_tag.location_m - t.location_m)
        is_starter = (p["starter_exception"] and el
                      and is_starter_signal_eligible_for_h2_7_exception(el.element_type))

        if lo <= gap_m <= hi:
            results.append(CheckResult(
                "H2.7", title, "PASS",
                f"{t.tag_ref} is {gap_m:.0f}m before {s_tag.tag_ref}", subject_ref=t.tag_ref,
            ))
        elif gap_m < lo and is_starter:
            results.append(CheckResult(
                "H2.7", title, "PASS",
                f"{t.tag_ref} is {gap_m:.0f}m before {s_tag.tag_ref} "
                f"(<{lo:g}m permitted -- exception for {el.element_type})", subject_ref=t.tag_ref,
            ))
        elif gap_m < lo:
            results.append(CheckResult(
                "H2.7", title, "FAIL",
                f"{t.tag_ref} is only {gap_m:.0f}m before {s_tag.tag_ref} "
                f"(<{lo:g}m only permitted for Advance/Intermediate Starter)", subject_ref=t.tag_ref,
            ))
        else:
            results.append(CheckResult(
                "H2.7", title, "FAIL",
                f"{t.tag_ref} is {gap_m:.0f}m before {s_tag.tag_ref} (exceeds {hi:g}m)",
                subject_ref=t.tag_ref,
            ))
    return results


# ---------------------------------------------------------------------------
# H2.9 Gate tag placed so auto-whistling can commence from >= 600m (or W/L board).
# NOTE: an earlier internal Excel tool used a 550-850m *range* for this, based on a
# secondary source deck. The Annexure-H text itself specifies only a *minimum* of
# 600m ("at least 600m or W/L board on approach of LC gate") -- no stated upper bound.
# This function follows the Annexure-H text; the 550-850m figure should be treated
# as superseded unless a Railway-specific circular says otherwise.
# ---------------------------------------------------------------------------
def check_h2_9_gate_tag_distance(tags: list[Tag], elements: list[Element],
                                 p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_9", p)
    lo, hi = p["min_m"], p.get("max_m")
    title = f"Gate tag {lo:g}-{hi:g}m from LC gate" if hi else f"Gate tag >= {lo:g}m approach to LC gate"
    results = []
    elements_by_id = {e.id: e for e in elements}
    for t in tags:
        if t.tag_type != "G" or not t.linked_element_id:
            continue
        el = elements_by_id.get(t.linked_element_id)
        if not el:
            continue
        gap_m = abs(el.location_m - t.location_m)
        ok = gap_m >= lo and (hi is None or gap_m <= hi)
        rng = f"{lo:g}-{hi:g}m" if hi else f">={lo:g}m"
        results.append(CheckResult(
            "H2.9", title, "PASS" if ok else "FAIL",
            f"{t.tag_ref} is {gap_m:.0f}m from LC gate '{el.element_ref}' "
            + (f"(within {rng})" if ok else f"(outside {rng}, or provide W/L board)"),
            subject_ref=t.tag_ref,
        ))
    return results


# ---------------------------------------------------------------------------
# H2.11 Exit tags: minimum 2 sets, each set >= 10m apart (H2.11(ii))
# ---------------------------------------------------------------------------
def check_h2_11_exit_tags(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_11", p)
    results = []
    exit_tags = [t for t in tags if t.tag_type == "X" and t.pair_group_id]
    groups: dict[str, list[Tag]] = {}
    for t in exit_tags:
        groups.setdefault(t.pair_group_id, []).append(t)

    for group_id, members in groups.items():
        sets = {m.exit_set for m in members if m.exit_set}
        if len(sets) < p["min_sets"]:
            results.append(CheckResult(
                "H2.11", f"Exit tag: minimum {p['min_sets']} sets", "FAIL",
                f"Exit tag group '{group_id}' has only {len(sets)} set(s); minimum {p['min_sets']} required",
                subject_ref=group_id,
            ))
            continue
        locs = [m.location_m for m in members]
        gap_m = (max(locs) - min(locs))
        ok = gap_m >= p["min_set_gap_m"]
        results.append(CheckResult(
            "H2.11", f"Exit tag sets >= {p['min_set_gap_m']:g}m apart", "PASS" if ok else "FAIL",
            f"Exit tag group '{group_id}': sets are {gap_m:.0f}m apart",
            subject_ref=group_id,
        ))
    return results


# ---------------------------------------------------------------------------
# H2.12 Duplicate tag pair 3-5m apart, EXCEPT TIN-discrimination/Turnout (T) and
# Adjustment (A) tags, which must be co-located (0m).
# ---------------------------------------------------------------------------
def _pair_groups(tags: list[Tag]) -> dict[str, list[Tag]]:
    groups: dict[str, list[Tag]] = {}
    for t in tags:
        if t.pair_group_id:
            groups.setdefault(t.pair_group_id, []).append(t)
    return {g: m for g, m in groups.items() if len(m) >= 2}


def check_h2_12_duplicate_spacing(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_12", p)
    dmin, dmax = p["dup_min_m"], p["dup_max_m"]
    results = []
    for group_id, members in _pair_groups(tags).items():
        locs = [m.location_m for m in members]
        gap_m = max(locs) - min(locs)
        if any(m.tag_type in ("T", "A") for m in members):
            ok = gap_m == 0
            results.append(CheckResult(
                "H2.12", "T/A tag pair co-located (0m)", "PASS" if ok else "FAIL",
                f"Group '{group_id}' (T/A): {gap_m:.0f}m apart"
                + ("" if ok else " -- must be same absolute location"),
                subject_ref=group_id,
            ))
        else:
            ok = dmin <= gap_m <= dmax
            results.append(CheckResult(
                "H2.12", f"Duplicate tag pair {dmin:g}-{dmax:g}m apart", "PASS" if ok else "FAIL",
                f"Group '{group_id}': {gap_m:.0f}m apart" + ("" if ok else f" (must be {dmin:g}-{dmax:g}m)"),
                subject_ref=group_id,
            ))
    return results


# ---------------------------------------------------------------------------
# H2.13 Tag-set (main + duplicate) to the next tag-set >= 10m.
# ---------------------------------------------------------------------------
def check_h2_13_tagset_spacing(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    tmin = _params("h2_13", p)["tagset_min_m"]
    extents = sorted(((g, min(m.location_m for m in ms), max(m.location_m for m in ms))
                      for g, ms in _pair_groups(tags).items()), key=lambda e: e[1])
    results = []
    for (id1, _, max1), (id2, min2, _) in zip(extents, extents[1:]):
        gap_m = min2 - max1
        if gap_m < 0:
            continue  # overlapping groups -- a data error, not a spacing result
        ok = gap_m >= tmin
        results.append(CheckResult(
            "H2.13", f"Tag-set to tag-set >= {tmin:g}m", "PASS" if ok else "FAIL",
            f"Group '{id1}' to group '{id2}': {gap_m:.0f}m apart",
            subject_ref=f"{id1}->{id2}",
        ))
    return results


# ---------------------------------------------------------------------------
# H2.15 Legend shape: Rectangle if main+duplicate co-located, Triangle if not
# (duplicate ahead of main in direction of travel, per triangle tip).
# ---------------------------------------------------------------------------
def check_h2_15_legend_shape(tags: list[Tag]) -> list[CheckResult]:
    results = []
    for group_id, members in _pair_groups(tags).items():
        locs = [m.location_m for m in members]
        expected_shape = "Rectangle" if max(locs) == min(locs) else "Triangle"
        shapes = {m.legend_shape for m in members if m.legend_shape}
        ok = shapes == {expected_shape}
        results.append(CheckResult(
            "H2.15", "Legend shape matches co-location", "PASS" if ok else "FAIL",
            f"Group '{group_id}': expected {expected_shape}, found {shapes or 'unset'}",
            subject_ref=group_id,
        ))
    return results


# ---------------------------------------------------------------------------
# H2.23 Tag numbers (1-1023) and TIN numbers (1-255) within the allowed range.
# ---------------------------------------------------------------------------
def check_h2_23_numbering_ranges(tags: list[Tag], tins: list[TIN], p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_23", p)
    results = []
    for t in tags:
        if t.tag_number is None:
            continue
        ok = p["tag_min"] <= t.tag_number <= p["tag_max"]
        results.append(CheckResult(
            "H2.23", f"Tag number within {p['tag_min']}-{p['tag_max']}", "PASS" if ok else "FAIL",
            f"{t.tag_ref}: tag number {t.tag_number}", subject_ref=t.tag_ref,
        ))
    for tin in tins:
        ok = p["tin_min"] <= tin.tin_no <= p["tin_max"]
        results.append(CheckResult(
            "H2.23", f"TIN number within {p['tin_min']}-{p['tin_max']}", "PASS" if ok else "FAIL",
            f"TIN {tin.tin_no}", subject_ref=str(tin.tin_no),
        ))
    return results


# ---------------------------------------------------------------------------
# H2.18 Non-KAVACH territory shown in white
# ---------------------------------------------------------------------------
def check_h2_18_non_kavach_white(tins: list[TIN], p: dict | None = None) -> list[CheckResult]:
    p = _params("h2_18", p)
    colour = p["colour"].strip().lower()
    results = []
    for tin in tins:
        if not tin.is_non_kavach_territory:
            continue
        ok = (tin.color or "").strip().lower() == colour
        results.append(CheckResult(
            "H2.18", f"Non-KAVACH territory shown {colour}", "PASS" if ok else "FAIL",
            f"TIN {tin.tin_no}: color={tin.color or 'unset'}", subject_ref=str(tin.tin_no),
        ))
    return results


# ---------------------------------------------------------------------------
# H2.21 Tag type notation must be one of the defined set
# ---------------------------------------------------------------------------
def check_h2_21_tag_notation(tags: list[Tag]) -> list[CheckResult]:
    results = []
    for t in tags:
        ok = t.tag_type in TAG_TYPES
        results.append(CheckResult(
            "H2.21", "Tag notation valid", "PASS" if ok else "FAIL",
            f"{t.tag_ref}: type '{t.tag_type}'" + ("" if ok else f" not in {TAG_TYPES}"),
            subject_ref=t.tag_ref,
        ))
    return results


# ---------------------------------------------------------------------------
# BRD FR-004: tag reference and tag number must each be unique within a station.
# Not tied to a specific Annexure-H clause number -- this is a data-integrity rule
# from the BRD (RTLDVMS v1.0), not something the RDSO text states explicitly, but
# a duplicate tag_ref or tag_number on one station's register is unambiguously a
# defect regardless of source, so it's implemented as a hard FAIL either way.
# ---------------------------------------------------------------------------
def check_brd_fr004_tag_uniqueness(tags: list[Tag]) -> list[CheckResult]:
    results = []

    by_ref: dict[str, list[Tag]] = {}
    for t in tags:
        by_ref.setdefault(t.tag_ref, []).append(t)
    for ref, group in by_ref.items():
        if len(group) > 1:
            results.append(CheckResult(
                "FR-004", "Tag reference unique within station", "FAIL",
                f"Tag ref '{ref}' used by {len(group)} tags -- must be unique",
                subject_ref=ref,
            ))

    by_number: dict[int, list[Tag]] = {}
    for t in tags:
        if t.tag_number is not None:
            by_number.setdefault(t.tag_number, []).append(t)
    for number, group in by_number.items():
        if len(group) > 1:
            refs = ", ".join(g.tag_ref for g in group)
            results.append(CheckResult(
                "FR-004", "Tag number unique within station", "FAIL",
                f"Tag number {number} used by {len(group)} tags ({refs}) -- must be unique",
                subject_ref=str(number),
            ))

    return results


# ---------------------------------------------------------------------------
# BRD FR-004: "Allocate even numbers for DN direction, odd numbers for UP direction."
#
# IMPORTANT ASSUMPTION -- please verify: Tag.direction currently holds "Reverse" /
# "Nominal" (renamed from UP/DN earlier per a separate request), not "UP"/"DN"
# literally. Evidence from the ALER drawing legend (UP/DOWN paired with
# REVERSE/NOMINAL as the same physical directions) suggests UP<->Reverse and
# DN<->Nominal, which is the mapping used below. If that mapping is wrong, this
# check will systematically flag every tag as a false FAIL -- confirm before
# relying on it, and see DIRECTION_PARITY_MAP below to correct it in one place.
# ---------------------------------------------------------------------------
DIRECTION_PARITY_MAP = {
    "Reverse": "odd",   # assumed == UP
    "Nominal": "even",  # assumed == DN
}


def check_brd_fr004_direction_parity(tags: list[Tag], p: dict | None = None) -> list[CheckResult]:
    parity_map = _params("fr004_parity", p)["parity_map"]
    results = []
    for t in tags:
        if t.tag_number is None or not t.direction:
            continue
        expected_parity = parity_map.get(t.direction)
        if expected_parity is None:
            results.append(CheckResult(
                "FR-004", "Tag number parity matches direction", "NA",
                f"{t.tag_ref}: direction '{t.direction}' not recognized for the "
                f"parity rule (expected one of {list(parity_map)})",
                subject_ref=t.tag_ref,
            ))
            continue
        actual_parity = "even" if t.tag_number % 2 == 0 else "odd"
        ok = actual_parity == expected_parity
        results.append(CheckResult(
            "FR-004", "Tag number parity matches direction", "PASS" if ok else "FAIL",
            f"{t.tag_ref}: number {t.tag_number} is {actual_parity}, direction "
            f"'{t.direction}' expects {expected_parity}",
            subject_ref=t.tag_ref,
        ))
    return results


# ---------------------------------------------------------------------------
# BRD BR-005 / Annexure-H H2.16: Border RFID tag must have an absolute location
# recorded (it marks the station boundary and is used to compute the maximum
# communication distance from the previous station's Stationary KAVACH -- see
# H2.16's full text). This checks presence/shape, not the RSSI survey criterion
# itself (BR-005's "RSSI survey criteria") -- that requires a Tower RSSI Survey
# dataset this platform doesn't currently ingest, so it stays a manual check;
# see MANUAL_CLAUSES.
# ---------------------------------------------------------------------------
def check_brd_br005_border_tag_present(tags: list[Tag]) -> list[CheckResult]:
    results = []
    border_tags = [t for t in tags if t.is_border_tag]
    for t in border_tags:
        ok = t.location_m is not None
        results.append(CheckResult(
            "BR-005", "Border tag has absolute location recorded", "PASS" if ok else "FAIL",
            f"{t.tag_ref}: location_m={t.location_m}",
            subject_ref=t.tag_ref,
        ))
    return results


# ---------------------------------------------------------------------------
# H2.28 Station centre line absolute location shown on the layout (H2.4 takes the
# Station Master's panel centre as the centre line -- that part stays manual).
# ---------------------------------------------------------------------------
def check_h2_28_centre_line(station: Station) -> list[CheckResult]:
    c = station.centre_line_m
    if c is None:
        return [CheckResult("H2.28", "Station centre line location recorded", "FAIL",
                            "Station centre line absolute location is not recorded")]
    msg = f"Centre line at {c:g} m"
    if station.tracks and not any(t.start_m <= c <= t.end_m for t in station.tracks):
        return [CheckResult("H2.28", "Station centre line location recorded", "FAIL",
                            msg + " -- outside every line recorded for this station")]
    return [CheckResult("H2.28", "Station centre line location recorded", "PASS", msg)]


# ---------------------------------------------------------------------------
# H2.16 Station border: the absolute location of the border line with each
# adjacent station must be shown. (Placement of the border tag itself and the
# H2.16.1 overlapping-signal exception stay manual.)
# ---------------------------------------------------------------------------
def check_h2_16_border_locations(station: Station) -> list[CheckResult]:
    title = "Station border location recorded"
    if not station.adjacent:
        return [CheckResult("H2.16", title, "FAIL",
                            "No adjacent stations recorded -- add each neighbouring station "
                            "with the absolute location of the border line")]
    out = []
    for a in station.adjacent:
        if a.borders:
            where = "; ".join(f"{b.line_label} {b.border_m:g} m"
                              + (f" ({b.border_tag_ref})" if b.border_tag_ref else "") for b in a.borders)
            out.append(CheckResult("H2.16", title, "PASS", f"Border with {a.name} ({a.side}): {where}",
                                   subject_ref=a.name))
            continue
        ok = a.border_m is not None
        out.append(CheckResult("H2.16", title, "PASS" if ok else "FAIL",
                               f"Border with {a.name} ({a.side}): "
                               + (f"{a.border_m:g} m" if ok else "location not recorded"),
                               subject_ref=a.name))
    return out


# ---------------------------------------------------------------------------
# BRD BR-001 / Annexure-H H2.23: tag and TIN numbers follow the approved RFID Tag /
# TIN allotment chart. A number is accepted if it is in the station's own row or in
# the row of one of its adjacent stations / block sections (a station layout also
# shows the tags of the block sections up to its borders).
# ---------------------------------------------------------------------------
def check_br001_allotment(station: Station, tags: list[Tag], tins: list[TIN]) -> list[CheckResult]:
    title = "Numbers within the allotment chart"
    a = station.allotment
    if a is None:
        return [CheckResult("BR-001", title, "WARN",
                            "No RFID Tag / TIN allotment chart loaded -- numbers are only checked "
                            "against 1-1023 / 1-255 (H2.23)")]
    if a.own is None:
        return [CheckResult("BR-001", title, "FAIL",
                            f"Station '{station.name}' (KAVACH ID {station.kavach_station_id}) is not in "
                            f"the current allotment chart {a.chart_ref}")]
    out = [CheckResult("BR-001", "Adjacent station found in the allotment chart", "WARN",
                       f"Adjacent station '{n}' is not in the allotment chart -- record its KAVACH ID "
                       f"so its numbers are recognised", subject_ref=n) for n in a.unmatched_adjacent]

    def owner(n, attr):
        if n in getattr(a.own, attr):
            return a.own.name
        for _, e in a.adjacent:
            if n in getattr(e, attr):
                return f"{e.name} (adjacent)"
        return None

    for t in tags:
        if t.tag_number is None:
            continue
        w = owner(t.tag_number, "tags")
        out.append(CheckResult("BR-001", title, "PASS" if w else "FAIL",
                               f"{t.tag_ref}: tag number {t.tag_number} "
                               + (f"allotted to {w}" if w else
                                  f"is not allotted to {a.own.name} ({a.own.tag_text}) or its adjacent sections"),
                               subject_ref=t.tag_ref))
    for n in tins:
        w = owner(n.tin_no, "tins")
        out.append(CheckResult("BR-001", title, "PASS" if w else "FAIL",
                               f"TIN {n.tin_no} " + (f"allotted to {w}" if w else
                                  f"is not allotted to {a.own.name} ({a.own.tin_text}) or its adjacent sections"),
                               subject_ref=str(n.tin_no)))
    return out


# ---------------------------------------------------------------------------
# DATA-TOPOLOGY: elements, tags and TINs placed on a line of this station and
# within its extent; points join two different lines. A data-integrity check that
# the later automated clauses (H2.8, H2.17, H2.19, H2.22) depend on.
# ---------------------------------------------------------------------------
def check_topology(station: Station, elements: list[Element], tags: list[Tag], tins: list[TIN],
                   p: dict | None = None) -> list[CheckResult]:
    from ..domain import POINTS
    tol = _params("topology", p)["tolerance_m"]
    title = "Placed on a line of the station"
    tracks = {t.id: t for t in station.tracks}
    if not tracks:
        return [CheckResult("DATA-TOPOLOGY", title, "FAIL",
                            "No lines recorded for this station -- add its lines (DN MAIN, UP MAIN, "
                            "loops, sidings) so elements, tags and TINs can be placed on them")]
    out: list[CheckResult] = []

    def on_line(ref, track_id, lo, hi, what):
        if track_id is None:
            out.append(CheckResult("DATA-TOPOLOGY", title, "FAIL", f"{what} {ref}: not placed on a line",
                                   subject_ref=ref))
            return
        tr = tracks.get(track_id)
        if tr is None:
            out.append(CheckResult("DATA-TOPOLOGY", title, "FAIL", f"{what} {ref}: line {track_id} not found",
                                   subject_ref=ref))
            return
        ok = tr.start_m - tol <= lo and hi <= tr.end_m + tol
        where = f"{lo:g} m" if lo == hi else f"{lo:g}-{hi:g} m"
        out.append(CheckResult("DATA-TOPOLOGY", title, "PASS" if ok else "FAIL",
                               f"{what} {ref} at {where} on {tr.name}"
                               + ("" if ok else f" -- outside the line ({tr.start_m:g}-{tr.end_m:g} m)"),
                               subject_ref=ref))

    for e in elements:
        on_line(e.element_ref, e.track_id, e.location_m, e.location_m, "Element")
        if e.element_type == POINTS:
            to = tracks.get(e.to_track_id) if e.to_track_id is not None else None
            ok = to is not None and e.to_track_id != e.track_id
            out.append(CheckResult("DATA-TOPOLOGY", "Points join two lines", "PASS" if ok else "FAIL",
                                   f"Points {e.element_ref}: "
                                   + (f"lead to {to.name}" if ok else "the line they lead to is not recorded"),
                                   subject_ref=e.element_ref))
    for t in tags:
        on_line(t.tag_ref, t.track_id, t.location_m, t.location_m, "Tag")
    for n in tins:
        lo, hi = min(n.start_m, n.end_m), max(n.start_m, n.end_m)
        on_line(f"TIN {n.tin_no}", n.track_id, lo, hi, "")
    return out


# ---------------------------------------------------------------------------
# Full run
# ---------------------------------------------------------------------------
# DATA-UNITS: all locations are chainage in METRES (e.g. 262910 = km 262.910), and
# every distance rule compares them directly. A station whose values look like km
# (262.910) makes every distance rule 1000x too small without any of them visibly
# failing -- so warn. It's a WARN, not a FAIL: a genuine metre chainage near km 0 can
# be small, so this is a prompt to look, not a proof.
def check_data_units(elements: list[Element], tags: list[Tag], tins: list[TIN],
                     p: dict | None = None) -> list[CheckResult]:
    threshold = _params("data_units", p)["span_threshold_m"]
    vals = ([e.location_m for e in elements] + [t.location_m for t in tags]
            + [n.start_m for n in tins] + [n.end_m for n in tins])
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return []
    span = max(vals) - min(vals)
    fractional = sum(1 for v in vals if abs(v - round(v)) > 1e-9)
    # A real station layout spans hundreds of metres or more; one that spans < 50
    # "metres" while carrying decimal parts is almost certainly entered in km.
    if span < threshold and fractional >= max(1, len(vals) // 2):
        return [CheckResult(
            "DATA-UNITS", "Chainage entered in metres", "WARN",
            f"All locations fall within {span:g} units of each other and have decimal parts "
            f"(e.g. {vals[0]:g}) -- this looks like km. Locations must be chainage in METRES "
            f"(e.g. {vals[0] * 1000:g}); distance checks are unreliable until corrected.")]
    return [CheckResult("DATA-UNITS", "Chainage entered in metres", "PASS",
                        f"Locations span {span:g} m")]


def run_all_checks(station: Station, elements: list[Element], tags: list[Tag],
                    tins: list[TIN], rules: "list | None" = None) -> VerificationReport:
    """Run the configured checklist (BRD FR-006). `rules` is a list of
    app.rules.checklist.RuleConfig, normally loaded from the database; None means the
    built-in defaults (identical to the pre-Phase-5 hard-coded behaviour). Manual
    checklist items are NOT run here -- they are confirmations by a reviewer, handled
    separately (see app/rules/checklist.py and routers/checklist.py)."""
    from .checklist import default_rules, execute_rule
    report = VerificationReport()
    for rule in (rules if rules is not None else default_rules()):
        if not rule.enabled or rule.kind == "manual":
            continue
        report.add(*execute_rule(rule, station, elements, tags, tins))
    return report


# Clauses that require visual/topological judgement on the actual drawing and are
# NOT (and cannot reliably be) automated here -- surfaced to the Checker explicitly
# rather than silently omitted.
MANUAL_CLAUSES = {
    "H2.3": "RFID layout must be prepared against the SIP with actual site-survey "
            "considerations -- requires comparing the drawing to the SIP and site survey.",
    "H2.4": "Station Master's panel centre taken as station centre line -- requires "
            "visual confirmation against the panel/drawing.",
    "H2.8": "TIN discrimination/Turnout/Inline/Signal-foot/Gate tags placed 'as per "
            "feasibility' to demarcate TIN sections -- topological judgement call.",
    "H2.10": "LC gate tag (optional) at both sides of LC gate 'as required by "
             "operating Railway' -- policy decision, not a fixed rule.",
    "H2.16": "Border RFID tag placement and the overlapping-signal exception "
             "diagram (H2.16.1) -- requires comparing adjacent stations' layouts.",
    "H2.14": "Repeated Tag ID not allowed within 25km radius -- requires "
             "cross-station data beyond a single station's register.",
    "H2.17": "Each TIN a single colour, distinguishable from neighbouring TINs -- "
             "automatable partially (flag identical colour on adjacent TIN rows) but "
             "'distinguishable' is ultimately a visual judgement.",
    "H2.19": "TIN layout must permit all Table-of-Control movements -- this is exactly "
             "what the ToC cross-validation module checks; see toc/cross_validate.py, "
             "not this rules engine.",
    "H2.20": "Exit tags provided at all places a train may leave KAVACH territory or "
             "stable long-term (e.g. sidings) -- requires knowing operational intent.",
    "H2.22": "Block Section TIN extended to BSLB (double line) / opposite Advance "
             "Starter (single line) -- topological continuity check across the network, "
             "not a single station's data.",
    "H2.24-H2.26": "Signature block, revision history, and legend presence/format -- "
                   "checked at a basic presence level in StationInfo, but format "
                   "compliance with 'User Railway practice' needs human review.",
    "BR-005 (RSSI)": "Border RFID tag's location is checked for presence (see "
                      "check_brd_br005_border_tag_present), but the BRD's full "
                      "criterion -- RSSI -70 dBm on both handing-over and "
                      "taking-over sides per a Tower RSSI Survey -- requires a "
                      "dataset this platform doesn't currently ingest.",
}

# BRD BR-008 states G-tags must be 550-850m from the LC gate. This directly
# contradicts check_h2_9_gate_tag_distance()'s >=600m-minimum-only rule, which was
# deliberately set to match the literal Annexure-H H2.9 text over an earlier
# 550-850m figure traced to a secondary source deck. The BRD re-asserting 550-850m
# might mean it's a genuine QFTL-specific policy stricter than the base standard,
# or it might mean the BRD inherited the same secondary-source figure. NOT changed
# here pending explicit confirmation -- see check_h2_9_gate_tag_distance()'s
# docstring, which still reflects the >=600m interpretation.
