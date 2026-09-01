"""Operator-scoped relay idempotency through the public HTTP surface (§9.1).

Idempotency keys are scoped to the effective principal — the attributed
operator, not the technical relay caller: the same key relayed for two
different operators executes twice (two parties), while the same operator
relaying the same key a second time replays the stored result (one party).
"""

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .party_relay_oracles import party_count
from .party_relay_support import (
    PARTY_CAPABILITIES,
    bot_actor,
    register_body,
    relay_client,
    relay_headers,
    seed_party_registry_tenant,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_same_key_for_two_operators_executes_twice(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    bots = {"bot": bot_actor(organization_id, ids["bot"], relay=True)}
    grants = {
        ids["operator"]: PARTY_CAPABILITIES,
        ids["second_operator"]: PARTY_CAPABILITIES,
    }
    async with relay_client(e2e_session_factory, bots, grants) as client:
        first = await client.post(
            "/v1/parties",
            json=register_body("Paciente Uno", whatsapp="809-555-0311"),
            headers=relay_headers("bot", acting=ids["operator"], idempotency_key="relay-key-1"),
        )
        assert first.status_code == 201, first.text
        second = await client.post(
            "/v1/parties",
            json=register_body("Paciente Dos", whatsapp="809-555-0312"),
            headers=relay_headers(
                "bot", acting=ids["second_operator"], idempotency_key="relay-key-1"
            ),
        )
        assert second.status_code == 201, second.text
        assert first.json()["party_id"] != second.json()["party_id"]
        assert party_count(e2e_admin_conn, organization_id) == 2


@pytest.mark.asyncio
async def test_same_key_for_the_same_operator_replays(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    bots = {"bot": bot_actor(organization_id, ids["bot"], relay=True)}
    grants = {ids["operator"]: PARTY_CAPABILITIES}
    body = register_body("Paciente Replay", whatsapp="809-555-0313")
    headers = relay_headers("bot", platform="whatsapp_bot", acting=ids["operator"])
    headers["Idempotency-Key"] = "relay-key-replay"
    async with relay_client(e2e_session_factory, bots, grants) as client:
        first = await client.post("/v1/parties", json=body, headers=headers)
        assert first.status_code == 201, first.text
        replayed = await client.post("/v1/parties", json=body, headers=headers)
        assert replayed.status_code == 201, replayed.text
        assert replayed.json()["party_id"] == first.json()["party_id"]
        assert party_count(e2e_admin_conn, organization_id) == 1
