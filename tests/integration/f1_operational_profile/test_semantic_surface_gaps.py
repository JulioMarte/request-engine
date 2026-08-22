from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.business_info_reader import (
    PostgresBusinessInfoReader,
)
from request_engine.modules.catalog.adapters.db.location_creation_commands import (
    PostgresLocationCreationCommands,
)
from request_engine.modules.catalog.application.commands.create_location import (
    CreateLocationCommand,
    create_location,
)
from request_engine.modules.catalog.application.errors import CatalogConfigurationConflict
from request_engine.modules.catalog.application.queries.get_business_info import (
    get_business_info,
)
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.application.commands.set_organization_public_contacts import (
    OrganizationPublicContactInput,
    SetOrganizationPublicContactsCommand,
    set_organization_public_contacts,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.operational_authority import (
    OperationalAuthorityRequired,
)

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _unauthorized_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"unauthorized-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_create_location_is_authorized_idempotent_and_conflict_safe(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresLocationCreationCommands(session_factory)
    command = CreateLocationCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        location_key=f"north-{uuid4().hex}",
        display_name="North clinic",
        timezone="America/Santo_Domingo",
        idempotency_key=f"create-location-{uuid4().hex}",
        address_line1="10 North Street",
        locality="Puerto Plata",
        country_code="DO",
        latitude=Decimal("19.800000"),
        longitude=Decimal("-70.690000"),
    )

    state = await create_location(handler, command)
    replay = await create_location(handler, command)
    assert replay == state
    assert state.operational_revision == 1
    assert state.display_name == "North clinic"
    assert state.country_code == "DO"

    count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.locations
        WHERE organization_id = %s AND location_key = %s
        """,
        (scenario.organization_id, command.location_key),
    ).fetchone()
    assert count == (1,)

    with pytest.raises(CatalogConfigurationConflict):
        await create_location(
            handler,
            CreateLocationCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                location_key=command.location_key,
                display_name="Conflicting duplicate",
                timezone="America/Santo_Domingo",
                idempotency_key=f"create-location-conflict-{uuid4().hex}",
            ),
        )

    unauthorized = _unauthorized_principal(admin_conn, scenario.organization_id)
    with pytest.raises(OperationalAuthorityRequired):
        await create_location(
            handler,
            CreateLocationCommand(
                organization_id=scenario.organization_id,
                principal_id=unauthorized,
                authority_party_id=scenario.authority_party_id,
                location_key=f"denied-{uuid4().hex}",
                display_name="Denied clinic",
                timezone="America/Santo_Domingo",
                idempotency_key=f"create-location-denied-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_organization_public_contacts_are_authorized_idempotent_and_tenant_local(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    other = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresOperationalProfileCommands(session_factory)
    command = SetOrganizationPublicContactsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        contacts=(
            OrganizationPublicContactInput(
                "phone",
                "+18095550999",
                "Central appointments",
            ),
            OrganizationPublicContactInput("email", "central@example.test"),
        ),
        idempotency_key=f"organization-contacts-{uuid4().hex}",
    )

    state = await set_organization_public_contacts(handler, command)
    replay = await set_organization_public_contacts(handler, command)
    assert replay == state

    info = await get_business_info(
        PostgresBusinessInfoReader(session_factory),
        scenario.organization_id,
    )
    assert {(item.channel, item.value) for item in info.contacts} == {
        ("phone", "+18095550999"),
        ("email", "central@example.test"),
    }

    other_contacts = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.organization_public_contact_endpoints
        WHERE organization_id = %s AND active AND is_public
        """,
        (other.organization_id,),
    ).fetchone()
    assert other_contacts == (0,)

    unauthorized = _unauthorized_principal(admin_conn, scenario.organization_id)
    with pytest.raises(OperationalAuthorityRequired):
        await set_organization_public_contacts(
            handler,
            SetOrganizationPublicContactsCommand(
                organization_id=scenario.organization_id,
                principal_id=unauthorized,
                authority_party_id=other.authority_party_id,
                contacts=(OrganizationPublicContactInput("phone", "+18095550000"),),
                idempotency_key=f"organization-contacts-denied-{uuid4().hex}",
            ),
        )

    unchanged = admin_conn.execute(
        """
        SELECT channel, normalized_value
        FROM request_engine.organization_public_contact_endpoints
        WHERE organization_id = %s AND active AND is_public
        ORDER BY channel, normalized_value
        """,
        (scenario.organization_id,),
    ).fetchall()
    assert unchanged == [
        ("email", "central@example.test"),
        ("phone", "+18095550999"),
    ]
