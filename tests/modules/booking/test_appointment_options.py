import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.appointment_options import (
    ReloadableSignedAppointmentOptionCodec,
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.application.errors import AppointmentOptionInvalid
from request_engine.platform.security.appointment_option_keyring import (
    create_appointment_option_keyring,
    parse_appointment_option_keyring,
    rotate_appointment_option_keyring,
)
from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    ResourceChoice,
)

_NOW = datetime(2030, 1, 7, 12, tzinfo=UTC)
_KEY = b"request-engine-appointment-option-test-key-0001"


def _codec() -> SignedAppointmentOptionCodec:
    return SignedAppointmentOptionCodec(
        _KEY,
        ttl=timedelta(minutes=10),
        now=lambda: _NOW,
    )


def _contextual_slot() -> AppointmentSlot:
    return AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=45),
        location_id=uuid4(),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=uuid4(),
                assignment_revision=4,
                availability_revision=9,
            ),
        ),
        planned_duration_minutes=45,
        amount=Decimal("4000.000000"),
        currency="DOP",
        location_operational_revision=6,
        configuration_fingerprint="sha256:test-context-observation",
    )


@pytest.mark.unit
def test_current_slot_uses_single_contextual_format_and_roundtrips_provenance() -> None:
    organization_id = uuid4()
    slot = _contextual_slot()

    token = _codec().issue(organization_id, slot)
    decoded = _codec().decode(organization_id, token)

    assert token.startswith("aptopt_v2.")
    assert decoded.location_id == slot.location_id
    assert decoded.resources == slot.resources
    assert decoded.amount == Decimal("4000.000000")
    assert decoded.currency == "DOP"
    assert decoded.planned_duration_minutes == 45
    assert decoded.location_operational_revision == 6
    assert decoded.configuration_fingerprint == slot.configuration_fingerprint


@pytest.mark.unit
def test_legacy_v1_token_prefix_is_rejected() -> None:
    with pytest.raises(AppointmentOptionInvalid, match="unsupported token format"):
        _codec().decode(uuid4(), "aptopt_v1.payload.signature")


@pytest.mark.unit
def test_slot_requires_assignment_provenance_for_every_resource() -> None:
    slot = _contextual_slot()
    contextual = slot.resources[0]
    slot = AppointmentSlot(
        offering_version_id=slot.offering_version_id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=(
            contextual,
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                availability_revision=5,
            ),
        ),
        planned_duration_minutes=slot.planned_duration_minutes,
        amount=slot.amount,
        currency=slot.currency,
        location_operational_revision=slot.location_operational_revision,
        configuration_fingerprint=slot.configuration_fingerprint,
    )

    with pytest.raises(ValueError, match="ResourceLocationAssignment provenance"):
        _codec().issue(uuid4(), slot)


@pytest.mark.unit
def test_slot_requires_availability_revision_for_every_resource() -> None:
    slot = _contextual_slot()
    choice = slot.resources[0]
    slot = AppointmentSlot(
        offering_version_id=slot.offering_version_id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=(
            ResourceChoice(
                requirement_id=choice.requirement_id,
                resource_id=choice.resource_id,
                resource_location_assignment_id=choice.resource_location_assignment_id,
                assignment_revision=choice.assignment_revision,
            ),
        ),
        planned_duration_minutes=slot.planned_duration_minutes,
        amount=slot.amount,
        currency=slot.currency,
        location_operational_revision=slot.location_operational_revision,
        configuration_fingerprint=slot.configuration_fingerprint,
    )

    with pytest.raises(ValueError, match="availability revision"):
        _codec().issue(uuid4(), slot)


@pytest.mark.unit
def test_slot_requires_positive_assignment_revision() -> None:
    slot = _contextual_slot()
    choice = slot.resources[0]
    slot = AppointmentSlot(
        offering_version_id=slot.offering_version_id,
        start_at=slot.start_at,
        end_at=slot.end_at,
        location_id=slot.location_id,
        resources=(
            ResourceChoice(
                requirement_id=choice.requirement_id,
                resource_id=choice.resource_id,
                resource_location_assignment_id=choice.resource_location_assignment_id,
                assignment_revision=0,
                availability_revision=choice.availability_revision,
            ),
        ),
        planned_duration_minutes=slot.planned_duration_minutes,
        amount=slot.amount,
        currency=slot.currency,
        location_operational_revision=slot.location_operational_revision,
        configuration_fingerprint=slot.configuration_fingerprint,
    )

    with pytest.raises(ValueError, match="positive assignment revision"):
        _codec().issue(uuid4(), slot)


@pytest.mark.unit
def test_rotated_keyring_verifies_retiring_key_during_overlap() -> None:
    organization_id = uuid4()
    slot = _contextual_slot()
    old_key = b"request-engine-appointment-option-old-key-0001"
    new_key = b"request-engine-appointment-option-new-key-0002"

    old_codec = SignedAppointmentOptionCodec(
        old_key,
        signing_key_id="appointment-2026-09-a",
        now=lambda: _NOW,
    )
    old_token = old_codec.issue(organization_id, slot)

    rotated = SignedAppointmentOptionCodec(
        new_key,
        signing_key_id="appointment-2026-09-b",
        verification_keys={"appointment-2026-09-a": old_key},
        now=lambda: _NOW,
    )

    assert rotated.decode(organization_id, old_token).location_id == slot.location_id
    new_token = rotated.issue(organization_id, slot)
    assert rotated.decode(organization_id, new_token).location_id == slot.location_id


@pytest.mark.unit
def test_retired_key_is_rejected_after_overlap_is_removed() -> None:
    organization_id = uuid4()
    slot = _contextual_slot()
    old_key = b"request-engine-appointment-option-old-key-0001"
    new_key = b"request-engine-appointment-option-new-key-0002"
    old_token = SignedAppointmentOptionCodec(
        old_key,
        signing_key_id="appointment-old",
        now=lambda: _NOW,
    ).issue(organization_id, slot)

    retired = SignedAppointmentOptionCodec(
        new_key,
        signing_key_id="appointment-new",
        now=lambda: _NOW,
    )

    with pytest.raises(AppointmentOptionInvalid, match="signing key is not accepted"):
        retired.decode(organization_id, old_token)


@pytest.mark.unit
def test_signing_key_id_is_covered_by_signature() -> None:
    organization_id = uuid4()
    token = SignedAppointmentOptionCodec(
        _KEY,
        signing_key_id="appointment-current",
        now=lambda: _NOW,
    ).issue(organization_id, _contextual_slot())
    prefix, payload, signature = token.split(".")
    raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    changed = raw.replace(b"appointment-current", b"appointment-retired")
    changed_payload = base64.urlsafe_b64encode(changed).rstrip(b"=").decode("ascii")
    tampered = f"{prefix}.{changed_payload}.{signature}"

    codec = SignedAppointmentOptionCodec(
        _KEY,
        signing_key_id="appointment-retired",
        now=lambda: _NOW,
    )
    with pytest.raises(AppointmentOptionInvalid, match="signature verification failed"):
        codec.decode(organization_id, tampered)


@pytest.mark.unit
def test_keyring_rejects_conflicting_active_key_material() -> None:
    with pytest.raises(ValueError, match="conflicts"):
        SignedAppointmentOptionCodec(
            _KEY,
            signing_key_id="current",
            verification_keys={"current": b"different-appointment-option-signing-key-0002"},
        )


@pytest.mark.unit
def test_reloadable_codec_switches_active_key_and_keeps_bounded_overlap() -> None:
    organization_id = uuid4()
    slot = _contextual_slot()
    wrapper = ReloadableSignedAppointmentOptionCodec(_KEY, now=lambda: _NOW)
    legacy = wrapper.issue(organization_id, slot)

    initial = create_appointment_option_keyring(
        "k1",
        key=b"appointment-managed-key-one-000000000000001",
    )
    rotated = rotate_appointment_option_keyring(
        initial,
        new_key_id="k2",
        now=_NOW,
        new_key=b"appointment-managed-key-two-000000000000002",
    )
    wrapper.replace_keyring(parse_appointment_option_keyring(rotated))
    managed = wrapper.issue(organization_id, slot)

    assert ".k2" not in managed
    assert wrapper.decode(organization_id, managed).location_id == slot.location_id
    with pytest.raises(AppointmentOptionInvalid):
        wrapper.decode(organization_id, legacy)


@pytest.mark.unit
def test_reloadable_codec_fails_closed_when_disabled() -> None:
    wrapper = ReloadableSignedAppointmentOptionCodec(_KEY, now=lambda: _NOW)
    wrapper.disable()
    with pytest.raises(AppointmentOptionInvalid, match="unavailable"):
        wrapper.issue(uuid4(), _contextual_slot())


@pytest.mark.unit
def test_signed_token_cannot_extend_lifetime_beyond_codec_ttl() -> None:
    organization_id = uuid4()
    token = _codec().issue(organization_id, _contextual_slot())
    prefix, encoded_payload, _signature = token.split(".")
    import json
    import hmac
    import hashlib

    padding = "=" * (-len(encoded_payload) % 4)
    payload = json.loads(base64.urlsafe_b64decode(encoded_payload + padding))
    payload["expires_at"] = (_NOW + timedelta(hours=4)).isoformat()
    tampered_payload = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    forged_signature = base64.urlsafe_b64encode(
        hmac.new(_KEY, f"{prefix}.{tampered_payload}".encode(), hashlib.sha256).digest()
    ).rstrip(b"=").decode()

    with pytest.raises(AppointmentOptionInvalid, match="lifetime"):
        _codec().decode(
            organization_id,
            f"{prefix}.{tampered_payload}.{forged_signature}",
        )
