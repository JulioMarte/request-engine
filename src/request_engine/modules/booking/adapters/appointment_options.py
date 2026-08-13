import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from request_engine.modules.booking.application.errors import AppointmentOptionExpired, AppointmentOptionInvalid
from request_engine.modules.booking.contracts.appointment_options import DecodedAppointmentOption
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice

_PREFIX = "aptopt_v1"
_VERSION = 1


class SignedAppointmentOptionCodec:
    def __init__(self, signing_key: bytes, *, ttl: timedelta = timedelta(minutes=10), now: Callable[[], datetime] | None = None) -> None:
        if len(signing_key) < 32:
            raise ValueError("appointment option signing key must contain at least 32 bytes")
        if ttl <= timedelta(0):
            raise ValueError("appointment option ttl must be positive")
        self._key = signing_key
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))

    def issue(self, organization_id: UUID, slot: AppointmentSlot) -> str:
        issued_at = _aware(self._now(), "codec clock")
        resources = sorted(slot.resources, key=lambda item: (str(item.requirement_id), str(item.resource_id)))
        payload: dict[str, object] = {
            "v": _VERSION,
            "organization_id": str(organization_id),
            "offering_version_id": str(slot.offering_version_id),
            "start_at": _aware(slot.start_at, "slot.start_at").isoformat(),
            "end_at": _aware(slot.end_at, "slot.end_at").isoformat(),
            "location_id": str(slot.location_id) if slot.location_id is not None else None,
            "resources": [{"requirement_id": str(item.requirement_id), "resource_id": str(item.resource_id)} for item in resources],
            "issued_at": issued_at.isoformat(),
            "expires_at": (issued_at + self._ttl).isoformat(),
        }
        encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        signature = _b64(hmac.new(self._key, f"{_PREFIX}.{encoded}".encode("ascii"), hashlib.sha256).digest())
        return f"{_PREFIX}.{encoded}.{signature}"

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _PREFIX:
            raise AppointmentOptionInvalid("unsupported token format")
        encoded, supplied = parts[1], parts[2]
        expected = _b64(hmac.new(self._key, f"{_PREFIX}.{encoded}".encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise AppointmentOptionInvalid("signature verification failed")
        try:
            decoded = json.loads(_unb64(encoded).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise AppointmentOptionInvalid("malformed payload") from exc
        if not isinstance(decoded, dict):
            raise AppointmentOptionInvalid("payload must be an object")
        payload = cast(dict[str, object], decoded)
        if payload.get("v") != _VERSION:
            raise AppointmentOptionInvalid("unsupported payload version")
        if _uuid(payload, "organization_id") != organization_id:
            raise AppointmentOptionInvalid("token belongs to a different Organization")
        start_at = _dt(payload, "start_at")
        end_at = _dt(payload, "end_at")
        expires_at = _dt(payload, "expires_at")
        if end_at <= start_at:
            raise AppointmentOptionInvalid("slot interval is invalid")
        if expires_at <= _aware(self._now(), "codec clock"):
            raise AppointmentOptionExpired()
        raw_location = payload.get("location_id")
        if raw_location is not None and not isinstance(raw_location, str):
            raise AppointmentOptionInvalid("location_id is malformed")
        location_id = UUID(raw_location) if isinstance(raw_location, str) else None
        raw_resources = payload.get("resources")
        if not isinstance(raw_resources, list) or not raw_resources:
            raise AppointmentOptionInvalid("resources are missing")
        resources: list[ResourceChoice] = []
        seen: set[UUID] = set()
        for raw in cast(list[object], raw_resources):
            if not isinstance(raw, dict):
                raise AppointmentOptionInvalid("resource selection is malformed")
            item = cast(dict[str, object], raw)
            requirement_id = _uuid(item, "requirement_id")
            if requirement_id in seen:
                raise AppointmentOptionInvalid("duplicate requirement selection")
            seen.add(requirement_id)
            resources.append(ResourceChoice(requirement_id, _uuid(item, "resource_id")))
        resources.sort(key=lambda item: (str(item.requirement_id), str(item.resource_id)))
        return DecodedAppointmentOption(organization_id=organization_id, offering_version_id=_uuid(payload, "offering_version_id"), start_at=start_at, end_at=end_at, location_id=location_id, resources=tuple(resources), expires_at=expires_at)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode((value + "=" * (-len(value) % 4)).encode("ascii"))


def _uuid(payload: dict[str, object], key: str) -> UUID:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise AppointmentOptionInvalid(f"{key} is malformed") from exc


def _dt(payload: dict[str, object], key: str) -> datetime:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    try:
        return _aware(datetime.fromisoformat(raw), key)
    except ValueError as exc:
        raise AppointmentOptionInvalid(f"{key} is malformed") from exc


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value
