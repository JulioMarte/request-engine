import pytest

from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.modules.tenancy.contracts.party_kind import PartyKind
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adopt_command, match_command, operator_actor
from ._identity_exchange_world import published_source
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_rnc_adopts_the_same_business_as_a_local_organization_party(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    rnc = "101850043"
    source, source_party, matcher, adopter = await published_source(
        admin_conn,
        app_session_factory,
        value=rnc,
        kind="rnc",
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-rnc-destination")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                rnc,
                kind="rnc",
            ),
        )
        assert match.matched and match.candidate_ref is not None
        adoption = await adopt_portable_identity(
            adopter,
            adopt_command(
                destination.organization_id,
                destination.operator_principal_id,
                match.candidate_ref,
                value="1-01-85004-3",
                kind="rnc",
                display_name="Acme Dominicana SRL",
            ),
        )

    assert source.organization_id != destination.organization_id
    assert adoption.party.party_id != source_party.party_id
    assert adoption.party.party_kind == PartyKind.ORGANIZATION.value
    assert adoption.party.documents[0].kind == "rnc"
    assert adoption.party.documents[0].authority == "DO:DGII"
    assert adoption.party.documents[0].normalized_value == rnc
    assert adoption.portable_insurance_identifiers == ()
    assert adoption.party.contact_points == ()
    assert adoption.portable_contact_suggestions
