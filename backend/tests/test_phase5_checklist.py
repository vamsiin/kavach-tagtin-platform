"""
Phase 5: BRD FR-006 configurable checklist engine -- rule parameters, severity,
enable/disable, custom declarative rules, audit/versioning, manual checklist items
per review cycle, and the 'Mark checked' gate.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from app.domain import Element, Station, Tag
from app.rules import checklist as ck
from app.rules.engine import run_all_checks

os.environ.setdefault("JWT_SECRET", "test-secret-for-phase5-tests")

ST = Station(id=1, name="T", kavach_station_id="1", sip_drawing_number="S", kavach_version="2",
             sip_version="1", guideline_version="0")


def rule(key):
    return next(r for r in ck.default_rules() if r.key == key)


# ---------------------------------------------------------------------------
# Pure engine
# ---------------------------------------------------------------------------
def test_defaults_equal_legacy_behaviour():
    tags = [Tag(id=1, tag_ref="R-1", tag_type="N", location_m=0, direction="UP"),
            Tag(id=2, tag_ref="R-2", tag_type="N", location_m=1200, direction="UP")]
    a = run_all_checks(ST, [], tags, [])
    b = run_all_checks(ST, [], tags, [], rules=ck.default_rules())
    assert [vars(x) for x in a.results] == [vars(x) for x in b.results]
    assert any(x.clause == "H2.5" and x.status == "FAIL" and "max 1000m" in x.message for x in a.results)


def test_gate_distance_configurable_resolves_br008():
    """BR-008 (550-850 m) vs Annexure-H (>= 600 m) is now a setting."""
    el = Element(id=1, element_ref="LC-1", element_type="LC Gate", location_m=50000)
    tags = [Tag(id=1, tag_ref="G-1", tag_type="G", location_m=50000 - 580, linked_element_id=1)]
    default = [x for x in run_all_checks(ST, [el], tags, []).results if x.clause == "H2.9"]
    assert default[0].status == "FAIL"  # 580 < 600
    rules = ck.default_rules()
    r = next(x for x in rules if x.key == "builtin.h2_9")
    r.params = ck.validate_params("builtin", "h2_9", {"min_m": 550, "max_m": 850})
    res = [x for x in run_all_checks(ST, [el], tags, [], rules=rules).results if x.clause == "H2.9"]
    assert res[0].status == "PASS" and "550-850m" in res[0].title


def test_parity_map_configurable():
    tags = [Tag(id=1, tag_ref="R-793", tag_type="S", location_m=1, tag_number=793, direction="Nominal")]
    rules = ck.default_rules()
    r = next(x for x in rules if x.key == "builtin.fr004_parity")
    assert [x.status for x in run_all_checks(ST, [], tags, [], rules=rules).results
            if x.title.startswith("Tag number parity")] == ["FAIL"]
    r.params = ck.validate_params("builtin", "fr004_parity",
                                  {"parity_map": {"Nominal": "odd", "Reverse": "even"}})
    assert [x.status for x in run_all_checks(ST, [], tags, [], rules=rules).results
            if x.title.startswith("Tag number parity")] == ["PASS"]


def test_warn_severity_and_disable():
    tags = [Tag(id=1, tag_ref="R-1", tag_type="N", location_m=0, direction="UP"),
            Tag(id=2, tag_ref="R-2", tag_type="N", location_m=5000, direction="UP")]
    rules = ck.default_rules()
    r = next(x for x in rules if x.key == "builtin.h2_5")
    r.severity = "WARN"
    rep = run_all_checks(ST, [], tags, [], rules=rules)
    h25 = [x.status for x in rep.results if x.clause == "H2.5"]
    assert h25 == ["WARN"]
    r.enabled = False
    assert not [x for x in run_all_checks(ST, [], tags, [], rules=rules).results if x.clause == "H2.5"]


def test_custom_declarative_rules():
    els = [Element(id=1, element_ref="S1", element_type="Mainline Starter", location_m=1000)]
    tags = [Tag(id=1, tag_ref="R-1", tag_type="S", location_m=1030, linked_element_id=1, direction="Nominal"),
            Tag(id=2, tag_ref="R-2", tag_type="L", location_m=2000, direction="Nominal"),
            Tag(id=3, tag_ref="R-3", tag_type="L", location_m=2600, direction="Nominal")]
    dist = ck.RuleConfig(key="custom.sfoot", kind="tag_element_distance", clause="QFTL-1",
                         title="Foot tag within 20m of signal",
                         params=ck.validate_params("tag_element_distance", None,
                                                   {"tag_types": ["S"], "max_m": 20}))
    spacing = ck.RuleConfig(key="custom.lspace", kind="tag_spacing", clause="QFTL-2",
                            title="L tags <= 500m apart",
                            params=ck.validate_params("tag_spacing", None, {"tag_types": ["L"], "max_gap_m": 500}))
    req = ck.RuleConfig(key="custom.req", kind="required_field", clause="QFTL-3", title="Tag numbers entered",
                        params=ck.validate_params("required_field", None,
                                                  {"entity": "tag", "field": "tag_number", "tag_types": ["S"]}))
    rep = run_all_checks(ST, els, tags, [], rules=[dist, spacing, req])
    got = {(x.clause, x.status) for x in rep.results}
    assert got == {("QFTL-1", "FAIL"), ("QFTL-2", "FAIL"), ("QFTL-3", "FAIL")}
    assert "30m from S1" in next(x.message for x in rep.results if x.clause == "QFTL-1")


@pytest.mark.parametrize("kind,builtin,params,msg", [
    ("builtin", "h2_9", {"min_m": 900, "max_m": 800}, "cannot exceed"),
    ("builtin", "h2_9", {"minimum": 1}, "Unknown parameter"),
    ("builtin", "h2_5", {"max_gap_m": -5}, ">= 0"),
    ("builtin", "fr004_parity", {"parity_map": {"Nominal": "sometimes"}}, "odd"),
    ("tag_element_distance", None, {"tag_types": ["S"]}, "minimum, a maximum"),
    ("tag_element_distance", None, {"tag_types": ["Q"], "max_m": 5}, "unknown value"),
    ("required_field", None, {"entity": "tin", "field": "tag_number"}, "not a field of tin"),
])
def test_param_validation(kind, builtin, params, msg):
    with pytest.raises(ck.RuleError, match=msg):
        ck.validate_params(kind, builtin, params)


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
    for u, role in (("dana", "designer"), ("cara", "checker"), ("ana", "approver")):
        client.post("/auth/users", json={"username": u, "full_name": u, "role": role,
                                         "password": "pass12345"}, headers=admin)
    return {"admin": admin, **{u: login(u, "pass12345") for u in ("dana", "cara", "ana")}}


def _rules(client, h):
    return {r["key"]: r for r in client.get("/checklist", headers=h["dana"]).json()["rules"]}


def _station(client, h):
    return client.post("/stations", json={"centre_line_m": 0, "adjacent_stations": [{"name": "ADJ", "side": "Nominal", "border_m": 0}],
        "name": "ALER", "kavach_station_id": "103", "sip_drawing_number": "IPU.1100A",
        "kavach_version": "2", "sip_version": "1", "guideline_version": "0"}, headers=h["dana"]).json()["id"]


def test_seeded_checklist_and_permissions(client, h):
    body = client.get("/checklist", headers=h["dana"]).json()
    keys = [r["key"] for r in body["rules"]]
    assert "builtin.h2_9" in keys and "manual.h2_19" in keys
    assert body["can_edit"] is False and body["config_version"] == len(keys)  # one 'seed' change each
    h29 = next(r for r in body["rules"] if r["key"] == "builtin.h2_9")
    assert h29["params"] == {"min_m": 600, "max_m": None} and h29["is_builtin"]
    assert {p["name"] for p in h29["param_schema"]} == {"min_m", "max_m"}
    r = client.put(f"/checklist/rules/{h29['id']}", json={"params": {"min_m": 550}, "reason": "x"},
                   headers=h["dana"])
    assert r.status_code == 403
    # restart doesn't duplicate or overwrite
    from app.database import SessionLocal
    from app.rules.store import seed_rules
    with SessionLocal() as db:
        assert seed_rules(db) == 0


def test_admin_edit_is_audited_and_changes_verification(client, h):
    sid = _station(client, h)
    el = client.post(f"/stations/{sid}/elements", json={"element_ref": "LC-1", "element_type": "Gate Stop Signal",
                     "location_m": 50000}, headers=h["dana"]).json()
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "G-1", "tag_type": "G", "location_m": 49420,
                "linked_element_id": el["id"]}, headers=h["dana"])
    v0 = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    assert "H2.9" in v0["summary"]["clauses_failing"]

    rid = _rules(client, h)["builtin.h2_9"]["id"]
    assert client.put(f"/checklist/rules/{rid}", json={"params": {"min_m": 550, "max_m": 850}, "reason": ""},
                      headers=h["admin"]).status_code == 422  # reason mandatory
    r = client.put(f"/checklist/rules/{rid}", json={"params": {"min_m": 550, "max_m": 850},
                   "reason": "BR-008: QFTL policy 550-850 m confirmed"}, headers=h["admin"])
    assert r.status_code == 200 and r.json()["params"] == {"min_m": 550.0, "max_m": 850.0}
    v1 = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    assert "H2.9" not in v1["summary"]["clauses_failing"]
    assert v1["checklist_version"] == v0["checklist_version"] + 1

    ch = client.get("/checklist/changes", headers=h["dana"]).json()[0]
    assert ch["action"] == "update" and ch["changed_by"] == "admin"
    assert ch["before"]["params"]["min_m"] == 600 and ch["after"]["params"]["max_m"] == 850
    assert "BR-008" in ch["reason"]

    # no-op edits rejected; reset restores defaults
    assert client.put(f"/checklist/rules/{rid}", json={"params": {"min_m": 550, "max_m": 850}, "reason": "again"},
                      headers=h["admin"]).status_code == 422
    r = client.post(f"/checklist/rules/{rid}/reset", json={"reason": "back to Annexure-H"}, headers=h["admin"])
    assert r.json()["params"] == {"min_m": 600, "max_m": None}


def test_disable_builtin_reported_and_cannot_delete(client, h):
    sid = _station(client, h)
    rid = _rules(client, h)["builtin.h2_15"]["id"]
    assert client.request("DELETE", f"/checklist/rules/{rid}", json={"reason": "x"},
                          headers=h["admin"]).status_code == 409
    client.put(f"/checklist/rules/{rid}", json={"enabled": False, "reason": "trial"}, headers=h["admin"])
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    assert any("H2.15" in x for x in v["rules_disabled"])


def test_custom_rule_lifecycle_via_api(client, h):
    sid = _station(client, h)
    client.post(f"/stations/{sid}/tags", json={"tag_ref": "R-1", "tag_type": "N", "location_m": 100},
                headers=h["dana"])
    body = {"kind": "required_field", "clause": "QFTL-3", "title": "Tag number entered",
            "params": {"entity": "tag", "field": "tag_number"}, "severity": "WARN", "reason": "QFTL practice"}
    r = client.post("/checklist/rules", json=body, headers=h["admin"])
    assert r.status_code == 200 and r.json()["key"] == "custom.tag_number_entered" and not r.json()["is_builtin"]
    rid = r.json()["id"]
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    res = [x for x in v["results"] if x["clause"] == "QFTL-3"]
    assert res and res[0]["status"] == "WARN" and v["summary"]["fail_count"] == 0
    # builtin kind can't be created; bad params rejected
    assert client.post("/checklist/rules", json={**body, "kind": "builtin"}, headers=h["admin"]).status_code == 422
    assert client.post("/checklist/rules", json={**body, "params": {"entity": "tag", "field": "nope"}},
                       headers=h["admin"]).status_code == 422
    # delete = soft delete, audited, disappears from checklist and verification
    assert client.request("DELETE", f"/checklist/rules/{rid}", json={"reason": "withdrawn"},
                          headers=h["admin"]).status_code == 204
    assert "custom.tag_number_entered" not in _rules(client, h)
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"]).json()
    assert not [x for x in v["results"] if x["clause"] == "QFTL-3"]


def test_reorder(client, h):
    rules = client.get("/checklist", headers=h["admin"]).json()["rules"]
    ids = [r["id"] for r in rules]
    new = ids[1:] + ids[:1]
    r = client.post("/checklist/reorder", json={"ordered_ids": new, "reason": "group by clause"},
                    headers=h["admin"])
    assert [x["id"] for x in r.json()["rules"]] == new
    assert client.post("/checklist/reorder", json={"ordered_ids": new[:-1], "reason": "x"},
                       headers=h["admin"]).status_code == 422


def _to_submitted(client, h, sid):
    assert client.post(f"/stations/{sid}/self-check", json={}, headers=h["dana"]).status_code == 200
    assert client.post(f"/stations/{sid}/submit", json={"assigned_checker_username": "cara"},
                       headers=h["dana"]).status_code == 200


def test_manual_items_blocking_gate_and_cycles(client, h):
    sid = _station(client, h)
    rid = _rules(client, h)["manual.h2_19"]["id"]
    client.put(f"/checklist/rules/{rid}", json={"blocking": True, "reason": "ToC movements must be confirmed"},
               headers=h["admin"])
    # can't respond in draft
    assert client.put(f"/stations/{sid}/checklist/{rid}", json={"status": "PASS"},
                      headers=h["cara"]).status_code == 409
    _to_submitted(client, h, sid)
    r = client.post(f"/stations/{sid}/check", json={}, headers=h["cara"])
    assert r.status_code == 409 and "H2.19" in r.json()["detail"]
    assert client.put(f"/stations/{sid}/checklist/{rid}", json={"status": "PASS"},
                      headers=h["dana"]).status_code == 403
    assert client.put(f"/stations/{sid}/checklist/{rid}", json={"status": "FAIL"},
                      headers=h["cara"]).status_code == 422  # note required
    body = client.put(f"/stations/{sid}/checklist/{rid}", json={"status": "FAIL", "note": "Route 7 not covered"},
                      headers=h["cara"]).json()
    item = next(i for i in body["items"] if i["rule_id"] == rid)
    assert item["status"] == "FAIL" and item["responded_by"] == "cara"
    r = client.post(f"/stations/{sid}/check", json={}, headers=h["cara"])
    assert r.status_code == 409 and "confirmed as FAIL" in r.json()["detail"]

    # rework -> new cycle: earlier FAIL no longer current, item pending again
    client.post(f"/stations/{sid}/request-changes", json={"comment": "fix route 7"}, headers=h["cara"])
    _to_submitted(client, h, sid)
    items = client.get(f"/stations/{sid}/checklist", headers=h["cara"]).json()
    assert next(i for i in items["items"] if i["rule_id"] == rid)["status"] is None
    assert items["summary"]["pending_blocking"] == ["H2.19"]
    client.put(f"/stations/{sid}/checklist/{rid}", json={"status": "PASS"}, headers=h["cara"])
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200

    # verification report shows the confirmation
    from app.database import SessionLocal
    from app import models
    from app.routers.reports import build_report
    with SessionLocal() as db:
        st = db.get(models.StationORM, sid)
        u = db.query(models.UserORM).filter_by(username="cara").first()
        text = build_report(db, st, u, "verification").plain_text()
    assert "H2.19" in text and "PASS | cara" in text and "Checklist configuration: version" in text


def test_non_blocking_manual_items_do_not_gate(client, h):
    sid = _station(client, h)
    _to_submitted(client, h, sid)
    assert client.post(f"/stations/{sid}/check", json={}, headers=h["cara"]).status_code == 200


def test_migrate_rules_renames_old_clause_numbering():
    """A DB seeded before the Annexure-H clause correction is renamed in place:
    edits and ids survive, H2.12 is split and the new H2.13 inherits its threshold."""
    import json
    from app import models
    from app.database import SessionLocal
    from app.rules.store import migrate_rules, active_rules
    with SessionLocal() as db:
        rows = {r.key: r for r in db.query(models.ChecklistRuleORM).all()}
        # rewind the table to the pre-correction shape
        db.delete(rows["builtin.h2_13"])
        r23, r15, r12 = rows["builtin.h2_23"], rows["builtin.h2_15"], rows["builtin.h2_12"]
        db.flush()
        r23.key, r23.builtin, r23.clause = "builtin.h2_13", "h2_13", "H2.13"
        r23.params = json.dumps({"tag_min": 1, "tag_max": 900, "tin_min": 1, "tin_max": 255})
        r15.key, r15.builtin, r15.clause = "builtin.h2_14", "h2_14", "H2.14"
        r12.params = json.dumps({"dup_min_m": 3, "dup_max_m": 5, "tagset_min_m": 12})
        r12.title = "Duplicate and tag-set spacing"
        m16 = rows["manual.h2_16"]
        m16.key, m16.clause = "manual.h2_15_h2_16", "H2.15/H2.16"
        ids = (r23.id, r15.id, m16.id)
        db.commit()

        assert migrate_rules(db) == 5
        assert migrate_rules(db) == 0          # idempotent
        rules = {r.key: r for r in active_rules(db)}
        assert rules["builtin.h2_23"].id == ids[0] and rules["builtin.h2_23"].params["tag_max"] == 900
        assert rules["builtin.h2_23"].clause == "H2.23"
        assert rules["builtin.h2_15"].id == ids[1] and rules["builtin.h2_15"].clause == "H2.15"
        assert rules["manual.h2_16"].id == ids[2] and rules["manual.h2_16"].clause == "H2.16"
        assert rules["builtin.h2_12"].params == {"dup_min_m": 3, "dup_max_m": 5}
        assert rules["builtin.h2_12"].title == "Duplicate tag pair spacing"
        assert rules["builtin.h2_13"].params == {"tagset_min_m": 12}
        assert rules["builtin.h2_13"].clause == "H2.13"


def test_migrate_repairs_defaults_seeded_before_rename(client, h):
    """Upgrade interrupted by a reload: new-numbered defaults were seeded beside the old
    rows, and H2.12 had already lost its tag-set threshold. seed_rules must repair it."""
    import json
    from app import models
    from app.database import SessionLocal
    from app.rules.store import seed_rules, rule_snapshot, active_rules, _log
    from app.rules.checklist import default_rules
    sid = _station(client, h)
    with SessionLocal() as db:
        rows = {r.key: r for r in db.query(models.ChecklistRuleORM).all()}
        db.delete(rows["builtin.h2_13"])
        db.flush()
        r23, r15, r12, m16, m14 = (rows[k] for k in ("builtin.h2_23", "builtin.h2_15", "builtin.h2_12",
                                                        "manual.h2_16", "manual.h2_14"))
        r23.key, r23.builtin, r23.clause = "builtin.h2_13", "h2_13", "H2.13"
        r23.params = json.dumps({"tag_min": 1, "tag_max": 1023, "tin_min": 1, "tin_max": 255})
        r15.key, r15.builtin, r15.clause = "builtin.h2_14", "h2_14", "H2.14"
        m16.key, m16.clause = "manual.h2_15_h2_16", "H2.15/H2.16"
        m14.key, m14.clause = "manual.h2_14__25km_radius", "H2.14 (25km radius)"
        r12.params = json.dumps({"dup_min_m": 3, "dup_max_m": 5, "tagset_min_m": 12})
        db.flush()
        old_ids = {k: r.id for k, r in (("h2_23", r23), ("h2_15", r15), ("m16", m16), ("m14", m14))}
        # the premature seed: defaults under the new keys, added beside the old rows
        existing = {k for (k,) in db.query(models.ChecklistRuleORM.key).all()}
        for d in default_rules():
            if d.key in existing or d.key == "builtin.h2_13":
                continue
            row = models.ChecklistRuleORM(key=d.key, kind=d.kind, builtin=d.builtin, clause=d.clause,
                                          title=d.title, description=d.description, params=json.dumps(d.params),
                                          severity=d.severity, enabled=True, blocking=False,
                                          sort_order=d.sort_order, updated_by="system", updated_at="x")
            db.add(row)
            db.flush()
            db.add(models.ChecklistChangeORM(rule_id=row.id, rule_key=row.key, action="seed",
                                             changed_by="system", changed_at="x"))
        # the partial migrate: H2.12 lost tagset_min_m, logged with a before snapshot
        before = rule_snapshot(r12)
        r12.params = json.dumps({"dup_min_m": 3, "dup_max_m": 5})
        _log(db, r12, "migrate", before, "partial")
        db.commit()

    # the broken state must not crash verification
    assert client.get(f"/stations/{sid}/verify", headers=h["dana"]).status_code == 200

    with SessionLocal() as db:
        seed_rules(db)
        rules = {r.key: r for r in active_rules(db)}
    assert not {"builtin.h2_14", "manual.h2_15_h2_16", "manual.h2_14__25km_radius"} & set(rules)
    assert rules["builtin.h2_23"].id == old_ids["h2_23"] and rules["builtin.h2_23"].clause == "H2.23"
    assert rules["builtin.h2_15"].id == old_ids["h2_15"]
    assert rules["manual.h2_16"].id == old_ids["m16"] and rules["manual.h2_14"].id == old_ids["m14"]
    assert rules["builtin.h2_13"].params == {"tagset_min_m": 12}
    assert rules["builtin.h2_13"].builtin == "h2_13" and rules["builtin.h2_13"].clause == "H2.13"
    assert sorted(r.key for r in default_rules()) == sorted(rules)   # nothing extra, nothing missing
    v = client.get(f"/stations/{sid}/verify", headers=h["dana"])
    assert v.status_code == 200
