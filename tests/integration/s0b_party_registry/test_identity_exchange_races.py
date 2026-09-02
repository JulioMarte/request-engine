import asyncio

import pytest

from request_engine.modules.tenancy.application.identity_exchange import (
    AdoptPortableIdentityCommand,
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeAlreadyAdopted,
)
from request_engine.modules.tenancy.contracts.identity_exchange import IdentityAdoptionResult
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adopt_command, match_command, operator_actor
from ._identity_exchange_world import (
    publish_additional_document,
    published_source,
)
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_concurrent_alias_adoptions_create_one_local_party(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000005"
    passport = "SC1357913"
    source, party, _, _ = await published_source(admin_conn, app_session_factory, value=cedula)
    matcher, adopter = await publish_additional_document(
        app_session_factory,
        source,
        party,
        kind="passport",
        value=passport,
        authority="DO",
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-alias-race")

    with operator_actor(destination.organization_id, destination.operator_principal_id):
        cedula_match = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                cedula,
            ),
        )
        passport_match = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                passport,
                kind="passport",
                authority="DO",
            ),
        )
        assert cedula_match.candidate_ref is not None
        assert passport_match.candidate_ref is not None

        async def attempt(
            command: AdoptPortableIdentityCommand,
        ) -> IdentityAdoptionResult | IdentityExchangeAlreadyAdopted:
            try:
                return await adopt_portable_identity(adopter, command)
            except IdentityExchangeAlreadyAdopted as error:
                return error

        outcomes = await asyncio.gather(
            attempt(
                adopt_command(
                    destination.organization_id,
                    destination.operator_principal_id,
                    cedula_match.candidate_ref,
                    value=cedula,
                    key="cedula-race",
                )
            ),
            attempt(
                adopt_command(
                    destination.organization_id,
                    destination.operator_principal_id,
                    passport_match.candidate_ref,
                    value=passport,
                    kind="passport",
                    authority="DO",
                    key="passport-race",
                )
            ),
        )

    winners = [item for item in outcomes if isinstance(item, IdentityAdoptionResult)]
    conflicts = [item for item in outcomes if isinstance(item, IdentityExchangeAlreadyAdopted)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert conflicts[0].existing_party_id == winners[0].party.party_id

    counts = admin_conn.execute(
        "SELECT "
        "(SELECT count(*) FROM request_engine.parties "
        " WHERE organization_id = %s AND display_name = 'María Gómez'), "
        "(SELECT count(*) FROM request_engine.organization_person_bindings "
        " WHERE organization_id = %s AND active)",
        (destination.organization_id, destination.organization_id),
    ).fetchone()
    assert counts == (1, 1)
