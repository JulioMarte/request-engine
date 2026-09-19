"""E3 resource-authority inspection over the real tenant HTTP surface."""

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
_SIGNING_KEY = b"resource-authority-inspection-e2e-signing-key"
_V5 = "tenant-controller-v5"
_INSPECT = "authority.inspect_resource"
_OVERRIDE = "appointments.subject_override"
_BOOK_SCOPE = "appointments.book"
_SUPPLY_OPERATION = "booking.manage_supply"
_SUPPLY_SCOPE = "operations.manage_supply"


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
        "INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment) "
        "VALUES ('native', %s) RETURNING id",
        (f"resource-authority-e2e-{uuid4().hex}",),
    )


def _provision_tenant_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals (principal_plane, principal_kind, "
        "external_subject) VALUES ('platform', 'human', %s) RETURNING id",
        (f"resource-authority-platform-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants ("
        "principal_id, principal_plane, authority_plane, capability_key, delegable, "
        "provenance_kind, provenance_reference) VALUES ("
        "%s, 'platform', 'platform', 'organization.provision', false, 'trust_bootstrap', %s)",
        (provisioner_id, f"resource-authority-root:{uuid4().hex}"),
    )
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (provisioner_id,),
    ).fetchone()
    assert revision is not None
    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(int(revision[0])),),
    )
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            "SELECT * FROM request_platform.provision_native_organization_root("
            "%s, %s, %s, %s, %s, %s, %s, %s)",
            (
                organization_id,
                f"resource-authority-{organization_id.hex}",
                "Resource Authority E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"resource-authority-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _create_party(conn: PgConnection, *, organization_id: UUID) -> UUID:
    party_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.parties (id, organization_id, party_kind, display_name) "
        "VALUES (%s, %s, 'person', %s)",
        (party_id, organization_id, f"Authority Target {party_id.hex[:8]}"),
    )
    return party_id


def _grant_representation(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
    scope_key: str,
) -> UUID:
    representation_id = uuid4()
    conn.execute(
        "INSERT INTO request_engine.representations ("
        "id, organization_id, principal_id, represented_party_id, authority_kind, scope_key, "
        "valid_from) VALUES (%s, %s, %s, %s, 'delegated', %s, clock_timestamp())",
        (representation_id, organization_id, principal_id, party_id, scope_key),
    )
    return representation_id


def _representation_revision(conn: PgConnection, representation_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.representations WHERE id = %s",
        (representation_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _insert_policy_grants(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    policy_key: str,
) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants ("
        "organization_id, principal_id, principal_plane, authority_plane, capability_key, "
        "delegable, granted_by_principal_id, provenance_kind, provenance_reference) "
        "SELECT %s, %s, 'tenant', g.authority_plane, g.capability_key, true, %s, "
        "'authority_management', %s "
        "FROM jsonb_to_recordset("
        "(SELECT grants FROM request_engine.initial_controller_policies "
        "WHERE policy_key = %s)) AS g(capability_key text, authority_plane text, "
        "delegable boolean) "
        "ON CONFLICT (principal_id, capability_key) WHERE status = 'active' DO NOTHING",
        (
            organization_id,
            principal_id,
            principal_id,
            f"e3-e2e:{policy_key}:{uuid4().hex}",
            policy_key,
        ),
    )


def _revoke_capability(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability_key: str,
) -> None:
    conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE organization_id=%s AND principal_id=%s AND capability_key=%s AND status='active'",
        (principal_id, organization_id, principal_id, capability_key),
    )


def _headers(*, token: str, organization_id: UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions", json={"login_handle": login_handle, "password": password}
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


async def _inspect(
    client: AsyncClient,
    *,
    token: str,
    organization_id: UUID,
    body: dict[str, object],
) -> Any:
    return await client.post(
        "/v1/me/authority:inspect",
        headers=_headers(token=token, organization_id=organization_id),
        json=body,
    )


@pytest.mark.asyncio
async def test_resource_authority_inspection_http_journey(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "resource-authority-root-password-1"
    root_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"ra-root-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, root_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, _foreign_root_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=(
            await runtime.service.enroll_password_identity(
                identity_authority_id=authority_id,
                login_handle=f"ra-foreign-{uuid4().hex}@example.test",
                password="resource-authority-foreign-password-2",
            )
        ).native_identity_id,
    )
    subject = _create_party(e2e_admin_conn, organization_id=organization_id)
    foreign_party = _create_party(e2e_admin_conn, organization_id=foreign_organization_id)
    supply_party = _create_party(e2e_admin_conn, organization_id=organization_id)

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login(
            client, login_handle=root_identity.login_handle, password=root_password
        )

        # The native root policy is v3: the dedicated inspection capability is absent.
        denied_capability = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(subject)},
        )
        assert denied_capability.status_code == 403, denied_capability.text
        assert denied_capability.json()["error"]["code"] == "capability_required"

        _insert_policy_grants(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            policy_key=_V5,
        )

        # The v1 override is active: an existing target is allowed without a representation.
        overridden = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(subject)},
        )
        assert overridden.status_code == 200, overridden.text
        assert overridden.headers["cache-control"] == "no-store"
        assert overridden.json()["decision"] == "allowed"
        assert overridden.json()["reason_codes"] == ["operator_override"]
        assert overridden.json()["representation_revision"] is None
        assert overridden.json()["requires_owner_validation"] is True

        foreign = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(foreign_party)},
        )
        random_target = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(uuid4())},
        )
        assert foreign.status_code == random_target.status_code == 404
        assert foreign.json() == random_target.json()
        assert foreign.headers["cache-control"] == "no-store"
        assert str(foreign_party) not in foreign.text

        unknown = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": "appointments.archive", "subject_party_id": str(subject)},
        )
        assert unknown.status_code == 422, unknown.text
        missing_target = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _SUPPLY_OPERATION},
        )
        assert missing_target.status_code == 422, missing_target.text

        # Supply management has no override: denied until a current representation exists.
        supply_denied = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _SUPPLY_OPERATION, "authority_party_id": str(supply_party)},
        )
        assert supply_denied.status_code == 200, supply_denied.text
        assert supply_denied.json()["decision"] == "denied"
        assert supply_denied.json()["reason_codes"] == ["no_current_representation"]
        supply_representation = _grant_representation(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            party_id=supply_party,
            scope_key=_SUPPLY_SCOPE,
        )
        supply_allowed = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _SUPPLY_OPERATION, "authority_party_id": str(supply_party)},
        )
        assert supply_allowed.status_code == 200, supply_allowed.text
        assert supply_allowed.json()["decision"] == "allowed"
        assert supply_allowed.json()["reason_codes"] == ["current_representation"]
        assert supply_allowed.json()["representation_revision"] == _representation_revision(
            e2e_admin_conn, supply_representation
        )

        # Without the override the book decision follows the exact-scope representation.
        _revoke_capability(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            capability_key=_OVERRIDE,
        )
        book_denied = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(subject)},
        )
        assert book_denied.status_code == 200, book_denied.text
        assert book_denied.json()["decision"] == "denied"
        book_representation = _grant_representation(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            party_id=subject,
            scope_key=_BOOK_SCOPE,
        )
        book_allowed = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(subject)},
        )
        assert book_allowed.status_code == 200, book_allowed.text
        assert book_allowed.json()["decision"] == "allowed"
        assert book_allowed.json()["reason_codes"] == ["current_representation"]
        assert book_allowed.json()["representation_revision"] == _representation_revision(
            e2e_admin_conn, book_representation
        )
        _revoke_capability(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            capability_key=_INSPECT,
        )
        revoked = await _inspect(
            client,
            token=token,
            organization_id=organization_id,
            body={"operation": _BOOK_SCOPE, "subject_party_id": str(subject)},
        )
        assert revoked.status_code == 403, revoked.text

    operation = app.openapi()["paths"]["/v1/me/authority:inspect"]["post"]
    assert operation["operationId"] == "authority_inspect_resource"
    assert operation["x-request-engine-capability"] == _INSPECT
    assert operation["x-request-engine-owner"] == "tenancy"
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"
    assert "x-request-engine-tool-name" not in operation
    headers = {
        parameter["name"].lower()
        for parameter in operation.get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert "idempotency-key" not in headers
