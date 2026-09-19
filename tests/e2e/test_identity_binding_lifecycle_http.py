"""End-to-end HTTP proof for the tenant identity-binding lifecycle.

Protects the current guarantee that ``POST /v1/identity-bindings/{id}:suspend``,
``:reactivate`` and ``:revoke`` require the standing ``identity.bind`` authority,
increment the binding revision exactly once, reject a stale revision, keep revoke
terminal, are tenant-opaque for a foreign or random binding, require an
``Idempotency-Key`` and never expose another tenant's binding.
"""

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
    pytest.mark.adversarial,
]
_SIGNING_KEY = b"native-identity-binding-lifecycle-e2e-key-v1"
_BIND_CAPABILITY = "identity.bind"


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
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"native-binding-lifecycle-{uuid4().hex}",),
    )


def _provision_tenant_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"binding-lifecycle-platform-{uuid4().hex}",),
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
        (provisioner_id, f"binding-lifecycle-root:{uuid4().hex}"),
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
                f"binding-lifecycle-{organization_id.hex}",
                "Identity Binding Lifecycle E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"binding-lifecycle-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, organization_party_id, controller_principal_id


def _binding_id(conn: PgConnection, *, organization_id: UUID, principal_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        SELECT id FROM request_engine.identity_bindings
         WHERE organization_id = %s AND principal_plane = 'tenant' AND principal_id = %s
        """,
        (organization_id, principal_id),
    )


def _set_tenant_actor(conn: PgConnection, *, organization_id: UUID, principal_id: UUID) -> None:
    conn.execute(
        "SELECT set_config('request_engine.organization_id', %s, false)",
        (str(organization_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(principal_id),),
    )
    conn.execute("SET ROLE request_engine_app")


def _invite_activate_staff(
    conn: PgConnection,
    *,
    organization_id: UUID,
    party_id: UUID,
    controller_id: UUID,
    authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    membership_id = uuid4()
    principal_id = uuid4()
    binding_id = uuid4()
    _set_tenant_actor(conn, organization_id=organization_id, principal_id=controller_id)
    try:
        returned = conn.execute(
            """
            SELECT request_engine.invite_native_staff(%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                membership_id,
                principal_id,
                binding_id,
                authority_id,
                native_identity_id,
                party_id,
                f"binding-lifecycle-staff:{uuid4().hex}",
            ),
        ).fetchone()
        assert returned == (binding_id,)
        activated = conn.execute(
            """
            SELECT request_engine.transition_staff_membership(%s, 1, 'active', %s)
            """,
            (membership_id, f"binding-lifecycle-staff:{uuid4().hex}"),
        ).fetchone()
        assert activated == (2,)
    finally:
        conn.execute("RESET ROLE")
    return principal_id, binding_id


def _binding_state(conn: PgConnection, binding_id: UUID) -> tuple[str, int]:
    row = conn.execute(
        "SELECT status, revision FROM request_engine.identity_bindings WHERE id = %s",
        (binding_id,),
    ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1])


def _revoke_control_grant(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID, capability: str
) -> None:
    conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked', revision = revision + 1,
               revoked_at = clock_timestamp(), revoked_by_principal_id = %s
         WHERE organization_id = %s AND principal_id = %s
           AND capability_key = %s AND status = 'active'
        """,
        (principal_id, organization_id, principal_id, capability),
    )


def _restore_control_grant(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID, capability: str
) -> None:
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
        (organization_id, principal_id, capability, principal_id, f"restore:{uuid4().hex}"),
    )


def _tenant_headers(*, token: str, organization_id: UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


@pytest.mark.asyncio
async def test_identity_binding_lifecycle_over_http(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "identity-binding-lifecycle-root-e2e-1"
    root_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"binding-lifecycle-root-{uuid4().hex}@example.test",
        password=root_password,
    )
    foreign_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"binding-lifecycle-foreign-{uuid4().hex}@example.test",
        password="identity-binding-lifecycle-foreign-2",
    )
    staff_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"binding-lifecycle-staff-{uuid4().hex}@example.test",
        password="identity-binding-lifecycle-staff-3",
    )
    organization_id, party_id, controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, _foreign_party, foreign_controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=foreign_identity.native_identity_id,
    )
    _staff_id, staff_binding_id = _invite_activate_staff(
        e2e_admin_conn,
        organization_id=organization_id,
        party_id=party_id,
        controller_id=controller_id,
        authority_id=authority_id,
        native_identity_id=staff_identity.native_identity_id,
    )
    foreign_binding_id = _binding_id(
        e2e_admin_conn,
        organization_id=foreign_organization_id,
        principal_id=foreign_controller_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(
            client,
            login_handle=root_identity.login_handle,
            password=root_password,
        )
        headers = _tenant_headers(token=token, organization_id=organization_id)

        # A revoked standing grant closes the lifecycle surface.
        _revoke_control_grant(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=controller_id,
            capability=_BIND_CAPABILITY,
        )
        denied = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:suspend",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 2, "provenance_reference": "denied"},
        )
        assert denied.status_code == 403, denied.text
        _restore_control_grant(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=controller_id,
            capability=_BIND_CAPABILITY,
        )

        # The Idempotency-Key header is mandatory for the command.
        missing_key = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:suspend",
            headers=headers,
            json={"expected_revision": 2, "provenance_reference": "missing-key"},
        )
        assert missing_key.status_code == 422, missing_key.text

        suspend = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:suspend",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 2, "provenance_reference": "lifecycle-suspend"},
        )
        assert suspend.status_code == 200, suspend.text
        assert suspend.headers["cache-control"] == "no-store"
        assert suspend.json() == {"binding_revision": 3}
        assert _binding_state(e2e_admin_conn, staff_binding_id) == ("suspended", 3)

        reactivate = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:reactivate",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 3, "provenance_reference": "lifecycle-reactivate"},
        )
        assert reactivate.status_code == 200, reactivate.text
        assert reactivate.json() == {"binding_revision": 4}
        assert _binding_state(e2e_admin_conn, staff_binding_id) == ("active", 4)

        revoke = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:revoke",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 4, "provenance_reference": "lifecycle-revoke"},
        )
        assert revoke.status_code == 200, revoke.text
        assert revoke.json() == {"binding_revision": 5}
        assert _binding_state(e2e_admin_conn, staff_binding_id) == ("revoked", 5)

        # Revoke is terminal.
        terminal = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:reactivate",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 5, "provenance_reference": "terminal"},
        )
        assert terminal.status_code == 409, terminal.text
        assert terminal.json()["error"]["code"] == "identity_binding_conflict"

        # A stale revision is a retryable conflict.
        stale = await client.post(
            f"/v1/identity-bindings/{staff_binding_id}:suspend",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 1, "provenance_reference": "stale"},
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["error"]["code"] == "identity_binding_revision_conflict"

        # Foreign and random bindings are indistinguishable.
        random_binding = uuid4()
        absent = await client.post(
            f"/v1/identity-bindings/{random_binding}:suspend",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 1, "provenance_reference": "absent"},
        )
        foreign = await client.post(
            f"/v1/identity-bindings/{foreign_binding_id}:suspend",
            headers={**headers, "Idempotency-Key": uuid4().hex},
            json={"expected_revision": 1, "provenance_reference": "foreign"},
        )
        assert absent.status_code == foreign.status_code == 404
        assert absent.json() == foreign.json()
        assert _binding_state(e2e_admin_conn, foreign_binding_id)[0] == "active"
