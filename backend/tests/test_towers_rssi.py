"""Input 5 -- tower locations and the tower RSSI survey: the towers register, CSV
import (long and one-column-per-tower), the BR-005 border coverage check
(-70 dBm on both stations' sides) and towers on the drawing."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from test_register_crud import client, _make_admin_designer_checker  # noqa: F401 (fixture)
from test_register_import import _up


def _station(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json={
        "name": "Aler", "kavach_station_id": "103", "centre_line_m": 262750,
        "adjacent_stations": [{"name": "Wangapalli-Aler IB", "side": "Lower km"}]}, headers=des).json()["id"]
    up = client.post(f"/stations/{sid}/tracks", json={"name": "UP MAIN", "track_type": "Main", "start_m": 258024,
                     "end_m": 266417}, headers=des).json()["id"]
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-774", "tag_number": 774, "tag_type": "S",
                "location_m": 258024, "direction": "Reverse", "track_id": up, "is_border_tag": True}, headers=des)
    return sid, des, up


def _br005(client, sid, des):
    rep = client.get(f"/stations/{sid}/verify", headers=des).json()
    return [c for c in rep["results"] if c["clause"] == "BR-005" and "RSSI" in c["title"]]


def test_towers_register_crud(client):
    sid, des, up = _station(client)
    r = client.post(f"/stations/{sid}/towers", json={"tower_ref": "ALR-T1", "location_m": 262760, "owner": "Aler",
                    "track_id": up, "height_m": 40}, headers=des)
    assert r.status_code == 201 and r.json()["owner"] is None          # own station stored as blank
    tid = r.json()["id"]
    assert client.post(f"/stations/{sid}/towers", json={"tower_ref": "ALR-T1", "location_m": 1},
                       headers=des).status_code == 422                  # unique per station
    assert client.post(f"/stations/{sid}/towers", json={"tower_ref": "X", "location_m": 1, "height_m": -3},
                       headers=des).status_code == 422
    r = client.put(f"/stations/{sid}/towers/{tid}", json={"tower_ref": "ALR-T1A", "location_m": 262770},
                   headers=des)
    assert r.json()["tower_ref"] == "ALR-T1A"
    assert [t["tower_ref"] for t in client.get(f"/stations/{sid}/towers", headers=des).json()] == ["ALR-T1A"]
    assert client.delete(f"/stations/{sid}/towers/{tid}", headers=des).status_code == 204


def test_import_towers_and_rssi_then_border_check(client):
    sid, des, up = _station(client)
    assert _br005(client, sid, des)[0]["status"] == "WARN"              # no survey loaded yet
    for kind in ("towers", "rssi"):
        t = client.get(f"/stations/{sid}/registers/{kind}/template", headers=des)
        assert t.status_code == 200 and "Tower" in t.text
    towers = ("#,Tower,Location(m),Station,Line\n"
              "1,ALR-T1,262760,Aler,UP MAIN\n"
              "2,WP-T1,256900,Wangapalli-Aler IB,UP MAIN\n")
    r = _up(client, sid, "towers", towers, des, apply=True).json()
    assert r["applied"] and r["counts"]["add"] == 2
    rssi = ("#,Tower,Location(m),Line,Dir,RSSI(dBm)\n"
            "1,ALR-T1,258024,UP MAIN,Reverse (UP),-66\n"
            "2,WP-T1,258024,UP MAIN,Reverse (UP),-58\n"
            "3,ALR-T1,258040,UP MAIN,Reverse (UP),-64 dBm\n")
    r = _up(client, sid, "rssi", rssi, des, apply=True).json()
    assert r["applied"] and r["counts"]["add"] == 3
    res = _br005(client, sid, des)
    assert res[0]["status"] == "PASS" and "-64 dBm" in res[0]["message"] and "-58 dBm" in res[0]["message"]

    # a weaker survey replaces the old readings of those towers
    weak = "Tower,Location(m),RSSI(dBm)\nALR-T1,258030,-75\n"
    r = _up(client, sid, "rssi", weak, des, apply=True, update=True).json()
    assert any("Replaces the 2 reading(s)" in w for x in r["rows"] for w in x["warnings"])
    res = _br005(client, sid, des)
    assert res[0]["status"] == "FAIL" and "below -70 dBm" in res[0]["message"]

    s = client.get(f"/stations/{sid}/rssi/summary", headers=des).json()
    assert {t["tower_ref"]: t["readings"] for t in s["towers"]} == {"ALR-T1": 1, "WP-T1": 1}
    assert s["border_coverage"][0]["status"] == "FAIL"
    assert client.delete(f"/stations/{sid}/rssi", params={"tower_ref": "WP-T1"}, headers=des).status_code == 204
    res = _br005(client, sid, des)
    assert res[0]["status"] == "FAIL" and "no reading within 50 m from: adjacent station tower" in res[0]["message"]


def test_rssi_one_column_per_tower_and_bad_values(client):
    sid, des, up = _station(client)
    _up(client, sid, "towers", "Tower,Location(m),Station\nALR-T1,262760,Aler\nWP-T1,256900,Wangapalli-Aler IB\n",
        des, apply=True)
    wide = ("Location(m),Line,RSSI ALR-T1 (dBm),RSSI WP-T1 (dBm)\n"
            "258024,UP MAIN,-61,-55\n"
            "258050,UP MAIN,-63,-\n")
    r = _up(client, sid, "rssi", wide, des).json()
    assert r["counts"]["add"] == 3 and r["counts"]["error"] == 0
    bad = "Tower,Location(m),RSSI(dBm)\nZZ-9,258024,-60\nALR-T1,258024,60\n"
    r = _up(client, sid, "rssi", bad, des).json()
    assert any("not in the towers register" in w for w in r["rows"][0]["warnings"])
    assert any("outside -140 to 0" in e for e in r["rows"][1]["errors"])
    assert not r["can_apply"]


def test_towers_on_the_drawing(client):
    sid, des, up = _station(client)
    _up(client, sid, "towers", "Tower,Location(m),Station\nALR-T1,262760,Aler\nWP-T1,256900,Wangapalli-Aler IB\n",
        des, apply=True)
    svg = client.get(f"/stations/{sid}/drawing", headers=des).text
    assert "ALR-T1" in svg and "WP-T1" in svg and "Wangapalli-Aler IB" in svg and "TOWERS" in svg
    docs = client.get("/documents/types", headers=des)
    if docs.status_code == 200:
        assert "RSSI_REPORT" in str(docs.json())
