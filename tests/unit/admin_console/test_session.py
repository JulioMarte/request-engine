import time

from request_engine.entrypoints.http.admin_console.session import (
    AdminSession,
    decode_session,
    decode_value,
    encode_session,
    encode_value,
    new_csrf_token,
)

_SECRET = b"unit-test-session-secret-32-bytes!!"


def _session(expires_at: int) -> AdminSession:
    return AdminSession(access_token="tok-123", csrf_token=new_csrf_token(), expires_at=expires_at)


def test_session_roundtrip() -> None:
    session = _session(int(time.time()) + 600)
    decoded = decode_session(_SECRET, encode_session(_SECRET, session))
    assert decoded == session


def test_session_rejects_tampering() -> None:
    encoded = encode_session(_SECRET, _session(int(time.time()) + 600))
    body, _, signature = encoded.partition(".")
    tampered = body[:-1] + ("A" if body[-1] != "A" else "B") + "." + signature
    assert decode_session(_SECRET, tampered) is None


def test_session_rejects_expiry() -> None:
    expired = encode_session(_SECRET, _session(int(time.time()) - 1))
    assert decode_session(_SECRET, expired) is None


def test_session_rejects_wrong_secret() -> None:
    encoded = encode_session(_SECRET, _session(int(time.time()) + 600))
    assert decode_session(b"a-different-secret-of-32-bytes!!!", encoded) is None


def test_generic_value_roundtrip() -> None:
    encoded = encode_value(_SECRET, {"t": "setup-token", "c": "csrf", "e": 123})
    assert decode_value(_SECRET, encoded) == {"t": "setup-token", "c": "csrf", "e": 123}


def test_generic_value_rejects_malformed() -> None:
    assert decode_value(_SECRET, "not-a-signed-value") is None
