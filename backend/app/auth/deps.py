import os

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from .security import decode_jwt, TokenError

# In production this MUST come from a secrets manager / environment variable that
# is never committed -- the fallback here is only so the app doesn't crash on a
# fresh clone before you've set one, and is deliberately obviously-a-placeholder.
JWT_SECRET = os.environ.get("JWT_SECRET", "CHANGE-ME-INSECURE-DEV-ONLY-SECRET")


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.UserORM:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_jwt(token, JWT_SECRET)
    except TokenError as e:
        raise HTTPException(401, f"Invalid token: {e}")

    username = payload.get("sub")
    user = db.query(models.UserORM).filter_by(username=username).first()
    if not user or not user.is_active:
        raise HTTPException(401, "User not found or inactive")
    return user


def require_role(*roles: str):
    """Usage: Depends(require_role("checker", "admin")) on any route that should
    only be reachable by those roles. Distinct from the workflow engine's own role
    checks (workflow/engine.py) -- this is the HTTP-layer gate; the workflow engine
    re-validates independently so a route wired to the wrong role list still can't
    bypass the actual state-machine rules."""
    def _dependency(user: models.UserORM = Depends(get_current_user)) -> models.UserORM:
        if user.role not in roles:
            raise HTTPException(403, f"Requires role in {roles}, have '{user.role}'")
        return user
    return _dependency
