from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from test_staff_membership_lifecycle import (
    invite_active_staff,
    new_staff_native_identity,
    provision_staff_root,
)

from request_engine.entrypoints.http.app import create_authenticated_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]


def _subject(conn: Connection[Any], binding: UUID) -> tuple[UUID, str]:
    row = conn.execute(
        "SELECT identity_authority_id, subject_id "
        "FROM request_engine.identity_bindings WHERE id=%s",
        (binding,),
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def _read(
    conn: Connection[Any], authority: UUID, subject: str, after: UUID | None = None
) -> list[Any]:
    conn.execute("SET ROLE request_engine_app")
    try:
        return conn.execute(
            "SELECT * FROM request_auth.read_self_organizations(%s,%s,%s,50)",
            (authority, subject, after),
        ).fetchall()
    finally:
        conn.execute("RESET ROLE")


def test_self_organizations_is_exact_subject_and_not_platform_directory(
    admin_conn: Connection[Any],
) -> None:
    org, _party, principal, binding, _provisioner = provision_staff_root(admin_conn)
    foreign_org, *_ = provision_staff_root(admin_conn)
    authority, subject = _subject(admin_conn, binding)
    rows = _read(admin_conn, authority, subject)
    assert len(rows) == 1
    assert rows[0][0:3] == (org, "Staff Tenant", principal)
    assert foreign_org not in {row[0] for row in rows}
    assert _read(admin_conn, authority, str(uuid4())) == []
    assert _read(admin_conn, uuid4(), subject) == []
    assert _read(admin_conn, authority, subject, org) == []
    # The projection does not create a grant or bind the unrelated platform provisioner.
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.staff_memberships WHERE principal_id=%s",
        (_provisioner,),
    ).fetchone() == (0,)


@pytest.mark.parametrize(
    "boundary", ["binding", "principal", "membership", "authority", "identity", "organization"]
)
def test_self_organizations_omits_unusable_context(
    admin_conn: Connection[Any], boundary: str
) -> None:
    _org, party, root, _, _ = provision_staff_root(admin_conn)
    authority, identity, _ = new_staff_native_identity(admin_conn)
    _, principal, binding = invite_active_staff(
        admin_conn,
        organization_id=_org,
        root_id=root,
        party_id=party,
        authority_id=authority,
        native_identity_id=identity,
    )
    authority, subject = _subject(admin_conn, binding)
    assert len(_read(admin_conn, authority, subject)) == 1
    # These rows are preconditions for read-only discovery, not manufactured read results.
    if boundary == "binding":
        admin_conn.execute(
            "UPDATE request_engine.identity_bindings SET status='suspended', "
            "revision=revision+1 WHERE id=%s",
            (binding,),
        )
    elif boundary == "principal":
        admin_conn.execute(
            "UPDATE request_engine.principals SET active=false WHERE id=%s", (principal,)
        )
    elif boundary == "membership":
        admin_conn.execute(
            "UPDATE request_engine.staff_memberships SET status='suspended', "
            "suspended_at=clock_timestamp(), revision=revision+1 WHERE principal_id=%s",
            (principal,),
        )
    elif boundary == "authority":
        admin_conn.execute(
            "UPDATE request_engine.identity_authorities SET status='disabled' WHERE id=%s",
            (authority,),
        )
    elif boundary == "identity":
        admin_conn.execute(
            "UPDATE request_engine.native_identities SET status='disabled', "
            "disabled_at=clock_timestamp(), revision=revision+1, "
            "session_epoch=session_epoch+1 WHERE id=%s",
            (UUID(subject),),
        )
    else:
        admin_conn.execute(
            "UPDATE request_engine.organizations SET operational_status='inactive' WHERE id=%s",
            (_org,),
        )
    assert _read(admin_conn, authority, subject) == []


def test_self_organizations_spans_only_the_same_subject_memberships(
    admin_conn: Connection[Any],
) -> None:
    native = new_staff_native_identity(admin_conn)
    first, *_ = provision_staff_root(admin_conn, native_identity=native)
    second, *_ = provision_staff_root(admin_conn, native_identity=native)
    provision_staff_root(admin_conn)
    expected = sorted([first, second])
    assert [row[0] for row in _read(admin_conn, native[0], str(native[1]))] == expected
    assert [row[0] for row in _read(admin_conn, native[0], str(native[1]), expected[0])] == [
        expected[1]
    ]


def test_self_organizations_accepts_another_active_binding_of_the_member(
    admin_conn: Connection[Any],
) -> None:
    organization, _, principal, original_binding, _ = provision_staff_root(admin_conn)
    authority, identity, _ = new_staff_native_identity(admin_conn)
    admin_conn.execute(
        "INSERT INTO request_engine.identity_bindings "
        "(organization_id, principal_id, principal_plane, "
        "identity_authority_id, subject_id, status) "
        "VALUES (%s, %s, 'tenant', %s, %s, 'active')",
        (organization, principal, authority, str(identity)),
    )
    rows = _read(admin_conn, authority, str(identity))
    assert len(rows) == 1
    assert rows[0][0] == organization
    # The membership's establishment binding is not the only valid sign-in path.
    assert admin_conn.execute(
        "SELECT identity_binding_id FROM request_engine.staff_memberships WHERE id=%s",
        (rows[0][3],),
    ).fetchone() == (original_binding,)


@pytest.mark.asyncio
async def test_http_composition_discovers_context_through_real_app_role(
    admin_conn: Connection[Any],
    command_session_factory: SessionFactory,
) -> None:
    native = new_staff_native_identity(admin_conn)
    first, *_ = provision_staff_root(admin_conn, native_identity=native)
    second, *_ = provision_staff_root(admin_conn, native_identity=native)
    foreign, *_ = provision_staff_root(admin_conn)

    class VerifiedSubject:
        async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
            if request.headers.get("authorization") != "Bearer verified-subject":
                raise AuthenticationRequired("Bearer required")
            return AuthenticatedHttpSubject(
                AuthenticatedSubject(
                    str(native[0]), str(native[1]), AuthenticatedSubjectClass.HUMAN
                ),
                "test-authentication-boundary",
            )

    app = create_authenticated_app(
        session_factory=command_session_factory,
        subject_resolver=VerifiedSubject(),
        appointment_option_signing_key=b"test-signing-key-at-least-32-bytes",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        headers = {"Authorization": "Bearer verified-subject"}
        page = await client.get("/v1/me/organizations?limit=1", headers=headers)
        assert page.status_code == 200, page.text
        assert UUID(page.json()["items"][0]["organization_id"]) == min(first, second)
        next_page = await client.get(
            "/v1/me/organizations",
            headers=headers,
            params={"after": page.json()["next_after"], "limit": "1"},
        )
        assert next_page.status_code == 200, next_page.text
        assert UUID(next_page.json()["items"][0]["organization_id"]) == max(first, second)
        assert next_page.json()["next_after"] is None
        assert str(foreign) not in page.text + next_page.text
        injected = await client.get(
            "/v1/me/organizations",
            headers={**headers, "X-RE-Organization-ID": str(foreign)},
        )
        assert injected.status_code == 400
        assert (await client.get("/v1/me/organizations")).status_code == 401
