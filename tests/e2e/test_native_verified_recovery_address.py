"""Universal Native HUMAN verified-address recovery over real HTTP/PostgreSQL."""

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.bootstrap.native_recovery_delivery_worker import (
    build_native_recovery_delivery_worker,
)
from request_engine.entrypoints.http.app import create_native_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    StagedRecoverySecret,
)
from request_engine.platform.security.webauthn import WebAuthnPolicy
from request_engine.platform.worker.runtime import WorkerItemState

from .conftest import PgConnection

pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security]


class RecordingRecoveryMessenger:
    def __init__(self) -> None:
        self.verifications: list[tuple[str, str]] = []
        self.recoveries: list[tuple[str, str]] = []

    async def send_verification(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        del idempotency_key
        self.verifications.append((secret, destination_reference))
        return DeliveryOutcome.DELIVERED

    async def send_recovery(
        self,
        *,
        secret: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        del idempotency_key
        self.recoveries.append((secret, destination_reference))
        return DeliveryOutcome.DELIVERED


class MemoryRecoverySecretDelivery:
    def __init__(self) -> None:
        self.secrets: dict[str, tuple[str, datetime]] = {}
        self.published: list[tuple[str, str, str]] = []

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        reference = f"memory://native-recovery/{case_id}/{generation}"
        existing = self.secrets.get(reference)
        if existing is not None:
            retained, retained_expiry = existing
            return StagedRecoverySecret(
                reference=reference,
                digest=hashlib.sha256(retained.encode()).hexdigest(),
                expires_at=retained_expiry,
                created=False,
            )
        self.secrets[reference] = (secret, expires_at)
        return StagedRecoverySecret(
            reference=reference,
            digest=hashlib.sha256(secret.encode()).hexdigest(),
            expires_at=expires_at,
            created=True,
        )

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.secrets.pop(f"memory://native-recovery/{case_id}/{generation}", None)

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        secret, _ = self.secrets[reference]
        self.published.append((secret, destination_reference, idempotency_key))
        return DeliveryOutcome.DELIVERED

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None:
        del reference, idempotency_key
        return None


async def _strong_session(
    client: AsyncClient,
    *,
    login_handle: str,
    password: str,
    origin: str,
) -> tuple[str, SoftwareAuthenticator]:
    logged_in = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert logged_in.status_code == 201, logged_in.text
    token = logged_in.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    options_response = await client.post(
        "/auth/native/sessions/current/webauthn/registration-options",
        headers=headers,
    )
    assert options_response.status_code == 200, options_response.text
    options = options_response.json()["public_key"]
    authenticator = SoftwareAuthenticator(
        rp_id=options["rp"]["id"],
        origin=origin,
    )
    registration = authenticator.registration_credential(
        challenge=websafe_decode(options["challenge"]),
        user_verified=True,
    )
    registered = await client.post(
        "/auth/native/sessions/current/webauthn/registrations",
        headers=headers,
        json={"credential": registration},
    )
    assert registered.status_code == 201, registered.text

    step_options_response = await client.post(
        "/auth/native/sessions/current/webauthn/step-up-options",
        headers=headers,
    )
    assert step_options_response.status_code == 200, step_options_response.text
    step_options = step_options_response.json()["public_key"]
    assertion = authenticator.authentication_credential(
        challenge=websafe_decode(step_options["challenge"]),
        user_verified=True,
    )
    stepped = await client.post(
        "/auth/native/sessions/current/webauthn/step-up",
        headers=headers,
        json={"credential": assertion},
    )
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["authentication_assurance"] == "phishing_resistant"
    return token, authenticator


@pytest.mark.asyncio
async def test_verified_recovery_address_is_self_service_anti_enumerating_and_restricted(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    e2e_worker_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment) "
        "VALUES (%s, 'native', %s)",
        (authority_id, f"verified-recovery-{uuid4().hex}"),
    )
    origin = "https://verified-recovery.test"
    messenger = RecordingRecoveryMessenger()
    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"verified-recovery-signing-key-0001",
        webauthn_policy=WebAuthnPolicy(
            rp_id="verified-recovery.test",
            rp_name="Request Engine",
            allowed_origins=frozenset({origin}),
        ),
        webauthn_decoy_key=b"v" * 64,
        native_recovery_messenger=messenger,
    )
    login_handle = f"verified-{uuid4().hex}@example.test"
    recovery_email = f"backup-{uuid4().hex}@example.test"
    old_password = "verified recovery original password"
    new_password = "verified recovery replacement password"

    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": login_handle, "password": old_password},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])

        weak_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": login_handle, "password": old_password},
        )
        assert weak_login.status_code == 201
        weak_headers = {"Authorization": f"Bearer {weak_login.json()['access_token']}"}
        weak_add = await client.post(
            "/auth/native/sessions/current/recovery-addresses",
            headers=weak_headers,
            json={"email": recovery_email},
        )
        assert weak_add.status_code == 403
        assert weak_add.json()["error"]["code"] == "phishing_resistant_auth_required"

        strong_token, _authenticator = await _strong_session(
            client,
            login_handle=login_handle,
            password=old_password,
            origin=origin,
        )
        strong_headers = {"Authorization": f"Bearer {strong_token}"}
        prepared = await client.post(
            "/auth/native/sessions/current/recovery-addresses",
            headers=strong_headers,
            json={"email": recovery_email},
        )
        assert prepared.status_code == 202, prepared.text
        assert prepared.json()["status"] == "pending"
        assert prepared.json()["verification_created"] is True
        assert len(messenger.verifications) == 1
        verification_secret, delivered_address = messenger.verifications[0]
        assert delivered_address == recovery_email

        verified = await client.post(
            "/auth/native/recovery-addresses:verify",
            json={"verification_token": verification_secret},
        )
        assert verified.status_code == 204, verified.text
        replay = await client.post(
            "/auth/native/recovery-addresses:verify",
            json={"verification_token": verification_secret},
        )
        assert replay.status_code == 401

        addresses = await client.get(
            "/auth/native/sessions/current/recovery-addresses",
            headers=strong_headers,
        )
        assert addresses.status_code == 200, addresses.text
        assert addresses.json()[0]["address"] == recovery_email
        assert addresses.json()[0]["status"] == "verified"

        requested = await client.post(
            "/auth/native/password:request-recovery",
            json={"login_handle": login_handle},
        )
        unknown = await client.post(
            "/auth/native/password:request-recovery",
            json={"login_handle": f"missing-{uuid4().hex}@example.test"},
        )
        throttled = await client.post(
            "/auth/native/password:request-recovery",
            json={"login_handle": login_handle},
        )
        assert requested.status_code == unknown.status_code == throttled.status_code == 202
        assert requested.content == unknown.content == throttled.content == b""
        assert messenger.recoveries == []

        queued = e2e_admin_conn.execute(
            """
            SELECT status, recovery_intent_id, secret_reference
              FROM request_engine.native_recovery_delivery_requests
             WHERE native_identity_id = %s
            """,
            (identity_id,),
        ).fetchall()
        assert queued == [("pending", None, None)]

        delivery = MemoryRecoverySecretDelivery()
        worker = build_native_recovery_delivery_worker(
            e2e_worker_session_factory,
            delivery,
        )
        outcomes = await worker.run_once()
        assert len(outcomes) == 1
        assert outcomes[0].state is WorkerItemState.COMPLETED
        assert len(delivery.published) == 1
        recovery_secret, recovery_destination, idempotency_key = delivery.published[0]
        assert recovery_destination == recovery_email
        assert idempotency_key.startswith("native-recovery:")

        delivered = e2e_admin_conn.execute(
            """
            SELECT status, recovery_intent_id IS NOT NULL, secret_reference IS NOT NULL
              FROM request_engine.native_recovery_delivery_requests
             WHERE native_identity_id = %s
            """,
            (identity_id,),
        ).fetchone()
        assert delivered == ("delivered", True, True)

        recovered = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": recovery_secret, "new_password": new_password},
        )
        assert recovered.status_code == 204, recovered.text

        old_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": login_handle, "password": old_password},
        )
        assert old_login.status_code == 401
        new_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": login_handle, "password": new_password},
        )
        assert new_login.status_code == 201, new_login.text
        recovered_headers = {"Authorization": f"Bearer {new_login.json()['access_token']}"}
        current = await client.get(
            "/auth/native/sessions/current",
            headers=recovered_headers,
        )
        assert current.status_code == 200
        assert current.json()["recovery_restricted"] is True

    # Recovery changes identity security posture only. It never synthesizes authority.
    assert e2e_admin_conn.execute(
        "SELECT state, recovery_epoch, last_recovery_method "
        "FROM request_engine.native_identity_recovery_state "
        "WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchone() == ("recovery_restricted", 1, "delivered_recovery_proof")
    assert e2e_admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (
        0,
    )
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_bindings"
    ).fetchone() == (0,)
