from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote_plus, urlsplit
from uuid import uuid4

from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import sql

from request_engine.entrypoints.http.discovery_app import create_discovery_app
from request_engine.entrypoints.http.discovery_availability_app import (
    create_discovery_availability_app,
)
from request_engine.modules.booking.adapters.discovery_slot_reader import HttpPublishedSlotReader
from request_engine.modules.discovery.api.composition import build_discovery_database_ports
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.platform_discovery import (
    DISCOVERY_SEARCH_CAPABILITY,
    DISCOVERY_SLOT_READ_CAPABILITY,
    PlatformDiscoveryActor,
)

from .operational_support import PgConnection

_TOKEN = "discovery-e2e-token"


class DiscoveryResolver:
    async def resolve_actor(self, request: Request) -> PlatformDiscoveryActor:
        if request.headers.get("authorization") != f"Bearer {_TOKEN}":
            raise AuthenticationRequired
        return PlatformDiscoveryActor(
            principal_id=uuid4(),
            capabilities=frozenset(
                {DISCOVERY_SEARCH_CAPABILITY, DISCOVERY_SLOT_READ_CAPABILITY}
            ),
            authentication_method="e2e",
        )


def _discovery_url(template_url: str, role: str, password: str) -> str:
    parsed = urlsplit(template_url)
    host = parsed.hostname or "127.0.0.1"
    port = f":{parsed.port}" if parsed.port is not None else ""
    return (
        f"postgresql+asyncpg://{quote_plus(role)}:{quote_plus(password)}"
        f"@{host}{port}{parsed.path}"
    )


@asynccontextmanager
async def discovery_client(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    app_database_url: str,
) -> AsyncIterator[AsyncClient]:
    role = f"re_e2e_discovery_{secrets.token_hex(6)}"
    password = secrets.token_urlsafe(24)
    admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_discovery NOBYPASSRLS").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )
    engine = create_postgres_engine(_discovery_url(app_database_url, role, password))
    resolver = DiscoveryResolver()
    internal_app = create_discovery_availability_app(
        domain_session_factory=app_session_factory,
        actor_resolver=resolver,
    )
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    internal_client = AsyncClient(
        transport=ASGITransport(app=internal_app),
        base_url="http://booking-internal",
        headers=headers,
    )
    ports = build_discovery_database_ports(create_session_factory(engine))
    public_app = create_discovery_app(
        candidate_reader=ports.candidate_reader,
        slot_reader=HttpPublishedSlotReader(internal_client),
        handoff_issuer=ports.handoff_issuer,
        actor_resolver=resolver,
    )
    public_client = AsyncClient(
        transport=ASGITransport(app=public_app),
        base_url="http://discovery",
        headers=headers,
    )
    try:
        yield public_client
    finally:
        await public_client.aclose()
        await internal_client.aclose()
        await engine.dispose()
        admin_conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
