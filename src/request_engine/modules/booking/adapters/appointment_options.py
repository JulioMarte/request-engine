import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from request_engine.modules.booking.application.errors import (
    AppointmentOptionExpired,
    AppointmentOptionInvalid,
)
from request_engine.modules.booking.contracts.appointment_options import DecodedAppointmentOption
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice

_V1_PREFIX = "aptopt_v1"
_V2_PREFIX = "aptopt_v2"
_V1_FORMAT = 1
_V2_FORMAT = 2


@dataclass(frozen=True, slots=True)
class _DecodedCommon:
    organization_id: UUID
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    expires_at: datetime


class SignedAppointmentOptionCodec:
    """Stateless HMAC codec for short-lived concrete appointment selections.

    V1 remains the released V3 slot-selection format. V2 is issued only when an
    AppointmentSlot carries an F1 material configuration fingerprint and binds
    the contextual observations that authoritative booking must revalidate.

    A V2 option may contain a mixed resource selection during the compatibility
    period: contextual Resources carry assignment provenance while legacy V3
    Resources carry only their availability revision. This keeps the complete
    selected set stale-detectable without inventing assignment provenance.
    """

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
        if slot.configuration_fingerprint is None:
            return self._issue_v1(organization_id, slot)
        return self._issue_v2(organization_id, slot)

    def decode(self, organization_id: UUID, token: str) -> DecodedAppointmentOption:
        parts = token.split(".")
        if len(parts) != 3:
            raise AppointmentOptionInvalid("unsupported token format")
        prefix = parts[0]
        if prefix not in {_V1_PREFIX, _V2_PREFIX}:
            raise AppointmentOptionInvalid("unsupported token format")

        encoded_payload, encoded_signature = parts[1], parts[2]
        self._verify_signature(prefix, encoded_payload, encoded_signature)
        payload = _payload(encoded_payload)

        if prefix == _V1_PREFIX:
            return self._decode_v1(organization_id, payload)
        return self._decode_v2(organization_id, payload)

    def _issue_v1(self, organization_id: UUID, slot: AppointmentSlot) -> str:
        now = _require_aware(self._now(), "codec clock")
        expires_at = now + self._ttl
        resources = _sorted_resources(slot.resources)
        payload: dict[str, object] = {
            "v": _V1_FORMAT,
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
        return self._encode_signed(_V1_PREFIX, payload)

    def _issue_v2(self, organization_id: UUID, slot: AppointmentSlot) -> str:
        _validate_contextual_slot(slot)
        now = _require_aware(self._now(), "codec clock")
        expires_at = now + self._ttl
        resources = _sorted_resources(slot.resources)
        amount = cast(Decimal, slot.amount)
        currency = cast(str, slot.currency)
        duration = cast(int, slot.planned_duration_minutes)
        location_revision = cast(int, slot.location_operational_revision)
        fingerprint = cast(str, slot.configuration_fingerprint)

        payload: dict[str, object] = {
            "v": _V2_FORMAT,
            "organization_id": str(organization_id),
            "offering_version_id": str(slot.offering_version_id),
            "start_at": _require_aware(slot.start_at, "slot.start_at").isoformat(),
            "end_at": _require_aware(slot.end_at, "slot.end_at").isoformat(),
            "location_id": str(slot.location_id),
            "resources": [
                {
                    "requirement_id": str(choice.requirement_id),
                    "resource_id": str(choice.resource_id),
                    "resource_location_assignment_id": (
                        str(choice.resource_location_assignment_id)
                        if choice.resource_location_assignment_id is not None
                        else None
                    ),
                    "assignment_revision": choice.assignment_revision,
                    "availability_revision": choice.availability_revision,
                }
                for choice in resources
            ],
            "planned_duration_minutes": duration,
            "amount": str(amount),
            "currency": currency,
            "location_operational_revision": location_revision,
            "configuration_fingerprint": fingerprint,
            "issued_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        return self._encode_signed(_V2_PREFIX, payload)

    def _encode_signed(self, prefix: str, payload: dict[str, object]) -> str:
        encoded_payload = _encode(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        signature = _signature(self._signing_key, prefix, encoded_payload)
        return f"{prefix}.{encoded_payload}.{_encode(signature)}"

    def _verify_signature(
        self,
        prefix: str,
        encoded_payload: str,
        encoded_signature: str,
    ) -> None:
        try:
            supplied_signature = _decode(encoded_signature)
        except ValueError as exc:
            raise AppointmentOptionInvalid("malformed signature") from exc
        expected_signature = _signature(self._signing_key, prefix, encoded_payload)
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise AppointmentOptionInvalid("signature verification failed")

    def _decode_v1(
        self,
        organization_id: UUID,
        payload: dict[str, object],
    ) -> DecodedAppointmentOption:
        if payload.get("v") != _V1_FORMAT:
            raise AppointmentOptionInvalid("unsupported payload version")
        common = self._decode_common(organization_id, payload, contextual=False)
        return DecodedAppointmentOption(
            organization_id=common.organization_id,
            offering_version_id=common.offering_version_id,
            start_at=common.start_at,
            end_at=common.end_at,
            location_id=common.location_id,
            resources=common.resources,
            expires_at=common.expires_at,
        )

    def _decode_v2(
        self,
        organization_id: UUID,
        payload: dict[str, object],
    ) -> DecodedAppointmentOption:
        if payload.get("v") != _V2_FORMAT:
            raise AppointmentOptionInvalid("unsupported payload version")
        common = self._decode_common(organization_id, payload, contextual=True)
        if common.location_id is None:
            raise AppointmentOptionInvalid("contextual option requires location_id")

        duration = _positive_int_field(payload, "planned_duration_minutes")
        amount = _decimal_field(payload, "amount")
        currency = _currency_field(payload, "currency")
        location_revision = _positive_int_field(payload, "location_operational_revision")
        fingerprint = payload.get("configuration_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise AppointmentOptionInvalid("configuration_fingerprint is malformed")

        return DecodedAppointmentOption(
            organization_id=common.organization_id,
            offering_version_id=common.offering_version_id,
            start_at=common.start_at,
            end_at=common.end_at,
            location_id=common.location_id,
            resources=common.resources,
            expires_at=common.expires_at,
            planned_duration_minutes=duration,
            amount=amount,
            currency=currency,
            location_operational_revision=location_revision,
            configuration_fingerprint=fingerprint,
        )

    def _decode_common(
        self,
        organization_id: UUID,
        payload: dict[str, object],
        *,
        contextual: bool,
    ) -> _DecodedCommon:
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

        return _DecodedCommon(
            organization_id=organization_id,
            offering_version_id=_uuid_field(payload, "offering_version_id"),
            start_at=start_at,
            end_at=end_at,
            location_id=location_id,
            resources=_resource_fields(payload, contextual=contextual),
            expires_at=expires_at,
        )


def _validate_contextual_slot(slot: AppointmentSlot) -> None:
    if slot.location_id is None:
        raise ValueError("contextual AppointmentSlot requires location_id")
    if slot.planned_duration_minutes is None or slot.planned_duration_minutes <= 0:
        raise ValueError("contextual AppointmentSlot requires positive planned duration")
    if slot.amount is None or slot.amount < 0:
        raise ValueError("contextual AppointmentSlot requires non-negative amount")
    if slot.currency is None or not _is_currency(slot.currency):
        raise ValueError("contextual AppointmentSlot requires uppercase three-letter currency")
    if slot.location_operational_revision is None or slot.location_operational_revision <= 0:
        raise ValueError("contextual AppointmentSlot requires Location operational revision")
    if not slot.configuration_fingerprint:
        raise ValueError("contextual AppointmentSlot requires configuration fingerprint")
    if not slot.resources:
        raise ValueError("contextual AppointmentSlot requires Resources")

    contextual_count = 0
    for choice in slot.resources:
        if choice.availability_revision is None or choice.availability_revision <= 0:
            raise ValueError("contextual ResourceChoice requires availability revision")
        assignment_id = choice.resource_location_assignment_id
        assignment_revision = choice.assignment_revision
        if (assignment_id is None) != (assignment_revision is None):
            raise ValueError(
                "contextual ResourceChoice assignment id and revision must be present together"
            )
        if assignment_revision is not None:
            if assignment_revision <= 0:
                raise ValueError("contextual ResourceChoice requires positive assignment revision")
            contextual_count += 1

    if contextual_count == 0:
        raise ValueError("aptopt_v2 requires at least one contextual ResourceLocationAssignment")


def _resource_fields(
    payload: dict[str, object],
    *,
    contextual: bool,
) -> tuple[ResourceChoice, ...]:
    resources_raw = payload.get("resources")
    if not isinstance(resources_raw, list) or not resources_raw:
        raise AppointmentOptionInvalid("resources are missing")
    resource_items = cast(list[object], resources_raw)
    resources: list[ResourceChoice] = []
    seen_requirements: set[UUID] = set()
    contextual_count = 0
    for raw in resource_items:
        if not isinstance(raw, dict):
            raise AppointmentOptionInvalid("resource selection is malformed")
        item = cast(dict[str, object], raw)
        requirement_id = _uuid_field(item, "requirement_id")
        resource_id = _uuid_field(item, "resource_id")
        if requirement_id in seen_requirements:
            raise AppointmentOptionInvalid("duplicate requirement selection")
        seen_requirements.add(requirement_id)

        if contextual:
            assignment_id = _optional_uuid_field(item, "resource_location_assignment_id")
            assignment_revision = _optional_positive_int_field(item, "assignment_revision")
            if (assignment_id is None) != (assignment_revision is None):
                raise AppointmentOptionInvalid(
                    "resource assignment id and revision must be present together"
                )
            if assignment_id is not None:
                contextual_count += 1
            resources.append(
                ResourceChoice(
                    requirement_id=requirement_id,
                    resource_id=resource_id,
                    resource_location_assignment_id=assignment_id,
                    assignment_revision=assignment_revision,
                    availability_revision=_positive_int_field(item, "availability_revision"),
                )
            )
        else:
            resources.append(ResourceChoice(requirement_id, resource_id))

    if contextual and contextual_count == 0:
        raise AppointmentOptionInvalid("aptopt_v2 requires a contextual ResourceLocationAssignment")
    return _sorted_resources(tuple(resources))


def _sorted_resources(resources: tuple[ResourceChoice, ...]) -> tuple[ResourceChoice, ...]:
    return tuple(
        sorted(
            resources,
            key=lambda choice: (str(choice.requirement_id), str(choice.resource_id)),
        )
    )


def _signature(signing_key: bytes, prefix: str, encoded_payload: str) -> bytes:
    message = f"{prefix}.{encoded_payload}".encode("ascii")
    return hmac.new(signing_key, message, hashlib.sha256).digest()


def _payload(encoded_payload: str) -> dict[str, object]:
    try:
        decoded = cast(object, json.loads(_decode(encoded_payload).decode("utf-8")))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise AppointmentOptionInvalid("malformed payload") from exc
    if not isinstance(decoded, dict):
        raise AppointmentOptionInvalid("payload must be an object")
    return cast(dict[str, object], decoded)


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


def _optional_uuid_field(payload: dict[str, object], key: str) -> UUID | None:
    raw = payload.get(key)
    if raw is None:
        return None
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


def _positive_int_field(payload: dict[str, object], key: str) -> int:
    raw = payload.get(key)
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise AppointmentOptionInvalid(f"{key} is malformed")
    return raw


def _optional_positive_int_field(payload: dict[str, object], key: str) -> int | None:
    raw = payload.get(key)
    if raw is None:
        return None
    if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
        raise AppointmentOptionInvalid(f"{key} is malformed")
    return raw


def _decimal_field(payload: dict[str, object], key: str) -> Decimal:
    raw = payload.get(key)
    if not isinstance(raw, str):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise AppointmentOptionInvalid(f"{key} is malformed") from exc
    if not value.is_finite() or value < 0:
        raise AppointmentOptionInvalid(f"{key} is malformed")
    return value


def _currency_field(payload: dict[str, object], key: str) -> str:
    raw = payload.get(key)
    if not isinstance(raw, str) or not _is_currency(raw):
        raise AppointmentOptionInvalid(f"{key} is malformed")
    return raw


def _is_currency(value: str) -> bool:
    return len(value) == 3 and value.isalpha() and value == value.upper()


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value
