"""HTTP WebAuthn login and step-up journey (ADR 0014 §8).

Claims a fresh instance over the control-plane HTTP surface, then authenticates
the Platform Owner with the SAME real software passkey over HTTP and proves the
resulting native session carries PHISHING_RESISTANT assurance. It also proves a
password session can be raised only by a session-bound WebAuthn step-up, that
challenges are single-use, and that unknown login handles are not an enumeration
oracle.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.bootstrap.platform_server import create_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import parse_opaque_token

from .conftest import PgConnection, RuntimeCredentials

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security]

ORIGIN = "https://localhost"
LOGIN_HANDLE = "webauthn-owner@example.test"
PASSWORD = "webauthn owner password"


@pytest.fixture
def private_runtime_configuration(
    e2e_admin_conn: PgConnection,
    app_runtime_credentials: RuntimeCredentials,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> UUID:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"webauthn-login-http-{authority_id}"),
    )
    monkeypatch.setenv("REQUEST_ENGINE_DATABASE_URL", app_runtime_credentials.database_url)
    monkeypatch.setenv("REQUEST_ENGINE_NATIVE_IDENTITY_AUTHORITY_ID", str(authority_id))
    read_engine = platform_read_session_factory.kw["bind"]
    write_engine = platform_control_session_factory.kw["bind"]
    monkeypatch.setenv(
        "REQUEST_ENGINE_PLATFORM_READ_DATABASE_URL",
        read_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv(
        "REQUEST_ENGINE_PLATFORM_CONTROL_DATABASE_URL",
        write_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_RP_ID", "localhost")
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setenv("REQUEST_ENGINE_WEBAUTHN_DECOY_KEY", "d" * 64)
    return authority_id


def _instance(e2e_admin_conn: PgConnection, *, native_authority_id: UUID) -> None:
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id, built_in_native_authority_id, built_in_workload_authority_id) "
        "VALUES (%s, %s, %s)",
        (uuid4(), native_authority_id, uuid4()),
    )


async def _claim_owner(
    client: AsyncClient, *, login_handle: str = LOGIN_HANDLE, password: str = PASSWORD
) -> SoftwareAuthenticator:
    issued = (await client.post("/v1/setup/sessions")).json()
    headers = {"Authorization": f"Setup {issued['token']}"}
    assert (
        await client.post(
            "/v1/setup/native-identity",
            headers=headers,
            json={"login_handle": login_handle, "password": password},
        )
    ).status_code == 204
    options = (
        await client.post("/v1/setup/webauthn/registration-options", headers=headers)
    ).json()["public_key"]
    authenticator = SoftwareAuthenticator(rp_id=options["rp"]["id"], origin=ORIGIN)
    credential = authenticator.registration_credential(
        challenge=websafe_decode(options["challenge"]), user_verified=True
    )
    assert (
        await client.post(
            "/v1/setup/webauthn/registrations",
            headers=headers,
            json={"credential": credential},
        )
    ).status_code == 204
    assert (await client.post("/v1/setup/recovery-codes", headers=headers)).status_code == 201
    finalized = await client.post(
        "/v1/setup:finalize",
        headers={**headers, "Idempotency-Key": "webauthn-login-claim"},
        json={"claim_provenance": "e2e:webauthn-login"},
    )
    assert finalized.status_code == 201
    return authenticator


async def _webauthn_login(
    client: AsyncClient, authenticator: SoftwareAuthenticator, *, login_handle: str = LOGIN_HANDLE
) -> tuple[object, str]:
    options_response = await client.post(
        "/auth/native/webauthn/authentication-options",
        json={"login_handle": login_handle},
    )
    assert options_response.status_code == 200
    public_key = options_response.json()["public_key"]
    credential = authenticator.authentication_credential(
        challenge=websafe_decode(public_key["challenge"]), user_verified=True
    )
    created = await client.post(
        "/auth/native/webauthn/sessions",
        json={"login_handle": login_handle, "credential": credential},
    )
    assert created.status_code == 201
    return created, created.json()["access_token"]


def _session_row(conn: PgConnection, token: str) -> tuple[str, bool, list[str], bool]:
    session_id = parse_opaque_token(token).token_id
    row = conn.execute(
        "SELECT authentication_assurance, user_verified, authentication_methods, "
        "recovery_derived FROM request_engine.native_sessions WHERE id = %s",
        (session_id,),
    ).fetchone()
    assert row is not None
    return cast("tuple[str, bool, list[str], bool]", row)


@pytest.mark.asyncio
async def test_platform_owner_authenticates_with_passkey_and_steps_up(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    _instance(e2e_admin_conn, native_authority_id=private_runtime_configuration)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        authenticator = await _claim_owner(client)

        _, webauthn_token = await _webauthn_login(client, authenticator)
        assurance, user_verified, methods, recovery = _session_row(e2e_admin_conn, webauthn_token)
        assert assurance == "phishing_resistant"
        assert user_verified is True
        assert "webauthn" in methods
        assert recovery is False

        # The self-inspection read must agree with the independent DB oracle.
        current = await client.get(
            "/auth/native/sessions/current",
            headers={"Authorization": f"Bearer {webauthn_token}"},
        )
        assert current.status_code == 200
        assert current.headers["cache-control"] == "no-store"
        assert current.json()["authentication_assurance"] == assurance
        assert current.json()["user_verified"] == user_verified
        assert current.json()["authentication_methods"] == ["webauthn"]
        assert current.json()["recovery_derived"] is False

        password_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": LOGIN_HANDLE, "password": PASSWORD},
        )
        assert password_login.status_code == 201
        password_token = password_login.json()["access_token"]
        assert _session_row(e2e_admin_conn, password_token)[0] == "single_factor"
        password_current = await client.get(
            "/auth/native/sessions/current",
            headers={"Authorization": f"Bearer {password_token}"},
        )
        assert password_current.json()["authentication_assurance"] == "single_factor"
        assert password_current.json()["authentication_methods"] == ["password"]

        step_options = await client.post(
            "/auth/native/sessions/current/webauthn/step-up-options",
            headers={"Authorization": f"Bearer {password_token}"},
        )
        assert step_options.status_code == 200
        public_key = step_options.json()["public_key"]
        step_credential = authenticator.authentication_credential(
            challenge=websafe_decode(public_key["challenge"]), user_verified=True
        )
        stepped = await client.post(
            "/auth/native/sessions/current/webauthn/step-up",
            headers={"Authorization": f"Bearer {password_token}"},
            json={"credential": step_credential},
        )
        assert stepped.status_code == 200
        assert stepped.json()["authentication_assurance"] == "phishing_resistant"
        assert stepped.json()["user_verified"] is True
        raised = _session_row(e2e_admin_conn, password_token)
        assert raised[0] == "phishing_resistant"
        assert raised[1] is True
        assert "webauthn" in raised[2]





@pytest.mark.asyncio
async def test_current_identity_can_enroll_passkey_then_issue_offline_recovery_codes(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    _instance(e2e_admin_conn, native_authority_id=private_runtime_configuration)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        enrollment = await client.post(
            "/auth/native/identities",
            json={
                "login_handle": "second-owner-candidate@example.test",
                "password": "second owner candidate password",
            },
        )
        assert enrollment.status_code == 201
        native_identity_id = enrollment.json()["native_identity_id"]
        login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "second-owner-candidate@example.test",
                "password": "second owner candidate password",
            },
        )
        assert login.status_code == 201
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # A password-only session cannot mint offline break-glass material.
        denied = await client.post(
            "/auth/native/sessions/current/recovery-codes",
            headers=headers,
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "phishing_resistant_auth_required"

        options = (
            await client.post(
                "/auth/native/sessions/current/webauthn/registration-options",
                headers=headers,
            )
        ).json()["public_key"]
        authenticator = SoftwareAuthenticator(rp_id=options["rp"]["id"], origin=ORIGIN)
        credential = authenticator.registration_credential(
            challenge=websafe_decode(options["challenge"]), user_verified=True
        )
        registered = await client.post(
            "/auth/native/sessions/current/webauthn/registrations",
            headers=headers,
            json={"credential": credential},
        )
        assert registered.status_code == 201, registered.text

        step_options = (
            await client.post(
                "/auth/native/sessions/current/webauthn/step-up-options",
                headers=headers,
            )
        ).json()["public_key"]
        assertion = authenticator.authentication_credential(
            challenge=websafe_decode(step_options["challenge"]), user_verified=True
        )
        stepped = await client.post(
            "/auth/native/sessions/current/webauthn/step-up",
            headers=headers,
            json={"credential": assertion},
        )
        assert stepped.status_code == 200
        assert stepped.json()["authentication_assurance"] == "phishing_resistant"

        issued = await client.post(
            "/auth/native/sessions/current/recovery-codes",
            headers=headers,
        )
        assert issued.status_code == 201, issued.text
        codes = issued.json()["codes"]
        assert len(codes) == 10
        assert all(isinstance(code, str) and len(code) >= 16 for code in codes)

        summary = e2e_admin_conn.execute(
            "SELECT status, native_identity_id FROM request_engine.recovery_code_sets "
            "WHERE native_identity_id = %s ORDER BY version DESC LIMIT 1",
            (UUID(native_identity_id),),
        ).fetchone()
        assert summary == ("active", UUID(native_identity_id))


@pytest.mark.asyncio
async def test_webauthn_challenge_is_single_use(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    _instance(e2e_admin_conn, native_authority_id=private_runtime_configuration)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        authenticator = await _claim_owner(client)
        options = (
            await client.post(
                "/auth/native/webauthn/authentication-options",
                json={"login_handle": LOGIN_HANDLE},
            )
        ).json()["public_key"]
        credential = authenticator.authentication_credential(
            challenge=websafe_decode(options["challenge"]), user_verified=True
        )
        first = await client.post(
            "/auth/native/webauthn/sessions",
            json={"login_handle": LOGIN_HANDLE, "credential": credential},
        )
        assert first.status_code == 201
        replay = await client.post(
            "/auth/native/webauthn/sessions",
            json={"login_handle": LOGIN_HANDLE, "credential": credential},
        )
        assert replay.status_code == 401


@pytest.mark.asyncio
async def test_step_up_challenge_is_bound_to_the_session(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    _instance(e2e_admin_conn, native_authority_id=private_runtime_configuration)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        authenticator = await _claim_owner(client)
        session_a = (
            await client.post(
                "/auth/native/sessions",
                json={"login_handle": LOGIN_HANDLE, "password": PASSWORD},
            )
        ).json()["access_token"]
        session_b = (
            await client.post(
                "/auth/native/sessions",
                json={"login_handle": LOGIN_HANDLE, "password": PASSWORD},
            )
        ).json()["access_token"]

        options = (
            await client.post(
                "/auth/native/sessions/current/webauthn/step-up-options",
                headers={"Authorization": f"Bearer {session_a}"},
            )
        ).json()["public_key"]
        credential = authenticator.authentication_credential(
            challenge=websafe_decode(options["challenge"]), user_verified=True
        )
        # Session B cannot complete session A's step-up challenge.
        mismatched = await client.post(
            "/auth/native/sessions/current/webauthn/step-up",
            headers={"Authorization": f"Bearer {session_b}"},
            json={"credential": credential},
        )
        assert mismatched.status_code == 401
        # The owning session still completes it.
        completed = await client.post(
            "/auth/native/sessions/current/webauthn/step-up",
            headers={"Authorization": f"Bearer {session_a}"},
            json={"credential": credential},
        )
        assert completed.status_code == 200
        assert completed.json()["authentication_assurance"] == "phishing_resistant"


@pytest.mark.asyncio
async def test_authentication_options_do_not_reveal_unknown_handles(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    _instance(e2e_admin_conn, native_authority_id=private_runtime_configuration)
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        authenticator = await _claim_owner(client)
        known = (
            await client.post(
                "/auth/native/webauthn/authentication-options",
                json={"login_handle": LOGIN_HANDLE},
            )
        ).json()["public_key"]
        unknown_response = await client.post(
            "/auth/native/webauthn/authentication-options",
            json={"login_handle": "does-not-exist@example.test"},
        )
        assert unknown_response.status_code == 200
        unknown = unknown_response.json()["public_key"]
        assert set(known) == set(unknown)
        assert len(known["allowCredentials"]) == 1
        assert len(unknown["allowCredentials"]) == 1
        known_credential_id = known["allowCredentials"][0]["id"]
        unknown_credential_id = unknown["allowCredentials"][0]["id"]
        assert unknown_credential_id != known_credential_id

        # A real assertion under an unknown handle fails closed and opaquely.
        forged = authenticator.authentication_credential(
            challenge=websafe_decode(unknown["challenge"]), user_verified=True
        )
        rejected = await client.post(
            "/auth/native/webauthn/sessions",
            json={"login_handle": "does-not-exist@example.test", "credential": forged},
        )
        assert rejected.status_code == 401
