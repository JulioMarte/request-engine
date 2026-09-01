"""Operator correction proofs on real PostgreSQL: `parties.rename` and
`parties.add_document`. A rename must move the party between name-prefix
buckets; an added document must be normalized exactly like registration and
feed the document lookup. Both are audited with the §9.1 attribution facts
and neither emits an outbox event.
"""

from uuid import UUID

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    register_party,
    rename_party,
)
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    lookup_parties,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import document_command, register_command, rename_command
from ._party_support import PgConnection, audit_rows, outbox_rows
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


async def _lookup_ids(
    reader: PostgresPartyLookupReader, organization_id: UUID, mode: PartyLookupMode, value: str
) -> list[UUID]:
    found = await lookup_parties(
        reader, PartyLookupQuery(organization_id=organization_id, mode=mode, value=value)
    )
    return [party.party_id for party in found]


@pytest.mark.asyncio
async def test_rename_moves_the_party_to_the_new_accent_folded_prefix(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-rename")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="José Pérez",
            whatsapp="809 555 0300",
        ),
    )

    renamed = await rename_party.rename_party(
        commands,
        rename_command(
            world.organization_id,
            world.operator_principal_id,
            party.party_id,
            world.bot_principal_id,
        ),
    )

    assert renamed.display_name == "María González"
    old_name = await _lookup_ids(reader, world.organization_id, PartyLookupMode.NAME, "jose perez")
    new_name = await _lookup_ids(reader, world.organization_id, PartyLookupMode.NAME, "maria gon")
    assert (old_name, new_name) == ([], [party.party_id])
    rename_audits = audit_rows(admin_conn, world.organization_id, "parties.rename")
    assert len(rename_audits) == 1
    assert rename_audits[0]["source_kind"] == "operator"
    assert rename_audits[0]["platform"] == "reception_web"
    assert rename_audits[0]["relay_principal_id"] == str(world.bot_principal_id)
    ledger = admin_conn.execute(
        "SELECT actor_principal_id, attributed_operator_principal_id"
        " FROM request_engine.party_identity_revisions"
        " WHERE organization_id = %s AND party_id = %s AND revision = 2",
        (world.organization_id, party.party_id),
    ).fetchone()
    assert ledger == (world.bot_principal_id, world.operator_principal_id)
    assert len(outbox_rows(admin_conn, world.organization_id, "party.registered.v1")) == 1


@pytest.mark.asyncio
async def test_add_document_attaches_a_normalized_document_to_an_existing_party(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-adddoc")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id, world.operator_principal_id, display_name="Luis Nova"
        ),
    )

    added = await add_party_document.add_party_document(
        commands,
        document_command(
            world.organization_id,
            world.operator_principal_id,
            party.party_id,
            "cedula",
            "402-1234567-8",
        ),
    )

    assert (added.kind, added.normalized_value) == ("cedula", "40212345678")
    by_document = await _lookup_ids(
        reader, world.organization_id, PartyLookupMode.DOCUMENT, "402-1234567-8"
    )
    assert by_document == [party.party_id]
    assert len(audit_rows(admin_conn, world.organization_id, "parties.add_document")) == 1
    assert len(outbox_rows(admin_conn, world.organization_id, "party.registered.v1")) == 1
