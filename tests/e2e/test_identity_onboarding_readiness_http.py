"""E2 identity-aware onboarding readiness over the real tenant HTTP surface.

The journey provisions a real tenant root with a credentialed Native identity,
authenticates through the public native-session endpoint and reads the existing
``GET /v1/onboarding/readiness`` projection. It asserts that owner-backed
identity/control facts are reported honestly (identity and staff administration
ready, recorded-policy readiness blocked) and that the response leaks no
Principal identity, login handle or global recovery configuration.
"""

from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from . import native_provisioning_support as support

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"identity-onboarding-readiness-e2e-signing-key"


def _create_native_authority(conn: PgConnection) -> Any:
    return support.uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s)
        RETURNING id
        """,
        (f"identity-onboarding-{uuid4().hex}",),
    )


@pytest.mark.asyncio
async def test_identity_aware_readiness_http_journey(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    runtime = build_native_auth_runtime(e2e_session_factory)
    password = "identity-onboarding-root-password-1"
    root_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-{uuid4().hex}@example.test",
        password=password,
    )
    organization_id, root_principal_id = support.provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    support.grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=root_principal_id,
        capability_key="onboarding.read",
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await support.login(
            client,
            login_handle=root_identity.login_handle,
            password=password,
        )
        response = await client.get(
            "/v1/onboarding/readiness",
            headers=support.tenant_headers(token=token, organization_id=organization_id),
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()

    assert body["identity"] == {"status": "ready", "ready": True, "blockers": []}
    assert body["staff_administration"] == {"status": "ready", "ready": True, "blockers": []}
    assert body["tenant_control"] == {
        "status": "blocked",
        "ready": False,
        "blockers": [
            {
                "code": "controller_policy_upgrade_required",
                "owner": "tenancy",
                "resolution_capabilities": ["controller_policy_upgrade"],
                "requires_operator": True,
                "operation_id": "controller_policy_upgrade",
            }
        ],
    }
    assert body["recovery"] == {"status": "unknown", "ready": False, "blockers": []}
    assert body["policy_revision"] is None
    assert isinstance(body["controller_authority_revision"], int)
    assert body["controller_authority_revision"] >= 1
    assert body["observed_at"]

    serialized = response.text
    assert root_identity.login_handle not in serialized
    assert str(root_principal_id) not in serialized
    assert str(root_identity.native_identity_id) not in serialized
    assert "recovery_delivery_unconfigured" not in serialized
    assert "recovery_security_operator_missing" not in serialized


@pytest.mark.asyncio
async def test_readiness_without_capability_is_denied(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    runtime = build_native_auth_runtime(e2e_session_factory)
    password = "identity-onboarding-no-capability-1"
    root_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"no-cap-{uuid4().hex}@example.test",
        password=password,
    )
    organization_id, _root_principal_id = support.provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await support.login(
            client,
            login_handle=root_identity.login_handle,
            password=password,
        )
        response = await client.get(
            "/v1/onboarding/readiness",
            headers=support.tenant_headers(token=token, organization_id=organization_id),
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "capability_required"
