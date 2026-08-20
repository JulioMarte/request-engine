from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice


_NOW = datetime(2030, 1, 7, 12, tzinfo=UTC)
_KEY = b"request-engine-appointment-option-test-key-0001"


def _codec() -> SignedAppointmentOptionCodec:
    return SignedAppointmentOptionCodec(
        _KEY,
        ttl=timedelta(minutes=10),
        now=lambda: _NOW,
    )


@pytest.mark.unit
def test_released_v3_slot_still_uses_v1_token() -> None:
    organization_id = uuid4()
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(ResourceChoice(uuid4(), uuid4()),),
    )

    token = _codec().issue(organization_id, slot)
    decoded = _codec().decode(organization_id, token)

    assert token.startswith("aptopt_v1.")
    assert decoded.offering_version_id == slot.offering_version_id
    assert decoded.resources == slot.resources
    assert decoded.configuration_fingerprint is None
    assert not decoded.is_contextual


@pytest.mark.unit
def test_contextual_slot_uses_v2_and_roundtrips_material_observation() -> None:
    organization_id = uuid4()
    assignment_id = uuid4()
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=45),
        location_id=uuid4(),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=assignment_id,
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
def test_contextual_slot_v2_supports_mixed_contextual_and_legacy_resources() -> None:
    organization_id = uuid4()
    contextual = ResourceChoice(
        requirement_id=uuid4(),
        resource_id=uuid4(),
        resource_location_assignment_id=uuid4(),
        assignment_revision=3,
        availability_revision=8,
    )
    legacy = ResourceChoice(
        requirement_id=uuid4(),
        resource_id=uuid4(),
        availability_revision=5,
    )
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=2),
        end_at=_NOW + timedelta(hours=2, minutes=30),
        location_id=uuid4(),
        resources=(contextual, legacy),
        planned_duration_minutes=30,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=2,
        configuration_fingerprint="sha256:mixed-observation",
    )

    token = _codec().issue(organization_id, slot)
    decoded = _codec().decode(organization_id, token)

    assert token.startswith("aptopt_v2.")
    assert decoded.is_contextual
    assert set(decoded.resources) == {contextual, legacy}
    decoded_legacy = next(
        choice for choice in decoded.resources if choice.resource_id == legacy.resource_id
    )
    assert decoded_legacy.resource_location_assignment_id is None
    assert decoded_legacy.assignment_revision is None
    assert decoded_legacy.availability_revision == 5


@pytest.mark.unit
def test_contextual_slot_requires_availability_revision_for_every_resource() -> None:
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=uuid4(),
                assignment_revision=1,
            ),
        ),
        planned_duration_minutes=30,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:incomplete",
    )

    with pytest.raises(ValueError, match="availability revision"):
        _codec().issue(uuid4(), slot)


@pytest.mark.unit
def test_contextual_slot_rejects_partial_assignment_observation() -> None:
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(
            ResourceChoice(
                requirement_id=uuid4(),
                resource_id=uuid4(),
                resource_location_assignment_id=uuid4(),
                availability_revision=1,
            ),
        ),
        planned_duration_minutes=30,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:partial-assignment",
    )

    with pytest.raises(ValueError, match="present together"):
        _codec().issue(uuid4(), slot)
