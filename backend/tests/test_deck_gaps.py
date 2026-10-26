"""Scope-deck gaps closed: H2.14 repeat limits, exit tag programming (H2.11), merged /
approach tags (H2.7), shunt-signal N tags (TAN-4), virtual BSLB (H2.6), border Normal
tag where no signal is available (BR-005), TIN bifurcation (common loop reception)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain import AdjacentStation, Element, NearbyStation, Station, Tag, TIN, Track
from app.rules.checklist import default_rules
from app.rules.deck_rules import (check_h2_14_repeat_limits, check_merged_approach, check_shunt_foot_as_normal,
                                  check_tin_bifurcation, check_virtual_bslb)
from app.rules.engine import (check_br005_rssi_coverage, check_h2_6_signal_foot_tags,
                              check_h2_11_exit_programming)

DN = Track(id=1, name="DN MAIN", track_type="Main", start_m=255000, end_m=270000, direction="Nominal",
           line_type="DN MAIN")


def st(**kw):
    return Station(**{**dict(id=1, name="Aler", kavach_station_id="103", centre_line_m=262750, tracks=[DN]), **kw})


def tag(i, ref, ttype, loc, **kw):
    return Tag(id=i, tag_ref=ref, tag_type=ttype, location_m=loc, track_id=1, direction="Nominal", **kw)


def el(i, ref, etype, loc, **kw):
    return Element(id=i, element_ref=ref, element_type=etype, location_m=loc, track_id=1, **kw)


def statuses(res):
    return [r.status for r in res]


# --- H2.14 ----------------------------------------------------------------
def test_h2_14_tag_number_repeat_within_25km_fails():
    near = NearbyStation("Wangapalli", 250000, tags=[("R-775", 775, 250100)], tins=[])
    mine = [tag(1, "R-775", "N", 262000, tag_number=775)]
    r = check_h2_14_repeat_limits(st(nearby=[near]), mine, [])
    assert statuses(r) == ["FAIL"] and "11.9 km" in r[0].message


def test_h2_14_beyond_25km_and_same_physical_tag_pass():
    far = NearbyStation("Far", 200000, tags=[("R-775", 775, 230000)])
    same = NearbyStation("Next", 270000, tags=[("R-775", 775, 262000.5)])    # one tag drawn on two layouts
    r = check_h2_14_repeat_limits(st(nearby=[far, same]), [tag(1, "R-775", "N", 262000, tag_number=775)], [])
    assert statuses(r) == ["PASS"]


def test_h2_14_tin_limits_station_10km_block_50km_and_shared_section():
    mine = [TIN(tin_no=5, section_type="Station", start_m=262000, end_m=263000, track_id=1),
            TIN(tin_no=6, section_type="Block", start_m=255000, end_m=261000, track_id=1),
            TIN(tin_no=7, section_type="Block", start_m=261000, end_m=262000, track_id=1)]
    o = NearbyStation("Other", 275000, tins=[(5, "Station", 270000, 271000),      # 7 km  -> FAIL (<10)
                                              (6, "Block", 290000, 291000),       # 29 km -> FAIL (<50)
                                              (7, "Block", 261500, 262500)])      # overlaps: the same section
    r = check_h2_14_repeat_limits(st(nearby=[o]), [], mine)
    assert sorted(x.subject_ref for x in r if x.status == "FAIL") == ["5", "6"]


def test_h2_14_not_checked_without_neighbours():
    assert statuses(check_h2_14_repeat_limits(st(), [], [])) == ["NA"]
    assert "centre line" in check_h2_14_repeat_limits(st(centre_line_m=None), [], [])[0].message


# --- H2.11 exit programming -----------------------------------------------
def test_exit_programming():
    tags = [tag(1, "X1", "X", 100, exit_set="1st", exit_comm="ENTRY"),
            tag(2, "X2", "X", 120, exit_set="2nd", exit_comm="ENTRY"),    # 2nd must be NONE
            tag(3, "X3", "X", 140, exit_set="2nd"),                       # not recorded
            tag(4, "X4", "X", 160)]                                       # no set
    assert statuses(check_h2_11_exit_programming(tags)) == ["PASS", "FAIL", "WARN", "WARN"]
    assert statuses(check_h2_11_exit_programming([tag(1, "X1", "X", 1, exit_set="2nd", exit_comm="NONE")])) == ["PASS"]


# --- H2.7 merged / approach tags ------------------------------------------
def test_merged_gate_tag_serves_as_approach_tag():
    home = el(1, "S1", "Main Home without Junction Route Indicator", 262000)
    tags = [tag(1, "R-1", "S", 262000, linked_element_id=1), tag(2, "R-2", "G", 261800)]   # 200 m before
    r = check_merged_approach(st(), tags, [home])
    assert statuses(r) == ["PASS"] and "merged" in r[0].message
    r = check_merged_approach(st(), [tags[0], tag(2, "R-2", "G", 261500)], [home])          # 500 m: too far
    assert statuses(r) == ["FAIL"]


def test_merged_check_leaves_linked_n_tags_to_h2_7_and_applies_starter_exception():
    home = el(1, "S1", "Main Home without Junction Route Indicator", 262000)
    adv = el(2, "S9", "Advanced Starter Signal", 264000)
    tags = [tag(1, "R-1", "S", 262000, linked_element_id=1), tag(2, "R-2", "N", 261800, linked_element_id=1),
            tag(3, "R-3", "S", 264000, linked_element_id=2), tag(4, "R-4", "N", 263900)]
    r = check_merged_approach(st(), tags, [home, adv])
    assert [(x.subject_ref, x.status) for x in r] == [("S9", "PASS")]      # 100 m is allowed for a starter


# --- TAN-4 shunt signal foot tag as N ---------------------------------------
def test_shunt_foot_tag_that_is_an_approach_tag_must_be_n():
    home = el(1, "S1", "Main Home without Junction Route Indicator", 262000)
    sh = el(2, "SH2", "Shunt Signal", 261800)
    base = [tag(1, "R-1", "S", 262000, linked_element_id=1)]
    r = check_shunt_foot_as_normal(st(), base + [tag(2, "R-2", "S", 261800, linked_element_id=2)], [home, sh])
    assert statuses(r) == ["FAIL"] and "designate it N" in r[0].message
    n_tags = base + [tag(2, "R-2", "N", 261800, linked_element_id=2)]
    assert statuses(check_shunt_foot_as_normal(st(), n_tags, [home, sh])) == ["PASS"]
    # and H2.6 accepts the N tag in place of an S tag
    h26 = check_h2_6_signal_foot_tags([home, sh], n_tags)
    assert statuses(h26) == ["PASS", "PASS"] and "in place of the S tag" in h26[1].message
    # a shunt signal far from any main signal keeps its S tag; an N there is questioned
    far = el(3, "SH3", "Shunt Signal", 258000)
    assert statuses(check_shunt_foot_as_normal(st(), [tag(5, "R-5", "S", 258000, linked_element_id=3)], [far, home])) == ["PASS"]
    assert statuses(check_shunt_foot_as_normal(st(), [tag(5, "R-5", "N", 258000, linked_element_id=3)], [far, home])) == ["WARN"]


# --- virtual BSLB -----------------------------------------------------------
def _bslb_station():
    return st(adjacent=[AdjacentStation(id=1, name="Wangapalli", side="Lower", line_config="Double")])


def test_virtual_bslb_s_tag_required_when_no_board():
    block = TIN(tin_no=222, section_type="Block", start_m=255000, end_m=261978, track_id=1)
    r = check_virtual_bslb(_bslb_station(), [], [], [block])
    assert statuses(r) == ["FAIL"]
    r = check_virtual_bslb(_bslb_station(), [], [tag(1, "R-9", "S", 261978)], [block])
    assert statuses(r) == ["PASS"] and "virtual BSLB" in r[0].message
    board = el(1, "BSLB", "BSLB Board", 261978)
    assert check_virtual_bslb(_bslb_station(), [board], [], [block]) == []     # a real board: not this check's job


# --- border tag as a Normal tag where there is no signal -------------------------
def test_border_normal_tag_where_no_signal():
    from app.domain import RssiReading, Tower
    base = dict(towers=[Tower(id=1, tower_ref="T1", location_m=250000)],
                rssi=[RssiReading(id=1, tower_ref="T1", location_m=250000, rssi_dbm=-60)])
    far_tag = lambda tt: tag(1, "R-B", tt, 259000, is_border_tag=True)
    assert statuses(check_br005_rssi_coverage(st(**base), [far_tag("N")])) == ["PASS"]
    r = check_br005_rssi_coverage(st(**base), [far_tag("S")])
    assert statuses(r) == ["WARN"] and "Normal (N) tag" in r[0].message


# --- TIN bifurcation ---------------------------------------------------------
def test_tin_bifurcated_between_shunt_signal_and_advance_starter():
    sh = el(1, "SH8", "Shunt Signal", 263000)
    adv = el(2, "S6", "Advanced Starter Signal", 263300)
    one = [TIN(tin_no=10, section_type="Station", start_m=262000, end_m=264000, track_id=1)]
    assert statuses(check_tin_bifurcation(st(), [sh, adv], one)) == ["FAIL"]
    split = [TIN(tin_no=10, section_type="Station", start_m=262000, end_m=263150, track_id=1),
             TIN(tin_no=11, section_type="Station", start_m=263150, end_m=264000, track_id=1)]
    assert statuses(check_tin_bifurcation(st(), [sh, adv], split)) == ["PASS"]


# --- wiring -------------------------------------------------------------------------
def test_new_rules_are_in_the_default_checklist():
    keys = {r.key for r in default_rules()}
    assert {"builtin.h2_14_repeat", "builtin.h2_11_prog", "builtin.h2_7_merged", "builtin.tan_shunt_n",
            "builtin.virtual_bslb", "builtin.tin_bifurcation"} <= keys


def test_nearby_stations_only_linked_and_in_range():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import models
    from app.allotment.service import nearby_stations
    from app.database import Base
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    ws = models.WorkspaceORM(code="SCR", name="SCR")
    db.add(ws)
    db.flush()

    def mk(name, kid, centre):
        s = models.StationORM(name=name, kavach_station_id=kid, centre_line_m=centre, workspace_id=ws.id)
        db.add(s)
        db.flush()
        return s
    a, b, c, far, other = mk("A", "1", 100000), mk("B", "2", 110000), mk("C", "3", 120000), mk("Far", "4", 500000), mk("Other", "5", 105000)
    db.add(models.AdjacentStationORM(station_id=a.id, name="B", kavach_station_id="2", side="Higher"))
    db.add(models.AdjacentStationORM(station_id=b.id, name="C", kavach_station_id="3", side="Higher"))
    db.add(models.AdjacentStationORM(station_id=far.id, name="C", kavach_station_id="3", side="Lower"))
    db.add(models.TagORM(station_id=c.id, tag_ref="R-1", tag_number=1, tag_type="N", location_m=120100))
    db.commit()
    got = {n.name for n in nearby_stations(db, a)}
    assert got == {"B", "C"}              # linked through B; Other is unlinked; Far is linked but 400 km off
    assert nearby_stations(db, a)[1].tags == [("R-1", 1, 120100)] or nearby_stations(db, a)[0].tags
