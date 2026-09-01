"""Rollback world: a Party with a four-revision history built by real commands.

register (rev 1) -> seed secondhand contact -> rename (2) -> confirm (3) ->
deactivate (4). The secondhand contact is a business-plausible direct
prerequisite (no creation command yields `verified = false`); every revision
comes from the real `parties.*` commands under test.
"""

from typing import Any
from uuid import UUID

from psycopg import Connection

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    ConfirmPartyContactPointCommand,
    confirm_party_contact_point,
)
from request_engine.modules.tenancy.application.commands.deactivate_party import (
    DeactivatePartyCommand,
    deactivate_party,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisteredParty,
    register_party,
)
from request_engine.modules.tenancy.application.commands.rename_party import (
    RenamePartyCommand,
    rename_party,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world

RollbackWorld = tuple[PartyRegistryWorld, PostgresPartyRegistryCommands, RegisteredParty, UUID]


async def world_with_history(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> RollbackWorld:
    world = create_party_registry_world(admin_conn, prefix="s0b-rollback")
    commands = registry_commands(app_session_factory)
    party = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Paciente Original",
            whatsapp="+1 809 555 0244",
        ),
    )
    seeded = admin_conn.execute(
        "INSERT INTO request_engine.party_contact_points"
        " (organization_id, party_id, channel, normalized_value, verified, source_kind,"
        "  created_by_principal_id)"
        " VALUES (%s, %s, 'phone', '+18095550255', false, 'subject', %s) RETURNING id",
        (world.organization_id, party.party_id, world.bot_principal_id),
    ).fetchone()
    assert seeded is not None
    await rename_party(
        commands,
        RenamePartyCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            display_name="Nombre Nuevo",
            idempotency_key="rollback-rename",
        ),
    )
    await confirm_party_contact_point(
        commands,
        ConfirmPartyContactPointCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            contact_point_id=UUID(str(seeded[0])),
            idempotency_key="rollback-confirm",
        ),
    )
    await deactivate_party(
        commands,
        DeactivatePartyCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            idempotency_key="rollback-deactivate",
        ),
    )
    return world, commands, party, UUID(str(seeded[0]))


def ledger_kinds(conn: Connection[Any], organization_id: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT revision, change_kind FROM request_engine.party_identity_revisions"
        " WHERE organization_id = %s ORDER BY revision",
        (organization_id,),
    ).fetchall()


def contact_row(
    conn: Connection[Any], organization_id: UUID, contact_point_id: UUID
) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT verified, active FROM request_engine.party_contact_points"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, contact_point_id),
    ).fetchone()
    assert row is not None
    return row
