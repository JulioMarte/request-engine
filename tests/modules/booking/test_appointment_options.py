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
def test_contextual_slot_requires_complete_assignment_observation() -> None:
    slot = AppointmentSlot(
        offering_version_id=uuid4(),
        start_at=_NOW + timedelta(hours=1),
        end_at=_NOW + timedelta(hours=1, minutes=30),
        location_id=uuid4(),
        resources=(ResourceChoice(uuid4(), uuid4()),),
        planned_duration_minutes=30,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:incomplete",
    )

    with pytest.raises(ValueError, match="ResourceLocationAssignment"):
        _codec().issue(uuid4(), slot)
