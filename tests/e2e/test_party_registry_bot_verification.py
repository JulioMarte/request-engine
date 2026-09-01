"""I-S0b-5 through the public HTTP surface: bot-created contact points are
never verified at creation, regardless of client-sent fields.

A bot actor (no subject-override authority, no confirm capability) registers
a Party; the response and the durable row show `verified = false` and
`registered_via = 'bot'`. The bot cannot confirm (403 by capability gate).
A granted operator confirms; verification flips durably. An operator-created
contact point is verified at creation. Attribution is server-derived.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection, new_org
from .tenant_sandbox import ALL_PUBLIC_CAPABILITIES, client_with_actors

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

PARTY_CAPABILITIES = frozenset(
    {
        "parties.register",
        "parties.add_contact_point",
        "parties.confirm_contact_point",
        "parties.lookup",
    }
)
_OPERATOR_TOKEN = "operator-e2e-token"
_BOT_TOKEN = "bot-e2e-token"


def seed_party_registry_tenant(conn: PgConnection) -> tuple[UUID, UUID, UUID]:
    organization_id = new_org(conn, "s0b-party")
    ids: list[UUID] = []
    for kind, subject in (("human", "front-desk"), ("integration", "chatwoot-bot")):
        row = conn.execute(
            "INSERT INTO request_engine.principals (organization_id, principal_kind,"
            " external_subject) VALUES (%s, %s, %s) RETURNING id",
            (organization_id, kind, f"{subject}-{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        ids.append(cast(UUID, row[0]))
    return organization_id, ids[0], ids[1]


def durable_contact_point(
    conn: PgConnection, organization_id: UUID, contact_point_id: UUID
) -> tuple[bool, str | None]:
    row = conn.execute(
        "SELECT verified, registered_via FROM request_engine.party_contact_points"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, contact_point_id),
    ).fetchone()
    assert row is not None
    return cast(bool, row[0]), row[1]


@pytest.mark.asyncio
async def test_bot_registration_is_never_verified_until_operator_confirms(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, operator_id, bot_id = seed_party_registry_tenant(e2e_admin_conn)
    actors = {
        _OPERATOR_TOKEN: ActorContext(
            organization_id=organization_id,
            principal_id=operator_id,
            capabilities=ALL_PUBLIC_CAPABILITIES | PARTY_CAPABILITIES,
        ),
        _BOT_TOKEN: ActorContext(
            organization_id=organization_id,
            principal_id=bot_id,
            capabilities=PARTY_CAPABILITIES - {"parties.confirm_contact_point"},
        ),
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        bot_register = await client.post(
            "/v1/parties",
            json={
                "display_name": "Paciente WhatsApp",
                "contact_points": [{"channel": "whatsapp", "value": "809-555-0123"}],
            },
            headers={"Authorization": f"Bearer {_BOT_TOKEN}", "Idempotency-Key": uuid4().hex},
        )
        assert bot_register.status_code == 201, bot_register.text
        bot_party = bot_register.json()
        contact = bot_party["contact_points"][0]
        assert bot_party["documents"] == []
        assert contact["verified"] is False and contact["registered_via"] == "bot"
        contact_point_id = UUID(contact["contact_point_id"])
        assert durable_contact_point(e2e_admin_conn, organization_id, contact_point_id) == (
            False,
            "bot",
        )

        confirm_url = (
            f"/v1/parties/{bot_party['party_id']}/contact-points/{contact_point_id}/confirm"
        )
        bot_confirm = await client.post(
            confirm_url,
            headers={"Authorization": f"Bearer {_BOT_TOKEN}", "Idempotency-Key": uuid4().hex},
        )
        assert bot_confirm.status_code == 403, bot_confirm.text
        assert durable_contact_point(e2e_admin_conn, organization_id, contact_point_id) == (
            False,
            "bot",
        )

        operator_confirm = await client.post(
            confirm_url,
            headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}", "Idempotency-Key": uuid4().hex},
        )
        assert operator_confirm.status_code == 200, operator_confirm.text
        assert operator_confirm.json()["verified"] is True
        assert durable_contact_point(e2e_admin_conn, organization_id, contact_point_id) == (
            True,
            "bot",
        )

        operator_register = await client.post(
            "/v1/parties",
            json={
                "display_name": "Paciente Mostrador",
                "contact_points": [{"channel": "phone", "value": "(809) 555-0199"}],
            },
            headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}", "Idempotency-Key": uuid4().hex},
        )
        assert operator_register.status_code == 201, operator_register.text
        operator_contact = operator_register.json()["contact_points"][0]
        assert operator_contact["verified"] and operator_contact["registered_via"] == "operator"
