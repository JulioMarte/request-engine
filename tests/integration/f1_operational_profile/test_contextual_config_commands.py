from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.contextual_config_commands import (
    PostgresContextualConfigCommands,
)
from request_engine.modules.booking.application.commands.assign_resource_to_location import (
    AssignResourceToLocationCommand,
    assign_resource_to_location,
)
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    ConfigureBookingContextTermsCommand,
    configure_booking_context_terms,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
)
from request_engine.modules.tenancy.contracts.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    OperationalAuthorityRequired,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(
    conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Context Config Test')
        RETURNING id
        """,
        (f"ctx-config-{suffix}",),
    )
    authority_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'organization', 'Operational Authority')
        RETURNING id
        """,
        (organization_id,),
    )
    supply_principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"supply-{suffix}"),
    )
    terms_principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"terms-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            scope_key, authority_kind
        ) VALUES
            (%s, %s, %s, %s, 'delegated'),
            (%s, %s, %s, %s, 'delegated')
        """,
        (
            organization_id,
            supply_principal_id,
            authority_party_id,
            MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            organization_id,
            terms_principal_id,
            authority_party_id,
            MANAGE_COMMERCIAL_TERMS_SCOPE,
        ),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, 'Dr Context', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"resource-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Consultation')
        RETURNING id
        """,
        (organization_id, f"offering-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version,
            duration_minutes, bookable
        ) VALUES (%s, %s, 1, 30, true)
        RETURNING id
        """,
        (organization_id, offering_id),
    )
    return (
        organization_id,
        authority_party_id,
        supply_principal_id,
        terms_principal_id,
        location_id,
        resource_id,
        offering_version_id,
    )


def _resource_revision(conn: PgConnection, organization_id: UUID, resource_id: UUID) -> int:
    row = conn.execute(
        """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, resource_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_assignment_is_idempotent_and_requires_supply_scope(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    (
        organization_id,
        authority_party_id,
        supply_principal_id,
        terms_principal_id,
        location_id,
        resource_id,
        _,
    ) = _fixture(admin_conn)
    handler = PostgresContextualConfigCommands(session_factory)
    initial_revision = _resource_revision(admin_conn, organization_id, resource_id)
    command = AssignResourceToLocationCommand(
        organization_id=organization_id,
        principal_id=supply_principal_id,
        authority_party_id=authority_party_id,
        resource_id=resource_id,
        location_id=location_id,
        effective_from=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        effective_until=None,
        expected_resource_availability_revision=initial_revision,
        idempotency_key=f"assign-{uuid4().hex}",
    )

    created = await assign_resource_to_location(handler, command)
    replay = await assign_resource_to_location(handler, command)

    assert replay == created
    assert created.resource_availability_revision == initial_revision + 1
    assert _resource_revision(admin_conn, organization_id, resource_id) == initial_revision + 1
    count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND resource_id = %s
        """,
        (organization_id, resource_id),
    ).fetchone()
    assert count == (1,)

    with pytest.raises(OperationalAuthorityRequired):
        await assign_resource_to_location(
            handler,
            AssignResourceToLocationCommand(
                organization_id=organization_id,
                principal_id=terms_principal_id,
                authority_party_id=authority_party_id,
                resource_id=resource_id,
                location_id=location_id,
                effective_from=datetime(2030, 1, 1, tzinfo=UTC),
                effective_until=None,
                expected_resource_availability_revision=created.resource_availability_revision,
                idempotency_key=f"assign-denied-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_assignment_rejects_stale_revision_and_effective_overlap(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    (
        organization_id,
        authority_party_id,
        supply_principal_id,
        _,
        location_id,
        resource_id,
        _,
    ) = _fixture(admin_conn)
    handler = PostgresContextualConfigCommands(session_factory)
    initial_revision = _resource_revision(admin_conn, organization_id, resource_id)
    created = await assign_resource_to_location(
        handler,
        AssignResourceToLocationCommand(
            organization_id=organization_id,
            principal_id=supply_principal_id,
            authority_party_id=authority_party_id,
            resource_id=resource_id,
            location_id=location_id,
            effective_from=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            effective_until=None,
            expected_resource_availability_revision=initial_revision,
            idempotency_key=f"assign-{uuid4().hex}",
        ),
    )

    with pytest.raises(ResourceAvailabilityRevisionConflict):
        await assign_resource_to_location(
            handler,
            AssignResourceToLocationCommand(
                organization_id=organization_id,
                principal_id=supply_principal_id,
                authority_party_id=authority_party_id,
                resource_id=resource_id,
                location_id=location_id,
                effective_from=datetime(2031, 1, 1, tzinfo=UTC),
                effective_until=None,
                expected_resource_availability_revision=initial_revision,
                idempotency_key=f"assign-stale-{uuid4().hex}",
            ),
        )

    with pytest.raises(ContextualConfigurationConflict):
        await assign_resource_to_location(
            handler,
            AssignResourceToLocationCommand(
                organization_id=organization_id,
                principal_id=supply_principal_id,
                authority_party_id=authority_party_id,
                resource_id=resource_id,
                location_id=location_id,
                effective_from=datetime(2027, 1, 1, tzinfo=UTC),
                effective_until=None,
                expected_resource_availability_revision=created.resource_availability_revision,
                idempotency_key=f"assign-overlap-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_context_terms_are_idempotent_scoped_and_overlap_safe(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    (
        organization_id,
        authority_party_id,
        supply_principal_id,
        terms_principal_id,
        location_id,
        resource_id,
        offering_version_id,
    ) = _fixture(admin_conn)
    handler = PostgresContextualConfigCommands(session_factory)
    assignment = await assign_resource_to_location(
        handler,
        AssignResourceToLocationCommand(
            organization_id=organization_id,
            principal_id=supply_principal_id,
            authority_party_id=authority_party_id,
            resource_id=resource_id,
            location_id=location_id,
            effective_from=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            effective_until=None,
            expected_resource_availability_revision=_resource_revision(
                admin_conn, organization_id, resource_id
            ),
            idempotency_key=f"assign-{uuid4().hex}",
        ),
    )
    command = ConfigureBookingContextTermsCommand(
        organization_id=organization_id,
        principal_id=terms_principal_id,
        authority_party_id=authority_party_id,
        resource_location_assignment_id=assignment.assignment_id,
        offering_version_id=offering_version_id,
        effective_from=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        effective_until=None,
        amount=Decimal("4000"),
        currency="DOP",
        planned_duration_minutes=45,
        bookable=True,
        idempotency_key=f"terms-{uuid4().hex}",
    )

    created = await configure_booking_context_terms(handler, command)
    replay = await configure_booking_context_terms(handler, command)
    assert replay == created
    count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.booking_context_terms
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
          AND offering_version_id = %s
        """,
        (organization_id, assignment.assignment_id, offering_version_id),
    ).fetchone()
    assert count == (1,)

    with pytest.raises(OperationalAuthorityRequired):
        await configure_booking_context_terms(
            handler,
            ConfigureBookingContextTermsCommand(
                organization_id=organization_id,
                principal_id=supply_principal_id,
                authority_party_id=authority_party_id,
                resource_location_assignment_id=assignment.assignment_id,
                offering_version_id=offering_version_id,
                effective_from=datetime(2030, 1, 1, tzinfo=UTC),
                effective_until=None,
                amount=Decimal("4200"),
                currency="DOP",
                planned_duration_minutes=45,
                bookable=True,
                idempotency_key=f"terms-denied-{uuid4().hex}",
            ),
        )

    with pytest.raises(ContextualConfigurationConflict):
        await configure_booking_context_terms(
            handler,
            ConfigureBookingContextTermsCommand(
                organization_id=organization_id,
                principal_id=terms_principal_id,
                authority_party_id=authority_party_id,
                resource_location_assignment_id=assignment.assignment_id,
                offering_version_id=offering_version_id,
                effective_from=datetime(2027, 1, 1, tzinfo=UTC),
                effective_until=None,
                amount=Decimal("4100"),
                currency="DOP",
                planned_duration_minutes=45,
                bookable=True,
                idempotency_key=f"terms-overlap-{uuid4().hex}",
            ),
        )
