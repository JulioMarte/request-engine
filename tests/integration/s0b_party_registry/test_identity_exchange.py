import pytest

from request_engine.modules.tenancy.adapters.db.party_administrative_identifier_reader import (
    PostgresPartyAdministrativeIdentifierReader,
)
from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adopt_command, match_command, operator_actor
from ._identity_exchange_world import published_source
from ._party_administrative_identifier_support import lookup_ids
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_cross_org_adoption_by_cedula_creates_normal_local_party(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000001"
    source, source_party, matcher, adopter = await published_source(
        admin_conn, app_session_factory, value=cedula
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-destination")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(destination.organization_id, destination.operator_principal_id, cedula),
        )
        assert match.matched and match.candidate_ref is not None
        command = adopt_command(
            destination.organization_id,
            destination.operator_principal_id,
            match.candidate_ref,
            value=cedula,
            key="stable-adoption",
        )
        adoption = await adopt_portable_identity(adopter, command)
        replay = await adopt_portable_identity(adopter, command)

    assert adoption.party.party_id != source_party.party_id
    assert adoption.party.organization_id == destination.organization_id
    assert adoption.party.display_name == "María Gómez"
    assert adoption.party.documents[0].authority == "DO:JCE"
    assert adoption.party.documents[0].normalized_value == cedula
    assert replay.party.party_id == adoption.party.party_id
    assert len(adoption.portable_insurance_identifiers) == 1
    reader = PostgresPartyAdministrativeIdentifierReader(app_session_factory)
    assert await lookup_ids(reader, destination.organization_id) == []
    assert source.organization_id != destination.organization_id


@pytest.mark.asyncio
async def test_cross_org_adoption_by_passport_preserves_issuing_country(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    passport = "SC1234567"
    _, source_party, matcher, adopter = await published_source(
        admin_conn,
        app_session_factory,
        value=passport,
        kind="passport",
        authority="DO",
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-passport-destination")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                passport.lower(),
                kind="passport",
                authority="do",
            ),
        )
        assert match.matched and match.candidate_ref is not None
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

    document = adoption.party.documents[0]
    assert adoption.party.party_id != source_party.party_id
    assert document.kind == "passport"
    assert document.authority == "DO"
    assert document.normalized_value == passport
