import pytest

from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeCandidateInvalid,
)
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_support import adopt_command, match_command, operator_actor
from ._identity_exchange_world import published_source
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_candidate_is_scoped_to_destination_organization(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000008"
    _, _, matcher, adopter = await published_source(admin_conn, app_session_factory, value=cedula)
    first = create_party_registry_world(admin_conn, prefix="s0d-candidate-a")
    second = create_party_registry_world(admin_conn, prefix="s0d-candidate-b")
    with operator_actor(first.organization_id, first.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(first.organization_id, first.operator_principal_id, cedula),
        )
    assert match.candidate_ref is not None
    with operator_actor(second.organization_id, second.operator_principal_id):
        with pytest.raises(IdentityExchangeCandidateInvalid):
            await adopt_portable_identity(
                adopter,
                adopt_command(
                    second.organization_id,
                    second.operator_principal_id,
                    match.candidate_ref,
                    value=cedula,
                ),
            )
    with operator_actor(first.organization_id, first.operator_principal_id):
        adopted = await adopt_portable_identity(
            adopter,
            adopt_command(
                first.organization_id,
                first.operator_principal_id,
                match.candidate_ref,
                value=cedula,
            ),
        )
    assert adopted.party.organization_id == first.organization_id


@pytest.mark.asyncio
async def test_expired_candidate_cannot_be_adopted(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000009"
    _, _, matcher, adopter = await published_source(admin_conn, app_session_factory, value=cedula)
    destination = create_party_registry_world(admin_conn, prefix="s0d-candidate-expired")
    with operator_actor(destination.organization_id, destination.operator_principal_id):
        match = await match_portable_identity(
            matcher,
            match_command(destination.organization_id, destination.operator_principal_id, cedula),
        )
    assert match.candidate_ref is not None
    admin_conn.execute(
        "UPDATE request_engine.identity_exchange_candidates "
        "SET expires_at = clock_timestamp() - interval '1 second' WHERE id = %s",
        (match.candidate_ref,),
    )
    with operator_actor(destination.organization_id, destination.operator_principal_id):
        with pytest.raises(IdentityExchangeCandidateInvalid):
            await adopt_portable_identity(
                adopter,
                adopt_command(
                    destination.organization_id,
                    destination.operator_principal_id,
                    match.candidate_ref,
                    value=cedula,
                ),
            )
