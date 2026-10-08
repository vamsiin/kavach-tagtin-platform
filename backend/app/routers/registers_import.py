"""CSV / Excel upload for the Elements, Tags and TINs registers (see registers/csv_import.py)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models
from ..auth.deps import get_current_user
from ..database import get_db
from ..registers import csv_import
from .stations import _get_station_or_404, _require_editable, _require_register_editor

router = APIRouter(prefix="/stations", tags=["registers"])
MAX_BYTES = 5 * 1024 * 1024


@router.get("/{station_id}/registers/{kind}/template")
def template(station_id: int, kind: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    _get_station_or_404(station_id, db)
    if kind not in csv_import.KINDS:
        raise HTTPException(404, "Unknown register")
    return Response(content=csv_import.TEMPLATES[kind], media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{kind}-template.csv"',
        "Access-Control-Expose-Headers": "Content-Disposition"})


@router.post("/{station_id}/registers/{kind}/import")
async def import_register(station_id: int, kind: str, file: UploadFile = File(...),
                          apply: bool = Query(False, description="false = preview only"),
                          update_existing: bool = Query(False, description="change rows that already exist"),
                          db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user)):
    """Preview (default) or apply a CSV / .xlsx file of register rows. Apply writes
    everything in one go, and only when no row has an error."""
    st = _get_station_or_404(station_id, db)
    _require_editable(st)
    _require_register_editor(user, st)
    if kind not in csv_import.KINDS:
        raise HTTPException(404, "Unknown register")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 5 MB)")
    rows = csv_import.read_table(file.filename or "", data)
    result = csv_import.preview(db, st, kind, rows, update_existing)
    out = {k: v for k, v in result.items() if not k.startswith("_")}
    if not apply:
        return out
    if not result["can_apply"]:
        raise HTTPException(422, {"message": "Fix the rows with errors and upload again -- nothing was saved",
                                  "preview": out})
    counts = csv_import.apply(db, st, kind, result)
    db.add(models.StationChangeORM(
        station_id=st.id, field=f"import {kind}", before=None,
        after=f"{counts['add']} added, {counts['update']} updated",
        reason=f"uploaded {file.filename or 'file'}", changed_by=user.username, changed_by_role=user.role,
        changed_at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    return {**out, "applied": True}
