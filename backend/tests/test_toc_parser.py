import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.toc.parser import parse_toc_csv, parse_tag_chain, distance_mismatches
from app.toc.cross_validate import cross_validate_station, summarize
from app.domain import Tag

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "sample_data", "ALER_ToC.csv")


def test_parse_tag_chain_basic():
    chain = parse_tag_chain("(0#R-775#0)#(819#R-777#0)#(200#R-779#0)")
    assert [c.tag_id for c in chain] == ["R-775", "R-777", "R-779"]
    assert [c.cumulative_m for c in chain] == [0, 819, 1019]


def test_parse_tag_chain_empty():
    assert parse_tag_chain("-") == []
    assert parse_tag_chain("") == []


def test_parse_real_aler_csv():
    routes = parse_toc_csv(SAMPLE_CSV)
    assert len(routes) > 0, "should parse at least one route from the real ALER ToC file"
    route1 = next(r for r in routes if r.s_no == "1")
    assert route1.entry_signal == "S1D"
    assert route1.exit_signal == "S1 ID"
    assert route1.entry_signal_foot_tag == "R-775"
    assert route1.tag_ids_in_order == ["R-775", "R-777", "R-779"]
    assert route1.stated_distance_m == 1019
    assert route1.computed_distance_m == 1019


def test_real_aler_csv_has_no_internal_distance_mismatches():
    """The ToC file's own stated entry-exit distance should equal the sum of its
    tag-chain deltas. A mismatch would mean the export itself has a data problem --
    this file should be clean."""
    routes = parse_toc_csv(SAMPLE_CSV)
    mismatches = distance_mismatches(routes)
    assert mismatches == [], f"unexpected internal distance mismatches: {mismatches}"


def _tags_from_route_chain(route, tolerance_ok=True, corrupt_tag=None) -> list[Tag]:
    """Build a synthetic drawn Tag Register that exactly matches a route's ToC chain,
    anchored at an arbitrary base chainage -- used to prove the cross-validator both
    passes a correct layout and catches a corrupted one."""
    base_m = 262750.0  # chainage in metres (km 262.750)
    tags = []
    entry_m = base_m
    tags.append(Tag(id=0, tag_ref=route.entry_signal_foot_tag, tag_type="S", location_m=entry_m))
    for i, entry in enumerate(route.tag_chain):
        m = entry_m + entry.cumulative_m
        if corrupt_tag == entry.tag_id:
            m += 50  # shift by 50m -- should trip the tolerance check
        tags.append(Tag(id=i + 1, tag_ref=entry.tag_id, tag_type="N", location_m=m))
    return tags


def test_cross_validate_passes_for_correct_layout():
    routes = parse_toc_csv(SAMPLE_CSV)
    route1 = next(r for r in routes if r.s_no == "1")
    tags = _tags_from_route_chain(route1)
    results = cross_validate_station([route1], tags)
    assert len(results) > 0
    assert all(r.status == "PASS" for r in results), \
        f"expected all PASS, got: {[r.message for r in results if r.status != 'PASS']}"


def test_cross_validate_catches_misplaced_tag():
    routes = parse_toc_csv(SAMPLE_CSV)
    route1 = next(r for r in routes if r.s_no == "1")
    # Corrupt R-777's drawn location by 50m -- a real layout error a distance-only
    # check within the layout itself (no ToC awareness) would NOT catch, because
    # R-777 might still be a plausible distance from *some* other tag.
    tags = _tags_from_route_chain(route1, corrupt_tag="R-777")
    results = cross_validate_station([route1], tags)
    failures = [r for r in results if r.status == "FAIL"]
    assert len(failures) >= 1
    assert any("R-777" in (r.tag_ref or "") for r in failures)


def test_cross_validate_catches_missing_tag():
    routes = parse_toc_csv(SAMPLE_CSV)
    route1 = next(r for r in routes if r.s_no == "1")
    tags = _tags_from_route_chain(route1)
    tags = [t for t in tags if t.tag_ref != "R-779"]  # simulate a tag left off the drawing
    results = cross_validate_station([route1], tags)
    summary = summarize(results)
    assert "R-779" in summary["missing_tags"]


def test_cross_validate_all_real_routes_smoke():
    """Run cross-validation across every real route in the ALER file (using
    self-consistent synthetic layouts per route) to make sure the validator doesn't
    crash on any real-world chain shape in this file, including short/edge-case
    routes."""
    routes = parse_toc_csv(SAMPLE_CSV)
    for route in routes:
        if not route.tag_chain:
            continue
        tags = _tags_from_route_chain(route)
        results = cross_validate_station([route], tags)
        assert all(r.status == "PASS" for r in results), \
            f"route {route.s_no} ({route.entry_signal}->{route.exit_signal}) unexpectedly failed: " \
            f"{[r.message for r in results if r.status != 'PASS']}"
