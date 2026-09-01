"""Party registry attribution authority through the public HTTP surface.

Per docs/v3/38 §9.1/§9.2: every contact point is created verified; provenance
is carried by `source_kind` + `platform`. A bot (INTEGRATION, no acting
operator) registers as the subject. A trusted bot holding
`platform.acting_for_operator` may relay through an admitted acting operator:
the effective actor is the operator — resolved by the REAL DB-backed
deployment resolver against authoritative principals rows — all semantic
capability checks run against the operator's grant set, and the technical
caller is preserved in the durable facts and the revision ledger. The relay
fails closed when the caller lacks the admission permission or the operator
lacks the mutation capability.
"""

from uuid import UUID

import pytest

from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .party_relay_oracles import contact_point_facts, latest_revision, party_count
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
async def test_bot_without_relay_is_subject_and_verified(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    bots = {"bot-plain": bot_actor(organization_id, ids["bot_plain"], relay=False)}
    async with relay_client(e2e_session_factory, bots, {}) as client:
        created = await client.post(
            "/v1/parties",
            json=register_body("Paciente WhatsApp", whatsapp="809-555-0123"),
            headers=relay_headers("bot-plain", platform="whatsapp_bot"),
        )
        assert created.status_code == 201, created.text
        contact = created.json()["contact_points"][0]
        assert contact["verified"] is True and contact["source_kind"] == "subject"
        assert contact_point_facts(
            e2e_admin_conn, organization_id, UUID(contact["contact_point_id"])
        ) == (True, "subject", "whatsapp_bot", None, ids["bot_plain"])

        confirm = await client.post(
            f"/v1/parties/{created.json()['party_id']}"
            f"/contact-points/{contact['contact_point_id']}/confirm",
            headers=relay_headers("bot-plain"),
        )
        assert confirm.status_code == 403, confirm.text


@pytest.mark.asyncio
async def test_relayed_bot_executes_with_operator_authority(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    bots = {
        "bot": bot_actor(organization_id, ids["bot"], relay=True),
        "bot-plain": bot_actor(organization_id, ids["bot_plain"], relay=False),
    }
    grants = {
        ids["operator"]: PARTY_CAPABILITIES,
        ids["limited_operator"]: PARTY_CAPABILITIES - {"parties.register"},
    }
    async with relay_client(e2e_session_factory, bots, grants) as client:
        before = party_count(e2e_admin_conn, organization_id)
        relayed = await client.post(
            "/v1/parties",
            json=register_body("Paciente Relayed", phone="(809) 555-0199"),
            headers=relay_headers("bot", platform="whatsapp_bot", acting=ids["operator"]),
        )
        assert relayed.status_code == 201, relayed.text
        contact = relayed.json()["contact_points"][0]
        assert contact["verified"] is True and contact["source_kind"] == "operator"
        assert contact_point_facts(
            e2e_admin_conn, organization_id, UUID(contact["contact_point_id"])
        ) == (True, "operator", "whatsapp_bot", ids["bot"], ids["operator"])
        assert latest_revision(
            e2e_admin_conn, organization_id, UUID(relayed.json()["party_id"])
        ) == (ids["bot"], ids["operator"], "operator", "whatsapp_bot")

        laundered = await client.post(
            "/v1/parties",
            json=register_body("No Authority"),
            headers=relay_headers("bot", acting=ids["limited_operator"]),
        )
        assert laundered.status_code == 403, laundered.text
        assert laundered.json()["error"]["details"]["capability"] == "parties.register"

        unadmitted = await client.post(
            "/v1/parties",
            json=register_body("No Admission"),
            headers=relay_headers("bot-plain", acting=ids["operator"]),
        )
        assert unadmitted.status_code == 403, unadmitted.text
        assert unadmitted.json()["error"]["details"]["capability"] == "platform.acting_for_operator"

        confirmed = await client.post(
            f"/v1/parties/{relayed.json()['party_id']}"
            f"/contact-points/{contact['contact_point_id']}/confirm",
            headers=relay_headers("bot", acting=ids["operator"]),
        )
        assert confirmed.status_code == 200, confirmed.text
        assert party_count(e2e_admin_conn, organization_id) == before + 1
