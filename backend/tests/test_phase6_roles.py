"""
Phase 6: BRD Section 7 roles -- Project Manager (monitor / assign, no edit rights) and
Configuration Manager (versions, baselines, checklist, reopen), plus the central
permission matrix that now also stops checkers/approvers editing layouts.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-phase6-tests")

USERS = {"dana": "designer", "dave": "designer", "cara": "checker", "chris": "checker",
         "ana": "approver", "pam": "project_manager", "cora": "config_manager"}


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
    for u, role in USERS.items():
        r = client.post("/auth/users", json={"username": u, "full_name": u.title(), "role": role,
                                             "password": "pass12345"}, headers=admin)
        assert r.status_code == 200, r.text
    return {"admin": admin, **{u: login(u, "pass12345") for u in USERS}}


def _station(client, h, who="dana", sid="103"):
    r = client.post("/stations", json={
        "name": "ALER", "kavach_station_id": sid, "sip_drawing_number": "IBU.1100A",
        "kavach_version": "2", "sip_version": "0", "guideline_version": "3"}, headers=h[who])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _tag(client, h, sid, who, ref="R-1"):
    return client.post(f"/stations/{sid}/tags", json={"tag_ref": ref, "tag_type": "N", "location_m": 100},
                       headers=h[who])


def _approve(client, h, sid):
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                       headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200
    assert client.post(f"/stations/{sid}/approve", json={}, headers=h["ana"]).status_code == 200


# ---------------------------------------------------------------------------
def test_new_roles_exist_and_me_reports_permissions(client, h):
    me = client.get("/auth/me", headers=h["pam"]).json()
    assert me["role"] == "project_manager" and me["role_label"] == "Project Manager"
    assert set(me["permissions"]) == {"assign.checker", "assign.designer", "dashboard.view", "reports.generate"}
    cm = client.get("/auth/me", headers=h["cora"]).json()
    assert {"checklist.edit", "station.versions", "baseline.create"} <= set(cm["permissions"])
    assert "registers.edit" not in cm["permissions"]
    assert "users.manage" in client.get("/auth/me", headers=h["admin"]).json()["permissions"]


def test_layout_editing_limited_to_designers(client, h):
    for who in ("cara", "ana", "pam", "cora"):
        r = client.post("/stations", json={"name": "X", "kavach_station_id": f"x-{who}"}, headers=h[who])
        assert r.status_code == 403, who
    sid = _station(client, h)
    for who in ("cara", "ana", "pam", "cora"):
        assert _tag(client, h, sid, who).status_code == 403, who
        r = client.post(f"/stations/{sid}/documents", files={"file": ("s.pdf", io.BytesIO(b"%PDF"))},
                        data={"doc_type": "SIP"}, headers=h[who])
        assert r.status_code == 403, who
    assert _tag(client, h, sid, "dana").status_code == 200
    assert _tag(client, h, sid, "admin", "R-2").status_code == 200


def test_project_manager_cannot_act_in_workflow_or_reviews(client, h):
    sid = _station(client, h)
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["pam"]).status_code == 409
    assert client.post(f"/stations/{sid}/observations", json={"description": "x"},
                       headers=h["pam"]).status_code == 403
    assert client.get("/checklist", headers=h["pam"]).json()["can_edit"] is False


def test_assign_designer_restricts_editing_and_workflow(client, h):
    sid = _station(client, h)
    assert client.put(f"/stations/{sid}/assign-designer", json={"designer_username": "dave"},
                      headers=h["dana"]).status_code == 403
    assert client.put(f"/stations/{sid}/assign-designer", json={"designer_username": "cara"},
                      headers=h["pam"]).status_code == 422  # not a designer
    r = client.put(f"/stations/{sid}/assign-designer", json={"designer_username": "dave", "comment": "workload"},
                   headers=h["pam"])
    assert r.status_code == 200 and r.json()["assigned_designer"] == "dave"
    # dana (creator) now locked out; dave and admin fine
    assert _tag(client, h, sid, "dana").status_code == 403
    assert _tag(client, h, sid, "dave").status_code == 200
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 409
    up = client.post(f"/stations/{sid}/documents", files={"file": ("s.pdf", io.BytesIO(b"%PDF"))},
                     data={"doc_type": "SIP"}, headers=h["dana"])
    assert up.status_code == 403
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dave"]).status_code == 200
    wf = client.get(f"/stations/{sid}/workflow", headers=h["pam"]).json()
    assert wf["assigned_designer"] == "dave"
    ch = client.get(f"/stations/{sid}/changes", headers=h["pam"]).json()
    assert ch[0]["field"] == "assigned_designer" and ch[0]["after"] == "dave" and ch[0]["reason"] == "workload"
    # unassign
    client.post(f"/stations/{sid}/revise", json={}, headers=h["dave"])
    client.put(f"/stations/{sid}/assign-designer", json={"designer_username": None}, headers=h["pam"])
    assert _tag(client, h, sid, "dana", "R-9").status_code == 200


def test_reassign_checker(client, h):
    sid = _station(client, h)
    assert client.post(f"/stations/{sid}/reassign-checker", json={"assigned_checker_username": "chris"},
                       headers=h["pam"]).status_code == 409  # not submitted
    client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])
    client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"}, headers=h["dana"])
    assert client.post(f"/stations/{sid}/reassign-checker", json={"assigned_checker_username": "chris"},
                       headers=h["dana"]).status_code == 409  # designers can't
    assert client.post(f"/stations/{sid}/reassign-checker", json={"assigned_checker_username": "ana"},
                       headers=h["pam"]).status_code == 409  # not a checker
    r = client.post(f"/stations/{sid}/reassign-checker",
                    json={"assigned_checker_username": "chris", "comment": "Cara on leave"}, headers=h["pam"])
    assert r.status_code == 200 and r.json()["assigned_checker"] == "chris"
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 409
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["chris"]).status_code == 200
    ev = [e for e in client.get(f"/stations/{sid}/workflow", headers=h["pam"]).json()["history"]
          if e["action"] == "reassign"][0]
    assert ev["actor_username"] == "pam" and ev["target_username"] == "chris"


def test_dashboard(client, h):
    s1 = _station(client, h, sid="1")
    s2 = _station(client, h, sid="2")
    client.put(f"/stations/{s2}/assign-designer", json={"designer_username": "dave"}, headers=h["pam"])
    client.post(f"/stations/{s1}/self-check", json={}, headers=h["dana"])
    client.post(f"/stations/{s1}/submit", json={"assigned_checker_username": "cara"}, headers=h["dana"])
    client.post(f"/stations/{s1}/observations", json={"description": "check R-1"}, headers=h["cara"])
    d = client.get("/dashboard", headers=h["pam"]).json()
    assert d["total"] == 2 and d["by_status"] == {"submitted": 1, "draft": 1}
    rows = {r["id"]: r for r in d["stations"]}
    assert rows[s1]["assigned_checker"] == "cara" and rows[s1]["open_observations"] == 1
    assert rows[s1]["last_action"] == "submit" and rows[s1]["days_in_status"] == 0
    assert rows[s2]["assigned_designer"] == "dave" and rows[s2]["missing_inputs"] == 3
    assert client.get("/dashboard").status_code == 401


def test_config_manager_versions(client, h):
    sid = _station(client, h)
    assert client.put(f"/stations/{sid}/versions", json={"sip_version": "1", "reason": "x"},
                      headers=h["dana"]).status_code == 403
    assert client.put(f"/stations/{sid}/versions", json={"sip_version": "1", "reason": ""},
                      headers=h["cora"]).status_code == 422
    r = client.put(f"/stations/{sid}/versions", json={"sip_version": "1", "reason": "SIP revised to Rev-1"},
                   headers=h["cora"])
    assert r.status_code == 200 and r.json()["layout_version"] == "2.1.3"
    assert client.put(f"/stations/{sid}/versions", json={"sip_version": "1", "reason": "again"},
                      headers=h["cora"]).status_code == 422
    ch = client.get(f"/stations/{sid}/changes", headers=h["dana"]).json()[0]
    assert (ch["field"], ch["before"], ch["after"], ch["changed_by_role"]) == ("sip_version", "0", "1", "config_manager")
    _approve(client, h, sid)
    assert client.put(f"/stations/{sid}/versions", json={"sip_version": "2", "reason": "x"},
                      headers=h["cora"]).status_code == 409


def test_config_manager_checklist_and_reopen(client, h):
    rid = next(r for r in client.get("/checklist", headers=h["cora"]).json()["rules"]
               if r["key"] == "builtin.h2_9")["id"]
    assert client.get("/checklist", headers=h["cora"]).json()["can_edit"] is True
    r = client.put(f"/checklist/rules/{rid}", json={"params": {"min_m": 550, "max_m": 850},
                   "reason": "BR-008"}, headers=h["cora"])
    assert r.status_code == 200
    sid = _station(client, h)
    _approve(client, h, sid)
    assert client.post(f"/stations/{sid}/reopen", json={"comment": "Rev-1"}, headers=h["ana"]).status_code == 409
    assert client.post(f"/stations/{sid}/reopen", json={"comment": "Rev-1"}, headers=h["cora"]).json()["status"] == "draft"


def test_baselines_and_diff(client, h):
    sid = _station(client, h)
    _tag(client, h, sid, "dana", "R-1")
    assert client.post(f"/stations/{sid}/baselines", json={"label": "B0"}, headers=h["cora"]).status_code == 409
    _approve(client, h, sid)
    assert client.post(f"/stations/{sid}/baselines", json={"label": "B0"}, headers=h["dana"]).status_code == 403
    r = client.post(f"/stations/{sid}/baselines", json={"label": "B0 - first approval", "notes": "as approved"},
                    headers=h["cora"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["layout_version"] == "2.0.3" and b["counts"] == {"elements": 0, "tags": 1, "tins": 0}
    assert b["verification_summary"]["fail_count"] == 0 and b["checklist_version"] > 0
    assert client.post(f"/stations/{sid}/baselines", json={"label": "B0 - first approval"},
                       headers=h["cora"]).status_code == 409
    d0 = client.get(f"/stations/{sid}/baselines/{b['id']}/diff", headers=h["pam"]).json()
    assert d0["identical"] is True and d0["rows"] == []
    # new revision: reopen, change a tag, add one, bump SIP version
    client.post(f"/stations/{sid}/reopen", json={"comment": "Rev-1"}, headers=h["cora"])
    tag = client.get(f"/stations/{sid}/tags", headers=h["dana"]).json()[0]
    client.put(f"/stations/{sid}/tags/{tag['id']}", json={**tag, "location_m": 120}, headers=h["dana"])
    _tag(client, h, sid, "dana", "R-2")
    client.put(f"/stations/{sid}/versions", json={"sip_version": "1", "reason": "Rev-1"}, headers=h["cora"])
    d1 = client.get(f"/stations/{sid}/baselines/{b['id']}/diff", headers=h["pam"]).json()
    changes = {r["item"]: r for r in d1["rows"]}
    assert changes["tag R-2"]["change"] == "added"
    assert changes["tag R-1"]["change"] == "changed" and any("location_m" in x for x in changes["tag R-1"]["details"])
    assert d1["identical"] is False and d1["current_layout_version"] == "2.1.3"
    lst = client.get(f"/stations/{sid}/baselines", headers=h["dana"]).json()
    assert [x["label"] for x in lst] == ["B0 - first approval"]


def test_reports_include_new_records(client, h):
    sid = _station(client, h)
    client.put(f"/stations/{sid}/assign-designer", json={"designer_username": "dana", "comment": "owner"},
               headers=h["pam"])
    client.put(f"/stations/{sid}/versions", json={"guideline_version": "4", "reason": "Amdt-6"}, headers=h["cora"])
    from app.database import SessionLocal
    from app import models
    from app.routers.reports import build_report
    with SessionLocal() as db:
        st = db.get(models.StationORM, sid)
        u = db.query(models.UserORM).filter_by(username="pam").first()
        audit = build_report(db, st, u, "audit").plain_text()
        revs = build_report(db, st, u, "revisions").plain_text()
        appr = build_report(db, st, u, "approval").plain_text()
    assert "assigned_designer: - -> dana" in audit and "guideline_version: 3 -> 4" in audit
    assert "guideline_version | 3 | 4 | cora | Amdt-6" in revs
    assert "Assigned designer: dana" in appr
