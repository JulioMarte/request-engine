from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Request
from psycopg import Connection

from request_engine.bootstrap.http import build_http_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from tests.integration.v3_first_vertical._response_loss import (
    DropFirstMatchingResponseTransport,
)

from .test_slot_offer_recovery import _fixture, _offer_command, _prepare

PgConnection = Connection[Any]


class SlotOfferBearerResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer operator":
            raise AuthenticationRequired
        return self._actor


def _app(session_factory: SessionFactory, organization_id: UUID, principal_id: UUID):
    actor = ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=frozenset(
            {
                "waitlist.accept_offer",
                "waitlist.decline_offer",
                "waitlist.subject_override",
            }
        ),
    )
    return build_http_app(
        session_factory=session_factory,
        actor_resolver=SlotOfferBearerResolver(actor),
        appointment_option_signing_key=b"x" * 64,
    )


async def _issued_offer(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
):
    fixture = _fixture(admin_conn)
    commands, opportunity_id, _, _ = await _prepare(fixture, app_session_factory)
    offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(fixture, opportunity_id, key=f"prepare-offer-{uuid4().hex}"),
    )
    assert offer is not None
    return fixture, offer


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_offer_accept_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, offer = await _issued_offer(admin_conn, app_session_factory)
    app = _app(app_session_factory, fixture.organization_id, fixture.principal_id)
    path = f"/v1/waitlist/offers/{offer.id}/accept"
    key = f"lost-offer-accept-{uuid4().hex}"
    body = {"expected_revision": offer.revision}
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer operator", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, json=body, headers=headers)
        replay = await client.post(path, json=body, headers=headers)

    assert replay.status_code == 200
    reservation_id = UUID(cast(str, replay.json()["reservation"]["id"]))
    state = admin_conn.execute(
        """
        SELECT so.status, h.status, o.status, w.status,
               count(DISTINCT cc.reservation_id)
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id AND h.id = so.capacity_hold_id
        JOIN request_engine.slot_opportunities o
          ON o.organization_id = so.organization_id AND o.id = so.slot_opportunity_id
        JOIN request_engine.waitlist_entries w
          ON w.organization_id = so.organization_id AND w.id = so.waitlist_entry_id
        LEFT JOIN request_engine.capacity_claims cc
          ON cc.organization_id = so.organization_id
         AND cc.hold_id = h.id
         AND cc.reservation_id IS NOT NULL
        WHERE so.organization_id = %s AND so.id = %s
        GROUP BY so.status, h.status, o.status, w.status
        """,
        (fixture.organization_id, offer.id),
    ).fetchone()
    assert state == ("accepted", "consumed", "filled", "fulfilled", 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'waitlist.slot_offer_accepted.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_offer_decline_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture, offer = await _issued_offer(admin_conn, app_session_factory)
    app = _app(app_session_factory, fixture.organization_id, fixture.principal_id)
    path = f"/v1/waitlist/offers/{offer.id}/decline"
    key = f"lost-offer-decline-{uuid4().hex}"
    body = {"expected_revision": offer.revision}
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer operator", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, json=body, headers=headers)
        replay = await client.post(path, json=body, headers=headers)

    assert replay.status_code == 200
    assert replay.json()["status"] == "declined"
    state = admin_conn.execute(
        """
        SELECT so.status, h.status, o.status
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id AND h.id = so.capacity_hold_id
        JOIN request_engine.slot_opportunities o
          ON o.organization_id = so.organization_id AND o.id = so.slot_opportunity_id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone()
    assert state == ("declined", "released", "open")
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'waitlist.slot_offer_declined.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone() == (1,)
