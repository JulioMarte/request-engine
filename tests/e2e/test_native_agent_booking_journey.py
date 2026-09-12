"""E2E E: an autonomous clinic agent uses business subjects correctly.

The agent authenticates through its own first-party workload credential,
resolves/registers the patient as a business Party through the real party API,
and books FOR that Party through the real two-step slot/book API. Durable
evidence must show audit actor = Agent A (workload authentication) and business
subject = Party P, with no Principal row for P and fail-closed booking when the
agent loses the ``appointments.subject_override`` operator permission.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory

from .agent_policy_support import grant_agent_policy_authority, provision_agent_policy
from .booking_world_support import BookableWorld, build_bookable_world, find_slots
from .native_provisioning_support import (
    PgConnection,
    bind_platform_identity,
    grant_controller_delegable_operational_authority,
    login,
    principal_revision,
    tenant_headers,
    workload_authority,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"agent-booking-journey-appointment-signing-key-v1"

_CONTROLLER_OPERATIONAL_CAPABILITIES = (
    "organization.bootstrap",
    "parties.register",
    "parties.lookup",
    "appointments.find_slots",
    "appointments.book",
    "appointments.subject_override",
    "catalog.manage",
    "booking.manage_supply",
)
_AGENT_CAPABILITIES = (
    "parties.register",
    "parties.lookup",
    "appointments.find_slots",
    "appointments.book",
    "appointments.subject_override",
)
_RISK_CEILING = "external_commitment"
_MUTATIONS_PER_MINUTE = 20


@dataclass(frozen=True, slots=True)
class AgentBookingWorld:
    organization_id: UUID
    controller_principal_id: UUID
    controller_token: str
    agent_principal_id: UUID
    workload_identity_id: UUID
    credential_id: UUID
    workload_token: str
    bookable: BookableWorld
    client: AsyncClient


def _bootstrap_platform_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID]:
    dsn = (
        f"host={os.environ.get('PGHOST', '127.0.0.1')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')} "
        f"user={os.environ.get('PGUSER', 'request_engine')} "
        f"password={os.environ.get('PGPASSWORD', 'request_engine')}"
    )
    monkeypatch.setenv("REQUEST_ENGINE_BOOTSTRAP_DSN", dsn)
    issue_output = issue_intent(
        ttl_minutes=15,
        provenance=f"agent-booking-journey-{uuid4().hex}",
    )
    bootstrap_lines = dict(
        line.split(": ", 1) for line in issue_output.splitlines() if ": " in line
    )
    native_authority_id = UUID(bootstrap_lines["Native authority"])
    bootstrap_token = bootstrap_lines["ONE-TIME BOOTSTRAP TOKEN"]
    admin_principal_id = establish_root(
        login_handle=f"agent-booking-admin-{uuid4().hex}@example.test",
        raw_token=bootstrap_token,
        password=f"agent-booking-admin-password-{uuid4().hex}",
    )
    return native_authority_id, admin_principal_id


async def _build_agent_booking_world(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> AgentBookingWorld:
    suffix = uuid4().hex
    native_authority_id, admin_principal_id = _bootstrap_platform_admin(monkeypatch)
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    controller_password = f"agent-booking-controller-password-{suffix}"
    provisioner_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=f"agent-booking-provisioner-{suffix}@example.test",
        password=f"agent-booking-provisioner-password-{suffix}",
    )
    controller_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=f"agent-booking-controller-{suffix}@example.test",
        password=controller_password,
    )

    provisioner_principal_id = uuid4()
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(admin_principal_id),),
    )
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(e2e_admin_conn, admin_principal_id)),),
    )
    e2e_admin_conn.execute("SET ROLE request_platform_control")
    try:
        created = e2e_admin_conn.execute(
            "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
            (
                provisioner_principal_id,
                f"native:{provisioner_identity.native_identity_id}",
                f"agent-booking-journey:provisioner-{suffix}",
            ),
        ).fetchone()
        assert created is not None
    finally:
        e2e_admin_conn.execute("RESET ROLE")
    bind_platform_identity(
        e2e_admin_conn,
        principal_id=provisioner_principal_id,
        identity_authority_id=native_authority_id,
        native_identity_id=provisioner_identity.native_identity_id,
    )

    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_principal_id),),
    )
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(e2e_admin_conn, provisioner_principal_id)),),
    )
    e2e_admin_conn.execute("SET ROLE request_platform_control")
    try:
        rooted = e2e_admin_conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"agent-booking-journey-{organization_id.hex}",
                "Agent Booking Journey Tenant",
                organization_party_id,
                controller_principal_id,
                native_authority_id,
                controller_identity.native_identity_id,
                f"agent-booking-journey:tenant-root-{suffix}",
            ),
        ).fetchone()
        assert rooted is not None
    finally:
        e2e_admin_conn.execute("RESET ROLE")

    for capability in _CONTROLLER_OPERATIONAL_CAPABILITIES:
        grant_controller_delegable_operational_authority(
            e2e_admin_conn,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            capability_key=capability,
        )
    grant_agent_policy_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=native_authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    controller_token = await login(
        client,
        login_handle=controller_identity.login_handle,
        password=controller_password,
    )

    bookable = await build_bookable_world(
        client,
        client,
        token=controller_token,
        organization_id=organization_id,
    )

    workload_authority_id = workload_authority(e2e_admin_conn)
    provisioned = await client.post(
        "/v1/agents",
        headers=tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-provision-{uuid4().hex}",
        ),
        json={
            "identity_authority_id": str(workload_authority_id),
            "display_name": "Clinic Scheduling Agent",
            "purpose": "register patients and book their appointments",
            "sponsor_principal_id": str(controller_principal_id),
            "operating_mode": "autonomous",
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": f"agent-booking-journey:provision-{suffix}",
        },
    )
    assert provisioned.status_code == 201, provisioned.text
    agent_view = provisioned.json()
    agent_principal_id = UUID(agent_view["principal_id"])
    workload_identity_id = UUID(agent_view["workload_identity_id"])
    credential_id = UUID(agent_view["credential_id"])
    workload_token = agent_view["workload_token"]
    assert workload_token

    activated = await client.put(
        f"/v1/agents/{agent_principal_id}/status",
        headers=tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-activate-{uuid4().hex}",
        ),
        json={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": f"agent-booking-journey:activate-{suffix}",
        },
    )
    assert activated.status_code == 200, activated.text

    assigned = await client.put(
        f"/v1/agents/{agent_principal_id}/authority",
        headers=tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-authority-{uuid4().hex}",
        ),
        json={
            "expected_authority_revision": principal_revision(e2e_admin_conn, agent_principal_id),
            "desired_capabilities": list(_AGENT_CAPABILITIES),
            "provenance_reference": f"agent-booking-journey:authority-{suffix}",
        },
    )
    assert assigned.status_code == 200, assigned.text

    policy = await provision_agent_policy(
        client,
        controller_headers=tenant_headers(
            token=controller_token,
            organization_id=organization_id,
        ),
        agent_principal_id=agent_principal_id,
        allowed_capabilities=list(_AGENT_CAPABILITIES),
        risk_ceiling=_RISK_CEILING,
        max_mutations_per_minute=_MUTATIONS_PER_MINUTE,
    )
    assert policy["policy_revision"] == 1

    return AgentBookingWorld(
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        controller_token=controller_token,
        agent_principal_id=agent_principal_id,
        workload_identity_id=workload_identity_id,
        credential_id=credential_id,
        workload_token=workload_token,
        bookable=bookable,
        client=client,
    )


async def _register_patient_as_agent(
    world: AgentBookingWorld,
    *,
    patient_name: str,
) -> UUID:
    registered = await world.client.post(
        "/v1/parties",
        headers=tenant_headers(
            token=world.workload_token,
            organization_id=world.organization_id,
            idempotency_key=f"agent-party-{uuid4().hex}",
        ),
        json={
            "party_kind": "person",
            "display_name": patient_name,
            "contact_points": [
                {"channel": "whatsapp", "value": f"+1829555{uuid4().int % 10_000:04d}"}
            ],
        },
    )
    assert registered.status_code == 201, registered.text
    return UUID(registered.json()["party_id"])


async def _agent_lookup_by_name(
    world: AgentBookingWorld,
    *,
    value: str,
) -> list[dict[str, object]]:
    response = await world.client.get(
        "/v1/parties/lookup",
        headers=tenant_headers(
            token=world.workload_token,
            organization_id=world.organization_id,
        ),
        params={"mode": "name", "value": value},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return cast(list[dict[str, object]], body)


def _assert_no_booking_state(e2e_admin_conn: PgConnection, organization_id: UUID) -> None:
    reservations = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.reservations WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert reservations == (0,)
    claims = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.capacity_claims WHERE organization_id = %s",
        (organization_id,),
    ).fetchone()
    assert claims == (0,)


@pytest.mark.asyncio
async def test_autonomous_agent_books_for_party_subject_without_impersonation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _build_agent_booking_world(e2e_admin_conn, e2e_session_factory, monkeypatch)
    try:
        organization_id = world.organization_id
        patient_name = f"Agent Journey Patient {uuid4().hex[:8]}"

        absent = await _agent_lookup_by_name(world, value=patient_name)
        assert absent == []

        patient_party_id = await _register_patient_as_agent(world, patient_name=patient_name)
        resolved = await _agent_lookup_by_name(world, value=patient_name)
        assert [entry["party_id"] for entry in resolved] == [str(patient_party_id)]

        slots = await find_slots(
            world.client,
            token=world.workload_token,
            organization_id=organization_id,
            offering_version_id=world.bookable.offering_version_id,
            location_id=world.bookable.location_id,
        )
        assert len(slots) == 11
        option = slots[0]
        assert option["planned_duration_minutes"] == 30
        assert option["currency"] == "DOP"

        booked = await world.client.post(
            "/v1/appointments",
            headers=tenant_headers(
                token=world.workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-book-{uuid4().hex}",
            ),
            json={
                "option_id": option["option_id"],
                "subject_party_id": str(patient_party_id),
            },
        )
        assert booked.status_code == 201, booked.text
        reservation_id = UUID(booked.json()["id"])

        reservation = e2e_admin_conn.execute(
            """
            SELECT status, subject_party_id, lower(during), upper(during)
              FROM request_engine.reservations
             WHERE organization_id = %s AND id = %s
            """,
            (organization_id, reservation_id),
        ).fetchone()
        assert reservation is not None
        assert reservation[0] == "confirmed"
        assert reservation[1] == patient_party_id
        assert reservation[2] == datetime.fromisoformat(cast(str, option["start_at"]))
        assert reservation[3] == datetime.fromisoformat(cast(str, option["end_at"]))

        claims = e2e_admin_conn.execute(
            """
            SELECT status FROM request_engine.capacity_claims
             WHERE organization_id = %s AND reservation_id = %s AND status = 'active'
            """,
            (organization_id, reservation_id),
        ).fetchall()
        assert claims == [("active",)]

        booking_audit = e2e_admin_conn.execute(
            """
            SELECT actor_principal_id, aggregate_kind, details, correlation_data
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = 'booking.book_appointment'
               AND aggregate_id = %s
            """,
            (organization_id, reservation_id),
        ).fetchone()
        assert booking_audit is not None
        actor_principal_id, aggregate_kind, details, correlation_data = booking_audit
        assert actor_principal_id == world.agent_principal_id
        assert aggregate_kind == "Reservation"
        assert details["subject_party_id"] == str(patient_party_id)
        assert details["subject_authority"]["mode"] == "operator"
        assert details["subject_authority"]["scope_key"] == "appointments.book"
        assert correlation_data["principal_kind"] == "agent"
        assert correlation_data["authentication_method"] == "workload_credential"
        assert correlation_data["credential_id"] == str(world.credential_id)

        party_audit = e2e_admin_conn.execute(
            """
            SELECT actor_principal_id
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = 'parties.register'
               AND aggregate_id = %s
            """,
            (organization_id, patient_party_id),
        ).fetchone()
        assert party_audit == (world.agent_principal_id,)

        subject_principals = e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.principals WHERE id = %s",
            (patient_party_id,),
        ).fetchone()
        assert subject_principals == (0,)

        credential_row = e2e_admin_conn.execute(
            """
            SELECT workload_identity_id, status
              FROM request_engine.workload_credentials
             WHERE id = %s
            """,
            (world.credential_id,),
        ).fetchone()
        assert credential_row == (world.workload_identity_id, "active")

        binding_row = e2e_admin_conn.execute(
            """
            SELECT principal_id, status
              FROM request_engine.identity_bindings
             WHERE organization_id = %s AND subject_id = %s
            """,
            (organization_id, str(world.workload_identity_id)),
        ).fetchone()
        assert binding_row == (world.agent_principal_id, "active")
    finally:
        await world.client.aclose()


@pytest.mark.asyncio
async def test_agent_without_subject_override_permission_fails_closed(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _build_agent_booking_world(e2e_admin_conn, e2e_session_factory, monkeypatch)
    try:
        organization_id = world.organization_id
        patient_party_id = await _register_patient_as_agent(
            world, patient_name=f"Fail Closed Patient {uuid4().hex[:8]}"
        )
        slots = await find_slots(
            world.client,
            token=world.workload_token,
            organization_id=organization_id,
            offering_version_id=world.bookable.offering_version_id,
            location_id=world.bookable.location_id,
        )
        option = slots[0]

        replaced = await provision_agent_policy(
            world.client,
            controller_headers=tenant_headers(
                token=world.controller_token,
                organization_id=organization_id,
            ),
            agent_principal_id=world.agent_principal_id,
            allowed_capabilities=[
                "parties.register",
                "parties.lookup",
                "appointments.find_slots",
                "appointments.book",
            ],
            risk_ceiling=_RISK_CEILING,
            max_mutations_per_minute=_MUTATIONS_PER_MINUTE,
        )
        assert replaced["policy_revision"] == 2

        denied = await world.client.post(
            "/v1/appointments",
            headers=tenant_headers(
                token=world.workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-denied-book-{uuid4().hex}",
            ),
            json={
                "option_id": option["option_id"],
                "subject_party_id": str(patient_party_id),
            },
        )
        assert denied.status_code == 403, denied.text
        error = denied.json()["error"]
        assert error["code"] == "party_authority_required"
        assert error["details"]["party_id"] == str(patient_party_id)
        assert error["details"]["authority_anchor"] == "subject"

        _assert_no_booking_state(e2e_admin_conn, organization_id)
    finally:
        await world.client.aclose()


@pytest.mark.asyncio
async def test_agent_booking_for_unknown_party_is_rejected(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = await _build_agent_booking_world(e2e_admin_conn, e2e_session_factory, monkeypatch)
    try:
        organization_id = world.organization_id
        slots = await find_slots(
            world.client,
            token=world.workload_token,
            organization_id=organization_id,
            offering_version_id=world.bookable.offering_version_id,
            location_id=world.bookable.location_id,
        )
        option = slots[0]
        unknown_party_id = uuid4()

        rejected = await world.client.post(
            "/v1/appointments",
            headers=tenant_headers(
                token=world.workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-unknown-book-{uuid4().hex}",
            ),
            json={
                "option_id": option["option_id"],
                "subject_party_id": str(unknown_party_id),
            },
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["error"]["code"] == "invalid_resource_selection"

        _assert_no_booking_state(e2e_admin_conn, organization_id)
    finally:
        await world.client.aclose()
