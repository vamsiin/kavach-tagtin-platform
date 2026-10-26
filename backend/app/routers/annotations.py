"""Drawing annotations: track circuit names, section notes and site features shown on the
layout sheet (sand hump, tower wagon shed, "Axle Counter Section" ...). Not verified, not
part of the Annexure-H checks -- they only make the generated drawing match the manual one.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..domain import ANNOTATION_KINDS
from .stations import _get_station_or_404, _require_editable, _require_register_editor, _validate_track_ref

router = APIRouter(prefix="/stations", tags=["annotations"])


def _clean(station: models.StationORM, data: dict, db: Session) -> dict:
    if data["kind"] not in ANNOTATION_KINDS:
        raise HTTPException(422, f"Kind must be one of {ANNOTATION_KINDS}")
    data["label"] = (data.get("label") or "").strip()
    if not data["label"]:
        raise HTTPException(422, "Label is required")
    if data["start_m"] is None or data["start_m"] < 0:
        raise HTTPException(422, "Start must be a chainage in metres (0 or more)")
    if data.get("end_m") is not None and data["end_m"] < 0:
        raise HTTPException(422, "End must be a chainage in metres (0 or more)")
    if data["kind"] in ("Track circuit", "Section note") and data.get("end_m") is None:
        raise HTTPException(422, f"A {data['kind'].lower()} covers a stretch of the line: give its end chainage")
    if data.get("track_id") is None:
        raise HTTPException(422, "Pick the line it is on")
    _validate_track_ref(station.id, data["track_id"], db)
    return data


def _get_or_404(station_id: int, ann_id: int, db: Session) -> models.AnnotationORM:
    a = db.query(models.AnnotationORM).filter_by(id=ann_id, station_id=station_id).first()
    if a is None:
        raise HTTPException(404, "Annotation not found")
    return a


@router.get("/{station_id}/annotations", response_model=list[schemas.AnnotationOut])
def list_annotations(station_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_station_or_404(station_id, db).annotations


@router.post("/{station_id}/annotations", response_model=schemas.AnnotationOut, status_code=201)
def add_annotation(station_id: int, payload: schemas.AnnotationCreate, db: Session = Depends(get_db),
                   user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    a = models.AnnotationORM(station_id=station_id, **_clean(st, payload.model_dump(), db))
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.put("/{station_id}/annotations/{ann_id}", response_model=schemas.AnnotationOut)
def update_annotation(station_id: int, ann_id: int, payload: schemas.AnnotationCreate,
                      db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    a = _get_or_404(station_id, ann_id, db)
    for k, v in _clean(st, payload.model_dump(), db).items():
        setattr(a, k, v)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{station_id}/annotations/{ann_id}", status_code=204)
def delete_annotation(station_id: int, ann_id: int, db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    db.delete(_get_or_404(station_id, ann_id, db))
    db.commit()
