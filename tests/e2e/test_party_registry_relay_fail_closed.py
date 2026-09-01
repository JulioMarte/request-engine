"""Relay fail-closed proofs against the REAL deployment operator resolver.

The DB-backed resolver reads authoritative `request_engine.principals` rows:
a referenced operator that is deactivated (direct-SQL prerequisite on a
column the guard does not own), belongs to a foreign organization, or is not
a HUMAN principal returns None and the relay fails closed with the platform
403 — with zero durable effect.
"""

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .party_relay_oracles import party_count
from .party_relay_support import (
    PARTY_CAPABILITIES,
    RELAY_PERMISSION,
    bot_actor,
    register_body,
    relay_client,
    relay_headers,
    seed_party_registry_tenant,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_relay_fails_closed_on_unresolvable_operator(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    e2e_admin_conn.execute(
        "UPDATE request_engine.principals SET active = false WHERE id = %s",
        (ids["operator"],),
    )
    bots = {"bot": bot_actor(organization_id, ids["bot"], relay=True)}
    grants = {ids["operator"]: PARTY_CAPABILITIES}
    cases = (
        ("deactivated", ids["operator"]),
        ("foreign organization", ids["foreign_operator"]),
        ("non-human", ids["bot_operator"]),
    )
    async with relay_client(e2e_session_factory, bots, grants) as client:
        before = party_count(e2e_admin_conn, organization_id)
        for label, acting in cases:
            refused = await client.post(
                "/v1/parties",
                json=register_body(f"No Relay {label}"),
                headers=relay_headers("bot", acting=acting),
            )
            assert refused.status_code == 403, (label, refused.text)
            assert refused.json()["error"]["details"]["capability"] == RELAY_PERMISSION
        assert party_count(e2e_admin_conn, organization_id) == before
