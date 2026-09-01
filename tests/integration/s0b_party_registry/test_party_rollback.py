"""`parties.rollback_identity` restore proof on real PostgreSQL (§9.3).

Rollback to revision 1 after rename, verification flip and deactivation
restores the recorded identity state as a NEW ledger revision: the party
becomes active again with the original display name and the originally
active contact points reactivated, while verification stays monotone — the
confirmed contact point keeps `verified = true` even though the rollback
deactivates it and the target snapshot records it unverified.
"""

from uuid import UUID

import pytest

from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
)
from request_engine.platform.db.session import SessionFactory

from ._party_ledger_support import PgConnection, ledger_rows
from ._party_rollback_world import contact_row, ledger_kinds, world_with_history
from ._party_support import audit_rows
from ._party_world import PartyRegistryWorld

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _rollback_command(world: PartyRegistryWorld, party_id: UUID, key: str):
    return RollbackPartyIdentityCommand(
        organization_id=world.organization_id,
        principal_id=world.operator_principal_id,
        party_id=party_id,
        target_revision=1,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_rollback_to_first_revision_restores_identity_monotonically(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, party, seeded_contact_id = await world_with_history(
        admin_conn, app_session_factory
    )
    party_row = admin_conn.execute(
        "SELECT display_name, active FROM request_engine.parties WHERE id = %s",
        (party.party_id,),
    ).fetchone()
    assert party_row == ("Nombre Nuevo", False)

    state = await commands.rollback_party_identity(
        _rollback_command(world, party.party_id, "rollback-execute")
    )

    assert state.active is True
    assert state.display_name == "Paciente Original"
    restored = admin_conn.execute(
        "SELECT display_name, active FROM request_engine.parties WHERE id = %s",
        (party.party_id,),
    ).fetchone()
    assert restored == ("Paciente Original", True)
    assert contact_row(
        admin_conn, world.organization_id, party.contact_points[0].contact_point_id
    ) == (True, True)
    assert contact_row(admin_conn, world.organization_id, seeded_contact_id) == (True, False)
    assert ledger_kinds(admin_conn, world.organization_id) == [
        (1, "registered"),
        (2, "renamed"),
        (3, "verification_flipped"),
        (4, "party_deactivated"),
        (5, "rollback"),
    ]
    assert ledger_rows(admin_conn, world.organization_id)[-1][4]["display_name"] == (
        "Paciente Original"
    )
    assert len(audit_rows(admin_conn, world.organization_id, "parties.rollback_identity")) == 1
