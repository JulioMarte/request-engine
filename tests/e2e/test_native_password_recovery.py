"""HTTP recovery consumption, not proof of a public token-issuance workflow."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_human_auth import NativeHumanAuthService

from .conftest import PgConnection

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security]


@pytest.mark.asyncio
async def test_recovery_http_consumes_once_revokes_old_sessions_and_preserves_authority(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"recovery-http-{uuid4().hex}"),
    )
    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"native-recovery-http-signing-key-1",
    )
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(e2e_session_factory))
    handle = f"recovery-{uuid4().hex}@example.test"
    old_password = "original native recovery password"
    new_password = "replacement native recovery password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={
                "login_handle": handle,
                "password": old_password,
            },
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])
        logged_in = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": handle,
                "password": old_password,
            },
        )
        assert logged_in.status_code == 201, logged_in.text
        session_token = logged_in.json()["access_token"]
        # Trusted internal issuance is a prerequisite. The HTTP operation under
        # test must consume it itself; no replacement credential is pre-seeded.
        issued = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert issued is not None
        payload = {"recovery_token": issued.raw_token, "new_password": new_password}
        for invalid in ("malformed", issue_opaque_token().raw_token):
            denied = await client.post(
                "/auth/native/password:recover",
                json={
                    **payload,
                    "recovery_token": invalid,
                },
            )
            assert denied.status_code == 401, denied.text
            assert denied.json()["error"]["code"] == "recovery_intent_invalid"
            assert denied.headers["cache-control"] == "no-store"
            assert new_password not in denied.text
        injected = await client.post(
            "/auth/native/password:recover",
            json={
                **payload,
                "native_identity_id": str(uuid4()),
            },
        )
        assert injected.status_code == 422
        assert issued.raw_token not in injected.text
        weak = await client.post(
            "/auth/native/password:recover",
            json={
                **payload,
                "new_password": "too-short",
            },
        )
        assert weak.status_code == 422
        assert weak.json()["error"]["code"] == "password_policy_violation"
        assert weak.headers["cache-control"] == "no-store"
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id=%s",
            (identity_id,),
        ).fetchone() == (1,)
        recovered = await client.post("/auth/native/password:recover", json=payload)
        assert recovered.status_code == 204, recovered.text
        assert recovered.content == b""
        assert recovered.headers["cache-control"] == "no-store"
        replay = await client.post("/auth/native/password:recover", json=payload)
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "recovery_intent_invalid"
        old_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": handle,
                "password": old_password,
            },
        )
        assert old_login.status_code == 401
        old_session = await client.delete(
            "/auth/native/sessions/current",
            headers={
                "Authorization": f"Bearer {session_token}",
            },
        )
        assert old_session.status_code == 401
        new_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": handle,
                "password": new_password,
            },
        )
        assert new_login.status_code == 201, new_login.text
        second = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert second is not None
        await service.disable_identity(
            native_identity_id=identity_id, reason="test_disabled_target"
        )
        disabled = await client.post(
            "/auth/native/password:recover",
            json={
                "recovery_token": second.raw_token,
                "new_password": "must not reactivate identity",
            },
        )
        assert disabled.status_code == 401
        assert disabled.json()["error"]["code"] == "recovery_intent_invalid"
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id=%s",
        (identity_id,),
    ).fetchone() == (2,)
    assert e2e_admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (
        0,
    )
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (0,)
