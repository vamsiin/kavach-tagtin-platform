"""
Integration tests exercising the real FastAPI app + SQLite via TestClient -- unlike
the other test files, these deliberately go through the actual HTTP layer (routing,
auth dependencies, SQLAlchemy session handling) rather than testing pure functions
in isolation, because the behavior under test (orphan-unlinking on delete, the
draft-only edit guard, role-gated station deletion) only exists at that wiring
layer. Requires fastapi/sqlalchemy installed (`pip install -r requirements.txt`) --
these are not part of the stdlib-only test set.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-crud-tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Fresh SQLite DB per test, via TestClient's lifespan context so startup
    (table creation) actually runs."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    # database.py reads DATABASE_URL at import time, so force a clean re-import
    # per test rather than reusing a cached module pointing at a stale engine.
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c:
        yield c


def _make_admin_and_designer(client):
    client.post("/auth/register", json={
        "username": "admin", "full_name": "Admin", "role": "admin", "password": "adminpass123",
    })
    r = client.post("/auth/login", json={"username": "admin", "password": "adminpass123"})
    admin_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    client.post("/auth/users", json={
        "username": "dana", "full_name": "Dana", "role": "designer", "password": "danapass123",
    }, headers=admin_headers)
    r = client.post("/auth/login", json={"username": "dana", "password": "danapass123"})
    designer_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    return admin_headers, designer_headers


def _make_admin_designer_checker(client):
    admin_headers, designer_headers = _make_admin_and_designer(client)
    client.post("/auth/users", json={
        "username": "cara", "full_name": "Cara", "role": "checker", "password": "carapass123",
    }, headers=admin_headers)
    r = client.post("/auth/login", json={"username": "cara", "password": "carapass123"})
    checker_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return admin_headers, designer_headers, checker_headers


def _submit(client, sid, headers, checker_username="cara"):
    return client.post(f"/stations/{sid}/submit",
                        json={"comment": "", "assigned_checker_username": checker_username},
                        headers=headers)


def test_update_element(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    eid = client.post(f"/stations/{sid}/elements",
                       json={"element_ref": "SIG-01", "element_type": "Main Home without Junction Route Indicator", "location_km": 120.2},
                       headers=headers).json()["id"]

    r = client.put(f"/stations/{sid}/elements/{eid}",
                    json={"element_ref": "SIG-01-RENAMED", "element_type": "Main Home without Junction Route Indicator", "location_km": 121.0},
                    headers=headers)
    assert r.status_code == 200
    assert r.json()["element_ref"] == "SIG-01-RENAMED"
    assert r.json()["location_km"] == 121.0


def test_delete_element_unlinks_orphaned_tags_rather_than_leaving_dangling_reference(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    eid = client.post(f"/stations/{sid}/elements",
                       json={"element_ref": "SIG-01", "element_type": "Main Home without Junction Route Indicator", "location_km": 120.2},
                       headers=headers).json()["id"]
    tid = client.post(f"/stations/{sid}/tags",
                       json={"tag_ref": "R-100", "tag_type": "S", "location_km": 120.2, "linked_element_id": eid},
                       headers=headers).json()["id"]

    r = client.delete(f"/stations/{sid}/elements/{eid}", headers=headers)
    assert r.status_code == 204

    tags = client.get(f"/stations/{sid}/tags", headers=headers).json()
    tag = next(t for t in tags if t["id"] == tid)
    assert tag["linked_element_id"] is None, \
        "tag should be unlinked, not left pointing at a deleted element"


def test_update_and_delete_tag(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    tid = client.post(f"/stations/{sid}/tags",
                       json={"tag_ref": "R-100", "tag_type": "N", "location_km": 100.0},
                       headers=headers).json()["id"]

    r = client.put(f"/stations/{sid}/tags/{tid}",
                    json={"tag_ref": "R-100-B", "tag_type": "S", "location_km": 100.5},
                    headers=headers)
    assert r.status_code == 200 and r.json()["tag_ref"] == "R-100-B"

    r = client.delete(f"/stations/{sid}/tags/{tid}", headers=headers)
    assert r.status_code == 204
    assert client.get(f"/stations/{sid}/tags", headers=headers).json() == []


def test_update_and_delete_tin(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    tinid = client.post(f"/stations/{sid}/tins",
                         json={"tin_no": 10, "section_type": "Station", "start_km": 1, "end_km": 2, "color": "Green"},
                         headers=headers).json()["id"]

    r = client.put(f"/stations/{sid}/tins/{tinid}",
                    json={"tin_no": 10, "section_type": "Station", "start_km": 1, "end_km": 3, "color": "Blue"},
                    headers=headers)
    assert r.status_code == 200 and r.json()["color"] == "Blue"

    r = client.delete(f"/stations/{sid}/tins/{tinid}", headers=headers)
    assert r.status_code == 204


def test_registers_cannot_be_edited_or_deleted_outside_draft(client):
    admin_headers, headers, checker_headers = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    eid = client.post(f"/stations/{sid}/elements",
                       json={"element_ref": "SIG-01", "element_type": "Stop Board/Buffer Stop", "location_km": 100.0},
                       headers=headers).json()["id"]
    r = _submit(client, sid, headers)
    assert r.status_code == 200

    r = client.put(f"/stations/{sid}/elements/{eid}",
                    json={"element_ref": "X", "element_type": "Stop Board/Buffer Stop", "location_km": 100.0},
                    headers=headers)
    assert r.status_code == 409

    r = client.delete(f"/stations/{sid}/elements/{eid}", headers=headers)
    assert r.status_code == 409


def test_creator_can_delete_own_draft_station(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]

    r = client.delete(f"/stations/{sid}", headers=headers)
    assert r.status_code == 204

    r = client.get(f"/stations/{sid}", headers=admin_headers)
    assert r.status_code == 404


def test_non_creator_non_admin_cannot_delete_station(client):
    admin_headers, headers = _make_admin_and_designer(client)
    client.post("/auth/users", json={
        "username": "other_dana", "full_name": "Other Dana", "role": "designer", "password": "otherpass123",
    }, headers=admin_headers)
    other_headers = {"Authorization": f"Bearer {client.post('/auth/login', json={'username': 'other_dana', 'password': 'otherpass123'}).json()['access_token']}"}

    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]

    r = client.delete(f"/stations/{sid}", headers=other_headers)
    assert r.status_code == 403

    # the actual creator still can, proving the 403 above was about identity, not
    # some blanket "designers can't delete" rule
    r = client.delete(f"/stations/{sid}", headers=headers)
    assert r.status_code == 204


def test_creator_cannot_delete_own_station_once_submitted(client):
    admin_headers, headers, checker_headers = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    r = _submit(client, sid, headers)
    assert r.status_code == 200

    r = client.delete(f"/stations/{sid}", headers=headers)
    assert r.status_code == 403
    assert "admin" in r.json()["detail"].lower()

    # admin can still delete it even though the creator no longer can
    r = client.delete(f"/stations/{sid}", headers=admin_headers)
    assert r.status_code == 204


def test_admin_can_delete_any_station_in_any_status(client):
    admin_headers, headers, checker_headers = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    r = _submit(client, sid, headers)
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"

    r = client.delete(f"/stations/{sid}", headers=admin_headers)
    assert r.status_code == 204

    r = client.get(f"/stations/{sid}", headers=admin_headers)
    assert r.status_code == 404


def test_station_records_its_creator(client):
    admin_headers, headers = _make_admin_and_designer(client)
    r = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers)
    assert r.json()["created_by"] == "dana"


def test_station_response_never_silently_drops_a_schema_field(client):
    """Regression guard for a bug class that happened twice (created_by, then
    assigned_checker: both silently absent from API responses after being added to
    the model, because _station_out() used to list each field by hand). Any field
    present on StationOut must appear as a key in the actual JSON response -- this
    fails loudly if a future field is added to the ORM/domain model but the API
    schema or response builder falls out of sync again."""
    from app import schemas
    admin_headers, headers = _make_admin_and_designer(client)
    r = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers)
    body = r.json()
    expected_fields = set(schemas.StationOut.model_fields.keys())
    assert expected_fields <= set(body.keys()), \
        f"StationOut fields missing from actual response: {expected_fields - set(body.keys())}"


def test_deleting_station_cascades_to_its_registers(client):
    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]
    client.post(f"/stations/{sid}/elements",
                json={"element_ref": "SIG-01", "element_type": "Stop Board/Buffer Stop", "location_km": 100.0},
                headers=headers)
    client.post(f"/stations/{sid}/tags",
                json={"tag_ref": "R-1", "tag_type": "N", "location_km": 100.0}, headers=headers)

    client.delete(f"/stations/{sid}", headers=admin_headers)

    # The station itself is gone, so its sub-resource routes 404 via the station
    # lookup rather than returning an orphaned list.
    r = client.get(f"/stations/{sid}/elements", headers=admin_headers)
    assert r.status_code == 404


def test_tag_with_null_boolean_fields_does_not_crash(client):
    """Same bug class as test_login_works_for_user_with_null_email and
    test_workflow_event_with_null_comment_does_not_crash: is_border_tag was added
    to an already-existing table via the auto-migration, which leaves pre-existing
    rows NULL rather than False. Confirms GET /stations/{id}/tags survives a row
    with is_border_tag (and, incidentally, is_duplicate) both NULL, rather than
    throwing a 500.

    IMPORTANT: must insert via raw SQL, NOT `models.TagORM(is_border_tag=None)` --
    that column has default=False at the SQLAlchemy level, which silently
    substitutes False for an explicitly-None constructor argument at flush time
    (confirmed by direct inspection: it does NOT store NULL). That's a real
    behavioral difference from `email`/`comment` (no `default=` on those columns),
    and using the ORM constructor here would test the wrong thing entirely --
    it would pass even with the bug reintroduced, silently proving nothing. Raw
    SQL bypasses the ORM-level default and genuinely reproduces what an
    ALTER-TABLE-added column on pre-existing rows actually looks like. This also
    incidentally omits is_duplicate from the INSERT, which surfaced that field has
    the identical vulnerability shape too, even though it wasn't originally
    suspected -- now covered by the same validator, see schemas.py."""
    from sqlalchemy import text
    from app.database import SessionLocal

    admin_headers, headers = _make_admin_and_designer(client)
    sid = client.post("/stations", json={"name": "T", "kavach_station_id": "1"}, headers=headers).json()["id"]

    db = SessionLocal()
    try:
        db.execute(text(
            "INSERT INTO tags (station_id, tag_ref, tag_type, location_km) "
            "VALUES (:sid, 'R-1', 'N', 100.0)"
        ), {"sid": sid})
        db.commit()
    finally:
        db.close()

    r = client.get(f"/stations/{sid}/tags", headers=headers)
    assert r.status_code == 200
    assert r.json()[0]["is_border_tag"] is False
    assert r.json()[0]["is_duplicate"] is False
