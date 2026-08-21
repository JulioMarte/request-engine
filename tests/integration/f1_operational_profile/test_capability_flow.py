import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Request, status
from psycopg import Connection

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    PostgresContextualReservationCommands,
)
from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import AppointmentOptionStale
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.catalog.adapters.db.business_info_reader import (
    PostgresBusinessInfoReader,
)
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.catalog.application.queries.get_business_info import (
    get_business_info,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    SearchOfferingsQuery,
    search_offerings,
)
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]
_TOKEN_KEY = b"request-engine-f1-capability-flow-test-key-0001"
_OBSERVED_AT = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def _codec() -> SignedAppointmentOptionCodec:
    return SignedAppointmentOptionCodec(
        _TOKEN_KEY,
        ttl=timedelta(minutes=10),
        now=lambda: _OBSERVED_AT,
    )


def _slot_query(fixture: F1ContextualScenario) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=fixture.organization_id,
        offering_version_id=fixture.offering_version_id,
        location_id=fixture.location_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 17, 0, tzinfo=UTC),
        limit=20,
    )


def _command_from_decoded(
    fixture: F1ContextualScenario,
    decoded: object,
) -> BookAppointmentCommand:
    from request_engine.modules.booking.contracts.appointments import AppointmentSlot

    option = cast(AppointmentSlot, decoded)
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=option.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        start_at=option.start_at,
        resources=option.resources,
        idempotency_key=f"f1-capability-flow-{uuid4().hex}",
        location_id=option.location_id,
        allow_subject_override=True,
        expected_planned_duration_minutes=option.planned_duration_minutes,
        expected_amount=option.amount,
        expected_currency=option.currency,
        expected_location_operational_revision=option.location_operational_revision,
        expected_configuration_fingerprint=option.configuration_fingerprint,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_capability_flow_issues_v2_and_books_decoded_option(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)

    business = await get_business_info(
        PostgresBusinessInfoReader(session_factory),
        fixture.organization_id,
    )
    assert any(location.id == fixture.location_id for location in business.locations)

    offerings = await search_offerings(
        PostgresOfferingCatalogReader(session_factory),
        SearchOfferingsQuery(
            organization_id=fixture.organization_id,
            search_text="cardiology",
            location_id=fixture.location_id,
            effective_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        ),
    )
    assert any(item.latest_version.id == fixture.offering_version_id for item in offerings)

    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        _slot_query(fixture),
    )
    assert slots
    slot = slots[0]
    assert slot.start_at == datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    assert slot.amount == Decimal("4000.000000")
    assert slot.currency == "DOP"
    assert slot.planned_duration_minutes == 45
    assert slot.resources[0].resource_location_assignment_id == fixture.assignment_id

    token = _codec().issue(fixture.organization_id, slot)
    assert token.startswith("aptopt_v2.")
    decoded = _codec().decode(fixture.organization_id, token)
    assert decoded.configuration_fingerprint == slot.configuration_fingerprint
    assert decoded.resources == slot.resources

    reservation = await book_appointment(
        PostgresContextualReservationCommands(session_factory),
        _command_from_decoded(fixture, decoded),
    )
    assert reservation.offering_version_id == fixture.offering_version_id
    assert reservation.location_id == fixture.location_id

    commitment = admin_conn.execute(
        """
        SELECT amount, currency, planned_duration_minutes, configuration_fingerprint
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert commitment == (
        Decimal("4000.000000"),
        "DOP",
        45,
        slot.configuration_fingerprint,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_stale_v2_option_maps_to_machine_readable_refresh_and_retry(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        _slot_query(fixture),
    )
    assert slots
    token = _codec().issue(fixture.organization_id, slots[0])
    decoded = _codec().decode(fixture.organization_id, token)

    admin_conn.execute(
        """
        UPDATE request_engine.booking_context_terms
           SET amount = 4100
         WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.context_terms_id),
    )

    with pytest.raises(AppointmentOptionStale) as captured:
        await book_appointment(
            PostgresContextualReservationCommands(session_factory),
            _command_from_decoded(fixture, decoded),
        )

    response = await booking_error_handler(
        Request({"type": "http"}),
        captured.value,
    )
    payload = cast(dict[str, object], json.loads(bytes(response.body)))
    error = cast(dict[str, object], payload["error"])

    assert response.status_code == status.HTTP_409_CONFLICT
    assert error["code"] == "appointment_option_stale"
    assert error["resolution"] == "refresh_and_retry"
    assert error["details"] == {}

    reservation_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone()
    assert reservation_count == (0,)
