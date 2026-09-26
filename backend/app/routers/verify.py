import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth.deps import get_current_user
from ..rules.engine import run_all_checks, MANUAL_CLAUSES
from ..toc.parser import parse_toc_file, UnsupportedFormatError
from ..toc.cross_validate import cross_validate_station, summarize

router = APIRouter(tags=["verification"])

SUPPORTED_TOC_EXTENSIONS = (".csv", ".xlsx", ".xls", ".docx")


def _load_domain_layout(station_id: int, db: Session):
    station_orm = db.get(models.StationORM, station_id)
    if not station_orm:
        raise HTTPException(404, "Station not found")
    station = station_orm.to_domain()
    elements = [e.to_domain() for e in
                db.query(models.ElementORM).filter_by(station_id=station_id).all()]
    tags = [t.to_domain() for t in
            db.query(models.TagORM).filter_by(station_id=station_id).all()]
    tins = [t.to_domain() for t in
            db.query(models.TINORM).filter_by(station_id=station_id).all()]
    return station, elements, tags, tins


@router.get("/stations/{station_id}/verify", response_model=schemas.VerificationReportOut)
def verify_station(station_id: int, db: Session = Depends(get_db),
                    user: models.UserORM = Depends(get_current_user)):
    """Run the full Annexure-H automated rule set against a station's current
    Elements/Tags/TINs. Every result carries the clause it came from. MANUAL_CLAUSES
    lists what this endpoint deliberately does NOT check, and why -- see rules/engine.py."""
    from ..rules import store
    station, elements, tags, tins = _load_domain_layout(station_id, db)
    st_orm = db.get(models.StationORM, station_id)
    rules = store.active_rules(db, st_orm.workspace_id if st_orm else None)
    report = run_all_checks(station, elements, tags, tins, rules=rules)
    from ..deviations import apply as apply_deviations
    unused = apply_deviations(report, list(st_orm.deviations)) if st_orm else []
    manual = {r.clause: r.description or r.title for r in rules if r.kind == "manual" and r.enabled}
    return schemas.VerificationReportOut(
        results=[schemas.CheckResultOut(**vars(r)) for r in report.results],
        summary=report.summary(),
        manual_clauses=manual,
        checklist_version=store.config_version(db),
        rules_disabled=[f"{r.clause} {r.title}" for r in rules if not r.enabled and r.kind != "manual"],
        deviations_unused=[f"{d.clause} {d.subject_ref or ''}".strip() for d in unused],
    )


@router.post("/stations/{station_id}/verify-toc", response_model=schemas.ToCCrossValidationOut)
async def verify_against_toc(station_id: int, toc_file: UploadFile = File(...),
                              db: Session = Depends(get_db),
                              user: models.UserORM = Depends(get_current_user)):
    """Upload a station's Table of Control export (.csv, .xlsx, .xls, or .docx) and
    cross-check the currently drawn Tag Register against the tag chains it encodes
    -- see toc/cross_validate.py. Legacy .doc is deliberately not supported; see
    toc/parser.py's module docstring for why, and what to do instead (convert to
    .docx/.xlsx/.csv)."""
    filename = toc_file.filename or ""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == ".doc":
        raise HTTPException(
            422,
            "Legacy .doc (Word 97-2003) files are not supported -- this format "
            "cannot be reliably parsed without a system conversion tool. Please "
            "save/export as .docx, .xlsx, or .csv and re-upload.",
        )
    if ext not in SUPPORTED_TOC_EXTENSIONS:
        raise HTTPException(
            422,
            f"Unsupported file type '{ext or filename}'. Supported: "
            f"{', '.join(SUPPORTED_TOC_EXTENSIONS)}.",
        )

    _, _, tags, _ = _load_domain_layout(station_id, db)

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await toc_file.read())
        tmp_path = tmp.name

    try:
        routes = parse_toc_file(tmp_path, filename)
    except UnsupportedFormatError as e:
        raise HTTPException(422, str(e))

    results = cross_validate_station(routes, tags)
    return schemas.ToCCrossValidationOut(
        results=[schemas.ChainCheckResultOut(**vars(r)) for r in results],
        summary=summarize(results),
    )
