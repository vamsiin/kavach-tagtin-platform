"""Workspaces (railway zones): create and edit them, manage members, move stations
between them, and override checklist rules for a zone. Managed by the Configuration
Manager (or admin); every user sees the workspaces they belong to."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..auth.permissions import require
from ..database import get_db
from ..rules import checklist as ck
from ..rules import store
from ..workspaces.service import DIRECTIONS, can_access, now, visible_workspaces

router = APIRouter(tags=["workspaces"])


def _out(db: Session, w: models.WorkspaceORM) -> schemas.WorkspaceOut:
    return schemas.WorkspaceOut(
        id=w.id, code=w.code, name=w.name, dn_direction=w.dn_direction, open_to_all=bool(w.open_to_all),
        remarks=w.remarks, created_by=w.created_by, created_at=w.created_at,
        members=sorted(m.username for m in w.members),
        station_count=db.query(models.StationORM).filter_by(workspace_id=w.id).count(),
        override_count=db.query(models.WorkspaceRuleOverrideORM).filter_by(workspace_id=w.id).count())


def _get(db: Session, ws_id: int) -> models.WorkspaceORM:
    w = db.get(models.WorkspaceORM, ws_id)
    if not w:
        raise HTTPException(404, "Workspace not found")
    return w


def _validate(db: Session, payload: schemas.WorkspaceIn, ws_id: int | None = None) -> str:
    code = payload.code.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]{0,15}", code):
        raise HTTPException(422, "Code: 1-16 letters / digits, e.g. SCR, ECR, NFR")
    if not payload.name.strip():
        raise HTTPException(422, "Name is required")
    if payload.dn_direction not in DIRECTIONS:
        raise HTTPException(422, f"dn_direction must be one of {DIRECTIONS}")
    clash = db.query(models.WorkspaceORM).filter(models.WorkspaceORM.code == code).first()
    if clash and clash.id != ws_id:
        raise HTTPException(409, f"Workspace {code} already exists")
    return code


@router.get("/workspaces", response_model=list[schemas.WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return [_out(db, w) for w in visible_workspaces(db, user)]


@router.get("/workspaces/users", response_model=list[schemas.UserOut])
def workspace_user_choices(db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    """Active users, for the Configuration Manager to pick members from."""
    require(user, "workspace.manage", "Listing users for workspace membership")
    return db.query(models.UserORM).filter_by(is_active=True).order_by(models.UserORM.username).all()


@router.post("/workspaces", response_model=schemas.WorkspaceOut)
def create_workspace(payload: schemas.WorkspaceIn, db: Session = Depends(get_db),
                     user: models.UserORM = Depends(get_current_user)):
    require(user, "workspace.manage", "Creating a workspace")
    code = _validate(db, payload)
    w = models.WorkspaceORM(code=code, name=payload.name.strip(), dn_direction=payload.dn_direction,
                            open_to_all=payload.open_to_all, remarks=payload.remarks,
                            created_by=user.username, created_at=now())
    db.add(w)
    db.commit()
    db.refresh(w)
    return _out(db, w)


@router.put("/workspaces/{ws_id}", response_model=schemas.WorkspaceOut)
def update_workspace(ws_id: int, payload: schemas.WorkspaceIn, db: Session = Depends(get_db),
                     user: models.UserORM = Depends(get_current_user)):
    require(user, "workspace.manage", "Editing a workspace")
    w = _get(db, ws_id)
    code = _validate(db, payload, ws_id)
    w.code, w.name, w.dn_direction = code, payload.name.strip(), payload.dn_direction
    w.open_to_all, w.remarks = payload.open_to_all, payload.remarks
    db.commit()
    db.refresh(w)
    return _out(db, w)


@router.put("/workspaces/{ws_id}/members", response_model=schemas.WorkspaceOut)
def set_members(ws_id: int, payload: schemas.WorkspaceMembersUpdate, db: Session = Depends(get_db),
                user: models.UserORM = Depends(get_current_user)):
    require(user, "workspace.manage", "Changing workspace members")
    w = _get(db, ws_id)
    wanted = {u.strip() for u in payload.usernames if u.strip()}
    known = {u for (u,) in db.query(models.UserORM.username)}
    unknown = sorted(wanted - known)
    if unknown:
        raise HTTPException(422, f"Unknown user(s): {', '.join(unknown)}")
    have = {m.username: m for m in w.members}
    for name in set(have) - wanted:
        db.delete(have[name])
    for name in wanted - set(have):
        db.add(models.WorkspaceMemberORM(workspace_id=w.id, username=name, added_by=user.username, added_at=now()))
    db.commit()
    db.refresh(w)
    return _out(db, w)


@router.post("/stations/{station_id}/move-workspace", response_model=schemas.StationOut)
def move_station(station_id: int, payload: schemas.MoveStationRequest, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    require(user, "workspace.manage", "Moving a station to another workspace")
    st = db.get(models.StationORM, station_id)
    if not st:
        raise HTTPException(404, "Station not found")
    target = _get(db, payload.workspace_id)
    before = st.workspace.code if st.workspace is not None else None
    if st.workspace_id == target.id:
        raise HTTPException(409, f"Station is already in {target.code}")
    st.workspace_id = target.id
    db.add(models.StationChangeORM(station_id=st.id, field="workspace", before=before, after=target.code,
                                   reason=payload.reason.strip(), changed_by=user.username,
                                   changed_by_role=user.role, changed_at=now()))
    db.commit()
    db.refresh(st)
    return schemas.StationOut.model_validate(st, from_attributes=True)


# ---------------------------------------------------------------------------
# Checklist overrides for a zone
# ---------------------------------------------------------------------------
def _snap(o: models.WorkspaceRuleOverrideORM | None) -> dict | None:
    if o is None:
        return None
    return {"params": json.loads(o.params) if o.params is not None else None, "severity": o.severity,
            "enabled": o.enabled}


@router.put("/workspaces/{ws_id}/overrides/{rule_id}")
def set_override(ws_id: int, rule_id: int, payload: schemas.RuleOverrideIn, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    """Override params / severity / enabled for this zone. Fields left out stay as in
    the standard checklist."""
    require(user, "workspace.manage", "Overriding a checklist rule for a workspace")
    w = _get(db, ws_id)
    rule = db.get(models.ChecklistRuleORM, rule_id)
    if not rule or rule.deleted:
        raise HTTPException(404, "Rule not found")
    if payload.params is None and payload.severity is None and payload.enabled is None:
        raise HTTPException(422, "Give at least one of params, severity or enabled")
    if payload.severity is not None and payload.severity not in ck.SEVERITIES:
        raise HTTPException(422, f"severity must be one of {ck.SEVERITIES}")
    params = None
    if payload.params is not None:
        try:
            params = ck.validate_params(rule.kind, rule.builtin, payload.params)
        except ck.RuleError as e:
            raise HTTPException(422, str(e))
    o = db.query(models.WorkspaceRuleOverrideORM).filter_by(workspace_id=w.id, rule_id=rule.id).first()
    before = _snap(o)
    if o is None:
        o = models.WorkspaceRuleOverrideORM(workspace_id=w.id, rule_id=rule.id)
        db.add(o)
    if payload.params is not None:
        o.params = json.dumps(params)
    if payload.severity is not None:
        o.severity = payload.severity
    if payload.enabled is not None:
        o.enabled = payload.enabled
    o.reason, o.updated_by, o.updated_at = payload.reason.strip(), user.username, now()
    db.flush()
    db.add(models.ChecklistChangeORM(rule_id=rule.id, rule_key=rule.key, action="override", workspace_id=w.id,
                                     before=json.dumps(before) if before else None, after=json.dumps(_snap(o)),
                                     reason=f"[{w.code}] {payload.reason.strip()}", changed_by=user.username,
                                     changed_at=store.now()))
    db.commit()
    return {"workspace": w.code, "rule_key": rule.key, "override": _snap(o)}


@router.delete("/workspaces/{ws_id}/overrides/{rule_id}")
def clear_override(ws_id: int, rule_id: int, reason: str = Body(..., embed=True, min_length=1),
                   db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    require(user, "workspace.manage", "Clearing a workspace checklist override")
    w = _get(db, ws_id)
    o = db.query(models.WorkspaceRuleOverrideORM).filter_by(workspace_id=w.id, rule_id=rule_id).first()
    if not o:
        raise HTTPException(404, "No override for this rule in this workspace")
    rule = db.get(models.ChecklistRuleORM, rule_id)
    db.add(models.ChecklistChangeORM(rule_id=rule_id, rule_key=rule.key if rule else None, action="override_clear",
                                     workspace_id=w.id, before=json.dumps(_snap(o)),
                                     reason=f"[{w.code}] {reason.strip()}", changed_by=user.username,
                                     changed_at=store.now()))
    db.delete(o)
    db.commit()
    return {"workspace": w.code, "rule_id": rule_id, "override": None}
