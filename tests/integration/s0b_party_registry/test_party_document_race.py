"""I-S0b-1: a cédula value is unique among active documents per tenant.

Two independent transactions register the same normalized cédula (different
raw formats, two different Parties) through the real
`PostgresPartyRegistryCommands.register_party`. Deterministic synchronization
holds both before any commit: the winner is parked at the audit append point
after inserting its document row; the loser then blocks on the unique index
entry the winner's in-flight insert created. Exactly one commits; the loser
raises the typed `PartyDocumentConflict` and its transaction rolls back.
Removing the migration's UNIQUE (organization_id, kind, normalized_value)
backstop would let both commits succeed and the assertions below would fail.
"""

import asyncio

import pytest

from request_engine.modules.tenancy.application.commands.register_party import (
    register_party,
)
from request_engine.modules.tenancy.application.errors import PartyDocumentConflict
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import (
    PgConnection,
    audit_rows,
    connect,
    document_rows,
    lock_audit_barrier,
    outbox_rows,
    party_rows,
    wait_until_query_blocked,
)
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]

_CEDULA = "40212345678"


@pytest.mark.asyncio
async def test_concurrent_register_with_same_cedula_loses_once(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-race")
    commands = registry_commands(app_session_factory)
    blocker = connect()
    loser_task: asyncio.Task[object] | None = None
    try:
        lock_audit_barrier(blocker)
        winner_task = asyncio.create_task(
            register_party(
                commands,
                register_command(
                    world.organization_id,
                    world.operator_principal_id,
                    display_name="Alma Bien",
                    cedula="402-1234567-8",
                ),
            )
        )
        await wait_until_query_blocked(
            admin_conn,
            "%INSERT INTO request_engine.audit_records%",
            "first register never parked at the audit append point",
        )
        loser_task = asyncio.create_task(
            register_party(
                commands,
                register_command(
                    world.organization_id,
                    world.operator_principal_id,
                    display_name="Otra Persona",
                    cedula=_CEDULA,
                ),
            )
        )
        await wait_until_query_blocked(
            admin_conn,
            "%INSERT INTO request_engine.party_identity_documents%",
            "second register never blocked on the document uniqueness backstop",
        )
        blocker.commit()
        winner = await asyncio.wait_for(winner_task, timeout=5)
        with pytest.raises(PartyDocumentConflict):
            await asyncio.wait_for(loser_task, timeout=5)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()
        if loser_task is not None and not loser_task.done():
            loser_task.cancel()

    assert winner.documents[0].normalized_value == _CEDULA
    rows = document_rows(admin_conn, world.organization_id, _CEDULA)
    assert [(str(row[0]), row[1], row[2], row[3]) for row in rows] == [
        (str(winner.party_id), "cedula", _CEDULA, True)
    ]
    assert [row[0] for row in party_rows(admin_conn, world.organization_id)] == [winner.party_id]
    assert len(audit_rows(admin_conn, world.organization_id, "parties.register")) == 1
    assert len(outbox_rows(admin_conn, world.organization_id, "party.registered.v1")) == 1
