"""
Phase 2 (BRD FR-009): Self Check as a recorded state, Revise, and Railway
Submission as a terminal state with its own frozen record.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest
from fastapi.testclient import TestClient

from app.domain import User
from app.workflow.engine import (
    attempt_transition, allowed_actions, StationWorkflowState, WorkflowError,
    DRAFT, SELF_CHECKED, SUBMITTED, APPROVED, RAILWAY_SUBMITTED,
    SELF_CHECK, REVISE, SUBMIT, RAILWAY_SUBMIT, REOPEN,
)

os.environ.setdefault("JWT_SECRET", "test-secret-for-phase2-tests")
NOW = "2026-09-25T10:00:00Z"


def mk(username, role):
    return User(id=None, username=username, full_name=username, role=role, is_active=True)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def test_self_check_requires_zero_failures():
    d = mk("dana", "designer")
    for bad in (None, 3):
        with pytest.raises(WorkflowError):
            attempt_transition(StationWorkflowState(DRAFT), SELF_CHECK, d, 1, NOW,
                               verification_fail_count=bad)
    st, ev = attempt_transition(StationWorkflowState(DRAFT), SELF_CHECK, d, 1, NOW,
                                verification_fail_count=0)
    assert st.status == SELF_CHECKED and st.self_checked_by == "dana"
    assert ev.verification_fail_count == 0


def test_cannot_submit_straight_from_draft():
    with pytest.raises(WorkflowError, match="not valid from status 'draft'"):
        attempt_transition(StationWorkflowState(DRAFT), SUBMIT, mk("dana", "designer"), 1, NOW,
                           target_username="cara", target_role="checker")


def test_only_self_checker_or_admin_may_submit():
    st = StationWorkflowState(SELF_CHECKED, self_checked_by="dana")
    with pytest.raises(WorkflowError, match="self-checked by 'dana'"):
        attempt_transition(st, SUBMIT, mk("dave", "designer"), 1, NOW,
                           target_username="cara", target_role="checker")
    new, _ = attempt_transition(st, SUBMIT, mk("root", "admin"), 1, NOW,
                                target_username="cara", target_role="checker")
    assert new.status == SUBMITTED


def test_revise_discards_self_check():
    st = StationWorkflowState(SELF_CHECKED, self_checked_by="dana")
    new, _ = attempt_transition(st, REVISE, mk("dana", "designer"), 1, NOW)
    assert new.status == DRAFT and new.self_checked_by is None


def test_railway_submit_roles_and_terminality():
    st = StationWorkflowState(APPROVED, submitted_by="dana", checked_by="cara")
    for role in ("designer", "checker"):
        with pytest.raises(WorkflowError):
            attempt_transition(st, RAILWAY_SUBMIT, mk("x", role), 1, NOW)
    new, _ = attempt_transition(st, RAILWAY_SUBMIT, mk("ana", "approver"), 1, NOW)
    assert new.status == RAILWAY_SUBMITTED
    assert allowed_actions(new, mk("ana", "approver")) == []
    assert allowed_actions(new, mk("root", "admin")) == [REOPEN]
    with pytest.raises(WorkflowError):
        attempt_transition(new, REOPEN, mk("ana", "approver"), 1, NOW)


def test_designer_allowed_actions_through_self_check():
    d = mk("dana", "designer")
    assert allowed_actions(StationWorkflowState(DRAFT), d) == [SELF_CHECK]
    assert set(allowed_actions(StationWorkflowState(SELF_CHECKED), d)) == {REVISE, SUBMIT}


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
    for u, role in (("dana", "designer"), ("dave", "designer"), ("cara", "checker"),
                    ("ana", "approver")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, **{u: login(u, "pass12345") for u in ("dana", "dave", "cara", "ana")}}


def _station(client, headers):
    return client.post("/stations", json={
        "name": "ALER", "kavach_station_id": "103", "sip_drawing_number": "IPU.1100A",
        "kavach_version": "2", "sip_version": "1", "guideline_version": "0",
    }, headers=headers).json()["id"]


def _to_approved(client, h, sid):
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                       headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200
    assert client.post(f"/stations/{sid}/approve", json={}, headers=h["ana"]).status_code == 200


RAIL = {"reference_no": "QFTL/KAV/ALER/001", "submitted_on": "2026-09-25",
        "addressed_to": "Sr. DSTE/Co", "remarks": "Rev 2 package"}


def test_self_check_failure_reports_clauses_and_changes_nothing(client, h):
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "9"},
                      headers=h["dana"]).json()["id"]  # versions missing -> H2.1/H2.2 fail
    r = client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["fail_count"] >= 1 and "H2.1" in d["clauses_failing"]
    wf = client.get(f"/stations/{sid}/workflow", headers=h["dana"]).json()
    assert wf["status"] == "draft" and wf["history"] == []


def test_self_checked_locks_registers_and_revise_unlocks(client, h):
    sid = _station(client, h["dana"])
    r = client.post(f"/stations/{sid}/self-check", json={"comment": "all clear"}, headers=h["dana"])
    assert r.status_code == 200 and r.json()["status"] == "self_checked"
    wf = client.get(f"/stations/{sid}/workflow", headers=h["dana"]).json()
    assert wf["self_checked_by"] == "dana"
    assert wf["history"][0]["verification_fail_count"] == 0
    assert wf["history"][0]["comment"] == "all clear"

    tag = {"tag_ref": "R-1", "tag_type": "N", "location_m": 1000}
    assert client.post(f"/stations/{sid}/tags", json=tag, headers=h["dana"]).status_code == 409
    up = client.post(f"/stations/{sid}/documents", files={"file": ("s.pdf", io.BytesIO(b"x"))},
                     data={"doc_type": "SIP"}, headers=h["dana"])
    assert up.status_code == 409

    r = client.post(f"/stations/{sid}/revise", json={}, headers=h["dana"])
    assert r.json()["status"] == "draft"
    assert client.post(f"/stations/{sid}/tags", json=tag, headers=h["dana"]).status_code == 200
    # the earlier self-check no longer counts
    r = client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                    headers=h["dana"])
    assert r.status_code == 409


def test_other_designer_cannot_submit_someone_elses_self_check(client, h):
    sid = _station(client, h["dana"])
    client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])
    r = client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                    headers=h["dave"])
    assert r.status_code == 409 and "self-checked by 'dana'" in r.json()["detail"]


def test_request_changes_requires_fresh_self_check(client, h):
    sid = _station(client, h["dana"])
    client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"])
    client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"}, headers=h["dana"])
    client.post(f"/stations/{sid}/request-changes", json={"comment": "rework"}, headers=h["cara"])
    wf = client.get(f"/stations/{sid}/workflow", headers=h["dana"]).json()
    assert wf["status"] == "draft" and wf["self_checked_by"] is None
    assert wf["allowed_actions"] == ["self_check"]


def test_railway_submission_full_lifecycle(client, h):
    sid = _station(client, h["dana"])
    client.post(f"/stations/{sid}/documents", files={"file": ("sip.pdf", io.BytesIO(b"%PDF"))},
                data={"doc_type": "SIP"}, headers=h["dana"])
    _to_approved(client, h, sid)

    r = client.post(f"/stations/{sid}/railway-submit", json=RAIL, headers=h["ana"])
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["reference_no"] == RAIL["reference_no"] and rec["submitted_on"] == "2026-09-25"
    assert rec["layout_version"] == "2.1.0" and rec["recorded_by"] == "ana"
    assert rec["layout_snapshot"]["station"]["kavach_station_id"] == "103"
    assert rec["input_snapshot"][0]["doc_type"] == "SIP"

    st = client.get(f"/stations/{sid}", headers=h["dana"]).json()
    assert st["status"] == "railway_submitted"
    wf = client.get(f"/stations/{sid}/workflow", headers=h["ana"]).json()
    last = wf["history"][-1]
    assert last["action"] == "railway_submit" and last["id"] == rec["workflow_event_id"]
    assert RAIL["reference_no"] in last["comment"]
    assert wf["allowed_actions"] == []

    lst = client.get(f"/stations/{sid}/railway-submissions", headers=h["cara"]).json()
    assert [x["id"] for x in lst] == [rec["id"]]


def test_railway_submission_snapshot_is_frozen_after_reopen(client, h):
    sid = _station(client, h["dana"])
    _to_approved(client, h, sid)
    client.post(f"/stations/{sid}/railway-submit", json=RAIL, headers=h["ana"])
    assert client.post(f"/stations/{sid}/reopen", json={"comment": "railway remarks"},
                       headers=h["admin"]).json()["status"] == "draft"
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-9", "tag_type": "N",
                "location_m": 5000}, headers=h["dana"])
    rec = client.get(f"/stations/{sid}/railway-submissions", headers=h["dana"]).json()[0]
    assert rec["layout_snapshot"]["tags"] == []


def test_railway_submit_guards(client, h):
    sid = _station(client, h["dana"])
    # not approved yet
    assert client.post(f"/stations/{sid}/railway-submit", json=RAIL,
                       headers=h["ana"]).status_code == 409
    _to_approved(client, h, sid)
    # wrong role
    assert client.post(f"/stations/{sid}/railway-submit", json=RAIL,
                       headers=h["cara"]).status_code == 409
    # validation
    assert client.post(f"/stations/{sid}/railway-submit", json={**RAIL, "reference_no": "  "},
                       headers=h["ana"]).status_code == 422
    assert client.post(f"/stations/{sid}/railway-submit", json={**RAIL, "submitted_on": "25/09/2026"},
                       headers=h["ana"]).status_code == 422
    # nothing recorded by any failed attempt
    assert client.get(f"/stations/{sid}/railway-submissions", headers=h["ana"]).json() == []
    assert client.get(f"/stations/{sid}", headers=h["ana"]).json()["status"] == "approved"
