"""Party registry attribution authority through the public HTTP surface.

Per docs/v3/38 §9.1/§9.2: every contact point is created verified; provenance
is carried by `source_kind` + `platform`. A bot (INTEGRATION, no acting
operator) registers as the subject. A trusted bot holding
`platform.acting_for_operator` may relay through an admitted acting operator:
the effective actor is the operator, all semantic capability checks run
against the operator's grant set, and the technical caller is preserved as
the attributed relay. The relay fails closed when the caller lacks the
admission permission or the operator lacks the mutation capability.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

from .operational_support import PgConnection, new_org
from .tenant_sandbox import ALL_PUBLIC_CAPABILITIES, SandboxResolver, client_with_actors

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

PARTY_CAPABILITIES = frozenset(
    {
        "parties.register",
        "parties.add_contact_point",
        "parties.confirm_contact_point",
        "parties.lookup",
    }
)
RELAY_PERMISSION = "platform.acting_for_operator"
_BOT_TOKEN = "bot-e2e-token"
_BOT_PLAIN_TOKEN = "bot-plain-e2e-token"
_SIGNING_KEY = b"request-engine-e2e-tenant-signing-key"


class _InlineOperatorActors:
    """Deployment operator port backed by the inline e2e actor world."""

    def __init__(self, operators: dict[UUID, ActorContext]) -> None:
        self._operators = operators

    async def resolve_operator_actor(
        self, organization_id: UUID, principal_id: UUID
    ) -> ActorContext | None:
        actor = self._operators.get(principal_id)
        if actor is None or actor.organization_id != organization_id:
            return None
        return actor


def seed_party_registry_tenant(conn: PgConnection) -> tuple[UUID, dict[str, UUID]]:
    organization_id = new_org(conn, "s0b-party")
    ids: dict[str, UUID] = {}
    for key, kind, subject in (
        ("operator", "human", "front-desk"),
        ("limited_operator", "human", "limited-desk"),
        ("bot", "integration", "chatwoot-bot"),
        ("bot_plain", "integration", "plain-bot"),
    ):
        row = conn.execute(
            "INSERT INTO request_engine.principals (organization_id, principal_kind,"
            " external_subject) VALUES (%s, %s, %s) RETURNING id",
            (organization_id, kind, f"{subject}-{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        ids[key] = cast(UUID, row[0])
    return organization_id, ids


def _durable_contact_point(
    conn: PgConnection, organization_id: UUID, contact_point_id: UUID
) -> tuple[bool, str | None, str | None, UUID | None, UUID | None]:
    row = conn.execute(
        "SELECT verified, source_kind, platform, relay_principal_id,"
        " created_by_principal_id FROM request_engine.party_contact_points"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, contact_point_id),
    ).fetchone()
    assert row is not None
    return cast(tuple[bool, str | None, str | None, UUID | None, UUID | None], tuple(row))


def _party_count(conn: PgConnection, organization_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.parties WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _headers(
    token: str, *, platform: str | None = None, acting: UUID | None = None
) -> dict[str, str]:
    headers: dict[str, str] = {"Authorization": f"Bearer {token}", "Idempotency-Key": uuid4().hex}
    if platform is not None:
        headers["X-RE-Platform"] = platform
    if acting is not None:
        headers["X-RE-Acting-Operator"] = str(acting)
    return headers


def _register_body(display_name: str, **contact: str) -> dict[str, object]:
    points: list[dict[str, str]] = [
        {"channel": channel, "value": value} for channel, value in contact.items()
    ]
    return {"display_name": display_name, "contact_points": points}


@pytest.mark.asyncio
async def test_bot_without_relay_is_subject_and_verified(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    actors = {
        _BOT_PLAIN_TOKEN: ActorContext(
            organization_id=organization_id,
            principal_id=ids["bot_plain"],
            capabilities=PARTY_CAPABILITIES - {"parties.confirm_contact_point"},
            principal_kind=PrincipalKind.INTEGRATION,
        ),
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        created = await client.post(
            "/v1/parties",
            json=_register_body("Paciente WhatsApp", whatsapp="809-555-0123"),
            headers=_headers(_BOT_PLAIN_TOKEN, platform="whatsapp_bot"),
        )
        assert created.status_code == 201, created.text
        contact = created.json()["contact_points"][0]
        assert contact["verified"] is True and contact["source_kind"] == "subject"
        durable = _durable_contact_point(
            e2e_admin_conn, organization_id, UUID(contact["contact_point_id"])
        )
        assert durable == (True, "subject", "whatsapp_bot", None, ids["bot_plain"])

        confirm = await client.post(
            f"/v1/parties/{created.json()['party_id']}"
            f"/contact-points/{contact['contact_point_id']}/confirm",
            headers=_headers(_BOT_PLAIN_TOKEN),
        )
        assert confirm.status_code == 403, confirm.text


@pytest.mark.asyncio
async def test_relayed_bot_executes_with_operator_authority(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, ids = seed_party_registry_tenant(e2e_admin_conn)
    operators = {
        ids["operator"]: ActorContext(
            organization_id=organization_id,
            principal_id=ids["operator"],
            capabilities=ALL_PUBLIC_CAPABILITIES | PARTY_CAPABILITIES,
        ),
        ids["limited_operator"]: ActorContext(
            organization_id=organization_id,
            principal_id=ids["limited_operator"],
            capabilities=PARTY_CAPABILITIES - {"parties.register"},
        ),
    }
    bots = {
        _BOT_TOKEN: ActorContext(
            organization_id=organization_id,
            principal_id=ids["bot"],
            capabilities=PARTY_CAPABILITIES - {"parties.confirm_contact_point"}
            | {RELAY_PERMISSION},
            principal_kind=PrincipalKind.INTEGRATION,
        ),
        _BOT_PLAIN_TOKEN: ActorContext(
            organization_id=organization_id,
            principal_id=ids["bot_plain"],
            capabilities=PARTY_CAPABILITIES - {"parties.confirm_contact_point"},
            principal_kind=PrincipalKind.INTEGRATION,
        ),
    }
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=SandboxResolver(bots),
        appointment_option_signing_key=_SIGNING_KEY,
        operator_actor_resolver=_InlineOperatorActors(operators),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = _party_count(e2e_admin_conn, organization_id)
        relayed = await client.post(
            "/v1/parties",
            json=_register_body("Paciente Relayed", phone="(809) 555-0199"),
            headers=_headers(_BOT_TOKEN, platform="whatsapp_bot", acting=ids["operator"]),
        )
        assert relayed.status_code == 201, relayed.text
        contact = relayed.json()["contact_points"][0]
        assert contact["verified"] is True and contact["source_kind"] == "operator"
        durable = _durable_contact_point(
            e2e_admin_conn, organization_id, UUID(contact["contact_point_id"])
        )
        assert durable == (True, "operator", "whatsapp_bot", ids["bot"], ids["operator"])

        laundered = await client.post(
            "/v1/parties",
            json=_register_body("No Authority"),
            headers=_headers(_BOT_TOKEN, acting=ids["limited_operator"]),
        )
        assert laundered.status_code == 403, laundered.text
        assert laundered.json()["error"]["details"]["capability"] == "parties.register"
        assert _party_count(e2e_admin_conn, organization_id) == before + 1

        unadmitted = await client.post(
            "/v1/parties",
            json=_register_body("No Admission"),
            headers=_headers(_BOT_PLAIN_TOKEN, acting=ids["operator"]),
        )
        assert unadmitted.status_code == 403, unadmitted.text
        assert unadmitted.json()["error"]["details"]["capability"] == RELAY_PERMISSION

        confirmed = await client.post(
            f"/v1/parties/{relayed.json()['party_id']}"
            f"/contact-points/{contact['contact_point_id']}/confirm",
            headers=_headers(_BOT_TOKEN, acting=ids["operator"]),
        )
        assert confirmed.status_code == 200, confirmed.text
