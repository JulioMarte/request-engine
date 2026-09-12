"""E2E: a tenant INTEGRATION Principal is provisioned, bounded, and revoked.

The tenant controller provisions an external B2B integration through the real
``/v1/integrations`` surface, assigns standing authority strictly within its own
delegable operational ceiling, and activates the integration. The integration
then authenticates with its one-time workload bearer, registers a customer
Party, and books an appointment FOR that Party over the real two-step
slot/book API. Suspend and revoke must immediately kill the integration's
authorization, and revocation must destroy the workload credential so no stale
bearer can resurrect access. No agent policy is ever provisioned: the agent
policy stack applies only to AGENT Principals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from .booking_world_support import book_appointment, build_bookable_world, find_slots
from .native_provisioning_support import (
    PgConnection,
    grant_controller_delegable_operational_authority,
    login,
    principal_revision,
    provision_tenant_root,
    tenant_headers,
    uuid_row,
    workload_authority,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"native-integration-e2e-appointment-signing-key-v1"

_INTEGRATION_CAPABILITIES = (
    "parties.register",
    "parties.lookup",
    "appointments.find_slots",
    "appointments.book",
    "appointments.subject_override",
)
_CONTROLLER_OPERATIONAL_CAPABILITIES = (
    "organization.bootstrap",
    "catalog.manage",
    "booking.manage_supply",
    *_INTEGRATION_CAPABILITIES,
)
_INTEGRATION_CONTROL_CAPABILITIES = (
    "integration.read",
    "integration.provision",
    "integration.manage_authority",
    "integration.suspend",
)


def _grant_integration_control(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_principal_id: UUID,
) -> None:
    for capability_key in _INTEGRATION_CONTROL_CAPABILITIES:
        conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                %s, %s, 'tenant', 'tenant_control', %s, true, %s,
                'authority_management', %s
            )
            """,
            (
                organization_id,
                controller_principal_id,
                capability_key,
                controller_principal_id,
                f"native-integration-control:{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
async def test_integration_is_provisioned_books_for_customers_and_revocation_destroys_access(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = uuid_row(
        e2e_admin_conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-integration-e2e-{uuid4().hex}",),
    )
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "root-integration-e2e-password-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-integration-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, controller_principal_id = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    workload_authority_id = workload_authority(e2e_admin_conn)
    _grant_integration_control(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )
    for capability in _CONTROLLER_OPERATIONAL_CAPABILITIES:
        grant_controller_delegable_operational_authority(
            e2e_admin_conn,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            capability_key=capability,
        )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        controller_token = await login(
            client,
            login_handle=root_identity.login_handle,
            password=root_password,
        )

        provision_key = f"integration-provision-{uuid4().hex}"
        provision_body = {
            "identity_authority_id": str(workload_authority_id),
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "native-integration-e2e-provision",
        }
        provisioned = await client.post(
            "/v1/integrations",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=provision_key,
            ),
            json=provision_body,
        )
        assert provisioned.status_code == 201, provisioned.text
        integration_view = provisioned.json()
        integration_principal_id = UUID(integration_view["principal_id"])
        workload_token = integration_view["workload_token"]
        assert workload_token
        assert integration_view["status"] == "pending"
        assert integration_view["authority_revision"] == 1

        replayed = await client.post(
            "/v1/integrations",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=provision_key,
            ),
            json=provision_body,
        )
        assert replayed.status_code == 201, replayed.text
        assert replayed.json()["principal_id"] == str(integration_principal_id)
        assert replayed.json()["workload_token"] is None

        read_headers = tenant_headers(token=controller_token, organization_id=organization_id)
        detail = await client.get(
            f"/v1/integrations/{integration_principal_id}", headers=read_headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["status"] == "pending"
        assert detail.json()["provenance_complete"] is True
        assert "workload_token" not in detail.text
        assert workload_token not in detail.text
        listing = await client.get("/v1/integrations", headers=read_headers)
        assert listing.status_code == 200, listing.text
        assert [item["principal_id"] for item in listing.json()["items"]] == [
            str(integration_principal_id)
        ]

        pending_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert pending_lookup.status_code == 403, pending_lookup.text
        assert pending_lookup.json()["error"]["code"] == "identity_binding_pending"

        assigned = await client.put(
            f"/v1/integrations/{integration_principal_id}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": principal_revision(
                    e2e_admin_conn, integration_principal_id
                ),
                "desired_capabilities": list(_INTEGRATION_CAPABILITIES),
                "provenance_reference": "native-integration-e2e-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text
        assert assigned.json()["authority_revision"] == principal_revision(
            e2e_admin_conn, integration_principal_id
        )

        activated = await client.put(
            f"/v1/integrations/{integration_principal_id}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": principal_revision(e2e_admin_conn, integration_principal_id),
                "target_status": "active",
                "provenance_reference": "native-integration-e2e-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["authority_revision"] == principal_revision(
            e2e_admin_conn, integration_principal_id
        )
        binding_row = e2e_admin_conn.execute(
            """
            SELECT status FROM request_engine.identity_bindings
             WHERE principal_id = %s AND status <> 'revoked'
            """,
            (integration_principal_id,),
        ).fetchone()
        assert binding_row == ("active",)

        current = await client.get(
            f"/v1/integrations/{integration_principal_id}", headers=read_headers
        )
        assert current.status_code == 200, current.text
        rotation_body = {
            "expected_revision": current.json()["authority_revision"],
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "native-integration-e2e-rotation",
        }
        rotation_headers = tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"integration-rotation-{uuid4().hex}",
        )
        rotation_path = f"/v1/integrations/{integration_principal_id}/credentials:rotate"
        rotated = await client.post(rotation_path, headers=rotation_headers, json=rotation_body)
        assert rotated.status_code == 200, rotated.text
        assert rotated.headers["cache-control"] == "no-store"
        replay = await client.post(rotation_path, headers=rotation_headers, json=rotation_body)
        assert replay.status_code == 200, replay.text
        assert replay.json()["credential_id"] == rotated.json()["credential_id"]
        assert replay.json()["workload_token"] is None
        old_credential = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=workload_token, organization_id=organization_id),
            params={"mode": "name", "value": "nobody"},
        )
        assert old_credential.status_code == 401, old_credential.text
        workload_token = rotated.json()["workload_token"]
        assert workload_token
        facts = e2e_admin_conn.execute(
            "SELECT snapshot::text FROM request_engine.integration_governance_facts "
            "WHERE integration_principal_id = %s AND operation = 'credential_rotate'",
            (integration_principal_id,),
        ).fetchall()
        assert len(facts) == 1
        assert workload_token not in facts[0][0]
        assert "token_digest" not in facts[0][0]

        customer_name = f"B2B Customer {uuid4().hex[:8]}"
        active_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert active_lookup.status_code == 200, active_lookup.text
        assert active_lookup.json() == []

        bookable = await build_bookable_world(
            client,
            client,
            token=controller_token,
            organization_id=organization_id,
        )

        registered = await client.post(
            "/v1/parties",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"integration-party-{uuid4().hex}",
            ),
            json={
                "party_kind": "person",
                "display_name": customer_name,
                "contact_points": [
                    {"channel": "whatsapp", "value": f"+1829555{uuid4().int % 10_000:04d}"}
                ],
            },
        )
        assert registered.status_code == 201, registered.text
        customer_party_id = UUID(cast(str, registered.json()["party_id"]))

        looked_up = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": customer_name},
        )
        assert looked_up.status_code == 200, looked_up.text
        assert [entry["party_id"] for entry in looked_up.json()] == [str(customer_party_id)]

        slots = await find_slots(
            client,
            token=workload_token,
            organization_id=organization_id,
            offering_version_id=bookable.offering_version_id,
            location_id=bookable.location_id,
        )
        assert len(slots) == 11
        booked = await book_appointment(
            client,
            token=workload_token,
            organization_id=organization_id,
            option_id=cast(str, slots[0]["option_id"]),
            subject_party_id=customer_party_id,
        )
        reservation = e2e_admin_conn.execute(
            """
            SELECT status, subject_party_id
              FROM request_engine.reservations
             WHERE organization_id = %s AND id = %s
            """,
            (organization_id, booked),
        ).fetchone()
        assert reservation == ("confirmed", customer_party_id)

        booking_audit = e2e_admin_conn.execute(
            """
            SELECT actor_principal_id, correlation_data
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = 'booking.book_appointment'
               AND aggregate_id = %s
            """,
            (organization_id, booked),
        ).fetchone()
        assert booking_audit is not None
        assert booking_audit[0] == integration_principal_id
        assert booking_audit[1]["principal_kind"] == "integration"

        forbidden_agent_provision = await client.post(
            "/v1/agents",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"integration-agent-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(workload_authority_id),
                "display_name": "Rogue Agent",
                "purpose": "self-provisioning attempt",
                "sponsor_principal_id": str(controller_principal_id),
                "operating_mode": "autonomous",
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "provenance_reference": "native-integration-e2e-agent",
            },
        )
        assert forbidden_agent_provision.status_code == 403, forbidden_agent_provision.text
        assert forbidden_agent_provision.json()["error"]["code"] == "capability_required"

        suspended = await client.put(
            f"/v1/integrations/{integration_principal_id}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-suspend-{uuid4().hex}",
            ),
            json={
                "expected_revision": principal_revision(e2e_admin_conn, integration_principal_id),
                "target_status": "suspended",
                "provenance_reference": "native-integration-e2e-suspend",
            },
        )
        assert suspended.status_code == 200, suspended.text

        suspended_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": customer_name},
        )
        assert suspended_lookup.status_code == 403, suspended_lookup.text
        assert suspended_lookup.json()["error"]["code"] == "identity_binding_suspended"

        suspended_authority = await client.put(
            f"/v1/integrations/{integration_principal_id}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-suspended-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": principal_revision(
                    e2e_admin_conn, integration_principal_id
                ),
                "desired_capabilities": list(_INTEGRATION_CAPABILITIES),
                "provenance_reference": "native-integration-e2e-suspended-authority",
            },
        )
        assert suspended_authority.status_code == 409, suspended_authority.text
        assert suspended_authority.json()["error"]["code"] == "integration_governance_conflict"

        reactivated = await client.put(
            f"/v1/integrations/{integration_principal_id}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-reactivate-{uuid4().hex}",
            ),
            json={
                "expected_revision": principal_revision(e2e_admin_conn, integration_principal_id),
                "target_status": "active",
                "provenance_reference": "native-integration-e2e-reactivate",
            },
        )
        assert reactivated.status_code == 200, reactivated.text
        reactivated_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": customer_name},
        )
        assert reactivated_lookup.status_code == 200, reactivated_lookup.text

        revoked = await client.put(
            f"/v1/integrations/{integration_principal_id}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-revoke-{uuid4().hex}",
            ),
            json={
                "expected_revision": principal_revision(e2e_admin_conn, integration_principal_id),
                "target_status": "revoked",
                "provenance_reference": "native-integration-e2e-revoke",
            },
        )
        assert revoked.status_code == 200, revoked.text

        revoked_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": customer_name},
        )
        assert revoked_lookup.status_code == 401, revoked_lookup.text
        assert revoked_lookup.json()["error"]["code"] == "credential_invalid"

        credential_row = e2e_admin_conn.execute(
            """
            SELECT status FROM request_engine.workload_credentials
             WHERE workload_identity_id = %s
            """,
            (UUID(integration_view["workload_identity_id"]),),
        ).fetchall()
        assert all(row[0] == "revoked" for row in credential_row)
        assert e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.identity_bindings
             WHERE principal_id = %s AND status <> 'revoked'
            """,
            (integration_principal_id,),
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_integration_authority_is_rejected_above_controller_ceiling(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = uuid_row(
        e2e_admin_conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-integration-ceiling-{uuid4().hex}",),
    )
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "root-integration-ceiling-password-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-integration-ceiling-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, controller_principal_id = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    workload_authority_id = workload_authority(e2e_admin_conn)
    _grant_integration_control(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )
    grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="parties.lookup",
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        controller_token = await login(
            client,
            login_handle=root_identity.login_handle,
            password=root_password,
        )
        provisioned = await client.post(
            "/v1/integrations",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-provision-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(workload_authority_id),
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "provenance_reference": "native-integration-ceiling-provision",
            },
        )
        assert provisioned.status_code == 201, provisioned.text
        integration_principal_id = UUID(provisioned.json()["principal_id"])

        above_ceiling = await client.put(
            f"/v1/integrations/{integration_principal_id}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"integration-ceiling-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": principal_revision(
                    e2e_admin_conn, integration_principal_id
                ),
                "desired_capabilities": ["appointments.book"],
                "provenance_reference": "native-integration-ceiling-authority",
            },
        )
        assert above_ceiling.status_code == 403, above_ceiling.text
        assert above_ceiling.json()["error"]["code"] == "integration_governance_forbidden"

        grants = e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.principal_authority_grants
             WHERE principal_id = %s AND status = 'active'
            """,
            (integration_principal_id,),
        ).fetchone()
        assert grants == (0,)
