from datetime import time
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.operational_config_commands import (
    PostgresOperationalConfigCommands,
)
from request_engine.modules.catalog.application.commands.set_location_operational_hours import (
    LocationOperationalHoursInput,
    SetLocationOperationalHoursCommand,
    set_location_operational_hours,
)
from request_engine.modules.catalog.application.errors import LocationOperationalRevisionConflict
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.application.commands import (
    update_organization_operational_profile as profile_command,
)
from request_engine.modules.tenancy.contracts.operational_authority import (
    MANAGE_OPERATIONAL_PROFILE_SCOPE,
    OperationalAuthorityRequired,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


def _id(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _location_revision(conn: PgConnection, organization_id: UUID, location_id: UUID) -> int:
    row = conn.execute(
        """
        SELECT operational_revision
        FROM request_engine.locations
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, location_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _authority_fixture(
    conn: PgConnection,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _id(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Operational Test') RETURNING id
        """,
        (f"ops-{suffix}",),
    )
    authority_party_id = _id(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'organization', 'Operations Authority') RETURNING id
        """,
        (organization_id,),
    )
    authorized_principal_id = _id(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s) RETURNING id
        """,
        (organization_id, f"authorized-{suffix}"),
    )
    unauthorized_principal_id = _id(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s) RETURNING id
        """,
        (organization_id, f"unauthorized-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            scope_key, authority_kind
        ) VALUES (%s, %s, %s, %s, 'delegated')
        """,
        (
            organization_id,
            authorized_principal_id,
            authority_party_id,
            MANAGE_OPERATIONAL_PROFILE_SCOPE,
        ),
    )
    location_id = _id(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main', 'America/Santo_Domingo') RETURNING id
        """,
        (organization_id, f"main-{suffix}",),
    )
    return (
        organization_id,
        authority_party_id,
        authorized_principal_id,
        unauthorized_principal_id,
        location_id,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_operational_profile_requires_exact_representation_scope(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    (
        organization_id,
        authority_party_id,
        authorized_principal_id,
        unauthorized_principal_id,
        _,
    ) = _authority_fixture(admin_conn)
    commands = PostgresOperationalProfileCommands(session_factory)

    profile = await profile_command.update_organization_operational_profile(
        commands,
        profile_command.UpdateOrganizationOperationalProfileCommand(
            organization_id=organization_id,
            principal_id=authorized_principal_id,
            authority_party_id=authority_party_id,
            legal_name="Operational Test SRL",
            default_timezone="America/Santo_Domingo",
            default_locale="es-DO",
            default_currency="DOP",
            operational_status="active",
            idempotency_key=f"profile-{uuid4().hex}",
        ),
    )
    assert profile.legal_name == "Operational Test SRL"
    assert profile.default_currency == "DOP"

    with pytest.raises(OperationalAuthorityRequired):
        await profile_command.update_organization_operational_profile(
            commands,
            profile_command.UpdateOrganizationOperationalProfileCommand(
                organization_id=organization_id,
                principal_id=unauthorized_principal_id,
                authority_party_id=authority_party_id,
                legal_name="Unauthorized change",
                default_timezone="America/Santo_Domingo",
                default_locale="es-DO",
                default_currency="DOP",
                operational_status="active",
                idempotency_key=f"profile-denied-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_location_hours_command_rejects_stale_operational_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    (
        organization_id,
        authority_party_id,
        principal_id,
        _,
        location_id,
    ) = _authority_fixture(admin_conn)
    commands = PostgresOperationalConfigCommands(session_factory)
    initial_revision = _location_revision(admin_conn, organization_id, location_id)

    state = await set_location_operational_hours(
        commands,
        SetLocationOperationalHoursCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            authority_party_id=authority_party_id,
            location_id=location_id,
            expected_operational_revision=initial_revision,
            windows=(
                LocationOperationalHoursInput(0, time(8, 0), time(17, 0)),
                LocationOperationalHoursInput(1, time(8, 0), time(17, 0)),
            ),
            idempotency_key=f"hours-{uuid4().hex}",
        ),
    )
    assert state.operational_revision > initial_revision
    assert len(state.windows) == 2

    with pytest.raises(LocationOperationalRevisionConflict):
        await set_location_operational_hours(
            commands,
            SetLocationOperationalHoursCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                authority_party_id=authority_party_id,
                location_id=location_id,
                expected_operational_revision=initial_revision,
                windows=(LocationOperationalHoursInput(0, time(9, 0), time(16, 0)),),
                idempotency_key=f"hours-stale-{uuid4().hex}",
            ),
        )
