"""Station-specific deviations from automated checks (see models.CheckDeviationORM)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..deviations import _key, apply
from .stations import _get_station_or_404, _require_editable, _require_register_editor

router = APIRouter(prefix="/stations", tags=["deviations"])


def _report(db: Session, st: models.StationORM):
    from ..rules.engine import run_all_checks
    from ..rules.store import active_rules
    return run_all_checks(st.to_domain(), [e.to_domain() for e in st.elements], [t.to_domain() for t in st.tags],
                          [n.to_domain() for n in st.tins], rules=active_rules(db, st.workspace_id))


def _log(db, st, before, after, reason, user):
    db.add(models.StationChangeORM(station_id=st.id, field="deviation", before=before, after=after, reason=reason,
                                   changed_by=user.username, changed_by_role=user.role,
                                   changed_at=datetime.now(timezone.utc).isoformat()))


def _label(d) -> str:
    return f"{d.clause} {d.subject_ref or '(station)'}"


@router.get("/{station_id}/deviations", response_model=list[schemas.DeviationOut])
def list_deviations(station_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    devs = list(st.deviations)
    unused = {d.id for d in apply(_report(db, st), devs)} if devs else set()
    return [schemas.DeviationOut.model_validate(d).model_copy(update={"in_use": d.id not in unused}) for d in devs]


@router.post("/{station_id}/deviations", response_model=schemas.DeviationOut)
def add_deviation(station_id: int, payload: schemas.DeviationIn, db: Session = Depends(get_db),
                  user: models.UserORM = Depends(get_current_user)):
    """Accept one FAILING automated check as a station deviation. Draft only, by the
    designer (or an admin); the check must be failing right now."""
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    key = _key(payload.clause, payload.subject_ref)
    if any(_key(d.clause, d.subject_ref) == key for d in st.deviations):
        raise HTTPException(409, "A deviation is already recorded for this check")
    if not any(r.status == "FAIL" and _key(r.clause, r.subject_ref) == key for r in _report(db, st).results):
        raise HTTPException(422, f"No failing check {payload.clause} {payload.subject_ref or ''} on this station "
                                 f"-- only a failing check can be accepted as a deviation")
    d = models.CheckDeviationORM(
        station_id=st.id, clause=payload.clause.strip(), subject_ref=(payload.subject_ref or "").strip() or None,
        reason=payload.reason.strip(), reference=(payload.reference or "").strip() or None,
        created_by=user.username, created_by_role=user.role, created_at=datetime.now(timezone.utc).isoformat())
    db.add(d)
    _log(db, st, None, _label(d), d.reason + (f" [{d.reference}]" if d.reference else ""), user)
    db.commit()
    db.refresh(d)
    return d


@router.delete("/{station_id}/deviations/{dev_id}", status_code=204)
def delete_deviation(station_id: int, dev_id: int, db: Session = Depends(get_db),
                     user: models.UserORM = Depends(get_current_user)):
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    d = db.get(models.CheckDeviationORM, dev_id)
    if d is None or d.station_id != st.id:
        raise HTTPException(404, "Deviation not found")
    _log(db, st, _label(d), None, "deviation withdrawn", user)
    db.delete(d)
    db.commit()
