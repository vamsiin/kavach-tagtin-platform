"""Station deviations: a failing automated check accepted, with a reason and SIP / LC
reference, as fitting this station's interlocking plan (QFTL 26.09.2026)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.deviations import apply
from app.rules.engine import CheckResult, VerificationReport


class D:
    def __init__(self, id, clause, subject_ref, reason="per SIP", reference=None):
        self.id, self.clause, self.subject_ref, self.reason, self.reference = id, clause, subject_ref, reason, reference
        self.created_by, self.created_at = "design", "2026-09-26T10:00:00"


def test_apply_turns_fail_into_deviation():
    rep = VerificationReport([CheckResult("H2.22", "Block TIN", "FAIL", "TIN 218 ends at 263145", "218"),
                              CheckResult("H2.22", "Block TIN", "FAIL", "TIN 221 ...", "221"),
                              CheckResult("H2.5", "Tag spacing", "PASS", "ok", "R-1")])
    unused = apply(rep, [D(1, "H2.22", "218", "UP block TIN ends at R-790 as per SIP", "IPU.1100A"),
                         D(2, "H2.5", "R-1")])
    assert [r.status for r in rep.results] == ["DEVIATION", "FAIL", "PASS"]
    assert "accepted as a station deviation: UP block TIN ends at R-790 as per SIP [IPU.1100A]" in rep.results[0].message
    assert rep.fail_count == 1 and rep.summary()["deviation_count"] == 1
    assert [d.id for d in unused] == [2]                    # H2.5 R-1 passes -- deviation no longer needed


from test_register_crud import client, _make_admin_designer_checker  # noqa: E402,F401  (fixture)

STATION = {"centre_line_m": 0, "adjacent_stations": [{"name": "ADJ", "side": "Nominal", "border_m": 0}],
           "name": "T", "kavach_station_id": "1", "sip_drawing_number": "SIP-1",
           "kavach_version": "2", "sip_version": "1", "guideline_version": "0"}


def test_deviation_api(client):
    admin, des, chk = _make_admin_designer_checker(client)
    sid = client.post("/stations", json=STATION, headers=des).json()["id"]
    # one failing check: tag number outside 1-1023 (H2.23)
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-2000", "tag_type": "N", "location_m": 100,
                                               "tag_number": 2000}, headers=des)
    def status_of():
        rs = client.get(f"/stations/{sid}/verify", headers=des).json()
        return {r["status"] for r in rs["results"] if r["clause"] == "H2.23" and r["subject_ref"] == "R-2000"}, rs
    assert status_of()[0] == {"FAIL"}

    body = {"clause": "H2.23", "subject_ref": "R-2000", "reason": "Number fixed by the SIP", "reference": "SIP-1 rev 2"}
    assert client.post(f"/stations/{sid}/deviations", json=body, headers=chk).status_code == 403
    assert client.post(f"/stations/{sid}/deviations", json={**body, "subject_ref": "R-9"},
                       headers=des).status_code == 422                       # nothing failing there
    r = client.post(f"/stations/{sid}/deviations", json=body, headers=des)
    assert r.status_code == 200 and r.json()["created_by"] == "dana"
    assert client.post(f"/stations/{sid}/deviations", json=body, headers=des).status_code == 409

    st, rep = status_of()
    assert st == {"DEVIATION"} and rep["summary"]["deviation_count"] == 1
    assert rep["summary"]["fail_count"] == sum(1 for x in rep["results"] if x["status"] == "FAIL")
    devs = client.get(f"/stations/{sid}/deviations", headers=chk).json()
    assert devs[0]["in_use"] is True and devs[0]["reference"] == "SIP-1 rev 2"
    changes = client.get(f"/stations/{sid}/changes", headers=admin).json()
    assert changes[0]["field"] == "deviation" and changes[0]["after"] == "H2.23 R-2000"

    # the layout changes so the check passes -> the deviation shows as no longer needed
    tag = client.get(f"/stations/{sid}/tags", headers=des).json()[0]
    client.put(f"/stations/{sid}/tags/{tag['id']}", json={**tag, "tag_number": 1}, headers=des)
    assert client.get(f"/stations/{sid}/deviations", headers=des).json()[0]["in_use"] is False
    assert client.get(f"/stations/{sid}/verify", headers=des).json()["deviations_unused"] == ["H2.23 R-2000"]

    dev_id = devs[0]["id"]
    assert client.delete(f"/stations/{sid}/deviations/{dev_id}", headers=des).status_code == 204
    assert client.get(f"/stations/{sid}/deviations", headers=des).json() == []


def test_baseline_index_keeps_same_name_on_two_lines():
    from app.routers.management import _index
    snap = {"tins": [{"tin_no": 169, "track": "DN MAIN"}, {"tin_no": 169, "track": "COMMON LOOP"},
                     {"tin_no": 170, "track": "DN MAIN"}],
            "elements": [{"element_ref": "SB", "track": "UP MAIN"}, {"element_ref": "SB", "track": "UP LOOP"}],
            "deviations": [{"clause": "H2.22", "subject_ref": "218"}]}
    keys = set(_index(snap))
    assert {"TIN 169 on DN MAIN", "TIN 169 on COMMON LOOP", "TIN 170", "element SB on UP MAIN",
            "element SB on UP LOOP", "deviation H2.22 218"} <= keys
