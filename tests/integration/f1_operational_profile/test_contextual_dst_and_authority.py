from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.domain.availability import LocalTimeResolutionError
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.application.commands.set_organization_public_contacts import (
    OrganizationPublicContactInput,
    SetOrganizationPublicContactsCommand,
    set_organization_public_contacts,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.operational_authority import OperationalAuthorityRequired

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _party(conn: PgConnection, organization_id: UUID, display_name: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.parties (
            organization_id,
            party_kind,
            display_name
        ) VALUES (%s, 'organization', %s)
        RETURNING id
        """,
        (organization_id, display_name),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _configure_new_york_sunday_schedule(
    conn: PgConnection,
    fixture: F1ContextualScenario,
    *,
    local_start: str,
    local_end: str,
) -> None:
    conn.execute(
        """
        UPDATE request_engine.locations
           SET timezone = 'America/New_York'
         WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.location_id),
    )
    conn.execute(
        """
        DELETE FROM request_engine.location_operational_hours
        WHERE organization_id = %s AND location_id = %s
        """,
        (fixture.organization_id, fixture.location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id,
            location_id,
            weekday,
            local_start,
            local_end
        ) VALUES (%s, %s, 6, %s::time, %s::time)
        """,
        (fixture.organization_id, fixture.location_id, local_start, local_end),
    )
    conn.execute(
        """
        DELETE FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
        """,
        (fixture.organization_id, fixture.assignment_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id,
            resource_location_assignment_id,
            weekday,
            local_start,
            local_end
        ) VALUES (%s, %s, 6, %s::time, %s::time)
        """,
        (fixture.organization_id, fixture.assignment_id, local_start, local_end),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_spring_forward_gap_is_rejected_explicitly(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    _configure_new_york_sunday_schedule(
        admin_conn,
        fixture,
        local_start="01:00",
        local_end="04:00",
    )

    with pytest.raises(LocalTimeResolutionError, match="nonexistent local time"):
        await find_appointment_slots(
            PostgresAppointmentAvailabilityReader(session_factory),
            FindAppointmentSlotsQuery(
                organization_id=fixture.organization_id,
                offering_version_id=fixture.offering_version_id,
                location_id=fixture.location_id,
                window_start=datetime(2026, 3, 8, 5, 0, tzinfo=UTC),
                window_end=datetime(2026, 3, 8, 9, 0, tzinfo=UTC),
                limit=20,
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_fall_back_fold_is_rejected_explicitly(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    _configure_new_york_sunday_schedule(
        admin_conn,
        fixture,
        local_start="00:30",
        local_end="03:00",
    )

    with pytest.raises(LocalTimeResolutionError, match="ambiguous local time"):
        await find_appointment_slots(
            PostgresAppointmentAvailabilityReader(session_factory),
            FindAppointmentSlotsQuery(
                organization_id=fixture.organization_id,
                offering_version_id=fixture.offering_version_id,
                location_id=fixture.location_id,
                window_start=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
                window_end=datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
                limit=20,
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_duplicate_party_display_names_do_not_grant_operational_authority(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    authority_name_row = admin_conn.execute(
        """
        SELECT display_name
        FROM request_engine.parties
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.authority_party_id),
    ).fetchone()
    assert authority_name_row is not None
    duplicate_party_id = _party(
        admin_conn,
        fixture.organization_id,
        cast(str, authority_name_row[0]),
    )

    with pytest.raises(OperationalAuthorityRequired):
        await set_organization_public_contacts(
            PostgresOperationalProfileCommands(session_factory),
            SetOrganizationPublicContactsCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                authority_party_id=duplicate_party_id,
                contacts=(
                    OrganizationPublicContactInput(
                        "phone",
                        "+18095550111",
                        "Should not be authorized",
                    ),
                ),
                idempotency_key=f"duplicate-name-authority-{uuid4().hex}",
            ),
        )
