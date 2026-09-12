from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from starlette.requests import Request

from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.identity_resolution import (
    IdentityBindingSuspended,
    IdentityNotBound,
)
from request_engine.platform.security.tenant_http import TenantContextInvalid

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.security]
PASSWORD = "correct horse battery staple"
PgConnection = Connection[Any]


def _request(*, token: str, organization_id: UUID) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/capabilities",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"x-re-organization-id", str(organization_id).encode()),
            ],
        }
    )


@pytest.mark.asyncio
async def test_native_session_resolves_current_principal_and_binding_revocation_is_immediate(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    authority_id = uuid4()
    organization_row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name, public_profile)
        VALUES (%s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (f"native-auth-{suffix}", f"Native Auth {suffix[:8]}"),
    ).fetchone()
    assert organization_row is not None
    assert isinstance(organization_row[0], UUID)
    organization_id = organization_row[0]
    principal_row = admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"native-human-{suffix}"),
    ).fetchone()
    assert principal_row is not None
    assert isinstance(principal_row[0], UUID)
    principal_id = principal_row[0]
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment)
        VALUES (%s, 'native', %s)
        """,
        (authority_id, f"native-test:{suffix}"),
    )

    runtime = build_native_auth_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"native-{suffix}@example.test",
        password=PASSWORD,
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.identity_bindings (
            organization_id, principal_id, principal_plane,
            identity_authority_id, subject_id, status
        ) VALUES (%s, %s, 'tenant', %s, %s, 'active')
        """,
        (organization_id, principal_id, authority_id, str(enrollment.native_identity_id)),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, provenance_kind, provenance_reference,
            granted_by_principal_id
        ) VALUES (%s, %s, 'tenant', 'operational',
                  'appointments.read', false, 'authority_management', %s, %s)
        """,
        (organization_id, principal_id, f"native-runtime:{suffix}", principal_id),
    )

    issued = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle=f"native-{suffix}@example.test",
        password=PASSWORD,
    )
    actor = await runtime.actor_resolver.resolve_actor(
        _request(token=issued.raw_token, organization_id=organization_id)
    )

    assert actor.organization_id == organization_id
    assert actor.principal_id == principal_id
    assert actor.principal_kind.value == "human"
    assert actor.capabilities == frozenset({"appointments.read"})
    assert actor.credential_id == str(issued.session_id)

    assert runtime.platform_actor_resolver is None

    admin_conn.execute(
        """
        UPDATE request_engine.identity_bindings
           SET status = 'suspended', revision = revision + 1
         WHERE organization_id = %s
           AND principal_id = %s
           AND identity_authority_id = %s
           AND subject_id = %s
           AND status = 'active'
        """,
        (organization_id, principal_id, authority_id, str(enrollment.native_identity_id)),
    )

    with pytest.raises(IdentityBindingSuspended):
        await runtime.actor_resolver.resolve_actor(
            _request(token=issued.raw_token, organization_id=organization_id)
        )


@pytest.mark.asyncio
async def test_native_platform_http_actor_uses_current_binding_and_authority(
    admin_conn: PgConnection,
    pg_conninfo: str,
    command_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REQUEST_ENGINE_BOOTSTRAP_DSN", pg_conninfo)
    issued_intent = dict(
        line.split(": ", 1)
        for line in issue_intent(ttl_minutes=5, provenance="platform-http-proof").splitlines()
    )
    authority_id = UUID(issued_intent["Native authority"])
    root_id = establish_root(
        login_handle="platform-controller@example.test",
        raw_token=issued_intent["ONE-TIME BOOTSTRAP TOKEN"],
        password=PASSWORD,
    )
    runtime = build_native_auth_runtime(
        command_session_factory, platform_session_factory=platform_read_session_factory
    )
    assert runtime.platform_actor_resolver is not None
    session = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle="platform-controller@example.test",
        password=PASSWORD,
    )
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/platform-control-proof",
            "headers": [
                (b"authorization", f"Bearer {session.raw_token}".encode()),
                (b"x-re-principal-id", str(uuid4()).encode()),
                (b"x-re-capabilities", b"appointments.book,*"),
                (b"x-re-authority-revision", b"999999"),
            ],
        }
    )
    actor = await runtime.platform_actor_resolver.resolve_platform_actor(request)
    assert actor.principal_id == root_id
    assert actor.principal_kind.value == "human"
    assert actor.credential_id == str(session.session_id)
    assert actor.capabilities == frozenset(
        {
            "platform.tenant_provisioner.provision",
            "organization.provision",
            "platform.principal.provision",
            "platform.identity.recover",
        }
    )
    revision = admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s", (root_id,)
    ).fetchone()
    assert revision == (actor.authority_revision,)
    assert not actor.allows("appointments.book")

    for tenant_selector in (b"", b"not-a-uuid", str(uuid4()).encode()):
        mixed_plane = Request(
            {
                **request.scope,
                "headers": [*request.scope["headers"], (b"x-re-organization-id", tenant_selector)],
            }
        )
        with pytest.raises(TenantContextInvalid):
            await runtime.platform_actor_resolver.resolve_platform_actor(mixed_plane)

    admin_conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked', revision = revision + 1,
               revoked_at = clock_timestamp(), revoked_by_principal_id = %s
         WHERE principal_id = %s AND capability_key = 'organization.provision'
        """,
        (root_id, root_id),
    )
    refreshed = await runtime.platform_actor_resolver.resolve_platform_actor(request)
    assert refreshed.capabilities == actor.capabilities - {"organization.provision"}
    assert refreshed.authority_revision > actor.authority_revision
    admin_conn.execute(
        """
        UPDATE request_engine.identity_bindings
           SET status = 'suspended', revision = revision + 1
         WHERE principal_id = %s AND principal_plane = 'platform'
        """,
        (root_id,),
    )
    with pytest.raises(IdentityBindingSuspended):
        await runtime.platform_actor_resolver.resolve_platform_actor(request)
    assert admin_conn.execute(
        "SELECT status FROM request_engine.native_sessions WHERE id = %s",
        (session.session_id,),
    ).fetchone() == ("active",)

    # A fresh authenticated human must remain unbound, not become another root.
    await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle="unbound-platform-caller@example.test",
        password=PASSWORD,
    )
    unbound_session = await runtime.service.authenticate_password(
        identity_authority_id=authority_id,
        login_handle="unbound-platform-caller@example.test",
        password=PASSWORD,
    )
    unbound_request = Request(
        {
            **request.scope,
            "headers": [(b"authorization", f"Bearer {unbound_session.raw_token}".encode())],
        }
    )
    with pytest.raises(IdentityNotBound):
        await runtime.platform_actor_resolver.resolve_platform_actor(unbound_request)
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.principals WHERE principal_plane = 'platform'"
    ).fetchone() == (1,)
