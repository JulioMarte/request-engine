import asyncio
from dataclasses import replace

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.application.identity_exchange import publish_portable_profile
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adapters, operator_actor, publish_command
from ._identity_exchange_world import published_source
from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


async def _unpublished_party(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    *,
    prefix: str,
    cedula: str,
) -> tuple[PartyRegistryWorld, RegisteredParty]:
    world = create_party_registry_world(admin_conn, prefix=prefix)
    commands = PostgresPartyRegistryCommands(session_factory)
    party = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="María Gómez",
            phone="809-555-1212",
            cedula=cedula,
        ),
    )
    return world, party


@pytest.mark.asyncio
async def test_concurrent_cross_org_publication_converges_to_one_portable_person(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000006"
    first, first_party = await _unpublished_party(
        admin_conn, app_session_factory, prefix="s0d-publish-a", cedula=cedula
    )
    second, second_party = await _unpublished_party(
        admin_conn, app_session_factory, prefix="s0d-publish-b", cedula=cedula
    )
    publisher = adapters(app_session_factory)[0]

    async def publish(world: PartyRegistryWorld, party: RegisteredParty) -> None:
        with operator_actor(world.organization_id, world.operator_principal_id):
            await publish_portable_profile(
                publisher,
                publish_command(
                    world.organization_id,
                    world.operator_principal_id,
                    party.party_id,
                ),
            )

    await asyncio.gather(publish(first, first_party), publish(second, second_party))
    counts = admin_conn.execute(
        "SELECT count(DISTINCT b.portable_party_id), count(DISTINCT i.id), "
        "count(DISTINCT b.id) "
        "FROM request_engine.organization_party_bindings b "
        "JOIN request_engine.portable_party_identifiers i "
        "ON i.portable_party_id = b.portable_party_id AND i.active "
        "WHERE b.organization_id IN (%s, %s) AND b.active",
        (first.organization_id, second.organization_id),
    ).fetchone()
    assert counts == (1, 1, 2)


@pytest.mark.asyncio
async def test_republish_replaces_snapshot_when_consent_is_reduced(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world, party, _, _ = await published_source(
        admin_conn, app_session_factory, value="40200000007"
    )
    publisher = adapters(app_session_factory)[0]
    command = replace(
        publish_command(world.organization_id, world.operator_principal_id, party.party_id),
        consented_fields=("display_name",),
    )
    with operator_actor(world.organization_id, world.operator_principal_id):
        await publish_portable_profile(publisher, command)
    row = admin_conn.execute(
        "SELECT p.profile FROM request_engine.portable_party_profiles p "
        "JOIN request_engine.organization_party_bindings b "
        "ON b.portable_party_id = p.portable_party_id "
        "AND b.organization_id = p.publisher_organization_id "
        "WHERE b.organization_id = %s AND b.party_id = %s AND b.active",
        (world.organization_id, party.party_id),
    ).fetchone()
    assert row is not None
    assert row[0] == {"display_name": "María Gómez"}
