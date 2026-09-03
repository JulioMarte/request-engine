import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_reader import (
    PostgresPartyLookupReader,
)
from request_engine.modules.tenancy.application.commands.register_party import register_party
from request_engine.modules.tenancy.application.queries.lookup_parties import (
    PartyLookupMode,
    PartyLookupQuery,
    lookup_parties,
)
from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.platform.db.session import SessionFactory

from ._party_commands import register_command, registry_commands
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_shared_email_is_a_multi_match_locator_not_identity(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-email-shared")
    commands = registry_commands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    first = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Ana Pérez",
            email="familia@example.com",
        ),
    )
    second = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="Luis Pérez",
            email="FAMILIA@example.com",
        ),
    )

    matches = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.EMAIL,
            value="familia@example.com",
        ),
    )
    assert {party.party_id for party in matches} == {first.party_id, second.party_id}


@pytest.mark.asyncio
async def test_organization_can_register_without_rnc_then_be_found_after_rnc_is_known(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world = create_party_registry_world(admin_conn, prefix="s0b-org-rnc")
    commands = registry_commands(app_session_factory)
    reader = PostgresPartyLookupReader(app_session_factory)
    without_document = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            party_kind=PartyKind.ORGANIZATION,
            display_name="Acme Dominicana SRL",
            email="compras@acme.example",
        ),
    )
    assert without_document.party_kind == PartyKind.ORGANIZATION.value
    assert without_document.documents == ()

    with_rnc = await register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            party_kind=PartyKind.ORGANIZATION,
            display_name="Ferretería Central SRL",
            rnc="1-01-85004-3",
        ),
    )
    matches = await lookup_parties(
        reader,
        PartyLookupQuery(
            organization_id=world.organization_id,
            mode=PartyLookupMode.DOCUMENT,
            value="101850043",
            document_kind="rnc",
        ),
    )
    assert [party.party_id for party in matches] == [with_rnc.party_id]
    assert matches[0].party_kind == PartyKind.ORGANIZATION.value
    assert matches[0].documents[0].authority == "DO:DGII"
