"""
BRD FR-006: configurable checklist -- admin rule management (audited, with a reason
for every change) and per-station manual checklist confirmations by reviewers.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..rules import checklist as ck
from ..rules import store

router = APIRouter(tags=["checklist"])

from ..auth.permissions import CAPABILITIES
CHECKLIST_EDITOR_ROLES = CAPABILITIES["checklist.edit"]      # admin + Configuration Manager
RESPONDER_ROLES = CAPABILITIES["checklist.respond"]
RESPOND_STATUSES = ("submitted", "checked")  # manual items are confirmed during review


def _default_keys() -> set[str]:
    return {r.key for r in ck.default_rules()}


def can_edit(user: models.UserORM) -> bool:
    return user.role in CHECKLIST_EDITOR_ROLES


def _require_editor(user):
    if not can_edit(user):
        raise HTTPException(403, "Only a Configuration Manager or admin can change the checklist configuration")


def _rule_or_404(rule_id: int, db: Session) -> models.ChecklistRuleORM:
    r = db.get(models.ChecklistRuleORM, rule_id)
    if not r or r.deleted:
        raise HTTPException(404, "Rule not found")
    return r


def _out(r: models.ChecklistRuleORM) -> schemas.ChecklistRuleOut:
    o = schemas.ChecklistRuleOut.model_validate(r, from_attributes=True)
    o.is_builtin = r.key in _default_keys()
    try:
        o.param_schema = ck.schema_for(r.kind, r.builtin)
    except ck.RuleError:
        o.param_schema = []
    return o


def _log(db, rule, action, before, after, reason, user):
    db.add(models.ChecklistChangeORM(
        rule_id=rule.id if rule else None, rule_key=rule.key if rule else None, action=action,
        before=json.dumps(before) if before is not None else None,
        after=json.dumps(after) if after is not None else None,
        reason=reason.strip(), changed_by=user.username, changed_at=store.now()))


def _validate_common(severity, kind):
    if severity is not None and severity not in ck.SEVERITIES:
        raise HTTPException(422, f"severity must be one of {ck.SEVERITIES}")
    if kind is not None and kind not in ck.KINDS:
        raise HTTPException(422, f"kind must be one of {ck.KINDS}")


# ---------------------------------------------------------------------------
# Rule management
# ---------------------------------------------------------------------------
@router.get("/checklist", response_model=schemas.ChecklistOut)
def get_checklist(db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    rows = (db.query(models.ChecklistRuleORM).filter(models.ChecklistRuleORM.deleted.isnot(True))
            .order_by(models.ChecklistRuleORM.sort_order, models.ChecklistRuleORM.id).all())
    return schemas.ChecklistOut(config_version=store.config_version(db), rules=[_out(r) for r in rows],
                                kinds={k: v for k, v in ck.KIND_SCHEMAS.items()}, can_edit=can_edit(user))


@router.post("/checklist/rules", response_model=schemas.ChecklistRuleOut)
def create_rule(payload: schemas.ChecklistRuleCreate, db: Session = Depends(get_db),
                user: models.UserORM = Depends(get_current_user)):
    _require_editor(user)
    _validate_common(payload.severity, payload.kind)
    if payload.kind == "builtin":
        raise HTTPException(422, "Built-in rules are provided by the platform; add a declarative "
                                 "rule (tag_element_distance / tag_spacing / required_field / manual)")
    try:
        params = ck.validate_params(payload.kind, None, payload.params)
    except ck.RuleError as e:
        raise HTTPException(422, str(e))
    slug = re.sub(r"[^a-z0-9]+", "_", payload.title.lower()).strip("_")[:40] or "rule"
    key = f"custom.{slug}"
    n = 2
    while db.query(models.ChecklistRuleORM).filter_by(key=key).first():
        key = f"custom.{slug}_{n}"
        n += 1
    last = db.query(models.ChecklistRuleORM).order_by(models.ChecklistRuleORM.sort_order.desc()).first()
    row = models.ChecklistRuleORM(
        key=key, kind=payload.kind, clause=payload.clause.strip(), title=payload.title.strip(),
        description=(payload.description or "").strip() or None, params=json.dumps(params),
        severity=payload.severity, enabled=payload.enabled,
        blocking=payload.blocking if payload.kind == "manual" else False,
        sort_order=(last.sort_order + 10) if last else 10, updated_by=user.username, updated_at=store.now())
    db.add(row)
    db.flush()
    _log(db, row, "create", None, store.rule_snapshot(row), payload.reason, user)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.put("/checklist/rules/{rule_id}", response_model=schemas.ChecklistRuleOut)
def update_rule(rule_id: int, payload: schemas.ChecklistRuleUpdate, db: Session = Depends(get_db),
                user: models.UserORM = Depends(get_current_user)):
    _require_editor(user)
    _validate_common(payload.severity, None)
    row = _rule_or_404(rule_id, db)
    before = store.rule_snapshot(row)
    if payload.params is not None:
        try:
            row.params = json.dumps(ck.validate_params(row.kind, row.builtin, payload.params))
        except ck.RuleError as e:
            raise HTTPException(422, str(e))
    for f in ("clause", "title"):
        v = getattr(payload, f)
        if v is not None:
            if not v.strip():
                raise HTTPException(422, f"{f} cannot be blank")
            setattr(row, f, v.strip())
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.severity is not None:
        row.severity = payload.severity
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.blocking is not None:
        if row.kind != "manual" and payload.blocking:
            raise HTTPException(422, "Only manual checklist items can be blocking")
        row.blocking = payload.blocking
    after = store.rule_snapshot(row)
    if after == before:
        raise HTTPException(422, "Nothing changed")
    row.updated_by, row.updated_at = user.username, store.now()
    _log(db, row, "update", before, after, payload.reason, user)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.post("/checklist/rules/{rule_id}/reset", response_model=schemas.ChecklistRuleOut)
def reset_rule(rule_id: int, payload: schemas.ChecklistReason, db: Session = Depends(get_db),
               user: models.UserORM = Depends(get_current_user)):
    _require_editor(user)
    row = _rule_or_404(rule_id, db)
    default = next((r for r in ck.default_rules() if r.key == row.key), None)
    if not default:
        raise HTTPException(409, "Only built-in rules can be reset to defaults")
    before = store.rule_snapshot(row)
    row.clause, row.title, row.description = default.clause, default.title, default.description
    row.params, row.severity = json.dumps(default.params), default.severity
    row.enabled, row.blocking = default.enabled, default.blocking
    row.updated_by, row.updated_at = user.username, store.now()
    _log(db, row, "reset", before, store.rule_snapshot(row), payload.reason, user)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/checklist/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, payload: schemas.ChecklistReason, db: Session = Depends(get_db),
                user: models.UserORM = Depends(get_current_user)):
    _require_editor(user)
    row = _rule_or_404(rule_id, db)
    if row.key in _default_keys():
        raise HTTPException(409, "Built-in rules cannot be deleted -- disable it instead")
    before = store.rule_snapshot(row)
    row.deleted, row.enabled = True, False
    row.updated_by, row.updated_at = user.username, store.now()
    _log(db, row, "delete", before, None, payload.reason, user)
    db.commit()
    return None


@router.post("/checklist/reorder", response_model=schemas.ChecklistOut)
def reorder(payload: schemas.ChecklistReorder, db: Session = Depends(get_db),
            user: models.UserORM = Depends(get_current_user)):
    _require_editor(user)
    rows = {r.id: r for r in db.query(models.ChecklistRuleORM)
            .filter(models.ChecklistRuleORM.deleted.isnot(True)).all()}
    if sorted(payload.ordered_ids) != sorted(rows):
        raise HTTPException(422, "ordered_ids must list every active rule exactly once")
    before = [rows[i].key for i in sorted(rows, key=lambda i: (rows[i].sort_order, i))]
    for pos, rid in enumerate(payload.ordered_ids):
        rows[rid].sort_order = (pos + 1) * 10
    after = [rows[i].key for i in payload.ordered_ids]
    if before == after:
        raise HTTPException(422, "Order unchanged")
    _log(db, None, "reorder", before, after, payload.reason, user)
    db.commit()
    return get_checklist(db, user)


@router.get("/checklist/changes", response_model=list[schemas.ChecklistChangeOut])
def changes(limit: int = 200, db: Session = Depends(get_db),
            user: models.UserORM = Depends(get_current_user)):
    return (db.query(models.ChecklistChangeORM).order_by(models.ChecklistChangeORM.id.desc())
            .limit(min(limit, 1000)).all())


# ---------------------------------------------------------------------------
# Manual checklist per station
# ---------------------------------------------------------------------------
def _station_or_404(station_id: int, db: Session) -> models.StationORM:
    st = db.get(models.StationORM, station_id)
    if not st:
        raise HTTPException(404, "Station not found")
    return st


@router.get("/stations/{station_id}/checklist", response_model=schemas.ManualChecklistOut)
def station_checklist(station_id: int, db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    st = _station_or_404(station_id, db)
    items = []
    for i in store.manual_items(db, station_id):
        r, resp = i["rule"], i["response"]
        items.append(schemas.ManualItemOut(
            rule_id=r.id, clause=r.clause, title=r.title, description=r.description,
            blocking=r.blocking, severity=r.severity,
            status=resp.status if resp else None, note=resp.note if resp else None,
            responded_by=resp.responded_by if resp else None,
            responded_at=resp.responded_at if resp else None))
    return schemas.ManualChecklistOut(
        items=items, summary=store.manual_summary(db, station_id),
        can_respond=user.role in RESPONDER_ROLES and st.status in RESPOND_STATUSES)


@router.put("/stations/{station_id}/checklist/{rule_id}", response_model=schemas.ManualChecklistOut)
def respond(station_id: int, rule_id: int, payload: schemas.ManualResponseIn,
            db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    st = _station_or_404(station_id, db)
    if user.role not in RESPONDER_ROLES:
        raise HTTPException(403, "Only a checker, approver or admin can confirm checklist items")
    if st.status not in RESPOND_STATUSES:
        raise HTTPException(409, f"Checklist items are confirmed during review (submitted / checked); "
                                 f"station is '{st.status}'")
    rule = _rule_or_404(rule_id, db)
    if rule.kind != "manual" or not rule.enabled:
        raise HTTPException(422, "Not an active manual checklist item")
    if payload.status not in ck.MANUAL_RESPONSES:
        raise HTTPException(422, f"status must be one of {ck.MANUAL_RESPONSES}")
    if payload.status in ("FAIL", "NA") and not payload.note.strip():
        raise HTTPException(422, f"A note is required when marking an item {payload.status}")
    db.add(models.ChecklistResponseORM(
        station_id=station_id, rule_id=rule_id, cycle_event_id=store.current_cycle_event_id(db, station_id),
        status=payload.status, note=payload.note.strip() or None, responded_by=user.username,
        responded_by_role=user.role, responded_at=store.now(), layout_version=st.layout_version))
    db.commit()
    return station_checklist(station_id, db, user)
