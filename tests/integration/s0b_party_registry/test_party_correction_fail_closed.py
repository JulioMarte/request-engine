"""Fail-closed corrections on an inactive party: rename, add_document and
deactivate_contact_point all raise the typed not-found once the party is
deactivated; only `parties.deactivate` itself can address it."""

from uuid import UUID, uuid4

import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_document,
    deactivate_party,
    deactivate_party_contact_point,
    register_party,
    rename_party,
)
from request_engine.modules.tenancy.application.errors import PartyNotFound
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


def _deactivate_point_attempt(
    commands: PostgresPartyRegistryCommands,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
):
    return deactivate_party_contact_point.deactivate_party_contact_point(
        commands,
        deactivate_party_contact_point.DeactivatePartyContactPointCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            party_id=party_id,
            contact_point_id=uuid4(),
            idempotency_key=f"cp-{uuid4().hex}",
        ),
    )


def _rename_attempt(
    commands: PostgresPartyRegistryCommands,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
):
    return rename_party.rename_party(
        commands,
        rename_party.RenamePartyCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            party_id=party_id,
            display_name="Nuevo Nombre",
            idempotency_key=f"rename-{uuid4().hex}",
        ),
    )


def _document_attempt(
    commands: PostgresPartyRegistryCommands,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
):
    return add_party_document.add_party_document(
        commands,
        add_party_document.AddPartyDocumentCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            party_id=party_id,
            kind="cedula",
            value="40299999999",
            idempotency_key=f"doc-{uuid4().hex}",
        ),
    )


@pytest.mark.asyncio
async def test_corrections_on_an_inactive_party_fail_closed(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-failclosed")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id, world.operator_principal_id, display_name="Elena Cruz"
        ),
    )
    await deactivate_party.deactivate_party(
        commands,
        deactivate_party.DeactivatePartyCommand(
            organization_id=world.organization_id,
            principal_id=world.operator_principal_id,
            party_id=party.party_id,
            idempotency_key=f"deactivate-{uuid4().hex}",
        ),
    )

    attempts = (
        _deactivate_point_attempt,
        _rename_attempt,
        _document_attempt,
    )
    for attempt in attempts:
        with pytest.raises(PartyNotFound):
            await attempt(
                commands, world.organization_id, world.operator_principal_id, party.party_id
            )
