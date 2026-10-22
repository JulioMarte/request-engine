"""Shared helpers for change-feed E2E proofs over a real uvicorn server (ADR 0020)."""

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import uvicorn
from fastapi import FastAPI

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.changes.feed import ChangeFeed, ChangeFeedSettings
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .f3_acceptance_assertions import acceptance_actor
from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, TenantSandbox, auth

SIGNING_KEY = b"request-engine-e2e-change-feed-key"
STREAM = "/v1/changes/stream"
DATA_FIELDS = {"topic", "kind", "resource_type", "resource_id", "scope", "occurred_at"}
PHONE = "+18095550147"


def feed_actor(sandbox: TenantSandbox) -> ActorContext:
    base = acceptance_actor(sandbox)
    return ActorContext(
        base.organization_id,
        base.principal_id,
        base.capabilities | {"appointments.day_board", "queue.staff_read"},
    )


@asynccontextmanager
async def serve(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:  # noqa: ASYNC110 - uvicorn exposes only a flag
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=httpx.Timeout(20.0)
        ) as client:
            yield client
    finally:
        server.should_exit = True
        await task
        sock.close()


class Sse:
    def __init__(self, response: httpx.Response) -> None:
        self._lines = response.aiter_lines()
        self.raw: list[str] = []

    async def block(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        async with asyncio.timeout(15):
            while True:
                line = await anext(self._lines)
                self.raw.append(line)
                if line == "":
                    if fields:
                        return fields
                    continue
                key, _, value = line.partition(":")
                fields[key] = value.removeprefix(" ")

    async def event(self) -> dict[str, str]:
        while True:
            fields = await self.block()
            if fields.get("event") != "heartbeat":
                return fields


def event_data(fields: dict[str, str]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(fields["data"]))


async def book(client: httpx.AsyncClient, sandbox: TenantSandbox) -> dict[str, Any]:
    slots = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers=auth(sandbox),
    )
    assert slots.status_code == 200, slots.text
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": slots.json()[0]["option_id"], "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"feed-book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    return cast(dict[str, Any], booked.json())


async def check_in(
    client: httpx.AsyncClient, sandbox: TenantSandbox, reservation_id: str
) -> dict[str, Any]:
    checked_in = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id), "reservation_id": reservation_id},
        headers=auth(sandbox, idempotency_key=f"feed-check-in-{uuid4().hex}"),
    )
    assert checked_in.status_code == 201, checked_in.text
    return cast(dict[str, Any], checked_in.json())


def change_feed(app: FastAPI) -> ChangeFeed:
    return cast(ChangeFeed, app.state.change_feed)


async def until(predicate: Any) -> None:
    async with asyncio.timeout(10):
        while not predicate():  # noqa: ASYNC110 - bounded poll of server-side state
            await asyncio.sleep(0.02)


def feed_app(
    session_factory: SessionFactory,
    actors: dict[str, ActorContext],
    settings: ChangeFeedSettings | None = None,
) -> FastAPI:
    return create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(actors),
        appointment_option_signing_key=SIGNING_KEY,
        change_feed_settings=settings or ChangeFeedSettings(),
    )


def seed_phone(conn: PgConnection, sandbox: TenantSandbox) -> str:
    conn.execute(
        "INSERT INTO request_engine.party_contact_points "
        "(organization_id, party_id, channel, normalized_value, source_kind) "
        "VALUES (%s, %s, 'phone', %s, 'operator')",
        (sandbox.organization_id, sandbox.party_id, PHONE),
    )
    row = conn.execute(
        "SELECT display_name FROM request_engine.parties WHERE id = %s", (sandbox.party_id,)
    ).fetchone()
    assert row is not None
    return cast(str, row[0])
