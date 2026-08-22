from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.business_info_reader import PostgresBusinessInfoReader
from request_engine.modules.catalog.application.queries.get_business_info import get_business_info
from request_engine.modules.tenancy.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.tenancy.application.commands.set_organization_public_contacts import (
    OrganizationPublicContactInput,
    SetOrganizationPublicContactsCommand,
    set_organization_public_contacts,
)
from request_engine.platform.db.session import SessionFactory

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_public_contacts_are_canonicalized_before_persistence(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    command = SetOrganizationPublicContactsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        contacts=(
            OrganizationPublicContactInput("phone", "+1 (809) 555-0999"),
            OrganizationPublicContactInput("email", " Central@Example.Test "),
        ),
        idempotency_key=f"normalized-contacts-{uuid4().hex}",
    )
    await set_organization_public_contacts(
        PostgresOperationalProfileCommands(session_factory),
        command,
    )
    info = await get_business_info(
        PostgresBusinessInfoReader(session_factory),
        scenario.organization_id,
    )
    assert {(item.channel, item.value) for item in info.contacts} == {
        ("phone", "+18095550999"),
        ("email", "central@example.test"),
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_canonical_duplicate_contacts_are_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    command = SetOrganizationPublicContactsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        contacts=(
            OrganizationPublicContactInput("phone", "+1 809 555 0999"),
            OrganizationPublicContactInput("phone", "+18095550999"),
        ),
        idempotency_key=f"duplicate-contacts-{uuid4().hex}",
    )
    with pytest.raises(ValueError, match="duplicate public contact"):
        await set_organization_public_contacts(
            PostgresOperationalProfileCommands(session_factory),
            command,
        )
