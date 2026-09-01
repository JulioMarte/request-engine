"""`parties.add_document` on real PostgreSQL: a duplicate document value hits
the same unique active-value backstop as registration and raises the typed
conflict enriched with the holding Party (id and display name)."""

from uuid import UUID, uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    register_party,
)
from request_engine.modules.tenancy.application.errors import PartyDocumentConflict
from request_engine.modules.tenancy.contracts.party_registry import PartySourceKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection, document_rows
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

_CEDULA = "40212345678"


def _document_command(
    organization_id: UUID, principal_id: UUID, party_id: UUID
) -> add_party_document.AddPartyDocumentCommand:
    return add_party_document.AddPartyDocumentCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
        kind="cedula",
        value=_CEDULA,
        source_kind=PartySourceKind.OPERATOR,
        idempotency_key=f"dup-{uuid4().hex}",
    )


@pytest.mark.asyncio
async def test_duplicate_document_value_names_the_holding_party(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-docdup")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    holder = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Alma Bien",
            cedula="402-1234567-8",
        ),
    )
    other = await register_party.register_party(
        commands,
        register_command(world.organization_id, world.operator_principal_id, display_name="Otra"),
    )

    with pytest.raises(PartyDocumentConflict) as conflict:
        await add_party_document.add_party_document(
            commands,
            _document_command(world.organization_id, world.operator_principal_id, other.party_id),
        )

    assert conflict.value.existing_party_id == holder.party_id
    assert conflict.value.existing_display_name == "Alma Bien"
    rows = document_rows(admin_conn, world.organization_id, _CEDULA)
    assert [str(row[0]) for row in rows if row[3]] == [str(holder.party_id)]
