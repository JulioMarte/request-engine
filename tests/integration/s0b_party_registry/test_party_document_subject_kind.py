import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import add_party_document, register_party
from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import document_command, register_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_add_document_rejects_identifier_for_wrong_party_kind(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0d-party-kind-doc")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    person = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Persona sin documento",
        ),
    )
    organization = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            party_kind=PartyKind.ORGANIZATION,
            display_name="Empresa sin RNC",
        ),
    )

    with pytest.raises(ValueError, match="rnc identifies a organization Party"):
        await add_party_document.add_party_document(
            commands,
            document_command(
                world.organization_id,
                world.operator_principal_id,
                person.party_id,
                "rnc",
                "101850043",
            ),
        )
    with pytest.raises(ValueError, match="cedula identifies a person Party"):
        await add_party_document.add_party_document(
            commands,
            document_command(
                world.organization_id,
                world.operator_principal_id,
                organization.party_id,
                "cedula",
                "40212345678",
            ),
        )

    count = admin_conn.execute(
        "SELECT count(*) FROM request_engine.party_identity_documents "
        "WHERE organization_id = %s AND party_id IN (%s, %s) AND active",
        (world.organization_id, person.party_id, organization.party_id),
    ).fetchone()
    assert count is not None and int(count[0]) == 0
