"""
Phase 1 endpoints:

  FR-001  Input documents -- SIP, Site Survey, RFID Allocation Chart, Adjacent
          Layout, ToC, other. Upload (new immutable revision), list, download,
          delete (draft-only, and only if nothing traces to it).
  FR-002  DXF import -- the previously unreachable dxf_import/importer.py, now
          exposed as parse -> human review -> explicit commit. Nothing is ever
          written to the registers without the commit call.
  FR-011  Traceability matrix -- every Tag/Element/TIN -> the input revision it
          came from -> the workflow events (each carrying a snapshot of the input
          package that was current at that moment).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth.deps import get_current_user
from ..database import get_db
from ..documents import service as docsvc
from ..domain import ELEMENT_TYPES, TAG_TYPES

router = APIRouter(prefix="/stations", tags=["inputs & traceability"])
# Separate, un-prefixed router: "/stations/document-types" would collide with
# GET /stations/{station_id} (registered earlier) and 422 on int parsing.
meta_router = APIRouter(tags=["inputs & traceability"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _station_or_404(station_id: int, db: Session) -> models.StationORM:
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    return station


def _doc_or_404(station_id: int, doc_id: int, db: Session) -> models.InputDocumentORM:
    doc = db.query(models.InputDocumentORM).filter_by(id=doc_id, station_id=station_id).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def _require_uploader(user: models.UserORM) -> None:
    if user.role not in docsvc.UPLOADER_ROLES:
        raise HTTPException(403, f"Only {' / '.join(docsvc.UPLOADER_ROLES)} can add or "
                                 f"remove design inputs (you are '{user.role}')")


def _require_draft(station: models.StationORM) -> None:
    # Same rule as the registers: the input package a Checker is reviewing must
    # not change underneath them.
    if station.status != "draft":
        raise HTTPException(409, f"Station is '{station.status}', not 'draft' -- design "
                                 f"inputs can only be changed in draft.")


def _doc_out(doc: models.InputDocumentORM, current_ids: set[int]) -> schemas.InputDocumentOut:
    out = schemas.InputDocumentOut.model_validate(doc, from_attributes=True)
    out.is_current = doc.id in current_ids
    return out


def _current_ids(db: Session, station_id: int) -> set[int]:
    return {d.id for d in docsvc.current_documents(db, station_id).values()}


async def _store_upload(station: models.StationORM, file: UploadFile, doc_type: str,
                        version_label: str | None, notes: str | None,
                        user: models.UserORM, db: Session) -> models.InputDocumentORM:
    if doc_type not in docsvc.DOC_TYPES:
        raise HTTPException(422, f"doc_type must be one of {list(docsvc.DOC_TYPES)}")
    filename = docsvc.safe_basename(file.filename or "")
    ext = docsvc.file_extension(filename)
    allowed = docsvc.DOC_TYPES[doc_type]["extensions"]
    if ext not in allowed:
        raise HTTPException(422, f"'{ext or filename}' is not accepted for "
                                 f"{docsvc.DOC_TYPES[doc_type]['label']}. "
                                 f"Accepted: {', '.join(allowed)}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "Uploaded file is empty")
    if len(data) > docsvc.max_upload_bytes():
        raise HTTPException(413, f"File exceeds the {docsvc.max_upload_bytes() // (1024*1024)} MB limit")

    rel_path, sha = docsvc.store_bytes(station.id, doc_type, ext, data)
    from datetime import datetime, timezone
    doc = models.InputDocumentORM(
        station_id=station.id, doc_type=doc_type,
        revision=docsvc.next_revision(db, station.id, doc_type),
        version_label=(version_label or "").strip() or None,
        original_filename=filename, stored_path=rel_path,
        content_type=file.content_type, size_bytes=len(data), sha256=sha,
        uploaded_by=user.username, uploaded_at=datetime.now(timezone.utc).isoformat(),
        notes=(notes or "").strip() or None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# FR-001 input documents
# ---------------------------------------------------------------------------
@meta_router.get("/document-types", response_model=list[schemas.DocTypeOut])
def list_document_types(user: models.UserORM = Depends(get_current_user)):
    return [schemas.DocTypeOut(code=k, label=v["label"], extensions=list(v["extensions"]),
                               required=k in docsvc.REQUIRED_DOC_TYPES)
            for k, v in docsvc.DOC_TYPES.items()]


@router.post("/{station_id}/documents", response_model=schemas.InputDocumentOut)
async def upload_document(
    station_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
    version_label: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Uploading a doc_type that already exists creates the next revision; the
    previous revision is kept (it may be what existing tags trace to)."""
    station = _station_or_404(station_id, db)
    _require_uploader(user)
    _require_draft(station)
    doc = await _store_upload(station, file, doc_type, version_label, notes, user, db)
    return _doc_out(doc, _current_ids(db, station_id))


@router.get("/{station_id}/documents", response_model=list[schemas.InputDocumentOut])
def list_documents(station_id: int, doc_type: str | None = None,
                   db: Session = Depends(get_db),
                   user: models.UserORM = Depends(get_current_user)):
    _station_or_404(station_id, db)
    q = db.query(models.InputDocumentORM).filter_by(station_id=station_id)
    if doc_type:
        q = q.filter_by(doc_type=doc_type)
    current = _current_ids(db, station_id)
    return [_doc_out(d, current) for d in
            q.order_by(models.InputDocumentORM.doc_type, models.InputDocumentORM.revision.desc()).all()]


@router.get("/{station_id}/documents/{doc_id}/download")
def download_document(station_id: int, doc_id: int, db: Session = Depends(get_db),
                      user: models.UserORM = Depends(get_current_user)):
    doc = _doc_or_404(station_id, doc_id, db)
    try:
        path = docsvc.absolute_path(doc)
    except ValueError:
        raise HTTPException(500, "Stored path is invalid")
    if not path.exists():
        raise HTTPException(410, "The stored file is missing from UPLOAD_DIR -- the DB "
                                 "record survives but the bytes do not. Re-upload it.")
    return FileResponse(path, filename=doc.original_filename,
                        media_type=doc.content_type or "application/octet-stream")


@router.delete("/{station_id}/documents/{doc_id}", status_code=204)
def delete_document(station_id: int, doc_id: int, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    _require_uploader(user)
    _require_draft(station)
    doc = _doc_or_404(station_id, doc_id, db)
    reasons = docsvc.document_is_referenced(db, doc)
    if reasons:
        raise HTTPException(409, "Cannot delete this document -- " + "; ".join(reasons) +
                                 ". Upload a new revision instead.")
    db.delete(doc)
    db.commit()
    docsvc.delete_file_quietly(doc)
    return None


# ---------------------------------------------------------------------------
# FR-002 DXF import: parse -> review -> commit
# ---------------------------------------------------------------------------
_DXF_DOC_TYPES = (docsvc.SIP, docsvc.ADJACENT_LAYOUT, docsvc.OTHER)


def _parse_dxf(doc: models.InputDocumentORM, ref_x: float | None, ref_km: float | None,
               units_per_km: float | None) -> tuple[list[schemas.DxfCandidateOut], list[str], list[str]]:
    from ..dxf_import.importer import import_dxf
    if docsvc.file_extension(doc.original_filename) != ".dxf":
        raise HTTPException(422, "This document is not a .dxf file")
    result = import_dxf(str(docsvc.absolute_path(doc)))
    calibrated = None not in (ref_x, ref_km, units_per_km) and units_per_km != 0
    warnings = list(result.warnings)
    if not calibrated:
        warnings.append("No chainage calibration supplied (ref_x, ref_km, units_per_km) -- "
                        "location_km must be entered for every candidate before commit.")
    cands = [
        schemas.DxfCandidateOut(
            index=i, text=c.text, layer=c.layer, x=c.x, y=c.y, kind=c.kind,
            suggested_location_km=(round(ref_km + (c.x - ref_x) / units_per_km, 4)
                                   if calibrated else None),
        )
        for i, c in enumerate(result.candidates)
    ]
    return cands, warnings, sorted({c.layer for c in result.candidates})


@router.post("/{station_id}/import-dxf", response_model=schemas.DxfImportOut)
async def import_dxf_upload(
    station_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form(docsvc.SIP),
    version_label: str | None = Form(None),
    notes: str | None = Form(None),
    ref_x: float | None = Form(None), ref_km: float | None = Form(None),
    units_per_km: float | None = Form(None),
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Store the .dxf as an input document revision, then return the importer's
    candidates for human review. Registers are NOT modified here."""
    if doc_type not in _DXF_DOC_TYPES:
        raise HTTPException(422, f"DXF import doc_type must be one of {_DXF_DOC_TYPES}")
    if docsvc.file_extension(file.filename or "") != ".dxf":
        raise HTTPException(422, "Only .dxf files can be imported (export .dwg to DXF "
                                 "from AutoCAD first)")
    station = _station_or_404(station_id, db)
    _require_uploader(user)
    _require_draft(station)
    doc = await _store_upload(station, file, doc_type, version_label, notes, user, db)
    cands, warnings, layers = _parse_dxf(doc, ref_x, ref_km, units_per_km)
    return schemas.DxfImportOut(document=_doc_out(doc, _current_ids(db, station_id)),
                                candidates=cands, warnings=warnings, layers=layers)


@router.get("/{station_id}/documents/{doc_id}/dxf-candidates", response_model=schemas.DxfImportOut)
def dxf_candidates(station_id: int, doc_id: int,
                   ref_x: float | None = Query(None), ref_km: float | None = Query(None),
                   units_per_km: float | None = Query(None),
                   db: Session = Depends(get_db),
                   user: models.UserORM = Depends(get_current_user)):
    """Re-parse an already-stored DXF (e.g. with a different chainage calibration)."""
    doc = _doc_or_404(station_id, doc_id, db)
    cands, warnings, layers = _parse_dxf(doc, ref_x, ref_km, units_per_km)
    return schemas.DxfImportOut(document=_doc_out(doc, _current_ids(db, station_id)),
                                candidates=cands, warnings=warnings, layers=layers)


@router.post("/{station_id}/documents/{doc_id}/dxf-commit", response_model=schemas.DxfCommitOut)
def dxf_commit(station_id: int, doc_id: int, payload: schemas.DxfCommitRequest,
               db: Session = Depends(get_db),
               user: models.UserORM = Depends(get_current_user)):
    """All-or-nothing: creates the reviewed Elements and Tags, every one stamped
    with source_document_id = this DXF revision. Any validation error rejects
    the whole batch so the register never ends up half-imported."""
    station = _station_or_404(station_id, db)
    _require_uploader(user)
    _require_draft(station)
    _doc_or_404(station_id, doc_id, db)
    if not payload.elements and not payload.tags:
        raise HTTPException(422, "Nothing to commit")

    errors: list[str] = []
    existing_el = {e.element_ref: e for e in
                   db.query(models.ElementORM).filter_by(station_id=station_id).all()}
    existing_tag_refs = {t.tag_ref for t in
                         db.query(models.TagORM).filter_by(station_id=station_id).all()}

    batch_el_refs: set[str] = set()
    for e in payload.elements:
        if e.element_type not in ELEMENT_TYPES:
            errors.append(f"element {e.element_ref}: unknown element_type '{e.element_type}'")
        if e.element_ref in existing_el or e.element_ref in batch_el_refs:
            errors.append(f"element {e.element_ref}: ref already exists on this station")
        batch_el_refs.add(e.element_ref)

    batch_tag_refs: set[str] = set()
    for t in payload.tags:
        if t.tag_type not in TAG_TYPES:
            errors.append(f"tag {t.tag_ref}: unknown tag_type '{t.tag_type}'")
        if t.tag_ref in existing_tag_refs or t.tag_ref in batch_tag_refs:
            errors.append(f"tag {t.tag_ref}: ref already exists on this station")
        batch_tag_refs.add(t.tag_ref)
        if t.linked_element_ref and t.linked_element_ref not in existing_el \
                and t.linked_element_ref not in batch_el_refs:
            errors.append(f"tag {t.tag_ref}: linked_element_ref '{t.linked_element_ref}' "
                          f"not found on station or in this batch")
    if errors:
        raise HTTPException(422, {"message": "DXF commit rejected -- nothing was saved",
                                  "errors": errors})

    try:
        new_elements = []
        for e in payload.elements:
            row = models.ElementORM(station_id=station_id,
                                    **{**e.model_dump(), "source_document_id": doc_id})
            db.add(row)
            new_elements.append(row)
        db.flush()
        el_by_ref = {**existing_el, **{e.element_ref: e for e in new_elements}}

        new_tags = []
        for t in payload.tags:
            data = t.model_dump(exclude={"linked_element_ref"})
            data["source_document_id"] = doc_id
            if t.linked_element_ref:
                data["linked_element_id"] = el_by_ref[t.linked_element_ref].id
            row = models.TagORM(station_id=station_id, **data)
            db.add(row)
            new_tags.append(row)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return schemas.DxfCommitOut(
        document_id=doc_id, elements_created=len(new_elements), tags_created=len(new_tags),
        element_ids=[e.id for e in new_elements], tag_ids=[t.id for t in new_tags],
    )


# ---------------------------------------------------------------------------
# FR-011 traceability
# ---------------------------------------------------------------------------
@router.get("/{station_id}/traceability", response_model=schemas.TraceabilityOut)
def traceability(station_id: int, db: Session = Depends(get_db),
                 user: models.UserORM = Depends(get_current_user)):
    station = _station_or_404(station_id, db)
    docs = (db.query(models.InputDocumentORM).filter_by(station_id=station_id)
            .order_by(models.InputDocumentORM.doc_type,
                      models.InputDocumentORM.revision.desc()).all())
    current = docsvc.current_documents(db, station_id)
    current_ids = {d.id for d in current.values()}
    by_id = {d.id: d for d in docs}

    def ref(doc_id: int | None) -> tuple[schemas.TraceDocRef | None, bool]:
        d = by_id.get(doc_id) if doc_id else None
        if not d:
            return None, False
        is_cur = d.id in current_ids
        return schemas.TraceDocRef(id=d.id, doc_type=d.doc_type, revision=d.revision,
                                   version_label=d.version_label,
                                   original_filename=d.original_filename,
                                   is_current=is_cur), not is_cur

    elements = db.query(models.ElementORM).filter_by(station_id=station_id).all()
    el_ref_by_id = {e.id: e.element_ref for e in elements}
    rows: list[schemas.TraceRow] = []
    for e in sorted(elements, key=lambda x: x.location_km):
        src, outdated = ref(e.source_document_id)
        rows.append(schemas.TraceRow(kind="element", id=e.id, ref=e.element_ref,
                                     type=e.element_type, location_km=e.location_km,
                                     source=src, source_outdated=outdated))
    for t in sorted(db.query(models.TagORM).filter_by(station_id=station_id).all(),
                    key=lambda x: x.location_km):
        src, outdated = ref(t.source_document_id)
        rows.append(schemas.TraceRow(kind="tag", id=t.id, ref=t.tag_ref, type=t.tag_type,
                                     location_km=t.location_km, source=src,
                                     source_outdated=outdated,
                                     linked_element_ref=el_ref_by_id.get(t.linked_element_id)))
    for n in sorted(db.query(models.TINORM).filter_by(station_id=station_id).all(),
                    key=lambda x: x.start_km):
        src, outdated = ref(n.source_document_id)
        rows.append(schemas.TraceRow(kind="tin", id=n.id, ref=f"TIN {n.tin_no}",
                                     type=n.section_type, location_km=n.start_km,
                                     source=src, source_outdated=outdated))

    events = (db.query(models.WorkflowEventORM).filter_by(station_id=station_id)
              .order_by(models.WorkflowEventORM.id.asc()).all())

    gaps: list[str] = []
    for code in docsvc.REQUIRED_DOC_TYPES:
        if code not in current:
            gaps.append(f"No {docsvc.DOC_TYPES[code]['label']} uploaded")
    tag_rows = [r for r in rows if r.kind == "tag"]
    untraced_tags = [r.ref for r in tag_rows if r.source is None]
    if untraced_tags:
        gaps.append(f"{len(untraced_tags)} tag(s) have no source document: "
                    f"{', '.join(untraced_tags[:10])}{' …' if len(untraced_tags) > 10 else ''}")
    outdated = [f"{r.ref} ({r.source.doc_type} rev {r.source.revision})"
                for r in rows if r.source_outdated and r.source]
    if outdated:
        gaps.append(f"{len(outdated)} row(s) trace to a superseded input revision -- re-check "
                    f"against the current revision: {', '.join(outdated[:10])}"
                    f"{' …' if len(outdated) > 10 else ''}")
    if station.status in ("self_checked", "submitted", "checked", "approved", "railway_submitted"):
        last = events[-1] if events else None
        if last is None or not last.input_snapshot:
            gaps.append("Current workflow state has no recorded input snapshot (transition "
                        "happened before traceability was enabled)")

    summary = {
        "documents": len(docs),
        "current_documents": len(current),
        "tags": len(tag_rows),
        "tags_traced": len(tag_rows) - len(untraced_tags),
        "elements": sum(1 for r in rows if r.kind == "element"),
        "elements_traced": sum(1 for r in rows if r.kind == "element" and r.source),
        "rows_on_superseded_inputs": len(outdated),
        "workflow_events": len(events),
    }
    return schemas.TraceabilityOut(
        station_id=station.id, station_name=station.name,
        layout_version=station.layout_version, status=station.status,
        inputs=[_doc_out(d, current_ids) for d in docs], rows=rows,
        workflow=[schemas.WorkflowEventOut.model_validate(e, from_attributes=True) for e in events],
        gaps=gaps, summary=summary,
    )
