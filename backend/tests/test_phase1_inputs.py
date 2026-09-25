"""
Phase 1: FR-001 input documents, FR-002 DXF import (parse -> review -> commit),
FR-011 traceability. Uses a REAL DXF generated with ezdxf (TEXT + INSERT/ATTRIB
blocks), not a mock, so the importer is exercised end-to-end through HTTP.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET", "test-secret-for-phase1-tests")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    from app.main import app as fastapi_app
    with TestClient(fastapi_app) as c:
        c.upload_root = tmp_path / "uploads"
        yield c


def _login(client, username, role, password="pass12345"):
    return {"Authorization": f"Bearer {client.post('/auth/login', json={'username': username, 'password': password}).json()['access_token']}"}


@pytest.fixture
def users(client):
    client.post("/auth/register", json={"username": "admin", "full_name": "Admin",
                                        "role": "admin", "password": "adminpass123"})
    admin = {"Authorization": "Bearer " + client.post(
        "/auth/login", json={"username": "admin", "password": "adminpass123"}).json()["access_token"]}
    for u, role in (("des", "designer"), ("chk", "checker"), ("apr", "approver")):
        r = client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                             "password": "pass12345"}, headers=admin)
        assert r.status_code in (200, 201), r.text
    return {"admin": admin, "des": _login(client, "des", "designer"),
            "chk": _login(client, "chk", "checker"), "apr": _login(client, "apr", "approver")}


def _station(client, headers, sid="100"):
    r = client.post("/stations", json={"name": "ALER", "kavach_station_id": sid,
                       "sip_drawing_number": "IPU.1100A", "kavach_version": "2",
                       "sip_version": "1", "guideline_version": "0"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _upload(client, headers, sid, doc_type="SIP", name="sip.pdf", data=b"%PDF-1.4 fake", **form):
    return client.post(f"/stations/{sid}/documents",
                       files={"file": (name, io.BytesIO(data), "application/octet-stream")},
                       data={"doc_type": doc_type, **form}, headers=headers)


def _make_dxf_bytes() -> bytes:
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    doc.layers.add("RFID_TAG")
    doc.layers.add("SIGNAL-MAIN")
    msp.add_text("S1", dxfattribs={"layer": "SIGNAL-MAIN", "insert": (1000, 50)})
    blk = doc.blocks.new(name="TAG_SYM")
    blk.add_attdef("ID", insert=(0, 0))
    ins = msp.add_blockref("TAG_SYM", (1250, 10), dxfattribs={"layer": "RFID_TAG"})
    ins.add_attrib("ID", "R-775", insert=(1250, 10)).dxf.layer = "RFID_TAG"
    msp.add_text("NOTE", dxfattribs={"layer": "TITLE_BLOCK", "insert": (0, 0)})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()


# ---------------------------------------------------------------------------
# FR-001
# ---------------------------------------------------------------------------
def test_document_types_endpoint(client, users):
    r = client.get("/document-types", headers=users["des"])
    assert r.status_code == 200
    codes = {d["code"]: d for d in r.json()}
    for c in ("SIP", "SITE_SURVEY", "RFID_ALLOCATION_CHART", "ADJACENT_LAYOUT", "TOC"):
        assert c in codes
    assert codes["SIP"]["required"] and not codes["ADJACENT_LAYOUT"]["required"]


def test_upload_creates_revisions_and_marks_current(client, users):
    sid = _station(client, users["des"])
    r1 = _upload(client, users["des"], sid, version_label="SIP Rev-A")
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["revision"] == 1 and d1["is_current"] and len(d1["sha256"]) == 64
    assert d1["uploaded_by"] == "des" and d1["version_label"] == "SIP Rev-A"

    r2 = _upload(client, users["des"], sid, data=b"%PDF-1.4 newer")
    assert r2.json()["revision"] == 2

    docs = client.get(f"/stations/{sid}/documents", headers=users["chk"]).json()
    by_rev = {d["revision"]: d for d in docs}
    assert by_rev[2]["is_current"] and not by_rev[1]["is_current"]
    # both files physically exist
    assert len(list(client.upload_root.rglob("*.pdf"))) == 2


def test_download_returns_original_bytes(client, users):
    sid = _station(client, users["des"])
    doc = _upload(client, users["des"], sid, doc_type="RFID_ALLOCATION_CHART",
                  name="alloc.csv", data=b"tag,number\nR-775,775\n").json()
    r = client.get(f"/stations/{sid}/documents/{doc['id']}/download", headers=users["chk"])
    assert r.status_code == 200
    assert r.content == b"tag,number\nR-775,775\n"
    assert "alloc.csv" in r.headers.get("content-disposition", "")


def test_upload_rejects_wrong_extension_for_type(client, users):
    sid = _station(client, users["des"])
    r = _upload(client, users["des"], sid, doc_type="RFID_ALLOCATION_CHART", name="chart.dwg")
    assert r.status_code == 422
    r = _upload(client, users["des"], sid, doc_type="NOPE")
    assert r.status_code == 422


def test_upload_rejects_empty_and_oversize(client, users, monkeypatch):
    sid = _station(client, users["des"])
    assert _upload(client, users["des"], sid, data=b"").status_code == 422
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.0001")  # ~100 bytes
    assert _upload(client, users["des"], sid, data=b"x" * 500).status_code == 413


def test_path_components_in_filename_are_stripped(client, users):
    sid = _station(client, users["des"])
    r = _upload(client, users["des"], sid, name="..\\..\\evil\\sip.pdf")
    assert r.status_code == 200
    assert r.json()["original_filename"] == "sip.pdf"
    for p in client.upload_root.rglob("*"):
        assert client.upload_root in p.resolve().parents or p.resolve() == client.upload_root


def test_checker_cannot_upload(client, users):
    sid = _station(client, users["des"])
    assert _upload(client, users["chk"], sid).status_code == 403


def test_upload_blocked_when_not_draft(client, users):
    sid = _station(client, users["des"])
    client.post(f"/stations/{sid}/self-check", json={}, headers=users["des"])
    client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "chk"},
                headers=users["des"])
    assert _upload(client, users["des"], sid).status_code == 409


def test_delete_unreferenced_document_removes_file(client, users):
    sid = _station(client, users["des"])
    doc = _upload(client, users["des"], sid).json()
    assert len(list(client.upload_root.rglob("*.pdf"))) == 1
    r = client.delete(f"/stations/{sid}/documents/{doc['id']}", headers=users["des"])
    assert r.status_code == 204
    assert len(list(client.upload_root.rglob("*.pdf"))) == 0


def test_delete_refused_when_tag_traces_to_document(client, users):
    sid = _station(client, users["des"])
    doc = _upload(client, users["des"], sid).json()
    r = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                    "location_km": 1.0, "source_document_id": doc["id"]}, headers=users["des"])
    assert r.status_code == 200
    r = client.delete(f"/stations/{sid}/documents/{doc['id']}", headers=users["des"])
    assert r.status_code == 409 and "trace" in r.json()["detail"]


def test_delete_refused_when_document_was_in_a_workflow_snapshot(client, users):
    sid = _station(client, users["des"])
    doc = _upload(client, users["des"], sid).json()
    client.post(f"/stations/{sid}/self-check", json={}, headers=users["des"])
    client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "chk"},
                headers=users["des"])
    client.post(f"/stations/{sid}/request-changes", json={"comment": "fix"}, headers=users["chk"])
    r = client.delete(f"/stations/{sid}/documents/{doc['id']}", headers=users["des"])
    assert r.status_code == 409 and "workflow" in r.json()["detail"]


def test_station_delete_removes_files(client, users):
    sid = _station(client, users["des"])
    _upload(client, users["des"], sid)
    assert client.delete(f"/stations/{sid}", headers=users["des"]).status_code == 204
    assert len(list(client.upload_root.rglob("*.pdf"))) == 0


# ---------------------------------------------------------------------------
# Register source_document_id
# ---------------------------------------------------------------------------
def test_source_document_must_belong_to_same_station(client, users):
    s1 = _station(client, users["des"], "1")
    s2 = _station(client, users["des"], "2")
    doc = _upload(client, users["des"], s1).json()
    r = client.post(f"/stations/{s2}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                    "location_km": 1.0, "source_document_id": doc["id"]}, headers=users["des"])
    assert r.status_code == 422


def test_put_without_source_field_preserves_link(client, users):
    """An older client that doesn't send source_document_id must not wipe it."""
    sid = _station(client, users["des"])
    doc = _upload(client, users["des"], sid).json()
    tag = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                      "location_km": 1.0, "source_document_id": doc["id"]},
                      headers=users["des"]).json()
    r = client.put(f"/stations/{sid}/tags/{tag['id']}", json={"tag_ref": "R-1", "tag_type": "N",
                   "location_km": 1.5}, headers=users["des"])
    assert r.status_code == 200
    assert r.json()["source_document_id"] == doc["id"] and r.json()["location_km"] == 1.5
    # explicit null does unlink
    r = client.put(f"/stations/{sid}/tags/{tag['id']}", json={"tag_ref": "R-1", "tag_type": "N",
                   "location_km": 1.5, "source_document_id": None}, headers=users["des"])
    assert r.json()["source_document_id"] is None


# ---------------------------------------------------------------------------
# FR-002 DXF import
# ---------------------------------------------------------------------------
def _import(client, headers, sid, **form):
    return client.post(f"/stations/{sid}/import-dxf",
                       files={"file": ("sip.dxf", io.BytesIO(_make_dxf_bytes()), "application/dxf")},
                       data=form, headers=headers)


def test_import_dxf_returns_candidates_without_touching_registers(client, users):
    sid = _station(client, users["des"])
    r = _import(client, users["des"], sid)
    assert r.status_code == 200, r.text
    body = r.json()
    texts = {c["text"]: c for c in body["candidates"]}
    assert texts["R-775"]["kind"] == "tag"
    assert texts["S1"]["kind"] == "element"
    assert texts["NOTE"]["kind"] == "unclassified"
    assert body["document"]["doc_type"] == "SIP" and body["document"]["revision"] == 1
    assert any("calibration" in w for w in body["warnings"])
    assert client.get(f"/stations/{sid}/tags", headers=users["des"]).json() == []
    assert client.get(f"/stations/{sid}/elements", headers=users["des"]).json() == []


def test_import_dxf_chainage_calibration(client, users):
    sid = _station(client, users["des"])
    # x=1000 drawing units == km 262.000 ; 1000 units per km
    r = _import(client, users["des"], sid, ref_x="1000", ref_km="262.0", units_per_km="1000")
    texts = {c["text"]: c for c in r.json()["candidates"]}
    assert texts["S1"]["suggested_location_km"] == 262.0
    assert texts["R-775"]["suggested_location_km"] == 262.25
    # re-parse stored doc with a different calibration
    doc_id = r.json()["document"]["id"]
    r2 = client.get(f"/stations/{sid}/documents/{doc_id}/dxf-candidates",
                    params={"ref_x": 0, "ref_km": 0, "units_per_km": 500}, headers=users["chk"])
    texts2 = {c["text"]: c for c in r2.json()["candidates"]}
    assert texts2["R-775"]["suggested_location_km"] == 2.5


def test_import_dxf_rejects_non_dxf(client, users):
    sid = _station(client, users["des"])
    r = client.post(f"/stations/{sid}/import-dxf",
                    files={"file": ("sip.dwg", io.BytesIO(b"x"), "application/octet-stream")},
                    headers=users["des"])
    assert r.status_code == 422


def test_dxf_commit_creates_traced_rows_and_links_by_ref(client, users):
    sid = _station(client, users["des"])
    doc_id = _import(client, users["des"], sid).json()["document"]["id"]
    r = client.post(f"/stations/{sid}/documents/{doc_id}/dxf-commit", json={
        "elements": [{"element_ref": "S1", "element_type": "Mainline Starter", "location_km": 262.0}],
        "tags": [{"tag_ref": "R-775", "tag_type": "S", "location_km": 262.25, "tag_number": 775,
                  "linked_element_ref": "S1"}],
    }, headers=users["des"])
    assert r.status_code == 200, r.text
    assert r.json()["elements_created"] == 1 and r.json()["tags_created"] == 1
    tags = client.get(f"/stations/{sid}/tags", headers=users["des"]).json()
    els = client.get(f"/stations/{sid}/elements", headers=users["des"]).json()
    assert tags[0]["source_document_id"] == doc_id and els[0]["source_document_id"] == doc_id
    assert tags[0]["linked_element_id"] == els[0]["id"]


def test_dxf_commit_is_all_or_nothing(client, users):
    sid = _station(client, users["des"])
    doc_id = _import(client, users["des"], sid).json()["document"]["id"]
    r = client.post(f"/stations/{sid}/documents/{doc_id}/dxf-commit", json={
        "elements": [{"element_ref": "S1", "element_type": "Mainline Starter", "location_km": 1}],
        "tags": [{"tag_ref": "R-1", "tag_type": "S", "location_km": 1},
                 {"tag_ref": "R-2", "tag_type": "BOGUS", "location_km": 2},
                 {"tag_ref": "R-3", "tag_type": "N", "location_km": 3, "linked_element_ref": "NOPE"}],
    }, headers=users["des"])
    assert r.status_code == 422
    errs = r.json()["detail"]["errors"]
    assert any("BOGUS" in e for e in errs) and any("NOPE" in e for e in errs)
    assert client.get(f"/stations/{sid}/tags", headers=users["des"]).json() == []
    assert client.get(f"/stations/{sid}/elements", headers=users["des"]).json() == []


def test_dxf_commit_rejects_duplicate_refs(client, users):
    sid = _station(client, users["des"])
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-775", "tag_type": "S",
                "location_km": 1.0}, headers=users["des"])
    doc_id = _import(client, users["des"], sid).json()["document"]["id"]
    r = client.post(f"/stations/{sid}/documents/{doc_id}/dxf-commit", json={
        "tags": [{"tag_ref": "R-775", "tag_type": "S", "location_km": 1}]}, headers=users["des"])
    assert r.status_code == 422


def test_dxf_commit_requires_designer_and_draft(client, users):
    sid = _station(client, users["des"])
    doc_id = _import(client, users["des"], sid).json()["document"]["id"]
    body = {"tags": [{"tag_ref": "R-1", "tag_type": "S", "location_km": 1}]}
    assert client.post(f"/stations/{sid}/documents/{doc_id}/dxf-commit", json=body,
                       headers=users["chk"]).status_code == 403


# ---------------------------------------------------------------------------
# FR-011 traceability
# ---------------------------------------------------------------------------
def test_traceability_matrix_end_to_end(client, users):
    sid = _station(client, users["des"])
    sip = _upload(client, users["des"], sid, version_label="SIP R1").json()
    _upload(client, users["des"], sid, doc_type="SITE_SURVEY", name="survey.xlsx")
    # no allocation chart yet
    t = client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N",
                    "location_km": 1.0, "source_document_id": sip["id"]}, headers=users["des"])
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-2", "tag_type": "N",
                "location_km": 2.0}, headers=users["des"])

    tr = client.get(f"/stations/{sid}/traceability", headers=users["chk"]).json()
    assert tr["summary"]["tags"] == 2 and tr["summary"]["tags_traced"] == 1
    assert any("Allocation Chart" in g for g in tr["gaps"])
    assert any("R-2" in g for g in tr["gaps"])
    row = next(r for r in tr["rows"] if r["ref"] == "R-1")
    assert row["source"]["doc_type"] == "SIP" and not row["source_outdated"]

    # new SIP revision -> R-1 now traces to a superseded input
    _upload(client, users["des"], sid, data=b"%PDF new")
    tr = client.get(f"/stations/{sid}/traceability", headers=users["chk"]).json()
    row = next(r for r in tr["rows"] if r["ref"] == "R-1")
    assert row["source_outdated"] and tr["summary"]["rows_on_superseded_inputs"] == 1


def test_workflow_events_record_input_snapshot(client, users):
    sid = _station(client, users["des"])
    sip = _upload(client, users["des"], sid).json()
    alloc = _upload(client, users["des"], sid, doc_type="RFID_ALLOCATION_CHART",
                    name="alloc.xlsx").json()
    client.post(f"/stations/{sid}/self-check", json={}, headers=users["des"])
    r = client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "chk"},
                    headers=users["des"])
    assert r.status_code == 200, r.text
    wf = client.get(f"/stations/{sid}/workflow", headers=users["des"]).json()
    snap = wf["history"][-1]["input_snapshot"]
    ids = {s["id"] for s in snap}
    assert ids == {sip["id"], alloc["id"]}
    assert all(len(s["sha256"]) == 64 for s in snap)
    tr = client.get(f"/stations/{sid}/traceability", headers=users["des"]).json()
    assert tr["workflow"][-1]["input_snapshot"] == snap
