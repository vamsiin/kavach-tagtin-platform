"""
Phase 6 -- BRD Section 7 stakeholder roles.

Project Manager:        portfolio dashboard, assign the designer (and, via
                        routers/workflow.py, reassign the checker).
Configuration Manager:  station version numbers (draft only, audited), baselines of
                        approved layouts, baseline-vs-current comparison.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..auth.permissions import require
from ..database import get_db
from ..documents import service as docsvc
from ..observations import rules as obsrules

router = APIRouter(tags=["management"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _station_or_404(station_id: int, db: Session) -> models.StationORM:
    st = db.get(models.StationORM, station_id)
    if not st:
        raise HTTPException(404, "Station not found")
    return st


def _log_change(db, station, field, before, after, reason, user):
    db.add(models.StationChangeORM(
        station_id=station.id, field=field, before=None if before is None else str(before),
        after=None if after is None else str(after), reason=(reason or "").strip() or None,
        changed_by=user.username, changed_by_role=user.role, changed_at=_now()))


# ---------------------------------------------------------------------------
# Dashboard (monitor)
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=schemas.DashboardOut)
def dashboard(db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    require(user, "dashboard.view")
    from ..rules.engine import run_all_checks
    from ..rules.store import active_rules
    from .workflow import _load_workflow_state
    rules = active_rules(db)
    now = datetime.now(timezone.utc)
    rows, by_status = [], {}
    for st in db.query(models.StationORM).order_by(models.StationORM.name).all():
        events = (db.query(models.WorkflowEventORM).filter_by(station_id=st.id)
                  .order_by(models.WorkflowEventORM.id.desc()).all())
        last = events[0] if events else None
        since = last.timestamp if last else (st.created_at.isoformat() if st.created_at else None)
        try:
            since_dt = datetime.fromisoformat(since) if since else None
            if since_dt and since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=timezone.utc)
            days = (now - since_dt).days if since_dt else None
        except ValueError:
            days = None
        rep = run_all_checks(st.to_domain(),
                             [e.to_domain() for e in st.elements], [t.to_domain() for t in st.tags],
                             [n.to_domain() for n in st.tins], rules=rules)
        blocking = obsrules.blocking_counts([(o.status, o.severity) for o in st.observations])
        current = docsvc.current_documents(db, st.id)
        missing = [c for c in docsvc.REQUIRED_DOC_TYPES if c not in current]
        state = _load_workflow_state(st, db)
        rail = st.railway_submissions[-1] if st.railway_submissions else None
        by_status[st.status] = by_status.get(st.status, 0) + 1
        rows.append(schemas.DashboardRow(
            id=st.id, name=st.name, kavach_station_id=st.kavach_station_id, status=st.status,
            layout_version=st.layout_version, assigned_designer=st.assigned_designer,
            assigned_checker=state.assigned_checker, created_by=st.created_by,
            days_in_status=days, last_action=last.action if last else None,
            last_actor=last.actor_username if last else None, last_at=last.timestamp if last else None,
            fail_count=rep.fail_count, warn_count=rep.warn_count,
            open_observations=blocking["unresolved"], unverified_observations=blocking["unverified"],
            missing_inputs=len(missing), tags=len(st.tags),
            railway_reference=rail.reference_no if rail else None,
            baselines=len(st.baselines)))
    return schemas.DashboardOut(stations=rows, by_status=by_status, total=len(rows))


# ---------------------------------------------------------------------------
# Assign designer (Project Manager)
# ---------------------------------------------------------------------------
@router.put("/stations/{station_id}/assign-designer", response_model=schemas.StationOut)
def assign_designer(station_id: int, payload: schemas.AssignDesignerRequest,
                    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    require(user, "assign.designer", "Assigning the designer")
    st = _station_or_404(station_id, db)
    new = (payload.designer_username or "").strip() or None
    if new:
        d = db.query(models.UserORM).filter_by(username=new).first()
        if not d or not d.is_active:
            raise HTTPException(404, f"No active user '{new}'")
        if d.role != "designer":
            raise HTTPException(422, f"'{new}' is a {d.role}, not a designer")
    if new == st.assigned_designer:
        raise HTTPException(422, "No change")
    _log_change(db, st, "assigned_designer", st.assigned_designer, new, payload.comment, user)
    st.assigned_designer = new
    db.commit()
    db.refresh(st)
    from .stations import _station_out
    return _station_out(st)


# ---------------------------------------------------------------------------
# Versions (Configuration Manager)
# ---------------------------------------------------------------------------
VERSION_FIELDS = ("kavach_version", "sip_version", "guideline_version", "sip_drawing_number")


@router.put("/stations/{station_id}/versions", response_model=schemas.StationOut)
def update_versions(station_id: int, payload: schemas.VersionUpdateRequest,
                    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    """FR-010 layout version X.Y.Z = KAVACH.SIP.Guideline. Before Phase 6 these could
    only be set when a station was created. Changing them re-labels the layout, so it
    is draft-only (an approved layout must be reopened first) and audited."""
    require(user, "station.versions", "Changing version numbers")
    st = _station_or_404(station_id, db)
    if st.status != "draft":
        raise HTTPException(409, f"Station is '{st.status}' -- versions can only change in draft "
                                 f"(reopen it first to start a new revision)")
    changed = 0
    for f in VERSION_FIELDS:
        v = getattr(payload, f)
        if v is None:
            continue
        v = v.strip() or None
        if v != getattr(st, f):
            _log_change(db, st, f, getattr(st, f), v, payload.reason, user)
            setattr(st, f, v)
            changed += 1
    if not changed:
        raise HTTPException(422, "No change")
    db.commit()
    db.refresh(st)
    from .stations import _station_out
    return _station_out(st)


@router.get("/stations/{station_id}/changes", response_model=list[schemas.StationChangeOut])
def station_changes(station_id: int, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    return (db.query(models.StationChangeORM).filter_by(station_id=station_id)
            .order_by(models.StationChangeORM.id.desc()).all())


# ---------------------------------------------------------------------------
# Baselines (Configuration Manager)
# ---------------------------------------------------------------------------
BASELINE_STATUSES = ("approved", "railway_submitted")


@router.get("/stations/{station_id}/baselines", response_model=list[schemas.BaselineOut])
def list_baselines(station_id: int, db: Session = Depends(get_db),
                   user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    return db.query(models.BaselineORM).filter_by(station_id=station_id).order_by(models.BaselineORM.id.desc()).all()


@router.post("/stations/{station_id}/baselines", response_model=schemas.BaselineOut)
def create_baseline(station_id: int, payload: schemas.BaselineCreate,
                    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    require(user, "baseline.create", "Creating a baseline")
    st = _station_or_404(station_id, db)
    if st.status not in BASELINE_STATUSES:
        raise HTTPException(409, f"Only an approved layout can be baselined (station is '{st.status}')")
    label = payload.label.strip()
    if db.query(models.BaselineORM).filter_by(station_id=station_id, label=label).first():
        raise HTTPException(409, f"Baseline '{label}' already exists for this station")
    from ..rules.engine import run_all_checks
    from ..rules.store import active_rules, config_version
    from .workflow import _layout_snapshot
    rep = run_all_checks(st.to_domain(), [e.to_domain() for e in st.elements],
                         [t.to_domain() for t in st.tags], [n.to_domain() for n in st.tins],
                         rules=active_rules(db))
    row = models.BaselineORM(
        station_id=st.id, label=label, layout_version=st.layout_version, station_status=st.status,
        notes=(payload.notes or "").strip() or None, layout_snapshot=_layout_snapshot(st, db),
        input_snapshot=docsvc.snapshot_current_inputs(db, st.id), checklist_version=config_version(db),
        verification_summary=json.dumps(rep.summary()), created_by=user.username, created_at=_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _index(snapshot: dict) -> dict[str, dict]:
    out = {}
    st = snapshot.get("station", {})
    out["station centre line"] = {"centre_line_m": st.get("centre_line_m")}
    for t in snapshot.get("tracks", []):
        out[f"line {t['name']}"] = t
    for a in snapshot.get("adjacent_stations", []):
        out[f"adjacent station {a['name']} ({a['side']})"] = a
    for e in snapshot.get("elements", []):
        out[f"element {e['element_ref']}"] = e
    for t in snapshot.get("tags", []):
        out[f"tag {t['tag_ref']}"] = t
    for n in snapshot.get("tins", []):
        out[f"TIN {n['tin_no']}"] = n
    return out


# Fields that identify rather than describe a row -- never reported as "changed".
_IGNORE = {"id", "linked_element_id", "source_document_id", "track_id", "to_track_id"}


@router.get("/stations/{station_id}/baselines/{baseline_id}/diff", response_model=schemas.BaselineDiffOut)
def baseline_diff(station_id: int, baseline_id: int, db: Session = Depends(get_db),
                  user: models.UserORM = Depends(get_current_user)):
    st = _station_or_404(station_id, db)
    b = db.query(models.BaselineORM).filter_by(id=baseline_id, station_id=station_id).first()
    if not b:
        raise HTTPException(404, "Baseline not found")
    from .workflow import _layout_snapshot
    old = _index(json.loads(b.layout_snapshot))
    new = _index(json.loads(_layout_snapshot(st, db)))
    rows = []
    for k in sorted(set(old) | set(new)):
        if k not in new:
            rows.append(schemas.DiffRow(item=k, change="removed"))
        elif k not in old:
            rows.append(schemas.DiffRow(item=k, change="added"))
        else:
            fields = [f"{f}: {old[k].get(f)!r} -> {new[k].get(f)!r}"
                      for f in sorted(set(old[k]) | set(new[k]))
                      if f not in _IGNORE and old[k].get(f) != new[k].get(f)]
            if fields:
                rows.append(schemas.DiffRow(item=k, change="changed", details=fields))
    inputs_then = {(i["doc_type"], i["revision"]) for i in json.loads(b.input_snapshot or "[]")}
    inputs_now = {(i["doc_type"], i["revision"]) for i in json.loads(docsvc.snapshot_current_inputs(db, st.id))}
    return schemas.BaselineDiffOut(
        baseline=b, current_layout_version=st.layout_version, current_status=st.status,
        rows=rows,
        inputs_changed=sorted(f"{t} r{r}" for t, r in inputs_now - inputs_then),
        identical=not rows and inputs_then == inputs_now and b.layout_version == st.layout_version)
