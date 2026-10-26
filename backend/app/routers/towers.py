"""Input 5 -- Stationary KAVACH tower locations and the tower RSSI survey.

  /stations/{id}/towers          the towers register (this station's towers, and the
                                 adjacent stations' towers the border survey measured)
  /stations/{id}/rssi            RSSI readings (loaded by CSV: Registers -> Upload CSV)
  /stations/{id}/rssi/summary    per tower: readings, km range, strongest / weakest; and
                                 the border-tag coverage verdict (BRD BR-005)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from .stations import (_get_station_or_404, _require_editable, _require_register_editor,
                       _validate_source_document, _validate_track_ref)

router = APIRouter(prefix="/stations", tags=["towers"])


def _clean_tower(station: models.StationORM, data: dict, db: Session, tower_id: int | None = None) -> dict:
    data["tower_ref"] = (data.get("tower_ref") or "").strip()
    if not data["tower_ref"]:
        raise HTTPException(422, "Tower ref is required")
    if data.get("location_m") is None or data["location_m"] < 0:
        raise HTTPException(422, "Tower location must be a chainage in metres (0 or more)")
    owner = (data.get("owner") or "").strip()
    data["owner"] = None if not owner or owner.lower() == station.name.strip().lower() else owner
    if data.get("height_m") is not None and data["height_m"] <= 0:
        raise HTTPException(422, "Tower height must be positive")
    _validate_track_ref(station.id, data.get("track_id"), db)
    clash = db.query(models.TowerORM).filter(models.TowerORM.station_id == station.id,
                                             models.TowerORM.tower_ref == data["tower_ref"])
    if tower_id is not None:
        clash = clash.filter(models.TowerORM.id != tower_id)
    if clash.first():
        raise HTTPException(422, f"Tower {data['tower_ref']} is already in this station's register")
    return data


@router.get("/{station_id}/towers", response_model=list[schemas.TowerOut])
def list_towers(station_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    return _get_station_or_404(station_id, db).towers


@router.post("/{station_id}/towers", response_model=schemas.TowerOut, status_code=201)
def add_tower(station_id: int, payload: schemas.TowerCreate, db: Session = Depends(get_db),
              user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    _validate_source_document(station_id, payload.source_document_id, db)
    t = models.TowerORM(station_id=station_id, **_clean_tower(st, payload.model_dump(), db))
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _tower_or_404(station_id: int, tower_id: int, db: Session) -> models.TowerORM:
    t = db.query(models.TowerORM).filter_by(id=tower_id, station_id=station_id).first()
    if t is None:
        raise HTTPException(404, "Tower not found")
    return t


@router.put("/{station_id}/towers/{tower_id}", response_model=schemas.TowerOut)
def update_tower(station_id: int, tower_id: int, payload: schemas.TowerCreate, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    t = _tower_or_404(station_id, tower_id, db)
    _validate_source_document(station_id, payload.source_document_id, db)
    old_ref = t.tower_ref
    for k, v in _clean_tower(st, payload.model_dump(), db, tower_id).items():
        setattr(t, k, v)
    if t.tower_ref != old_ref:      # keep the survey readings attached to the renamed tower
        db.query(models.RssiReadingORM).filter_by(station_id=station_id, tower_ref=old_ref).update(
            {"tower_ref": t.tower_ref})
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{station_id}/towers/{tower_id}", status_code=204)
def delete_tower(station_id: int, tower_id: int, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    db.delete(_tower_or_404(station_id, tower_id, db))
    db.commit()


@router.get("/{station_id}/rssi", response_model=list[schemas.RssiReadingOut])
def list_rssi(station_id: int, tower_ref: str | None = None, db: Session = Depends(get_db),
              user=Depends(get_current_user)):
    _get_station_or_404(station_id, db)
    q = db.query(models.RssiReadingORM).filter_by(station_id=station_id)
    if tower_ref:
        q = q.filter_by(tower_ref=tower_ref)
    return q.order_by(models.RssiReadingORM.tower_ref, models.RssiReadingORM.location_m).all()


@router.delete("/{station_id}/rssi", status_code=204)
def clear_rssi(station_id: int, tower_ref: str | None = Query(None, description="only this tower's readings"),
               db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    q = db.query(models.RssiReadingORM).filter_by(station_id=station_id)
    if tower_ref:
        q = q.filter_by(tower_ref=tower_ref)
    q.delete()
    db.commit()


@router.get("/{station_id}/rssi/summary")
def rssi_summary(station_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Per tower: how many readings, over which km, strongest and weakest; plus the
    border-tag coverage verdict that the verification runs (BR-005)."""
    from ..rules.engine import check_br005_rssi_coverage
    st = _get_station_or_404(station_id, db)
    towers = {t.tower_ref: t for t in st.towers}
    per: dict[str, dict] = {}
    for r in st.rssi_readings:
        s = per.setdefault(r.tower_ref, {"tower_ref": r.tower_ref, "readings": 0, "from_m": r.location_m,
                                         "to_m": r.location_m, "best_dbm": r.rssi_dbm, "worst_dbm": r.rssi_dbm})
        s["readings"] += 1
        s["from_m"], s["to_m"] = min(s["from_m"], r.location_m), max(s["to_m"], r.location_m)
        s["best_dbm"], s["worst_dbm"] = max(s["best_dbm"], r.rssi_dbm), min(s["worst_dbm"], r.rssi_dbm)
    rows = []
    for ref, s in sorted(per.items()):
        t = towers.get(ref)
        rows.append({**s, "in_register": t is not None,
                     "owner": (t.owner or st.name) if t is not None else None})
    dom = st.to_domain()
    border = [{"status": c.status, "subject_ref": c.subject_ref, "message": c.message}
              for c in check_br005_rssi_coverage(dom, [t.to_domain() for t in st.tags])]
    return {"towers": rows, "border_coverage": border, "total_readings": len(st.rssi_readings)}
