"""Signed, HttpOnly cookie transport for the admin console.

The signed value is integrity-protected but not opaque or confidential: its
base64url payload contains upstream credential material. HttpOnly prevents
JavaScript access, but this codec is not a server-side session store.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from secrets import token_urlsafe

from request_engine.entrypoints.http.admin_console.json_types import as_mapping


class SessionEncodingError(RuntimeError):
    """Raised when a session value cannot be decoded."""


@dataclass(frozen=True)
class AdminSession:
    """Authenticated operator material currently serialized into the signed cookie."""

    access_token: str
    csrf_token: str
    expires_at: int


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _signature(secret: bytes, body: str) -> str:
    return _b64encode(hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest())


def new_csrf_token() -> str:
    return token_urlsafe(32)


def encode_session(secret: bytes, session: AdminSession) -> str:
    payload = json.dumps(
        {"t": session.access_token, "c": session.csrf_token, "e": session.expires_at},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    body = _b64encode(payload)
    return f"{body}.{_signature(secret, body)}"


def decode_session(secret: bytes, value: str, *, now: float | None = None) -> AdminSession | None:
    """Return the session when the signature is valid and unexpired."""

    if not value or "." not in value:
        return None
    body, _, signature = value.partition(".")
    if not body or not signature:
        return None
    if not hmac.compare_digest(signature, _signature(secret, body)):
        return None
    try:
        data = as_mapping(json.loads(_b64decode(body)))
    except (ValueError, json.JSONDecodeError):
        return None
    access_token = data.get("t")
    csrf_token = data.get("c")
    expires_at = data.get("e")
    if not isinstance(access_token, str) or not isinstance(csrf_token, str):
        return None
    if not isinstance(expires_at, (int, float)) or isinstance(expires_at, bool):
        return None
    reference = time.time() if now is None else now
    if float(expires_at) <= reference:
        return None
    return AdminSession(
        access_token=access_token,
        csrf_token=csrf_token,
        expires_at=int(expires_at),
    )


def encode_value(secret: bytes, payload: dict[str, object]) -> str:
    """Encode an arbitrary signed JSON payload (used for the setup cookie)."""

    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64encode(raw)
    return f"{body}.{_signature(secret, body)}"


def decode_value(secret: bytes, value: str) -> dict[str, object] | None:
    if not value or "." not in value:
        return None
    body, _, signature = value.partition(".")
    if not body or not signature:
        return None
    if not hmac.compare_digest(signature, _signature(secret, body)):
        return None
    try:
        data = as_mapping(json.loads(_b64decode(body)))
    except (ValueError, json.JSONDecodeError):
        return None
    return data


__all__ = [
    "AdminSession",
    "SessionEncodingError",
    "decode_session",
    "decode_value",
    "encode_session",
    "encode_value",
    "new_csrf_token",
]
