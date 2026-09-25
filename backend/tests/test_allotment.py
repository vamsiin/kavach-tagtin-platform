"""
RFID Tag / TIN allotment charts (BRD BR-001, FR-004): range parsing, the BR-001
check, loading / superseding charts, spreadsheet import and a station's usage.
Rows are the Aler rows of the Secunderabad Division chart
(RDSO-SIG0MISC(GEN)/1/2021 dated 16.08.2024).
"""
import io
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.allotment.ranges import RangeError, compact, id_key, parse_ranges
from app.domain import AllotmentEntry, Station, StationAllotment, Tag, TIN
from app.rules.engine import check_br001_allotment

os.environ.setdefault("JWT_SECRET", "test-secret-for-allotment-tests")

ROWS = [
    {"s_no": "25", "name": "Wangapalli-Aler IB", "division_code": "00", "station_code": "104", "station_id": "00104",
     "tin_ranges": "224, 223, 222, 221", "tag_ranges": "679-774", "tag_total": 96},
    {"s_no": "26", "name": "Aler", "division_code": "00", "station_code": "103", "station_id": "00103",
     "tin_ranges": "169-192", "tag_ranges": "775-902", "tag_total": 128},
    {"s_no": "27", "name": "Aler-Pembarti IB", "division_code": "00", "station_code": "102", "station_id": "00102",
     "tin_ranges": "220, 219, 218, 217", "tag_ranges": "903-976", "tag_total": 74},
    {"s_no": "28", "name": "Pembarti", "division_code": "00", "station_code": "101", "station_id": "00101",
     "tin_ranges": "193-208, 1-8", "tag_ranges": "977-1023, 1-70", "tag_total": 128},
]
CHART = {"title": "Secunderabad Division RFID Tag / TIN Allocation Chart", "division": "Secunderabad",
         "reference_no": "RDSO-SIG0MISC(GEN)/1/2021", "issued_on": "2024-08-16",
         "issued_by": "RDSO, Executive Director/Telecom-II", "rows": ROWS}


# ---------------------------------------------------------------------------
# Ranges
# ---------------------------------------------------------------------------
def test_parse_ranges():
    assert parse_ranges("775-902", 1023) == list(range(775, 903))
    assert len(parse_ranges("977-1023, 1-70", 1023)) == 117          # wraps past 1023
    assert parse_ranges("220, 219, 218, 217", 255) == [217, 218, 219, 220]
    assert parse_ranges("190 – 460; 731-824", 1023)[:2] == [190, 191]   # en dash, semicolon
    assert parse_ranges(None, 255) == [] and parse_ranges("  ", 255) == []
    for bad in ("12-5", "1-1024", "abc", "0-3"):
        with pytest.raises(RangeError):
            parse_ranges(bad, 1023)
    assert compact([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert id_key("00103") == id_key("103") == 103 and id_key("") is None


# ---------------------------------------------------------------------------
# BR-001 rule
# ---------------------------------------------------------------------------
def _entry(name, tags, tins):
    return AllotmentEntry(name=name, tags=frozenset(parse_ranges(tags, 1023)), tins=frozenset(parse_ranges(tins, 255)),
                          tag_text=tags, tin_text=tins)


def test_br001_rule():
    st = Station(id=1, name="Aler", kavach_station_id="103")
    assert check_br001_allotment(st, [], [])[0].status == "WARN"      # no chart loaded
    st.allotment = StationAllotment(chart_ref="SC chart")
    r = check_br001_allotment(st, [], [])
    assert r[0].status == "FAIL" and "not in the current allotment chart" in r[0].message

    st.allotment = StationAllotment(
        chart_ref="SC chart", own=_entry("Aler", "775-902", "169-192"),
        adjacent=[("Aler-WP-IB", _entry("Wangapalli-Aler IB", "679-774", "221-224"))],
        unmatched_adjacent=["Aler-PBP-IB"])
    tags = [Tag(id=1, tag_ref="R-775", tag_type="S", location_m=1, tag_number=775),
            Tag(id=2, tag_ref="R-774", tag_type="N", location_m=1, tag_number=774),
            Tag(id=3, tag_ref="R-905", tag_type="N", location_m=1, tag_number=905),
            Tag(id=4, tag_ref="R-x", tag_type="N", location_m=1)]
    tins = [TIN(tin_no=169, section_type="Station", start_m=0, end_m=1),
            TIN(tin_no=222, section_type="Block", start_m=0, end_m=1),
            TIN(tin_no=1, section_type="Block", start_m=0, end_m=1)]
    res = {x.subject_ref: x for x in check_br001_allotment(st, tags, tins)}
    assert res["Aler-PBP-IB"].status == "WARN"
    assert res["R-775"].status == "PASS" and "allotted to Aler" in res["R-775"].message
    assert res["R-774"].status == "PASS" and "Wangapalli-Aler IB (adjacent)" in res["R-774"].message
    assert res["R-905"].status == "FAIL" and "775-902" in res["R-905"].message
    assert "R-x" not in res
    assert res["169"].status == "PASS" and res["222"].status == "PASS" and res["1"].status == "FAIL"


# ---------------------------------------------------------------------------
# API
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
    for u, role in (("dana", "designer"), ("cora", "config_manager")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, "dana": login("dana", "pass12345"), "cora": login("cora", "pass12345")}


def _aler(client, h):
    return client.post("/stations", json={
        "name": "Aler", "kavach_station_id": "103", "sip_drawing_number": "IBU.1100A", "kavach_version": "2",
        "sip_version": "0", "guideline_version": "3", "centre_line_m": 262750, "adjacent_stations": [
            {"name": "Aler-WP-IB", "kavach_station_id": "104", "side": "Lower km",
             "borders": [{"line_label": "DN line", "border_m": 259740, "border_tag_ref": "S1D"}]},
            {"name": "Aler-PBP-IB", "kavach_station_id": "102", "side": "Higher km",
             "borders": [{"line_label": "DN line", "border_m": 265278, "border_tag_ref": "S7D"}]}]},
        headers=h["dana"]).json()["id"]


def test_load_chart_permissions_and_validation(client, h):
    assert client.post("/allotment-charts", json=CHART, headers=h["dana"]).status_code == 403
    bad = {**CHART, "rows": [{**ROWS[1], "tag_ranges": "902-775"}, {**ROWS[0], "station_id": "103"}]}
    r = client.post("/allotment-charts", json=bad, headers=h["cora"])
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("runs backwards" in e for e in errs) and any("also used by Aler" in e for e in errs)

    r = client.post("/allotment-charts", json=CHART, headers=h["cora"])
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["is_current"] and c["row_count"] == 4 and c["created_by"] == "cora"
    pem = next(x for x in c["rows"] if x["name"] == "Pembarti")
    assert pem["tag_count"] == 117 and "printed as 128" in pem["problems"][0]   # as on the issued chart
    assert any("Pembarti" in w for w in c["warnings"])
    assert not any("both" in w for w in c["warnings"])      # no overlaps between these neighbours
    clash = client.post("/allotment-charts", json={**CHART, "division": "X", "rows": [
        ROWS[0], {**ROWS[1], "tag_ranges": "770-902", "tag_total": 133}, ROWS[2]]}, headers=h["cora"]).json()
    assert any("770-774 are in both Wangapalli-Aler IB and Aler" in w for w in clash["warnings"])
    assert [x["id"] for x in client.get("/allotment-charts", headers=h["dana"]).json()] == [clash["id"], c["id"]]


def test_supersede_and_roll_back(client, h):
    first = client.post("/allotment-charts", json=CHART, headers=h["cora"]).json()
    rev = client.post("/allotment-charts", json={**CHART, "issued_on": "2025-01-10", "rows": ROWS[:2]},
                      headers=h["cora"]).json()
    other = client.post("/allotment-charts", json={**CHART, "division": "Hyderabad", "rows": ROWS[3:]},
                        headers=h["cora"]).json()
    charts = {c["id"]: c for c in client.get("/allotment-charts", headers=h["dana"]).json()}
    assert not charts[first["id"]]["is_current"] and charts[first["id"]]["superseded_by_id"] == rev["id"]
    assert charts[rev["id"]]["is_current"] and charts[other["id"]]["is_current"]   # other division untouched
    r = client.post(f"/allotment-charts/{first['id']}/make-current", headers=h["cora"])
    assert r.status_code == 200 and r.json()["is_current"]
    assert not client.get(f"/allotment-charts/{rev['id']}", headers=h["dana"]).json()["is_current"]


def test_station_allotment_usage_and_verification(client, h):
    sid = _aler(client, h)
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    assert [x["status"] for x in v["results"] if x["clause"] == "BR-001"] == ["WARN"]   # no chart yet
    assert client.get(f"/stations/{sid}/allotment", headers=h["dana"]).json()["chart"] is None

    client.post("/allotment-charts", json=CHART, headers=h["cora"])
    for ref, n in (("R-775", 775), ("R-777", 777), ("R-774", 774), ("R-1000", 1000)):
        client.post(f"/stations/{sid}/tags", json={"tag_ref": ref, "tag_type": "N", "location_m": 262000,
                                                   "tag_number": n}, headers=h["dana"])
    client.post(f"/stations/{sid}/tins", json={"tin_no": 169, "section_type": "Station", "start_m": 1,
                                               "end_m": 2}, headers=h["dana"])
    a = client.get(f"/stations/{sid}/allotment", headers=h["dana"]).json()
    assert a["own"]["name"] == "Aler" and a["chart"]["reference_no"] == "RDSO-SIG0MISC(GEN)/1/2021"
    assert [(x["adjacent_name"], x["row"]["name"]) for x in a["adjacent"]] == \
        [("Aler-WP-IB", "Wangapalli-Aler IB"), ("Aler-PBP-IB", "Aler-Pembarti IB")]
    t = a["tags"]
    assert t["allotted"] == 128 and t["used_in_own"] == 2 and t["free"] == 126
    assert t["next_free_odd"] == 779 and t["next_free_even"] == 776
    assert t["free_ranges"].startswith("776, 778-902")
    assert [(u["number"], u["owner"]) for u in t["used"]] == \
        [(774, "Wangapalli-Aler IB"), (775, "own"), (777, "own"), (1000, None)]
    assert [u["ref"] for u in t["outside"]] == ["R-1000"]
    assert a["tins"]["used_in_own"] == 1 and a["tins"]["next_free_odd"] == 171

    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    br = {x["subject_ref"]: x["status"] for x in v["results"] if x["clause"] == "BR-001"}
    assert br == {"R-775": "PASS", "R-777": "PASS", "R-774": "PASS", "R-1000": "FAIL", "169": "PASS"}
    assert "BR-001" in v["summary"]["clauses_failing"]


def test_station_not_in_chart_fails(client, h):
    client.post("/allotment-charts", json=CHART, headers=h["cora"])
    sid = client.post("/stations", json={"name": "Nowhere", "kavach_station_id": "555"},
                      headers=h["dana"]).json()["id"]
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    br = [x for x in v["results"] if x["clause"] == "BR-001"]
    assert len(br) == 1 and br[0]["status"] == "FAIL"
    assert client.get(f"/stations/{sid}/allotment", headers=h["dana"]).json()["own"] is None


def test_import_spreadsheet_and_attach_file(client, h):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Secunderabad Division RFID Tag / TIN Allocation Chart"])
    ws.append(["S.No.", "Station / Block Section", "Division Code", "Station Code", "Station ID",
               "TIN Range", "TIN Allotted", "RFID Tag Numbers Range", "Total"])
    for r in ROWS:
        ws.append([r["s_no"], r["name"], r["division_code"], r["station_code"], r["station_id"],
                   r["tin_ranges"], "", r["tag_ranges"], r["tag_total"]])
    buf = io.BytesIO()
    wb.save(buf)
    files = {"file": ("chart.xlsx", buf.getvalue(),
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    assert client.post("/allotment-charts/parse", files=files, headers=h["dana"]).status_code == 403
    r = client.post("/allotment-charts/parse", files=files, headers=h["cora"])
    assert r.status_code == 200, r.text
    p = r.json()
    assert [x["name"] for x in p["rows"]] == [x["name"] for x in ROWS] and not p["errors"]
    assert p["rows"][1]["station_id"] == "00103" and p["rows"][1]["tag_total"] == 128
    assert any("Pembarti" in w for w in p["warnings"])

    csv_bytes = "S.No,Station / Block Section,Station ID,TIN Range,RFID Tag Range,Total\n26,Aler,00103,169-192,775-902,128\n"
    r = client.post("/allotment-charts/parse", files={"file": ("c.csv", csv_bytes.encode(), "text/csv")},
                    headers=h["cora"])
    assert r.json()["rows"][0]["tag_count"] == 128
    assert client.post("/allotment-charts/parse", files={"file": ("c.pdf", b"%PDF", "application/pdf")},
                       headers=h["cora"]).status_code == 422

    c = client.post("/allotment-charts", json={**CHART, "rows": [
        {k: v for k, v in x.items() if k not in ("id", "tag_count", "tin_count", "problems")} for x in p["rows"]]},
        headers=h["cora"]).json()
    r = client.post(f"/allotment-charts/{c['id']}/file", files={"file": ("letter.pdf", b"%PDF-1.7 chart", "application/pdf")},
                    headers=h["cora"])
    assert r.status_code == 200 and r.json()["source_filename"] == "letter.pdf" and r.json()["source_sha256"]
    d = client.get(f"/allotment-charts/{c['id']}/file", headers=h["dana"])
    assert d.status_code == 200 and d.content == b"%PDF-1.7 chart"
