from dataclasses import replace
from typing import LiteralString, cast
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, TenantSandbox, actor_for

OPERATIONAL_CAPABILITIES = frozenset(
    {"organization.manage_profile", "booking.manage_supply", "catalog.manage"}
)


def grant_operational_scopes(conn: PgConnection, sandbox: TenantSandbox) -> None:
    for scope in (
        "operations.manage_profile",
        "operations.manage_supply",
        "operations.manage_terms",
    ):
        conn.execute(
            """
            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id,
                authority_kind, scope_key, valid_until
            ) VALUES (
                %s, %s, %s, 'delegated', %s,
                clock_timestamp() + interval '1 day'
            )
            """,
            (sandbox.organization_id, sandbox.principal_id, sandbox.party_id, scope),
        )


def revision(conn: PgConnection, query: LiteralString, entity_id: UUID) -> int:
    row = conn.execute(query, (entity_id,)).fetchone()
    assert row is not None
    return cast(int, row[0])


def operator_actor(
    sandbox: TenantSandbox,
    *,
    capabilities: frozenset[str] = OPERATIONAL_CAPABILITIES,
) -> ActorContext:
    """Add only the canonical operational capabilities required by the scenario."""

    base = actor_for(sandbox)
    return replace(base, capabilities=base.capabilities | capabilities)


def operator_client(factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    app = create_operational_app(
        session_factory=factory,
        actor_resolver=SandboxResolver({sandbox.token: operator_actor(sandbox)}),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
