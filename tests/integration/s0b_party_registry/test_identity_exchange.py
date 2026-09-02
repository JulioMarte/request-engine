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
async def test_cross_org_adoption_creates_local_party_without_copying_insurance(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000001"
    source, source_party, matcher, adopter = await published_source(
        admin_conn,
        app_session_factory,
        cedula=cedula,
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
    assert {item.normalized_value for item in adoption.party.contact_points} == {"+18095551212"}
    assert {item.normalized_value for item in adoption.party.documents} == {cedula}
    assert replay.party.party_id == adoption.party.party_id
    assert len(adoption.portable_insurance_identifiers) == 1
    reader = PostgresPartyAdministrativeIdentifierReader(app_session_factory)
    assert await lookup_ids(reader, destination.organization_id) == []
    assert source.organization_id != destination.organization_id
