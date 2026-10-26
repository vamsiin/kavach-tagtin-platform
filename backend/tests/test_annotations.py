"""Drawing annotations: track circuit names, section notes and site features -- the register
(API) and how they appear on the generated layout sheet."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_register_crud import client, _make_admin_designer_checker  # noqa: F401 (fixture)
from test_drawing import aler, texts

from app.drawing import render
from app.drawing.layout import DAnnotation, Line, build
from app.drawing.scene import Text


def _station(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "Aler", "kavach_station_id": "103", "centre_line_m": 262750},
                      headers=des).json()["id"]
    dn = client.post(f"/stations/{sid}/tracks", json={"name": "DN MAIN", "track_type": "Main", "start_m": 259740,
                     "end_m": 265279}, headers=des).json()["id"]
    return sid, des, dn


def test_annotation_register_crud_and_validation(client):
    sid, des, dn = _station(client)
    r = client.post(f"/stations/{sid}/annotations", json={"kind": "Track circuit", "label": " DMAT ", "track_id": dn,
                    "start_m": 262000, "end_m": 262500}, headers=des)
    assert r.status_code == 201 and r.json()["label"] == "DMAT"
    aid = r.json()["id"]
    bad = [{"kind": "Wall", "label": "x", "track_id": dn, "start_m": 1},                      # unknown kind
           {"kind": "Feature", "label": " ", "track_id": dn, "start_m": 1},                  # blank label
           {"kind": "Track circuit", "label": "X", "track_id": dn, "start_m": 1},              # a stretch needs an end
           {"kind": "Feature", "label": "X", "start_m": 1},                                   # no line
           {"kind": "Feature", "label": "X", "track_id": 9999, "start_m": 1}]                 # not this station's line
    for b in bad:
        assert client.post(f"/stations/{sid}/annotations", json=b, headers=des).status_code == 422, b
    assert client.post(f"/stations/{sid}/annotations", json={"kind": "Feature", "label": "Sand hump",
                       "track_id": dn, "start_m": 262100}, headers=des).status_code == 201
    r = client.put(f"/stations/{sid}/annotations/{aid}", json={"kind": "Track circuit", "label": "UMAT",
                   "track_id": dn, "start_m": 262000, "end_m": 262600}, headers=des)
    assert r.json()["label"] == "UMAT" and r.json()["end_m"] == 262600
    assert len(client.get(f"/stations/{sid}/annotations", headers=des).json()) == 2
    assert client.delete(f"/stations/{sid}/annotations/{aid}", headers=des).status_code == 204
    assert len(client.get(f"/stations/{sid}/annotations", headers=des).json()) == 1


def test_annotations_appear_on_the_layout():
    d = aler(annotations=[DAnnotation("Track circuit", "DMAT", 1, 260000, 261000),
                          DAnnotation("Section note", "Axle Counter Section", 1, 261100, 262000),
                          DAnnotation("Feature", "Sand hump", 2, 262500),
                          DAnnotation("Feature", "Lost", 99, 262500)])       # a line that is not drawn: skipped
    s = build(d)
    t = texts(s)
    assert "DMAT" in t and "(Axle Counter Section)" in t and "SAND HUMP" in t and "LOST" not in t
    assert any(i.layer == "ANNOTATIONS" for i in s.items)
    assert sum(isinstance(i, Line) and i.layer == "ANNOTATIONS" for i in s.items) >= 7   # ticks, bracket, hatch


def test_annotations_survive_the_renderers():
    d = aler(annotations=[DAnnotation("Track circuit", "DMAT", 1, 260000, 261000)])
    s = build(d)
    assert b"DMAT" in render.to_svg(s) and render.to_pdf(s)[:4] == b"%PDF" and render.to_dxf(s)
