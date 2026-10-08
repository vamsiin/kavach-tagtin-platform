"""Tag placement: the 'linked element' (what the tag is placed for) must be an element of
the station, and should suit the tag type -- a turnout (T) tag goes with points."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain import Element, Station, Tag, Track, suitable_link
from app.rules.engine import check_topology
from test_register_crud import client, _make_admin_and_designer  # noqa: F401 (fixture)


def test_suitable_link_by_tag_type():
    assert suitable_link("T", "Points / Turnout") and not suitable_link("T", "Mainline Starter")
    assert suitable_link("S", "Shunt Signal") and suitable_link("S", "BSLB Board") and not suitable_link("S", "LC Gate")
    assert suitable_link("G", "LC Gate") and suitable_link("L", "Advanced Starter Signal")
    assert suitable_link("D", "Stop Board/Buffer Stop") and suitable_link("A", "anything")


def test_topology_flags_unsuitable_and_missing_turnout_links():
    dn = Track(id=1, name="DN MAIN", track_type="Main", start_m=0, end_m=10000)
    els = [Element(id=1, element_ref="P19", element_type="Points / Turnout", location_m=5000, track_id=1, to_track_id=1),
           Element(id=2, element_ref="S3", element_type="Mainline Starter", location_m=5200, track_id=1)]
    tags = [Tag(id=1, tag_ref="R-836", tag_type="T", location_m=4990, track_id=1, linked_element_id=1),
            Tag(id=2, tag_ref="R-840", tag_type="T", location_m=5100, track_id=1, linked_element_id=2),
            Tag(id=3, tag_ref="R-842", tag_type="T", location_m=5150, track_id=1)]
    res = {r.subject_ref: r for r in check_topology(Station(id=1, name="S", kavach_station_id="1", tracks=[dn]),
                                                     els, tags, []) if r.title == "Tag linked to a suitable element"}
    assert res["R-836"].status == "PASS"
    assert res["R-840"].status == "FAIL" and "points / turnout" in res["R-840"].message
    assert res["R-842"].status == "FAIL" and "link it to its points" in res["R-842"].message


def test_link_must_be_an_element_of_the_station(client):
    _, des = _make_admin_and_designer(client)
    station = {"name": "T", "kavach_station_id": "1", "centre_line_m": 0,
               "adjacent_stations": [{"name": "ADJ", "side": "Lower km", "border_m": 0}]}
    s1 = client.post("/stations", json=station, headers=des).json()["id"]
    s2 = client.post("/stations", json={**station, "kavach_station_id": "2"}, headers=des).json()["id"]
    other = client.post(f"/stations/{s2}/elements", json={"element_ref": "P1", "element_type": "Points / Turnout",
                                                           "location_m": 100}, headers=des).json()["id"]
    r = client.post(f"/stations/{s1}/tags", json={"tag_ref": "R-1", "tag_type": "T", "location_m": 100,
                                                   "linked_element_id": other}, headers=des)
    assert r.status_code == 422 and "not an element of this station" in r.json()["detail"]
