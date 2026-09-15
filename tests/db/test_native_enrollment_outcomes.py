"""Native enrollment outcome contract: created, duplicate and unavailable are distinct.

request_auth.create_native_identity must never collapse an absent, disabled or
wrong-kind authority into a duplicate-handle result. The three outcomes are
observed directly through the app role and through the owning service mapping.
"""

from typing import Any, LiteralString
from uuid import UUID, uuid4

import pytest
from native_authority_gate_support import (
    PASSWORD,
    auth_fingerprint,
    insert_authority,
    set_authority_status,
)
from psycopg import Connection

from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import hash_password
from request_engine.platform.security.native_human_auth import (
    NativeEnrollmentUnavailable,
    NativeHumanAuthService,
    NativeIdentityAlreadyExists,
)

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_CREATE_SQL: LiteralString = "SELECT request_auth.create_native_identity(%s, %s, %s, %s, %s)"


def _service(session_factory: SessionFactory) -> NativeHumanAuthService:
    return NativeHumanAuthService(store=PostgresNativeHumanAuthStore(session_factory))


def _direct_call(conn: PgConnection, authority_id: UUID, *, handle: str) -> tuple[object, ...]:
    row = conn.execute(
        _CREATE_SQL,
        (authority_id, uuid4(), handle, uuid4(), hash_password(PASSWORD)),
    ).fetchone()
    # Commit the observed call: rollback would conceal an accidental write.
    conn.commit()
    assert row is not None
    return row


def test_created_and_duplicate_are_distinct_sql_outcomes(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
) -> None:
    authority_id = insert_authority(admin_conn)
    handle = f"outcome-{uuid4().hex}@example.test"

    assert _direct_call(app_role_conn, authority_id, handle=handle) == (True,)
    created = admin_conn.execute(
        "SELECT i.id, c.id FROM request_engine.native_identities AS i "
        "JOIN request_engine.native_credentials AS c ON c.native_identity_id = i.id "
        "WHERE i.identity_authority_id = %s AND i.login_handle = %s",
        (authority_id, handle),
    ).fetchone()
    assert created is not None

    assert _direct_call(app_role_conn, authority_id, handle=handle) == (False,)
    assert (
        admin_conn.execute(
            "SELECT i.id, c.id FROM request_engine.native_identities AS i "
            "JOIN request_engine.native_credentials AS c ON c.native_identity_id = i.id "
            "WHERE i.identity_authority_id = %s AND i.login_handle = %s",
            (authority_id, handle),
        ).fetchone()
        == created
    )


def test_unavailable_authority_is_not_a_duplicate_sql_outcome(
    admin_conn: PgConnection,
    app_role_conn: PgConnection,
) -> None:
    disabled_authority = insert_authority(admin_conn)
    disabled_handle = f"outcome-disabled-{uuid4().hex}@example.test"
    set_authority_status(admin_conn, disabled_authority, "disabled")
    assert _direct_call(app_role_conn, disabled_authority, handle=disabled_handle) == (None,)

    unknown_handle = f"outcome-unknown-{uuid4().hex}@example.test"
    assert _direct_call(app_role_conn, uuid4(), handle=unknown_handle) == (None,)

    wrong_kind_authority = insert_authority(admin_conn, kind="workload")
    wrong_kind_handle = f"outcome-workload-{uuid4().hex}@example.test"
    assert _direct_call(app_role_conn, wrong_kind_authority, handle=wrong_kind_handle) == (None,)

    for handle in (disabled_handle, unknown_handle, wrong_kind_handle):
        assert admin_conn.execute(
            "SELECT count(*) FROM request_engine.native_identities WHERE login_handle = %s",
            (handle,),
        ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_service_maps_duplicate_and_unavailable_to_distinct_errors(
    admin_conn: PgConnection,
    command_session_factory: SessionFactory,
) -> None:
    authority_id = insert_authority(admin_conn)
    service = _service(command_session_factory)
    handle = f"outcome-service-{uuid4().hex}@example.test"
    enrollment = await service.enroll_password_identity(
        identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
    )
    before = auth_fingerprint(admin_conn, enrollment.native_identity_id)

    with pytest.raises(NativeIdentityAlreadyExists):
        await service.enroll_password_identity(
            identity_authority_id=authority_id, login_handle=handle, password=PASSWORD
        )
    assert auth_fingerprint(admin_conn, enrollment.native_identity_id) == before

    set_authority_status(admin_conn, authority_id, "disabled")
    with pytest.raises(NativeEnrollmentUnavailable):
        await service.enroll_password_identity(
            identity_authority_id=authority_id,
            login_handle=f"outcome-service-disabled-{uuid4().hex}@example.test",
            password=PASSWORD,
        )
    assert auth_fingerprint(admin_conn, enrollment.native_identity_id) == before
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities"
    ).fetchone() == (1,)
