"""
End-to-end proof of the checker-assignment + email-notification workflow, running
through the real FastAPI app over TestClient (same pattern as test_register_crud.py)
-- this is the feature set from the "designer assigns checker, emails on every
decision, full audit history" request, and it's important enough to prove all the
way through HTTP, not just at the workflow-engine unit-test level.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

os.environ.setdefault("JWT_SECRET", "test-secret-for-assignment-tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("SMTP_HOST", raising=False)  # force console-fallback by default

    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def _bootstrap_full_cast(client):
    """admin, designer (with email), checker (with email), approver (with email)."""
    client.post("/auth/register", json={
        "username": "admin", "full_name": "Admin", "role": "admin", "password": "adminpass123",
    })
    admin_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'admin', 'password': 'adminpass123'}).json()['access_token']}"}

    users = {}
    for username, role in [("dana", "designer"), ("cara", "checker"), ("ana", "approver")]:
        client.post("/auth/users", json={
            "username": username, "full_name": username.title(), "role": role,
            "email": f"{username}@example.com", "password": f"{username}pass123",
        }, headers=admin_headers)
        token = client.post("/auth/login", json={"username": username, "password": f"{username}pass123"}).json()["access_token"]
        users[username] = {"Authorization": f"Bearer {token}"}

    return admin_headers, users["dana"], users["cara"], users["ana"]


def _make_compliant_station(client, designer_headers) -> int:
    """Creates a station with complete StationInfo (H2.1/H2.2 pass) and zero
    Elements/Tags/TINs (so there's nothing else for the Annexure-H checks to flag)
    -- i.e. a station that should cleanly pass verification with fail_count == 0,
    so tests can exercise the CHECK workflow action without being blocked by
    unrelated, entirely legitimate compliance failures. Real compliance-content
    testing belongs in test_rules.py; these tests are about the workflow/assignment
    machinery layered on top of verification, not verification itself."""
    r = client.post("/stations", json={"centre_line_m": 0, "adjacent_stations": [{"name": "ADJ", "side": "Nominal", "border_m": 0}],
        "name": "ALER", "kavach_station_id": "103", "sip_drawing_number": "IPU.1100A",
        "kavach_version": "2", "sip_version": "1", "guideline_version": "0",
    }, headers=designer_headers)
    return r.json()["id"]


def test_submit_requires_and_records_checker_assignment(client):
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)

    # missing assignment -> 422 (Pydantic validation, field is required)
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    r = client.post(f"/stations/{sid}/submit", json={"comment": ""}, headers=designer_headers)
    assert r.status_code == 422

    # assigning a non-existent user -> 404
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    r = client.post(f"/stations/{sid}/submit",
                     json={"assigned_checker_username": "nobody", "comment": ""},
                     headers=designer_headers)
    assert r.status_code == 404

    # assigning the designer themselves (wrong role) -> 409 from the workflow engine
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    r = client.post(f"/stations/{sid}/submit",
                     json={"assigned_checker_username": "dana", "comment": ""},
                     headers=designer_headers)
    assert r.status_code == 409
    assert "checker" in r.json()["detail"].lower()

    # correct assignment succeeds
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    r = client.post(f"/stations/{sid}/submit",
                     json={"assigned_checker_username": "cara", "comment": ""},
                     headers=designer_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"
    assert r.json()["assigned_checker"] == "cara"


def test_unassigned_checker_cannot_act_but_assigned_one_can(client):
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    client.post("/auth/users", json={
        "username": "chris", "full_name": "Chris", "role": "checker",
        "email": "chris@example.com", "password": "chrispass123",
    }, headers=admin_headers)
    other_checker_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'chris', 'password': 'chrispass123'}).json()['access_token']}"}

    sid = _make_compliant_station(client, designer_headers)
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": ""}, headers=designer_headers)

    r = client.post(f"/stations/{sid}/check", json={"comment": ""}, headers=other_checker_headers)
    assert r.status_code == 409
    assert "cara" in r.json()["detail"]

    r = client.post(f"/stations/{sid}/check", json={"comment": ""}, headers=checker_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "checked"


def test_email_notification_sent_on_checker_assignment(client):
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)

    with patch("app.routers.workflow.notify_checker_assigned") as mock_notify:
        mock_notify.return_value = type("R", (), {"sent": False, "mode": "console-fallback", "error": None})()
        client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
        r = client.post(f"/stations/{sid}/submit",
                         json={"assigned_checker_username": "cara", "comment": ""},
                         headers=designer_headers)
        assert r.status_code == 200
        mock_notify.assert_called_once()
        call_args = mock_notify.call_args[0]
        assert call_args[0] == "cara@example.com"  # checker's email
        assert call_args[1] == "ALER"               # station name


def test_full_cycle_emails_designer_and_checker_on_approval(client):
    """Full assign -> submit -> check(approve) -> approve cycle, asserting on the
    actual email recipients at each step -- this is the concrete proof that item 5
    (designer notified of checker's decision) and item 6 (designer AND checker
    notified of approver's decision) both work end to end."""
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)

    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": ""}, headers=designer_headers)

    with patch("app.routers.workflow.notify_designer_of_check_result") as mock_check_notify:
        mock_check_notify.return_value = type("R", (), {"sent": False, "mode": "console-fallback", "error": None})()
        r = client.post(f"/stations/{sid}/check", json={"comment": ""}, headers=checker_headers)
        assert r.status_code == 200
        mock_check_notify.assert_called_once()
        assert mock_check_notify.call_args[0][0] == "dana@example.com"  # designer's email
        assert mock_check_notify.call_args[1]["approved"] is True

    with patch("app.routers.workflow.notify_of_approval_result") as mock_approve_notify:
        mock_approve_notify.return_value = type("R", (), {"sent": False, "mode": "console-fallback", "error": None})()
        r = client.post(f"/stations/{sid}/approve", json={"comment": ""}, headers=approver_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "approved"
        mock_approve_notify.assert_called_once()
        recipients = set(mock_approve_notify.call_args[0][0])
        assert recipients == {"dana@example.com", "cara@example.com"}
        assert mock_approve_notify.call_args[1]["approved"] is True


def test_checker_reject_only_emails_designer_not_checker(client):
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": ""}, headers=designer_headers)

    with patch("app.routers.workflow.notify_designer_of_check_result") as mock_notify:
        mock_notify.return_value = type("R", (), {"sent": False, "mode": "console-fallback", "error": None})()
        r = client.post(f"/stations/{sid}/request-changes",
                         json={"comment": "fix H2.5 spacing"}, headers=checker_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "draft"
        mock_notify.assert_called_once()
        assert mock_notify.call_args[0][0] == "dana@example.com"
        assert mock_notify.call_args[1]["approved"] is False
        assert mock_notify.call_args[1]["comment"] == "fix H2.5 spacing"


def test_approver_reject_emails_both_designer_and_checker(client):
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": ""}, headers=designer_headers)
    client.post(f"/stations/{sid}/check", json={"comment": ""}, headers=checker_headers)

    with patch("app.routers.workflow.notify_of_approval_result") as mock_notify:
        mock_notify.return_value = type("R", (), {"sent": False, "mode": "console-fallback", "error": None})()
        r = client.post(f"/stations/{sid}/request-changes",
                         json={"comment": "needs another pass"}, headers=approver_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "draft"
        mock_notify.assert_called_once()
        recipients = set(mock_notify.call_args[0][0])
        assert recipients == {"dana@example.com", "cara@example.com"}
        assert mock_notify.call_args[1]["approved"] is False


def test_assignment_visible_in_workflow_history(client):
    """Item 7: full audit history with date/time. Confirms the assignment itself
    (target_username) shows up in the workflow event history, not just the bare
    status transitions."""
    admin_headers, designer_headers, checker_headers, approver_headers = _bootstrap_full_cast(client)
    sid = _make_compliant_station(client, designer_headers)
    client.post(f"/stations/{sid}/self-check", json={}, headers=designer_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": "please review"}, headers=designer_headers)

    r = client.get(f"/stations/{sid}/workflow", headers=designer_headers)
    history = r.json()["history"]
    assert len(history) == 2
    assert history[0]["action"] == "self_check"
    ev = history[1]
    assert ev["action"] == "submit"
    assert ev["actor_username"] == "dana"
    assert ev["target_username"] == "cara"
    assert ev["comment"] == "please review"
    assert ev["timestamp"]  # non-empty ISO timestamp present
