"""Black-box HTTP Instance Claim journey (ADR 0014 P4).

Drives the real control-plane ASGI app over a fresh instance: create a bounded
SetupSession, record the pending owner identity, complete a real WebAuthn
registration with genuine crypto, issue recovery codes and atomically finalize
the claim. It then proves setup is permanently closed and exact finalize replay
returns the same non-secret result without redisplaying recovery codes.
"""

from uuid import UUID, uuid4

import pytest
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.bootstrap.platform_server import create_app
from request_engine.platform.db.session import SessionFactory

from .conftest import PgConnection, RuntimeCredentials

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security]

ORIGIN = "https://localhost"
LOGIN_HANDLE = "http-owner@example.test"
PASSWORD = "http claim owner password"


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
        (authority_id, f"instance-setup-http-{authority_id}"),
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
    return authority_id


def _instance(e2e_admin_conn: PgConnection, *, native_authority_id: UUID) -> tuple[UUID, UUID]:
    instance_id = uuid4()
    workload_authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id, built_in_native_authority_id, built_in_workload_authority_id) "
        "VALUES (%s, %s, %s)",
        (instance_id, native_authority_id, workload_authority_id),
    )
    return instance_id, workload_authority_id


@pytest.mark.asyncio
async def test_fresh_instance_is_claimed_over_http_and_setup_closes(
    private_runtime_configuration: UUID,
    e2e_admin_conn: PgConnection,
) -> None:
    instance_id, workload_authority_id = _instance(
        e2e_admin_conn, native_authority_id=private_runtime_configuration
    )
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="https://private-control.test"
        ) as client,
    ):
        assert (await client.get("/health/ready")).json() == {"status": "ready"}
        assert (await client.get("/v1/setup")).json() == {"setup_required": True}
        anonymous = await client.post(
            "/v1/setup/native-identity",
            json={"login_handle": "anonymous@example.test", "password": "anonymous password"},
        )
        assert anonymous.status_code == 401

        created = await client.post("/v1/setup/sessions")
        assert created.status_code == 201
        issued = created.json()
        assert UUID(issued["setup_session_id"])
        setup_headers = {"Authorization": f"Setup {issued['token']}"}

        enrolled = await client.post(
            "/v1/setup/native-identity",
            headers=setup_headers,
            json={"login_handle": LOGIN_HANDLE, "password": PASSWORD},
        )
        assert enrolled.status_code == 204

        options_response = await client.post(
            "/v1/setup/webauthn/registration-options", headers=setup_headers
        )
        assert options_response.status_code == 200
        public_key = options_response.json()["public_key"]
        rp_id = public_key["rp"]["id"]
        authenticator = SoftwareAuthenticator(rp_id=rp_id, origin=ORIGIN)
        credential = authenticator.registration_credential(
            challenge=websafe_decode(public_key["challenge"]), user_verified=True
        )
        registered = await client.post(
            "/v1/setup/webauthn/registrations",
            headers=setup_headers,
            json={"credential": credential},
        )
        assert registered.status_code == 204

        codes_response = await client.post("/v1/setup/recovery-codes", headers=setup_headers)
        assert codes_response.status_code == 201
        codes = codes_response.json()["codes"]
        assert len(codes) == 10 and len(set(codes)) == 10

        finalize_headers = {**setup_headers, "Idempotency-Key": "claim-e2e-1"}
        finalized = await client.post(
            "/v1/setup:finalize",
            headers=finalize_headers,
            json={"claim_provenance": "e2e:instance-setup-http"},
        )
        assert finalized.status_code == 201
        result = finalized.json()
        assert UUID(result["instance_id"]) == instance_id
        assert result["policy_key"] == "platform-owner-v1"
        assert UUID(result["built_in_native_authority_id"]) == private_runtime_configuration
        assert UUID(result["built_in_workload_authority_id"]) == workload_authority_id
        assert "codes" not in result

        replayed = await client.post(
            "/v1/setup:finalize",
            headers=finalize_headers,
            json={"claim_provenance": "e2e:instance-setup-http"},
        )
        assert replayed.status_code == 201
        assert replayed.json() == result

        # Reusing the key with different request content is a conflict, not a
        # foreign receipt: the request fingerprint must match.
        conflicting = await client.post(
            "/v1/setup:finalize",
            headers=finalize_headers,
            json={"claim_provenance": "e2e:different-provenance"},
        )
        assert conflicting.status_code == 409

        assert (await client.get("/v1/setup")).json() == {"setup_required": False}
        assert (await client.post("/v1/setup/sessions")).status_code == 409

    owner_principal_id = UUID(result["owner_principal_id"])
    grants = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id = %s AND principal_plane = 'platform'",
        (owner_principal_id,),
    ).fetchone()
    assert grants is not None and grants[0] == 9


@pytest.mark.asyncio
async def test_webauthn_registration_rejects_another_setup_session(
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
        issued_a = (await client.post("/v1/setup/sessions")).json()
        issued_b = (await client.post("/v1/setup/sessions")).json()
        headers_a = {"Authorization": f"Setup {issued_a['token']}"}
        headers_b = {"Authorization": f"Setup {issued_b['token']}"}

        options_response = await client.post(
            "/v1/setup/webauthn/registration-options", headers=headers_a
        )
        assert options_response.status_code == 200
        public_key = options_response.json()["public_key"]
        authenticator = SoftwareAuthenticator(rp_id=public_key["rp"]["id"], origin=ORIGIN)
        credential = authenticator.registration_credential(
            challenge=websafe_decode(public_key["challenge"]), user_verified=True
        )

        # A valid bearer for another concurrent ceremony cannot complete this one.
        mismatched = await client.post(
            "/v1/setup/webauthn/registrations",
            headers=headers_b,
            json={"credential": credential},
        )
        assert mismatched.status_code == 409

        # The owning session still completes it: the rejected attempt did not
        # consume the challenge or create a pending credential.
        registered = await client.post(
            "/v1/setup/webauthn/registrations",
            headers=headers_a,
            json={"credential": credential},
        )
        assert registered.status_code == 204

    pending = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.setup_pending_webauthn_credential "
        "WHERE setup_session_id = %s AND status = 'pending'",
        (UUID(issued_a["setup_session_id"]),),
    ).fetchone()
    assert pending is not None and pending[0] == 1
