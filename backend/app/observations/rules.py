"""
Observation lifecycle (BRD FR-008) as a pure state machine -- no DB, no HTTP --
in the same style as workflow/engine.py, so it can be tested exhaustively.

    open / reopened --resolve--> resolved --close--> closed
    resolved / closed --reopen--> reopened
    open / reopened / resolved --withdraw--> withdrawn

Who may do what:
  raise     checker, approver, admin (reviewers). Designers record their own notes
            in the self-check comment, not as observations against themselves.
  resolve   designer, admin -- the person fixing the layout says what they changed.
  close     checker, approver, admin -- a reviewer confirms the fix. Not the person
            who resolved it (segregation of duties; admin exempt, as elsewhere).
  reopen    checker, approver, admin -- the fix wasn't adequate.
  withdraw  the person who raised it, or admin -- raised in error.
  comment   anyone, any non-final status.

How observations gate the station workflow (applied in routers/workflow.py):
  self-check / submit        blocked while any non-info observation is UNRESOLVED
                             (open / reopened) -- don't send it back for review with
                             known issues unaddressed.
  check / approve / railway  blocked while any non-info observation is UNRESOLVED or
                             UNVERIFIED (resolved but not yet closed by a reviewer).
'info' severity observations never block anything.
"""
from __future__ import annotations

from dataclasses import dataclass

OPEN = "open"
RESOLVED = "resolved"
CLOSED = "closed"
REOPENED = "reopened"
WITHDRAWN = "withdrawn"
STATUSES = [OPEN, RESOLVED, CLOSED, REOPENED, WITHDRAWN]

UNRESOLVED = (OPEN, REOPENED)
UNVERIFIED = (RESOLVED,)
FINAL = (CLOSED, WITHDRAWN)

SEVERITIES = ["major", "minor", "info"]
CATEGORIES = ["annexure-h", "toc", "drafting", "data", "inputs", "other"]
SUBJECT_KINDS = ["station", "tag", "element", "tin", "document"]

REVIEWER_ROLES = ("checker", "approver", "admin")
RESOLVER_ROLES = ("designer", "admin")

RESOLVE = "resolve"
CLOSE = "close"
REOPEN = "reopen"
WITHDRAW = "withdraw"
COMMENT = "comment"


class ObservationError(Exception):
    pass


@dataclass
class ObsState:
    status: str
    raised_by: str
    resolved_by: str | None = None


_TRANSITIONS = {
    RESOLVE: (UNRESOLVED, RESOLVED, RESOLVER_ROLES),
    CLOSE: (UNVERIFIED, CLOSED, REVIEWER_ROLES),
    REOPEN: ((RESOLVED, CLOSED), REOPENED, REVIEWER_ROLES),
    WITHDRAW: ((OPEN, REOPENED, RESOLVED), WITHDRAWN, None),  # raiser or admin
}


def can_raise(role: str) -> bool:
    return role in REVIEWER_ROLES


def apply(state: ObsState, action: str, username: str, role: str, text: str = "") -> str:
    """Validate an action; return the new status (unchanged for COMMENT)."""
    text = (text or "").strip()
    if action == COMMENT:
        if state.status in FINAL:
            raise ObservationError(f"Observation is {state.status} -- no further comments")
        if not text:
            raise ObservationError("Comment text is required")
        return state.status

    if action not in _TRANSITIONS:
        raise ObservationError(f"Unknown action '{action}'")
    from_statuses, to_status, roles = _TRANSITIONS[action]
    if state.status not in from_statuses:
        raise ObservationError(f"Cannot {action} an observation that is '{state.status}'")

    if action == WITHDRAW:
        if role != "admin" and username != state.raised_by:
            raise ObservationError("Only the reviewer who raised it (or an admin) can withdraw it")
    elif role not in roles:
        raise ObservationError(f"Role '{role}' cannot {action} observations "
                               f"(requires one of {roles})")

    if action in (RESOLVE, REOPEN, WITHDRAW) and not text:
        raise ObservationError(f"A comment is required to {action} an observation"
                               + (" -- say what was changed" if action == RESOLVE else ""))
    if action == CLOSE and role != "admin" and state.resolved_by and username == state.resolved_by:
        raise ObservationError("Segregation of duties: the person who resolved an "
                               "observation cannot also close it")
    return to_status


def allowed_actions(state: ObsState, username: str, role: str) -> list[str]:
    out = []
    for action in (RESOLVE, CLOSE, REOPEN, WITHDRAW):
        try:
            apply(state, action, username, role, text="x")
            out.append(action)
        except ObservationError:
            pass
    if state.status not in FINAL:
        out.append(COMMENT)
    return out


def blocking_counts(observations: list[tuple[str, str]]) -> dict[str, int]:
    """observations: (status, severity) pairs -> counts that matter for gating."""
    blocking = [(st, sev) for st, sev in observations if sev != "info"]
    return {
        "unresolved": sum(1 for st, _ in blocking if st in UNRESOLVED),
        "unverified": sum(1 for st, _ in blocking if st in UNVERIFIED),
    }
