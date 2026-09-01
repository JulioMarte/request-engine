"""Concurrent same-key rollback executes exactly once (race proof).

Two independent transactions run the real `parties.rollback_identity`
command with the same idempotency key. Deterministic synchronization holds
both before any commit: the first parks at the audit append point holding
the party row lock; the second blocks on the idempotency identity the first
created. Exactly one rollback revision and one audit record exist, and both
callers observe the restored party.
"""

import asyncio
from uuid import UUID

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands.rollback_party_identity import (
    RollbackPartyIdentityCommand,
)
from request_engine.modules.tenancy.contracts.party_registry import RegisteredParty
from request_engine.platform.db.session import SessionFactory

from ._party_rollback_world import ledger_kinds, world_with_history
from ._party_support import (
    PgConnection,
    audit_rows,
    connect,
    lock_audit_barrier,
    wait_until_query_blocked,
)
from ._party_world import PartyRegistryWorld

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]


async def _rollback(
    commands: PostgresPartyRegistryCommands,
    world: PartyRegistryWorld,
    party_id: UUID,
    key: str,
) -> RegisteredParty:
    return await commands.rollback_party_identity(
        RollbackPartyIdentityCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party_id,
            target_revision=1,
            idempotency_key=key,
        )
    )


@pytest.mark.asyncio
async def test_concurrent_same_key_rollback_executes_once(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, party, _seeded = await world_with_history(admin_conn, app_session_factory)
    key = "rollback-concurrent"
    blocker = connect()
    try:
        lock_audit_barrier(blocker)
        first_task = asyncio.create_task(_rollback(commands, world, party.party_id, key))
        await wait_until_query_blocked(
            admin_conn,
            "%INSERT INTO request_engine.audit_records%",
            "first rollback never parked at the audit append point",
        )
        second_task = asyncio.create_task(_rollback(commands, world, party.party_id, key))
        await wait_until_query_blocked(
            admin_conn,
            "%request_cmd.acquire_idempotency%",
            "second rollback never blocked on the idempotency identity",
        )
        blocker.commit()
        first = await asyncio.wait_for(first_task, timeout=5)
        second = await asyncio.wait_for(second_task, timeout=5)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()

    assert first.party_id == second.party_id == party.party_id
    assert first.active and second.active
    rollback_rows = [
        row for row in ledger_kinds(admin_conn, world.organization_id) if row[1] == "rollback"
    ]
    assert [revision for revision, _ in rollback_rows] == [5]
    assert len(audit_rows(admin_conn, world.organization_id, "parties.rollback_identity")) == 1
