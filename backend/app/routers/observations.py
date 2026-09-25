"""
BRD FR-008: review observations -- raise, resolve, close, reopen, withdraw, comment.
Lifecycle rules live in app/observations/rules.py; this is the HTTP/DB adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..observations import rules as obs

router = APIRouter(prefix="/stations", tags=["observations"])

_SUBJECT_MODELS = {
    "tag": (models.TagORM, "tag_ref"),
    "element": (models.ElementORM, "element_ref"),
    "tin": (models.TINORM, None),
    "document": (models.InputDocumentORM, None),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _station_or_404(station_id: int, db: Session) -> models.StationORM:
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    return station


def _obs_or_404(station_id: int, obs_id: int, db: Session) -> models.ObservationORM:
    o = db.query(models.ObservationORM).filter_by(id=obs_id, station_id=station_id).first()
    if not o:
        raise HTTPException(404, "Observation not found")
    return o


def _subject_label(kind: str, row) -> str:
    if kind == "tin":
        return f"TIN {row.tin_no}"
    if kind == "document":
        return f"{row.doc_type} rev {row.revision}"
    return getattr(row, _SUBJECT_MODELS[kind][1])


def _resolve_subject(station_id: int, payload: schemas.ObservationCreate,
                     db: Session) -> tuple[int | None, str | None]:
    kind = payload.subject_kind
    if kind == "station":
        return None, None
    model, ref_col = _SUBJECT_MODELS[kind]
    row = None
    if payload.subject_id is not None:
        row = db.query(model).filter_by(id=payload.subject_id, station_id=station_id).first()
    elif payload.subject_ref and ref_col:
        row = db.query(model).filter(model.station_id == station_id,
                                     getattr(model, ref_col) == payload.subject_ref).first()
    if row is None:
        raise HTTPException(422, f"No {kind} matching "
                                 f"{payload.subject_id or payload.subject_ref!r} on this station")
    return row.id, _subject_label(kind, row)


def _out(o: models.ObservationORM, user: models.UserORM, db: Session) -> schemas.ObservationOut:
    out = schemas.ObservationOut.model_validate(o, from_attributes=True)
    out.label = f"OBS-{o.obs_no:03d}"
    if o.subject_kind in _SUBJECT_MODELS and o.subject_id is not None:
        model = _SUBJECT_MODELS[o.subject_kind][0]
        out.subject_exists = db.get(model, o.subject_id) is not None
    out.allowed_actions = obs.allowed_actions(
        obs.ObsState(o.status, o.raised_by, o.resolved_by), user.username, user.role)
    return out


def observation_summary(db: Session, station_id: int) -> dict:
    rows = db.query(models.ObservationORM.status, models.ObservationORM.severity).filter_by(
        station_id=station_id).all()
    by_status = {s: 0 for s in obs.STATUSES}
    for st, _ in rows:
        by_status[st] = by_status.get(st, 0) + 1
    return {"total": len(rows), "by_status": by_status,
            **obs.blocking_counts([(st, sev) for st, sev in rows])}


# ---------------------------------------------------------------------------
@router.get("/{station_id}/observations", response_model=schemas.ObservationListOut)
def list_observations(station_id: int, status: str | None = None,
                      db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    q = db.query(models.ObservationORM).filter_by(station_id=station_id)
    if status:
        q = q.filter(models.ObservationORM.status.in_(status.split(",")))
    items = q.order_by(models.ObservationORM.obs_no.asc()).all()
    return schemas.ObservationListOut(observations=[_out(o, user, db) for o in items],
                                      summary=observation_summary(db, station_id))


@router.post("/{station_id}/observations", response_model=schemas.ObservationOut)
def raise_observation(station_id: int, payload: schemas.ObservationCreate,
                      db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    if not obs.can_raise(user.role):
        raise HTTPException(403, f"Only reviewers ({', '.join(obs.REVIEWER_ROLES)}) can raise "
                                 f"observations (you are '{user.role}')")
    if station.status == "railway_submitted":
        raise HTTPException(409, "Station has been submitted to the Railway -- reopen it first")
    if payload.severity not in obs.SEVERITIES:
        raise HTTPException(422, f"severity must be one of {obs.SEVERITIES}")
    if payload.category and payload.category not in obs.CATEGORIES:
        raise HTTPException(422, f"category must be one of {obs.CATEGORIES}")
    if payload.subject_kind not in obs.SUBJECT_KINDS:
        raise HTTPException(422, f"subject_kind must be one of {obs.SUBJECT_KINDS}")
    subject_id, subject_ref = _resolve_subject(station_id, payload, db)

    now = _now()
    next_no = (db.query(func.max(models.ObservationORM.obs_no))
               .filter_by(station_id=station_id).scalar() or 0) + 1
    o = models.ObservationORM(
        station_id=station_id, obs_no=next_no, description=payload.description.strip(),
        severity=payload.severity, category=payload.category,
        clause=(payload.clause or "").strip() or None,
        subject_kind=payload.subject_kind, subject_id=subject_id, subject_ref=subject_ref,
        status=obs.OPEN, raised_by=user.username, raised_by_role=user.role, raised_at=now,
        raised_at_status=station.status, layout_version=station.layout_version,
    )
    o.comments.append(models.ObservationCommentORM(
        action="raise", from_status=None, to_status=obs.OPEN, author=user.username,
        author_role=user.role, text=o.description, created_at=now))
    db.add(o)
    db.commit()
    db.refresh(o)
    return _out(o, user, db)


def _act(station_id: int, obs_id: int, action: str, comment: str,
         db: Session, user: models.UserORM) -> schemas.ObservationOut:
    station = _station_or_404(station_id, db)
    if station.status == "railway_submitted" and action != obs.COMMENT:
        raise HTTPException(409, "Station has been submitted to the Railway -- reopen it first")
    o = _obs_or_404(station_id, obs_id, db)
    try:
        new_status = obs.apply(obs.ObsState(o.status, o.raised_by, o.resolved_by),
                               action, user.username, user.role, comment)
    except obs.ObservationError as e:
        raise HTTPException(409, str(e))
    now = _now()
    o.comments.append(models.ObservationCommentORM(
        action=action, from_status=o.status, to_status=new_status, author=user.username,
        author_role=user.role, text=comment.strip() or None, created_at=now))
    if action == obs.RESOLVE:
        o.resolved_by, o.resolved_at = user.username, now
    elif action == obs.CLOSE:
        o.closed_by, o.closed_at = user.username, now
    elif action == obs.REOPEN:
        o.resolved_by = o.resolved_at = o.closed_by = o.closed_at = None
    o.status = new_status
    db.commit()
    db.refresh(o)
    return _out(o, user, db)


@router.post("/{station_id}/observations/{obs_id}/resolve", response_model=schemas.ObservationOut)
def resolve_observation(station_id: int, obs_id: int, payload: schemas.ObservationActionRequest,
                        db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return _act(station_id, obs_id, obs.RESOLVE, payload.comment, db, user)


@router.post("/{station_id}/observations/{obs_id}/close", response_model=schemas.ObservationOut)
def close_observation(station_id: int, obs_id: int, payload: schemas.ObservationActionRequest,
                      db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return _act(station_id, obs_id, obs.CLOSE, payload.comment, db, user)


@router.post("/{station_id}/observations/{obs_id}/reopen", response_model=schemas.ObservationOut)
def reopen_observation(station_id: int, obs_id: int, payload: schemas.ObservationActionRequest,
                       db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return _act(station_id, obs_id, obs.REOPEN, payload.comment, db, user)


@router.post("/{station_id}/observations/{obs_id}/withdraw", response_model=schemas.ObservationOut)
def withdraw_observation(station_id: int, obs_id: int, payload: schemas.ObservationActionRequest,
                         db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return _act(station_id, obs_id, obs.WITHDRAW, payload.comment, db, user)


@router.post("/{station_id}/observations/{obs_id}/comments", response_model=schemas.ObservationOut)
def comment_observation(station_id: int, obs_id: int, payload: schemas.ObservationActionRequest,
                        db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    return _act(station_id, obs_id, obs.COMMENT, payload.comment, db, user)
