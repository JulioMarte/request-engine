import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from request_engine.modules.booking.application.errors import (
    AppointmentOptionExpired,
    AppointmentOptionInvalid,
)
from request_engine.modules.booking.contracts.appointment_options import DecodedAppointmentOption
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice

_TOKEN_PREFIX = "aptopt_v1"
_FORMAT_VERSION = 1


class SignedAppointmentOptionCodec:
    """Stateless HMAC codec for short-lived concrete appointment selections."""

    def __init__(
        self,
        signing_key: bytes,
        *,
        ttl: timedelta = timedelta(minutes=10),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("appointment option signing key must contain at least 32 bytes")
        if ttl <= timedelta(0):
            raise ValueError("appointment option ttl must be positive")
        self._signing_key = signing_key
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))

    def issue(self, organization_id: UUID, slot: AppointmentSlot) -> str:
        now = _require_aware(self._now(), "codec clock")
        expires_at = now + self._ttl
        resources = sorted(
            slot.resources,
            key=lambda choice: (str(choice.requirement_id), str(choice.resource_id)),
        )
        payload: dict[str, object] = {
            "v": _FORMAT_VERSION,
            "organization_id": str(organization_id),
            "offering_version_id": str(slot.offering_version_id),
            "start_at": _require_aware(slot.start_at, "slot.start_at").isoformat(),
            "end_at": _require_aware(slot.end_at, "slot.end_at").isoformat(),
            "location_id": str(slot.location_id) if slot.location_id is not None else None,
            "resources": [
                {
                    "requirement_id": str(choice.requirement_id),
                    "resource_id": str(choice.resource_id),
                }
                for choice in resources
            ],
            "issued_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        encoded_payload = _encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _signature(self._signing_key, encoded_payload)
        return f"{_TOKEN_PREFIX}.{encoded_payload}.{_encode(signature)}"

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
            raise AppointmentOptionInvalid("unsupported token format")
        encoded_payload, encoded_signature = parts[1], parts[2]
        try:
            supplied_signature = _decode(encoded_signature)
        except ValueError as exc:
            raise AppointmentOptionInvalid("malformed signature") from exc
        expected_signature = _signature(self._signing_key, encoded_payload)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise AppointmentOptionInvalid("signature verification failed")

        try:
            decoded = cast(object, json.loads(_decode(encoded_payload).decode("utf-8")))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            raise AppointmentOptionInvalid("malformed payload") from exc
        if not isinstance(decoded, dict):
            raise AppointmentOptionInvalid("payload must be an object")
        payload = cast(dict[str, object], decoded)

        if payload.get("v") != _FORMAT_VERSION:
            raise AppointmentOptionInvalid("unsupported payload version")
        token_organization_id = _uuid_field(payload, "organization_id")
        if token_organization_id != organization_id:
            raise AppointmentOptionInvalid("token belongs to a different Organization")

        start_at = _datetime_field(payload, "start_at")
        end_at = _datetime_field(payload, "end_at")
        expires_at = _datetime_field(payload, "expires_at")
        _datetime_field(payload, "issued_at")
        if end_at <= start_at:
            raise AppointmentOptionInvalid("slot interval is invalid")
        if expires_at <= _require_aware(self._now(), "codec clock"):
            raise AppointmentOptionExpired()

        location_raw = payload.get("location_id")
        if location_raw is not None and not isinstance(location_raw, str):
            raise AppointmentOptionInvalid("location_id is malformed")
        try:
            location_id = UUID(location_raw) if isinstance(location_raw, str) else None
        except ValueError as exc:
            raise AppointmentOptionInvalid("location_id is malformed") from exc

        resources_raw = payload.get("resources")
        if not isinstance(resources_raw, list) or not resources_raw:
            raise AppointmentOptionInvalid("resources are missing")
        resource_items = cast(list[object], resources_raw)
        resources: list[ResourceChoice] = []
        seen_requirements: set[UUID] = set()
        for raw in resource_items:
            if not isinstance(raw, dict):
                raise AppointmentOptionInvalid("resource selection is malformed")
            item = cast(dict[str, object], raw)
            requirement_id = _uuid_field(item, "requirement_id")
            resource_id = _uuid_field(item, "resource_id")
            if requirement_id in seen_requirements:
                raise AppointmentOptionInvalid("duplicate requirement selection")
            seen_requirements.add(requirement_id)
            resources.append(ResourceChoice(requirement_id, resource_id))
        resources.sort(key=lambda choice: (str(choice.requirement_id), str(choice.resource_id)))

        return DecodedAppointmentOption(
            organization_id=organization_id,
            offering_version_id=_uuid_field(payload, "offering_version_id"),
            start_at=start_at,
            end_at=end_at,
            location_id=location_id,
            resources=tuple(resources),
            expires_at=expires_at,
        )


def _signature(signing_key: bytes, encoded_payload: str) -> bytes:
    message = f"{_TOKEN_PREFIX}.{encoded_payload}".encode("ascii")
    return hmac.new(signing_key, message, hashlib.sha256).digest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise ValueError("invalid base64url value") from exc


def _uuid_field(payload: dict[str, object], key: str) -> UUID:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise AppointmentOptionInvalid(f"{key} is malformed") from exc


def _datetime_field(payload: dict[str, object], key: str) -> datetime:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    try:
        return _require_aware(datetime.fromisoformat(raw), key)
    except ValueError as exc:
        raise AppointmentOptionInvalid(f"{key} is malformed") from exc


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value
