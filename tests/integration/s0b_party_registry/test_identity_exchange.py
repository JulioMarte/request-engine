import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import (
    add_party_administrative_identifier as admin_identifier_commands,
    register_party,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
    publish_portable_profile,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeCandidateInvalid,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from ._identity_exchange_support import (
    adapters,
    adopt_command,
    match_command,
    operator_actor,
    publish_command,
)
from ._party_administrative_identifier_support import identifier_command, lookup_ids
from ._party_commands import register_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


async def _published_source(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    *,
    cedula: str,
):
    world = create_party_registry_world(admin_conn, prefix="s0d-source")
    commands = PostgresPartyRegistryCommands(app_session_factory)
    party = await register_party.register_party(
        commands,
        register_command(
            world.organization_id,
            world.operator_principal_id,
            display_name="María Gómez",
            phone="809-555-1212",
            cedula=cedula,
        ),
    )
    await admin_identifier_commands.add_party_administrative_identifier(
        commands,
        identifier_command(
            world.organization_id,
            world.operator_principal_id,
            party.party_id,
        ),
    )
    publisher, matcher, adopter = adapters(app_session_factory)
    with operator_actor(world.organization_id, world.operator_principal_id):
        await publish_portable_profile(
            publisher,
            publish_command(world.organization_id, world.operator_principal_id, party.party_id),
        )
    return world, party, matcher, adopter


@pytest.mark.asyncio
async def test_cross_org_adoption_creates_local_party_without_copying_history_or_insurance(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000001"
    source, source_party, matcher, adopter = await _published_source(
        admin_conn, app_session_factory, cedula=cedula
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-destination")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(destination.organization_id, destination.operator_principal_id, cedula),
        )
        assert match.matched and match.candidate_ref is not None
        adoption = await adopt_portable_identity(
            adopter,
            adopt_command(
                destination.organization_id,
                destination.operator_principal_id,
                match.candidate_ref,
                value=cedula,
                key="stable-adoption",
            ),
        )
        replay = await adopt_portable_identity(
            adopter,
            adopt_command(
                destination.organization_id,
                destination.operator_principal_id,
                match.candidate_ref,
                value=cedula,
                key="stable-adoption",
            ),
        )

    assert adoption.party.party_id != source_party.party_id
    assert adoption.party.organization_id == destination.organization_id
    assert adoption.party.display_name == "María Gómez"
    assert {item.normalized_value for item in adoption.party.contact_points} == {"+18095551212"}
    assert {item.normalized_value for item in adoption.party.documents} == {cedula}
    assert replay.party.party_id == adoption.party.party_id
    assert len(adoption.portable_insurance_identifiers) == 1
    assert await lookup_ids(
        __import__(
            "request_engine.modules.tenancy.adapters.db.party_administrative_identifier_reader",
            fromlist=["PostgresPartyAdministrativeIdentifierReader"],
        ).PostgresPartyAdministrativeIdentifierReader(app_session_factory),
        destination.organization_id,
    ) == []
    assert source.organization_id != destination.organization_id


@pytest.mark.asyncio
async def test_wrong_document_does_not_consume_candidate_and_global_tables_are_not_app_readable(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000002"
    _, _, matcher, adopter = await _published_source(
        admin_conn, app_session_factory, cedula=cedula
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-private")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(destination.organization_id, destination.operator_principal_id, cedula),
        )
        assert match.candidate_ref is not None
        with pytest.raises(IdentityExchangeCandidateInvalid):
            await adopt_portable_identity(
                adopter,
                adopt_command(
                    destination.organization_id,
                    destination.operator_principal_id,
                    match.candidate_ref,
                    value="40299999999",
                ),
            )
        adopted = await adopt_portable_identity(
            adopter,
            adopt_command(
                destination.organization_id,
                destination.operator_principal_id,
                match.candidate_ref,
                value=cedula,
            ),
        )
        assert adopted.party.documents[0].normalized_value == cedula
        with pytest.raises(DBAPIError):
            async with tenant_transaction(
                app_session_factory, destination.organization_id
            ) as session:
                await session.execute(text("SELECT * FROM request_engine.portable_person_profiles"))
