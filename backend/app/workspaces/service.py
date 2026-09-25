"""Workspaces (railway zones): who can see what, and which workspace new data goes in.

Admins and Configuration Managers see every workspace. Everyone else sees the
workspaces they are members of, plus any marked open_to_all. Stations and charts
with no workspace (only possible before the upgrade that introduced workspaces)
are visible to everyone.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .. import models
from ..auth.deps import get_current_user
from ..database import get_db

ALL_ACCESS_ROLES = ("admin", "config_manager")
DIRECTIONS = ("Nominal", "Reverse")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def accessible_ids(db: Session, user) -> set[int] | None:
    """Workspace ids the user may see; None means all of them."""
    if user.role in ALL_ACCESS_ROLES:
        return None
    ids = {m.workspace_id for m in db.query(models.WorkspaceMemberORM).filter_by(username=user.username)}
    ids |= {w.id for w in db.query(models.WorkspaceORM).filter(models.WorkspaceORM.open_to_all.is_(True))}
    return ids


def can_access(db: Session, user, workspace_id: int | None) -> bool:
    if workspace_id is None:
        return True
    ids = accessible_ids(db, user)
    return ids is None or workspace_id in ids


def visible_workspaces(db: Session, user) -> list[models.WorkspaceORM]:
    ids = accessible_ids(db, user)
    q = db.query(models.WorkspaceORM).order_by(models.WorkspaceORM.code)
    return [w for w in q if ids is None or w.id in ids]


def resolve_for_create(db: Session, user, requested: int | None) -> int:
    """Workspace for a new station / chart: the one asked for (if the user may use it),
    else the user's only workspace. On a brand-new installation with no workspaces
    at all, an open 'DEFAULT' workspace is created so the platform works out of the box."""
    if requested is not None:
        if not db.get(models.WorkspaceORM, requested):
            raise HTTPException(422, f"Workspace {requested} does not exist")
        if not can_access(db, user, requested):
            raise HTTPException(403, "You are not a member of that workspace")
        return requested
    if db.query(models.WorkspaceORM).count() == 0:
        w = models.WorkspaceORM(code="DEFAULT", name="Default workspace", dn_direction="Nominal",
                                open_to_all=True, created_by="system", created_at=now(),
                                remarks="Created automatically for the first station")
        db.add(w)
        db.flush()
        return w.id
    mine = visible_workspaces(db, user)
    if len(mine) == 1:
        return mine[0].id
    if not mine:
        raise HTTPException(403, "You are not a member of any workspace -- ask a Configuration Manager to add you")
    raise HTTPException(422, "Choose a workspace: " + ", ".join(w.code for w in mine))


def ensure_initial_workspace(db: Session) -> None:
    """Upgrade step: data created before workspaces existed goes into an 'SCR'
    (South Central Railway) workspace -- the zone of the existing Secunderabad
    division layouts -- and every existing user becomes a member so nobody loses
    access. No-op once any workspace exists or when there is nothing to move."""
    if db.query(models.WorkspaceORM).count():
        return
    orphans = db.query(models.StationORM).filter(models.StationORM.workspace_id.is_(None)).count() \
        + db.query(models.AllotmentChartORM).filter(models.AllotmentChartORM.workspace_id.is_(None)).count()
    if not orphans:
        return
    w = models.WorkspaceORM(code="SCR", name="South Central Railway", dn_direction="Nominal",
                            created_by="system", created_at=now(),
                            remarks="Created on upgrade for the existing layouts (SIP Down = Nominal)")
    db.add(w)
    db.flush()
    db.query(models.StationORM).filter(models.StationORM.workspace_id.is_(None)).update({"workspace_id": w.id})
    db.query(models.AllotmentChartORM).filter(models.AllotmentChartORM.workspace_id.is_(None)) \
        .update({"workspace_id": w.id})
    for u in db.query(models.UserORM).all():
        db.add(models.WorkspaceMemberORM(workspace_id=w.id, username=u.username, added_by="system", added_at=now()))
    db.commit()


def station_access(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)) -> None:
    """Router-level guard: any route with a {station_id} path parameter checks that
    the user may see the station's workspace."""
    sid = request.path_params.get("station_id")
    if sid is None:
        return
    try:
        st = db.get(models.StationORM, int(sid))
    except (TypeError, ValueError):
        return
    if st is not None and not can_access(db, user, st.workspace_id):
        raise HTTPException(403, "This station belongs to a workspace you are not a member of")


def require_member(db: Session, user, station, what: str) -> None:
    """The person a station is handed to (checker, designer) must be able to see it."""
    if not can_access(db, user, station.workspace_id):
        code = station.workspace.code if station.workspace is not None else "?"
        raise HTTPException(422, f"{user.username} is not a member of workspace {code}, so can't be {what}")
