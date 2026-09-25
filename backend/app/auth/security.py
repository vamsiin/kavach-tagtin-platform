"""
Password hashing and JSON Web Tokens, implemented with only the Python standard
library (hashlib, hmac, base64, json). No passlib/bcrypt, no python-jose/PyJWT.

This is a deliberate choice, same rationale as domain.py: auth is the one place
where an untested "trust me" implementation is least acceptable, so it's built to
be fully unit-testable in an environment where pip installs were blocked (see
tests/test_security.py) -- not a NIH objection to those libraries in general. If/when
this ships for real, swapping to passlib (for its automatic hash-scheme upgrades) and
a maintained JWT library (for revocation lists, JWKs, etc.) is a reasonable hardening
step -- this module intentionally does not implement token revocation, refresh
tokens, or key rotation, which a production auth system should have.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


# ---------------------------------------------------------------------------
# Password hashing: PBKDF2-HMAC-SHA256, per-user random salt.
# ---------------------------------------------------------------------------
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Returns (password_hash_hex, salt_hex). Generates a new random salt if none given."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, password_hash_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    candidate_hash, _ = hash_password(password, salt)
    # Constant-time comparison -- do not use `==` for secrets.
    return hmac.compare_digest(candidate_hash, password_hash_hex)


# ---------------------------------------------------------------------------
# JWT (HS256 only -- deliberately not supporting "alg": "none" or asymmetric algs,
# which is where most homegrown JWT vulnerabilities come from).
# ---------------------------------------------------------------------------
class TokenError(Exception):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def peek_jwt_subject(token: str) -> str | None:
    """Reads the 'sub' claim WITHOUT verifying the signature -- only ever useful to
    know which user's current password_hash to fetch before doing real validation
    via decode_jwt/validate_password_reset_token. Never trust the return value of
    this function for any authorization decision; it is not proof of anything."""
    try:
        _, payload_b64, _ = token.split(".")
        payload = json.loads(_b64url_decode(payload_b64))
        return payload.get("sub")
    except Exception:
        return None


def create_jwt(payload: dict, secret: str, expires_in_seconds: int = 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    full_payload = {**payload, "iat": now, "exp": now + expires_in_seconds}

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = _b64url_encode(json.dumps(full_payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_jwt(token: str, secret: str) -> dict:
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError:
        raise TokenError("Malformed token (expected 3 dot-separated segments)")

    try:
        header = json.loads(_b64url_decode(header_b64))
    except Exception:
        raise TokenError("Malformed token header")
    if header.get("alg") != "HS256":
        raise TokenError(f"Unsupported or missing algorithm: {header.get('alg')!r}")

    signing_input = f"{header_b64}.{payload_b64}".encode()
    expected_sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(signature_b64)
    except Exception:
        raise TokenError("Malformed token signature")
    if not hmac.compare_digest(expected_sig, actual_sig):
        raise TokenError("Signature verification failed")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise TokenError("Malformed token payload")

    if "exp" in payload and time.time() > payload["exp"]:
        raise TokenError("Token has expired")

    return payload


# ---------------------------------------------------------------------------
# Password reset tokens: a JWT with purpose="password_reset", bound to a fragment
# of the user's CURRENT password hash at the moment the token is issued.
#
# Why bind to the current hash: a stateless JWT can normally be replayed any number
# of times until it expires, even after it's been "used" -- there's no server-side
# revocation list. Binding the token to a hash of the current password_hash gives
# free single-use semantics with zero extra storage: the moment the password
# actually changes, the stored hash changes, so a replayed token's embedded binding
# no longer matches and decode fails. No separate "used tokens" table needed.
# ---------------------------------------------------------------------------
RESET_TOKEN_PURPOSE = "password_reset"


def _hash_binding(password_hash: str) -> str:
    """Short, non-reversible fragment derived from the current password hash, used
    only to detect 'has this password already been changed since the token was
    issued' -- never used for authentication on its own."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def create_password_reset_token(
    username: str, current_password_hash: str, secret: str, expires_in_seconds: int = 900,
) -> str:
    """15-minute default expiry -- short-lived by design, since this token is as
    powerful as the password itself for the window it's valid."""
    return create_jwt(
        {"sub": username, "purpose": RESET_TOKEN_PURPOSE,
         "hb": _hash_binding(current_password_hash)},
        secret, expires_in_seconds=expires_in_seconds,
    )


def validate_password_reset_token(token: str, current_password_hash: str, secret: str) -> str:
    """Returns the username if the token is a valid, unexpired, unused password-reset
    token for an account whose password hasn't changed since issuance. Raises
    TokenError otherwise (with a specific reason -- caller should NOT relay these
    reasons verbatim to an unauthenticated client beyond a generic failure message,
    to avoid leaking account existence/state)."""
    payload = decode_jwt(token, secret)
    if payload.get("purpose") != RESET_TOKEN_PURPOSE:
        raise TokenError("Token is not a password-reset token")
    if payload.get("hb") != _hash_binding(current_password_hash):
        raise TokenError(
            "Token was issued for a different password state -- it has already "
            "been used, or the password was changed by another means since"
        )
    return payload["sub"]
