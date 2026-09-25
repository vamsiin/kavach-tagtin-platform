import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.auth.security import (
    hash_password, verify_password, create_jwt, decode_jwt, TokenError,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
def test_password_roundtrip():
    h, salt = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", h, salt) is True


def test_password_wrong_password_rejected():
    h, salt = hash_password("correct-horse-battery-staple")
    assert verify_password("wrong-password", h, salt) is False


def test_password_different_salts_for_same_password():
    h1, salt1 = hash_password("same-password")
    h2, salt2 = hash_password("same-password")
    assert salt1 != salt2
    assert h1 != h2  # different salts -> different hashes even for identical passwords


def test_password_hash_is_not_the_plaintext():
    h, _ = hash_password("hunter2")
    assert "hunter2" not in h


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
SECRET = "test-secret-do-not-use-in-prod"


def test_jwt_roundtrip():
    token = create_jwt({"sub": "alice", "role": "designer"}, SECRET)
    payload = decode_jwt(token, SECRET)
    assert payload["sub"] == "alice"
    assert payload["role"] == "designer"
    assert "exp" in payload and "iat" in payload


def test_jwt_wrong_secret_rejected():
    token = create_jwt({"sub": "alice"}, SECRET)
    try:
        decode_jwt(token, "a-different-secret")
        assert False, "expected TokenError"
    except TokenError:
        pass


def test_jwt_tampered_payload_rejected():
    """The classic JWT attack: modify the payload to escalate privilege, keep the
    old signature. Must be rejected."""
    token = create_jwt({"sub": "alice", "role": "designer"}, SECRET)
    header_b64, payload_b64, sig_b64 = token.split(".")

    import base64, json
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    payload["role"] = "admin"  # privilege escalation attempt
    tampered_payload_b64 = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    tampered_token = f"{header_b64}.{tampered_payload_b64}.{sig_b64}"

    try:
        decode_jwt(tampered_token, SECRET)
        assert False, "expected TokenError for tampered payload"
    except TokenError:
        pass


def test_jwt_expired_token_rejected():
    token = create_jwt({"sub": "alice"}, SECRET, expires_in_seconds=-1)
    try:
        decode_jwt(token, SECRET)
        assert False, "expected TokenError for expired token"
    except TokenError as e:
        assert "expired" in str(e).lower()


def test_jwt_alg_none_attack_rejected():
    """The other classic JWT attack: craft a token with alg='none' and no real
    signature, hoping a naive verifier skips signature checking entirely."""
    import base64, json

    header = {"alg": "none", "typ": "JWT"}
    payload = {"sub": "alice", "role": "admin", "exp": time.time() + 3600}
    h_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    forged_token = f"{h_b64}.{p_b64}."

    try:
        decode_jwt(forged_token, SECRET)
        assert False, "expected TokenError for alg=none token"
    except TokenError:
        pass


def test_jwt_malformed_token_rejected():
    try:
        decode_jwt("not-a-real-token", SECRET)
        assert False, "expected TokenError"
    except TokenError:
        pass
