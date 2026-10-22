"""Receptionist journey through the operator console against the real runtime API.

Browser-shaped requests hit the real console ASGI app (sessions, CSRF, origin
check, shared executor). The console forwards them to the real tenant runtime
HTTP app backed by PostgreSQL 18 with the least-privilege app role. Only the
sign-in exchange is a fixture: the control plane returns the sandbox bearer that
the e2e ``SandboxResolver`` maps to an ActorContext, as every e2e journey does.

Oracle: the reservation/queue rows read with the admin connection and the
owner day-board read, never values computed by the console itself.
"""

import html
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.platform.db.session import SessionFactory

from .front_desk_recall_support import front_desk_actor
from .operational_support import PgConnection
from .tenant_sandbox import (
    OVERRIDE_CAPABILITIES,
    TenantSandbox,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_RECEPTION_CAPABILITIES = frozenset(
    {"parties.register", "parties.lookup", "appointments.record_arrival_estimate"}
)
_LIMITED_TOKEN = "token-console-no-subject-override"
_SANDBOX_DAY = "2030-01-07"


class _RuntimePort:
    """Console runtime port over the real tenant runtime ASGI app."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        setup_bearer: str | None = None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse:
        del setup_bearer
        headers = {"accept": "application/json", **(extra_headers or {})}
        if bearer is not None:
            headers["authorization"] = f"Bearer {bearer}"
        response = await self._client.request(
            method, path, json=json_body, params=params, headers=headers
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        return ControlResponse(
            response.status_code, payload, {k.lower(): v for k, v in response.headers.items()}
        )

    async def openapi(self) -> dict[str, Any]:
        response = await self._client.get("/openapi.json")
        response.raise_for_status()
        return cast(dict[str, Any], response.json())

    async def aclose(self) -> None:
        pass


class _SignInFixture:
    """Control plane stand-in for the sign-in exchange only."""

    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    async def request(self, method: str, path: str, **kwargs: Any) -> ControlResponse:
        if method == "POST" and path == "/auth/native/sessions":
            handle = cast(dict[str, str], kwargs.get("json_body") or {}).get("login_handle", "")
            return ControlResponse(200, {"access_token": self._tokens[handle]}, {})
        return ControlResponse(404, {"error": {"code": "not_found"}}, {})

    async def openapi(self) -> dict[str, Any]:
        return {"paths": {}}

    async def aclose(self) -> None:
        pass


@asynccontextmanager
async def _console(
    tmp_path: Path, session_factory: SessionFactory, sandbox: TenantSandbox
) -> AsyncGenerator[tuple[httpx.AsyncClient, httpx.AsyncClient, httpx.AsyncClient]]:
    reception = replace(
        front_desk_actor(sandbox),
        capabilities=front_desk_actor(sandbox).capabilities | _RECEPTION_CAPABILITIES,
    )
    limited = replace(reception, capabilities=reception.capabilities - OVERRIDE_CAPABILITIES)
    actors = {sandbox.token: reception, _LIMITED_TOKEN: limited}
    async with client_with_actors(session_factory, actors) as runtime:
        app = create_admin_console_app(
            AdminConsoleSettings(
                session_store_directory=tmp_path / "sessions",
                control_api_base_url="http://control",
                runtime_api_base_url="http://runtime",
                session_secret=SecretStr("e2e-console-session-secret-with-32-plus-chars"),
                cookie_secure=False,
            ),
            client=_SignInFixture({"front": sandbox.token, "limited": _LIMITED_TOKEN}),
            runtime_client=_RuntimePort(runtime),
        )
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(
                transport=transport, base_url="http://console", headers={"Origin": "http://console"}
            ) as front,
            httpx.AsyncClient(
                transport=transport, base_url="http://console", headers={"Origin": "http://console"}
            ) as limited_client,
        ):
            for client, handle in ((front, "front"), (limited_client, "limited")):
                signed = await client.post(
                    "/login", data={"login_handle": handle, "password": "fixture"}
                )
                assert signed.status_code == 303, signed.text
            yield front, limited_client, runtime


def _csrf(text: str) -> str:
    match = re.search(r'data-csrf="([^"]+)"', text)
    assert match is not None
    return match.group(1)


def _reservations(conn: PgConnection, party_id: UUID) -> list[tuple[UUID, str]]:
    rows = conn.execute(
        "SELECT id, status FROM request_engine.reservations WHERE subject_party_id = %s",
        (party_id,),
    ).fetchall()
    return [(cast(UUID, row[0]), cast(str, row[1])) for row in rows]


@pytest.mark.asyncio
async def test_receptionist_registers_books_and_checks_in_through_the_console(
    tmp_path: Path,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    sandbox = seed_tenant_sandbox(e2e_admin_conn, "console-front-desk")
    org = sandbox.organization_id
    async with _console(tmp_path, e2e_session_factory, sandbox) as (front, limited, runtime):
        visit = await front.get(f"/tenants/{org}/today/visit")
        assert visit.status_code == 200, visit.text
        registered = await front.post(
            f"/tenants/{org}/today/visit/register",
            data={
                "csrf_token": _csrf(visit.text),
                "_intent_id": "console-register-0001",
                "display_name": "Altagracia Console Paciente",
                "phone": "8095550123",
            },
        )
        assert registered.status_code == 303, registered.text
        location = registered.headers["location"]
        match = re.fullmatch(rf"/tenants/{org}/today/visit/([0-9a-f-]+)\?done=registered", location)
        assert match is not None, location
        party_id = UUID(match.group(1))
        party = e2e_admin_conn.execute(
            "SELECT display_name, organization_id FROM request_engine.parties WHERE id = %s",
            (party_id,),
        ).fetchone()
        assert party == ("Altagracia Console Paciente", org)

        slots_page = await front.get(
            f"/tenants/{org}/today/visit/{party_id}",
            params={"offering_version_id": str(sandbox.offering_version_id), "day": _SANDBOX_DAY},
        )
        assert slots_page.status_code == 200, slots_page.text
        options = re.findall(r'name="option_id" value="([^"]+)"', slots_page.text)
        assert options, slots_page.text
        option_id = html.unescape(options[0])
        book_form = {
            "csrf_token": _csrf(slots_page.text),
            "_intent_id": "console-book-intent-0001",
            "option_id": option_id,
        }

        # Without the owner's subject-override capability (and no Party scope
        # for this newly registered customer) the owner refuses the booking.
        limited_page = await limited.get(f"/tenants/{org}/today/visit")
        denied = await limited.post(
            f"/tenants/{org}/today/visit/{party_id}/book",
            data={**book_form, "csrf_token": _csrf(limited_page.text)},
        )
        assert denied.status_code == 403, denied.text
        assert _reservations(e2e_admin_conn, party_id) == []

        booked = await front.post(f"/tenants/{org}/today/visit/{party_id}/book", data=book_form)
        assert booked.status_code == 303, booked.text
        assert booked.headers["location"] == f"/tenants/{org}/today?done=booked"
        # The unchanged intent replays the owner's idempotent result.
        replay = await front.post(f"/tenants/{org}/today/visit/{party_id}/book", data=book_form)
        assert replay.status_code == 303, replay.text
        reservations = _reservations(e2e_admin_conn, party_id)
        assert len(reservations) == 1 and reservations[0][1] == "confirmed"
        reservation_id = reservations[0][0]

        board = await runtime.get(
            "/v1/appointments/day-board",
            params={
                "window_start": f"{_SANDBOX_DAY}T00:00:00+00:00",
                "window_end": "2030-01-08T00:00:00+00:00",
            },
            headers=auth(sandbox),
        )
        assert board.status_code == 200, board.text
        rows = [row for row in board.json() if row["reservation_id"] == str(reservation_id)]
        assert len(rows) == 1
        assert rows[0]["subject_display_name"] == "Altagracia Console Paciente"
        assert rows[0]["subject_party_id"] == str(party_id)
        revision = int(rows[0]["revision"])

        today = await front.get(f"/tenants/{org}/today")
        csrf = _csrf(today.text)
        stale = await front.post(
            f"/tenants/{org}/today/appointments/{reservation_id}/cancel",
            data={
                "csrf_token": csrf,
                "_intent_id": "console-stale-cancel-01",
                "expected_revision": str(revision + 7),
            },
        )
        assert stale.status_code == 409, stale.text
        assert "Otra persona cambió esta cita" in stale.text
        assert _reservations(e2e_admin_conn, party_id) == [(reservation_id, "confirmed")]

        checked_in = await front.post(
            f"/tenants/{org}/today/appointments/{reservation_id}/check-in",
            data={
                "csrf_token": csrf,
                "_intent_id": "console-check-in-00001",
                "queue_id": str(sandbox.queue_id),
                "subject_party_id": str(party_id),
            },
        )
        assert checked_in.status_code == 303, checked_in.text
        assert checked_in.headers["location"] == f"/tenants/{org}/today?done=checked_in"
    entries = e2e_admin_conn.execute(
        "SELECT service_queue_id, subject_party_id FROM request_engine.queue_entries "
        "WHERE reservation_id = %s",
        (reservation_id,),
    ).fetchall()
    assert entries == [(sandbox.queue_id, party_id)]
