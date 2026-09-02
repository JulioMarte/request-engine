import pytest

from request_engine.modules.tenancy.application.identity_exchange_errors import (
    IdentityExchangeIdentityConflict,
)
from request_engine.platform.db.session import SessionFactory

from ._identity_exchange_world import publish_additional_document, published_source
from ._party_support import PgConnection

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_alias_document_cannot_join_two_existing_portable_people(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    passport = "SC2468101"
    first, first_party, _, _ = await published_source(
        admin_conn,
        app_session_factory,
        value="40200000010",
    )
    await publish_additional_document(
        app_session_factory,
        first,
        first_party,
        kind="passport",
        value=passport,
        authority="DO",
    )
    second, second_party, _, _ = await published_source(
        admin_conn,
        app_session_factory,
        value="40200000011",
    )

    with pytest.raises(IdentityExchangeIdentityConflict):
        await publish_additional_document(
            app_session_factory,
            second,
            second_party,
            kind="passport",
            value=passport,
            authority="DO",
        )

    counts = admin_conn.execute(
        "SELECT count(DISTINCT b.portable_party_id), "
        "count(DISTINCT i.id) FILTER "
        "(WHERE i.kind = 'passport' AND i.authority = 'DO') "
        "FROM request_engine.organization_party_bindings b "
        "LEFT JOIN request_engine.portable_party_identifiers i "
        "ON i.portable_party_id = b.portable_party_id AND i.active "
        "WHERE b.organization_id IN (%s, %s) AND b.active",
        (first.organization_id, second.organization_id),
    ).fetchone()
    assert counts == (2, 1)
