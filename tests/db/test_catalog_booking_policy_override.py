"""Cross-module proof: catalog booking-policy overrides freeze into bookings.

Catalog owns the offering booking-policy vocabulary; booking consumes it
through the effective-policy read and freezes it into
`reservations.booking_policy_snapshot` at booking time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    PostgresContextualReservationCommands,
)
from request_engine.modules.booking.application.authority import BOOK_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.catalog.adapters.db.offering_policy_commands import (
    PostgresOfferingBookingPolicyCommands,
)
from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    ChannelPolicyInput,
)
from request_engine.modules.catalog.application.errors import (
    OfferingBookingPolicyRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory

pytestmark = pytest.mark.postgres

PgConnection = Connection[Any]

_POLICY_WORLD_PREFIX = "pol-override"


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


class PolicyWorld:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    capability_id: UUID
    requirement_id: UUID
    resource_id: UUID
    assignment_id: UUID


def _seed_policy_world(conn: PgConnection, prefix: str) -> PolicyWorld:
    world = PolicyWorld()
    suffix = uuid4().hex
    world.organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{suffix}", f"{prefix} {suffix}"),
    )
    world.principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (world.organization_id, f"operator-{suffix}"),
    )
    world.subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (world.organization_id, f"Subject {suffix}"),
    )
    world.location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone, public_data
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo', '{}'::jsonb)
        RETURNING id
        """,
        (world.organization_id, f"location-{suffix}", f"Location {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (world.organization_id, world.location_id),
    )

    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (world.organization_id, f"offering-{suffix}", f"Offering {suffix}"),
    )
    world.offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy, public_data
        ) VALUES (%s, %s, 1, 30, true, true, %s::jsonb, '{}'::jsonb)
        RETURNING id
        """,
        (
            world.organization_id,
            offering_id,
            '{"slot_step_minutes": 30}',
        ),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (world.organization_id, world.offering_version_id),
    )
    world.capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (world.organization_id, f"capability-{suffix}", f"Capability {suffix}"),
    )
    world.requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (world.organization_id, world.offering_version_id, world.capability_id),
    )
    world.resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (world.organization_id, f"resource-{suffix}", f"Resource {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (world.organization_id, world.resource_id, world.capability_id),
    )
    world.assignment_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2029-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (world.organization_id, world.resource_id, world.location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (world.organization_id, world.assignment_id),
    )

    for scope_key in ("operations.manage_terms", BOOK_APPOINTMENT_SCOPE):
        conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, valid_until
            ) VALUES (%s, %s, %s, 'self', %s, clock_timestamp() + interval '1 day')
            """,
            (world.organization_id, world.principal_id, world.subject_party_id, scope_key),
        )
    return world


def _override_policy() -> policy_commands.BookingPolicyInput:
    return policy_commands.BookingPolicyInput(
        slot_step_minutes=15,
        attendance=policy_commands.BookingAttendancePolicyInput(
            confirmation_required=True,
            attendance_request_before_minutes=120,
            decline_action="cancel",
            no_show_after_minutes=20,
        ),
        communications=policy_commands.BookingCommunicationsPolicyInput(
            confirmation=True,
            reminders_before_minutes=(1440, 60),
            channel_policy=ChannelPolicyInput(
                channels=("email", "whatsapp"),
                provider_key="probe-provider",
            ),
        ),
        slot_recovery=policy_commands.BookingSlotRecoveryPolicyInput(
            enabled=True,
            minimum_lead_minutes=45,
        ),
    )


def _expected_policy_json() -> dict[str, object]:
    return {
        "slot_step_minutes": 15,
        "attendance": {
            "confirmation_required": True,
            "attendance_request_before_minutes": 120,
            "decline_action": "cancel",
            "no_response_action": "keep",
            "no_show_after_minutes": 20,
        },
        "communications": {
            "confirmation": True,
            "reminders_before_minutes": [1440, 60],
            "channel_policy": {
                "channels": ["email", "whatsapp"],
                "reconcile_after_seconds": 300,
                "retry_after_seconds": 60,
                "provider_key": "probe-provider",
            },
        },
        "slot_recovery": {
            "enabled": True,
            "minimum_lead_minutes": 45,
        },
    }


def _policy_command(world: PolicyWorld, *, expected_revision: int, key: str):
    return policy_commands.SetOfferingVersionBookingPolicyCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        authority_party_id=world.subject_party_id,
        offering_version_id=world.offering_version_id,
        expected_revision=expected_revision,
        policy=_override_policy(),
        idempotency_key=key,
    )


async def _contextual_booking_command(
    world: PolicyWorld,
    session_factory: SessionFactory,
) -> BookAppointmentCommand:
    start_at = datetime(2030, 1, 7, 13, 0, tzinfo=UTC)
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=world.organization_id,
            offering_version_id=world.offering_version_id,
            location_id=world.location_id,
            resource_id=world.resource_id,
            window_start=start_at,
            window_end=start_at + timedelta(hours=1),
            limit=20,
        ),
    )
    slot = next((candidate for candidate in slots if candidate.start_at == start_at), None)
    assert slot is not None
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return BookAppointmentCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        offering_version_id=world.offering_version_id,
        subject_party_id=world.subject_party_id,
        start_at=slot.start_at,
        resources=slot.resources,
        location_id=world.location_id,
        idempotency_key=f"book-{uuid4().hex}",
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
    )


@pytest.mark.asyncio
async def test_booking_policy_override_freezes_into_future_reservations(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_policy_world(admin_conn, _POLICY_WORLD_PREFIX)
    expected = _expected_policy_json()

    state = await PostgresOfferingBookingPolicyCommands(
        command_session_factory
    ).set_offering_version_booking_policy(
        _policy_command(world, expected_revision=0, key=f"policy-{uuid4().hex}")
    )
    assert state.booking_policy_revision == 1

    bootstrap_policy = admin_conn.execute(
        """
        SELECT booking_policy
        FROM request_engine.offering_versions
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, world.offering_version_id),
    ).fetchone()
    assert bootstrap_policy == ({"slot_step_minutes": 30},)

    ledger = admin_conn.execute(
        """
        SELECT revision, booking_policy
        FROM request_engine.offering_version_booking_policies
        WHERE organization_id = %s AND offering_version_id = %s
        """,
        (world.organization_id, world.offering_version_id),
    ).fetchall()
    assert ledger == [(1, expected)]

    reservation = await book_appointment(
        PostgresContextualReservationCommands(command_session_factory),
        await _contextual_booking_command(world, command_session_factory),
    )
    snapshot = admin_conn.execute(
        """
        SELECT booking_policy_snapshot
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (world.organization_id, reservation.id),
    ).fetchone()
    assert snapshot == (expected,)


@pytest.mark.asyncio
async def test_booking_policy_override_replays_idempotently_without_new_revision(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_policy_world(admin_conn, _POLICY_WORLD_PREFIX)
    key = f"policy-{uuid4().hex}"
    commands = PostgresOfferingBookingPolicyCommands(command_session_factory)

    first = await commands.set_offering_version_booking_policy(
        _policy_command(world, expected_revision=0, key=key)
    )
    replay = await commands.set_offering_version_booking_policy(
        _policy_command(world, expected_revision=0, key=key)
    )

    assert replay.booking_policy_revision == first.booking_policy_revision == 1
    count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.offering_version_booking_policies
        WHERE organization_id = %s AND offering_version_id = %s
        """,
        (world.organization_id, world.offering_version_id),
    ).fetchone()
    assert count == (1,)


@pytest.mark.asyncio
async def test_booking_policy_override_stale_expected_revision_conflicts(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    world = _seed_policy_world(admin_conn, _POLICY_WORLD_PREFIX)
    commands = PostgresOfferingBookingPolicyCommands(command_session_factory)
    await commands.set_offering_version_booking_policy(
        _policy_command(world, expected_revision=0, key=f"policy-a-{uuid4().hex}")
    )

    with pytest.raises(OfferingBookingPolicyRevisionConflict) as conflict:
        await commands.set_offering_version_booking_policy(
            _policy_command(world, expected_revision=0, key=f"policy-b-{uuid4().hex}")
        )

    assert conflict.value.actual == 1
    assert conflict.value.expected == 0
