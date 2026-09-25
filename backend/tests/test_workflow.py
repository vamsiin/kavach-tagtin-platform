import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.domain import User
from app.workflow.engine import (
    attempt_transition, allowed_actions, StationWorkflowState, WorkflowError,
    DRAFT, SUBMITTED, CHECKED, APPROVED,
    SUBMIT, CHECK, APPROVE, REQUEST_CHANGES, REOPEN,
)

NOW = "2026-08-18T12:00:00Z"


def mk_user(username, role, active=True):
    return User(id=None, username=username, full_name=username.title(), role=role,
                is_active=active)


# ---------------------------------------------------------------------------
# Happy path: draft -> submitted -> checked -> approved
# ---------------------------------------------------------------------------
def test_full_happy_path():
    designer = mk_user("dana", "designer")
    checker = mk_user("cara", "checker")
    approver = mk_user("ana", "approver")

    state = StationWorkflowState(status=DRAFT)

    state, ev1 = attempt_transition(state, SUBMIT, designer, 1, NOW,
                                     target_username="cara", target_role="checker")
    assert state.status == SUBMITTED
    assert state.submitted_by == "dana"
    assert state.assigned_checker == "cara"
    assert ev1.from_status == DRAFT and ev1.to_status == SUBMITTED
    assert ev1.target_username == "cara"

    state, ev2 = attempt_transition(state, CHECK, checker, 1, NOW, verification_fail_count=0)
    assert state.status == CHECKED
    assert state.checked_by == "cara"

    state, ev3 = attempt_transition(state, APPROVE, approver, 1, NOW)
    assert state.status == APPROVED


def test_submit_requires_assigning_a_checker():
    designer = mk_user("dana", "designer")
    state = StationWorkflowState(status=DRAFT)
    try:
        attempt_transition(state, SUBMIT, designer, 1, NOW)  # no target_username
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "assigning a Checker" in str(e)


def test_submit_rejects_assignee_without_checker_role():
    designer = mk_user("dana", "designer")
    state = StationWorkflowState(status=DRAFT)
    try:
        attempt_transition(state, SUBMIT, designer, 1, NOW,
                            target_username="bob", target_role="designer")
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "'checker' role" in str(e)


def test_only_assigned_checker_can_check():
    designer = mk_user("dana", "designer")
    assigned_checker = mk_user("cara", "checker")
    other_checker = mk_user("chris", "checker")
    state = StationWorkflowState(status=DRAFT)
    state, _ = attempt_transition(state, SUBMIT, designer, 1, NOW,
                                   target_username="cara", target_role="checker")

    try:
        attempt_transition(state, CHECK, other_checker, 1, NOW, verification_fail_count=0)
        assert False, "expected WorkflowError -- other_checker was not assigned this station"
    except WorkflowError as e:
        assert "assigned to Checker 'cara'" in str(e)

    # the actually-assigned checker can proceed
    state, _ = attempt_transition(state, CHECK, assigned_checker, 1, NOW, verification_fail_count=0)
    assert state.status == CHECKED


def test_only_assigned_checker_can_reject_while_submitted():
    designer = mk_user("dana", "designer")
    other_checker = mk_user("chris", "checker")
    state = StationWorkflowState(status=DRAFT)
    state, _ = attempt_transition(state, SUBMIT, designer, 1, NOW,
                                   target_username="cara", target_role="checker")
    try:
        attempt_transition(state, REQUEST_CHANGES, other_checker, 1, NOW, comment="nope")
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "assigned to Checker 'cara'" in str(e)


def test_admin_can_check_regardless_of_assignment():
    designer = mk_user("dana", "designer")
    admin = mk_user("root", "admin")
    state = StationWorkflowState(status=DRAFT)
    state, _ = attempt_transition(state, SUBMIT, designer, 1, NOW,
                                   target_username="cara", target_role="checker")
    state, _ = attempt_transition(state, CHECK, admin, 1, NOW, verification_fail_count=0)
    assert state.status == CHECKED


def test_assignment_clears_on_request_changes():
    designer = mk_user("dana", "designer")
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=DRAFT)
    state, _ = attempt_transition(state, SUBMIT, designer, 1, NOW,
                                   target_username="cara", target_role="checker")
    state, _ = attempt_transition(state, REQUEST_CHANGES, checker, 1, NOW, comment="fix it")
    assert state.status == DRAFT
    assert state.assigned_checker is None


# ---------------------------------------------------------------------------
# Fail-count gate
# ---------------------------------------------------------------------------
def test_cannot_check_with_failing_checks():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    try:
        attempt_transition(state, CHECK, checker, 1, NOW, verification_fail_count=3)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "failing" in str(e).lower()


def test_cannot_check_without_running_verification():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    try:
        attempt_transition(state, CHECK, checker, 1, NOW)  # no verification_fail_count passed
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "verification" in str(e).lower()


def test_can_check_with_zero_fails():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    state, _ = attempt_transition(state, CHECK, checker, 1, NOW, verification_fail_count=0)
    assert state.status == CHECKED


# ---------------------------------------------------------------------------
# Segregation of duties
# ---------------------------------------------------------------------------
def test_submitter_cannot_check_own_layout():
    dana_as_checker = mk_user("dana", "checker")  # same username as submitter
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    try:
        attempt_transition(state, CHECK, dana_as_checker, 1, NOW, verification_fail_count=0)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "segregation" in str(e).lower()


def test_checker_cannot_approve_own_check():
    cara_as_approver = mk_user("cara", "approver")  # same username as checker
    state = StationWorkflowState(status=CHECKED, submitted_by="dana", checked_by="cara")
    try:
        attempt_transition(state, APPROVE, cara_as_approver, 1, NOW)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "segregation" in str(e).lower()


def test_different_people_can_check_and_approve():
    checker = mk_user("cara", "checker")
    approver = mk_user("ana", "approver")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    state, _ = attempt_transition(state, CHECK, checker, 1, NOW, verification_fail_count=0)
    state, _ = attempt_transition(state, APPROVE, approver, 1, NOW)
    assert state.status == APPROVED


def test_admin_is_exempt_from_segregation_of_duties():
    """Admin is an escape hatch for small teams / bootstrap -- but this should be
    used sparingly in practice; it exists so a solo pilot deployment isn't blocked."""
    admin = mk_user("root", "admin")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="root")
    state, _ = attempt_transition(state, CHECK, admin, 1, NOW, verification_fail_count=0)
    assert state.status == CHECKED


# ---------------------------------------------------------------------------
# Role permission checks
# ---------------------------------------------------------------------------
def test_designer_cannot_check():
    designer = mk_user("dana", "designer")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="someone_else")
    try:
        attempt_transition(state, CHECK, designer, 1, NOW, verification_fail_count=0)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "cannot perform" in str(e).lower()


def test_checker_cannot_approve():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=CHECKED, checked_by="someone_else")
    try:
        attempt_transition(state, APPROVE, checker, 1, NOW)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "cannot perform" in str(e).lower()


def test_inactive_user_cannot_act():
    inactive_checker = mk_user("cara", "checker", active=False)
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    try:
        attempt_transition(state, CHECK, inactive_checker, 1, NOW, verification_fail_count=0)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "not an active account" in str(e).lower()


# ---------------------------------------------------------------------------
# Invalid transitions / state machine shape
# ---------------------------------------------------------------------------
def test_cannot_approve_from_draft():
    approver = mk_user("ana", "approver")
    state = StationWorkflowState(status=DRAFT)
    try:
        attempt_transition(state, APPROVE, approver, 1, NOW)
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "not valid from status" in str(e).lower()


def test_request_changes_requires_comment():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    try:
        attempt_transition(state, REQUEST_CHANGES, checker, 1, NOW, comment="")
        assert False, "expected WorkflowError"
    except WorkflowError as e:
        assert "comment" in str(e).lower()


def test_request_changes_resets_to_draft_and_clears_submitted_by():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED, submitted_by="dana")
    state, ev = attempt_transition(
        state, REQUEST_CHANGES, checker, 1, NOW, comment="Fix H2.5 spacing on R-777"
    )
    assert state.status == DRAFT
    assert state.submitted_by is None
    assert "H2.5" in ev.comment


def test_reopen_requires_admin():
    approver = mk_user("ana", "approver")
    state = StationWorkflowState(status=APPROVED)
    try:
        attempt_transition(state, REOPEN, approver, 1, NOW)
        assert False, "expected WorkflowError"
    except WorkflowError:
        pass

    admin = mk_user("root", "admin")
    state, _ = attempt_transition(state, REOPEN, admin, 1, NOW)
    assert state.status == DRAFT


# ---------------------------------------------------------------------------
# allowed_actions (UI helper)
# ---------------------------------------------------------------------------
def test_allowed_actions_for_designer_in_draft():
    designer = mk_user("dana", "designer")
    state = StationWorkflowState(status=DRAFT)
    assert allowed_actions(state, designer) == [SUBMIT]


def test_allowed_actions_for_checker_in_submitted():
    checker = mk_user("cara", "checker")
    state = StationWorkflowState(status=SUBMITTED)
    actions = allowed_actions(state, checker)
    assert set(actions) == {REQUEST_CHANGES, CHECK}


def test_allowed_actions_empty_for_wrong_role():
    designer = mk_user("dana", "designer")
    state = StationWorkflowState(status=CHECKED)
    assert allowed_actions(state, designer) == []
