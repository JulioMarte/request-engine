"""Shared world/composition support for the acting-operator relay e2e proofs.

The relay flow uses the real DB-backed operator resolver against authoritative
``principals`` and ``principal_authority_grants`` rows. Deployment-configured
operator capabilities are only a ceiling over RE-owned standing authority.
"""

from typing import cast
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext, PrincipalKind

from .operational_support import PgConnection, new_org
from .tenant_sandbox import SandboxResolver

SIGNING_KEY = b"request-engine-e2e-tenant-signing-key"
PARTY_CAPABILITIES = frozenset(
    {
        "parties.register",
        "parties.add_contact_point",
        "parties.confirm_contact_point",
        "parties.lookup",
    }
)
RELAY_PERMISSION = "platform.acting_for_operator"


def _seed_platform_provisioner(conn: PgConnection) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane,
            principal_kind,
            external_subject
        ) VALUES ('platform', 'human', %s)
        RETURNING id
        """,
        (f"e2e-party-relay-provisioner-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    provisioner_id = cast(UUID, row[0])
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id,
            principal_id,
            principal_plane,
            authority_plane,
            capability_key,
            delegable,
            granted_by_principal_id,
            provenance_kind,
            provenance_reference
        ) VALUES (
            NULL, %s, 'platform', 'platform', 'organization.provision', true,
            NULL, 'trust_bootstrap', %s
        )
        """,
        (provisioner_id, f"e2e-party-relay-root:{uuid4().hex}"),
    )
    return provisioner_id


def _grant_operator_authority(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    provisioner_id: UUID,
    capabilities: frozenset[str],
) -> None:
    for capability in sorted(capabilities):
        conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id,
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                %s, %s, 'tenant', 'operational', %s, false, %s,
                'provisioning', %s
            )
            """,
            (
                organization_id,
                principal_id,
                capability,
                provisioner_id,
                f"e2e-party-relay:{uuid4().hex}",
            ),
        )


def seed_party_registry_tenant(conn: PgConnection) -> tuple[UUID, dict[str, UUID]]:
    """One tenant with real operator/bot principals plus cross-tenant bait."""

    provisioner_id = _seed_platform_provisioner(conn)
    organization_id = new_org(conn, "s0b-party")
    foreign_organization_id = new_org(conn, "s0b-party-foreign")
    ids: dict[str, UUID] = {"platform_provisioner": provisioner_id}
    for key, kind, organization, subject in (
        ("operator", "human", organization_id, "front-desk"),
        ("second_operator", "human", organization_id, "second-desk"),
        ("limited_operator", "human", organization_id, "limited-desk"),
        ("bot", "integration", organization_id, "chatwoot-bot"),
        ("bot_plain", "integration", organization_id, "plain-bot"),
        ("bot_operator", "integration", organization_id, "bot-operator"),
        ("foreign_operator", "human", foreign_organization_id, "foreign-desk"),
    ):
        row = conn.execute(
            "INSERT INTO request_engine.principals (organization_id, principal_kind,"
            " external_subject) VALUES (%s, %s, %s) RETURNING id",
            (organization, kind, f"{subject}-{uuid4().hex}"),
        ).fetchone()
        assert row is not None
        ids[key] = cast(UUID, row[0])

    _grant_operator_authority(
        conn,
        organization_id=organization_id,
        principal_id=ids["operator"],
        provisioner_id=provisioner_id,
        capabilities=PARTY_CAPABILITIES,
    )
    _grant_operator_authority(
        conn,
        organization_id=organization_id,
        principal_id=ids["second_operator"],
        provisioner_id=provisioner_id,
        capabilities=PARTY_CAPABILITIES,
    )
    _grant_operator_authority(
        conn,
        organization_id=organization_id,
        principal_id=ids["limited_operator"],
        provisioner_id=provisioner_id,
        capabilities=PARTY_CAPABILITIES - {"parties.register"},
    )
    return organization_id, ids


class OperatorGrantSource:
    """Deployment ceiling model: it can restrict, but never grant, operator authority."""

    def __init__(self, grants: dict[UUID, frozenset[str]]) -> None:
        self._grants = grants

    async def operator_capabilities(
        self, organization_id: UUID, principal_id: UUID
    ) -> frozenset[str]:
        return self._grants.get(principal_id, frozenset())


def bot_actor(organization_id: UUID, principal_id: UUID, *, relay: bool) -> ActorContext:
    capabilities = PARTY_CAPABILITIES - {"parties.confirm_contact_point"}
    if relay:
        capabilities = capabilities | {RELAY_PERMISSION}
    return ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=capabilities,
        principal_kind=PrincipalKind.INTEGRATION,
    )


def relay_client(
    session_factory: SessionFactory,
    bot_actors: dict[str, ActorContext],
    grants: dict[UUID, frozenset[str]],
) -> AsyncClient:
    """Compose the app with RE authority plus an explicit deployment ceiling."""

    app = create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(bot_actors),
        appointment_option_signing_key=SIGNING_KEY,
        operator_capability_source=OperatorGrantSource(grants),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def register_body(display_name: str, **contact: str) -> dict[str, object]:
    points = [{"channel": channel, "value": value} for channel, value in contact.items()]
    return {"display_name": display_name, "contact_points": points}


def relay_headers(
    token: str,
    *,
    platform: str | None = None,
    acting: UUID | None = None,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": idempotency_key or uuid4().hex,
    }
    if platform is not None:
        headers["X-RE-Platform"] = platform
    if acting is not None:
        headers["X-RE-Acting-Operator"] = str(acting)
    return headers
