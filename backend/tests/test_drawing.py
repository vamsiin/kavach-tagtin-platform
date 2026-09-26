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
    assert "RFID TAG / TIN LAYOUT : ALER" in joined and "NOT DRAWN TO SCALE" in joined
    assert "STATION CENTRE LINE  km 262.750" in joined
    assert "BORDER S1D km 259.740" in joined
    assert drawing_number(aler()) == "RFID_TAG_LAYOUT_ALER_2.0.3" and "RFID_TAG_LAYOUT_ALER_2.0.3" in joined
    assert any(x.startswith("R-862 / R-863") for x in t)            # co-located pair: one symbol, one label
    assert not any(x.startswith("R-863 ") for x in t)
    assert any("N-222" in x for x in t)
    assert any("not recognised" in x and "Mauve-ish" in x for x in t)
    assert any("Not placed on a line" in x and "R-999" in x for x in t)
    assert "SIP Down = Nominal, SIP Up = Reverse" in joined
    assert "<< Aler-WP-IB" in joined and "Aler-PBP-IB >>" in joined
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
