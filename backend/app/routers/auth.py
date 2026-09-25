from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..domain import ROLES
from ..auth.security import (
    hash_password, verify_password, create_jwt,
    create_password_reset_token, validate_password_reset_token, peek_jwt_subject, TokenError,
)
from ..auth.deps import require_role, get_current_user, JWT_SECRET

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    """Open ONLY when no users exist yet (first-run bootstrap of an admin account).
    After that, use POST /auth/users (admin-only) to create further accounts --
    this endpoint intentionally cannot be used to self-register once a platform
    instance has any users at all."""
    if payload.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")

    user_count = db.query(models.UserORM).count()
    if user_count > 0:
        raise HTTPException(
            403, "Registration is closed -- an admin must create further accounts "
                 "via POST /auth/users"
        )

    existing = db.query(models.UserORM).filter_by(username=payload.username).first()
    if existing:
        raise HTTPException(400, f"Username '{payload.username}' already exists")

    password_hash, salt = hash_password(payload.password)
    user = models.UserORM(
        username=payload.username, full_name=payload.full_name, email=payload.email,
        role=payload.role, password_hash=password_hash, password_salt=salt, is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users", response_model=schemas.UserOut)
def create_user(
    payload: schemas.UserCreate, db: Session = Depends(get_db),
    _admin: models.UserORM = Depends(require_role("admin")),
):
    if payload.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    existing = db.query(models.UserORM).filter_by(username=payload.username).first()
    if existing:
        raise HTTPException(400, f"Username '{payload.username}' already exists")

    password_hash, salt = hash_password(payload.password)
    user = models.UserORM(
        username=payload.username, full_name=payload.full_name, email=payload.email,
        role=payload.role, password_hash=password_hash, password_salt=salt, is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/users/{username}", response_model=schemas.UserOut)
def update_user(
    username: str, payload: schemas.UserUpdate, db: Session = Depends(get_db),
    admin: models.UserORM = Depends(require_role("admin")),
):
    if payload.role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    user = db.query(models.UserORM).filter_by(username=username).first()
    if not user:
        raise HTTPException(404, f"User '{username}' not found")
    if user.username == admin.username and payload.role != "admin":
        raise HTTPException(
            400, "You cannot demote your own account away from admin -- have "
                 "another admin do it, to avoid locking yourself out"
        )
    if user.username == admin.username and not payload.is_active:
        raise HTTPException(400, "You cannot deactivate your own account")

    user.full_name = payload.full_name
    user.email = payload.email
    user.role = payload.role
    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{username}", status_code=204)
def delete_user(
    username: str, db: Session = Depends(get_db),
    admin: models.UserORM = Depends(require_role("admin")),
):
    """Deletes a user account. Does NOT touch historical WorkflowEvent records or
    Station.created_by -- those store the username as plain text, not a foreign
    key, precisely so deleting an account never erases audit history (see
    WorkflowEventORM). A deleted user's past actions remain fully visible in the
    audit trail, just attributed to a username that no longer has a live account."""
    if username == admin.username:
        raise HTTPException(400, "You cannot delete your own account")

    user = db.query(models.UserORM).filter_by(username=username).first()
    if not user:
        raise HTTPException(404, f"User '{username}' not found")

    if user.role == "admin":
        remaining_admins = db.query(models.UserORM).filter(
            models.UserORM.role == "admin", models.UserORM.id != user.id
        ).count()
        if remaining_admins == 0:
            raise HTTPException(
                400, "Cannot delete the last remaining admin account -- create "
                     "another admin first"
            )

    db.delete(user)
    db.commit()
    return None


@router.get("/users/by-role/{role}", response_model=list[schemas.UserOut])
def list_users_by_role(
    role: str, workspace_id: int | None = None, db: Session = Depends(get_db),
    _user: models.UserORM = Depends(get_current_user),
):
    """Unlike GET /auth/users (admin-only, full user management), this is available
    to any authenticated user -- it exists specifically so a Designer can populate
    a 'assign to Checker' dropdown when submitting a station without needing admin
    privileges just to see who the checkers are. Still requires authentication
    (not public), and only returns active users."""
    if role not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    users = db.query(models.UserORM).filter_by(role=role, is_active=True).all()
    if workspace_id is not None:   # only people who can see that workspace (e.g. checker picker)
        from ..workspaces.service import can_access
        users = [u for u in users if can_access(db, u, workspace_id)]
    return users


@router.get("/me", response_model=schemas.UserOut)
def get_me(user: models.UserORM = Depends(get_current_user)):
    return user


@router.get("/users", response_model=list[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: models.UserORM = Depends(require_role("admin")),
):
    return db.query(models.UserORM).all()


@router.post("/login", response_model=schemas.TokenOut)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.UserORM).filter_by(username=payload.username).first()
    # Deliberately identical error for "no such user" and "wrong password" -- do not
    # let a login endpoint reveal which usernames exist.
    invalid = HTTPException(401, "Invalid username or password")
    if not user or not user.is_active:
        raise invalid
    if not verify_password(payload.password, user.password_hash, user.password_salt):
        raise invalid

    token = create_jwt({"sub": user.username, "role": user.role}, JWT_SECRET)
    return schemas.TokenOut(access_token=token, user=user)


@router.post("/forgot-password", response_model=schemas.ForgotPasswordResponse)
def forgot_password(payload: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Issues a 15-minute password-reset token if the account exists and is active.

    Honest limitation: this deployment has no email/SMTP integration configured, so
    the token is NOT emailed -- it is printed to the backend server's console/log
    output, where only whoever is running the server can see it. That is a
    deliberate choice, not an oversight: returning the token directly in this HTTP
    response would let anyone who knows (or guesses) a username reset that
    account's password, which is a real vulnerability. Wiring this to an actual
    email provider is a small, contained change (replace the print() below with an
    email send) once one is available -- the token generation/validation logic
    doesn't need to change.

    The response message is identical whether or not the account exists, so this
    endpoint cannot be used to enumerate valid usernames.
    """
    user = db.query(models.UserORM).filter_by(username=payload.username).first()
    generic_message = (
        "If that account exists, a password reset has been generated. "
        "Contact your system administrator, who can see it in the server logs."
    )
    if not user or not user.is_active:
        return schemas.ForgotPasswordResponse(message=generic_message)

    token = create_password_reset_token(user.username, user.password_hash, JWT_SECRET)
    print(
        f"\n{'='*70}\n"
        f"PASSWORD RESET requested for user '{user.username}'\n"
        f"Reset token (valid 15 minutes, single-use):\n{token}\n"
        f"Give this to the user directly (e.g. verbally, over a call) -- it is "
        f"as sensitive as their password for the next 15 minutes.\n{'='*70}\n"
    )
    return schemas.ForgotPasswordResponse(message=generic_message)


@router.post("/reset-password", response_model=schemas.ForgotPasswordResponse)
def reset_password(payload: schemas.ResetPasswordRequest, db: Session = Depends(get_db)):
    """Consumes a reset token from /auth/forgot-password. The token becomes invalid
    the instant this succeeds (see security.py's hash-binding mechanism), so it
    cannot be replayed even though it's a stateless JWT with no server-side
    revocation list."""
    # We need to find which user this token is for before we can validate it
    # (validation needs their current password_hash to check the binding) --
    # but we must not leak *which part* failed, so every failure path returns the
    # same generic error.
    invalid = HTTPException(400, "This reset link is invalid, expired, or already used")

    claimed_username = peek_jwt_subject(payload.token)
    if not claimed_username:
        raise invalid

    user = db.query(models.UserORM).filter_by(username=claimed_username).first()
    if not user or not user.is_active:
        raise invalid

    try:
        validate_password_reset_token(payload.token, user.password_hash, JWT_SECRET)
    except TokenError:
        raise invalid

    if len(payload.new_password) < 8:
        raise HTTPException(422, "New password must be at least 8 characters")

    new_hash, new_salt = hash_password(payload.new_password)
    user.password_hash = new_hash
    user.password_salt = new_salt
    db.commit()

    return schemas.ForgotPasswordResponse(message="Password has been reset. You can now log in.")


@router.post("/users/{username}/reset-password", response_model=schemas.UserOut)
def admin_reset_password(
    username: str, payload: schemas.AdminResetPasswordRequest,
    db: Session = Depends(get_db),
    _admin: models.UserORM = Depends(require_role("admin")),
):
    """Direct admin-initiated reset -- no token flow, for when a Checker/Approver/
    Designer is locked out and an admin is available to help them. Does NOT work
    for resetting the admin's own account if there is only one admin and they
    forgot their password -- see scripts/reset_password.py for that last-resort
    case, which requires direct filesystem/DB access rather than going through
    this API (deliberately: an API endpoint that lets an unauthenticated caller
    reset an admin password would be a serious hole)."""
    user = db.query(models.UserORM).filter_by(username=username).first()
    if not user:
        raise HTTPException(404, f"User '{username}' not found")
    if len(payload.new_password) < 8:
        raise HTTPException(422, "New password must be at least 8 characters")

    new_hash, new_salt = hash_password(payload.new_password)
    user.password_hash = new_hash
    user.password_salt = new_salt
    db.commit()
    db.refresh(user)
    return user
