"""A brand-new clinic owner sets up their business through the guided console flow.

Browser-shaped requests hit the real console ASGI app (session, CSRF, origin
check). The console forwards them to the real native tenant runtime backed by
PostgreSQL 18 and the least-privilege app role. The owner is a real native
identity that signs in through ``/auth/native/sessions`` of an organization root
provisioned with the current initial controller policy, so every grant and
Party representation the flow relies on is the one a real fresh owner holds.
Only the control-plane sign-in exchange is a fixture: it returns that owner's
real runtime bearer.

Oracles: rows read with the admin connection, the owner readiness read and the
owner slot read made directly against the runtime (never console output).
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from request_engine.entrypoints.http.admin_console.app import create_admin_console_app
from request_engine.entrypoints.http.admin_console.client import ControlResponse
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from .native_provisioning_support import PgConnection, login, principal_revision, uuid_row

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]
_POLICY = "tenant-controller-v8"
_SIGNING_KEY = b"console-clinic-setup-journey-signing-key-32"
_WEEKDAYS = {f"day{day}_{part}": value for day in range(5) for part, value in (
    ("open", "on"), ("start", "08:00"), ("end", "17:00"))}  # fmt: skip


class _RuntimePort:
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
    def __init__(self, token: str) -> None:
        self._token = token

    async def request(self, method: str, path: str, **_: Any) -> ControlResponse:
        if method == "POST" and path == "/auth/native/sessions":
            return ControlResponse(200, {"access_token": self._token}, {})
        return ControlResponse(404, {"error": {"code": "not_found"}}, {})

    async def openapi(self) -> dict[str, Any]:
        return {"paths": {}}

    async def aclose(self) -> None:
        pass


def _provision_fresh_clinic(
    conn: PgConnection, authority_id: UUID, native_identity_id: UUID
) -> tuple[UUID, UUID]:
    provisioner_id = uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"clinic-setup-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner_id, f"clinic-setup-provisioner:{uuid4().hex}"),
    )
    organization_id, party_id = uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)",
        (str(principal_revision(conn, provisioner_id)),),
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute("SELECT request_platform.select_initial_controller_policy(%s)", (_POLICY,))
            conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"clinic-setup-{organization_id.hex}",
                    "Centro Médico Duarte",
                    party_id,
                    uuid4(),
                    authority_id,
                    native_identity_id,
                    f"clinic-setup-root:{uuid4().hex}",
                ),
            )
        finally:
            conn.execute("RESET ROLE")
    for setting in ("authenticated_principal_id", "authority_revision"):
        conn.execute(f"RESET request_engine.{setting}")
    return organization_id, party_id


@asynccontextmanager
async def _owner_console(
    tmp_path: Path, conn: PgConnection, session_factory: SessionFactory
) -> AsyncGenerator[tuple[httpx.AsyncClient, httpx.AsyncClient, str, UUID, UUID]]:
    authority_id = uuid_row(
        conn,
        "INSERT INTO request_engine.identity_authorities(kind,issuer_or_environment) "
        "VALUES ('native',%s) RETURNING id",
        (f"clinic-setup-{uuid4().hex}",),
    )
    handle, password = f"owner-{uuid4().hex}@example.test", f"clinic-owner-{uuid4().hex}"
    identity = await build_native_auth_runtime(session_factory).service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=password
    )
    organization_id, party_id = _provision_fresh_clinic(
        conn, authority_id, identity.native_identity_id
    )
    runtime_app = create_native_app(
        session_factory=session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime_app), base_url="http://runtime"
    ) as runtime:
        token = await login(runtime, login_handle=handle, password=password)
        console = create_admin_console_app(
            AdminConsoleSettings(
                session_store_directory=tmp_path / "sessions",
                control_api_base_url="http://control",
                runtime_api_base_url="http://runtime",
                session_secret=SecretStr("e2e-clinic-setup-session-secret-32-plus-chars"),
                cookie_secure=False,
            ),
            client=_SignInFixture(token),
            runtime_client=_RuntimePort(runtime),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=console),
            base_url="http://console",
            headers={"Origin": "http://console"},
        ) as browser:
            signed = await browser.post("/login", data={"login_handle": "owner", "password": "x"})
            assert signed.status_code == 303, signed.text
            yield browser, runtime, token, organization_id, party_id


def _csrf(text: str) -> str:
    match = re.search(r'data-csrf="([^"]+)"', text)
    assert match is not None
    return match.group(1)


def _count(conn: PgConnection, query: LiteralString, organization_id: UUID) -> int:
    row = conn.execute(query, (organization_id,)).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.asyncio
async def test_fresh_owner_sets_up_a_bookable_clinic_through_the_guided_flow(
    tmp_path: Path,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    async with _owner_console(tmp_path, e2e_admin_conn, e2e_session_factory) as (
        browser,
        runtime,
        token,
        org,
        party_id,
    ):
        root = f"/tenants/{org}/setup"
        start = await browser.get(root)
        assert start.status_code == 200, start.text
        # The business Party is resolved from the owner, never typed or shown.
        assert "authority_party_id" not in start.text
        assert str(party_id) not in start.text
        csrf = _csrf(start.text)

        clinic = await browser.post(
            f"{root}/clinic",
            data={
                "csrf_token": csrf,
                "_intent_id": "clinic-setup-e2e-clinic",
                "legal_name": "Centro Médico Duarte SRL",
                "phone": "809 555 0101",
                "timezone": "America/Santo_Domingo",
                "currency": "DOP",
                "locale": "es-DO",
            },
        )
        if clinic.status_code == 303:
            assert clinic.headers["location"] == f"{root}?step=location&done=clinic"
        else:
            # The v8 owner lacks organization.manage_profile: the owner refuses and
            # the console explains it plainly and offers to skip the optional step.
            assert clinic.status_code == 403, clinic.text
            assert "platform administrator has to upgrade them" in clinic.text
            assert "Skip this step" in clinic.text

        location_form = {
            "csrf_token": csrf,
            "_intent_id": "clinic-setup-e2e-location",
            "display_name": "Sede Gazcue",
            "address_line1": "Av. Independencia 123",
            "locality": "Santo Domingo",
            "administrative_area": "Distrito Nacional",
            "country_code": "DO",
            "phone": "809 555 0102",
            **_WEEKDAYS,
        }
        for _ in range(2):  # the second submission is a browser replay
            saved = await browser.post(f"{root}/location", data=location_form)
            assert saved.status_code == 303, saved.text
            assert saved.headers["location"] == f"{root}?step=services&done=location"
        assert (
            _count(
                e2e_admin_conn,
                "SELECT count(*) FROM request_engine.locations WHERE organization_id=%s",
                org,
            )
            == 1
        )
        hours = e2e_admin_conn.execute(
            "SELECT weekday, local_start::text, local_end::text "
            "FROM request_engine.location_operational_hours WHERE organization_id=%s "
            "ORDER BY weekday",
            (org,),
        ).fetchall()
        assert hours == [(day, "08:00:00", "17:00:00") for day in range(5)]

        service_form = {
            "csrf_token": csrf,
            "_intent_id": "clinic-setup-e2e-service",
            "display_name": "Consulta general",
            "duration_minutes": "30",
            "price": "1500",
            "currency": "DOP",
        }
        for _ in range(2):
            saved = await browser.post(f"{root}/services", data=service_form)
            assert saved.status_code == 303, saved.text
        terms = e2e_admin_conn.execute(
            "SELECT t.amount::text, t.currency "
            "FROM request_engine.offering_version_booking_terms t "
            "JOIN request_engine.offering_versions v ON v.id = t.offering_version_id "
            "JOIN request_engine.offerings o ON o.id = v.offering_id "
            "WHERE o.organization_id=%s AND o.display_name='Consulta general'",
            (org,),
        ).fetchall()
        assert [(float(amount), currency) for amount, currency in terms] == [(1500.0, "DOP")]

        providers = await browser.get(f"{root}?step=providers")
        assert providers.status_code == 200, providers.text
        capability = re.search(r'name="capability_id" value="([0-9a-f-]+)"', providers.text)
        location = re.search(r'<option value="([0-9a-f-]+)"[^>]*>Sede Gazcue', providers.text)
        assert capability is not None and location is not None, providers.text
        provider = await browser.post(
            f"{root}/providers",
            data={
                "csrf_token": csrf,
                "_intent_id": "clinic-setup-e2e-provider",
                "display_name": "Dra. Ana Pérez",
                "kind": "doctor",
                "location_id": location.group(1),
                "capability_id": capability.group(1),
                **{key: "09:00" if value == "08:00" else value for key, value in _WEEKDAYS.items()},
            },
        )
        assert provider.status_code == 303, provider.text
        assert provider.headers["location"] == f"{root}?step=providers&done=provider"

        queue = await browser.post(
            f"{root}/queue",
            data={
                "csrf_token": csrf,
                "_intent_id": "clinic-setup-e2e-queue",
                "display_name": "Walk-ins",
                "location_id": location.group(1),
            },
        )
        if queue.status_code != 303:
            assert queue.status_code == 403, queue.text
            assert "not allowed to create walk-in lines" in queue.text

        finish = await browser.get(f"{root}?step=finish")
        assert finish.status_code == 200, finish.text
        assert "First free times for Consulta general" in finish.text
        assert '<ul class="slot-preview"><li>' in finish.text
        assert 'href="/tenants/' + str(org) + '/today">Open today' in finish.text

        headers = {"Authorization": f"Bearer {token}", "X-RE-Organization-ID": str(org)}
        readiness = await runtime.get("/v1/onboarding/readiness", headers=headers)
        assert readiness.status_code == 200, readiness.text
        assert readiness.json()["locations"]["ready"] is True
        assert readiness.json()["appointments"]["ready"] is True
        version = e2e_admin_conn.execute(
            "SELECT v.id FROM request_engine.offering_versions v "
            "JOIN request_engine.offerings o ON o.id = v.offering_id WHERE o.organization_id=%s",
            (org,),
        ).fetchall()
        assert len(version) == 1
        slots = await runtime.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(version[0][0]),
                "window_start": "2030-01-07T00:00:00-04:00",
                "window_end": "2030-01-08T00:00:00-04:00",
            },
            headers=headers,
        )
        assert slots.status_code == 200, slots.text
        # Monday 2030-01-07: doctor 09:00-17:00 inside clinic hours, 30-minute steps.
        assert len(slots.json()) == 16
        assert slots.json()[0]["start_at"].startswith("2030-01-07T13:00:00")
    for table in ("resources", "offerings", "resource_capabilities"):
        assert (
            _count(
                e2e_admin_conn,
                f"SELECT count(*) FROM request_engine.{table} WHERE organization_id=%s",
                org,
            )
            == 1
        ), table
