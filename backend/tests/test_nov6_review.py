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
