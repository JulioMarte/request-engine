"""A freshly provisioned clinic owner can set up and delegate the front desk.

The organization is created through the real platform provisioning HTTP command
(the application selects the initial controller policy; only the platform actor
resolver is supplied by the test). Every tenant call then goes through the native
HTTP application with password sessions. No controller grant is seeded by SQL:
the committed ``tenant-controller-v9`` manifest alone must allow the owner to
create a service queue, see it live, update the business profile and delegate a
bounded front-desk capability set to a receptionist, but nothing beyond the
owner's delegable ceiling.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.api.native_platform_provisioning import (
    install_native_platform_provisioning_http,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.platform_context import PlatformActorContext

from .booking_world_support import build_bookable_world

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]
_SIGNING_KEY = b"tenant-controller-v9-front-desk-signing-key"
_RECEPTIONIST = ["queue.list", "queue.staff_read", "queue.check_in", "queue.call_next"]


def _headers(token: str, organization_id: UUID, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "X-RE-Organization-ID": str(organization_id)}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


async def _login(client: AsyncClient, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions", json={"login_handle": login_handle, "password": password}
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


def _platform_creator(conn: Connection[Any]) -> PlatformActorContext:
    row = conn.execute(
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES ('platform','human',%s) RETURNING id",
        (f"v9-front-desk-provisioner-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    creator = cast(UUID, row[0])
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES (%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (creator, f"proof:{uuid4().hex}"),
    )
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (creator,)
    ).fetchone()
    assert revision is not None
    return PlatformActorContext(
        principal_id=creator,
        authority_revision=int(revision[0]),
        capabilities=frozenset({"organization.provision"}),
    )


def _active_grants(conn: Connection[Any], principal_id: UUID) -> set[tuple[str, bool]]:
    return {
        (str(row[0]), bool(row[1]))
        for row in conn.execute(
            "SELECT capability_key,delegable FROM request_engine.principal_authority_grants "
            "WHERE principal_id=%s AND status='active'",
            (principal_id,),
        ).fetchall()
    }


@pytest.mark.asyncio
async def test_fresh_v9_owner_runs_and_delegates_front_desk_within_ceiling(
    e2e_admin_conn: Connection[Any],
    e2e_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id,kind,issuer_or_environment) "
        "VALUES(%s,'native',%s)",
        (authority_id, f"v9-front-desk-{authority_id}"),
    )
    enrollment = build_native_auth_runtime(e2e_session_factory).service
    owner_handle, owner_password = f"owner-{uuid4().hex}@example.test", "v9 owner password 1"
    desk_handle, desk_password = f"desk-{uuid4().hex}@example.test", "v9 receptionist password"
    owner_identity = await enrollment.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=owner_handle, password=owner_password
    )
    desk_identity = await enrollment.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=desk_handle, password=desk_password
    )
    actor = _platform_creator(e2e_admin_conn)

    class Resolver:
        async def resolve_platform_actor(self, request: Request) -> PlatformActorContext:
            return actor

    platform_app = FastAPI()
    install_native_platform_provisioning_http(
        platform_app,
        session_factory=platform_control_session_factory,
        actor_resolver=Resolver(),
        native_authority_id=authority_id,
    )
    async with AsyncClient(
        transport=ASGITransport(app=platform_app), base_url="http://platform.test"
    ) as platform:
        created = await platform.post(
            "/v1/platform/organizations",
            headers={"Idempotency-Key": f"v9-clinic-{uuid4().hex}"},
            json={
                "organization_key": f"v9-clinic-{uuid4().hex[:12]}",
                "display_name": "Clinica Front Desk",
                "controller_native_identity_id": str(owner_identity.native_identity_id),
                "provenance_reference": "v9-front-desk-proof",
            },
        )
    assert created.status_code == 201, created.text
    organization_id = UUID(created.json()["organization_id"])
    owner_id = UUID(created.json()["controller_principal_id"])
    # Catches: the application still selecting v8 for new organizations.
    assert e2e_admin_conn.execute(
        "SELECT initial_controller_policy_key FROM "
        "request_engine.organization_root_provisioning_facts WHERE organization_id=%s",
        (organization_id,),
    ).fetchone() == ("tenant-controller-v9",)

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        owner = await _login(client, owner_handle, owner_password)
        world = await build_bookable_world(
            client, client, token=owner, organization_id=organization_id
        )

        # Catches: missing queue.configure (no clinic could ever create a walk-in queue).
        queue = await client.post(
            "/v1/queues",
            headers=_headers(owner, organization_id, f"queue-{uuid4().hex}"),
            json={
                "authority_party_id": str(world.organization_party_id),
                "location_id": str(world.location_id),
                "offering_id": str(world.offering_id),
                "queue_key": f"walk-in-{uuid4().hex[:12]}",
                "display_name": "Walk-in desk",
            },
        )
        assert queue.status_code == 201, queue.text
        queue_id = queue.json()["queue_id"]
        # Catches: missing queue.list / queue.staff_read (Today console cannot load).
        listed = await client.get("/v1/queues", headers=_headers(owner, organization_id))
        assert listed.status_code == 200, listed.text
        assert queue_id in listed.text
        live = await client.get(
            f"/v1/queues/{queue_id}/staff", headers=_headers(owner, organization_id)
        )
        assert live.status_code == 200, live.text
        # Catches: missing organization.manage_profile (timezone/currency/locale frozen).
        profile = await client.patch(
            "/v1/operations/organization/profile",
            headers=_headers(owner, organization_id, f"profile-{uuid4().hex}"),
            json={
                "authority_party_id": str(world.organization_party_id),
                "legal_name": "Clinica Front Desk SRL",
                "default_timezone": "America/Santo_Domingo",
                "default_locale": "es-DO",
                "default_currency": "DOP",
                "operational_status": "active",
            },
        )
        assert profile.status_code == 200, profile.text

        invited = await client.post(
            "/v1/staff/members/native",
            headers=_headers(owner, organization_id, f"invite-{uuid4().hex}"),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(desk_identity.native_identity_id),
                "provenance_reference": "v9-front-desk-receptionist",
            },
        )
        assert invited.status_code == 201, invited.text
        membership_id = invited.json()["membership_id"]
        desk_id = UUID(invited.json()["principal_id"])
        activated = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_headers(owner, organization_id, f"activate-{uuid4().hex}"),
            json={"expected_revision": 1, "target_status": "active", "provenance_reference": "v9"},
        )
        assert activated.status_code == 200, activated.text

        async def replace(capabilities: list[str]) -> Any:
            member = await client.get(
                f"/v1/staff/members/{membership_id}", headers=_headers(owner, organization_id)
            )
            assert member.status_code == 200, member.text
            return await client.put(
                f"/v1/staff/members/{membership_id}/authority",
                headers=_headers(owner, organization_id, f"authority-{uuid4().hex}"),
                json={
                    "expected_authority_revision": member.json()["authority_revision"],
                    "desired_capabilities": capabilities,
                    "provenance_reference": "v9-front-desk-delegation",
                },
            )

        # Catches: v9 front-desk grants recorded as non-delegable.
        delegated = await replace(_RECEPTIONIST)
        assert delegated.status_code == 200, delegated.text
        assert _active_grants(e2e_admin_conn, desk_id) == {(key, False) for key in _RECEPTIONIST}
        # Catches: v9 silently including queue.join or a widened ceiling check.
        beyond = await replace([*_RECEPTIONIST, "queue.join"])
        assert beyond.status_code == 403, beyond.text
        assert _active_grants(e2e_admin_conn, desk_id) == {(key, False) for key in _RECEPTIONIST}

        desk = await _login(client, desk_handle, desk_password)
        desk_live = await client.get(
            f"/v1/queues/{queue_id}/staff", headers=_headers(desk, organization_id)
        )
        assert desk_live.status_code == 200, desk_live.text
        # The receptionist holds only what was delegated: no queue configuration.
        desk_create = await client.post(
            "/v1/queues",
            headers=_headers(desk, organization_id, f"desk-queue-{uuid4().hex}"),
            json={
                "authority_party_id": str(world.organization_party_id),
                "location_id": str(world.location_id),
                "offering_id": str(world.offering_id),
                "queue_key": f"desk-{uuid4().hex[:12]}",
                "display_name": "Not allowed",
            },
        )
        assert desk_create.status_code == 403, desk_create.text
    assert ("queue.configure", True) in _active_grants(e2e_admin_conn, owner_id)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_queues WHERE organization_id=%s",
        (organization_id,),
    ).fetchone() == (1,)
