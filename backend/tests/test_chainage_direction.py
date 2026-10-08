"""REQ-TAGTIN-DIR-001..007 (test-team observation, Oct 2026): From/Start is always the
lower chainage and To/End the higher one; direction (Nominal = lower->higher,
Reverse = higher->lower) is a separate attribute that never swaps the endpoints."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

from app.chainage import movement, movement_text, normalise_section
from test_register_crud import client, _make_admin_and_designer  # noqa: F401 (fixture)

STATION = {"centre_line_m": 262750, "adjacent_stations": [{"name": "ADJ", "side": "Lower km", "border_m": 258024}],
           "name": "T", "kavach_station_id": "1", "sip_drawing_number": "SIP-1",
           "kavach_version": "2", "sip_version": "1", "guideline_version": "0"}


def test_normalise_section_rules():
    assert normalise_section(1250, 1800, "Nominal") == (1250, 1800, False)
    assert normalise_section(1800, 1250, "Nominal") == (1250, 1800, True)       # DIR-001: reversed input normalised
    assert normalise_section(1800, 1250, "Reverse") == (1250, 1800, True)       # DIR-004: direction never swaps
    for a, b, d, msg in [(1250, 1250, None, "equal"), (None, 1800, None, "required"),
                         ("abc", 1800, None, "number"), (-5, 1800, None, "negative"),
                         (float("inf"), 1800, None, "finite"), (1, 2, "Up", "direction must be")]:
        with pytest.raises(HTTPException) as e:
            normalise_section(a, b, d)
        assert e.value.status_code == 422 and msg in e.value.detail


def test_negative_allowed_by_setting(monkeypatch):
    monkeypatch.setenv("ALLOW_NEGATIVE_CHAINAGE", "true")
    assert normalise_section(-100, 50, None) == (-100, 50, False)


def test_movement_interpretation():
    assert movement(1250, 1800, "Nominal") == (1250, 1800)                     # DIR-002
    assert movement(1250, 1800, "Reverse") == (1800, 1250)                     # DIR-003
    assert movement(1250, 1800, "Both") == (None, None)
    assert movement_text(258024, 266417, "Reverse") == "266.417 -> 258.024"


def test_track_api_normalises_and_keeps_direction(client):
    _, des = _make_admin_and_designer(client)
    sid = client.post("/stations", json=STATION, headers=des).json()["id"]
    # UP line entered the way it runs: 266.417 -> 258.024
    r = client.post(f"/stations/{sid}/tracks", json={"name": "UP MAIN", "track_type": "Main", "start_m": 266417,
                                                      "end_m": 258024, "direction": "Reverse"}, headers=des)
    assert r.status_code == 200, r.text
    t = r.json()
    assert (t["start_m"], t["end_m"], t["direction"]) == (258024, 266417, "Reverse")
    # switching direction changes only the direction (acceptance criterion)
    r = client.put(f"/stations/{sid}/tracks/{t['id']}", json={**t, "direction": "Nominal"}, headers=des)
    assert (r.json()["start_m"], r.json()["end_m"], r.json()["direction"]) == (258024, 266417, "Nominal")
    # persistence: reload returns the same normalised endpoints and direction (DIR-006)
    got = client.get(f"/stations/{sid}/tracks", headers=des).json()[0]
    assert (got["start_m"], got["end_m"], got["direction"]) == (258024, 266417, "Nominal")
    # invalid input rejected (DIR-005)
    for bad in ({"start_m": 1000, "end_m": 1000}, {"start_m": -10, "end_m": 1000}, {"direction": "UP"}):
        body = {"name": "X", "track_type": "Loop", "start_m": 1000, "end_m": 2000, **bad}
        assert client.post(f"/stations/{sid}/tracks", json=body, headers=des).status_code == 422
    assert client.post(f"/stations/{sid}/tracks", json={"name": "X", "track_type": "Loop", "start_m": "abc",
                                                         "end_m": 2000}, headers=des).status_code == 422


def test_tin_api_normalises(client):
    _, des = _make_admin_and_designer(client)
    sid = client.post("/stations", json=STATION, headers=des).json()["id"]
    r = client.post(f"/stations/{sid}/tins", json={"tin_no": 218, "section_type": "Block", "start_m": 266417,
                                                    "end_m": 263145, "direction": "Reverse"}, headers=des)
    assert r.status_code == 200, r.text
    n = r.json()
    assert (n["start_m"], n["end_m"], n["direction"]) == (263145, 266417, "Reverse")
    r = client.put(f"/stations/{sid}/tins/{n['id']}", json={**n, "start_m": 266417, "end_m": 263145,
                                                             "direction": "Nominal"}, headers=des)
    assert (r.json()["start_m"], r.json()["end_m"], r.json()["direction"]) == (263145, 266417, "Nominal")
    assert client.post(f"/stations/{sid}/tins", json={"tin_no": 1, "section_type": "Station", "start_m": 5,
                                                       "end_m": 5}, headers=des).status_code == 422


def test_legacy_rows_normalised_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'legacy.db'}")
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    from app.database import Base, SessionLocal, engine
    from app import models
    from app.chainage import normalise_existing
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        st = models.StationORM(name="L", kavach_station_id="9")
        db.add(st); db.flush()
        db.add(models.TrackORM(station_id=st.id, name="UP", track_type="Main", start_m=266417, end_m=258024,
                               direction="Reverse"))
        db.add(models.TINORM(station_id=st.id, tin_no=218, section_type="Block", start_m=266417, end_m=263145))
        db.commit()
        assert normalise_existing(db) == 2
        tr = db.query(models.TrackORM).one()
        assert (tr.start_m, tr.end_m, tr.direction) == (258024, 266417, "Reverse")
        assert normalise_existing(db) == 0


def test_layout_report_shows_direction_and_movement(client):
    admin, des = _make_admin_and_designer(client)
    sid = client.post("/stations", json=STATION, headers=des).json()["id"]
    client.post(f"/stations/{sid}/tracks", json={"name": "UP MAIN", "track_type": "Main", "start_m": 266417,
                                                  "end_m": 258024, "direction": "Reverse"}, headers=des)
    r = client.get(f"/stations/{sid}/reports/layout", params={"format": "docx"}, headers=des)
    assert r.status_code == 200
    import io
    import docx
    text = "\n".join(c.text for t in docx.Document(io.BytesIO(r.content)).tables for row in t.rows for c in row.cells)
    assert "From / Start (m)" in text and "Movement (km)" in text and "266.417 -> 258.024" in text
