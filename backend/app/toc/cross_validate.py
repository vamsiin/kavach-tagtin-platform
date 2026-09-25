"""
Cross-validates a station's drawn RFID Tag layout (app.domain.Tag records) against
the tag chains encoded in its Table of Control (ToC) export -- the platform's core
differentiator over static distance-rule checking alone (see parser.py docstring).

For each route in the ToC, this checks:
  1. Every tag in the route's expected chain actually exists in the drawn layout
     (by tag_ref) -- a tag the interlocking expects but the layout omits is a real
     defect, not a style nitpick.
  2. The drawn tag's location matches the ToC's expected cumulative distance from
     the entry signal foot tag, within a tolerance (default 1m, matching Annexure-H
     H2.7's "exact multiple of 1m" expectation for approach-tag distances).
  3. The tags appear in the same order along the route as the ToC chain -- catches
     a tag misplaced upstream/downstream of where the route logic expects it, which
     a pure distance check would miss entirely.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import Tag
from .parser import Route


@dataclass
class ChainCheckResult:
    route_s_no: str
    entry_signal: str
    exit_signal: str
    status: str  # PASS | FAIL | WARN
    message: str
    tag_ref: str | None = None


def cross_validate_route(route: Route, tags_by_ref: dict[str, Tag],
                          tolerance_m: float = 1.0) -> list[ChainCheckResult]:
    results: list[ChainCheckResult] = []

    if not route.tag_chain:
        return results  # nothing to check for this route (e.g. incomplete ToC row)

    entry_tag = tags_by_ref.get(route.entry_signal_foot_tag)
    if route.entry_signal_foot_tag and not entry_tag:
        results.append(ChainCheckResult(
            route.s_no, route.entry_signal, route.exit_signal, "FAIL",
            f"Entry Signal Foot Tag '{route.entry_signal_foot_tag}' referenced by ToC "
            f"is not present in the drawn Tag Register at all",
            tag_ref=route.entry_signal_foot_tag,
        ))
        return results  # can't meaningfully continue this route's chain check

    entry_km = entry_tag.location_km if entry_tag else None
    drawn_chain_kms: list[float] = []  # locations of tags actually found, in ToC chain order

    for entry in route.tag_chain:
        drawn = tags_by_ref.get(entry.tag_id)
        if not drawn:
            results.append(ChainCheckResult(
                route.s_no, route.entry_signal, route.exit_signal, "FAIL",
                f"Tag '{entry.tag_id}' is in the ToC chain for this route but missing "
                f"from the drawn Tag Register",
                tag_ref=entry.tag_id,
            ))
            continue

        if entry_km is not None:
            actual_delta_m = abs(drawn.location_km - entry_km) * 1000
            diff_m = abs(actual_delta_m - entry.cumulative_m)
            if diff_m <= tolerance_m:
                results.append(ChainCheckResult(
                    route.s_no, route.entry_signal, route.exit_signal, "PASS",
                    f"{entry.tag_id}: drawn at {actual_delta_m:.1f}m from entry tag "
                    f"(ToC expects {entry.cumulative_m}m)",
                    tag_ref=entry.tag_id,
                ))
            else:
                results.append(ChainCheckResult(
                    route.s_no, route.entry_signal, route.exit_signal, "FAIL",
                    f"{entry.tag_id}: drawn {actual_delta_m:.1f}m from entry tag, but "
                    f"ToC route expects {entry.cumulative_m}m (diff {diff_m:.1f}m)",
                    tag_ref=entry.tag_id,
                ))

        drawn_chain_kms.append(drawn.location_km)

    # Order check: tags actually found should progress monotonically along the chain
    # in the same direction the chain is travelling (away from the entry tag).
    if len(drawn_chain_kms) >= 2:
        deltas = [b - a for a, b in zip(drawn_chain_kms, drawn_chain_kms[1:])]
        travelling_positive = sum(deltas) >= 0
        out_of_order = any(
            (d < 0 if travelling_positive else d > 0) for d in deltas
        )
        if out_of_order:
            results.append(ChainCheckResult(
                route.s_no, route.entry_signal, route.exit_signal, "FAIL",
                "Drawn tag locations do not progress monotonically in the order the "
                "ToC chain expects -- a tag may be placed upstream/downstream of where "
                "this route's logic requires it",
            ))

    return results


def cross_validate_station(routes: list[Route], tags: list[Tag],
                            tolerance_m: float = 1.0) -> list[ChainCheckResult]:
    tags_by_ref = {t.tag_ref: t for t in tags}
    all_results: list[ChainCheckResult] = []
    for route in routes:
        all_results.extend(cross_validate_route(route, tags_by_ref, tolerance_m))
    return all_results


def summarize(results: list[ChainCheckResult]) -> dict:
    fails = [r for r in results if r.status == "FAIL"]
    return {
        "total_checks": len(results),
        "fail_count": len(fails),
        "routes_with_failures": sorted({r.route_s_no for r in fails}),
        "missing_tags": sorted({r.tag_ref for r in fails
                                 if r.tag_ref and "missing" in r.message}),
    }
