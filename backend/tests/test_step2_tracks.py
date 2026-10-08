"""
Step 2 (Annexure-H plan): track / line model, new element types (LC gates, points,
fouling marks, marker boards, axle counters, W/L boards), station centre line
(H2.28) and adjacent-station border lines (H2.16).
"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.domain import AdjacentStation, Element, Station, Tag, TIN, Track
from app.rules import checklist as ck
from app.rules.engine import (check_h2_16_border_locations, check_h2_28_centre_line,
                              check_topology, run_all_checks)

os.environ.setdefault("JWT_SECRET", "test-secret-for-step2-tests")

DN = Track(id=1, name="DN MAIN", track_type="Main", start_m=260000, end_m=265000)
LOOP = Track(id=2, name="COMMON LOOP", track_type="Loop", start_m=262300, end_m=263200)


def st(**kw):
    base = dict(id=1, name="ALER", kavach_station_id="103", sip_drawing_number="S",
                kavach_version="2", sip_version="0", guideline_version="3")
    return Station(**{**base, **kw})


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------
def test_h2_28_centre_line():
    assert check_h2_28_centre_line(st())[0].status == "FAIL"
    assert check_h2_28_centre_line(st(centre_line_m=262750))[0].status == "PASS"
    assert check_h2_28_centre_line(st(centre_line_m=262750, tracks=[DN]))[0].status == "PASS"
    off = check_h2_28_centre_line(st(centre_line_m=270000, tracks=[DN, LOOP]))[0]
    assert off.status == "FAIL" and "outside every line" in off.message


def test_h2_16_border_locations():
    r = check_h2_16_border_locations(st())
    assert [x.status for x in r] == ["FAIL"] and "No adjacent stations" in r[0].message
    adj = [AdjacentStation(id=1, name="PEMBARTI", side="Nominal", border_m=264100),
           AdjacentStation(id=2, name="BIBINAGAR", side="Reverse")]
    r = check_h2_16_border_locations(st(adjacent=adj))
    assert [(x.subject_ref, x.status) for x in r] == [("PEMBARTI", "PASS"), ("BIBINAGAR", "FAIL")]


def test_topology_no_lines_is_one_finding():
    r = check_topology(st(), [], [Tag(id=1, tag_ref="R-1", tag_type="N", location_m=1)], [])
    assert len(r) == 1 and r[0].status == "FAIL" and "No lines recorded" in r[0].message


def test_topology_placement_and_points():
    s = st(tracks=[DN, LOOP])
    els = [Element(id=1, element_ref="S1", element_type="Mainline Starter", location_m=262900, track_id=1),
           Element(id=2, element_ref="LC-38", element_type="LC Gate", location_m=258000, track_id=1),
           Element(id=3, element_ref="P-101", element_type="Points / Turnout", location_m=262310, track_id=1,
                   to_track_id=2),
           Element(id=4, element_ref="P-102", element_type="Points / Turnout", location_m=263190, track_id=1),
           Element(id=5, element_ref="FM-1", element_type="Fouling Mark", location_m=262350)]
    tags = [Tag(id=1, tag_ref="R-775", tag_type="S", location_m=262900, track_id=2),
            Tag(id=2, tag_ref="R-777", tag_type="N", location_m=262700, track_id=1)]
    tins = [TIN(tin_no=169, section_type="Station", start_m=262300, end_m=263200, track_id=2),
            TIN(tin_no=170, section_type="Block", start_m=259000, end_m=266000, track_id=1)]
    res = {(x.title, x.subject_ref): x for x in check_topology(s, els, tags, tins, {"tolerance_m": 0})}
    place = "Placed on a line of the station"
    assert res[(place, "S1")].status == "PASS"
    assert res[(place, "LC-38")].status == "FAIL" and "outside the line" in res[(place, "LC-38")].message
    assert res[(place, "FM-1")].status == "FAIL" and "not placed on a line" in res[(place, "FM-1")].message
    assert res[(place, "R-775")].status == "PASS" and res[(place, "R-777")].status == "PASS"
    assert res[(place, "TIN 169")].status == "PASS" and res[(place, "TIN 170")].status == "FAIL"
    assert res[("Points join two lines", "P-101")].status == "PASS"
    assert "lead to COMMON LOOP" in res[("Points join two lines", "P-101")].message
    assert res[("Points join two lines", "P-102")].status == "FAIL"
    # tolerance widens the line ends
    tol = {x.subject_ref: x.status for x in check_topology(s, els[1:2], [], [], {"tolerance_m": 2000})
           if x.title == place}
    assert tol["LC-38"] == "PASS"


def test_topology_is_a_warning_by_default_and_new_rules_are_fail():
    rules = {r.key: r for r in ck.default_rules()}
    assert rules["builtin.topology"].severity == "WARN"
    assert rules["builtin.h2_16"].severity == "FAIL" and rules["builtin.h2_28"].severity == "FAIL"
    rep = run_all_checks(st(), [], [], [])
    topo = [x for x in rep.results if x.clause == "DATA-TOPOLOGY"]
    assert topo and all(x.status == "WARN" for x in topo)
    assert {"H2.16", "H2.28"} <= set(rep.summary()["clauses_failing"])


# ---------------------------------------------------------------------------
# API
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
    for u, role in (("dana", "designer"), ("cara", "checker"), ("ana", "approver"), ("cora", "config_manager")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, **{u: login(u, "pass12345") for u in ("dana", "cara", "ana", "cora")}}


def _station(client, h, **extra):
    r = client.post("/stations", json={"name": "ALER", "kavach_station_id": "103",
                                       "sip_drawing_number": "IBU.1100A", "kavach_version": "2",
                                       "sip_version": "0", "guideline_version": "3", **extra},
                    headers=h["dana"])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _track(client, h, sid, name, lo, hi, ttype="Main"):
    r = client.post(f"/stations/{sid}/tracks", json={"name": name, "track_type": ttype,
                                                     "start_m": lo, "end_m": hi}, headers=h["dana"])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _verify(client, h, sid):
    return client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()


def test_tracks_crud_and_validation(client, h):
    sid = _station(client, h)
    dn = _track(client, h, sid, "DN MAIN", 260000, 265000)
    assert client.post(f"/stations/{sid}/tracks", json={"name": " dn main ", "track_type": "Main",
                       "start_m": 1, "end_m": 2}, headers=h["dana"]).status_code == 409
    assert client.post(f"/stations/{sid}/tracks", json={"name": "X", "track_type": "Spur",
                       "start_m": 1, "end_m": 2}, headers=h["dana"]).status_code == 422
    r = client.post(f"/stations/{sid}/tracks", json={"name": "X", "track_type": "Loop",
                    "start_m": 5, "end_m": 5}, headers=h["dana"])
    assert r.status_code == 422 and "endpoints are equal" in r.json()["detail"]   # REQ-TAGTIN-DIR-005
    r = client.put(f"/stations/{sid}/tracks/{dn}", json={"name": "DN MAIN", "track_type": "Main",
                   "start_m": 259000, "end_m": 265000, "is_kavach": False}, headers=h["dana"])
    assert r.status_code == 200 and r.json()["start_m"] == 259000 and r.json()["is_kavach"] is False
    lst = client.get(f"/stations/{sid}/tracks", headers=h["cara"]).json()
    assert [t["name"] for t in lst] == ["DN MAIN"]
    # checker can read but not edit
    assert client.post(f"/stations/{sid}/tracks", json={"name": "UP", "track_type": "Main",
                       "start_m": 1, "end_m": 2}, headers=h["cara"]).status_code == 403


def test_elements_on_lines_with_type_specific_fields(client, h):
    sid = _station(client, h)
    dn = _track(client, h, sid, "DN MAIN", 260000, 265000)
    loop = _track(client, h, sid, "COMMON LOOP", 262300, 263200, "Loop")
    other = _station(client, h, kavach_station_id="999")
    foreign = _track(client, h, other, "DN MAIN", 1, 2)

    lc = client.post(f"/stations/{sid}/elements", json={
        "element_ref": "LC-38", "element_type": "LC Gate", "location_m": 261500, "track_id": dn,
        "lc_class": "C", "lc_manning": "Manned interlocked"}, headers=h["dana"])
    assert lc.status_code == 200, lc.text
    assert lc.json()["lc_class"] == "C" and lc.json()["track_id"] == dn
    assert client.post(f"/stations/{sid}/elements", json={
        "element_ref": "LC-39", "element_type": "LC Gate", "location_m": 1, "lc_class": "Z"},
        headers=h["dana"]).status_code == 422
    assert client.post(f"/stations/{sid}/elements", json={
        "element_ref": "S1", "element_type": "Mainline Starter", "location_m": 1, "track_id": foreign},
        headers=h["dana"]).status_code == 422

    pts = client.post(f"/stations/{sid}/elements", json={
        "element_ref": "P-101", "element_type": "Points / Turnout", "location_m": 262310,
        "track_id": dn, "to_track_id": loop}, headers=h["dana"])
    assert pts.status_code == 200 and pts.json()["to_track_id"] == loop
    r = client.post(f"/stations/{sid}/elements", json={
        "element_ref": "P-102", "element_type": "Points / Turnout", "location_m": 262310,
        "track_id": dn, "to_track_id": dn}, headers=h["dana"])
    assert r.status_code == 422 and "different line" in r.json()["detail"]

    # LC details and the diverging line are cleared when the type no longer uses them
    r = client.put(f"/stations/{sid}/elements/{lc.json()['id']}", json={
        "element_ref": "LC-38", "element_type": "Whistle Board (W/L)", "location_m": 261500},
        headers=h["dana"])
    assert r.status_code == 200
    assert r.json()["lc_class"] is None and r.json()["lc_manning"] is None
    assert r.json()["track_id"] == dn  # not sent -> kept (older clients can't wipe it)

    # deleting a line unassigns what was on it
    assert client.delete(f"/stations/{sid}/tracks/{loop}", headers=h["dana"]).status_code == 204
    p = next(e for e in client.get(f"/stations/{sid}/elements", headers=h["dana"]).json()
             if e["element_ref"] == "P-101")
    assert p["to_track_id"] is None and p["track_id"] == dn


def test_tags_and_tins_reference_lines(client, h):
    sid = _station(client, h)
    dn = _track(client, h, sid, "DN MAIN", 260000, 265000)
    t = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-775", "tag_type": "N",
                    "location_m": 262910, "track_id": dn}, headers=h["dana"])
    assert t.status_code == 200 and t.json()["track_id"] == dn
    assert client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-777", "tag_type": "N",
                       "location_m": 1, "track_id": 9999}, headers=h["dana"]).status_code == 422
    n = client.post(f"/stations/{sid}/tins", json={"tin_no": 169, "section_type": "Station",
                    "start_m": 262000, "end_m": 263000, "track_id": dn}, headers=h["dana"])
    assert n.status_code == 200 and n.json()["track_id"] == dn
    client.delete(f"/stations/{sid}/tracks/{dn}", headers=h["dana"])
    assert client.get(f"/stations/{sid}/tags", headers=h["dana"]).json()[0]["track_id"] is None
    assert client.get(f"/stations/{sid}/tins", headers=h["dana"]).json()[0]["track_id"] is None


def test_centre_line_adjacent_stations_and_verification(client, h):
    sid = _station(client, h)
    v = _verify(client, h, sid)
    assert {"H2.16", "H2.28"} <= set(v["summary"]["clauses_failing"])
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 409

    r = client.put(f"/stations/{sid}/centre-line", json={"centre_line_m": 262750}, headers=h["dana"])
    assert r.status_code == 200 and r.json()["centre_line_m"] == 262750
    assert client.post(f"/stations/{sid}/adjacent-stations", json={"name": "PEMBARTI", "side": "Nominal",
                       "line_config": "Triple"}, headers=h["dana"]).status_code == 422
    assert client.post(f"/stations/{sid}/adjacent-stations", json={"name": " ", "side": "Nominal"},
                       headers=h["dana"]).status_code == 422
    a = client.post(f"/stations/{sid}/adjacent-stations", json={
        "name": "PEMBARTI", "side": "Nominal", "kavach_station_id": "104", "distance_m": 8830,
        "line_config": "Double"}, headers=h["dana"]).json()
    v = _verify(client, h, sid)
    assert "H2.28" not in v["summary"]["clauses_failing"] and "H2.16" in v["summary"]["clauses_failing"]
    r = client.put(f"/stations/{sid}/adjacent-stations/{a['id']}", json={
        **{k: a[k] for k in ("name", "side", "kavach_station_id", "distance_m", "line_config")},
        "border_m": 264100}, headers=h["dana"])
    assert r.status_code == 200 and r.json()["border_m"] == 264100
    v = _verify(client, h, sid)
    assert not {"H2.16", "H2.28"} & set(v["summary"]["clauses_failing"])
    assert [x["name"] for x in client.get(f"/stations/{sid}/adjacent-stations", headers=h["ana"]).json()] \
        == ["PEMBARTI"]

    # locked once the layout leaves Draft
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    assert client.put(f"/stations/{sid}/centre-line", json={"centre_line_m": 1},
                      headers=h["dana"]).status_code == 409
    assert client.delete(f"/stations/{sid}/adjacent-stations/{a['id']}",
                         headers=h["dana"]).status_code == 409
    assert client.post(f"/stations/{sid}/tracks", json={"name": "UP", "track_type": "Main",
                       "start_m": 1, "end_m": 2}, headers=h["dana"]).status_code == 409


def test_create_station_with_neighbours(client, h):
    sid = _station(client, h, centre_line_m=262750, adjacent_stations=[
        {"name": "BIBINAGAR", "side": "Reverse", "border_m": 261000},
        {"name": "PEMBARTI", "side": "Nominal", "border_m": 264100}])
    adj = client.get(f"/stations/{sid}/adjacent-stations", headers=h["dana"]).json()
    assert [a["name"] for a in adj] == ["BIBINAGAR", "PEMBARTI"]
    r = client.post("/stations", json={"name": "B", "kavach_station_id": "1",
                    "adjacent_stations": [{"name": "X", "side": "Up", "line_config": "Quad"}]},
                    headers=h["dana"])
    assert r.status_code == 422


def test_layout_report_and_baseline_diff_show_lines(client, h):
    sid = _station(client, h, centre_line_m=262750,
                   adjacent_stations=[{"name": "PEMBARTI", "side": "Nominal", "border_m": 264100,
                                       "line_config": "Double"}])
    dn = _track(client, h, sid, "DN MAIN", 260000, 265000)
    up = _track(client, h, sid, "UP MAIN", 260000, 265000)
    client.post(f"/stations/{sid}/elements", json={"element_ref": "LC-38", "element_type": "LC Gate",
                "location_m": 261500, "track_id": dn, "lc_class": "C"}, headers=h["dana"])

    from app.database import SessionLocal
    from app import models
    from app.routers.reports import build_report
    with SessionLocal() as db:
        text = build_report(db, db.get(models.StationORM, sid),
                            db.query(models.UserORM).filter_by(username="dana").first(), "layout").plain_text()
    assert "Lines and neighbouring stations" in text and "DN MAIN" in text and "PEMBARTI" in text
    assert "262750" in text and "Class C" in text

    # take it through to approval, baseline, reopen, move the LC gate to UP MAIN
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                       headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200
    assert client.post(f"/stations/{sid}/approve", json={}, headers=h["ana"]).status_code == 200
    b = client.post(f"/stations/{sid}/baselines", json={"label": "B1"}, headers=h["cora"])
    assert b.status_code == 200, b.text
    assert client.post(f"/stations/{sid}/reopen", json={"comment": "rev"}, headers=h["cora"]).status_code == 200
    el = client.get(f"/stations/{sid}/elements", headers=h["dana"]).json()[0]
    client.put(f"/stations/{sid}/elements/{el['id']}", json={
        "element_ref": "LC-38", "element_type": "LC Gate", "location_m": 261500, "track_id": up,
        "lc_class": "C"}, headers=h["dana"])
    client.put(f"/stations/{sid}/centre-line", json={"centre_line_m": 262760}, headers=h["dana"])
    diff = client.get(f"/stations/{sid}/baselines/{b.json()['id']}/diff", headers=h["dana"]).json()
    rows = {r["item"]: r for r in diff["rows"]}
    assert "track: 'DN MAIN' -> 'UP MAIN'" in rows["element LC-38"]["details"]
    assert rows["station centre line"]["change"] == "changed"
    with SessionLocal() as db:
        snap = json.loads(db.get(models.BaselineORM, b.json()["id"]).layout_snapshot)
    assert [t["name"] for t in snap["tracks"]] == ["DN MAIN", "UP MAIN"]
    assert snap["adjacent_stations"][0]["border_m"] == 264100


def test_h2_16_per_line_borders_rule():
    from app.domain import StationBorder
    adj = [AdjacentStation(id=1, name="Aler-PBP-IB", side="Higher km", borders=[
               StationBorder("DN line", 265278, "S7D"), StationBorder("UP line", 266417, "S30D")]),
           AdjacentStation(id=2, name="Aler-WP-IB", side="Lower km", borders=[
               StationBorder("DN line", 259740, "S1D"), StationBorder("UP line", 258024, "S24D")])]
    r = check_h2_16_border_locations(st(adjacent=adj))
    assert [x.status for x in r] == ["PASS", "PASS"]
    assert "DN line 265278 m (S7D); UP line 266417 m (S30D)" in r[0].message


def test_per_line_borders_api(client, h):
    """The Aler case: two neighbours, each with a different border on the DN and UP lines."""
    sid = _station(client, h, centre_line_m=262750)
    dn = _track(client, h, sid, "DN MAIN", 255000, 270000)
    r = client.post(f"/stations/{sid}/adjacent-stations", json={
        "name": "Aler-WP-IB", "side": "Lower km", "borders": [
            {"line_label": "DN line", "border_m": 259740, "border_tag_ref": "S1D", "track_id": dn},
            {"line_label": "UP line", "border_m": 258024, "border_tag_ref": "S24D"}]}, headers=h["dana"])
    assert r.status_code == 200, r.text
    wp = r.json()
    assert [(b["line_label"], b["border_m"], b["border_tag_ref"], b["track_id"]) for b in wp["borders"]] == \
        [("DN line", 259740, "S1D", dn), ("UP line", 258024, "S24D", None)]
    # one border per line; a line from another station is refused
    assert client.post(f"/stations/{sid}/adjacent-stations", json={"name": "X", "side": "Higher km", "borders": [
        {"line_label": "DN line", "border_m": 1}, {"line_label": "dn line ", "border_m": 2}]},
        headers=h["dana"]).status_code == 422
    assert client.post(f"/stations/{sid}/adjacent-stations", json={"name": "X", "side": "Higher km", "borders": [
        {"line_label": "DN line", "border_m": 1, "track_id": 9999}]}, headers=h["dana"]).status_code == 422
    client.post(f"/stations/{sid}/adjacent-stations", json={
        "name": "Aler-PBP-IB", "side": "Higher km", "borders": [
            {"line_label": "DN line", "border_m": 265278, "border_tag_ref": "S7D"},
            {"line_label": "UP line", "border_m": 266417, "border_tag_ref": "S30D"}]}, headers=h["dana"])
    v = _verify(client, h, sid)
    assert "H2.16" not in v["summary"]["clauses_failing"]
    msgs = [x["message"] for x in v["results"] if x["clause"] == "H2.16"]
    assert any("S24D" in m and "258024" in m for m in msgs)

    # PUT without `borders` keeps them; with `borders` replaces them
    base = {"name": "Aler-WP-IB", "side": "Lower km", "distance_m": 8000}
    r = client.put(f"/stations/{sid}/adjacent-stations/{wp['id']}", json=base, headers=h["dana"])
    assert len(r.json()["borders"]) == 2 and r.json()["distance_m"] == 8000
    r = client.put(f"/stations/{sid}/adjacent-stations/{wp['id']}", json={**base, "borders": [
        {"line_label": "DN line", "border_m": 259741, "border_tag_ref": "S1D"}]}, headers=h["dana"])
    assert [b["border_m"] for b in r.json()["borders"]] == [259741]

    # deleting the line keeps the border, unlinked
    client.put(f"/stations/{sid}/adjacent-stations/{wp['id']}", json={**base, "borders": [
        {"line_label": "DN line", "border_m": 259740, "border_tag_ref": "S1D", "track_id": dn}]}, headers=h["dana"])
    client.delete(f"/stations/{sid}/tracks/{dn}", headers=h["dana"])
    b = client.get(f"/stations/{sid}/adjacent-stations", headers=h["dana"]).json()[0]["borders"][0]
    assert b["track_id"] is None and b["border_m"] == 259740

    from app.database import SessionLocal
    from app import models
    from app.routers.reports import build_report
    with SessionLocal() as db:
        text = build_report(db, db.get(models.StationORM, sid),
                            db.query(models.UserORM).filter_by(username="dana").first(), "layout").plain_text()
    assert "DN line: 259740 (S1D)" in text and "UP line: 266417 (S30D)" in text
