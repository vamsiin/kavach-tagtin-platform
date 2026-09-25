import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth.deps import get_current_user
from ..documents.service import snapshot_current_inputs
from ..rules.engine import run_all_checks
from ..notifications.email import (
    notify_checker_assigned, notify_designer_of_check_result, notify_of_approval_result,
)
from ..workflow.engine import (
    attempt_transition, allowed_actions, StationWorkflowState, WorkflowError,
    SUBMIT, CHECK, APPROVE, REQUEST_CHANGES, REOPEN,
    SELF_CHECK, REVISE, RAILWAY_SUBMIT, CYCLE_RESET_ACTIONS,
)

router = APIRouter(prefix="/stations", tags=["workflow"])


def _load_workflow_state(station: models.StationORM, db: Session) -> StationWorkflowState:
    """Reconstructs submitted_by/checked_by/assigned_checker from the most recent
    relevant events in the audit trail, rather than trusting redundant columns on
    Station -- the event log is the source of truth."""
    events = (
        db.query(models.WorkflowEventORM)
        .filter_by(station_id=station.id)
        .order_by(models.WorkflowEventORM.id.desc())
        .all()
    )
    submitted_by = None
    checked_by = None
    assigned_checker = None
    self_checked_by = None
    for e in events:
        if e.action in CYCLE_RESET_ACTIONS:
            break
        if e.action == SUBMIT and submitted_by is None:
            submitted_by = e.actor_username
            assigned_checker = e.target_username
        if e.action == CHECK and checked_by is None:
            checked_by = e.actor_username
        if e.action == SELF_CHECK and self_checked_by is None:
            self_checked_by = e.actor_username
    return StationWorkflowState(
        status=station.status, submitted_by=submitted_by, checked_by=checked_by,
        assigned_checker=assigned_checker, self_checked_by=self_checked_by,
    )


def _run_verification(station_id: int, db: Session):
    """Fresh server-side Annexure-H run -- workflow gates never trust a
    client-supplied result."""
    station_orm = db.get(models.StationORM, station_id)
    if not station_orm:
        raise HTTPException(404, "Station not found")
    elements = [e.to_domain() for e in db.query(models.ElementORM).filter_by(station_id=station_id).all()]
    tags = [t.to_domain() for t in db.query(models.TagORM).filter_by(station_id=station_id).all()]
    tins = [t.to_domain() for t in db.query(models.TINORM).filter_by(station_id=station_id).all()]
    return run_all_checks(station_orm.to_domain(), elements, tags, tins)


def _user_email(username: str | None, db: Session) -> str:
    if not username:
        return ""
    user = db.query(models.UserORM).filter_by(username=username).first()
    return (user.email if user and user.email else "") or ""


def _do_transition(
    station_id: int, action: str, comment: str, db: Session, user: models.UserORM,
    verification_fail_count: int | None = None,
    target_username: str | None = None,
    target_role: str | None = None,
    before_commit=None,
) -> tuple[models.StationORM, StationWorkflowState]:
    """before_commit(station, event_orm), if given, runs after the event row is
    flushed (so it has an id) and before the single commit -- used to write
    records that must be atomic with the transition (e.g. railway submission)."""
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")

    state = _load_workflow_state(station, db)
    actor = user.to_domain()
    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        new_state, event = attempt_transition(
            state, action, actor, station_id, now_iso, comment=comment,
            verification_fail_count=verification_fail_count,
            target_username=target_username, target_role=target_role,
        )
    except WorkflowError as e:
        raise HTTPException(409, str(e))

    station.status = new_state.status
    station.assigned_checker = new_state.assigned_checker
    event_orm = models.WorkflowEventORM(
        station_id=station_id, from_status=event.from_status, to_status=event.to_status,
        action=event.action, actor_username=event.actor_username,
        actor_role=event.actor_role, comment=event.comment, timestamp=event.timestamp,
        verification_fail_count=event.verification_fail_count,
        target_username=event.target_username,
        input_snapshot=snapshot_current_inputs(db, station_id),
    )
    db.add(event_orm)
    if before_commit is not None:
        db.flush()
        before_commit(station, event_orm)
    db.commit()
    db.refresh(station)
    return station, state  # also return the PRE-transition state (for from_status/emails)


@router.post("/{station_id}/self-check", response_model=schemas.StationOut,
             responses={409: {"model": schemas.SelfCheckFailedOut}})
def self_check_station(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """BRD FR-009 'Self Check': the Designer's own recorded verification step.
    Runs the full Annexure-H rule set server-side; only a zero-failure result moves
    the station to 'self_checked'. On failure nothing changes and the failing
    clauses are returned so the designer knows what to fix."""
    report = _run_verification(station_id, db)
    if report.fail_count > 0:
        summary = report.summary()
        raise HTTPException(409, {
            "message": f"Self-check failed: {report.fail_count} automated check(s) failing",
            "fail_count": report.fail_count,
            "clauses_failing": summary.get("clauses_failing", []),
        })
    station, _ = _do_transition(station_id, SELF_CHECK, payload.comment, db, user,
                                verification_fail_count=report.fail_count)
    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/revise", response_model=schemas.StationOut)
def revise_station(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Take a self-checked (not yet submitted) layout back to draft for editing.
    The self-check is discarded -- it must be run again before submitting."""
    station, _ = _do_transition(station_id, REVISE, payload.comment, db, user)
    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/submit", response_model=schemas.StationOut)
def submit_station(
    station_id: int, payload: schemas.SubmitForCheckRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Submitting requires naming a specific Checker to assign this to -- see
    workflow/engine.py's module docstring for why this handoff, specifically, is an
    explicit assignment rather than "any checker may pick it up"."""
    checker = db.query(models.UserORM).filter_by(username=payload.assigned_checker_username).first()
    if not checker:
        raise HTTPException(404, f"No user '{payload.assigned_checker_username}' found")

    station, _ = _do_transition(
        station_id, SUBMIT, payload.comment, db, user,
        target_username=checker.username, target_role=checker.role,
    )

    result = notify_checker_assigned(checker.email, station.name, user.full_name)
    if not result.sent and result.mode == "smtp":
        print(f"[email] WARNING: failed to notify checker {checker.username}: {result.error}")

    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/check", response_model=schemas.StationOut)
def check_station(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Re-runs Annexure-H verification server-side at the moment of check -- the
    fail count used for the workflow gate is never trusted from the client, it is
    always freshly computed here so a stale/tampered client-side report can't be
    used to force a check through."""
    report = _run_verification(station_id, db)

    station, pre_state = _do_transition(
        station_id, CHECK, payload.comment, db, user,
        verification_fail_count=report.fail_count,
    )

    designer_email = _user_email(pre_state.submitted_by, db)
    notify_designer_of_check_result(designer_email, station.name, user.full_name, approved=True)

    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/approve", response_model=schemas.StationOut)
def approve_station(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station_orm = db.get(models.StationORM, station_id)
    if not station_orm:
        raise HTTPException(404, "Station not found")

    station, pre_state = _do_transition(station_id, APPROVE, payload.comment, db, user)

    recipients = [e for e in (
        _user_email(pre_state.submitted_by, db), _user_email(pre_state.checked_by, db),
    ) if e]
    notify_of_approval_result(recipients, station.name, user.full_name, approved=True)

    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/request-changes", response_model=schemas.StationOut)
def request_changes(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """Used by both a Checker (rejecting a SUBMITTED station back to the Designer)
    and an Approver (rejecting a CHECKED station back to the Designer) -- which one
    happened is read off the pre-transition status, and the notification recipients
    and wording differ accordingly (checker-reject notifies only the Designer;
    approver-reject notifies both the Designer and the Checker, per the original
    requirement)."""
    station_orm = db.get(models.StationORM, station_id)
    if not station_orm:
        raise HTTPException(404, "Station not found")
    pre_state = _load_workflow_state(station_orm, db)
    was_checked = pre_state.status == "checked"

    station, _ = _do_transition(station_id, REQUEST_CHANGES, payload.comment, db, user)

    designer_email = _user_email(pre_state.submitted_by, db)
    if was_checked:
        recipients = [e for e in (designer_email, _user_email(pre_state.checked_by, db)) if e]
        notify_of_approval_result(recipients, station.name, user.full_name, approved=False,
                                   comment=payload.comment)
    else:
        notify_designer_of_check_result(designer_email, station.name, user.full_name,
                                         approved=False, comment=payload.comment)

    from .stations import _station_out
    return _station_out(station)


@router.post("/{station_id}/reopen", response_model=schemas.StationOut)
def reopen_station(
    station_id: int, payload: schemas.WorkflowActionRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    station, _ = _do_transition(station_id, REOPEN, payload.comment, db, user)
    from .stations import _station_out
    return _station_out(station)


@router.get("/{station_id}/workflow", response_model=schemas.WorkflowStatusOut)
def get_workflow_status(
    station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user),
):
    station = db.get(models.StationORM, station_id)
    if not station:
        raise HTTPException(404, "Station not found")
    state = _load_workflow_state(station, db)
    events = (
        db.query(models.WorkflowEventORM)
        .filter_by(station_id=station_id)
        .order_by(models.WorkflowEventORM.id.asc())
        .all()
    )
    return schemas.WorkflowStatusOut(
        status=state.status, submitted_by=state.submitted_by, checked_by=state.checked_by,
        assigned_checker=state.assigned_checker, self_checked_by=state.self_checked_by,
        allowed_actions=allowed_actions(state, user.to_domain()),
        history=events,
    )


def _layout_snapshot(station: models.StationORM, db: Session) -> str:
    def rows(model, cols):
        return [{c: getattr(r, c) for c in cols}
                for r in db.query(model).filter_by(station_id=station.id).order_by(model.id).all()]
    return json.dumps({
        "station": {"id": station.id, "name": station.name,
                    "kavach_station_id": station.kavach_station_id,
                    "sip_drawing_number": station.sip_drawing_number,
                    "layout_version": station.layout_version},
        "elements": rows(models.ElementORM, [c.name for c in models.ElementORM.__table__.columns
                                             if c.name != "station_id"]),
        "tags": rows(models.TagORM, [c.name for c in models.TagORM.__table__.columns
                                     if c.name != "station_id"]),
        "tins": rows(models.TINORM, [c.name for c in models.TINORM.__table__.columns
                                     if c.name != "station_id"]),
    }, default=str)


@router.post("/{station_id}/railway-submit", response_model=schemas.RailwaySubmissionOut)
def railway_submit(
    station_id: int, payload: schemas.RailwaySubmitRequest,
    db: Session = Depends(get_db), user: models.UserORM = Depends(get_current_user),
):
    """BRD FR-009 terminal step. Records that the APPROVED layout package was sent
    to the Railway, with its reference and date, and freezes a snapshot of exactly
    what was sent (registers + input revisions). Atomic with the status change."""
    station_orm = db.get(models.StationORM, station_id)
    if not station_orm:
        raise HTTPException(404, "Station not found")
    if station_orm.layout_version == "INCOMPLETE":
        raise HTTPException(409, "Cannot submit to Railway: layout version is INCOMPLETE -- "
                                 "KAVACH, SIP and guideline versions must all be set (FR-010)")
    report = _run_verification(station_id, db)
    if report.fail_count > 0:
        # Registers are locked after approval, so this should never trigger -- if it
        # does, rules changed since approval and a human must look before sending.
        raise HTTPException(409, f"Cannot submit to Railway: {report.fail_count} automated "
                                 f"check(s) now fail (rules may have changed since approval). "
                                 f"Reopen and re-verify.")
    created: dict = {}

    def _record(station: models.StationORM, event: models.WorkflowEventORM):
        rec = models.RailwaySubmissionORM(
            station_id=station.id, workflow_event_id=event.id,
            layout_version=station.layout_version, reference_no=payload.reference_no,
            submitted_on=payload.submitted_on, addressed_to=(payload.addressed_to or "").strip() or None,
            remarks=(payload.remarks or "").strip() or None, recorded_by=user.username,
            recorded_at=event.timestamp, verification_fail_count=report.fail_count,
            layout_snapshot=_layout_snapshot(station, db), input_snapshot=event.input_snapshot,
        )
        db.add(rec)
        created["rec"] = rec

    comment = f"Railway submission ref {payload.reference_no} dated {payload.submitted_on}"
    _do_transition(station_id, RAILWAY_SUBMIT, comment, db, user,
                   verification_fail_count=report.fail_count, before_commit=_record)
    db.refresh(created["rec"])
    return created["rec"]


@router.get("/{station_id}/railway-submissions", response_model=list[schemas.RailwaySubmissionOut])
def list_railway_submissions(
    station_id: int, db: Session = Depends(get_db),
    user: models.UserORM = Depends(get_current_user),
):
    if not db.get(models.StationORM, station_id):
        raise HTTPException(404, "Station not found")
    return (db.query(models.RailwaySubmissionORM).filter_by(station_id=station_id)
            .order_by(models.RailwaySubmissionORM.id.desc()).all())
