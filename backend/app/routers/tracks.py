"""Track model (step 2 of the Annexure-H plan): the station's named lines, its
neighbouring stations with their border lines, and the station centre line.

Same editing rules as the other registers: Draft only, designers (or the assigned
designer) and admins only."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..domain import LINE_CONFIGS, TRACK_TYPES
from .stations import (_get_station_or_404, _require_editable, _require_register_editor,
                       _station_out, _validate_source_document)

router = APIRouter(prefix="/stations", tags=["tracks"])


def _editable_station(station_id: int, db: Session, user) -> models.StationORM:
    station = _get_station_or_404(station_id, db)
    _require_editable(station)
    _require_register_editor(user, station)
    return station


# ---------------------------------------------------------------------------
# Station centre line (H2.4 / H2.28)
# ---------------------------------------------------------------------------
@router.put("/{station_id}/centre-line", response_model=schemas.StationOut)
def set_centre_line(station_id: int, payload: schemas.CentreLineUpdate, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    station = _editable_station(station_id, db, user)
    station.centre_line_m = payload.centre_line_m
    db.commit()
    db.refresh(station)
    return _station_out(station)


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------
def _validate_track(station_id: int, payload: schemas.TrackCreate, db: Session, track_id: int | None = None):
    if payload.track_type not in TRACK_TYPES:
        raise HTTPException(422, f"track_type must be one of {TRACK_TYPES}")
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, "Track name is required")
    from ..domain import LINE_TYPES, guess_line_type
    if payload.line_type is None or not str(payload.line_type).strip():
        payload.line_type = guess_line_type(name)
    payload.line_type = str(payload.line_type).strip().upper()
    if payload.line_type not in LINE_TYPES:
        raise HTTPException(422, f"line_type must be one of {', '.join(LINE_TYPES)}")
    from ..chainage import normalise_section
    payload.start_m, payload.end_m, _ = normalise_section(payload.start_m, payload.end_m, payload.direction,
                                                          f"Line '{name}'")
    clash = [t for t in db.query(models.TrackORM).filter_by(station_id=station_id).all()
             if t.name.strip().lower() == name.lower() and t.id != track_id]
    if clash:
        raise HTTPException(409, f"This station already has a line named '{clash[0].name}'")
    _validate_source_document(station_id, payload.source_document_id, db)


@router.get("/{station_id}/tracks", response_model=list[schemas.TrackOut])
def list_tracks(station_id: int, db: Session = Depends(get_db),
                user: models.UserORM = Depends(get_current_user)):
    return _get_station_or_404(station_id, db).tracks


@router.post("/{station_id}/tracks", response_model=schemas.TrackOut)
def add_track(station_id: int, payload: schemas.TrackCreate, db: Session = Depends(get_db),
              user: models.UserORM = Depends(get_current_user)):
    _editable_station(station_id, db, user)
    _validate_track(station_id, payload, db)
    data = payload.model_dump()
    data["name"] = data["name"].strip()
    tr = models.TrackORM(station_id=station_id, **data)
    db.add(tr)
    db.commit()
    db.refresh(tr)
    return tr


def _get_track_or_404(station_id: int, track_id: int, db: Session) -> models.TrackORM:
    tr = db.query(models.TrackORM).filter_by(id=track_id, station_id=station_id).first()
    if not tr:
        raise HTTPException(404, "Track not found")
    return tr


@router.put("/{station_id}/tracks/{track_id}", response_model=schemas.TrackOut)
def update_track(station_id: int, track_id: int, payload: schemas.TrackCreate,
                 db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    _editable_station(station_id, db, user)
    tr = _get_track_or_404(station_id, track_id, db)
    _validate_track(station_id, payload, db, track_id)
    data = payload.model_dump()
    data["name"] = data["name"].strip()
    if "source_document_id" not in payload.model_fields_set:
        data.pop("source_document_id")
    for k, v in data.items():
        setattr(tr, k, v)
    db.commit()
    db.refresh(tr)
    return tr


@router.delete("/{station_id}/tracks/{track_id}", status_code=204)
def delete_track(station_id: int, track_id: int, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    """Elements, tags and TINs on the line are kept and simply unassigned, the same
    way deleting an element unlinks its tags."""
    _editable_station(station_id, db, user)
    tr = _get_track_or_404(station_id, track_id, db)
    for model in (models.ElementORM, models.TagORM, models.TINORM):
        db.query(model).filter_by(station_id=station_id, track_id=track_id).update({"track_id": None})
    db.query(models.ElementORM).filter_by(station_id=station_id, to_track_id=track_id).update({"to_track_id": None})
    for b in db.query(models.StationBorderORM).filter_by(track_id=track_id).all():
        b.track_id = None
    db.delete(tr)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Adjacent stations and border lines (H2.16, H2.22)
# ---------------------------------------------------------------------------
def _validate_adjacent(payload: schemas.AdjacentStationCreate, station_id: int | None = None,
                       db: Session | None = None):
    if not payload.name.strip():
        raise HTTPException(422, "Adjacent station name is required")
    if not payload.side.strip():
        raise HTTPException(422, "Side (direction towards the adjacent station) is required")
    if payload.line_config is not None and payload.line_config not in LINE_CONFIGS:
        raise HTTPException(422, f"line_config must be one of {LINE_CONFIGS}")
    tracks = {t.id: t for t in db.query(models.TrackORM).filter_by(station_id=station_id).all()} if db else {}
    for b in payload.borders:
        # the label defaults to this station's line name when a line is picked
        if not (b.line_label or "").strip() and b.track_id in tracks:
            b.line_label = tracks[b.track_id].name
        if b.border_m is None or b.border_m < 0:
            raise HTTPException(422, "Border chainage must be a positive number")
    mapped = [b.track_id for b in payload.borders if b.track_id is not None]
    if len(set(mapped)) != len(mapped):
        raise HTTPException(422, "Each line of this station can cross the border with a neighbour only once")
    # line-wise mapping decides single / double / multiple line (H2.22); the stored
    # value is only used as given when no lines are mapped (older data / API clients)
    from ..domain import line_config_from_borders
    derived = line_config_from_borders(payload.borders)
    if derived:
        payload.line_config = derived
    if payload.distance_m is not None and payload.distance_m < 0:
        raise HTTPException(422, "Distance cannot be negative")
    labels = [b.line_label.strip().lower() for b in payload.borders]
    if any(not x for x in labels):
        raise HTTPException(422, "Each border needs the line it is on: pick this station's line")
    if len(set(labels)) != len(labels):
        raise HTTPException(422, "Only one border per line for each adjacent station")
    for b in payload.borders:
        if b.track_id is not None and (db is None or not db.query(models.TrackORM)
                                       .filter_by(id=b.track_id, station_id=station_id).first()):
            raise HTTPException(422, f"track_id {b.track_id} is not a line of this station")


def _border_rows(payload: schemas.AdjacentStationCreate) -> list[models.StationBorderORM]:
    return [models.StationBorderORM(line_label=b.line_label.strip(), border_m=b.border_m,
                                    border_tag_ref=(b.border_tag_ref or "").strip() or None,
                                    track_id=b.track_id,
                                    neighbour_line=(b.neighbour_line or "").strip() or None)
            for b in payload.borders]


@router.get("/{station_id}/adjacent-stations", response_model=list[schemas.AdjacentStationOut])
def list_adjacent(station_id: int, db: Session = Depends(get_db),
                  user: models.UserORM = Depends(get_current_user)):
    return _get_station_or_404(station_id, db).adjacent_stations


@router.post("/{station_id}/adjacent-stations", response_model=schemas.AdjacentStationOut)
def add_adjacent(station_id: int, payload: schemas.AdjacentStationCreate, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    _editable_station(station_id, db, user)
    _validate_adjacent(payload, station_id, db)
    row = models.AdjacentStationORM(station_id=station_id, **payload.model_dump(exclude={"borders"}))
    row.borders = _border_rows(payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_adjacent_or_404(station_id: int, adj_id: int, db: Session) -> models.AdjacentStationORM:
    row = db.query(models.AdjacentStationORM).filter_by(id=adj_id, station_id=station_id).first()
    if not row:
        raise HTTPException(404, "Adjacent station not found")
    return row


@router.put("/{station_id}/adjacent-stations/{adj_id}", response_model=schemas.AdjacentStationOut)
def update_adjacent(station_id: int, adj_id: int, payload: schemas.AdjacentStationCreate,
                    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    _editable_station(station_id, db, user)
    row = _get_adjacent_or_404(station_id, adj_id, db)
    _validate_adjacent(payload, station_id, db)
    if "borders" not in payload.model_fields_set:
        from ..domain import line_config_from_borders
        payload.line_config = (line_config_from_borders(row.borders)
                               or (payload.line_config if "line_config" in payload.model_fields_set else row.line_config))
    for k, v in payload.model_dump(exclude={"borders"}).items():
        setattr(row, k, v)
    if "borders" in payload.model_fields_set:   # replace the per-line borders only when sent
        row.borders = _border_rows(payload)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{station_id}/adjacent-stations/{adj_id}", status_code=204)
def delete_adjacent(station_id: int, adj_id: int, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    _editable_station(station_id, db, user)
    db.delete(_get_adjacent_or_404(station_id, adj_id, db))
    db.commit()
    return None
