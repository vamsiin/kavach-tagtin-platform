"""
Phase 3: BRD FR-008 observations (lifecycle, permissions, workflow gates) and the
km/metres chainage guard.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.observations import rules as obs

os.environ.setdefault("JWT_SECRET", "test-secret-for-phase3-tests")


# ---------------------------------------------------------------------------
# Pure lifecycle rules
# ---------------------------------------------------------------------------
def S(status, raised_by="cara", resolved_by=None):
    return obs.ObsState(status, raised_by, resolved_by)


def test_lifecycle_happy_path():
    assert obs.apply(S("open"), obs.RESOLVE, "dana", "designer", "moved R-795") == "resolved"
    assert obs.apply(S("resolved", resolved_by="dana"), obs.CLOSE, "cara", "checker") == "closed"
    assert obs.apply(S("closed"), obs.REOPEN, "ana", "approver", "still wrong") == "reopened"
    assert obs.apply(S("reopened"), obs.RESOLVE, "dana", "designer", "fixed again") == "resolved"


@pytest.mark.parametrize("state,action,user,role,text", [
    ("open", obs.RESOLVE, "cara", "checker", "x"),        # reviewers don't resolve
    ("open", obs.RESOLVE, "dana", "designer", ""),        # resolve needs a note
    ("open", obs.CLOSE, "cara", "checker", ""),           # can't close unresolved
    ("resolved", obs.CLOSE, "dana", "designer", ""),      # designers don't close
    ("resolved", obs.REOPEN, "cara", "checker", ""),      # reopen needs a reason
    ("open", obs.WITHDRAW, "chris", "checker", "oops"),   # only the raiser
    ("closed", obs.WITHDRAW, "cara", "checker", "oops"),  # final
    ("withdrawn", obs.COMMENT, "cara", "checker", "hi"),  # final
])
def test_lifecycle_rejections(state, action, user, role, text):
    with pytest.raises(obs.ObservationError):
        obs.apply(S(state), action, user, role, text)


def test_resolver_cannot_close_own_fix_but_admin_can():
    st = S("resolved", resolved_by="root")
    with pytest.raises(obs.ObservationError, match="Segregation"):
        obs.apply(S("resolved", resolved_by="cara"), obs.CLOSE, "cara", "checker")
    assert obs.apply(st, obs.CLOSE, "root", "admin") == "closed"


def test_blocking_counts_ignore_info_and_final():
    rows = [("open", "major"), ("reopened", "minor"), ("resolved", "major"),
            ("open", "info"), ("closed", "major"), ("withdrawn", "major")]
    assert obs.blocking_counts(rows) == {"unresolved": 2, "unverified": 1}


# ---------------------------------------------------------------------------
# HTTP
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
    for u, role in (("dana", "designer"), ("cara", "checker"), ("chris", "checker"),
                    ("ana", "approver")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, **{u: login(u, "pass12345") for u in ("dana", "cara", "chris", "ana")}}


def _station(client, h):
    sid = client.post("/stations", json={
        "name": "ALER", "kavach_station_id": "103", "sip_drawing_number": "IPU.1100A",
        "kavach_version": "2", "sip_version": "1", "guideline_version": "0",
    }, headers=h["dana"]).json()["id"]
    return sid


def _submit(client, h, sid):
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    r = client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                    headers=h["dana"])
    assert r.status_code == 200, r.text


def _raise(client, h, sid, who="cara", **kw):
    body = {"description": "R-795 too far from S3", "severity": "major", **kw}
    return client.post(f"/stations/{sid}/observations", json=body, headers=h[who])


def _act(client, h, sid, oid, action, who, comment=""):
    return client.post(f"/stations/{sid}/observations/{oid}/{action}",
                       json={"comment": comment}, headers=h[who])


def test_raise_numbering_subject_by_ref_and_thread(client, h):
    sid = _station(client, h)
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-795", "tag_type": "N",
                "location_km": 263.152}, headers=h["dana"])
    r1 = _raise(client, h, sid, subject_kind="tag", subject_ref="R-795", clause="H2.6",
                category="annexure-h")
    assert r1.status_code == 200, r1.text
    o1 = r1.json()
    assert o1["label"] == "OBS-001" and o1["status"] == "open"
    assert o1["subject_ref"] == "R-795" and o1["subject_id"] and o1["subject_exists"]
    assert o1["raised_by"] == "cara" and o1["layout_version"] == "2.1.0"
    assert o1["comments"][0]["action"] == "raise"
    assert set(o1["allowed_actions"]) == {"withdraw", "comment"}
    assert _raise(client, h, sid).json()["label"] == "OBS-002"

    lst = client.get(f"/stations/{sid}/observations", headers=h["dana"]).json()
    assert lst["summary"]["unresolved"] == 2
    assert set(lst["observations"][0]["allowed_actions"]) == {"resolve", "comment"}


def test_raise_validation_and_permissions(client, h):
    sid = _station(client, h)
    assert _raise(client, h, sid, who="dana").status_code == 403
    assert _raise(client, h, sid, severity="huge").status_code == 422
    assert _raise(client, h, sid, subject_kind="tag", subject_ref="NOPE").status_code == 422
    assert _raise(client, h, sid, subject_kind="planet").status_code == 422
    r = client.post(f"/stations/{sid}/observations", json={"description": ""}, headers=h["cara"])
    assert r.status_code == 422


def test_observation_survives_deletion_of_its_tag(client, h):
    sid = _station(client, h)
    tid = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                      "location_km": 1.0}, headers=h["dana"]).json()["id"]
    oid = _raise(client, h, sid, subject_kind="tag", subject_id=tid).json()["id"]
    assert client.delete(f"/stations/{sid}/tags/{tid}", headers=h["dana"]).status_code == 204
    o = client.get(f"/stations/{sid}/observations", headers=h["dana"]).json()["observations"][0]
    assert o["id"] == oid and o["subject_ref"] == "R-1" and o["subject_exists"] is False


def test_full_review_cycle_with_gates(client, h):
    sid = _station(client, h)
    _submit(client, h, sid)
    oid = _raise(client, h, sid).json()["id"]

    # checker cannot mark checked with an open observation
    r = client.post(f"/stations/{sid}/check", json={}, headers=h["cara"])
    assert r.status_code == 409 and "still open" in r.json()["detail"]

    client.post(f"/stations/{sid}/request-changes", json={"comment": "see OBS-001"}, headers=h["cara"])
    # designer cannot self-check again while it's unresolved
    r = client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])
    assert r.status_code == 409 and "observation" in r.json()["detail"]

    assert _act(client, h, sid, oid, "resolve", "dana").status_code == 409  # needs a note
    r = _act(client, h, sid, oid, "resolve", "dana", "Moved R-795 to 263.100")
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert r.json()["resolved_by"] == "dana"

    _submit(client, h, sid)  # unverified doesn't block submit
    r = client.post(f"/stations/{sid}/check", json={}, headers=h["cara"])
    assert r.status_code == 409 and "not been verified" in r.json()["detail"]

    # any reviewer may close, the raiser needn't
    r = _act(client, h, sid, oid, "close", "chris", "Verified")
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200

    thread = [c["action"] for c in r.json()["comments"]]
    assert thread == ["raise", "resolve", "close"]


def test_info_observations_never_block(client, h):
    sid = _station(client, h)
    _submit(client, h, sid)
    _raise(client, h, sid, severity="info", description="Consider legend note")
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200


def test_reopen_and_withdraw(client, h):
    sid = _station(client, h)
    oid = _raise(client, h, sid).json()["id"]
    _act(client, h, sid, oid, "resolve", "dana", "done")
    _act(client, h, sid, oid, "close", "cara", "ok")
    r = _act(client, h, sid, oid, "reopen", "ana", "Still 820m, max 1000m ok but G-tag wrong")
    assert r.json()["status"] == "reopened" and r.json()["resolved_by"] is None

    oid2 = _raise(client, h, sid, description="dup").json()["id"]
    assert _act(client, h, sid, oid2, "withdraw", "chris", "not mine").status_code == 409
    r = _act(client, h, sid, oid2, "withdraw", "cara", "duplicate of OBS-001")
    assert r.json()["status"] == "withdrawn"
    assert _act(client, h, sid, oid2, "comments", "cara", "late").status_code == 409

    s = client.get(f"/stations/{sid}/observations", headers=h["cara"]).json()["summary"]
    assert s["by_status"]["reopened"] == 1 and s["by_status"]["withdrawn"] == 1
    assert s["unresolved"] == 1


def test_comments_append_without_status_change(client, h):
    sid = _station(client, h)
    oid = _raise(client, h, sid).json()["id"]
    r = _act(client, h, sid, oid, "comments", "dana", "Which revision of the SIP?")
    assert r.status_code == 200 and r.json()["status"] == "open"
    assert r.json()["comments"][-1]["text"] == "Which revision of the SIP?"
    assert _act(client, h, sid, oid, "comments", "dana", "  ").status_code == 409


def test_railway_submission_blocked_by_unverified_observation(client, h):
    sid = _station(client, h)
    _submit(client, h, sid)
    client.post(f"/stations/{sid}/check", json={}, headers=h["cara"])
    client.post(f"/stations/{sid}/approve", json={}, headers=h["ana"])
    oid = _raise(client, h, sid, who="ana").json()["id"]
    rail = {"reference_no": "R/1", "submitted_on": "2026-09-25"}
    assert client.post(f"/stations/{sid}/railway-submit", json=rail,
                       headers=h["ana"]).status_code == 409
    _act(client, h, sid, oid, "resolve", "admin", "Clarified on drawing")
    assert client.post(f"/stations/{sid}/railway-submit", json=rail,
                       headers=h["ana"]).status_code == 409
    _act(client, h, sid, oid, "close", "ana", "ok")
    assert client.post(f"/stations/{sid}/railway-submit", json=rail,
                       headers=h["ana"]).status_code == 200
    # frozen after railway submission
    assert _raise(client, h, sid, who="ana").status_code == 409


def test_station_delete_cascades_observations(client, h):
    sid = _station(client, h)
    _raise(client, h, sid)
    assert client.delete(f"/stations/{sid}", headers=h["admin"]).status_code == 204


# ---------------------------------------------------------------------------
# km / metres guard
# ---------------------------------------------------------------------------
def test_metres_entered_as_km_rejected_with_hint(client, h):
    sid = _station(client, h)
    r = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                    "location_km": 262910}, headers=h["dana"])
    assert r.status_code == 422 and "262.91" in r.text
    r = client.post(f"/stations/{sid}/tins", json={"tin_no": 1, "section_type": "Station",
                    "start_km": 262.9, "end_km": 263152}, headers=h["dana"])
    assert r.status_code == 422 and "end_km" in r.text


def test_legacy_metre_rows_still_list_and_fail_verification(client, h):
    """Rows stored before the guard (like the real Aler station) must still load,
    and verification must flag them so they can't pass self-check."""
    sid = _station(client, h)
    from app.database import SessionLocal
    from app import models
    db = SessionLocal()
    db.add(models.TagORM(station_id=sid, tag_ref="R-793", tag_type="S", location_km=262910))
    db.commit()
    db.close()
    r = client.get(f"/stations/{sid}/tags", headers=h["dana"])
    assert r.status_code == 200 and r.json()[0]["location_km"] == 262910
    rep = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    units = [x for x in rep["results"] if x["clause"] == "DATA-UNITS"]
    assert units and units[0]["status"] == "FAIL" and "262.91" in units[0]["message"]
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 409
