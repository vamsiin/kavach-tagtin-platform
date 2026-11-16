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

    entry_m = entry_tag.location_m if entry_tag else None
    drawn_chain_ms: list[float] = []  # locations of tags actually found, in ToC chain order

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

        if entry_m is not None:
            actual_delta_m = abs(drawn.location_m - entry_m)
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

        drawn_chain_ms.append(drawn.location_m)

    # Order check: tags actually found should progress monotonically along the chain
    # in the same direction the chain is travelling (away from the entry tag).
    if len(drawn_chain_ms) >= 2:
        deltas = [b - a for a, b in zip(drawn_chain_ms, drawn_chain_ms[1:])]
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


# ---------------------------------------------------------------------------
# Turnout TINs from the ToC (QFTL, Nov 2026): which TINs a turnout carries depends on the routes that run over it,
# the TINs each route needs free (and free in its overlap). For every turnout with a T tag, the routes whose tag
# chain contains that T tag name the TINs required; each half of the turnout should carry one of them.
# ---------------------------------------------------------------------------
def _tin_numbers(text: str) -> set[int]:
    import re
    txt = text or ""
    found = re.findall(r"N\s*-?\s*(\d+)", txt, flags=re.I) or re.findall(r"\b(\d{1,4})\b", txt)
    return {int(x) for x in found}


def turnout_tins_from_toc(routes: list[Route], elements: list, tags: list, tins: list) -> list[dict]:
    from ..domain import POINTS

    def line_tin(track_id, m):
        nums = sorted({n.tin_no for n in tins if n.track_id == track_id
                       and min(n.start_m, n.end_m) - 1 <= m <= max(n.start_m, n.end_m) + 1})
        return nums

    out = []
    els = {e.id: e for e in elements}
    for e in elements:
        if e.element_type != POINTS or e.to_track_id is None or getattr(e, "b_end_m", None) is None:
            continue
        lo, hi = sorted((e.location_m, e.b_end_m))
        t = next((x for x in tags if x.tag_type == "T" and (els.get(x.linked_element_id) is e or
                                                           (x.linked_element_id is None and lo - 5 <= x.location_m <= hi + 5))), None)
        if t is None:
            continue                                     # no T tag: one TIN, no route dependence to check
        through = [r for r in routes if t.tag_ref in r.tag_ids_in_order]
        if not through:
            continue
        need = set()
        for r in through:
            need |= _tin_numbers(r.tins_required_free) | _tin_numbers(r.tins_required_free_overlap)
        halves = []
        for label, over, track, m in (("A", getattr(e, "tin_a_no", None), e.track_id, e.location_m),
                                      ("B", getattr(e, "tin_b_no", None), e.to_track_id, e.b_end_m)):
            nums = [over] if over is not None else line_tin(track, m)
            halves.append((label, nums))
        bad = [(lab, nums) for lab, nums in halves if nums and not (set(nums) & need)]
        routes_txt = ", ".join(sorted({r.s_no for r in through}))
        if bad:
            what = "; ".join(f"half {lab} is TIN {'/'.join(map(str, nums))}" for lab, nums in bad)
            out.append({"turnout": e.element_ref, "status": "WARN",
                        "message": f"{e.element_ref}: routes {routes_txt} over {t.tag_ref} need TIN "
                                   f"{', '.join(f'N-{n}' for n in sorted(need))} free, but {what}. Check the TIN rows, or "
                                   f"set TIN on A / B half on the points"})
        else:
            out.append({"turnout": e.element_ref, "status": "PASS",
                        "message": f"{e.element_ref}: both halves carry TINs the routes over {t.tag_ref} "
                                   f"({routes_txt}) require free"})
    return out
