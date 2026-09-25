"""
Producer -> Checker -> Approving Authority workflow state machine for a station's
RFID Tag/TIN layout, mirroring the sign-off cycle described in the source design
process (self-check -> submit -> Checker verifies against Annexure-H -> repeat until
clean -> approval) and enforced here as actual code rather than a paper process.

Two governance rules are load-bearing and deliberately hard-coded, not configurable:
  1. A Checker cannot mark a station "checked" while automated Annexure-H checks are
     still failing (fail_count must be 0 at the moment of the check action).
  2. Segregation of duties: the person who submitted a layout cannot check it, and
     the person who checked it cannot approve it. Same person wearing two hats on
     the same layout defeats the entire point of a Checker role. The 'admin' role is
     exempt from rule 2 -- an intentional escape hatch so a small pilot team (or a
     single person testing the whole cycle) isn't blocked, at the cost of admin
     being able to rubber-stamp their own work. Use sparingly in practice; this is
     a bootstrap convenience, not a recommendation for how real approvals should work.

A third rule governs task assignment: submitting a layout requires naming a specific
Checker (target_username), and only that Checker (or an admin) can act on it while
it's SUBMITTED -- any other checker with a login is not allowed to pick it up
unilaterally, since that would defeat the point of an explicit assignment. There is
deliberately no equivalent assignment step for Checker -> Approver: any active
approver may act on a CHECKED station, per the original request that only the
Designer->Checker handoff be an explicit assignment.

Both are tested in tests/test_workflow.py against every state/role combination that
matters, not just the happy path.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..domain import WorkflowEvent, User

DRAFT = "draft"
SUBMITTED = "submitted"
CHECKED = "checked"
APPROVED = "approved"

STATUSES = [DRAFT, SUBMITTED, CHECKED, APPROVED]

SUBMIT = "submit"
REQUEST_CHANGES = "request_changes"
CHECK = "check"
APPROVE = "approve"
REOPEN = "reopen"


class WorkflowError(Exception):
    pass


@dataclass
class TransitionRule:
    from_status: str
    action: str
    to_status: str
    allowed_roles: tuple[str, ...]


TRANSITIONS: list[TransitionRule] = [
    TransitionRule(DRAFT, SUBMIT, SUBMITTED, ("designer", "admin")),
    TransitionRule(SUBMITTED, REQUEST_CHANGES, DRAFT, ("checker", "approver", "admin")),
    TransitionRule(SUBMITTED, CHECK, CHECKED, ("checker", "admin")),
    TransitionRule(CHECKED, REQUEST_CHANGES, DRAFT, ("approver", "admin")),
    TransitionRule(CHECKED, APPROVE, APPROVED, ("approver", "admin")),
    TransitionRule(APPROVED, REOPEN, DRAFT, ("admin",)),
]

_BY_FROM_ACTION = {(t.from_status, t.action): t for t in TRANSITIONS}


@dataclass
class StationWorkflowState:
    """Everything the workflow engine needs about a station beyond its current
    status: who did the last submit/check, so segregation-of-duty rules can be
    enforced. In production this is reconstructed from the WorkflowEvent history
    (see models.py's WorkflowEventORM) rather than stored redundantly on Station."""
    status: str
    submitted_by: str | None = None
    checked_by: str | None = None
    assigned_checker: str | None = None


def attempt_transition(
    state: StationWorkflowState,
    action: str,
    actor: User,
    station_id: int,
    now_iso: str,
    comment: str = "",
    verification_fail_count: int | None = None,
    target_username: str | None = None,
    target_role: str | None = None,
) -> tuple[StationWorkflowState, WorkflowEvent]:
    """Validate and apply a workflow action. Raises WorkflowError with a specific,
    actionable message on any rule violation. Returns the new state and the
    WorkflowEvent to persist as an audit-trail record -- callers must not mutate
    state directly; this function is the only legitimate way a station's status
    changes.

    target_username / target_role are only meaningful for the SUBMIT action (the
    Checker being assigned). target_role, if provided, lets the engine validate the
    assignee actually holds the checker role without needing DB access itself --
    the router looks the user up and passes their role in; the engine just checks
    it matches "checker" rather than trusting the caller blindly."""
    rule = _BY_FROM_ACTION.get((state.status, action))
    if rule is None:
        raise WorkflowError(
            f"Action '{action}' is not valid from status '{state.status}'"
        )

    if actor.role not in rule.allowed_roles:
        raise WorkflowError(
            f"Role '{actor.role}' cannot perform '{action}' "
            f"(requires one of {rule.allowed_roles})"
        )

    if not actor.is_active:
        raise WorkflowError(f"User '{actor.username}' is not an active account")

    if action == SUBMIT:
        if not target_username:
            raise WorkflowError(
                "Submitting for check requires assigning a Checker -- pass "
                "target_username of the checker to route this to"
            )
        if target_role is not None and target_role != "checker":
            raise WorkflowError(
                f"Assigned user must have the 'checker' role (got '{target_role}')"
            )

    if action in (CHECK,) or (action == REQUEST_CHANGES and state.status == SUBMITTED):
        if (actor.role != "admin" and state.assigned_checker
                and actor.username != state.assigned_checker):
            raise WorkflowError(
                f"This submission was assigned to Checker '{state.assigned_checker}' -- "
                f"only they (or an admin) can act on it"
            )

    if action == CHECK:
        if verification_fail_count is None:
            raise WorkflowError(
                "Cannot mark a layout checked without a verification result -- "
                "run the Annexure-H verification first and pass its fail_count in"
            )
        if verification_fail_count > 0:
            raise WorkflowError(
                f"Cannot mark checked: {verification_fail_count} automated "
                f"Annexure-H check(s) are still failing"
            )
        if actor.role != "admin" and state.submitted_by and actor.username == state.submitted_by:
            raise WorkflowError(
                "Segregation of duties: the Checker cannot be the same person who "
                "submitted this layout for check"
            )

    if action == APPROVE:
        if actor.role != "admin" and state.checked_by and actor.username == state.checked_by:
            raise WorkflowError(
                "Segregation of duties: the Approver cannot be the same person who "
                "checked this layout"
            )

    if action == REQUEST_CHANGES and not comment.strip():
        raise WorkflowError("A comment explaining what needs to change is required")

    event = WorkflowEvent(
        id=None, station_id=station_id, from_status=state.status, to_status=rule.to_status,
        action=action, actor_username=actor.username, actor_role=actor.role,
        comment=comment, timestamp=now_iso, verification_fail_count=verification_fail_count,
        target_username=target_username if action == SUBMIT else None,
    )

    new_state = StationWorkflowState(
        status=rule.to_status,
        submitted_by=actor.username if action == SUBMIT else (
            None if action == REQUEST_CHANGES else state.submitted_by
        ),
        checked_by=actor.username if action == CHECK else (
            None if action == REQUEST_CHANGES else state.checked_by
        ),
        assigned_checker=target_username if action == SUBMIT else (
            None if action in (REQUEST_CHANGES, REOPEN) else state.assigned_checker
        ),
    )

    return new_state, event


def allowed_actions(state: StationWorkflowState, actor: User) -> list[str]:
    """Which actions `actor` could currently perform from `state.status`, ignoring
    fail-count/segregation checks that depend on runtime context (verification
    result) -- useful for the UI to know which buttons to show at all."""
    return [
        t.action for t in TRANSITIONS
        if t.from_status == state.status and actor.role in t.allowed_roles and actor.is_active
    ]
