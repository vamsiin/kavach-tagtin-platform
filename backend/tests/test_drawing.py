"""
Step 5: the RFID Tag / TIN layout sheet (H2.24-H2.29) -- scene content, the not-to-
scale chainage axis, and the SVG / PDF / DXF renderers and endpoint.
"""
import io
import os
import sys
import xml.dom.minidom
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.drawing import render
from app.drawing.layout import (X0, X1, Axis, DAllotRow, DBorder, DElement, DrawingData, DTag, DTin,
                                DTrack, build, drawing_number)
from app.drawing.scene import Text

os.environ.setdefault("JWT_SECRET", "test-secret-for-drawing-tests")


def aler(**kw):
    base = dict(
        station_name="Aler", kavach_station_id="103", sip_drawing_number="IBU.1100A", layout_version="2.0.3",
        zone="SCR - South Central Railway", centre_line_m=262750, generated_at="2026-09-25T12:00:00",
        generated_by="admin",
        tracks=[DTrack(1, "DN MAIN", 259740, 265279), DTrack(2, "UP MAIN", 258024, 266417)],
        tins=[DTin(222, 259740, 262910, 1, "Black", "Block"), DTin(171, 262910, 263152, 1, "Light Blue"),
              DTin(172, 263152, 263275, 1, "Mauve-ish")],
        tags=[DTag("R-793", "S", 262910, 1, 793, "Nominal", "Triangle"),
              DTag("R-862", "A", 261144, 1, 862, "Nominal", "Rectangle", "G1"),
              DTag("R-863", "A", 261144, 1, 863, "Nominal", "Rectangle", "G1"),
              DTag("R-774", "N", 262700, 2, 774, "Reverse"), DTag("R-999", "N", 262000, None)],
        elements=[DElement("S3", "Mainline Starter", 262910, 1), DElement("LC-38", "LC Gate", 261500, 1),
                  DElement("P-101", "Points / Turnout", 262400, 1, 2)],
        borders=[DBorder("Aler-WP-IB", "Lower km", "DN line", 259740, "S1D", 1)],
        neighbours=[("Aler-WP-IB", "Lower km"), ("Aler-PBP-IB", "Higher km")],
        revisions=[("0", "2024-09-01", "First issue")], signatures={"Prepared": ("Design Engineer", "2026-09-25")},
        allotment=[DAllotRow("Aler", "775-902", 1, 127, "169-192", 2, 22)], allotment_ref="SC chart")
    return DrawingData(**{**base, **kw})


def texts(scene):
    return [i.text for i in scene.items if isinstance(i, Text)]


def test_axis_keeps_order_and_fits():
    ax = Axis([259740, 262910, 262915, 265279])
    xs = [ax(m) for m in (259740, 262910, 262915, 265279)]
    assert xs == sorted(xs) and xs[0] == pytest.approx(X0) and xs[-1] == pytest.approx(X1)
    assert xs[2] - xs[1] > 3.5                 # a 5 m duplicate pair stays legible
    assert ax(100) == X0 and ax(10 ** 7) == X1
    assert xs[1] < ax(262912) < xs[2]          # interpolates between points


def test_sheet_content():
    t = texts(build(aler()))
    joined = "\n".join(t)
    assert "ALER" in t and "STATION ID-00103" in t and "ABSOLUTE LOCATION: 262.750" in t   # CAD-style heading
    assert "NOT DRAWN TO SCALE" in joined and "RFID TAG / TIN LAYOUT" in joined
    assert "262.750" in t                                                    # centre line ABS, in red at its top
    assert "COMM. EXIT FOR ALER-WP-IB" in t and "COMM. ENTRY FOR ALER" in t  # border note, as on the CAD sheet
    assert drawing_number(aler()) == "RFID_TAG_LAYOUT_ALER_2.0.3" and "RFID_TAG_LAYOUT_ALER_2.0.3" in joined
    assert any(x.startswith("R-862 / R-863") for x in t)            # co-located pair: one symbol, one label
    assert not any(x.startswith("R-863 ") for x in t)
    assert any("N-222" in x for x in t)
    assert any("not recognised" in x and "Mauve-ish" in x for x in t)
    assert any("Not placed on a line" in x and "R-999" in x for x in t)
    assert "SIP Down = Nominal, SIP Up = Reverse" in joined
    assert "ALER-WP-IB" in t and "ALER-PBP-IB" in t                          # named at the line ends
    assert "Design Engineer" in joined and "First issue" in joined and "775-902" in joined
    assert not any("NOT DRAWN" in x for x in texts(build(aler(drawn_to_scale=True))))
    ecr = "\n".join(texts(build(aler(dn_direction="Reverse"))))
    assert "SIP Down = Reverse, SIP Up = Nominal" in ecr


def test_no_lines_message():
    assert any("No lines recorded" in x for x in texts(build(aler(tracks=[]))))


def test_renderers():
    sc = build(aler())
    xml.dom.minidom.parseString(render.to_svg(sc))
    assert render.to_pdf(sc)[:5] == b"%PDF-"
    import ezdxf
    doc = ezdxf.read(io.StringIO(render.to_dxf(sc).decode()))
    assert not doc.audit().errors
    assert {"TAGS", "TINS", "TRACKS", "CENTRE", "BORDER"} <= {l.dxf.name for l in doc.layers}


# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def h(client):
    client.post("/auth/register", json={"username": "admin", "full_name": "Admin",
                                        "role": "admin", "password": "adminpass123"})

    def login(u, p):
        return {"Authorization": "Bearer " + client.post(
            "/auth/login", json={"username": u, "password": p}).json()["access_token"]}
    admin = login("admin", "adminpass123")
    client.post("/auth/users", json={"username": "dana", "full_name": "Dana D", "role": "designer",
                                     "password": "pass12345"}, headers=admin)
    return {"admin": admin, "dana": login("dana", "pass12345")}


def test_drawing_endpoint(client, h):
    sid = client.post("/stations", json={
        "name": "Aler", "kavach_station_id": "103", "sip_drawing_number": "IBU.1100A", "kavach_version": "2",
        "sip_version": "0", "guideline_version": "3", "centre_line_m": 262750,
        "adjacent_stations": [{"name": "Aler-WP-IB", "side": "Lower km",
                               "borders": [{"line_label": "DN line", "border_m": 259740, "border_tag_ref": "S1D"}]}]},
        headers=h["dana"]).json()["id"]
    dn = client.post(f"/stations/{sid}/tracks", json={"name": "DN MAIN", "track_type": "Main", "start_m": 259740,
                     "end_m": 265279}, headers=h["dana"]).json()["id"]
    client.post(f"/stations/{sid}/tins", json={"tin_no": 171, "section_type": "Station", "start_m": 262910,
                "end_m": 263152, "color": "Light Blue", "track_id": dn}, headers=h["dana"])
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-793", "tag_type": "S", "location_m": 262910,
                "tag_number": 793, "direction": "Nominal", "track_id": dn}, headers=h["dana"])
    client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])

    r = client.get(f"/stations/{sid}/drawing", headers=h["dana"])
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    svg = r.text
    assert "R-793" in svg and "N-171" in svg and "Dana D" in svg        # self-check -> "Prepared"
    assert "content-disposition" not in r.headers                         # preview, not a download
    r = client.get(f"/stations/{sid}/drawing", params={"format": "pdf"}, headers=h["dana"])
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert 'RFID_TAG_LAYOUT_ALER_2.0.3.pdf' in r.headers["content-disposition"]
    r = client.get(f"/stations/{sid}/drawing", params={"format": "dxf"}, headers=h["dana"])
    assert r.status_code == 200 and b"SECTION" in r.content[:200]
    assert client.get(f"/stations/{sid}/drawing", params={"format": "png"}, headers=h["dana"]).status_code == 422
    log = client.get(f"/stations/{sid}/report-log", headers=h["dana"]).json()
    assert sorted(x["fmt"] for x in log if x["report_type"] == "drawing") == ["dxf", "pdf"]


def test_line_order_follows_line_type():
    """QFTL review (Oct 2026): COMMON LOOP above DN MAIN, then UP MAIN, then UP LOOP,
    whatever order the lines were entered in."""
    from app.drawing.layout import DTrack, ordered_tracks
    tr = [DTrack(1, "UP LOOP", 0, 1, line_type="UP LOOP"), DTrack(2, "DN MAIN", 0, 1, line_type="DN MAIN"),
          DTrack(3, "SIDING", 0, 1, line_type="OTHER"), DTrack(4, "UP MAIN", 0, 1, line_type="UP MAIN"),
          DTrack(5, "COMMON LOOP", 0, 1, line_type="COMMON LOOP")]
    assert [t.name for t in ordered_tracks(tr)] == ["COMMON LOOP", "DN MAIN", "UP MAIN", "UP LOOP", "SIDING"]


def test_adjustment_tag_shows_abs1_and_abs2():
    from app.drawing.layout import DTag, _tag
    from app.drawing.scene import Scene, Text
    s = Scene(420, 297)
    _tag(s, DTag("R-862", "A", 261083, 1, 862, "Reverse", abs2_m=261144), 100, 100, [], "R-862")
    t = [x.text for x in s.items if isinstance(x, Text)]
    assert "ABS-1 261.083" in t and "ABS-2 261.144" in t


# ---------------------------------------------------------------------------
# QFTL observations (Oct 2026), checked against the approved Aler V2.0.3 layout
# ---------------------------------------------------------------------------
def _rects(scene, layer):
    return [i for i in scene.items if type(i).__name__ == "Rect" and i.layer == layer]


def _overlap(a, b, pad=0.0):
    return a.x < b.x + b.w + pad and b.x < a.x + a.w + pad and a.y < b.y + b.h + pad and b.y < a.y + a.h + pad


def test_labels_never_overlap_each_other_or_a_line():
    tags = [DTag(f"R-{900 + i}", "N", 262000 + i * 3, 1 + i % 2, 900 + i, "Nominal" if i % 3 else "Reverse")
            for i in range(30)]
    sc = build(aler(tags=tags))
    boxes = [r for r in _rects(sc, "LABELS") if r.stroke is not None]      # tag no. / TIN boxes
    blocks = [r for r in _rects(sc, "LABELS") if r.stroke is None]         # each label's whole block
    assert len(boxes) > 30 and len(blocks) > 30
    for group in (boxes, blocks):
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                assert not _overlap(a, b), (a, b)
    bands = [r for r in _rects(sc, "TRACKS") if r.fill is None]
    for a in boxes:                               # obs. 6/7: nothing written on a line
        for b in bands:
            assert not _overlap(a, b)
    from app.drawing.layout import spread
    assert spread([10, 10, 10, 50], 3, 0, 100) == [7, 10, 13, 50]


def test_tags_sit_on_their_line_and_tins_have_just_a_number():
    sc = build(aler())
    t = texts(sc)
    assert "N-222" in t and "N-171" in t
    assert not any("Black" in x or "Block" in x or "Light Blue" in x for x in t)    # obs. 1
    band_y = {round(i.y + i.h / 2, 2) for i in _rects(sc, "TRACKS")}
    tag_y = {round(min(p[1] for p in i.points) + 1.7, 2) for i in sc.items
             if type(i).__name__ == "Poly" and i.layer == "TAGS"} | \
        {round(i.y + i.h / 2, 2) for i in _rects(sc, "TAGS") if i.stroke != (210, 0, 0)}   # not a "no T tag" flag
    assert tag_y and tag_y <= band_y                                                # obs. 5


def test_sheet_grows_instead_of_squeezing():
    small = build(aler())
    assert small.width >= 420
    tags = [DTag(f"R-{i}", "N", 250000 + i * 150, 1 + i % 2, i, "Nominal" if i % 2 else "Reverse")
            for i in range(160)]
    big = build(aler(tags=tags, tracks=[DTrack(1, "DN MAIN", 249000, 276000), DTrack(2, "UP MAIN", 249000, 276000)]))
    assert big.width > small.width


def test_turnouts_coloured_by_tin_at_each_end_with_a_and_b_ends():
    d = aler(tracks=[DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"),
                     DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN"),
                     DTrack(3, "UP LOOP", 262200, 263000, line_type="UP LOOP")],
             tins=[DTin(169, 261978, 262221, 1, "Yellow"), DTin(179, 261824, 262265, 2, "Sky Blue")],
             tags=[DTag("R-838", "T", 262023, 2, 838, "Reverse", linked_ref="P11")],
             elements=[DElement("P11", "Points / Turnout", 262067, 1, 2, b_end_m=261978),
                       DElement("P13", "Points / Turnout", 262150, 2, 3, b_end_m=262254)])
    sc = build(d)
    toes = [i for i in sc.items if type(i).__name__ == "Poly" and i.layer == "POINTS" and i.fill == (0, 0, 0)]
    assert len(toes) == 2                                                      # one turnout each
    fills = {i.fill for i in sc.items if type(i).__name__ == "Poly" and i.layer == "POINTS"}
    assert (240, 200, 0) in fills and (110, 190, 245) in fills                     # yellow A-end, sky blue B-end
    t = texts(sc)
    assert "A 262.067" in t and "B 261.978" in t and "A 262.150" in t and "B 262.254" in t      # obs. 11
    assert "R-838  262.023" in t                                                   # T tag on the turnout


def test_only_reference_distances():
    d = aler(tags=[DTag("R-791", "N", 262710, 1, 791, "Nominal"), DTag("R-793", "S", 262910, 1, 793, "Nominal"),
                   DTag("R-797", "N", 263100, 1, 797, "Nominal"), DTag("R-883", "G", 263574, 1, 883, "Nominal")],
             elements=[DElement("S3", "Mainline Starter", 262910, 1, direction="Down"),
                       DElement("LC-38", "LC Gate", 264174, 1, lc_class="Special")])
    dims = [x.text for x in build(d).items if type(x).__name__ == "Text" and x.layer == "DIMENSIONS"]
    assert sorted(dims) == ["200m", "600m"]                                        # S to rear tag; G to gate
    t = texts(build(d))
    assert "'SPL' CLASS LC GATE NO. 38" in t and "264.174" in t                 # obs. 3


def test_signal_aspects_drawn_in_colour():
    from app.domain import default_aspects, normalise_aspects
    assert default_aspects("Distant Signal") == "G/YY/Y"
    assert default_aspects("Main Home with Junction Route Indicator") == "R/Y/YY/G+RI"
    assert default_aspects("Gate-cum-Inner Distant Signal").startswith("R/")
    assert default_aspects("BSLB Board") is None and default_aspects("LC Gate") is None
    assert normalise_aspects(" r y g ") == "R/Y/G" and normalise_aspects("R-Y-YY-G + JRI") == "R/Y/YY/G+RI"
    with pytest.raises(ValueError):
        normalise_aspects("R/X")
    d = aler(elements=[DElement("S1D", "Distant Signal", 259740, 1, direction="Down", aspects="G/YY/Y"),
                       DElement("S1", "Main Home with Junction Route Indicator", 261789, 1, direction="Down",
                                aspects="R/Y/YY/G+RI"),
                       DElement("S1A", "Calling-on Signal", 261789, 1, direction="Down", aspects="C"),
                       DElement("S3", "Mainline Starter", 262910, 1, direction="Down", aspects="R/Y/G",
                                aspects_default=True)])
    sc = build(d)
    fills = [i.fill for i in sc.items if type(i).__name__ == "Poly" and i.layer == "SIGNALS"]
    assert (220, 30, 30) in fills and (0, 150, 60) in fills
    t = texts(sc)
    assert "S1D" in t and "S3*" in t and "S1" in t and "S1A" in t                    # calling-on named, one post
    sig = [i for i in sc.items if type(i).__name__ == "Text" and i.layer == "SIGNALS" and i.text in ("S1", "S1A")]
    assert abs(sig[0].x - sig[1].x) > 1.5                                           # names don't overlap


def test_allotment_shows_allotted_and_spare():
    row = DAllotRow("Aler", "775-825", 2, 49, "169-192", 3, 21, station_id="00103",
                    tags_allotted="775-798, 800, 802", tags_spare="799, 801, 803-825",
                    tins_allotted="169-172", tins_spare="173-192", border_tags="775")
    t = texts(build(aler(allotment=[row])))
    assert "00103" in t and "ALLOTTED" in t and "SPARE" in t and any("803-825" in x for x in t)


def test_element_aspects_api(client, h):
    sid = client.post("/stations", json={"name": "X", "kavach_station_id": "9", "kavach_version": "1",
                                         "sip_version": "0", "guideline_version": "0"}, headers=h["dana"]).json()["id"]
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "S1", "element_type": "Distant Signal",
                    "location_m": 1000, "aspects": "g yy y"}, headers=h["dana"])
    assert r.status_code in (200, 201) and r.json()["aspects"] == "G/YY/Y"
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "S2", "element_type": "Distant Signal",
                    "location_m": 1100, "aspects": "R/Q"}, headers=h["dana"])
    assert r.status_code == 422
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "LC1", "element_type": "LC Gate",
                    "location_m": 1200, "aspects": "R/Y/G"}, headers=h["dana"])
    assert r.json()["aspects"] is None                 # not a signal: cleared
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "P1", "element_type": "Points / Turnout",
                    "location_m": 1300, "b_end_m": 1390}, headers=h["dana"])
    assert r.json()["b_end_m"] == 1390
    r = client.post(f"/stations/{sid}/elements", json={"element_ref": "S9", "element_type": "Distant Signal",
                    "location_m": 1400, "b_end_m": 1500}, headers=h["dana"])
    assert r.json()["b_end_m"] is None                 # B-end only for points


def test_line_names_on_their_line_and_running_directions():
    """Approved-layout style: each line's name is written beside its band (not in a
    margin column), with the running-direction legend at the top."""
    sc = build(aler())
    t = texts(sc)
    assert "DN MAIN" in t and "UP MAIN" in t
    assert "UP / DOWN" in t and "REVERSE / NOMINAL" in t
    names = [i for i in sc.items if type(i).__name__ == "Text" and i.text in ("DN MAIN", "UP MAIN")]
    assert all(i.layer == "LABELS" for i in names)


def test_t_tag_found_on_its_turnout_from_any_line_and_flagged_when_missing():
    """QFTL (Oct 2026): R-840 missing from P20. A T tag is matched to the turnout whose
    ends it lies between even when it is entered against another line; a turnout with
    no T tag is marked on the drawing, and the data check says which tag is wrong."""
    from app.domain import Element, Tag
    from app.rules.layout_rules import check_turnout_t_tags
    base = dict(tracks=[DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"),
                        DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN"),
                        DTrack(3, "COMMON LOOP", 262175, 263146, line_type="COMMON LOOP")],
                elements=[DElement("P19", "Points / Turnout", 263009, 1, 3, b_end_m=262922),
                          DElement("P20", "Points / Turnout", 263044, 1, 2, b_end_m=263140)])
    good = build(aler(**base, tags=[DTag("R-836", "T", 262966, 3, 836), DTag("R-840", "T", 263092, 3, 840)]))
    t = texts(good)
    assert "R-836  262.966" in t and "R-840  263.092" in t and not any("no T tag" in x for x in t)
    bad = build(aler(**base, tags=[DTag("R-836", "T", 262966, 3, 836), DTag("R-840", "T", 262966, 3, 840)]))
    assert "no T tag on P20" in texts(bad)

    els = [Element(1, "P19", "Points / Turnout", 263009, track_id=1, to_track_id=3, b_end_m=262922),
           Element(2, "P20", "Points / Turnout", 263044, track_id=1, to_track_id=2, b_end_m=263140)]
    res = check_turnout_t_tags([Tag(1, "R-836", "T", 262966, track_id=3), Tag(2, "R-840", "T", 262966, track_id=3)],
                               els)
    msgs = " | ".join(r.message for r in res)
    assert "R-836 and R-840 are at the same chainage on P19" in msgs and "No T tag between the ends of P20" in msgs
    res = check_turnout_t_tags([Tag(1, "R-836", "T", 262966, track_id=3),
                                Tag(2, "R-840", "T", 263092, track_id=3, linked_element_id=2)], els)
    assert all(r.status == "PASS" for r in res)
    res = check_turnout_t_tags([Tag(3, "R-899", "T", 250000, track_id=1)], els)
    assert any("not on any turnout" in r.message and "nearest is P19" in r.message for r in res)


def test_line_keeps_its_own_tin_where_turnout_pieces_overlap():
    """QFTL (Oct 2026): N-186 to be corrected. TIN rows that are really turnout pieces
    (ending at a T tag, TIN of another line) entered on COMMON LOOP must not repaint
    the loop's own TIN; the data check names each stray row."""
    from app.domain import Station, TIN as DomTIN, Tag as DomTag, Track as DomTrack
    from app.rules.layout_rules import check_tin_overlaps
    tins = [DTin(186, 262907, 263116, 3, "Yellow"), DTin(171, 262910, 263092, 3, "Sky Blue"),
            DTin(171, 262910, 263152, 1, "Sky Blue"), DTin(177, 263092, 263145, 3, "Magenta"),
            DTin(177, 263145, 262977, 2, "Magenta")]
    d = aler(tracks=[DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"),
                     DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN"),
                     DTrack(3, "COMMON LOOP", 262175, 263146, line_type="COMMON LOOP")],
             tins=tins, tags=[DTag("R-840", "T", 263092, 3, 840)], elements=[])
    sc = build(d)
    cl_y = max(i.y for i in sc.items if type(i).__name__ == "Rect" and i.layer == "TINS")   # top line = COMMON LOOP
    cl = [i for i in sc.items if type(i).__name__ == "Rect" and i.layer == "TINS" and abs(i.y - cl_y) < 0.01]
    assert {r.fill for r in cl} == {(240, 200, 0)}                         # yellow N-186 only
    boxes = [x.text for x in sc.items if type(x).__name__ == "Text" and x.layer == "LABELS" and x.text.startswith("N-")]
    assert boxes.count("N-186") == 1 and boxes.count("N-171") == 1 and boxes.count("N-177") == 1   # 171/177 on DN/UP only

    st = Station(name="Aler", tracks=[DomTrack(id=i, name=n, track_type="Main", start_m=0, end_m=1)
                                      for i, n in ((1, "DN MAIN"), (2, "UP MAIN"), (3, "COMMON LOOP"))])
    dt = [DomTIN(tin_no=n.tin_no, section_type="Station", start_m=n.start_m, end_m=n.end_m, track_id=n.track_id)
          for n in tins]
    msgs = [r.message for r in check_tin_overlaps(st, dt, [DomTag(1, "R-840", "T", 263092, track_id=3)])]
    assert any(m.startswith("TIN 171 (262.910-263.092) overlaps TIN 186 on COMMON LOOP") and
               "The drawing shows TIN 186" in m for m in msgs)
    assert any(m.startswith("TIN 177 (263.092-263.145)") and "turnout tag R-840" in m for m in msgs)
    assert not any(m.startswith("TIN 186") for m in msgs)


def test_signal_entered_on_two_lines_is_drawn_once():
    """QFTL (Oct 2026): repeated signals at the ends of N-170 / N-171 / N-172 / N-178 --
    loop signals also entered on the main lines. One copy is drawn (the one on a line
    that fits its type, at its signal-foot tag); names only on the other copy carry
    over (S5/SH8 -> 'S5 / SH8'); the data check names the extra rows."""
    from app.domain import Element, Station, Tag as DomTag, Track as DomTrack
    from app.rules.layout_rules import check_duplicate_elements
    tracks = [DTrack(1, "DN MAIN", 259740, 265279, line_type="DN MAIN"),
              DTrack(2, "UP MAIN", 258024, 266417, line_type="UP MAIN"),
              DTrack(3, "COMMON LOOP", 262175, 263146, line_type="COMMON LOOP")]
    tags = [DTag("R-833", "S", 262907, 3, 833, "Nominal"), DTag("R-793", "S", 262910, 1, 793, "Nominal"),
            DTag("R-798", "S", 262265, 2, 798, "Reverse"), DTag("R-827", "S", 262213, 3, 827, "Reverse"),
            DTag("R-792", "S", 262977, 2, 792, "Nominal")]
    els = [DElement("S5", "Loopline Starter", 262907, 3), DElement("S5/SH8", "Loopline Starter", 262907, 1, direction="Down"),
           DElement("S3", "Mainline Starter", 262910, 1, direction="Down"),
           DElement("S26", "Loopline Starter", 262213, 3), DElement("S26", "Loopline Starter", 262268, 2, direction="Up"),
           DElement("S28", "Mainline Starter", 262265, 2, direction="Up"),
           DElement("SB", "Stop Board/Buffer Stop", 262977, 2, direction="Up")]
    t = [x.text for x in build(aler(tracks=tracks, tags=tags, elements=els)).items
         if type(x).__name__ == "Text" and x.layer == "SIGNALS"]
    assert t.count("S26*") + t.count("S26") == 1 and any(x.startswith("S5 / SH8") for x in t)
    assert not any(x.startswith("S5/SH8") for x in t)

    st = Station(name="Aler", tracks=[DomTrack(id=i.id, name=i.name, track_type="Main", start_m=0, end_m=1,
                                               line_type=i.line_type) for i in tracks])
    dom_els = [Element(i, e.ref, e.element_type, e.location_m, track_id=e.track_id) for i, e in enumerate(els)]
    dom_tags = [DomTag(i, g.ref, g.tag_type, g.location_m, track_id=g.track_id) for i, g in enumerate(tags)]
    msgs = [r.message for r in check_duplicate_elements(st, dom_els, dom_tags)]
    assert len(msgs) == 2
    assert any(m.startswith("S5/SH8 is entered on DN MAIN") and "shows the COMMON LOOP one" in m for m in msgs)
    assert any(m.startswith("S26 is entered on UP MAIN") and "R-827" in m for m in msgs)
