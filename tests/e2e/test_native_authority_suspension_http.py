"""HTTP authority suspension: login, rotation, recovery and session resolution."""

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_human_auth import NativeHumanAuthService

from .conftest import PgConnection

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]

_OLD_PASSWORD = "original authority suspension password"
_NEW_PASSWORD = "replacement authority suspension password"


def _app(session_factory: SessionFactory, authority_id: UUID) -> FastAPI:
    return create_native_app(
        session_factory=session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"native-authority-suspension-key-1",
    )


def _authority(conn: PgConnection, *, kind: str = "native") -> UUID:
    authority_id = uuid4()
    conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment)
        VALUES (%s, %s, %s)
        """,
        (authority_id, kind, f"authority-suspension:{authority_id}"),
    )
    return authority_id


def _set_authority(conn: PgConnection, authority_id: UUID, status: str) -> None:
    conn.execute(
        "UPDATE request_engine.identity_authorities SET status = %s, "
        "revision = revision + 1 WHERE id = %s",
        (status, authority_id),
    )


@pytest.mark.asyncio
async def test_suspended_authority_rejects_http_authentication_and_recovers_after_reenable(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _authority(e2e_admin_conn)
    app = _app(e2e_session_factory, authority_id)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(e2e_session_factory))
    handle = f"authority-suspension-{uuid4().hex}@example.test"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": _OLD_PASSWORD},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])
        logged_in = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": _OLD_PASSWORD},
        )
        assert logged_in.status_code == 201, logged_in.text
        session_token = logged_in.json()["access_token"]
        issued = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert issued is not None

        _set_authority(e2e_admin_conn, authority_id, "disabled")

        denied_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": _OLD_PASSWORD},
        )
        assert denied_login.status_code == 401, denied_login.text
        assert denied_login.headers["cache-control"] == "no-store"
        assert denied_login.json()["error"]["code"] == "credential_invalid"
        assert _OLD_PASSWORD not in denied_login.text
        assert "authority" not in denied_login.text.casefold()

        denied_rotation = await client.put(
            "/auth/native/password",
            json={
                "login_handle": handle,
                "current_password": _OLD_PASSWORD,
                "new_password": _NEW_PASSWORD,
            },
        )
        assert denied_rotation.status_code == 401, denied_rotation.text
        assert denied_rotation.headers["cache-control"] == "no-store"
        assert denied_rotation.json()["error"]["code"] == "credential_invalid"
        assert _NEW_PASSWORD not in denied_rotation.text

        denied_recovery = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": issued.raw_token, "new_password": _NEW_PASSWORD},
        )
        assert denied_recovery.status_code == 401, denied_recovery.text
        assert denied_recovery.json()["error"]["code"] == "recovery_intent_invalid"
        assert denied_recovery.headers["cache-control"] == "no-store"
        assert issued.raw_token not in denied_recovery.text
        assert _NEW_PASSWORD not in denied_recovery.text

        denied_session = await client.delete(
            "/auth/native/sessions/current",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert denied_session.status_code == 401, denied_session.text
        assert denied_session.json()["error"]["code"] == "credential_invalid"

        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id = %s",
            (identity_id,),
        ).fetchone() == (1,)
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.native_sessions "
            "WHERE native_identity_id = %s AND status = 'active'",
            (identity_id,),
        ).fetchone() == (1,)
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
            (issued.recovery_id,),
        ).fetchone() == ("pending",)

        _set_authority(e2e_admin_conn, authority_id, "active")

        revived_session = await client.delete(
            "/auth/native/sessions/current",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert revived_session.status_code == 204, revived_session.text

        reenabled_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": _OLD_PASSWORD},
        )
        assert reenabled_login.status_code == 201, reenabled_login.text
        consumed = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": issued.raw_token, "new_password": _NEW_PASSWORD},
        )
        assert consumed.status_code == 204, consumed.text
        old_password_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": _OLD_PASSWORD},
        )
        assert old_password_login.status_code == 401
        new_password_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": _NEW_PASSWORD},
        )
        assert new_password_login.status_code == 201, new_password_login.text


@pytest.mark.asyncio
async def test_suspended_authority_enrollment_rejects_without_creating_identity(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _authority(e2e_admin_conn)
    app = _app(e2e_session_factory, authority_id)
    _set_authority(e2e_admin_conn, authority_id, "disabled")
    handle = f"authority-suspended-enroll-{uuid4().hex}@example.test"
    password = "suspended enrollment password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": password},
        )
    # create_native_identity distinguishes a duplicate handle (false) from an
    # unavailable authority (NULL). An unavailable authority is operator
    # intervention, not a duplicate, and never creates identity or credential.
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "native_enrollment_unavailable"
    assert error["resolution"] == "operator_intervention"
    assert error["retryable"] is False
    assert response.headers["cache-control"] == "no-store"
    assert password not in response.text
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities"
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials"
    ).fetchone() == (0,)


@pytest.mark.asyncio
@pytest.mark.parametrize("authority_kind", ["absent", "workload"])
async def test_unavailable_authority_enrollment_is_operator_intervention(
    authority_kind: str,
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = (
        uuid4() if authority_kind == "absent" else _authority(e2e_admin_conn, kind="workload")
    )
    app = _app(e2e_session_factory, authority_id)
    handle = f"authority-{authority_kind}-enroll-{uuid4().hex}@example.test"
    password = "unavailable authority enrollment password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": password},
        )
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "native_enrollment_unavailable"
    assert error["resolution"] == "operator_intervention"
    assert error["retryable"] is False
    assert response.headers["cache-control"] == "no-store"
    assert password not in response.text
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_identities"
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials"
    ).fetchone() == (0,)
