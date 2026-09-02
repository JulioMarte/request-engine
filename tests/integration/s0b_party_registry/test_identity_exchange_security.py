import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.modules.tenancy.application.identity_exchange import (
    adopt_portable_identity,
    match_portable_identity,
)
from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeCandidateInvalid,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from ._identity_exchange_support import adopt_command, match_command, operator_actor
from ._identity_exchange_world import published_source
from ._party_support import PgConnection
from ._party_world import create_party_registry_world

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_wrong_document_does_not_consume_candidate(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000002"
    _, _, matcher, adopter = await published_source(admin_conn, app_session_factory, value=cedula)
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


@pytest.mark.asyncio
async def test_same_passport_number_from_different_country_does_not_match(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    passport = "SC7654321"
    _, _, matcher, _ = await published_source(
        admin_conn,
        app_session_factory,
        value=passport,
        kind="passport",
        authority="DO",
    )
    destination = create_party_registry_world(admin_conn, prefix="s0d-passport-isolation")
    with operator_actor(destination.organization_id, destination.operator_principal_id):
        result = await match_portable_identity(
            matcher,
            match_command(
                destination.organization_id,
                destination.operator_principal_id,
                passport,
                kind="passport",
                authority="US",
            ),
        )
    assert not result.matched
    assert result.candidate_ref is None


@pytest.mark.asyncio
async def test_global_index_stores_fingerprint_not_raw_document(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    cedula = "40200000003"
    await published_source(admin_conn, app_session_factory, value=cedula)
    row = admin_conn.execute(
        "SELECT fingerprint FROM request_engine.portable_person_identifiers "
        "WHERE kind = 'cedula' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    fingerprint = str(row[0])
    assert fingerprint != cedula
    assert cedula not in fingerprint
    assert len(fingerprint) == 64


@pytest.mark.asyncio
async def test_runtime_app_cannot_select_global_portable_profiles(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    destination = create_party_registry_world(admin_conn, prefix="s0d-sql-private")
    with (
        operator_actor(destination.organization_id, destination.operator_principal_id),
        pytest.raises(DBAPIError),
    ):
        async with tenant_transaction(
            app_session_factory,
            destination.organization_id,
        ) as session:
            await session.execute(text("SELECT * FROM request_engine.portable_person_profiles"))
