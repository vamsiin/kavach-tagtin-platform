"""
Step 4 (Annexure-H plan): checks enabled by the line model -- H2.8, H2.17, H2.20,
H2.22, H2.26 -- the H2.7 whole-metre and H2.9 W/L-board refinements, and the
New-TAN rules (TAN-1 dead stop, TAN-2 adjacent line tag, TAN-3 after adjustment).
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain import AdjacentStation, Element, Station, Tag, TIN, Track
from app.rules import checklist as ck
from app.rules.engine import check_h2_7_approach_tag_distance, check_h2_9_gate_tag_distance, run_all_checks
from app.rules.layout_rules import (check_h2_8_tin_demarcation, check_h2_17_tin_colours,
                                    check_h2_20_exit_at_sidings, check_h2_22_block_tin_extent,
                                    check_h2_26_not_to_scale, check_tan_adjacent_line_tag,
                                    check_tan_after_adjustment, check_tan_dead_stop)

DN = Track(id=1, name="DN MAIN", track_type="Main", start_m=255000, end_m=270000)
LOOP = Track(id=2, name="COMMON LOOP", track_type="Loop", start_m=262300, end_m=263200)
SID = Track(id=3, name="SIDING 1", track_type="Siding", start_m=262400, end_m=262900)


def st(**kw):
    return Station(**{**dict(id=1, name="Aler", kavach_station_id="103", centre_line_m=262750,
                             tracks=[DN, LOOP, SID]), **kw})


def tin(no, lo, hi, track, colour="Green", section="Station", **kw):
    return TIN(tin_no=no, section_type=section, start_m=lo, end_m=hi, color=colour, track_id=track, **kw)


def tag(i, ref, ttype, loc, track=1, **kw):
    return Tag(id=i, tag_ref=ref, tag_type=ttype, location_m=loc, track_id=track, **kw)


# ---------------------------------------------------------------------------
def test_h2_17_colours_neighbours_and_points():
    pts = Element(id=9, element_ref="P-101", element_type="Points / Turnout", location_m=262310,
                  track_id=1, to_track_id=2)
    tins = [tin(169, 261000, 262300, 1, "Red"), tin(170, 262300, 263500, 1, "Red"),   # consecutive, same colour
            tin(171, 262300, 263200, 2, "Blue"),                                     # loop, via P-101
            tin(172, 263500, 264000, 1, "")]                                        # colour missing
    res = check_h2_17_tin_colours(st(), [pts], tins)
    by = {(r.title, r.subject_ref): r for r in res}
    assert by[("Neighbouring TINs in different colours", "169/170")].status == "FAIL"
    r171 = by[("Neighbouring TINs in different colours", "170/171")]      # P-101 at 262310 is inside TIN 170
    assert r171.status == "PASS" and "joined by points P-101" in r171.message
    assert ("Neighbouring TINs in different colours", "169/171") not in by
    assert by[("TIN colour recorded", "172")].status == "FAIL"
    # one TIN drawn in two colours
    two = check_h2_17_tin_colours(st(), [], [tin(180, 1, 2, 1, "Red"), tin(180, 5, 6, 2, "Pink")])
    assert any(r.title == "One colour per TIN" and r.status == "FAIL" for r in two)
    # non-KAVACH TINs are white by H2.18 and ignored here
    assert check_h2_17_tin_colours(st(), [], [tin(1, 1, 2, 1, "White", is_non_kavach_territory=True),
                                              tin(2, 2, 3, 1, "White", is_non_kavach_territory=True)]) == []
    assert any(r.status == "NA" for r in check_h2_17_tin_colours(st(tracks=[]), [], tins))


def test_h2_8_boundary_tags():
    tins = [tin(169, 261000, 262300, 1), tin(170, 262300, 263500, 1, "Red"), tin(171, 263500, 264000, 1, "Blue")]
    tags = [tag(1, "R-801", "T", 262310), tag(2, "R-803", "X", 263500)]
    res = {r.subject_ref: r for r in check_h2_8_tin_demarcation(st(), tags, tins)}
    assert res["169/170"].status == "PASS" and "R-801" in res["169/170"].message
    assert res["170/171"].status == "FAIL"             # an exit tag doesn't demarcate
    rules = {r.key: r for r in ck.default_rules()}
    assert rules["builtin.h2_8"].severity == "WARN"    # "as per feasibility"


def test_h2_20_sidings_and_non_kavach():
    pts = Element(id=1, element_ref="P-105", element_type="Points / Turnout", location_m=262400,
                  track_id=2, to_track_id=3)
    res = check_h2_20_exit_at_sidings(st(), [pts], [tag(1, "X-1", "X", 262450, track=2)])
    assert [(r.subject_ref, r.status) for r in res] == [("SIDING 1", "PASS")]
    res = check_h2_20_exit_at_sidings(st(), [pts], [tag(1, "X-1", "X", 264000, track=1)])
    assert res[0].status == "FAIL"
    nk = Track(id=4, name="GOODS LINE", track_type="Loop", start_m=1, end_m=2, is_kavach=False)
    res = check_h2_20_exit_at_sidings(st(tracks=[DN, nk]), [], [])
    assert res[0].status == "FAIL" and "no points leading to it" in res[0].message


def test_h2_22_block_tin_extent():
    adj = [AdjacentStation(id=1, name="Aler-WP-IB", side="Lower km", line_config="Double"),
           AdjacentStation(id=2, name="Aler-PBP-IB", side="Higher km", line_config="Single")]
    els = [Element(id=1, element_ref="BSLB-1", element_type="BSLB Board", location_m=261500, track_id=1),
           Element(id=2, element_ref="S6", element_type="Advanced Starter Signal", location_m=264010, track_id=1)]
    tins = [tin(221, 258000, 261510, 1, section="Block"),    # lower side, double -> BSLB at 261500
            tin(217, 264000, 266000, 1, section="Block"),    # higher side, single -> Advance Starter 264010
            tin(222, 257000, 261300, 1, section="Block")]    # lower side, 200 m short of the BSLB
    res = {r.subject_ref: r for r in check_h2_22_block_tin_extent(st(adjacent=adj), els, tins)}
    assert res["221"].status == "PASS" and "BSLB-1" in res["221"].message
    assert res["217"].status == "PASS" and "S6" in res["217"].message
    assert res["222"].status == "FAIL"
    none = check_h2_22_block_tin_extent(st(adjacent=[]), els, tins[:1])
    assert none[0].status == "NA" and "single/double" in none[0].message
    assert check_h2_22_block_tin_extent(st(), els, [tin(169, 1, 2, 1)]) == []   # station TINs not concerned


def test_h2_26_not_to_scale():
    assert check_h2_26_not_to_scale(st())[0].status == "PASS"
    assert check_h2_26_not_to_scale(st(drawn_to_scale=False))[0].status == "FAIL"
    assert check_h2_26_not_to_scale(st(drawn_to_scale=False, not_to_scale_note_present=True))[0].status == "PASS"


def test_h2_7_whole_metres():
    el = Element(id=1, element_ref="S1", element_type="Main Home without Junction Route Indicator", location_m=1000)
    tags = [Tag(id=1, tag_ref="R-1", tag_type="S", location_m=1000, linked_element_id=1),
            Tag(id=2, tag_ref="R-2", tag_type="N", location_m=799.5, linked_element_id=1)]
    res = check_h2_7_approach_tag_distance(tags, [el])
    assert any(r.status == "FAIL" and "exact multiple of 1 m" in r.message for r in res)
    tags[1].location_m = 800
    assert all(r.status == "PASS" for r in check_h2_7_approach_tag_distance(tags, [el]))
    assert all(r.status == "PASS" for r in check_h2_7_approach_tag_distance(
        [tags[0], Tag(id=2, tag_ref="R-2", tag_type="N", location_m=799.5, linked_element_id=1)], [el],
        {"min_m": 150, "max_m": 250, "starter_exception": True, "whole_metres": False}))


def test_h2_9_wl_board_alternative():
    gate = Element(id=1, element_ref="LC-38", element_type="LC Gate", location_m=261500, track_id=1)
    g = Tag(id=1, tag_ref="G-1", tag_type="G", location_m=261100, linked_element_id=1, track_id=1)   # only 400 m
    assert check_h2_9_gate_tag_distance([g], [gate])[0].status == "FAIL"
    wl_far_side = Element(id=2, element_ref="WL-1", element_type="Whistle Board (W/L)", location_m=262100, track_id=1)
    assert check_h2_9_gate_tag_distance([g], [gate, wl_far_side])[0].status == "FAIL"
    wl = Element(id=3, element_ref="WL-2", element_type="Whistle Board (W/L)", location_m=260900, track_id=1)
    r = check_h2_9_gate_tag_distance([g], [gate, wl])[0]
    assert r.status == "PASS" and "W/L board WL-2" in r.message


def test_new_tan_rules():
    pts = Element(id=1, element_ref="P-1", element_type="Points / Turnout", location_m=1000, track_id=1)
    lss = Element(id=2, element_ref="S6", element_type="Advanced Starter Signal", location_m=5000, track_id=1)
    d_ok, d_bad = tag(1, "D-1", "D", 970), tag(2, "D-2", "D", 950)
    assert [r.status for r in check_tan_dead_stop([d_ok, d_bad], [pts])] == ["PASS", "FAIL"]
    assert check_tan_dead_stop([d_ok], [])[0].status == "FAIL"
    l_ok = tag(3, "L-1", "L", 5100, linked_element_id=2)
    l_unlinked = tag(4, "L-2", "L", 5100)
    res = check_tan_adjacent_line_tag([l_ok, l_unlinked], [lss])
    assert [r.status for r in res] == ["PASS", "FAIL"] and "link it" in res[1].message
    # Aler: next two tags 75 m after the A tag (0.5 x 130 + 10 = 75)
    a = tag(5, "R-862", "A", 261144, direction="Nominal")
    n1, n2 = tag(6, "R-864", "N", 261180, direction="Nominal"), tag(7, "R-866", "N", 261219, direction="Nominal")
    r = check_tan_after_adjustment([a, n1, n2])[0]
    assert r.status == "PASS" and "within 75 m" in r.title
    assert check_tan_after_adjustment([a, n1])[0].status == "FAIL"
    assert check_tan_after_adjustment([a, n1, n2], {"max_speed_kmph": 110, "normal_tags": 2})[0].status == "FAIL"


def test_registered_and_run_by_default():
    rep = run_all_checks(st(drawn_to_scale=False), [], [], [tin(169, 261000, 262300, 1, "")])
    clauses = set(rep.summary()["clauses_checked"])
    assert {"H2.17", "H2.26"} <= clauses
    keys = {r.key for r in ck.default_rules()}
    assert {"builtin.h2_8", "builtin.h2_17", "builtin.h2_20", "builtin.h2_22", "builtin.h2_26",
            "builtin.tan_dead_stop", "builtin.tan_l_tag", "builtin.tan_after_a"} <= keys


def test_h2_22_side_by_midpoint_aler():
    """Aler: TIN 222 runs 259.740 -> 262.910, past the 262.750 centre line, but it is the
    lower-km (Wangapalli-Aler IB) block section; its station-side end is 262.910."""
    adj = [AdjacentStation(id=1, name="Aler-WP-IB", side="Lower km", line_config="Single"),
           AdjacentStation(id=2, name="Aler-PBP-IB", side="Higher km", line_config="Single")]
    els = [Element(id=1, element_ref="S6", element_type="Advanced Starter Signal", location_m=263275, track_id=1),
           Element(id=2, element_ref="S1", element_type="Advanced Starter Signal", location_m=262900, track_id=1)]
    res = {r.subject_ref: r for r in check_h2_22_block_tin_extent(
        st(adjacent=adj), els, [tin(222, 259740, 262910, 1, "Black", section="Block"),
                                tin(217, 263275, 265279, 1, "Black", section="Block")])}
    assert res["222"].status == "PASS" and "ends at 262910" in res["222"].message
    assert res["217"].status == "PASS" and "ends at 263275" in res["217"].message
