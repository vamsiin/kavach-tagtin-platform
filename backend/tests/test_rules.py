import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain import Station, Element, Tag, TIN
from app.rules.engine import (
    check_h2_5_normal_tag_spacing,
    check_h2_6_signal_foot_tags,
    check_h2_7_approach_tag_distance,
    check_h2_9_gate_tag_distance,
    check_h2_11_exit_tags,
    check_h2_12_duplicate_and_tagset_spacing,
    check_h2_13_numbering_ranges,
    check_h2_14_legend_shape,
    check_h2_18_non_kavach_white,
    check_brd_fr004_tag_uniqueness,
    check_brd_fr004_direction_parity,
    check_brd_br005_border_tag_present,
    run_all_checks,
)


def mk_element(id, element_type, location_km, ref=None):
    return Element(id=id, element_ref=ref or f"EL-{id}", element_type=element_type,
                   location_km=location_km)


def mk_tag(id, tag_type, location_km, ref=None, linked_element_id=None,
           pair_group_id=None, legend_shape=None, exit_set=None, tag_number=None,
           direction=None, is_border_tag=False):
    return Tag(id=id, tag_ref=ref or f"R-{id}", tag_type=tag_type, location_km=location_km,
               linked_element_id=linked_element_id, pair_group_id=pair_group_id,
               legend_shape=legend_shape, exit_set=exit_set, tag_number=tag_number,
               direction=direction, is_border_tag=is_border_tag)


# ---------------------------------------------------------------------------
# H2.5 -- Normal tag spacing
# ---------------------------------------------------------------------------
def test_h2_5_pass_within_1000m():
    tags = [mk_tag(1, "N", 100.000, direction="UP"), mk_tag(2, "N", 100.800, direction="UP")]
    results = check_h2_5_normal_tag_spacing(tags)
    assert len(results) == 1
    assert results[0].status == "PASS"


def test_h2_5_fail_over_1000m():
    tags = [mk_tag(1, "N", 100.000, direction="UP"), mk_tag(2, "N", 101.200, direction="UP")]
    results = check_h2_5_normal_tag_spacing(tags)
    assert results[0].status == "FAIL"
    assert "1200" in results[0].message


def test_h2_5_directions_checked_independently():
    tags = [
        mk_tag(1, "N", 100.000, direction="UP"),
        mk_tag(2, "N", 105.000, direction="UP"),  # 5km gap, UP direction -- should fail
        mk_tag(3, "N", 100.500, direction="DN"),
    ]
    results = check_h2_5_normal_tag_spacing(tags)
    # Only one comparison possible in DN (single tag -> no pairs); UP pair should fail
    up_results = [r for r in results]
    assert any(r.status == "FAIL" for r in up_results)


# ---------------------------------------------------------------------------
# H2.6 -- Signal foot tags required
# ---------------------------------------------------------------------------
def test_h2_6_fail_when_missing():
    elements = [mk_element(1, "Main Home without Junction Route Indicator", 120.000, ref="SIG-HS-01")]
    tags = []
    results = check_h2_6_signal_foot_tags(elements, tags)
    assert results[0].status == "FAIL"


def test_h2_6_pass_when_linked():
    elements = [mk_element(1, "Main Home without Junction Route Indicator", 120.000, ref="SIG-HS-01")]
    tags = [mk_tag(1, "S", 120.000, linked_element_id=1)]
    results = check_h2_6_signal_foot_tags(elements, tags)
    assert results[0].status == "PASS"


def test_h2_6_ignores_non_qualifying_element_types():
    elements = [mk_element(1, "Distant Signal", 120.000)]  # pure Distant signal -- should NOT require a Signal Foot Tag
    results = check_h2_6_signal_foot_tags(elements, [])
    assert results == []


def test_h2_6_classification_across_new_element_type_taxonomy():
    """Spot-checks requires_signal_foot_tag() against a representative sample of
    the expanded 41-entry element type list -- documents (and locks in) the
    classification decisions made when that list replaced the old fixed set, so a
    future change to the keyword heuristic that accidentally flips one of these is
    caught immediately rather than silently shipped. See domain.py's
    requires_signal_foot_tag() docstring for the full reasoning; this is not a
    substitute for a signalling domain expert reviewing that classification."""
    from app.domain import requires_signal_foot_tag

    should_require = [
        "Mainline Starter", "Loopline Starter", "Intermediate Starter",
        "Advanced Starter Signal", "IB Stop Signal", "Gate Stop Signal",
        "Calling-on Signal", "Main Home without Junction Route Indicator",
        "Main Home with Junction Route Indicator", "BSLB Board",
        "Stop Board/Buffer Stop", "Berthing Track End",
        "Auto Signal (Excludes Gate Stop Signal in Auto Territory)",
        "Semi-Automatic Signal with A-marker lit", "Various Home Signals",
        "Advanced Starter-cum-Gate Signal", "Advanced Starter-cum-Distant Signal",
    ]
    should_not_require = [
        "Distant Signal", "Inner Distant Signal", "IB Distant Signal",
        "IB Inner Distant Signal", "Gate Distant Signal", "Gate Inner Distant Signal",
        "Gate-cum-Distant Signal", "Gate Cum IB Distant Signal",
        "Gate Cum IB Inner Distant Signal", "Gate-cum-Inner Distant Signal",
        "Other Misc Signals",
    ]
    for t in should_require:
        assert requires_signal_foot_tag(t), f"expected '{t}' to require a Signal Foot Tag"
    for t in should_not_require:
        assert not requires_signal_foot_tag(t), f"expected '{t}' to NOT require a Signal Foot Tag"


# ---------------------------------------------------------------------------
# H2.7 -- Approach tag distance, with Advance Starter exception
# ---------------------------------------------------------------------------
def test_h2_7_pass_in_band():
    elements = [mk_element(1, "Mainline Starter", 120.200)]
    tags = [
        mk_tag(1, "S", 120.200, linked_element_id=1),
        mk_tag(2, "N", 120.000, linked_element_id=1),  # 200m before
    ]
    results = check_h2_7_approach_tag_distance(tags, elements)
    assert results[0].status == "PASS"


def test_h2_7_fail_too_close_for_main_signal():
    elements = [mk_element(1, "Mainline Starter", 120.200)]
    tags = [
        mk_tag(1, "S", 120.200, linked_element_id=1),
        mk_tag(2, "N", 120.100, linked_element_id=1),  # only 100m before
    ]
    results = check_h2_7_approach_tag_distance(tags, elements)
    assert results[0].status == "FAIL"


def test_h2_7_advance_starter_exception_allows_close_tag():
    elements = [mk_element(1, "Advanced Starter Signal", 120.200)]
    tags = [
        mk_tag(1, "S", 120.200, linked_element_id=1),
        mk_tag(2, "N", 120.100, linked_element_id=1),  # 100m before -- OK for Adv Starter
    ]
    results = check_h2_7_approach_tag_distance(tags, elements)
    assert results[0].status == "PASS"
    assert "exception" in results[0].message


def test_h2_7_starter_exception_also_covers_combination_signal_types():
    """The exception isn't just for the exact string 'Advanced Starter Signal' --
    it must also cover the '...-cum-Starter...' combination types introduced
    alongside the expanded element-type taxonomy, since those still have a genuine
    Starter function even when combined with a Distant/Gate/IB role. This is the
    actual behavior change from the old exact-set-membership check; a passing test
    here is what proves the broadened keyword logic works, not just that the
    renamed string still matches."""
    elements = [mk_element(1, "Advanced Starter-cum-Gate Signal", 120.200)]
    tags = [
        mk_tag(1, "S", 120.200, linked_element_id=1),
        mk_tag(2, "N", 120.100, linked_element_id=1),  # 100m before
    ]
    results = check_h2_7_approach_tag_distance(tags, elements)
    assert results[0].status == "PASS"
    assert "exception" in results[0].message


def test_h2_7_pure_distant_signal_combination_does_not_get_starter_exception():
    """Conversely: a Gate/IB Distant combination that does NOT include a Starter
    function must NOT get the exception -- proves the keyword match isn't so broad
    it accidentally exempts everything."""
    elements = [mk_element(1, "Gate Cum IB Distant Signal", 120.200)]
    tags = [
        mk_tag(1, "S", 120.200, linked_element_id=1),
        mk_tag(2, "N", 120.100, linked_element_id=1),  # 100m before -- should FAIL, no exception applies
    ]
    results = check_h2_7_approach_tag_distance(tags, elements)
    assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# H2.9 -- Gate tag >= 600m (corrected from the deck's 550-850m range)
# ---------------------------------------------------------------------------
def test_h2_9_pass_at_exactly_600m():
    elements = [mk_element(1, "LC Gate", 50.000)]
    tags = [mk_tag(1, "G", 49.400, linked_element_id=1)]  # 600m before
    results = check_h2_9_gate_tag_distance(tags, elements)
    assert results[0].status == "PASS"


def test_h2_9_fail_under_600m():
    elements = [mk_element(1, "LC Gate", 50.000)]
    tags = [mk_tag(1, "G", 49.500, linked_element_id=1)]  # 500m before
    results = check_h2_9_gate_tag_distance(tags, elements)
    assert results[0].status == "FAIL"


def test_h2_9_pass_at_850m_would_have_failed_old_excel_rule():
    """Regression guard: the OLD Excel tool (550-850m range, sourced from the deck)
    would have flagged this as a FAIL for exceeding 850m. The Annexure-H text has no
    upper bound, only a >=600m minimum -- this must PASS under the corrected rule."""
    elements = [mk_element(1, "LC Gate", 50.000)]
    tags = [mk_tag(1, "G", 49.100, linked_element_id=1)]  # 900m before
    results = check_h2_9_gate_tag_distance(tags, elements)
    assert results[0].status == "PASS"


# ---------------------------------------------------------------------------
# H2.11 -- Exit tags
# ---------------------------------------------------------------------------
def test_h2_11_pass_two_sets_10m_apart():
    tags = [
        mk_tag(1, "X", 200.000, pair_group_id="EX1", exit_set="1st"),
        mk_tag(2, "X", 200.012, pair_group_id="EX1", exit_set="2nd"),
    ]
    results = check_h2_11_exit_tags(tags)
    assert all(r.status == "PASS" for r in results)


def test_h2_11_fail_only_one_set():
    tags = [mk_tag(1, "X", 200.000, pair_group_id="EX1", exit_set="1st")]
    results = check_h2_11_exit_tags(tags)
    assert results[0].status == "FAIL"


def test_h2_11_fail_sets_too_close():
    tags = [
        mk_tag(1, "X", 200.000, pair_group_id="EX1", exit_set="1st"),
        mk_tag(2, "X", 200.005, pair_group_id="EX1", exit_set="2nd"),  # 5m, needs >=10
    ]
    results = check_h2_11_exit_tags(tags)
    assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# H2.12 -- Duplicate pair spacing + T/A co-location + tag-set to tag-set
# ---------------------------------------------------------------------------
def test_h2_12_normal_duplicate_pass_in_3_5m():
    tags = [
        mk_tag(1, "N", 100.000, pair_group_id="G1"),
        mk_tag(2, "N", 100.004, pair_group_id="G1"),  # 4m
    ]
    results = check_h2_12_duplicate_and_tagset_spacing(tags)
    assert results[0].status == "PASS"


def test_h2_12_t_tag_must_be_colocated():
    tags = [
        mk_tag(1, "T", 100.000, pair_group_id="G1"),
        mk_tag(2, "T", 100.000, pair_group_id="G1"),  # 0m -- correct
    ]
    results = check_h2_12_duplicate_and_tagset_spacing(tags)
    assert results[0].status == "PASS"


def test_h2_12_t_tag_fails_if_not_colocated():
    tags = [
        mk_tag(1, "T", 100.000, pair_group_id="G1"),
        mk_tag(2, "T", 100.004, pair_group_id="G1"),  # 4m -- wrong for T tag
    ]
    results = check_h2_12_duplicate_and_tagset_spacing(tags)
    assert results[0].status == "FAIL"


def test_h2_12_tagset_to_tagset_min_10m():
    tags = [
        mk_tag(1, "N", 100.000, pair_group_id="G1"),
        mk_tag(2, "N", 100.004, pair_group_id="G1"),
        mk_tag(3, "N", 100.006, pair_group_id="G2"),  # only 2m after G1's max -- fail
        mk_tag(4, "N", 100.010, pair_group_id="G2"),
    ]
    results = check_h2_12_duplicate_and_tagset_spacing(tags)
    tagset_results = [r for r in results if "tag-set" in r.title.lower()]
    assert tagset_results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# H2.13 -- Numbering ranges
# ---------------------------------------------------------------------------
def test_h2_13_tag_number_out_of_range():
    tags = [mk_tag(1, "N", 100.0, tag_number=1500)]
    results = check_h2_13_numbering_ranges(tags, [])
    assert results[0].status == "FAIL"


def test_h2_13_tin_out_of_range():
    tin = TIN(tin_no=300, section_type="Station", start_km=0, end_km=1)
    results = check_h2_13_numbering_ranges([], [tin])
    assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# H2.14 -- Legend shape
# ---------------------------------------------------------------------------
def test_h2_14_rectangle_for_colocated():
    tags = [
        mk_tag(1, "N", 100.000, pair_group_id="G1", legend_shape="Rectangle"),
        mk_tag(2, "N", 100.000, pair_group_id="G1", legend_shape="Rectangle"),
    ]
    results = check_h2_14_legend_shape(tags)
    assert results[0].status == "PASS"


def test_h2_14_fail_wrong_shape():
    tags = [
        mk_tag(1, "N", 100.000, pair_group_id="G1", legend_shape="Rectangle"),
        mk_tag(2, "N", 100.004, pair_group_id="G1", legend_shape="Rectangle"),  # not co-located -> should be Triangle
    ]
    results = check_h2_14_legend_shape(tags)
    assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# H2.18 -- Non-KAVACH white
# ---------------------------------------------------------------------------
def test_h2_18_pass_white():
    tin = TIN(tin_no=50, section_type="Block", start_km=0, end_km=1,
              is_non_kavach_territory=True, color="White")
    results = check_h2_18_non_kavach_white([tin])
    assert results[0].status == "PASS"


def test_h2_18_fail_non_white():
    tin = TIN(tin_no=50, section_type="Block", start_km=0, end_km=1,
              is_non_kavach_territory=True, color="Green")
    results = check_h2_18_non_kavach_white([tin])
    assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# Integration: run_all_checks against a small realistic station
# ---------------------------------------------------------------------------
def test_run_all_checks_smoke():
    station = Station(name="TEST", kavach_station_id="00999",
                       sip_drawing_number="IPU.9999", kavach_version="2", sip_version="1",
                       guideline_version="0")
    elements = [mk_element(1, "Mainline Starter", 120.200, ref="S1")]
    tags = [
        mk_tag(1, "S", 120.200, ref="R-100", linked_element_id=1),
        mk_tag(2, "N", 120.000, ref="R-098", linked_element_id=1, direction="UP"),
    ]
    tins = [TIN(tin_no=10, section_type="Station", start_km=119, end_km=121, color="Green")]
    report = run_all_checks(station, elements, tags, tins)
    assert report.summary()["total_checks"] > 0
    assert isinstance(report.fail_count, int)


# ---------------------------------------------------------------------------
# BRD FR-004 -- tag reference / tag number uniqueness
# ---------------------------------------------------------------------------
def test_fr004_unique_refs_and_numbers_pass():
    tags = [
        mk_tag(1, "N", 100.0, ref="R-1", tag_number=101),
        mk_tag(2, "N", 100.5, ref="R-2", tag_number=102),
    ]
    results = check_brd_fr004_tag_uniqueness(tags)
    assert results == []


def test_fr004_duplicate_tag_ref_fails():
    tags = [
        mk_tag(1, "N", 100.0, ref="R-1", tag_number=101),
        mk_tag(2, "N", 100.5, ref="R-1", tag_number=102),  # same ref
    ]
    results = check_brd_fr004_tag_uniqueness(tags)
    ref_failures = [r for r in results if "reference" in r.title.lower()]
    assert len(ref_failures) == 1
    assert ref_failures[0].status == "FAIL"


def test_fr004_duplicate_tag_number_fails():
    tags = [
        mk_tag(1, "N", 100.0, ref="R-1", tag_number=101),
        mk_tag(2, "N", 100.5, ref="R-2", tag_number=101),  # same number
    ]
    results = check_brd_fr004_tag_uniqueness(tags)
    num_failures = [r for r in results if "number" in r.title.lower()]
    assert len(num_failures) == 1
    assert num_failures[0].status == "FAIL"
    assert "R-1" in num_failures[0].message and "R-2" in num_failures[0].message


def test_fr004_tags_without_numbers_dont_falsely_collide():
    """Two tags with tag_number=None must not be treated as duplicates of each
    other -- 'no number assigned yet' isn't a collision."""
    tags = [
        mk_tag(1, "N", 100.0, ref="R-1", tag_number=None),
        mk_tag(2, "N", 100.5, ref="R-2", tag_number=None),
    ]
    results = check_brd_fr004_tag_uniqueness(tags)
    assert results == []


# ---------------------------------------------------------------------------
# BRD FR-004 -- odd/even tag number parity by direction
# (Reverse assumed == UP == odd, Nominal assumed == DN == even -- see
# DIRECTION_PARITY_MAP's docstring in engine.py for why this mapping was chosen
# and that it needs domain confirmation.)
# ---------------------------------------------------------------------------
def test_fr004_parity_pass_reverse_odd():
    tags = [mk_tag(1, "N", 100.0, tag_number=101, direction="Reverse")]
    results = check_brd_fr004_direction_parity(tags)
    assert results[0].status == "PASS"


def test_fr004_parity_fail_reverse_even():
    tags = [mk_tag(1, "N", 100.0, tag_number=102, direction="Reverse")]
    results = check_brd_fr004_direction_parity(tags)
    assert results[0].status == "FAIL"


def test_fr004_parity_pass_nominal_even():
    tags = [mk_tag(1, "N", 100.0, tag_number=102, direction="Nominal")]
    results = check_brd_fr004_direction_parity(tags)
    assert results[0].status == "PASS"


def test_fr004_parity_fail_nominal_odd():
    tags = [mk_tag(1, "N", 100.0, tag_number=101, direction="Nominal")]
    results = check_brd_fr004_direction_parity(tags)
    assert results[0].status == "FAIL"


def test_fr004_parity_na_for_unrecognized_direction():
    """A direction value outside the known map (e.g. Elements' 'UP'/'Down', which
    are NOT the same field as Tag.direction) must not be silently treated as a
    pass or a fail -- explicit NA so nobody mistakes an unmapped value for
    compliance."""
    tags = [mk_tag(1, "N", 100.0, tag_number=101, direction="UP")]
    results = check_brd_fr004_direction_parity(tags)
    assert results[0].status == "NA"


def test_fr004_parity_skips_tags_without_number_or_direction():
    tags = [
        mk_tag(1, "N", 100.0, tag_number=None, direction="Reverse"),
        mk_tag(2, "N", 100.0, tag_number=101, direction=None),
    ]
    results = check_brd_fr004_direction_parity(tags)
    assert results == []


# ---------------------------------------------------------------------------
# BRD BR-005 -- border tag presence
# ---------------------------------------------------------------------------
def test_br005_border_tag_with_location_passes():
    tags = [mk_tag(1, "N", 123.850, is_border_tag=True)]
    results = check_brd_br005_border_tag_present(tags)
    assert results[0].status == "PASS"


def test_br005_non_border_tags_not_checked():
    tags = [mk_tag(1, "N", 123.850, is_border_tag=False)]
    results = check_brd_br005_border_tag_present(tags)
    assert results == []
