"""Operator correction proofs on real PostgreSQL: `parties.rename` and
`parties.add_document`.

A rename must move the party between name-prefix buckets (the accent-folded
SQL path still matches the new stored name); an added document must be
normalized exactly like registration and feed the document lookup. Both are
audited and neither emits an outbox event: `party.registered.v1` stays the
only outbox payload.
"""

from uuid import UUID, uuid4

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
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection, audit_rows, outbox_rows
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


async def _lookup_ids(
    reader: PostgresPartyLookupReader,
    organization_id: UUID,
    mode: PartyLookupMode,
    value: str,
) -> list[UUID]:
    found = await lookup_parties(
        reader, PartyLookupQuery(organization_id=organization_id, mode=mode, value=value)
    )
    return [party.party_id for party in found]


def _rename_command(
    organization_id: UUID, principal_id: UUID, party_id: UUID
) -> rename_party.RenamePartyCommand:
    return rename_party.RenamePartyCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        display_name="María González",
        idempotency_key=f"rename-{uuid4().hex}",
    )


def _document_command(
    organization_id: UUID, principal_id: UUID, party_id: UUID, kind: str, value: str
) -> add_party_document.AddPartyDocumentCommand:
    return add_party_document.AddPartyDocumentCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        kind=kind,
        value=value,
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key=f"doc-{uuid4().hex}",
    )


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
        _rename_command(world.organization_id, world.operator_principal_id, party.party_id),
    )

    assert renamed.display_name == "María González"
    old_name = await _lookup_ids(reader, world.organization_id, PartyLookupMode.NAME, "jose perez")
    new_name = await _lookup_ids(reader, world.organization_id, PartyLookupMode.NAME, "maria gon")
    assert (old_name, new_name) == ([], [party.party_id])
    assert len(audit_rows(admin_conn, world.organization_id, "parties.rename")) == 1
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
        _document_command(
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
