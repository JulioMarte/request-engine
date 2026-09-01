"""Ledger access proofs: append-only enforcement, org scoping, attribution.

The revision ledger rejects UPDATE and DELETE for the runtime role (missing
grant) and for the table owner (guard trigger backstop). The read surface is
org-scoped: a foreign organization gets the typed not-found, not the
history. Ledger attribution keeps the technical caller and the attributed
operator apart (§9.1/§9.3).
"""

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.party_revision_history_reader import (
    PostgresPartyRevisionHistoryReader,
)
from request_engine.modules.tenancy.application.commands.register_party import (
    RegisterPartyCommand,
    register_party,
)
from request_engine.modules.tenancy.application.errors import PartyNotFound
from request_engine.modules.tenancy.application.queries.party_revision_history import (
    PartyRevisionHistoryQuery,
)
from request_engine.modules.tenancy.contracts.party_registry import (
    PartySourceKind,
    RegisteredParty,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import PartyRegistryWorld, create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


async def _registered_party(
    admin_conn: PgConnection, app_session_factory: SessionFactory, prefix: str
) -> tuple[PartyRegistryWorld, RegisteredParty]:
    world = create_party_registry_world(admin_conn, prefix=prefix)
    party = await register_party(
        registry_commands(app_session_factory),
        register_command(world.organization_id, world.operator_principal_id, display_name="Uno"),
    )
    return world, party


@pytest.mark.asyncio
async def test_ledger_rejects_update_and_delete_for_every_role(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, _party = await _registered_party(admin_conn, app_session_factory, prefix="s0b-ledger")
    for statement in (
        "UPDATE request_engine.party_identity_revisions SET display_name = 'x'",
        "DELETE FROM request_engine.party_identity_revisions",
    ):
        async with app_session_factory() as session:
            await session.execute(
                text("SELECT set_config('request_engine.organization_id', :org, true)"),
                {"org": str(world.organization_id)},
            )
            with pytest.raises(DBAPIError) as runtime_error:
                await session.execute(text(statement))
            assert getattr(runtime_error.value.orig, "sqlstate", None) == "42501"

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        admin_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(world.organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(
                "UPDATE request_engine.party_identity_revisions SET display_name = 'x'"
                " WHERE organization_id = %s",
                (world.organization_id,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute("DELETE FROM request_engine.party_identity_revisions")
    finally:
        admin_conn.execute("RESET ROLE")


@pytest.mark.asyncio
async def test_revision_history_reader_is_org_scoped(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, party = await _registered_party(admin_conn, app_session_factory, prefix="s0b-ledger")
    foreign = create_party_registry_world(admin_conn, prefix="s0b-ledger-foreign")
    reader = PostgresPartyRevisionHistoryReader(app_session_factory)

    own = await reader.revision_history(
        PartyRevisionHistoryQuery(world.organization_id, party.party_id)
    )
    assert [revision.revision for revision in own] == [1]
    assert own[0].snapshot["display_name"] == "Uno"
    with pytest.raises(PartyNotFound):
        await reader.revision_history(
            PartyRevisionHistoryQuery(foreign.organization_id, party.party_id)
        )


@pytest.mark.asyncio
async def test_ledger_separates_technical_caller_from_attributed_operator(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-ledger-relay")
    commands = registry_commands(app_session_factory)
    await register_party(
        commands,
        RegisterPartyCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            display_name="Relay",
            source_kind=PartySourceKind.OPERATOR,
            idempotency_key="ledger-relay",
            technical_principal_id=world.bot_principal_id,
        ),
    )
    row = admin_conn.execute(
        "SELECT actor_principal_id, attributed_operator_principal_id, source_kind"
        " FROM request_engine.party_identity_revisions WHERE organization_id = %s",
        (world.organization_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == world.bot_principal_id
    assert row[1] == world.operator_principal_id
    assert row[2] == "operator"
