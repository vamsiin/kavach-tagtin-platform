"""
BRD FR-007 / Section 11: report generation (PDF + Word), generation log, archived
verification evidence, and the drawing revision table (RevisionORM, previously dead).
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..documents import service as docsvc
from ..reports import builders
from ..reports.model import Report

router = APIRouter(prefix="/stations", tags=["reports"])
meta_router = APIRouter(tags=["reports"])

MEDIA = {"pdf": "application/pdf",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
ARCHIVE_ON = ("self_check", "check", "approve", "railway_submit")


def _station_or_404(station_id: int, db: Session) -> models.StationORM:
    st = db.get(models.StationORM, station_id)
    if not st:
        raise HTTPException(404, "Station not found")
    return st


def build_report(db: Session, station: models.StationORM, user: models.UserORM, code: str) -> Report:
    if code not in builders.REPORT_TYPES:
        raise HTTPException(404, f"Unknown report type '{code}'. Available: {list(builders.REPORT_TYPES)}")
    ctx = builders.load_ctx(db, station, user)
    if code == "traceability":
        from .documents import traceability
        return builders.build_traceability(ctx, traceability(station.id, db, user))
    return builders.BUILDERS[code](ctx)


def render(report: Report, fmt: str) -> bytes:
    wide = report.code in builders.WIDE_REPORTS
    if fmt == "pdf":
        try:
            from ..reports.render_pdf import render_pdf
        except ImportError:
            raise HTTPException(503, "PDF output needs the 'reportlab' package -- run "
                                     "`pip install -r requirements.txt` in the backend venv. "
                                     "Word (.docx) output works without it.")
        return render_pdf(report, wide=wide)
    if fmt == "docx":
        from ..reports.render_docx import render_docx
        return render_docx(report, wide=wide)
    raise HTTPException(422, "format must be 'pdf' or 'docx'")


def _filename(report: Report, fmt: str) -> str:
    base = f"{report.station_name}_{report.title}_{report.layout_version}_{report.generated_at[:10]}"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("_") + f".{fmt}"


def _log(db, station, report: Report, fmt, data: bytes, *, archived=False, stored_path=None,
         event_id=None, trigger="manual") -> models.GeneratedReportORM:
    row = models.GeneratedReportORM(
        station_id=station.id, report_type=report.code, report_id=report.report_id, fmt=fmt,
        generated_by=report.generated_by, generated_at=report.generated_at,
        layout_version=report.layout_version, station_status=report.station_status,
        sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), archived=archived,
        stored_path=stored_path, workflow_event_id=event_id, trigger=trigger)
    db.add(row)
    db.commit()
    return row


def archive_verification_report(db: Session, station_id: int, event: models.WorkflowEventORM,
                                user: models.UserORM) -> None:
    """Called after a workflow transition commits. Freezes the verification report
    as it stood at that step. Must never break the workflow: any failure is logged
    and swallowed."""
    if event.action not in ARCHIVE_ON:
        return
    try:
        station = db.get(models.StationORM, station_id)
        report = build_report(db, station, user, "verification")
        report.title = f"Verification Report - at {builders.ACTION_LABELS.get(event.action, event.action)}"
        data = render(report, "pdf")
        rel = Path(f"station_{station_id}") / "reports" / f"{report.report_id}-{event.id}.pdf"
        abs_path = docsvc.upload_dir() / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)
        _log(db, station, report, "pdf", data, archived=True, stored_path=rel.as_posix(),
             event_id=event.id, trigger=event.action)
    except Exception as e:  # pragma: no cover - defensive
        db.rollback()
        print(f"[reports] WARNING: could not archive verification report for event {event.id}: {e}")


# ---------------------------------------------------------------------------
@meta_router.get("/report-types", response_model=list[schemas.ReportTypeOut])
def report_types(user: models.UserORM = Depends(get_current_user)):
    return [schemas.ReportTypeOut(code=k, title=v["title"], description=v["description"],
                                  formats=["pdf", "docx"]) for k, v in builders.REPORT_TYPES.items()]


@router.get("/{station_id}/reports/{code}")
def generate_report(station_id: int, code: str, format: str = Query("pdf"),
                    db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    if format not in MEDIA:
        raise HTTPException(422, "format must be 'pdf' or 'docx'")
    report = build_report(db, station, user, code)
    data = render(report, format)
    _log(db, station, report, format, data)
    return Response(content=data, media_type=MEDIA[format], headers={
        "Content-Disposition": f'attachment; filename="{_filename(report, format)}"',
        "X-Report-Id": report.report_id,
        "Access-Control-Expose-Headers": "Content-Disposition, X-Report-Id",
    })


@router.get("/{station_id}/report-log", response_model=list[schemas.GeneratedReportOut])
def report_log(station_id: int, archived_only: bool = False, db: Session = Depends(get_db),
               user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    q = db.query(models.GeneratedReportORM).filter_by(station_id=station_id)
    if archived_only:
        q = q.filter(models.GeneratedReportORM.archived.is_(True))
    return q.order_by(models.GeneratedReportORM.id.desc()).limit(500).all()


@router.get("/{station_id}/report-log/{log_id}/download")
def download_archived(station_id: int, log_id: int, db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    row = db.query(models.GeneratedReportORM).filter_by(id=log_id, station_id=station_id).first()
    if not row:
        raise HTTPException(404, "Report not found")
    if not row.archived or not row.stored_path:
        raise HTTPException(409, "Only archived reports are stored; generate this report again instead")
    path = (docsvc.upload_dir() / row.stored_path).resolve()
    if docsvc.upload_dir() not in path.parents or not path.exists():
        raise HTTPException(410, "Archived report file is missing from UPLOAD_DIR")
    return FileResponse(path, media_type=MEDIA[row.fmt], filename=Path(row.stored_path).name)


# ---------------------------------------------------------------------------
# Drawing revision table
# ---------------------------------------------------------------------------
@router.get("/{station_id}/revisions", response_model=list[schemas.RevisionOut])
def list_revisions(station_id: int, db: Session = Depends(get_db),
                   user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    return db.query(models.RevisionORM).filter_by(station_id=station_id).order_by(models.RevisionORM.id).all()


def _require_designer_draft(station, user):
    if user.role not in ("designer", "admin"):
        raise HTTPException(403, "Only a designer or admin can edit the revision table")
    if station.status != "draft":
        raise HTTPException(409, f"Station is '{station.status}', not 'draft' -- the revision "
                                 f"table can only be edited in draft")


@router.post("/{station_id}/revisions", response_model=schemas.RevisionOut)
def add_revision(station_id: int, payload: schemas.RevisionCreate, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    _require_designer_draft(station, user)
    if db.query(models.RevisionORM).filter_by(station_id=station_id, rev_no=payload.rev_no.strip()).first():
        raise HTTPException(409, f"Revision '{payload.rev_no}' already exists")
    row = models.RevisionORM(station_id=station_id, rev_no=payload.rev_no.strip(), date=payload.date,
                             description=payload.description.strip(),
                             layout_version=station.layout_version, created_by=user.username,
                             created_at=datetime.now(timezone.utc).isoformat())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{station_id}/revisions/{rev_id}", status_code=204)
def delete_revision(station_id: int, rev_id: int, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    _require_designer_draft(station, user)
    row = db.query(models.RevisionORM).filter_by(id=rev_id, station_id=station_id).first()
    if not row:
        raise HTTPException(404, "Revision not found")
    db.delete(row)
    db.commit()
    return None
