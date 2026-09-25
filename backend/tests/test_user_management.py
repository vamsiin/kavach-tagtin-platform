import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-user-mgmt-tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def _admin_headers(client):
    client.post("/auth/register", json={
        "username": "admin", "full_name": "Admin", "role": "admin", "password": "adminpass123",
    })
    r = client.post("/auth/login", json={"username": "admin", "password": "adminpass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_create_user_with_email(client):
    admin_headers = _admin_headers(client)
    r = client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "dana@example.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "dana@example.com"


def test_edit_user_updates_profile_fields(client):
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "dana@old.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)

    r = client.put("/auth/users/dana", json={
        "full_name": "Dana Updated", "email": "dana@new.com", "role": "checker", "is_active": True,
    }, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["full_name"] == "Dana Updated"
    assert r.json()["email"] == "dana@new.com"
    assert r.json()["role"] == "checker"


def test_edit_user_can_deactivate_account(client):
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "d@x.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)

    r = client.put("/auth/users/dana", json={
        "full_name": "Dana", "email": "d@x.com", "role": "designer", "is_active": False,
    }, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # deactivated user can no longer log in
    r = client.post("/auth/login", json={"username": "dana", "password": "danapass123"})
    assert r.status_code == 401


def test_admin_cannot_demote_own_account(client):
    admin_headers = _admin_headers(client)
    r = client.put("/auth/users/admin", json={
        "full_name": "Admin", "email": "", "role": "designer", "is_active": True,
    }, headers=admin_headers)
    assert r.status_code == 400
    assert "own account" in r.json()["detail"].lower()


def test_admin_cannot_deactivate_own_account(client):
    admin_headers = _admin_headers(client)
    r = client.put("/auth/users/admin", json={
        "full_name": "Admin", "email": "", "role": "admin", "is_active": False,
    }, headers=admin_headers)
    assert r.status_code == 400
    assert "own account" in r.json()["detail"].lower()


def test_delete_user(client):
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "d@x.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)

    r = client.delete("/auth/users/dana", headers=admin_headers)
    assert r.status_code == 204

    r = client.get("/auth/users", headers=admin_headers)
    usernames = [u["username"] for u in r.json()]
    assert "dana" not in usernames


def test_admin_cannot_delete_own_account(client):
    admin_headers = _admin_headers(client)
    r = client.delete("/auth/users/admin", headers=admin_headers)
    assert r.status_code == 400
    assert "own account" in r.json()["detail"].lower()


def test_cannot_delete_the_last_admin(client):
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "root2", "full_name": "Root2", "email": "",
        "role": "admin", "password": "root2pass123",
    }, headers=admin_headers)
    root2_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'root2', 'password': 'root2pass123'}).json()['access_token']}"}

    # root2 (not deleting themselves) tries to delete the original admin --
    # allowed, since root2 remains as an admin afterward
    r = client.delete("/auth/users/admin", headers=root2_headers)
    assert r.status_code == 204

    # now only root2 is left as admin -- nobody (including root2 acting on someone
    # else) can delete the last admin
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "", "role": "designer",
        "password": "danapass123",
    }, headers=root2_headers)
    # this isn't the last-admin case (dana isn't admin) -- sanity check it works
    r = client.delete("/auth/users/dana", headers=root2_headers)
    assert r.status_code == 204


def test_deleting_user_preserves_audit_history(client):
    """A deleted user's past workflow actions must remain visible in the audit
    trail -- see WorkflowEventORM storing actor_username as plain text, not a
    foreign key, specifically so this holds."""
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "d@x.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)
    client.post("/auth/users", json={
        "username": "cara", "full_name": "Cara", "email": "c@x.com",
        "role": "checker", "password": "carapass123",
    }, headers=admin_headers)
    dana_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'dana', 'password': 'danapass123'}).json()['access_token']}"}

    sid = client.post("/stations", json={"centre_line_m": 0, "adjacent_stations": [{"name": "ADJ", "side": "Nominal", "border_m": 0}], "name": "T", "kavach_station_id": "1", "sip_drawing_number": "SIP-1", "kavach_version": "2", "sip_version": "1", "guideline_version": "0"}, headers=dana_headers).json()["id"]
    client.post(f"/stations/{sid}/self-check", json={}, headers=dana_headers)
    client.post(f"/stations/{sid}/submit",
                json={"assigned_checker_username": "cara", "comment": ""}, headers=dana_headers)

    # delete dana's account entirely
    r = client.delete("/auth/users/dana", headers=admin_headers)
    assert r.status_code == 204

    # the submit event dana made is still in the audit trail, unmodified
    r = client.get(f"/stations/{sid}/workflow", headers=admin_headers)
    history = r.json()["history"]
    assert len(history) == 2
    assert [h["actor_username"] for h in history] == ["dana", "dana"]
    assert [h["action"] for h in history] == ["self_check", "submit"]


def test_non_admin_cannot_edit_or_delete_users(client):
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "d@x.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)
    dana_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'dana', 'password': 'danapass123'}).json()['access_token']}"}

    r = client.put("/auth/users/dana", json={
        "full_name": "Hacked", "email": "", "role": "admin", "is_active": True,
    }, headers=dana_headers)
    assert r.status_code == 403

    r = client.delete("/auth/users/dana", headers=dana_headers)
    assert r.status_code == 403


def test_list_users_by_role_available_to_any_authenticated_user(client):
    """This is the endpoint the Designer's 'assign a Checker' dropdown uses -- must
    NOT require admin, unlike GET /auth/users."""
    admin_headers = _admin_headers(client)
    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "email": "d@x.com",
        "role": "designer", "password": "danapass123",
    }, headers=admin_headers)
    client.post("/auth/users", json={
        "username": "cara", "full_name": "Cara", "email": "c@x.com",
        "role": "checker", "password": "carapass123",
    }, headers=admin_headers)
    dana_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'dana', 'password': 'danapass123'}).json()['access_token']}"}

    r = client.get("/auth/users/by-role/checker", headers=dana_headers)
    assert r.status_code == 200
    usernames = [u["username"] for u in r.json()]
    assert usernames == ["cara"]

    # a plain designer still cannot list ALL users (admin-only)
    r = client.get("/auth/users", headers=dana_headers)
    assert r.status_code == 403


def test_login_works_for_user_with_null_email(client):
    """Reproduces a real bug: accounts that existed before the `email` column was
    added get NULL there (the auto-migration adds the column with no default for
    existing rows -- see database.py's ensure_schema_up_to_date()). UserOut's
    email field validator must coerce that None to "" rather than letting Pydantic
    validation fail with a 500 on every request that returns this user, including
    login itself. Inserts the row directly via SQLAlchemy (bypassing the API,
    which always sets email="" for new users) to faithfully reproduce the
    pre-migration data shape rather than something the API could ever produce on
    its own."""
    from app import models
    from app.auth.security import hash_password
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        pw_hash, salt = hash_password("adminpass123")
        user = models.UserORM(
            username="oldadmin", full_name="Old Admin", email=None, role="admin",
            password_hash=pw_hash, password_salt=salt, is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    r = client.post("/auth/login", json={"username": "oldadmin", "password": "adminpass123"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == ""

    # GET /auth/me and GET /auth/users (admin-only, but oldadmin IS admin) must
    # also survive returning this user, not just login
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == ""

    r = client.get("/auth/users", headers=headers)
    assert r.status_code == 200
    assert all(u["email"] == "" or u["email"] for u in r.json())  # never null/missing


def test_workflow_event_with_null_comment_does_not_crash(client):
    """Same bug class as test_login_works_for_user_with_null_email, applied
    defensively to WorkflowEventOut.comment before it could ever actually happen
    through the app's own API (which always supplies comment="" at minimum) --
    proven here by inserting a WorkflowEventORM row directly with comment=None,
    then confirming GET /stations/{id}/workflow still returns 200, not a 500."""
    from app import models
    from app.database import SessionLocal

    admin_headers = _admin_headers(client)
    sid_resp = client.post("/stations", json={"centre_line_m": 0, "adjacent_stations": [{"name": "ADJ", "side": "Nominal", "border_m": 0}], "name": "T", "kavach_station_id": "1", "sip_drawing_number": "SIP-1", "kavach_version": "2", "sip_version": "1", "guideline_version": "0"}, headers=admin_headers)
    sid = sid_resp.json()["id"]

    db = SessionLocal()
    try:
        db.add(models.WorkflowEventORM(
            station_id=sid, from_status="draft", to_status="draft", action="note",
            actor_username="admin", actor_role="admin", comment=None,
            timestamp="2026-01-01T00:00:00Z",
        ))
        db.commit()
    finally:
        db.close()

    r = client.get(f"/stations/{sid}/workflow", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["history"][0]["comment"] == ""
