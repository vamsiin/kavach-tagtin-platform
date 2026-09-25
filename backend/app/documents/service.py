"""
Input-document storage and traceability helpers (FR-001 / FR-011 / BR-001).

Kept separate from the routers so the workflow router can snapshot "which input
revisions were current at this transition" without importing the documents
router (and so the storage rules can be tested without HTTP).

Storage layout on disk:  <UPLOAD_DIR>/station_<id>/<doc_type>/<uuid><ext>
Only the path RELATIVE to UPLOAD_DIR is stored in the DB, so moving the upload
directory (e.g. onto a mounted volume in Docker) only needs the env var changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models

# ---------------------------------------------------------------------------
# Document types (BRD FR-001) and which file extensions each accepts.
# ---------------------------------------------------------------------------
SIP = "SIP"
SITE_SURVEY = "SITE_SURVEY"
RFID_ALLOCATION_CHART = "RFID_ALLOCATION_CHART"
ADJACENT_LAYOUT = "ADJACENT_LAYOUT"
TOC = "TOC"
OTHER = "OTHER"

_DRAWING_EXT = (".pdf", ".dxf", ".dwg", ".png", ".jpg", ".jpeg", ".tif", ".tiff")
_SHEET_EXT = (".pdf", ".xlsx", ".xls", ".csv", ".docx")

DOC_TYPES: dict[str, dict] = {
    SIP: {"label": "Signal Interlocking Plan (SIP)", "extensions": _DRAWING_EXT},
    SITE_SURVEY: {"label": "Site Survey Report", "extensions": _SHEET_EXT + (".png", ".jpg", ".jpeg", ".zip")},
    RFID_ALLOCATION_CHART: {"label": "RFID Tag Allocation Chart", "extensions": _SHEET_EXT},
    ADJACENT_LAYOUT: {"label": "Adjacent Station Layout", "extensions": _DRAWING_EXT},
    TOC: {"label": "Table of Control", "extensions": (".csv", ".xlsx", ".xls", ".docx", ".pdf")},
    OTHER: {"label": "Other supporting document", "extensions": _DRAWING_EXT + _SHEET_EXT + (".zip", ".txt")},
}

# Inputs the BRD treats as mandatory for a layout to be traceable end-to-end.
# Reported as gaps by the traceability endpoint; NOT enforced as a submit gate
# (yet) so existing in-flight stations aren't blocked by an upgrade.
REQUIRED_DOC_TYPES = (SIP, SITE_SURVEY, RFID_ALLOCATION_CHART)

UPLOADER_ROLES = ("designer", "admin")


def upload_dir() -> Path:
    """Read at call time (not import time) so tests / deployments can point it
    somewhere else via the UPLOAD_DIR env var."""
    return Path(os.environ.get("UPLOAD_DIR", "./uploads")).resolve()


def max_upload_bytes() -> int:
    return int(float(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024)


def file_extension(filename: str) -> str:
    name = os.path.basename(filename or "")
    return ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""


def safe_basename(filename: str) -> str:
    """Strip any client-supplied directory components (both / and \\ -- Windows
    browsers have been known to send full paths)."""
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return name or "upload.bin"


def next_revision(db: Session, station_id: int, doc_type: str) -> int:
    current = db.query(func.max(models.InputDocumentORM.revision)).filter_by(
        station_id=station_id, doc_type=doc_type).scalar()
    return (current or 0) + 1


def store_bytes(station_id: int, doc_type: str, ext: str, data: bytes) -> tuple[str, str]:
    """Write bytes to disk; returns (relative_path, sha256_hex)."""
    rel = Path(f"station_{station_id}") / doc_type / f"{uuid.uuid4().hex}{ext}"
    abs_path = upload_dir() / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)
    return rel.as_posix(), hashlib.sha256(data).hexdigest()


def absolute_path(doc: models.InputDocumentORM) -> Path:
    p = (upload_dir() / doc.stored_path).resolve()
    # Defence in depth: never serve anything outside UPLOAD_DIR even if a DB row
    # were tampered with.
    if upload_dir() not in p.parents:
        raise ValueError("stored_path escapes UPLOAD_DIR")
    return p


def delete_file_quietly(doc: models.InputDocumentORM) -> None:
    try:
        absolute_path(doc).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def current_documents(db: Session, station_id: int) -> dict[str, models.InputDocumentORM]:
    """Latest revision per doc_type for a station."""
    latest: dict[str, models.InputDocumentORM] = {}
    for d in (db.query(models.InputDocumentORM).filter_by(station_id=station_id)
              .order_by(models.InputDocumentORM.revision.asc()).all()):
        latest[d.doc_type] = d
    return latest


def snapshot_current_inputs(db: Session, station_id: int) -> str:
    """JSON recorded on every WorkflowEvent (see models.WorkflowEventORM.input_snapshot)."""
    docs = current_documents(db, station_id)
    return json.dumps([
        {"id": d.id, "doc_type": d.doc_type, "revision": d.revision,
         "version_label": d.version_label, "sha256": d.sha256,
         "original_filename": d.original_filename}
        for d in sorted(docs.values(), key=lambda x: x.doc_type)
    ])


def document_is_referenced(db: Session, doc: models.InputDocumentORM) -> list[str]:
    """Why a document can't be deleted -- empty list means it's safe to delete."""
    reasons = []
    for model, label in ((models.TagORM, "tag"), (models.ElementORM, "element"),
                         (models.TINORM, "TIN")):
        n = db.query(model).filter_by(source_document_id=doc.id).count()
        if n:
            reasons.append(f"{n} {label}(s) trace to it")
    events = (db.query(models.WorkflowEventORM)
              .filter(models.WorkflowEventORM.station_id == doc.station_id,
                      models.WorkflowEventORM.input_snapshot.isnot(None)).all())
    for e in events:
        try:
            ids = {item["id"] for item in json.loads(e.input_snapshot or "[]")}
        except (ValueError, TypeError, KeyError):
            continue
        if doc.id in ids:
            reasons.append(f"it was part of the input package recorded at workflow "
                           f"'{e.action}' on {e.timestamp[:10]}")
            break
    return reasons
