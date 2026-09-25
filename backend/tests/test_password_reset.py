import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth.security import (
    hash_password, create_password_reset_token, validate_password_reset_token,
    create_jwt, TokenError,
)

SECRET = "test-secret-do-not-use-in-prod"


def test_reset_token_roundtrip():
    pw_hash, _ = hash_password("current-password")
    token = create_password_reset_token("alice", pw_hash, SECRET)
    username = validate_password_reset_token(token, pw_hash, SECRET)
    assert username == "alice"


def test_reset_token_rejected_after_password_changed():
    """This is the core single-use guarantee: once the password actually changes,
    a previously-issued reset token must stop working, even though it hasn't
    expired -- with no server-side revocation list needed."""
    old_hash, _ = hash_password("old-password")
    token = create_password_reset_token("alice", old_hash, SECRET)

    new_hash, _ = hash_password("new-password")  # simulates the reset having happened
    try:
        validate_password_reset_token(token, new_hash, SECRET)
        assert False, "expected TokenError -- token should not be replayable"
    except TokenError as e:
        assert "already been used" in str(e) or "different password state" in str(e)


def test_reset_token_rejected_if_not_reset_purpose():
    """A normal login JWT must never be usable as a password-reset token, even if
    someone tries to pass it into the reset endpoint."""
    login_token = create_jwt({"sub": "alice", "role": "designer"}, SECRET)
    pw_hash, _ = hash_password("whatever")
    try:
        validate_password_reset_token(login_token, pw_hash, SECRET)
        assert False, "expected TokenError"
    except TokenError as e:
        assert "not a password-reset token" in str(e)


def test_reset_token_expires():
    pw_hash, _ = hash_password("current-password")
    token = create_password_reset_token("alice", pw_hash, SECRET, expires_in_seconds=-1)
    try:
        validate_password_reset_token(token, pw_hash, SECRET)
        assert False, "expected TokenError"
    except TokenError as e:
        assert "expired" in str(e).lower()


def test_reset_token_is_per_username():
    pw_hash, _ = hash_password("current-password")
    token = create_password_reset_token("alice", pw_hash, SECRET)
    username = validate_password_reset_token(token, pw_hash, SECRET)
    assert username != "bob"
    assert username == "alice"
