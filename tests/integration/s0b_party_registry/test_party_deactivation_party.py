"""`parties.deactivate` proofs on real PostgreSQL.

A deactivated party is excluded from all three lookup modes and
re-deactivating an already inactive party succeeds idempotently.
"""

from uuid import UUID, uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.application.commands import deactivate_party, register_party
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    lookup_parties,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _deactivate_command(
    world: PartyRegistryWorld, party_id: UUID, key: str
) -> deactivate_party.DeactivatePartyCommand:
    return deactivate_party.DeactivatePartyCommand(
        organization_id=world.organization_id,
        principal_id=world.operator_principal_id,
        party_id=party_id,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_deactivation_excludes_the_party_from_every_lookup_mode(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-pdeact")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Carla Mena",
            whatsapp="809 555 0600",
            cedula="402-7777777-7",
        ),
    )

    deactivated = await deactivate_party.deactivate_party(
        commands, _deactivate_command(world, party.party_id, f"deactivate-{uuid4().hex}")
    )

    assert deactivated.active is False
    for mode, value in (
        (PartyLookupMode.PHONE, "+1 809 555 0600"),
        (PartyLookupMode.NAME, "carla"),
        (PartyLookupMode.DOCUMENT, "402-7777777-7"),
    ):
        found = await lookup_parties(
            reader, PartyLookupQuery(organization_id=world.organization_id, mode=mode, value=value)
        )
        assert [item.party_id for item in found] == []


@pytest.mark.asyncio
async def test_re_deactivating_an_inactive_party_succeeds_idempotently(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-redeact")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Dario Leo",
            whatsapp="809 555 0700",
        ),
    )
    first = await deactivate_party.deactivate_party(
        commands, _deactivate_command(world, party.party_id, f"deactivate-{uuid4().hex}")
    )

    second = await deactivate_party.deactivate_party(
        commands, _deactivate_command(world, party.party_id, f"deactivate-again-{uuid4().hex}")
    )

    assert (first.active, second.active) == (False, False)
