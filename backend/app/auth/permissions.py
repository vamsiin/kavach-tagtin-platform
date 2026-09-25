"""
Role -> capability matrix (BRD Section 7, stakeholders & roles). This is the single
place that says who may do what; routers ask `can(user, "cap")` / `require(user, "cap")`
instead of hard-coding role tuples. The workflow state machine (workflow/engine.py)
still owns *transition* roles, because those also depend on the station's status.

Roles:
  designer          prepares the layout: registers, inputs, self-check, submit, resolve observations
  checker           verifies: observations, manual checklist, mark checked, request changes
  approver          approves, records Railway submission
  project_manager   MONITORS and ASSIGNS -- portfolio dashboard, assigns the designer,
                    reassigns the checker. No edit rights on layouts, inputs or reviews.
  config_manager    VERSION / BASELINE management -- station version numbers (in draft),
                    baselines of approved layouts, checklist configuration, reopening an
                    approved layout for a new revision. No layout editing.
  admin             everything (bootstrap / small-team escape hatch)
"""
from __future__ import annotations

from fastapi import HTTPException

ROLE_LABELS = {
    "designer": "Designer",
    "checker": "Checker (Verifier)",
    "approver": "Approver",
    "project_manager": "Project Manager",
    "config_manager": "Configuration Manager",
    "admin": "Administrator",
}

CAPABILITIES: dict[str, tuple[str, ...]] = {
    # layout content
    "station.create": ("designer", "admin"),
    "registers.edit": ("designer", "admin"),
    "inputs.upload": ("designer", "admin"),
    "revisions.edit": ("designer", "admin"),
    # review
    "observations.raise": ("checker", "approver", "admin"),
    "checklist.respond": ("checker", "approver", "admin"),
    # project management
    "assign.designer": ("project_manager", "admin"),
    "assign.checker": ("project_manager", "admin"),
    # configuration management
    "checklist.edit": ("config_manager", "admin"),
    "station.versions": ("config_manager", "admin"),
    "baseline.create": ("config_manager", "admin"),
    "allotment.manage": ("config_manager", "admin"),
    # administration
    "users.manage": ("admin",),
    # everyone who can log in
    "dashboard.view": tuple(ROLE_LABELS),
    "reports.generate": tuple(ROLE_LABELS),
}


def can(user, capability: str) -> bool:
    return user is not None and user.role in CAPABILITIES.get(capability, ())


def require(user, capability: str, what: str | None = None) -> None:
    if not can(user, capability):
        roles = " / ".join(ROLE_LABELS[r] for r in CAPABILITIES.get(capability, ()))
        raise HTTPException(403, f"{what or 'This action'} requires the role: {roles} "
                                 f"(you are '{ROLE_LABELS.get(user.role, user.role)}')")


def capabilities_for(role: str) -> list[str]:
    return sorted(c for c, roles in CAPABILITIES.items() if role in roles)
