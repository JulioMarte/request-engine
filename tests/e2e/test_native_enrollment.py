"""HTTP enrollment persists credentials without creating tenant authority.

The deployment bootstrap establishes only the native authority prerequisite;
enrollment/login and all observed outcomes use supported HTTP surfaces. No SQL
or direct auth-service enrollment seeds the identity under test. Owned by the
current-product PostgreSQL E2E lane; run centrally with the shared DB suite.
"""

import os
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.platform_bootstrap_cli import issue_intent
from request_engine.platform.db.session import SessionFactory

from .conftest import PgConnection

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_native_enrollment_login_does_not_provision_authority(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_BOOTSTRAP_DSN",
        make_conninfo(
            e2e_admin_conn.info.dsn,
            password=os.environ.get("PGPASSWORD", "request_engine"),
        ),
    )
    issued = issue_intent(ttl_minutes=15, provenance="native-enrollment-e2e")
    authority_line = next(
        line for line in issued.splitlines() if line.startswith("Native authority:")
    )
    authority_id = UUID(authority_line.split(": ", 1)[1])
    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"native-enrollment-e2e-signing-key-1",
    )
    handle = f"reception-{uuid4().hex}@example.test"
    password = "native enrollment secure password"
    replacement = "unauthorized replacement password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": f" {handle.upper()} ", "password": password},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity = enrolled.json()
        assert UUID(identity["native_identity_id"])
        assert identity == {
            "native_identity_id": identity["native_identity_id"],
            "identity_authority_id": str(authority_id),
            "login_handle": handle,
        }
        assert enrolled.headers["cache-control"] == "no-store"
        duplicate = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": replacement},
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["error"]["code"] == "native_identity_already_exists"
        rejected = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": replacement}
        )
        assert rejected.status_code == 401, rejected.text
        logged_in = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": password}
        )
        assert logged_in.status_code == 201, logged_in.text
        token = logged_in.json()["access_token"]
        assert token and logged_in.json()["token_type"] == "Bearer"
        credentials_before = e2e_admin_conn.execute(
            "SELECT id, status, revision FROM request_engine.native_credentials "
            "WHERE native_identity_id = %s ORDER BY id",
            (UUID(identity["native_identity_id"]),),
        ).fetchall()
        for weak_password in ("too-short", "\U0001f512" * 300):
            weak_rotation = await client.put(
                "/auth/native/password",
                json={
                    "login_handle": handle,
                    "current_password": password,
                    "new_password": weak_password,
                },
            )
            assert weak_rotation.status_code == 422, weak_rotation.text
            assert weak_rotation.json()["error"]["code"] == "password_policy_violation"
            assert weak_rotation.headers["cache-control"] == "no-store"
            assert password not in weak_rotation.text
        assert (
            e2e_admin_conn.execute(
                "SELECT id, status, revision FROM request_engine.native_credentials "
                "WHERE native_identity_id = %s ORDER BY id",
                (UUID(identity["native_identity_id"]),),
            ).fetchall()
            == credentials_before
        )
        unbound = await client.get(
            "/v1/parties/lookup",
            headers={
                "Authorization": f"Bearer {token}",
                "X-RE-Organization-ID": str(uuid4()),
            },
            params={"mode": "name", "value": "Nobody"},
        )
        assert unbound.status_code == 403, unbound.text
        assert unbound.json()["error"]["code"] == "identity_not_bound"
        logged_out = await client.delete(
            "/auth/native/sessions/current", headers={"Authorization": f"Bearer {token}"}
        )
        assert logged_out.status_code == 204, logged_out.text
        revoked = await client.delete(
            "/auth/native/sessions/current", headers={"Authorization": f"Bearer {token}"}
        )
        assert revoked.status_code == 401, revoked.text
        second_login = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": password}
        )
        assert second_login.status_code == 201, second_login.text
        second_token = second_login.json()["access_token"]
        rotated = await client.put(
            "/auth/native/password",
            json={
                "login_handle": handle,
                "current_password": password,
                "new_password": replacement,
            },
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.headers["cache-control"] == "no-store"
        assert replacement not in rotated.text
        old_password = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": password}
        )
        assert old_password.status_code == 401, old_password.text
        old_session = await client.delete(
            "/auth/native/sessions/current", headers={"Authorization": f"Bearer {second_token}"}
        )
        assert old_session.status_code == 401, old_session.text
        new_login = await client.post(
            "/auth/native/sessions", json={"login_handle": handle, "password": replacement}
        )
        assert new_login.status_code == 201, new_login.text
    assert e2e_admin_conn.execute(
        "SELECT status, count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s GROUP BY status ORDER BY status",
        (UUID(identity["native_identity_id"]),),
    ).fetchall() == [("active", 1), ("revoked", 1)]
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings "
        "WHERE identity_authority_id = %s AND subject_id = %s",
        (authority_id, identity["native_identity_id"]),
    ).fetchone() == (0,)
