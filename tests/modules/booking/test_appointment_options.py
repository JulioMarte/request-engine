from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.application.errors import AppointmentOptionInvalid
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
    assert decoded.is_contextual
    assert decoded.location_id == slot.location_id
    assert decoded.resources == slot.resources
    assert decoded.amount == Decimal("4000.000000")
    assert decoded.currency == "DOP"
    assert decoded.planned_duration_minutes == 45
    assert decoded.location_operational_revision == 6
    assert decoded.configuration_fingerprint == slot.configuration_fingerprint


@pytest.mark.unit
def test_noncontextual_slot_cannot_be_issued() -> None:
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(ResourceChoice(uuid4(), uuid4()),),
    )

    with pytest.raises(ValueError, match="planned duration"):
        _codec().issue(uuid4(), slot)


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
