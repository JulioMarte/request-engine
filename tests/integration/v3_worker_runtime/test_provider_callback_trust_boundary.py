from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.callbacks import (
    TrustedProviderCallbackContext,
    ingest_provider_callback,
)

PgConnection = Connection[Any]


def _organization(admin_conn: PgConnection, label: str) -> UUID:
    row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"callback-{label}-{uuid4().hex}", f"Callback {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@dataclass
class StubCallbackAuthenticator:
    context: TrustedProviderCallbackContext
    calls: int = 0

    async def authenticate_callback(self, request: Request) -> TrustedProviderCallbackContext:
        del request
        self.calls += 1
        return self.context


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/provider-callback",
            "raw_path": b"/provider-callback",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 443),
        }
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i13_provider_callback_authority_is_derived_before_event_ingest(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    trusted_org = _organization(admin_conn, "trusted")
    attacker_named_org = _organization(admin_conn, "payload")
    authenticator = StubCallbackAuthenticator(
        TrustedProviderCallbackContext(
            organization_id=trusted_org,
            provider_key="trusted-provider",
            connection_key="primary",
        )
    )
    provider_event_id = f"event-{uuid4().hex}"
    payload: dict[str, object] = {
        "organization_id": str(attacker_named_org),
        "provider_key": "payload-selected-provider",
        "connection_key": "payload-selected-connection",
        "status": "delivered",
    }

    receipt = await ingest_provider_callback(
        app_session_factory,
        authenticator,
        _request(),
        provider_event_id=provider_event_id,
        payload=payload,
    )

    assert authenticator.calls == 1
    stored = admin_conn.execute(
        """
        SELECT organization_id, provider_key, connection_key, provider_event_id, payload
        FROM request_engine.provider_events
        WHERE id = %s
        """,
        (receipt.id,),
    ).fetchone()
    assert stored is not None
    assert stored[0] == trusted_org
    assert stored[1] == "trusted-provider"
    assert stored[2] == "primary"
    assert stored[3] == provider_event_id
    assert stored[4] == payload

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.provider_events
        WHERE organization_id = %s
        """,
        (attacker_named_org,),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
        """,
        (trusted_org,),
    ).fetchone() == (0,)
