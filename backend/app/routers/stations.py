from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth.deps import get_current_user

router = APIRouter(prefix="/stations", tags=["stations"])


def _station_out(s: models.StationORM) -> schemas.StationOut:
    """Uses Pydantic's from_attributes to pull every field straight off the ORM
    object by name, rather than listing each field by hand -- see StationORM's
    layout_version property docstring in models.py for why (this used to be a
    manual field list and silently dropped fields twice)."""
    return schemas.StationOut.model_validate(s, from_attributes=True)


@router.post("", response_model=schemas.StationOut)
def create_station(payload: schemas.StationCreate, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    existing = db.query(models.StationORM).filter_by(
        kavach_station_id=payload.kavach_station_id).first()
    if existing:
        raise HTTPException(400, f"Station with KAVACH ID {payload.kavach_station_id} already exists")
    station = models.StationORM(created_by=user.username, **payload.model_dump())
    db.add(station)
    db.commit()
    db.refresh(station)
    return _station_out(station)


@router.get("", response_model=list[schemas.StationOut])
def list_stations(db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    return [_station_out(s) for s in db.query(models.StationORM).all()]


@router.get("/{station_id}", response_model=schemas.StationOut)
def get_station(station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    return _station_out(station)


@router.delete("/{station_id}", status_code=204)
def delete_station(
    station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user),
):
    """Deletion is irreversible and cascades to every Element, Tag, TIN, and the
    full workflow audit history for this station (cascade configured at the ORM
    relationship level in models.py).

    Who can delete:
      - An admin can delete ANY station, in any status.
      - The station's creator can delete it themselves, but ONLY while it's still
        'draft' -- once it's been submitted, the creator loses unilateral deletion
        rights over it (mirrors the same draft-only philosophy as register edits:
        once something is under review, nobody should be able to make it vanish
        without going through 'request changes' or an admin).
      - Everyone else gets a 403, including other designers/checkers/approvers who
        didn't create this station.

    Stations created before this field existed have created_by=None (an older
    database upgraded in place via the startup schema migration) -- those can only
    be deleted by an admin, since there's no creator to defer to.
    """
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")

    is_admin = user.role == "admin"
    is_creator = station.created_by is not None and station.created_by == user.username

    if is_admin:
        pass  # admins can always delete
    elif is_creator and station.status == "draft":
        pass  # creators can delete their own drafts
    elif is_creator:
        raise HTTPException(
            403,
            f"You created this station, but it is '{station.status}', not 'draft' "
            f"-- only an admin can delete a station once it has left Draft.",
        )
    else:
        raise HTTPException(
            403,
            "Only an admin, or the designer who created this station (while it's "
            "still in Draft), can delete it.",
        )

    # Input-document FILES live on disk, not in the DB -- the cascade removes the
    # rows, so collect the files first and remove them after a successful commit.
    from ..documents.service import delete_file_quietly
    docs = list(station.documents)
    db.delete(station)
    db.commit()
    for d in docs:
        delete_file_quietly(d)
    return None


def _get_station_or_404(station_id: int, db: Session) -> models.StationORM:
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    return station


def _validate_source_document(station_id: int, doc_id: int | None, db: Session) -> None:
    """source_document_id must point at an input document of THIS station --
    otherwise a tag could claim provenance from another station's SIP."""
    if doc_id is None:
        return
    doc = db.query(models.InputDocumentORM).filter_by(id=doc_id, station_id=station_id).first()
    if not doc:
        raise HTTPException(422, f"source_document_id {doc_id} is not an input document "
                                 f"of this station")


def _update_fields(payload) -> dict:
    """PUT semantics for register rows, with one exception: source_document_id is
    only changed when the client explicitly sends it. Older clients that don't
    know about the field must not silently wipe a row's traceability link on
    every edit."""
    data = payload.model_dump()
    if "source_document_id" not in payload.model_fields_set:
        data.pop("source_document_id", None)
    return data


def _require_editable(station: models.StationORM) -> None:
    """Registers (Elements/Tags/TINs) are only mutable while a station is in
    'draft'. Once submitted, edits must go through 'request changes' (which
    resets status to draft) rather than being made silently mid-review -- a
    Checker reviewing a submitted layout should be reviewing something stable.
    Applies to create, update, AND delete of register rows."""
    if station.status != "draft":
        raise HTTPException(
            409,
            f"Station is '{station.status}', not 'draft' -- registers can only be "
            f"edited in draft. Use request-changes to reopen for editing.",
        )


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------
@router.post("/{station_id}/elements", response_model=schemas.ElementOut)
def add_element(station_id: int, payload: schemas.ElementCreate, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    from ..domain import ELEMENT_TYPES
    if payload.element_type not in ELEMENT_TYPES:
        raise HTTPException(422, f"element_type must be one of {ELEMENT_TYPES}")
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    _validate_source_document(station_id, payload.source_document_id, db)
    el = models.ElementORM(station_id=station_id, **payload.model_dump())
    db.add(el)
    db.commit()
    db.refresh(el)
    return el


@router.get("/{station_id}/elements", response_model=list[schemas.ElementOut])
def list_elements(station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    _get_station_or_404(station_id, db)
    return db.query(models.ElementORM).filter_by(station_id=station_id).all()


def _get_element_or_404(station_id: int, element_id: int, db: Session) -> models.ElementORM:
    el = db.query(models.ElementORM).filter_by(id=element_id, station_id=station_id).first()
    if not el:
        raise HTTPException(404, "Element not found")
    return el


@router.put("/{station_id}/elements/{element_id}", response_model=schemas.ElementOut)
def update_element(
    station_id: int, element_id: int, payload: schemas.ElementCreate,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    from ..domain import ELEMENT_TYPES
    if payload.element_type not in ELEMENT_TYPES:
        raise HTTPException(422, f"element_type must be one of {ELEMENT_TYPES}")
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    el = _get_element_or_404(station_id, element_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    for field, value in _update_fields(payload).items():
        setattr(el, field, value)
    db.commit()
    db.refresh(el)
    return el


@router.delete("/{station_id}/elements/{element_id}", status_code=204)
def delete_element(
    station_id: int, element_id: int,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    el = _get_element_or_404(station_id, element_id, db)
    # Tags that reference this element as linked_element_id are not cascade-deleted
    # (the FK has no ON DELETE CASCADE) -- unlink them rather than leaving a dangling
    # reference, since a Tag pointing at a nonexistent Element would silently break
    # the H2.6/H2.7/H2.9 checks that join on linked_element_id.
    orphaned_tags = db.query(models.TagORM).filter_by(
        station_id=station_id, linked_element_id=element_id
    ).all()
    for t in orphaned_tags:
        t.linked_element_id = None
    db.delete(el)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
@router.post("/{station_id}/tags", response_model=schemas.TagOut)
def add_tag(station_id: int, payload: schemas.TagCreate, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    from ..domain import TAG_TYPES
    if payload.tag_type not in TAG_TYPES:
        raise HTTPException(422, f"tag_type must be one of {TAG_TYPES}")
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    _validate_source_document(station_id, payload.source_document_id, db)
    tag = models.TagORM(station_id=station_id, **payload.model_dump())
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.get("/{station_id}/tags", response_model=list[schemas.TagOut])
def list_tags(station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    _get_station_or_404(station_id, db)
    return db.query(models.TagORM).filter_by(station_id=station_id).all()


def _get_tag_or_404(station_id: int, tag_id: int, db: Session) -> models.TagORM:
    tag = db.query(models.TagORM).filter_by(id=tag_id, station_id=station_id).first()
    if not tag:
        raise HTTPException(404, "Tag not found")
    return tag


@router.put("/{station_id}/tags/{tag_id}", response_model=schemas.TagOut)
def update_tag(
    station_id: int, tag_id: int, payload: schemas.TagCreate,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    from ..domain import TAG_TYPES
    if payload.tag_type not in TAG_TYPES:
        raise HTTPException(422, f"tag_type must be one of {TAG_TYPES}")
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    tag = _get_tag_or_404(station_id, tag_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    for field, value in _update_fields(payload).items():
        setattr(tag, field, value)
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/{station_id}/tags/{tag_id}", status_code=204)
def delete_tag(
    station_id: int, tag_id: int,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    tag = _get_tag_or_404(station_id, tag_id, db)
    db.delete(tag)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# TINs
# ---------------------------------------------------------------------------
@router.post("/{station_id}/tins", response_model=schemas.TINOut)
def add_tin(station_id: int, payload: schemas.TINCreate, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    _validate_source_document(station_id, payload.source_document_id, db)
    tin = models.TINORM(station_id=station_id, **payload.model_dump())
    db.add(tin)
    db.commit()
    db.refresh(tin)
    return tin


@router.get("/{station_id}/tins", response_model=list[schemas.TINOut])
def list_tins(station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    _get_station_or_404(station_id, db)
    return db.query(models.TINORM).filter_by(station_id=station_id).all()


def _get_tin_or_404(station_id: int, tin_id: int, db: Session) -> models.TINORM:
    tin = db.query(models.TINORM).filter_by(id=tin_id, station_id=station_id).first()
    if not tin:
        raise HTTPException(404, "TIN not found")
    return tin


@router.put("/{station_id}/tins/{tin_id}", response_model=schemas.TINOut)
def update_tin(
    station_id: int, tin_id: int, payload: schemas.TINCreate,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    tin = _get_tin_or_404(station_id, tin_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    for field, value in _update_fields(payload).items():
        setattr(tin, field, value)
    db.commit()
    db.refresh(tin)
    return tin


@router.delete("/{station_id}/tins/{tin_id}", status_code=204)
def delete_tin(
    station_id: int, tin_id: int,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    tin = _get_tin_or_404(station_id, tin_id, db)
    db.delete(tin)
    db.commit()
    return None
