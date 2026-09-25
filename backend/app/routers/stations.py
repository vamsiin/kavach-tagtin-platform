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
def create_station(payload: schemas.StationCreateRequest, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user)):
    from ..auth.permissions import require
    require(user, "station.create", "Creating a station")
    existing = db.query(models.StationORM).filter_by(
        kavach_station_id=payload.kavach_station_id).first()
    if existing:
        raise HTTPException(400, f"Station with KAVACH ID {payload.kavach_station_id} already exists")
    from .tracks import _validate_adjacent
    from .tracks import _border_rows
    for a in payload.adjacent_stations:
        if any(b.track_id is not None for b in a.borders):
            raise HTTPException(422, "Add the station's lines first, then link borders to them")
        _validate_adjacent(a)
    station = models.StationORM(created_by=user.username, **payload.model_dump(exclude={"adjacent_stations"}))
    station.adjacent_stations = [models.AdjacentStationORM(**a.model_dump(exclude={"borders"}),
                                                           borders=_border_rows(a))
                                 for a in payload.adjacent_stations]
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
    # ...and anything else stored for the station (archived reports, Phase 4).
    import shutil
    from ..documents.service import upload_dir
    shutil.rmtree(upload_dir() / f"station_{station_id}", ignore_errors=True)
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


# Fields added after the first clients shipped: only changed when the client sends
# them, so an older client can't wipe them on every edit.
_SEND_TO_CHANGE = ("source_document_id", "track_id", "to_track_id", "lc_class", "lc_manning")


def _update_fields(payload) -> dict:
    """PUT semantics for register rows, with one exception: fields in _SEND_TO_CHANGE
    (traceability link, track placement, LC details) are only changed when the client
    explicitly sends them."""
    data = payload.model_dump()
    for f in _SEND_TO_CHANGE:
        if f in data and f not in payload.model_fields_set:
            data.pop(f)
    return data


def _validate_track_ref(station_id: int, track_id: int | None, db: Session, label: str = "track_id") -> None:
    if track_id is None:
        return
    if not db.query(models.TrackORM).filter_by(id=track_id, station_id=station_id).first():
        raise HTTPException(422, f"{label} {track_id} is not a line of this station")


def _clean_element(station_id: int, data: dict, el: "models.ElementORM | None", db: Session) -> dict:
    """Type-specific element fields: LC details only on LC gates, the diverging line
    only on points. Values that don't apply to the type are cleared, not rejected,
    so changing an element's type in the form never leaves stale data behind."""
    from ..domain import LC_CLASSES, LC_GATE, LC_MANNING, POINTS
    etype = data.get("element_type")
    track = data.get("track_id", el.track_id if el else None)
    if etype != LC_GATE:
        for f in ("lc_class", "lc_manning"):
            if f in data or (el is not None and getattr(el, f) is not None):
                data[f] = None
    if etype != POINTS and ("to_track_id" in data or (el is not None and el.to_track_id is not None)):
        data["to_track_id"] = None
    if data.get("lc_class") is not None and data["lc_class"] not in LC_CLASSES:
        raise HTTPException(422, f"lc_class must be one of {LC_CLASSES}")
    if data.get("lc_manning") is not None and data["lc_manning"] not in LC_MANNING:
        raise HTTPException(422, f"lc_manning must be one of {LC_MANNING}")
    _validate_track_ref(station_id, data.get("track_id"), db)
    _validate_track_ref(station_id, data.get("to_track_id"), db, "to_track_id")
    to_track = data.get("to_track_id", el.to_track_id if el else None)
    if to_track is not None and to_track == track:
        raise HTTPException(422, "Points must lead to a different line from the one they are on")
    return data


def _require_register_editor(user: models.UserORM, station: models.StationORM) -> None:
    """Phase 6: only designers/admins edit registers (before this, any logged-in role
    could, including checkers and approvers), and when a Project Manager has assigned
    a designer, only that designer (or an admin)."""
    from ..auth.permissions import require
    require(user, "registers.edit", "Editing the registers")
    if user.role != "admin" and station.assigned_designer and station.assigned_designer != user.username:
        raise HTTPException(403, f"This station is assigned to designer '{station.assigned_designer}' "
                                 f"-- only they (or an admin) can edit it")


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
    _require_register_editor(user, station)
    _validate_source_document(station_id, payload.source_document_id, db)
    el = models.ElementORM(station_id=station_id, **_clean_element(station_id, payload.model_dump(), None, db))
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
    _require_register_editor(user, station)
    el = _get_element_or_404(station_id, element_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    for field, value in _clean_element(station_id, _update_fields(payload), el, db).items():
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
    _require_register_editor(user, station)
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
    _require_register_editor(user, station)
    _validate_source_document(station_id, payload.source_document_id, db)
    _validate_track_ref(station_id, payload.track_id, db)
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
    _require_register_editor(user, station)
    tag = _get_tag_or_404(station_id, tag_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    _validate_track_ref(station_id, payload.track_id, db)
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
    _require_register_editor(user, station)
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
    _require_register_editor(user, station)
    _validate_source_document(station_id, payload.source_document_id, db)
    _validate_track_ref(station_id, payload.track_id, db)
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
    _require_register_editor(user, station)
    tin = _get_tin_or_404(station_id, tin_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    _validate_track_ref(station_id, payload.track_id, db)
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
    _require_register_editor(user, station)
    tin = _get_tin_or_404(station_id, tin_id, db)
    db.delete(tin)
    db.commit()
    return None
