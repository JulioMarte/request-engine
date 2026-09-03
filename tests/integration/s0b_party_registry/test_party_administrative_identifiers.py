import pytest

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_reader import (
    PostgresPartyAdministrativeIdentifierReader,
)
from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.administrative_identifier_errors import (
    PartyAdministrativeIdentifierConflict,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_administrative_identifier as admin_identifier_commands,
)
from request_engine.modules.tenancy.application.commands import register_party
from request_engine.platform.db.session import SessionFactory

from ._party_administrative_identifier_support import identifier_command, lookup_ids
from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_insurance_member_lookup_is_tenant_owned(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world_a = create_party_registry_world(admin_conn, prefix="s0c-ins-a")
    world_b = create_party_registry_world(admin_conn, prefix="s0c-ins-b")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    reader = PostgresPartyAdministrativeIdentifierReader(app_session_factory)
    party_a = await register_party.register_party(
        commands,
        register_command(
            world_a.organization_id,
            world_a.operator_principal_id,
            display_name="Ana A",
        ),
    )
    party_b = await register_party.register_party(
        commands,
        register_command(
            world_b.organization_id,
            world_b.operator_principal_id,
            display_name="Ana B",
        ),
    )

    await admin_identifier_commands.add_party_administrative_identifier(
        commands,
        identifier_command(
            world_a.organization_id,
            world_a.operator_principal_id,
            party_a.party_id,
        ),
    )
    assert await lookup_ids(reader, world_a.organization_id) == [party_a.party_id]
    assert await lookup_ids(reader, world_b.organization_id) == []

    await admin_identifier_commands.add_party_administrative_identifier(
        commands,
        identifier_command(
            world_b.organization_id,
            world_b.operator_principal_id,
            party_b.party_id,
        ),
    )
    assert await lookup_ids(reader, world_b.organization_id) == [party_b.party_id]


@pytest.mark.asyncio
async def test_same_tenant_member_id_conflicts_and_replay_is_stable(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0c-ins-conflict")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    first = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="First",
        ),
    )
    second = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Second",
        ),
    )
    command = identifier_command(
        world.organization_id,
        world.operator_principal_id,
        first.party_id,
        idempotency_key="insurance-replay",
    )
    created = await admin_identifier_commands.add_party_administrative_identifier(commands, command)
    replay = await admin_identifier_commands.add_party_administrative_identifier(commands, command)
    assert replay.identifier_id == created.identifier_id

    with pytest.raises(PartyAdministrativeIdentifierConflict) as conflict:
        await admin_identifier_commands.add_party_administrative_identifier(
            commands,
            identifier_command(
                world.organization_id,
                world.operator_principal_id,
                second.party_id,
            ),
        )
    assert conflict.value.existing_party_id == first.party_id
