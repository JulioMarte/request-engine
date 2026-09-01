"""Party identity revision ledger proof on real PostgreSQL (docs/v3/38 §9.3).

Register -> rename -> add contact -> deactivate contact leaves four ledger
revisions with monotone per-party revision numbers, and each recorded
snapshot matches the database state right after that step (raw-SQL oracle,
not the production reader).
"""

from typing import Any

import pytest

from request_engine.modules.tenancy.application.commands.add_party_contact_point import (
    AddPartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.deactivate_party_contact_point import (
    DeactivatePartyContactPointCommand,
)
from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.application.commands.rename_party import (
    RenamePartyCommand,
    rename_party,
)
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_ledger_support import PgConnection, identity_state, ledger_rows
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_every_mutation_appends_a_snapshot_revision(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-ledger")
    commands = registry_commands(app_session_factory)
    party = await register_party(
        commands,
        register_command(world.organization_id, world.operator_principal_id, display_name="Uno"),
    )
    oracles: list[dict[str, object]] = [
        identity_state(admin_conn, world.organization_id, party.party_id)
    ]

    await rename_party(
        commands,
        RenamePartyCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            display_name="Dos",
            idempotency_key="ledger-rename",
        ),
    )
    oracles.append(identity_state(admin_conn, world.organization_id, party.party_id))
    added = await commands.add_party_contact_point(
        AddPartyContactPointCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            channel="phone",
            value="+1 809 555 0233",
            source_kind=PartySourceKind.OPERATOR,
            idempotency_key="ledger-add",
        )
    )
    oracles.append(identity_state(admin_conn, world.organization_id, party.party_id))
    await commands.deactivate_party_contact_point(
        DeactivatePartyContactPointCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            contact_point_id=added.contact_point_id,
            idempotency_key="ledger-deactivate",
        )
    )
    oracles.append(identity_state(admin_conn, world.organization_id, party.party_id))

    rows: list[tuple[Any, ...]] = ledger_rows(admin_conn, world.organization_id)
    assert [row[1] for row in rows] == [
        "registered",
        "renamed",
        "contact_added",
        "contact_deactivated",
    ]
    assert [row[0] for row in rows] == [1, 2, 3, 4]
    for row, oracle in zip(rows, oracles, strict=True):
        assert row[2] == oracle["display_name"]
        assert row[3] == oracle["active"]
        assert row[4] == oracle
