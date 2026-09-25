"""
Workspaces (railway zones): membership-based visibility, workspace for new data, the
SIP Up/Down <-> Nominal/Reverse convention per zone (ECR: SIP Up = Nominal), zone
overrides of checklist rules, allotment charts per zone, and the upgrade that puts
existing data into 'SCR'.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.domain import Element, Station, Tag
from app.rules.layout_rules import check_direction_convention, sip_to_kavach

os.environ.setdefault("JWT_SECRET", "test-secret-for-workspace-tests")


def test_sip_to_kavach_convention():
    assert sip_to_kavach("Down", "Nominal") == "Nominal" and sip_to_kavach("UP", "Nominal") == "Reverse"
    assert sip_to_kavach("Down", "Reverse") == "Reverse" and sip_to_kavach("Up", "Reverse") == "Nominal"  # ECR
    assert sip_to_kavach("Nominal", "Nominal") is None and sip_to_kavach(None, "Nominal") is None


def test_direction_convention_rule():
    s3 = Element(id=1, element_ref="S3", element_type="Mainline Starter", location_m=1, direction="Down")
    tags = [Tag(id=1, tag_ref="R-793", tag_type="S", location_m=1, linked_element_id=1, direction="Nominal"),
            Tag(id=2, tag_ref="R-795", tag_type="S", location_m=2, linked_element_id=1, direction="Reverse")]
    scr = {r.subject_ref: r for r in check_direction_convention(
        Station(id=1, name="Aler", kavach_station_id="103", workspace_code="SCR"), [s3], tags)}
    assert scr["R-793"].status == "PASS"
    assert scr["R-795"].status == "FAIL" and "expected Nominal (SCR: SIP Down = Nominal)" in scr["R-795"].message
    ecr = {r.subject_ref: r.status for r in check_direction_convention(
        Station(id=1, name="X", kavach_station_id="9", dn_direction="Reverse", workspace_code="ECR"), [s3], tags)}
    assert ecr == {"R-793": "FAIL", "R-795": "PASS"}


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
    for u, role in (("dana", "designer"), ("eddie", "designer"), ("cara", "checker"), ("cora", "config_manager")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, **{u: login(u, "pass12345") for u in ("dana", "eddie", "cara", "cora")}}


def _zones(client, h):
    scr = client.post("/workspaces", json={"code": "scr", "name": "South Central Railway"}, headers=h["cora"]).json()
    ecr = client.post("/workspaces", json={"code": "ECR", "name": "East Central Railway", "dn_direction": "Reverse",
                                           "remarks": "SIP Down = Reverse, SIP Up = Nominal"}, headers=h["cora"]).json()
    client.put(f"/workspaces/{scr['id']}/members", json={"usernames": ["dana", "cara"]}, headers=h["cora"])
    client.put(f"/workspaces/{ecr['id']}/members", json={"usernames": ["eddie"]}, headers=h["cora"])
    return scr, ecr


def _station(client, headers, sid, ws=None, name="S"):
    body = {"name": name, "kavach_station_id": sid, "sip_drawing_number": "X", "kavach_version": "2",
            "sip_version": "0", "guideline_version": "3", "centre_line_m": 1,
            "adjacent_stations": [{"name": "A", "side": "Lower km", "border_m": 0}]}
    if ws is not None:
        body["workspace_id"] = ws
    return client.post("/stations", json=body, headers=headers)


def test_first_station_gets_open_default_workspace(client, h):
    r = _station(client, h["dana"], "1")
    assert r.status_code == 200 and r.json()["workspace_code"] == "DEFAULT"
    ws = client.get("/workspaces", headers=h["cara"]).json()
    assert [(w["code"], w["open_to_all"]) for w in ws] == [("DEFAULT", True)]
    assert len(client.get("/stations", headers=h["eddie"]).json()) == 1      # open to all


def test_workspace_management_and_validation(client, h):
    assert client.post("/workspaces", json={"code": "SCR", "name": "x"}, headers=h["dana"]).status_code == 403
    scr, ecr = _zones(client, h)
    assert scr["code"] == "SCR" and ecr["dn_direction"] == "Reverse"
    assert client.post("/workspaces", json={"code": "SCR", "name": "dup"}, headers=h["cora"]).status_code == 409
    assert client.post("/workspaces", json={"code": "NR", "name": "n", "dn_direction": "Up"},
                       headers=h["cora"]).status_code == 422
    assert client.put(f"/workspaces/{scr['id']}/members", json={"usernames": ["nobody"]},
                      headers=h["cora"]).status_code == 422
    assert [w["code"] for w in client.get("/workspaces", headers=h["dana"]).json()] == ["SCR"]
    assert [w["code"] for w in client.get("/workspaces", headers=h["cora"]).json()] == ["ECR", "SCR"]
    got = {w["code"]: w for w in client.get("/workspaces", headers=h["admin"]).json()}
    assert got["SCR"]["members"] == ["cara", "dana"]


def test_members_only_visibility(client, h):
    scr, ecr = _zones(client, h)
    a = _station(client, h["dana"], "103", name="Aler").json()            # dana's only workspace -> SCR
    assert a["workspace_code"] == "SCR"
    assert _station(client, h["dana"], "999", ws=ecr["id"]).status_code == 403
    e = _station(client, h["eddie"], "501", name="Patna").json()
    assert e["workspace_code"] == "ECR"
    assert [s["name"] for s in client.get("/stations", headers=h["dana"]).json()] == ["Aler"]
    assert [s["name"] for s in client.get("/stations", headers=h["eddie"]).json()] == ["Patna"]
    assert len(client.get("/stations", headers=h["cora"]).json()) == 2
    assert [s["name"] for s in client.get("/stations", params={"workspace_id": ecr["id"]},
                                          headers=h["cora"]).json()] == ["Patna"]
    # every station route is guarded
    for path in (f"/stations/{e['id']}", f"/stations/{e['id']}/verify", f"/stations/{e['id']}/tags",
                 f"/stations/{e['id']}/workflow", f"/stations/{e['id']}/allotment"):
        assert client.get(path, headers=h["dana"]).status_code == 403, path
    assert client.post(f"/stations/{e['id']}/tags", json={"tag_ref": "R-1", "tag_type": "N", "location_m": 1},
                       headers=h["dana"]).status_code == 403
    assert [(r["name"], r["workspace_code"]) for r in client.get("/dashboard", headers=h["dana"]).json()["stations"]] \
        == [("Aler", "SCR")]
    # a member of two workspaces has to choose
    client.put(f"/workspaces/{ecr['id']}/members", json={"usernames": ["eddie", "dana"]}, headers=h["cora"])
    r = _station(client, h["dana"], "104")
    assert r.status_code == 422 and "Choose a workspace" in r.text


def test_move_station_is_logged(client, h):
    scr, ecr = _zones(client, h)
    a = _station(client, h["dana"], "103").json()
    body = {"workspace_id": ecr["id"], "reason": "wrong zone"}
    assert client.post(f"/stations/{a['id']}/move-workspace", json=body, headers=h["dana"]).status_code == 403
    r = client.post(f"/stations/{a['id']}/move-workspace", json=body, headers=h["cora"])
    assert r.status_code == 200 and r.json()["workspace_code"] == "ECR"
    ch = client.get(f"/stations/{a['id']}/changes", headers=h["cora"]).json()
    assert any(c["field"] == "workspace" and c["before"] == "SCR" and c["after"] == "ECR" for c in ch)
    assert client.get(f"/stations/{a['id']}", headers=h["dana"]).status_code == 403


def test_zone_overrides(client, h):
    scr, ecr = _zones(client, h)
    a = _station(client, h["dana"], "103").json()
    e = _station(client, h["eddie"], "501").json()
    for sid, hd in ((a["id"], h["dana"]), (e["id"], h["eddie"])):
        el = client.post(f"/stations/{sid}/elements", json={"element_ref": "LC-1", "element_type": "LC Gate",
                         "location_m": 10000}, headers=hd).json()
        client.post(f"/stations/{sid}/tags", json={"tag_ref": "G-1", "tag_type": "G", "location_m": 9420,
                    "linked_element_id": el["id"]}, headers=hd)
    rules = {r["key"]: r for r in client.get("/checklist", headers=h["cora"]).json()["rules"]}
    h29 = rules["builtin.h2_9"]["id"]
    assert client.put(f"/workspaces/{ecr['id']}/overrides/{h29}", json={"params": {"min_m": 550}, "reason": "x"},
                      headers=h["dana"]).status_code == 403
    assert client.put(f"/workspaces/{ecr['id']}/overrides/{h29}", json={"reason": "x"},
                      headers=h["cora"]).status_code == 422
    assert client.put(f"/workspaces/{ecr['id']}/overrides/{h29}", json={"params": {"min_m": -1}, "reason": "x"},
                      headers=h["cora"]).status_code == 422
    r = client.put(f"/workspaces/{ecr['id']}/overrides/{h29}",
                   json={"params": {"min_m": 550, "max_m": 850}, "reason": "ECR follows BR-008"}, headers=h["cora"])
    assert r.status_code == 200 and r.json()["override"]["params"]["min_m"] == 550

    def h29_status(sid, hd):
        v = client.get(f"/stations/{sid}/verify", headers=hd).json()
        return [x["status"] for x in v["results"] if x["clause"] == "H2.9"]
    assert h29_status(a["id"], h["dana"]) == ["FAIL"]      # SCR: standard >= 600 m, gate tag at 580 m
    assert h29_status(e["id"], h["eddie"]) == ["PASS"]     # ECR: 550-850 m
    cl = {r["key"]: r for r in client.get("/checklist", params={"workspace_id": ecr["id"]},
                                          headers=h["eddie"]).json()["rules"]}
    assert cl["builtin.h2_9"]["override"]["reason"] == "ECR follows BR-008"
    assert cl["builtin.h2_9"]["effective"]["params"]["min_m"] == 550 and cl["builtin.h2_9"]["params"]["min_m"] == 600
    assert cl["builtin.h2_5"]["override"] is None
    # disable a rule for one zone only
    client.put(f"/workspaces/{ecr['id']}/overrides/{rules['builtin.h2_26']['id']}",
               json={"enabled": False, "reason": "trial"}, headers=h["cora"])
    v = client.get(f"/stations/{e['id']}/verify", headers=h["eddie"]).json()
    assert "H2.26" not in v["summary"]["clauses_checked"]
    assert "H2.26" in client.get(f"/stations/{a['id']}/verify", headers=h["dana"]).json()["summary"]["clauses_checked"]
    ch = client.get("/checklist/changes", headers=h["cora"]).json()
    assert any(c["action"] == "override" and c["reason"].startswith("[ECR]") for c in ch)
    r = client.request("DELETE", f"/workspaces/{ecr['id']}/overrides/{h29}", json={"reason": "back to standard"},
                       headers=h["cora"])
    assert r.status_code == 200 and h29_status(e["id"], h["eddie"]) == ["FAIL"]


def test_allotment_charts_are_per_zone(client, h):
    scr, ecr = _zones(client, h)
    rows = [{"name": "Aler", "station_id": "00103", "tag_ranges": "775-902", "tin_ranges": "169-192"}]
    c = client.post("/allotment-charts", json={"title": "SC chart", "division": "Secunderabad",
                    "workspace_id": scr["id"], "rows": rows}, headers=h["cora"]).json()
    assert c["workspace_code"] == "SCR"
    c2 = client.post("/allotment-charts", json={"title": "Danapur chart", "division": "Secunderabad",
                     "workspace_id": ecr["id"], "rows": rows}, headers=h["cora"]).json()
    ids = {x["id"]: x for x in client.get("/allotment-charts", headers=h["cora"]).json()}
    assert ids[c["id"]]["is_current"] and ids[c2["id"]]["is_current"]   # same division name, different zone
    assert [x["title"] for x in client.get("/allotment-charts", headers=h["dana"]).json()] == ["SC chart"]
    assert client.get(f"/allotment-charts/{c2['id']}", headers=h["dana"]).status_code == 404
    a = _station(client, h["dana"], "103").json()
    assert client.get(f"/stations/{a['id']}/allotment", headers=h["dana"]).json()["chart"]["title"] == "SC chart"


def test_upgrade_moves_existing_data_to_scr(client, h):
    from app import models
    from app.database import SessionLocal
    from app.workspaces.service import ensure_initial_workspace
    sid = _station(client, h["dana"], "103").json()["id"]
    with SessionLocal() as db:        # rewind to a pre-workspace database
        db.get(models.StationORM, sid).workspace_id = None
        db.query(models.WorkspaceMemberORM).delete()
        db.query(models.WorkspaceORM).delete()
        db.commit()
        ensure_initial_workspace(db)
        ensure_initial_workspace(db)      # idempotent
        ws = db.query(models.WorkspaceORM).all()
        assert [(w.code, w.dn_direction, w.open_to_all) for w in ws] == [("SCR", "Nominal", False)]
        assert db.get(models.StationORM, sid).workspace_id == ws[0].id
        assert {m.username for m in ws[0].members} == {"admin", "dana", "eddie", "cara", "cora"}


def test_handoffs_only_to_members(client, h):
    scr, ecr = _zones(client, h)
    a = _station(client, h["dana"], "103").json()
    r = client.get("/auth/users/by-role/checker", params={"workspace_id": ecr["id"]}, headers=h["dana"])
    assert r.json() == []
    assert [u["username"] for u in client.get("/auth/users/by-role/checker", params={"workspace_id": scr["id"]},
                                              headers=h["dana"]).json()] == ["cara"]
    r = client.put(f"/stations/{a['id']}/assign-designer", json={"designer_username": "eddie"}, headers=h["admin"])
    assert r.status_code == 422 and "not a member of workspace SCR" in r.text
    assert client.post(f"/stations/{a['id']}/self-check", json={}, headers=h["dana"]).status_code == 200
    client.put(f"/workspaces/{scr['id']}/members", json={"usernames": ["dana"]}, headers=h["cora"])   # cara leaves SCR
    r = client.post(f"/stations/{a['id']}/submit", json={"assigned_checker_username": "cara"}, headers=h["dana"])
    assert r.status_code == 422 and "not a member" in r.text
    assert [u["username"] for u in client.get("/workspaces/users", headers=h["cora"]).json()] == \
        ["admin", "cara", "cora", "dana", "eddie"]
    assert client.get("/workspaces/users", headers=h["dana"]).status_code == 403
