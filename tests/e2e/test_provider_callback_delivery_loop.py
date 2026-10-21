"""Outbound delivery loop closed through the authenticated HTTP callback.

Guarantee: a delivery dispatched through the webhook transport is finalized by
the gateway's signed provider-event callback over HTTP (persist before
interpretation, then the fenced ProviderEvent worker), a duplicate callback is
absorbed by ProviderEvent dedupe, and an unauthenticated callback (wrong key or
an organization that does not exist) persists nothing.

The gateway side is simulated only at the external boundary: the HTTP transport
captures Request Engine's real handoff, and the callback is signed with an
independent re-implementation of the documented v1 contract (hashlib/hmac),
never with the production signing helpers. Oracles read authoritative rows.
"""

import hashlib
import hmac
import json
import urllib.request
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient

from request_engine.bootstrap.communication_providers import (
    PROVIDER_CALLBACK_CONNECTIONS,
    build_communication_provider_event_handlers,
)
from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.worker.provider_event_router import ProviderEventRouter
from request_engine.modules.communications.adapters.transport.webhook_delivery_provider import (
    WebhookDeliveryProvider,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.events.callback_signature import HmacProviderCallbackAuthenticator
from request_engine.platform.events.provider_events import (
    PostgresProviderEventWorker,
    ProviderEventLease,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.worker.runtime import (
    FencedWorkerRuntime,
    WorkerItemState,
    WorkerRuntimeConfig,
)

from . import operational_support as support
from .delivery_resilience_store import dispatch
from .delivery_resilience_world import claim_and_process, worker_stack

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]

MASTER = b"provider-callback-e2e-master-secret-0123456789"
GATEWAY_URL = "https://gateway.example.test/outbound"
WEBHOOK_POLICY = {
    "channels": ["email"],
    "provider_key": "webhook",
    "reconcile_after_seconds": 30,
    "retry_after_seconds": 30,
}


class _NoActors:
    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        raise AuthenticationRequired


class _GatewayResponse:
    status = 202

    def read(self) -> bytes:
        return b'{"provider_message_id": "gw-msg-1"}'


class _GatewayTransport:
    def __init__(self) -> None:
        self.handoffs: list[dict[str, Any]] = []

    def __call__(self, request: urllib.request.Request, *, timeout: float) -> _GatewayResponse:
        del timeout
        assert isinstance(request.data, bytes)
        self.handoffs.append(cast(dict[str, Any], json.loads(request.data)))
        return _GatewayResponse()


def _webhook_task(conn: support.PgConnection, organization_id: UUID) -> UUID:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_id = support.new_contact_point(conn, organization_id, party_id, "callback")
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status
        ) VALUES (%s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, 'pending')
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_id,
            json.dumps(WEBHOOK_POLICY),
            f"callback-e2e:{uuid4().hex}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _signed(
    body: bytes, organization: str, *, master: bytes = MASTER, timestamp: int
) -> dict[str, str]:
    material = f"request-engine.provider-callback.v1\n{organization}\nwebhook\nprimary"
    key = hmac.new(master, material.encode(), hashlib.sha256).digest()
    signed = b"v1\n" + str(timestamp).encode() + b"\n" + body
    return {
        "Content-Type": "application/json",
        "X-Request-Engine-Organization": organization,
        "X-Request-Engine-Timestamp": str(timestamp),
        "X-Request-Engine-Signature": "v1=" + hmac.new(key, signed, hashlib.sha256).hexdigest(),
    }


def _provider_events(conn: support.PgConnection) -> list[tuple[Any, ...]]:
    return conn.execute(
        """
        SELECT organization_id, provider_key, connection_key, provider_event_id,
               payload, status
        FROM request_engine.provider_events
        ORDER BY received_at
        """
    ).fetchall()


def _delivery(conn: support.PgConnection, task_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        """
        SELECT d.status, d.provider_message_id, t.status
        FROM request_engine.communication_deliveries d
        JOIN request_engine.communication_tasks t
          ON t.organization_id = d.organization_id AND t.id = d.communication_task_id
        WHERE d.communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _outcome_runtime(
    worker_factory: SessionFactory, app_factory: SessionFactory
) -> FencedWorkerRuntime[ProviderEventLease]:
    store = PostgresProviderEventWorker(worker_factory)
    return FencedWorkerRuntime(
        store,
        ProviderEventRouter(build_communication_provider_event_handlers(app_factory)),
        rejecter=store.reject,
        config=WorkerRuntimeConfig(max_concurrency=1, claim_batch_size=1),
    )


@pytest.mark.asyncio
async def test_gateway_callback_over_http_finalizes_delivery_once(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
    e2e_worker_session_factory: SessionFactory,
    worker_runtime_credentials: Any,
) -> None:
    org = support.new_org(e2e_admin_conn, "provider-callback")
    task_id = _webhook_task(e2e_admin_conn, org)
    dispatch(e2e_admin_conn, org, task_id)
    gateway = _GatewayTransport()
    provider = WebhookDeliveryProvider(GATEWAY_URL, transport=gateway)
    async with worker_stack(worker_runtime_credentials, {"webhook": provider}) as stack:
        _, _, scheduler, handler = stack
        await claim_and_process(scheduler, handler)

    assert _delivery(e2e_admin_conn, task_id) == ("accepted", "gw-msg-1", "delivering")
    [handoff] = gateway.handoffs
    assert handoff["organization_id"] == str(org)
    assert handoff["dedupe_key"] == f"communication:{task_id}:attempt:1"

    clock = 1_800_000_000
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=_NoActors(),
        appointment_option_signing_key=b"provider-callback-e2e-option-signing-key",
        provider_callback_authenticator=HmacProviderCallbackAuthenticator(
            MASTER, connections=PROVIDER_CALLBACK_CONNECTIONS, clock=lambda: float(clock)
        ),
    )
    body = json.dumps(
        {
            "provider_event_id": f"gw:{handoff['dedupe_key']}:delivered",
            "payload": {
                "dedupe_key": handoff["dedupe_key"],
                "status": "delivered",
                "provider_message_id": "gw-msg-1",
                # Payload naming a tenant is opaque data, never authority.
                "organization_id": str(uuid4()),
            },
        }
    ).encode()
    path = "/v1/provider-events/webhook/primary"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        forged = await client.post(
            path,
            content=body,
            headers=_signed(body, handoff["organization_id"], master=b"f" * 40, timestamp=clock),
        )
        unknown_tenant = await client.post(
            path, content=body, headers=_signed(body, str(uuid4()), timestamp=clock)
        )
        assert (forged.status_code, unknown_tenant.status_code) == (401, 401)
        assert forged.json() == unknown_tenant.json()
        assert _provider_events(e2e_admin_conn) == []

        first = await client.post(
            path, content=body, headers=_signed(body, handoff["organization_id"], timestamp=clock)
        )
        duplicate = await client.post(
            path,
            content=body,
            headers=_signed(body, handoff["organization_id"], timestamp=clock + 5),
        )

    assert (first.status_code, first.json()["replay"]) == (202, False)
    assert (duplicate.status_code, duplicate.json()["replay"]) == (200, True)
    [event] = _provider_events(e2e_admin_conn)
    assert event[:4] == (org, "webhook", "primary", f"gw:{handoff['dedupe_key']}:delivered")
    assert event[5] == "received"
    # Persisted before interpretation: the delivery is untouched until the worker runs.
    assert _delivery(e2e_admin_conn, task_id) == ("accepted", "gw-msg-1", "delivering")

    outcomes = await _outcome_runtime(e2e_worker_session_factory, e2e_session_factory).run_once()

    assert [outcome.state for outcome in outcomes] == [WorkerItemState.COMPLETED]
    assert _delivery(e2e_admin_conn, task_id) == ("delivered", "gw-msg-1", "completed")
    assert [row[5] for row in _provider_events(e2e_admin_conn)] == ["processed"]
    completed_facts = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = 'communication.task_completed.v1'
        """,
        (org,),
    ).fetchone()
    assert completed_facts == (1,)
