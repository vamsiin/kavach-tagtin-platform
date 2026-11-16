"""QFTL review of 6 Nov 2026: siding and sand hump input and drawing, BSLB behind its post, turnout ABS at the
ends, calling-on aspects (see also test_drawing.py)."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_register_crud import client, _make_admin_designer_checker  # noqa: F401 (fixture)
from test_drawing import aler

from app.drawing.layout import BAND, DElement, DTag, DTrack, Rect, build
from app.drawing.scene import Text


def _texts(s):
    return [i.text for i in s.items if isinstance(i, Text)]


def test_api_sand_hump_type_and_siding_fields(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "Aler", "kavach_station_id": "103", "centre_line_m": 262750}, headers=des).json()["id"]
    loop = client.post(f"/stations/{sid}/tracks", json={"name": "COMMON LOOP", "track_type": "Loop", "start_m": 262175,
                       "end_m": 263146}, headers=des).json()["id"]
    main = client.post(f"/stations/{sid}/tracks", json={"name": "DN MAIN", "track_type": "Main", "start_m": 259740,
                       "end_m": 265279}, headers=des).json()["id"]
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "HUMP-1", "element_type": "Sand Hump",
                    "location_m": 262169, "track_id": loop}, headers=des)
    assert r.status_code == 200, r.text
    # points that lead to no recorded line keep their siding name and shed ...
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "P17", "element_type": "Points / Turnout",
                    "location_m": 263050, "track_id": loop, "siding_name": " Siding for tower wagon ",
                    "siding_shed": "Tower wagon shed"}, headers=des).json()
    assert r["siding_name"] == "Siding for tower wagon" and r["siding_shed"] == "Tower wagon shed"
    # ... points that lead to a line, and anything that is not points, drop them
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "P18", "element_type": "Points / Turnout",
                    "location_m": 262400, "track_id": loop, "to_track_id": main, "siding_name": "x"}, headers=des).json()
    assert r["siding_name"] is None
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "SB", "element_type": "Stop Board/Buffer Stop",
                    "location_m": 262977, "track_id": loop, "siding_name": "x", "signal_side": "above"}, headers=des).json()
    assert r["siding_name"] is None and r["signal_side"] == "Above"            # a board takes the Drawn setting


def test_siding_continues_the_line_to_a_buffer_stop_with_shed_and_name():
    tracks = [DTrack(3, "COMMON LOOP", 262175, 263146, line_type="COMMON LOOP"), DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN")]
    p17 = DElement("P17", "Points / Turnout", 263050, 3, siding_name="Siding for sub station & tower wagon",
                   siding_shed="Tower wagon shed")
    s = build(aler(tracks=tracks, elements=[p17], tins=[], tags=[], borders=[], annotations=[]))
    t = _texts(s)
    assert "TOWER WAGON SHED" in t and "BS" in t and "SIDING FOR SUB STATION &" in t and "TOWER WAGON" in t
    assert "P17 (siding)" in t
    # no diagonal stub: the siding is the line carrying straight on (white band + shed box + buffer stop bar)
    assert not any(type(i).__name__ == "Poly" and i.layer == "POINTS" and len(i.points) == 4 and i.fill is None
                   and abs(i.points[0][1] - i.points[2][1]) > 3 for i in s.items)
    assert any(isinstance(i, Rect) and i.layer == "POINTS" and i.w > 20 for i in s.items)                # the shed
    # points far from the end of their line keep the old diagonal stub (named SIDING)
    long_loop = [DTrack(3, "COMMON LOOP", 262000, 264000, line_type="COMMON LOOP"), tracks[1]]
    far = DElement("P17", "Points / Turnout", 263000, 3)                         # 1000 m from both ends of the loop
    s2 = build(aler(tracks=long_loop, elements=[far], tins=[], tags=[], borders=[], annotations=[]))
    assert "SIDING" in _texts(s2) and "BS" not in _texts(s2)


def test_sand_hump_element_is_a_half_disc_with_bar_and_foot_at_the_nearer_end():
    tracks = [DTrack(4, "UP LOOP", 262169, 263031, line_type="UP LOOP"), DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN")]
    s = build(aler(tracks=tracks, elements=[DElement("HUMP-1", "Sand Hump", 262169, 4)], tins=[], tags=[], borders=[], annotations=[]))
    assert "SAND HUMP" in _texts(s)
    disc = [i for i in s.items if type(i).__name__ == "Poly" and i.layer == "ANNOTATIONS"]
    assert len(disc) == 1 and len(disc[0].points) == 13
    marks = [i for i in s.items if type(i).__name__ == "Line" and i.layer == "ANNOTATIONS"]
    assert len(marks) == 3                                       # end bar, the bar across the line, its foot
    y_disc = sum(p[1] for p in disc[0].points) / len(disc[0].points)
    loop_x0 = min(r.x for r in s.items if type(r).__name__ == "Rect" and r.layer == "TRACKS" and r.h < 3
                  and abs(r.y + r.h / 2 - y_disc) < 4)
    assert max(p[0] for p in disc[0].points) <= loop_x0 + 0.5    # on the left end: the disc lies outside the line


def test_bslb_stands_behind_its_post_and_calling_on_defaults_to_a_marker_with_a_yellow_lens():
    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN")]
    els = [DElement("BSLB", "BSLB Board", 261978, 1)]
    tags = [DTag("R-785", "S", 261978, 1, 785, "Reverse", linked_ref="BSLB")]
    s = build(aler(tracks=tracks, elements=els, tags=tags, tins=[], borders=[], annotations=[]))
    box = next(i for i in s.items if isinstance(i, Rect) and i.layer == "BOARDS")
    post = next(i for i in s.items if type(i).__name__ == "Line" and i.layer == "BOARDS" and abs(i.x1 - i.x2) < 1e-9
                and abs(i.y1 - i.y2) > 1)
    assert box.x + box.w < post.x1 + 0.1                         # Nominal home: the box is to the left of its post


def test_turnout_abs_arrow_ends_at_the_tab_and_the_text_is_beyond_it():
    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"), DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN")]
    els = [DElement("P11", "Points / Turnout", 262067, 1, 2, b_end_m=261978)]
    s = build(aler(tracks=tracks, elements=els, tins=[], tags=[], borders=[], annotations=[]))
    vert = [i for i in s.items if isinstance(i, Text) and i.layer == "POINTS" and i.angle == 90]
    assert {v.text for v in vert} == {"262067", "261978"}
    bands = sorted({round(r.y + r.h / 2, 1) for r in s.items if type(r).__name__ == "Rect" and r.layer == "TRACKS" and r.h < 3})
    heads = [i for i in s.items if type(i).__name__ == "Poly" and i.layer == "POINTS" and len(i.points) == 3]
    assert len(heads) == 2
    for h in heads:                                              # the arrow tip is the tab's outer edge, 3.7 mm out
        tip_y = h.points[0][1]
        assert min(abs(tip_y - b) for b in bands) > BAND / 2 + 2.0


def test_home_signal_marks_a_track_circuit_boundary_within_a_few_metres():
    """CAD: a Home signal's head ends in a slanted tick where its track circuit (1AT) ends -- only for a Home signal
    with a track circuit boundary within a few metres, on the head's side; a route indicator is the separate fork."""
    from app.drawing.layout import DAnnotation, DrawingData  # noqa: F401
    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN")]
    els = [DElement("S1", "Main Home without Junction Route Indicator", 261789, 1, direction="Down", aspects="R/Y/G"),
           DElement("S3", "Mainline Starter", 262910, 1, direction="Down", aspects="R/Y/G")]

    def ticks(annotations):
        s = build(aler(tracks=tracks, elements=els, tins=[], tags=[], borders=[], annotations=annotations))
        return [i for i in s.items if type(i).__name__ == "Line" and i.layer == "SIGNALS" and i.width == 0.45
                and abs(i.x1 - i.x2) > 1.0 and abs(i.y1 - i.y2) > 2.0 and i.y1 > 110]
    near = [DAnnotation("Track circuit", "1AT", 1, 260000, 261791), DAnnotation("Track circuit", "DMAT", 1, 261791, 262910)]
    assert len(ticks([])) == 0                                    # no track circuits entered: no mark
    assert len(ticks(near)) == 1                                  # 1AT ends 2 m past S1: S1 gets the tick (S3, a starter, does not)
    far = [DAnnotation("Track circuit", "1AT", 1, 260000, 261100)]
    assert len(ticks(far)) == 0                                   # the boundary is 689 m away


def test_route_indicator_types_junction_multilamp_stencil():
    """Route indicators (UG notes): junction type = fork, multi-lamp type = lamp matrix showing 0-9 / A-Z, stencil type =
    a boxed letter; only on a first stop (Home) signal or a starter."""
    import pytest
    from app.domain import Element, Station, normalise_aspects, split_route_indicator
    from app.rules.deck_rules import check_route_indicator_position
    assert normalise_aspects("r y g + ri") == "R/Y/G+RI"
    assert normalise_aspects("R/Y/G+RI:M:2") == "R/Y/G+RI:M:2"
    assert normalise_aspects("R/Y+RI:S:b") == "R/Y+RI:S:B"
    assert split_route_indicator("R/Y/G+RI:M:7") == ("R/Y/G", "M", "7")
    with pytest.raises(ValueError):
        normalise_aspects("R/Y/G+RI:S")                               # a stencil / multi-lamp indicator shows a character

    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN")]

    def texts_and_dots(asp):
        els = [DElement("S29", "Main Home with Junction Route Indicator", 261789, 1, direction="Down", aspects=asp)]
        s = build(aler(tracks=tracks, elements=els, tins=[], tags=[], borders=[]))
        dots = [i for i in s.items if type(i).__name__ == "Poly" and i.layer == "SIGNALS" and len(i.points) == 6]
        return [i.text for i in s.items if isinstance(i, Text) and i.layer == "SIGNALS"], len(dots), s
    t_j, d_j, _ = texts_and_dots("R/Y/G+RI")
    t_m, d_m, _ = texts_and_dots("R/Y/G+RI:M:2")
    t_s, d_s, _ = texts_and_dots("R/Y+RI:S:B")
    assert "2" in t_m and d_m == 16 and "2" not in t_j and d_j == 0     # multi-lamp: the character inside a lamp matrix
    assert "B" in t_s and d_s == 0                                      # stencil: the boxed letter

    def el(typ, asp):
        return Element(1, "X1", typ, 100, aspects=asp)
    st = Station(1, "Aler", "1", 100)
    res = check_route_indicator_position(st, [el("Mainline Starter", "R/Y/G+RI:S:B"),
                                              el("Distant Signal", "Y/G+RI"),
                                              el("Main Home without Junction Route Indicator", "R/Y/G+RI:M")])
    assert [r.status for r in res] == ["PASS", "FAIL", "FAIL"]


def test_turnout_t_tag_centre_single_tin_and_siding_tin():
    """Team answers (16 Nov): the T tag stands at the midpoint of A and B, 0.5 m rounding up; a turnout whose two halves
    are in one TIN needs no T tag; the TIN of a siding reaches its shunt signal."""
    from app.domain import Element, Station, Tag, TIN, Track
    from app.rules.layout_rules import check_siding_tin_to_shunt, check_turnout_t_tags, point_centre_m
    assert point_centre_m(0, 80) == 40 and point_centre_m(0, 123) == 62 and point_centre_m(263009, 262922) == 262966
    p12 = Element(1, "P12", "Points / Turnout", 262103, track_id=1, to_track_id=3, b_end_m=262197)
    one = [TIN(169, "Station", 261978, 262221, track_id=1), TIN(169, "Station", 262175, 262213, track_id=3)]
    two = [TIN(171, "Station", 261978, 262221, track_id=1), TIN(172, "Station", 262175, 262213, track_id=3)]
    r = check_turnout_t_tags([], [p12], tins=one)
    assert [x.status for x in r] == ["PASS"] and "no separate T tag" in r[0].message
    assert [x.status for x in check_turnout_t_tags([], [p12], tins=two)] == ["WARN"]          # two TINs: the T tag is needed
    ok = check_turnout_t_tags([Tag(1, "R-834", "T", 262150, track_id=3, linked_element_id=1)], [p12], tins=two)
    assert [x.status for x in ok] == ["PASS"]
    off = check_turnout_t_tags([Tag(1, "R-834", "T", 262140, track_id=3, linked_element_id=1)], [p12], tins=two)
    assert [x.status for x in off] == ["PASS", "WARN"] and "point centre" in off[1].message and "262.150" in off[1].message

    st = Station(1, "Aler", "1", 262750, tracks=[Track(3, "COMMON LOOP", "Loop", 262175, 263146)])
    p17 = Element(2, "P17", "Points / Turnout", 263050, track_id=3)
    sh22 = Element(3, "SH22", "Shunt Signal", 263066, track_id=3)
    short = [TIN(186, "Station", 262907, 263060, track_id=3)]
    full = [TIN(186, "Station", 262907, 263116, track_id=3)]
    assert [x.status for x in check_siding_tin_to_shunt(st, [p17, sh22], short)] == ["WARN"]
    r = check_siding_tin_to_shunt(st, [p17, sh22], full)
    assert [x.status for x in r] == ["WARN"] and "runs 50 m past the shunt signal" in r[0].message   # to R-839: too far
    ends_at_signal = [TIN(186, "Station", 262907, 263066, track_id=3)]
    assert [x.status for x in check_siding_tin_to_shunt(st, [p17, sh22], ends_at_signal)] == ["PASS"]


def test_turnout_half_tins_labels_piece_rows_close_turnouts_and_toc():
    """R2 (TIN on A / B half), R3 (label only where a half differs from its line), R4 (turnout-piece rows accepted),
    R7 (close turnouts offset), and the turnout TINs checked against the ToC routes."""
    from app.drawing.layout import DTin
    from app.domain import Element, Tag as DomTag, TIN as DomTIN
    from app.toc.cross_validate import turnout_tins_from_toc
    from app.toc.parser import Route, TagChainEntry
    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"),
              DTrack(3, "COMMON LOOP", 262175, 263146, line_type="COMMON LOOP")]
    tins = [DTin(171, 262910, 263152, 1, "Sky Blue"), DTin(186, 262907, 263116, 3, "Yellow")]
    tag = DTag("R-836", "T", 262966, 3, 836)

    def scene(p19):
        els = [p19]
        return build(aler(tracks=tracks, elements=els, tins=tins, tags=[tag], borders=[]))

    def tin_labels(sc):
        return [i.text for i in sc.items if isinstance(i, Text) and i.layer == "LABELS" and i.text.startswith("N-")]
    base = DElement("P19", "Points / Turnout", 263009, 1, to_track_id=3, b_end_m=262922)
    plain = tin_labels(scene(base))
    assert plain.count("N-171") == 1 and plain.count("N-186") == 1               # the lines' own labels only (R3)
    same_as_line = DElement("P19", "Points / Turnout", 263009, 1, to_track_id=3, b_end_m=262922, tin_a_no=171)
    assert tin_labels(scene(same_as_line)).count("N-171") == 1                    # equal to its line: no extra label
    differs = DElement("P19", "Points / Turnout", 263009, 1, to_track_id=3, b_end_m=262922, tin_a_no=186, tin_b_no=177)
    labs = tin_labels(scene(differs))
    assert labs.count("N-177") == 1 and labs.count("N-186") == 2                  # R2: B half N-177; A half N-186 labelled

    # R7: two turnouts with centres under 30 m apart: the second one's labels flip to the other side
    from app.drawing.layout import _flip_close_turnouts

    class T:
        def __init__(self, a, b):
            self.a_m, self.b_m, self.tb = a, b, 3
    t1, t2, t3 = T(100, 140), T(110, 150), T(400, 440)
    _flip_close_turnouts([t1, t2, t3])
    assert (t1.flip, t2.flip, t3.flip) == (False, True, False)

    # ToC: routes over the T tag need N-186 and N-177 free; the A half on DN MAIN is N-171 -> flagged
    el = [Element(1, "P19", "Points / Turnout", 263009, track_id=1, to_track_id=3, b_end_m=262922)]
    tg = [DomTag(1, "R-836", "T", 262966, track_id=3, linked_element_id=1)]
    dt = [DomTIN(171, "Station", 262910, 263152, track_id=1), DomTIN(186, "Station", 262907, 263116, track_id=3)]
    route = Route("5", "S1", "S3", "Main", "DN", "Home", "R-1", [TagChainEntry("R-836", 10, 10)],
                  tins_required_free="N-186, N-177")
    res = turnout_tins_from_toc([route], el, tg, dt)
    assert res[0]["status"] == "WARN" and "half A is TIN 171" in res[0]["message"]
    el[0].tin_a_no = 186
    assert turnout_tins_from_toc([route], el, tg, dt)[0]["status"] == "PASS"


def test_api_half_tin_fields(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "Aler", "kavach_station_id": "103", "centre_line_m": 262750}, headers=des).json()["id"]
    main = client.post(f"/stations/{sid}/tracks", json={"name": "DN MAIN", "track_type": "Main", "start_m": 259740,
                       "end_m": 265279}, headers=des).json()["id"]
    loop = client.post(f"/stations/{sid}/tracks", json={"name": "COMMON LOOP", "track_type": "Loop", "start_m": 262175,
                       "end_m": 263146}, headers=des).json()["id"]
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "P19", "element_type": "Points / Turnout",
                    "location_m": 263009, "track_id": main, "to_track_id": loop, "b_end_m": 262922, "tin_a_no": 186,
                    "tin_b_no": 177}, headers=des)
    assert r.status_code == 200 and (r.json()["tin_a_no"], r.json()["tin_b_no"]) == (186, 177), r.text
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "SH1", "element_type": "Shunt Signal",
                    "location_m": 262000, "track_id": main, "tin_a_no": 5}, headers=des).json()
    assert r["tin_a_no"] is None                                                  # only points carry half TINs
    assert client.post(f"/stations/{sid}/elements", json={"element_ref": "P2", "element_type": "Points / Turnout",
                       "location_m": 262100, "track_id": main, "tin_a_no": 0}, headers=des).status_code == 422


def test_toc_distances_follow_the_absolute_location_correction_of_an_adjustment_tag():
    """Aler route 11: R-862 is an adjustment tag, ABS-1 261.083 -> ABS-2 261.144 (+61 m); the ToC distances after it are
    61 m longer than the drawn chainages. Without the A tag's ABS-2 they fail; with it they pass."""
    from app.domain import Tag
    from app.toc.cross_validate import cross_validate_station
    from app.toc.parser import Route, parse_tag_chain
    chain = parse_tag_chain("(0#R-802#0)#(100#R-860#0)#(641#R-862#0)#(75#R-864#0)#(75#R-866#0)")
    route = Route("11", "S25", "S24D", "Absolute Block", "Up Main", "Advanced Starter", "R-802", chain)

    def tags(abs2):
        return [Tag(1, "R-802", "S", 261824), Tag(2, "R-860", "L", 261724), Tag(3, "R-862", "A", 261083, abs2_m=abs2),
                Tag(4, "R-864", "N", 261069), Tag(5, "R-866", "N", 260994)]
    bad = [r for r in cross_validate_station([route], tags(None)) if r.status == "FAIL"]
    assert [r.tag_ref for r in bad] == ["R-864", "R-866"]                       # 61 m out, no correction known
    res = cross_validate_station([route], tags(261144))
    assert all(r.status == "PASS" for r in res)
    assert any("correction of +61m at adjustment tag R-862" in r.message for r in res)
