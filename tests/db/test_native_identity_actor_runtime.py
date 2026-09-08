from uuid import UUID, uuid4

import pytest
from starlette.requests import Request

from request_engine.entrypoints.http.native_runtime import build_native_human_runtime
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.identity_resolution import IdentityBindingSuspended

pytestmark = [pytest.mark.postgres, pytest.mark.integration, pytest.mark.security]
PASSWORD = "correct horse battery staple"


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
    admin_conn: object,
    command_session_factory: SessionFactory,
) -> None:
    admin = admin_conn
    assert hasattr(admin, "execute")
    suffix = uuid4().hex
    authority_id = uuid4()
    organization_id = admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.organizations (organization_key, display_name, public_profile)
        VALUES (%s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (f"native-auth-{suffix}", f"Native Auth {suffix[:8]}"),
    ).fetchone()[0]
    principal_id = admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"native-human-{suffix}"),
    ).fetchone()[0]
    admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment)
        VALUES (%s, 'native', %s)
        """,
        (authority_id, f"native-test:{suffix}"),
    )

    runtime = build_native_human_runtime(command_session_factory)
    enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"native-{suffix}@example.test",
        password=PASSWORD,
    )
    admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.identity_bindings (
            organization_id, principal_id, principal_plane,
            identity_authority_id, subject_id, status
        ) VALUES (%s, %s, 'tenant', %s, %s, 'active')
        """,
        (organization_id, principal_id, authority_id, str(enrollment.native_identity_id)),
    )
    admin.execute(  # type: ignore[attr-defined]
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, provenance_kind, provenance_reference
        ) VALUES (%s, %s, 'tenant', 'operational',
                  'appointments.read', false, 'trust_bootstrap', %s)
        """,
        (organization_id, principal_id, f"native-runtime:{suffix}"),
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

    admin.execute(  # type: ignore[attr-defined]
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
