"""Bounded keyring format for appointment-option HMAC signing.

The keyring is secret material and is intended to live in OpenBao. PostgreSQL may
store only the opaque secret binding plus non-secret configuration metadata.
"""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

_VERSION = 1
_MIN_KEY_BYTES = 32
_MAX_KEYS = 4
DEFAULT_OPTION_TTL = timedelta(minutes=10)
DEFAULT_CLOCK_SKEW = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class AppointmentOptionSigningKey:
    key_id: str
    key: bytes
    verify_until: datetime | None


@dataclass(frozen=True, slots=True)
class AppointmentOptionKeyring:
    active_key_id: str
    keys: tuple[AppointmentOptionSigningKey, ...]

    @property
    def active_key(self) -> bytes:
        for item in self.keys:
            if item.key_id == self.active_key_id:
                return item.key
        raise ValueError("appointment option keyring has no active key")

    def accepted_keys(self, *, now: datetime | None = None) -> dict[str, bytes]:
        observed_at = _aware(now or datetime.now(UTC), "keyring clock")
        accepted: dict[str, bytes] = {}
        for item in self.keys:
            if item.key_id == self.active_key_id:
                accepted[item.key_id] = item.key
            elif item.verify_until is not None and item.verify_until > observed_at:
                accepted[item.key_id] = item.key
        return accepted


def create_appointment_option_keyring(
    key_id: str,
    *,
    key: bytes | None = None,
) -> str:
    normalized = validate_appointment_option_key_id(key_id)
    material = key or secrets.token_bytes(_MIN_KEY_BYTES)
    _validate_key(material)
    return _serialize(
        AppointmentOptionKeyring(
            active_key_id=normalized,
            keys=(
                AppointmentOptionSigningKey(
                    key_id=normalized,
                    key=material,
                    verify_until=None,
                ),
            ),
        )
    )


def rotate_appointment_option_keyring(
    value: str,
    *,
    new_key_id: str,
    now: datetime | None = None,
    token_ttl: timedelta = DEFAULT_OPTION_TTL,
    clock_skew: timedelta = DEFAULT_CLOCK_SKEW,
    new_key: bytes | None = None,
) -> str:
    if token_ttl <= timedelta(0):
        raise ValueError("appointment option token ttl must be positive")
    if clock_skew < timedelta(0) or clock_skew > timedelta(minutes=5):
        raise ValueError("appointment option clock skew must be between zero and five minutes")

    observed_at = _aware(now or datetime.now(UTC), "rotation clock")
    keyring = parse_appointment_option_keyring(value)
    normalized = validate_appointment_option_key_id(new_key_id)
    if any(item.key_id == normalized for item in keyring.keys):
        raise ValueError("new appointment option key id already exists")

    material = new_key or secrets.token_bytes(_MIN_KEY_BYTES)
    _validate_key(material)
    retiring_until = observed_at + token_ttl + clock_skew
    rotated: list[AppointmentOptionSigningKey] = [
        AppointmentOptionSigningKey(normalized, material, None)
    ]
    for item in keyring.keys:
        if item.key_id == keyring.active_key_id:
            rotated.append(
                AppointmentOptionSigningKey(
                    item.key_id,
                    item.key,
                    retiring_until,
                )
            )
        elif item.verify_until is not None and item.verify_until > observed_at:
            rotated.append(item)

    if len(rotated) > _MAX_KEYS:
        rotated = sorted(
            rotated,
            key=lambda item: (
                item.key_id != normalized,
                datetime.max.replace(tzinfo=UTC)
                if item.verify_until is None
                else item.verify_until,
            ),
            reverse=True,
        )[:_MAX_KEYS]
        if not any(item.key_id == normalized for item in rotated):
            raise ValueError("appointment option keyring rotation exceeded key limit")

    return _serialize(AppointmentOptionKeyring(normalized, tuple(rotated)))


def parse_appointment_option_keyring(value: str) -> AppointmentOptionKeyring:
    try:
        raw = cast(object, json.loads(value))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("appointment option keyring must be valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("appointment option keyring must be an object")
    body = cast(dict[str, object], raw)
    if set(body) != {"version", "active_key_id", "keys"} or body.get("version") != _VERSION:
        raise ValueError("appointment option keyring schema is unsupported")

    raw_active = body.get("active_key_id")
    if not isinstance(raw_active, str):
        raise ValueError("appointment option active key id is malformed")
    active_key_id = validate_appointment_option_key_id(raw_active)
    raw_keys = body.get("keys")
    if not isinstance(raw_keys, dict):
        raise ValueError("appointment option keys must be an object")
    key_rows = cast(dict[object, object], raw_keys)
    if not 1 <= len(key_rows) <= _MAX_KEYS:
        raise ValueError("appointment option keyring must contain between one and four keys")

    keys: list[AppointmentOptionSigningKey] = []
    for raw_key_id, raw_record in key_rows.items():
        if not isinstance(raw_key_id, str) or not isinstance(raw_record, dict):
            raise ValueError("appointment option key entry is malformed")
        key_id = validate_appointment_option_key_id(raw_key_id)
        record = cast(dict[str, object], raw_record)
        if set(record) != {"key", "verify_until"}:
            raise ValueError("appointment option key entry schema is unsupported")
        raw_key = record.get("key")
        if not isinstance(raw_key, str):
            raise ValueError("appointment option key material is malformed")
        key = _decode_key(raw_key)
        raw_until = record.get("verify_until")
        verify_until: datetime | None
        if raw_until is None:
            verify_until = None
        elif isinstance(raw_until, str):
            try:
                verify_until = _aware(
                    datetime.fromisoformat(raw_until.replace("Z", "+00:00")),
                    "verify_until",
                )
            except ValueError as exc:
                raise ValueError("appointment option verify_until is malformed") from exc
        else:
            raise ValueError("appointment option verify_until is malformed")
        keys.append(AppointmentOptionSigningKey(key_id, key, verify_until))

    active = next((item for item in keys if item.key_id == active_key_id), None)
    if active is None or active.verify_until is not None:
        raise ValueError("appointment option active key must exist and cannot be retiring")
    for item in keys:
        if item.key_id != active_key_id and item.verify_until is None:
            raise ValueError("non-active appointment option keys require verify_until")
    return AppointmentOptionKeyring(active_key_id, tuple(keys))


def validate_appointment_option_key_id(key_id: str) -> str:
    normalized = key_id.strip()
    if (
        not normalized
        or len(normalized) > 80
        or not all(character.isalnum() or character in "._-" for character in normalized)
    ):
        raise ValueError("appointment option signing key id is invalid")
    return normalized


def _serialize(keyring: AppointmentOptionKeyring) -> str:
    payload = {
        "version": _VERSION,
        "active_key_id": keyring.active_key_id,
        "keys": {
            item.key_id: {
                "key": _encode_key(item.key),
                "verify_until": (
                    None
                    if item.verify_until is None
                    else item.verify_until.astimezone(UTC).isoformat()
                ),
            }
            for item in keyring.keys
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _validate_key(key: bytes) -> None:
    if len(key) < _MIN_KEY_BYTES:
        raise ValueError("appointment option signing keys must contain at least 32 bytes")


def _encode_key(key: bytes) -> str:
    _validate_key(key)
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")


def _decode_key(value: str) -> bytes:
    try:
        raw = value.encode("ascii")
        padding = b"=" * (-len(raw) % 4)
        decoded = base64.b64decode(raw + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("appointment option key material is malformed") from exc
    _validate_key(decoded)
    return decoded


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value
