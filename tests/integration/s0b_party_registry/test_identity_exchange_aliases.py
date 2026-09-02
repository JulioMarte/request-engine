import pytest

from request_engine.modules.tenancy.adapters.db.party_registry_commands import (
    PostgresPartyRegistryCommands,
)
from request_engine.modules.tenancy.application.commands import add_party_document
from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
    publish_portable_profile,
)
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import (
    adapters,
    adopt_command,
    match_command,
    operator_actor,
    publish_command,
)
from ._identity_exchange_world import published_source
from ._party_commands import document_command
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_one_portable_person_can_be_found_by_cedula_or_passport(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000004"
    passport = "SC2468101"
    source, party, _, _ = await published_source(admin_conn, app_session_factory, value=cedula)
    commands = PostgresPartyRegistryCommands(app_session_factory)
    await add_party_document.add_party_document(
        commands,
        document_command(
            source.organization_id,
            source.operator_principal_id,
            party.party_id,
            "passport",
            passport,
            authority="DO",
        ),
    )
    publisher, matcher, adopter = adapters(app_session_factory)
    with operator_actor(source.organization_id, source.operator_principal_id):
        await publish_portable_profile(
            publisher,
            publish_command(
                source.organization_id,
                source.operator_principal_id,
                party.party_id,
                kind="passport",
                authority="DO",
            ),
        )

    row = admin_conn.execute(
        "SELECT b.portable_person_id, count(i.id) "
        "FROM request_engine.organization_person_bindings b "
        "JOIN request_engine.portable_person_identifiers i "
        "ON i.portable_person_id = b.portable_person_id AND i.active "
        "WHERE b.organization_id = %s AND b.party_id = %s AND b.active "
        "GROUP BY b.portable_person_id",
        (source.organization_id, party.party_id),
    ).fetchone()
    assert row is not None and int(row[1]) == 2

    destination = create_party_registry_world(admin_conn, prefix="s0d-alias-destination")
    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                passport,
                kind="passport",
                authority="DO",
            ),
        )
        assert match.candidate_ref is not None
        adoption = await adopt_portable_identity(
            adopter,
            adopt_command(
                destination.organization_id,
                destination.operator_principal_id,
                match.candidate_ref,
                value=passport,
                kind="passport",
                authority="DO",
            ),
        )
    assert adoption.party.documents[0].authority == "DO"
    assert adoption.party.documents[0].normalized_value == passport
