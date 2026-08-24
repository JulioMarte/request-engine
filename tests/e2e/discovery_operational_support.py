from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory

from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, TenantSandbox, actor_for


def grant_manage_discovery(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'operations.manage_discovery',
            clock_timestamp() + interval '1 day'
        )
        """,
        (sandbox.organization_id, sandbox.principal_id, sandbox.party_id),
    )


def create_classification(conn: PgConnection, prefix: str = "cardiology") -> str:
    key = f"{prefix}_{uuid4().hex}"
    conn.execute(
        """
        INSERT INTO request_engine.service_classifications (classification_key, canonical_name)
        VALUES (%s, 'F2 E2E Classification')
        """,
        (key,),
    )
    return key


def operational_client(factory: SessionFactory, sandbox: TenantSandbox) -> AsyncClient:
    resolver = SandboxResolver({sandbox.token: actor_for(sandbox)})
    app = create_operational_app(session_factory=factory, actor_resolver=resolver)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
