from uuid import UUID, uuid4

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
from request_engine.modules.tenancy.application.commands import register_party
from request_engine.modules.tenancy.application.commands.add_party_administrative_identifier import (
    AddPartyAdministrativeIdentifierCommand,
    add_party_administrative_identifier,
)
from request_engine.modules.tenancy.application.queries.party_administrative_identifiers import (
    PartyAdministrativeIdentifierLookupQuery,
    lookup_party_by_administrative_identifier,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


def _identifier_command(
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    *,
    value: str = "MEM-001 23",
    idempotency_key: str | None = None,
) -> AddPartyAdministrativeIdentifierCommand:
    return AddPartyAdministrativeIdentifierCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        kind="insurance_member",
        issuer=" ARS   Primera ",
        value=value,
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key=idempotency_key or f"insurance-{uuid4().hex}",
        platform="reception_web",
    )


async def _lookup_ids(
    reader: PostgresPartyAdministrativeIdentifierReader,
    organization_id: UUID,
    value: str = "MEM-00123",
) -> list[UUID]:
    parties = await lookup_party_by_administrative_identifier(
        reader,
        PartyAdministrativeIdentifierLookupQuery(
            organization_id=organization_id,
            kind="insurance_member",
            issuer="ars primera",
            value=value,
        ),
    )
    return [party.party_id for party in parties]


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
        register_command(world_a.organization_id, world_a.operator_principal_id, display_name="Ana A"),
    )
    party_b = await register_party.register_party(
        commands,
        register_command(world_b.organization_id, world_b.operator_principal_id, display_name="Ana B"),
    )

    await add_party_administrative_identifier(
        commands,
        _identifier_command(world_a.organization_id, world_a.operator_principal_id, party_a.party_id),
    )
    assert await _lookup_ids(reader, world_a.organization_id) == [party_a.party_id]
    assert await _lookup_ids(reader, world_b.organization_id) == []

    await add_party_administrative_identifier(
        commands,
        _identifier_command(world_b.organization_id, world_b.operator_principal_id, party_b.party_id),
    )
    assert await _lookup_ids(reader, world_b.organization_id) == [party_b.party_id]


@pytest.mark.asyncio
async def test_same_tenant_member_id_conflicts_and_replay_is_stable(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0c-ins-conflict")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    first = await register_party.register_party(
        commands,
        register_command(world.organization_id, world.operator_principal_id, display_name="First"),
    )
    second = await register_party.register_party(
        commands,
        register_command(world.organization_id, world.operator_principal_id, display_name="Second"),
    )
    command = _identifier_command(
        world.organization_id,
        world.operator_principal_id,
        first.party_id,
        idempotency_key="insurance-replay",
    )
    created = await add_party_administrative_identifier(commands, command)
    replay = await add_party_administrative_identifier(commands, command)
    assert replay.identifier_id == created.identifier_id

    with pytest.raises(PartyAdministrativeIdentifierConflict) as conflict:
        await add_party_administrative_identifier(
            commands,
            _identifier_command(world.organization_id, world.operator_principal_id, second.party_id),
        )
    assert conflict.value.existing_party_id == first.party_id
