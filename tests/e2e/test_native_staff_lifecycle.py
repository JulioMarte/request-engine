from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"native-staff-e2e-appointment-signing-key-v1"


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_native_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s)
        RETURNING id
        """,
        (f"native-staff-e2e-{uuid4().hex}",),
    )


def _provision_tenant_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s)
        RETURNING id
        """,
        (f"native-staff-platform-{uuid4().hex}",),
    )
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (
            %s, 'platform', 'platform', 'organization.provision', false,
            'trust_bootstrap', %s
        )
        """,
        (provisioner_id, f"native-staff-root:{uuid4().hex}"),
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (provisioner_id,),
    ).fetchone()
    assert revision_row is not None

    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(int(revision_row[0])),),
    )
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"native-staff-{organization_id.hex}",
                "Native Staff E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"native-staff-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _tenant_headers(
    *,
    token: str,
    organization_id: UUID,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


@pytest.mark.asyncio
async def test_native_staff_lifecycle_is_re_owned_and_revocation_is_immediate(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "root-e2e-password-1"
    staff_password = "staff-e2e-password-2"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-{uuid4().hex}@example.test",
        password=root_password,
    )
    staff_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"staff-{uuid4().hex}@example.test",
        password=staff_password,
    )
    third_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"third-{uuid4().hex}@example.test",
        password="third-e2e-password-3",
    )
    fourth_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"fourth-{uuid4().hex}@example.test",
        password="fourth-e2e-password-4",
    )
    organization_id, _root_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, foreign_controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=third_identity.native_identity_id,
    )
    foreign_membership_id = _uuid_row(
        e2e_admin_conn,
        "SELECT id FROM request_engine.staff_memberships "
        "WHERE organization_id = %s AND principal_id = %s",
        (foreign_organization_id, foreign_controller_id),
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root_token = await _login(
            client,
            login_handle=root_identity.login_handle,
            password=root_password,
        )
        invite_key = f"staff-invite-{uuid4().hex}"
        invite_body = {
            "identity_authority_id": str(authority_id),
            "native_identity_id": str(staff_identity.native_identity_id),
            "provenance_reference": "native-staff-e2e-invite",
        }
        root_invite_headers = _tenant_headers(
            token=root_token,
            organization_id=organization_id,
            idempotency_key=invite_key,
        )
        invited = await client.post(
            "/v1/staff/members/native",
            headers=root_invite_headers,
            json=invite_body,
        )
        replay = await client.post(
            "/v1/staff/members/native",
            headers=root_invite_headers,
            json=invite_body,
        )
        assert invited.status_code == 201, invited.text
        assert replay.status_code == 201, replay.text
        assert replay.json() == invited.json()
        membership_id = UUID(invited.json()["membership_id"])
        staff_principal_id = UUID(invited.json()["principal_id"])

        inspection_headers = _tenant_headers(token=root_token, organization_id=organization_id)
        detail = await client.get(f"/v1/staff/members/{membership_id}", headers=inspection_headers)
        assert detail.status_code == 200, detail.text
        assert detail.headers["cache-control"] == "no-store"
        assert detail.json()["status"] == "invited"
        assert detail.json()["membership_revision"] == 1
        assert detail.json()["standing_grants"] == []
        page = await client.get(
            "/v1/staff/members", headers=inspection_headers, params={"limit": 1}
        )
        assert page.status_code == 200, page.text
        assert len(page.json()["items"]) == 1
        second_page = await client.get(
            "/v1/staff/members",
            headers=inspection_headers,
            params={"after": page.json()["next_cursor"], "limit": 1},
        )
        assert second_page.status_code == 200, second_page.text
        assert len(second_page.json()["items"]) == 1
        assert (
            page.json()["items"][0]["membership_id"]
            != (second_page.json()["items"][0]["membership_id"])
        )
        assert {
            item["principal_id"] for item in page.json()["items"] + second_page.json()["items"]
        } == {str(_root_principal_id), str(staff_principal_id)}
        absent = await client.get(f"/v1/staff/members/{uuid4()}", headers=inspection_headers)
        foreign = await client.get(
            f"/v1/staff/members/{foreign_membership_id}", headers=inspection_headers
        )
        assert absent.status_code == foreign.status_code == 404
        assert absent.json() == foreign.json()
        invalid_filter = await client.get(
            "/v1/staff/members", headers=inspection_headers, params={"principal_id": str(uuid4())}
        )
        assert invalid_filter.status_code == 422

        activated = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "native-staff-e2e-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["membership_revision"] == 2

        current_member = await client.get(
            f"/v1/staff/members/{membership_id}", headers=inspection_headers
        )
        assert current_member.status_code == 200, current_member.text
        replaced = await client.put(
            f"/v1/staff/members/{membership_id}/authority",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": current_member.json()["authority_revision"],
                "desired_capabilities": ["staff.invite"],
                "provenance_reference": "native-staff-e2e-authority",
            },
        )
        assert replaced.status_code == 200, replaced.text

        staff_token = await _login(
            client,
            login_handle=staff_identity.login_handle,
            password=staff_password,
        )
        unauthorized_read = await client.get(
            "/v1/staff/members",
            headers=_tenant_headers(token=staff_token, organization_id=organization_id),
        )
        assert unauthorized_read.status_code == 403, unauthorized_read.text
        delegated_invite = await client.post(
            "/v1/staff/members/native",
            headers=_tenant_headers(
                token=staff_token,
                organization_id=organization_id,
                idempotency_key=f"delegated-invite-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(third_identity.native_identity_id),
                "provenance_reference": "native-staff-e2e-delegated-invite",
            },
        )
        assert delegated_invite.status_code == 201, delegated_invite.text

        suspended = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-suspend-{uuid4().hex}",
            ),
            json={
                "expected_revision": 2,
                "target_status": "suspended",
                "provenance_reference": "native-staff-e2e-suspend",
            },
        )
        assert suspended.status_code == 200, suspended.text
        assert suspended.json()["membership_revision"] == 3

        after_suspend = await client.post(
            "/v1/staff/members/native",
            headers=_tenant_headers(
                token=staff_token,
                organization_id=organization_id,
                idempotency_key=f"post-suspend-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(fourth_identity.native_identity_id),
                "provenance_reference": "native-staff-e2e-post-suspend",
            },
        )
        assert after_suspend.status_code == 401
        assert after_suspend.json()["error"]["code"] == "credential_invalid"

        suspended_view = await client.get(
            f"/v1/staff/members/{membership_id}", headers=inspection_headers
        )
        assert suspended_view.json()["status"] == "suspended"
        assert suspended_view.json()["principal_active"] is False
        reactivated = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-reactivate-{uuid4().hex}",
            ),
            json={
                "expected_revision": suspended_view.json()["membership_revision"],
                "target_status": "active",
                "provenance_reference": "native-staff-e2e-reactivate",
            },
        )
        assert reactivated.status_code == 200, reactivated.text
        assert reactivated.json()["membership_revision"] == 4
        stale_session = await client.delete(
            "/auth/native/sessions/current", headers={"Authorization": f"Bearer {staff_token}"}
        )
        assert stale_session.status_code == 401, stale_session.text
        fresh_staff_token = await _login(
            client, login_handle=staff_identity.login_handle, password=staff_password
        )
        current_view = await client.get(
            f"/v1/staff/members/{membership_id}", headers=inspection_headers
        )
        assert current_view.json()["status"] == "active"
        assert current_view.json()["principal_active"] is True
        revoked_member = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-revoke-{uuid4().hex}",
            ),
            json={
                "expected_revision": current_view.json()["membership_revision"],
                "target_status": "revoked",
                "provenance_reference": "native-staff-e2e-revoke",
            },
        )
        assert revoked_member.status_code == 200, revoked_member.text
        assert revoked_member.json()["membership_revision"] == 5
        rejected_session = await client.delete(
            "/auth/native/sessions/current",
            headers={"Authorization": f"Bearer {fresh_staff_token}"},
        )
        assert rejected_session.status_code == 401, rejected_session.text

        # A pending invitation can be revoked without ever activating its Principal.
        pending = await client.post(
            "/v1/staff/members/native",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"staff-pending-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(fourth_identity.native_identity_id),
                "provenance_reference": "native-staff-e2e-pending",
            },
        )
        assert pending.status_code == 201, pending.text
        pending_id = pending.json()["membership_id"]
        for member_id, expected_revision in ((pending_id, 1), (str(membership_id), 5)):
            if member_id == pending_id:
                cancelled = await client.put(
                    f"/v1/staff/members/{member_id}/status",
                    headers=_tenant_headers(
                        token=root_token,
                        organization_id=organization_id,
                        idempotency_key=f"staff-cancel-invitation-{uuid4().hex}",
                    ),
                    json={
                        "expected_revision": expected_revision,
                        "target_status": "revoked",
                        "provenance_reference": "native-staff-e2e-cancel-invitation",
                    },
                )
                assert cancelled.status_code == 200, cancelled.text
            revoked_view = await client.get(
                f"/v1/staff/members/{member_id}", headers=inspection_headers
            )
            assert revoked_view.json()["status"] == "revoked"
            assert revoked_view.json()["principal_active"] is False
            resurrection = await client.put(
                f"/v1/staff/members/{member_id}/status",
                headers=_tenant_headers(
                    token=root_token,
                    organization_id=organization_id,
                    idempotency_key=f"staff-resurrect-{uuid4().hex}",
                ),
                json={
                    "expected_revision": revoked_view.json()["membership_revision"],
                    "target_status": "active",
                    "provenance_reference": "native-staff-e2e-resurrection",
                },
            )
            assert resurrection.status_code == 409, resurrection.text
            after_rejection = await client.get(
                f"/v1/staff/members/{member_id}", headers=inspection_headers
            )
            assert after_rejection.json() == revoked_view.json()
