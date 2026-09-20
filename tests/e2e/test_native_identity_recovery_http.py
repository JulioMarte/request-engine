"""Governed identity recovery over the private HTTP control plane.

Production-like journey for the accepted recovery contract: double-control
approval, staging/publishing through a test secret-delivery adapter, the real
fenced delivery worker, one-time consumption, revocation and fail-closed
boundaries. Real PostgreSQL 18, real ASGI HTTP and the real worker runtime;
direct SQL only builds valid preconditions and inspects durable state.
"""

import hashlib
import json
import os
import smtplib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.bootstrap.recovery_delivery_worker import build_recovery_delivery_worker
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.secrets.composed_delivery import ComposedRecoverySecretDelivery
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoverySecretDelivery,
    StagedRecoverySecret,
)
from request_engine.platform.secrets.smtp_delivery_channel import SmtpRecoveryDeliveryChannel
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore
from request_engine.platform.security.native_auth import hash_password
from request_engine.platform.security.webauthn import WebAuthnPolicy
from request_engine.platform.worker.runtime import WorkerRuntimeConfig

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_CASES_PATH = "/v1/platform/identity-recovery-cases"
_CASE_VIEW_FIELDS = frozenset(
    {
        "case_id",
        "target_native_identity_id",
        "status",
        "delivery_status",
        "revision",
        "issuance_generation",
        "approval_expires_at",
        "proof_expires_at",
        "created_at",
        "approved_at",
        "issued_at",
        "consumed_at",
        "revoked_at",
    }
)


class FakeRecoverySecretDelivery(RecoverySecretDelivery):
    """Create-if-absent staging plus recorded, idempotent publication."""

    def __init__(self, *, outcome: DeliveryOutcome = DeliveryOutcome.DELIVERED) -> None:
        self.outcome = outcome
        self.staged: dict[tuple[UUID, int], tuple[StagedRecoverySecret, str]] = {}
        self.publish_calls: list[tuple[str, str, str]] = []
        self.published_outcomes: dict[str, DeliveryOutcome] = {}

    async def stage(
        self,
        *,
        case_id: UUID,
        generation: int,
        secret: str,
        expires_at: datetime,
    ) -> StagedRecoverySecret:
        key = (case_id, generation)
        existing = self.staged.get(key)
        if existing is not None:
            return replace(existing[0], created=False)
        staged = StagedRecoverySecret(
            reference=f"test://{case_id}/{generation}",
            digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
            created=True,
        )
        self.staged[key] = (staged, secret)
        return staged

    async def discard(self, *, case_id: UUID, generation: int) -> None:
        self.staged.pop((case_id, generation), None)

    async def publish(
        self,
        *,
        reference: str,
        destination_reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome:
        self.publish_calls.append((reference, destination_reference, idempotency_key))
        self.published_outcomes[idempotency_key] = self.outcome
        return self.outcome

    async def reconcile(
        self,
        *,
        reference: str,
        idempotency_key: str,
    ) -> DeliveryOutcome | None:
        return self.published_outcomes.get(idempotency_key)

    def staged_secret(self, case_id: UUID, generation: int = 1) -> str:
        return self.staged[(case_id, generation)][1]


@dataclass(frozen=True, slots=True)
class _PlatformHuman:
    identity_id: UUID
    principal_id: UUID
    login_handle: str
    password: str


@dataclass(frozen=True, slots=True)
class _RecoveryTarget:
    identity_id: UUID
    login_handle: str
    password: str


def _bootstrap_root(
    admin_conn: PgConnection,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provenance: str,
) -> tuple[UUID, UUID, str, str]:
    monkeypatch.setenv(
        "REQUEST_ENGINE_BOOTSTRAP_DSN",
        make_conninfo(
            host=admin_conn.info.host,
            port=admin_conn.info.port,
            dbname=admin_conn.info.dbname,
            user=admin_conn.info.user,
            password=os.environ.get("PGPASSWORD", "request_engine"),
        ),
    )
    intent = dict(
        line.split(": ", 1)
        for line in issue_intent(ttl_minutes=5, provenance=provenance).splitlines()
    )
    authority_id = UUID(intent["Native authority"])
    login_handle = f"recovery-root-{uuid4().hex}@example.test"
    password = "root identity recovery proof password"
    root_id = establish_root(
        login_handle=login_handle,
        password=password,
        raw_token=intent["ONE-TIME BOOTSTRAP TOKEN"],
    )
    return authority_id, root_id, login_handle, password


def _insert_platform_human(
    conn: PgConnection,
    *,
    authority_id: UUID,
    capabilities: tuple[str, ...],
    login_handle: str | None = None,
    password: str | None = None,
) -> _PlatformHuman:
    identity_id = uuid4()
    principal_id = uuid4()
    handle = login_handle or f"recovery-operator-{uuid4().hex}@example.test"
    secret = password or "operator identity recovery proof password"
    conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, handle),
    )
    conn.execute(
        "INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier) "
        "VALUES (%s, %s, %s)",
        (uuid4(), identity_id, hash_password(secret)),
    )
    conn.execute(
        "INSERT INTO request_engine.principals "
        "(id, principal_plane, principal_kind, external_subject) "
        "VALUES (%s, 'platform', 'human', %s)",
        (principal_id, f"native:{identity_id}"),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings "
        "(id, principal_id, principal_plane, identity_authority_id, subject_id, status) "
        "VALUES (%s, %s, 'platform', %s, %s, 'active')",
        (uuid4(), principal_id, authority_id, str(identity_id)),
    )
    for capability in capabilities:
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants "
            "(principal_id, principal_plane, authority_plane, capability_key, delegable, "
            "provenance_kind, provenance_reference) "
            "VALUES (%s, 'platform', 'platform', %s, false, 'trust_bootstrap', %s)",
            (principal_id, capability, f"recovery-http-proof:{uuid4().hex}"),
        )
    return _PlatformHuman(identity_id, principal_id, handle, secret)


def _insert_target_identity(
    conn: PgConnection,
    *,
    authority_id: UUID,
    login_handle: str | None = None,
    password: str | None = None,
) -> _RecoveryTarget:
    identity_id = uuid4()
    handle = login_handle or f"recovery-target-{uuid4().hex}@example.test"
    secret = password or "original identity recovery proof password"
    conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, handle),
    )
    conn.execute(
        "INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier) "
        "VALUES (%s, %s, %s)",
        (uuid4(), identity_id, hash_password(secret)),
    )
    return _RecoveryTarget(identity_id, handle, secret)


def _control_app(
    *,
    authority_id: UUID,
    auth_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_write_session_factory: SessionFactory,
    delivery: RecoverySecretDelivery | None,
) -> FastAPI:
    return create_platform_control_app(
        auth_session_factory=auth_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_write_session_factory,
        native_authority_id=authority_id,
        recovery_delivery=delivery,
        webauthn_policy=WebAuthnPolicy(
            rp_id="control.test",
            rp_name="Request Engine recovery E2E",
            allowed_origins=frozenset({"https://control.test"}),
        ),
        webauthn_decoy_key=b"recovery-control-e2e-decoy-key-" + b"x" * 32,
    )


async def _login(client: AsyncClient, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


async def _bearer_headers(
    client: AsyncClient,
    login_handle: str,
    password: str,
) -> dict[str, str]:
    token = await _login(client, login_handle, password)
    headers = {"Authorization": f"Bearer {token}"}
    options = (
        await client.post(
            "/auth/native/sessions/current/webauthn/registration-options",
            headers=headers,
        )
    ).json()["public_key"]
    authenticator = SoftwareAuthenticator(
        rp_id=options["rp"]["id"],
        origin="https://control.test",
    )
    credential = authenticator.registration_credential(
        challenge=websafe_decode(options["challenge"]),
        user_verified=True,
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
    return headers


def _case_state(conn: PgConnection, case_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, delivery_status, revision, issuance_generation, recovery_intent_id "
        "FROM request_engine.identity_recovery_cases WHERE id = %s",
        (case_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


def _ticket_state(conn: PgConnection, case_id: UUID) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT generation, status, secret_reference, secret_digest, destination_reference "
        "FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchone()
    assert row is not None
    return tuple(row)


@pytest_asyncio.fixture
async def recovery_worker_session_factory(
    e2e_admin_conn: PgConnection,
) -> AsyncIterator[SessionFactory]:
    """Ephemeral release-shaped worker LOGIN for the real fenced runtime."""

    role_name = f"re_recovery_worker_{uuid4().hex[:10]}"
    role_password = uuid4().hex
    e2e_admin_conn.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE request_engine_worker").format(
            sql.Identifier(role_name), sql.Literal(role_password)
        )
    )
    info = e2e_admin_conn.info
    engine = create_postgres_engine(
        f"postgresql+asyncpg://{role_name}:{role_password}@{info.host}:{info.port}/{info.dbname}"
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        e2e_admin_conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role_name)))


@pytest.mark.asyncio
async def test_governed_identity_recovery_http_journey_issues_delivers_and_consumes(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    recovery_worker_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, root_id, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-journey",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    fake = FakeRecoverySecretDelivery()
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=fake,
    )
    create_body = {
        "target_native_identity_id": str(target.identity_id),
        "reason_code": "lost_credential",
        "evidence_reference": "case-ref-7f3a",
        "delivery_destination_reference": "channel-ref-9c1b",
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)

        created = await client.post(
            _CASES_PATH,
            headers={**root_headers, "Idempotency-Key": "recovery-create-1"},
            json=create_body,
        )
        assert created.status_code == 201, created.text
        assert created.headers["Cache-Control"] == "no-store"
        assert set(created.json()) == _CASE_VIEW_FIELDS
        assert created.json()["status"] == "requested"
        assert created.json()["delivery_status"] == "pending"
        assert created.json()["revision"] == 1
        case_id = UUID(created.json()["case_id"])
        assert _case_state(e2e_admin_conn, case_id) == (
            "requested",
            "pending",
            1,
            0,
            None,
        )

        # An unaccepted reason_code is a bounded input error, never a server fault.
        invalid_reason = await client.post(
            _CASES_PATH,
            headers={**root_headers, "Idempotency-Key": "recovery-create-invalid-reason"},
            json={**create_body, "reason_code": "not_an_accepted_reason"},
        )
        assert invalid_reason.status_code == 422, invalid_reason.text
        assert invalid_reason.json()["error"]["code"] == "platform_identity_recovery_invalid"

        # The requester cannot approve their own case, even with the capability.
        self_approve = await client.post(
            f"{_CASES_PATH}/{case_id}:approve",
            headers={**root_headers, "Idempotency-Key": "recovery-approve-self"},
            json={"expected_revision": 1, "reason_code": "ownership_verified"},
        )
        assert self_approve.status_code == 403, self_approve.text
        assert self_approve.json()["error"]["code"] == "platform_identity_recovery_forbidden"
        assert _case_state(e2e_admin_conn, case_id)[0] == "requested"

        approved = await client.post(
            f"{_CASES_PATH}/{case_id}:approve",
            headers={**approver_headers, "Idempotency-Key": "recovery-approve-1"},
            json={"expected_revision": 1, "reason_code": "ownership_verified"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        assert approved.json()["revision"] == 2
        assert approved.json()["approved_at"] is not None
        assert _case_state(e2e_admin_conn, case_id) == ("approved", "pending", 2, 0, None)

        # The approver lacks platform.identity.recover and cannot request a case.
        denied_create = await client.post(
            _CASES_PATH,
            headers={**approver_headers, "Idempotency-Key": "recovery-approver-create"},
            json=create_body,
        )
        assert denied_create.status_code == 403, denied_create.text
        assert denied_create.json()["error"]["code"] == "platform_identity_recovery_forbidden"

        issue_headers = {**root_headers, "Idempotency-Key": "recovery-issue-1"}
        issue_body = {"expected_revision": 2}
        issued = await client.post(
            f"{_CASES_PATH}/{case_id}:issue", headers=issue_headers, json=issue_body
        )
        assert issued.status_code == 202, issued.text
        assert issued.headers["Cache-Control"] == "no-store"
        assert issued.json()["status"] == "issued"
        assert issued.json()["delivery_status"] == "pending"
        assert issued.json()["revision"] == 3
        assert issued.json()["issuance_generation"] == 1
        assert issued.json()["proof_expires_at"] is not None
        raw_proof = fake.staged_secret(case_id)
        staged = fake.staged[(case_id, 1)][0]
        assert raw_proof not in issued.text
        assert staged.reference not in issued.text
        assert staged.digest not in issued.text
        assert fake.publish_calls == []

        state = _case_state(e2e_admin_conn, case_id)
        assert state[:4] == ("issued", "pending", 3, 1)
        intent_id = UUID(str(state[4]))
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
            (intent_id,),
        ).fetchone() == ("pending",)
        assert _ticket_state(e2e_admin_conn, case_id) == (
            1,
            "pending",
            staged.reference,
            staged.digest,
            "channel-ref-9c1b",
        )

        # Replaying the same issuance intent returns the same case and stages nothing new.
        replay = await client.post(
            f"{_CASES_PATH}/{case_id}:issue", headers=issue_headers, json=issue_body
        )
        assert replay.status_code == 202, replay.text
        assert replay.json() == issued.json()
        assert len(fake.staged) == 1
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.identity_recovery_delivery_tickets "
            "WHERE case_id = %s",
            (case_id,),
        ).fetchone() == (1,)

        listing = await client.get(_CASES_PATH, headers=approver_headers)
        assert listing.status_code == 200, listing.text
        assert listing.headers["Cache-Control"] == "no-store"
        assert [item["case_id"] for item in listing.json()["items"]] == [str(case_id)]
        assert listing.json()["next_after"] is None
        assert raw_proof not in listing.text

        detail = await client.get(f"{_CASES_PATH}/{case_id}", headers=approver_headers)
        assert detail.status_code == 200, detail.text
        assert detail.headers["Cache-Control"] == "no-store"
        assert detail.json() == issued.json()
        assert raw_proof not in detail.text

        ticket_row = e2e_admin_conn.execute(
            "SELECT id FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
            (case_id,),
        ).fetchone()
        assert ticket_row is not None
        ticket_id = UUID(str(ticket_row[0]))
        runtime = build_recovery_delivery_worker(recovery_worker_session_factory, fake)
        outcomes = await runtime.run_once()
        assert [outcome.work_id for outcome in outcomes] == [ticket_id]
        assert [outcome.state.value for outcome in outcomes] == ["completed"]
        assert fake.publish_calls == [(staged.reference, "channel-ref-9c1b", f"{case_id}:1")]
        assert e2e_admin_conn.execute(
            "SELECT status, delivered_at IS NOT NULL "
            "FROM request_engine.identity_recovery_delivery_tickets WHERE id = %s",
            (ticket_id,),
        ).fetchone() == ("delivered", True)
        assert _case_state(e2e_admin_conn, case_id)[:3] == ("issued", "delivered", 5)

        new_password = "replacement identity recovery proof password"
        recovered = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": raw_proof, "new_password": new_password},
        )
        assert recovered.status_code == 204, recovered.text
        assert recovered.content == b""
        assert recovered.headers["Cache-Control"] == "no-store"
        replay_consume = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": raw_proof, "new_password": new_password},
        )
        assert replay_consume.status_code == 401
        assert replay_consume.json()["error"]["code"] == "recovery_intent_invalid"

        old_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": target.password},
        )
        assert old_login.status_code == 401
        assert old_login.json()["error"]["code"] == "credential_invalid"
        new_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": new_password},
        )
        assert new_login.status_code == 201, new_login.text

        assert e2e_admin_conn.execute(
            "SELECT status, count(*) FROM request_engine.native_credentials "
            "WHERE native_identity_id = %s GROUP BY status ORDER BY status",
            (target.identity_id,),
        ).fetchall() == [("active", 1), ("revoked", 1)]

    assert _case_state(e2e_admin_conn, case_id) == ("consumed", "delivered", 6, 1, intent_id)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
        (intent_id,),
    ).fetchone() == ("consumed",)
    # The raw proof never entered any authoritative recovery row.
    leaked = e2e_admin_conn.execute(
        """
        SELECT count(*) FROM (
            SELECT row_to_json(c) AS payload
              FROM request_engine.identity_recovery_cases AS c
            UNION ALL
            SELECT row_to_json(t)
              FROM request_engine.identity_recovery_delivery_tickets AS t
            UNION ALL
            SELECT row_to_json(f)
              FROM request_engine.platform_identity_recovery_facts AS f
            UNION ALL
            SELECT row_to_json(i)
              FROM request_engine.native_recovery_intents AS i
        ) AS rows
        WHERE rows.payload::text LIKE %s
        """,
        (f"%{raw_proof}%",),
    ).fetchone()
    assert leaked == (0,)
    facts = e2e_admin_conn.execute(
        "SELECT action, actor_principal_id FROM request_engine.platform_identity_recovery_facts "
        "WHERE case_id = %s ORDER BY created_at, id",
        (case_id,),
    ).fetchall()
    assert [fact[0] for fact in facts] == ["request", "approve", "issue", "deliver", "consume"]
    assert facts[0][1] == root_id
    assert facts[1][1] == approver.principal_id


@pytest.mark.asyncio
async def test_identity_recovery_revoke_terminates_staged_proof(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-revoke",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    fake = FakeRecoverySecretDelivery()
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=fake,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        created = await client.post(
            _CASES_PATH,
            headers={**root_headers, "Idempotency-Key": "recovery-revoke-create-1"},
            json={
                "target_native_identity_id": str(target.identity_id),
                "reason_code": "lost_credential",
                "evidence_reference": "case-ref-revoke",
                "delivery_destination_reference": "channel-ref-revoke",
            },
        )
        assert created.status_code == 201, created.text
        case_id = UUID(created.json()["case_id"])
        approved = await client.post(
            f"{_CASES_PATH}/{case_id}:approve",
            headers={**approver_headers, "Idempotency-Key": "recovery-revoke-approve-1"},
            json={"expected_revision": 1, "reason_code": "ownership_verified"},
        )
        assert approved.status_code == 200, approved.text
        issued = await client.post(
            f"{_CASES_PATH}/{case_id}:issue",
            headers={**root_headers, "Idempotency-Key": "recovery-revoke-issue-1"},
            json={"expected_revision": 2},
        )
        assert issued.status_code == 202, issued.text
        raw_proof = fake.staged_secret(case_id)
        issued_state = _case_state(e2e_admin_conn, case_id)
        assert issued_state[:4] == ("issued", "pending", 3, 1)
        intent_id = UUID(str(issued_state[4]))

        revoked = await client.post(
            f"{_CASES_PATH}/{case_id}:revoke",
            headers={**root_headers, "Idempotency-Key": "recovery-revoke-1"},
            json={"expected_revision": 3, "reason_code": "security_investigation"},
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
        assert revoked.json()["revision"] == 4
        assert revoked.json()["revoked_at"] is not None

        denied = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": raw_proof, "new_password": "must not be installed at all"},
        )
        assert denied.status_code == 401, denied.text
        assert denied.json()["error"]["code"] == "recovery_intent_invalid"

        # A different key is required: the same key would replay the successful revoke.
        second_revoke = await client.post(
            f"{_CASES_PATH}/{case_id}:revoke",
            headers={**root_headers, "Idempotency-Key": "recovery-revoke-2"},
            json={"expected_revision": 4, "reason_code": "request_withdrawn"},
        )
        assert second_revoke.status_code == 409, second_revoke.text
        assert second_revoke.json()["error"]["code"] == "platform_identity_recovery_conflict"

        # Revocation kills the proof but does not rotate the existing credential.
        still_valid = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": target.password},
        )
        assert still_valid.status_code == 201, still_valid.text

    assert _case_state(e2e_admin_conn, case_id) == ("revoked", "pending", 4, 1, intent_id)
    assert e2e_admin_conn.execute(
        "SELECT revoke_reason_code FROM request_engine.identity_recovery_cases WHERE id = %s",
        (case_id,),
    ).fetchone() == ("security_investigation",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchone() == ("cancelled",)
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.native_recovery_intents WHERE native_identity_id = %s",
        (target.identity_id,),
    ).fetchall() == [("revoked",)]
    assert e2e_admin_conn.execute(
        "SELECT status, count(*) FROM request_engine.native_credentials "
        "WHERE native_identity_id = %s GROUP BY status",
        (target.identity_id,),
    ).fetchall() == [("active", 1)]


@pytest.mark.asyncio
async def test_identity_recovery_issue_without_delivery_adapter_fails_closed(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-unconfigured",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=None,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        created = await client.post(
            _CASES_PATH,
            headers={**root_headers, "Idempotency-Key": "recovery-unconfigured-create-1"},
            json={
                "target_native_identity_id": str(target.identity_id),
                "reason_code": "lost_credential",
                "evidence_reference": "case-ref-unconfigured",
                "delivery_destination_reference": "channel-ref-unconfigured",
            },
        )
        assert created.status_code == 201, created.text
        case_id = UUID(created.json()["case_id"])
        approved = await client.post(
            f"{_CASES_PATH}/{case_id}:approve",
            headers={**approver_headers, "Idempotency-Key": "recovery-unconfigured-approve-1"},
            json={"expected_revision": 1, "reason_code": "ownership_verified"},
        )
        assert approved.status_code == 200, approved.text

        issue = await client.post(
            f"{_CASES_PATH}/{case_id}:issue",
            headers={**root_headers, "Idempotency-Key": "recovery-unconfigured-issue-1"},
            json={"expected_revision": 2},
        )
        assert issue.status_code == 503, issue.text
        assert issue.headers["Cache-Control"] == "no-store"
        assert issue.json()["error"]["code"] == "recovery_delivery_unconfigured"
        assert issue.json()["error"]["retryable"] is False
        assert issue.json()["error"]["resolution"] == "operator_intervention"

    # Fail-closed issuance leaves the approved case untouched.
    assert _case_state(e2e_admin_conn, case_id) == ("approved", "pending", 2, 0, None)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
        (case_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_recovery_intents WHERE native_identity_id = %s",
        (target.identity_id,),
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_identity_recovery_private_surface_denies_unbound_callers_and_publishes_operations(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-boundaries",
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    fake = FakeRecoverySecretDelivery()
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=fake,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        assert (await client.get(_CASES_PATH)).status_code == 401
        assert (
            await client.post(
                _CASES_PATH,
                headers={"Idempotency-Key": "recovery-no-bearer"},
                json={
                    "target_native_identity_id": str(target.identity_id),
                    "reason_code": "lost_credential",
                    "evidence_reference": "case-ref-no-bearer",
                    "delivery_destination_reference": "channel-ref-no-bearer",
                },
            )
        ).status_code == 401

        target_token = await _login(client, target.login_handle, target.password)
        unbound = await client.get(_CASES_PATH, headers={"Authorization": f"Bearer {target_token}"})
        assert unbound.status_code == 403, unbound.text
        assert unbound.json()["error"]["code"] == "identity_not_bound"

        root_token = await _login(client, root_handle, root_password)
        missing = await client.get(
            f"{_CASES_PATH}/{uuid4()}",
            headers={"Authorization": f"Bearer {root_token}"},
        )
        assert missing.status_code == 404, missing.text
        assert missing.json()["error"]["code"] == "platform_identity_recovery_case_not_found"

    schema = app.openapi()
    operations = {
        ("/v1/platform/identity-recovery-cases", "post"): (
            "platform_identity_recovery_case_create"
        ),
        ("/v1/platform/identity-recovery-cases", "get"): ("platform_identity_recovery_case_list"),
        ("/v1/platform/identity-recovery-cases/{case_id}", "get"): (
            "platform_identity_recovery_case_get"
        ),
        ("/v1/platform/identity-recovery-cases/{case_id}:approve", "post"): (
            "platform_identity_recovery_case_approve"
        ),
        ("/v1/platform/identity-recovery-cases/{case_id}:issue", "post"): (
            "platform_identity_recovery_case_issue"
        ),
        ("/v1/platform/identity-recovery-cases/{case_id}:revoke", "post"): (
            "platform_identity_recovery_case_revoke"
        ),
    }
    for (path, method), operation_id in operations.items():
        operation = schema["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert operation["x-request-engine-owner"] == "tenancy"


class _VaultKvV2Mock:
    """In-memory Vault KV v2 boundary for the real ``VaultRecoverySecretStore``.

    Emulates only the endpoints the store uses: create-if-absent CAS writes,
    read-back, TTL metadata and discard. The authoritative staging/read-back
    logic under test is the real HTTP client; only the Vault server is faked.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, dict[str, Any]] = {}
        self.data_writes: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        segments = request.url.path.strip("/").split("/")
        if len(segments) < 4 or segments[0] != "v1":
            return httpx.Response(404, json={"errors": []})
        _, _mount, kind, *rest = segments
        key = "/".join(rest)
        if kind == "data" and request.method == "POST":
            body = json.loads(request.content)
            self.data_writes.append(body)
            if body.get("options", {}).get("cas") == 0 and key in self.payloads:
                return httpx.Response(
                    400,
                    json={"errors": ["check-and-set parameter did not match the current version"]},
                )
            self.payloads[key] = body["data"]
            return httpx.Response(200, json={"data": {"version": 1}})
        if kind == "data" and request.method == "GET":
            stored = self.payloads.get(key)
            if stored is None:
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(
                200,
                json={"data": {"data": stored, "metadata": {"version": 1}}},
            )
        if kind == "metadata" and request.method in ("POST", "DELETE"):
            if request.method == "DELETE":
                self.payloads.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(405)

    def staged_secret(self, case_id: UUID, generation: int = 1) -> str:
        return str(self._reference(case_id, generation)["secret"])

    def _reference(self, case_id: UUID, generation: int) -> dict[str, Any]:
        reference = f"request-engine/identity-recovery/{case_id}/{generation}"
        return self.payloads[reference]


class _RecordingSmtp(smtplib.SMTP):
    """Minimal SMTP double that records calls and never opens a socket."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.connection_args = args
        self.connection_kwargs = kwargs
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        self.connect_error: Exception | None = None
        self.send_error: Exception | None = None

    def __enter__(self) -> "_RecordingSmtp":
        self.calls.append("connect")
        if self.connect_error is not None:
            raise self.connect_error
        return self

    def __exit__(self, *args: Any) -> None:
        self.calls.append("close")

    def ehlo(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("ehlo")
        return (250, b"ok")

    def starttls(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("starttls")
        return (220, b"ready")

    def login(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        self.calls.append("login")
        return (235, b"authenticated")

    def send_message(self, *args: Any, **kwargs: Any) -> dict[str, tuple[int, bytes]]:
        self.calls.append("send_message")
        if self.send_error is not None:
            raise self.send_error
        self.sent.append(args[0])
        return {}


class _SmtpTransportDouble:
    """SMTP transport boundary with per-attempt injected failures."""

    def __init__(self) -> None:
        self.instances: list[_RecordingSmtp] = []
        self.connect_errors: list[Exception | None] = []
        self.send_errors: list[Exception | None] = []

    def __call__(self, *args: Any, **kwargs: Any) -> smtplib.SMTP:
        index = len(self.instances)
        instance = _RecordingSmtp(*args, **kwargs)
        if index < len(self.connect_errors):
            instance.connect_error = self.connect_errors[index]
        if index < len(self.send_errors):
            instance.send_error = self.send_errors[index]
        self.instances.append(instance)
        return instance

    @property
    def messages(self) -> list[EmailMessage]:
        return [message for instance in self.instances for message in instance.sent]


_FAST_RETRY_CONFIG = WorkerRuntimeConfig(
    retry_base=timedelta(0),
    retry_cap=timedelta(0),
    retry_jitter_fraction=0.0,
)


def _real_delivery(
    vault: _VaultKvV2Mock,
    smtp: _SmtpTransportDouble,
) -> ComposedRecoverySecretDelivery:
    return ComposedRecoverySecretDelivery(
        store=VaultRecoverySecretStore(
            address="https://vault.test",
            token="test-vault-token",
            transport=vault.transport(),
        ),
        channel=SmtpRecoveryDeliveryChannel(
            host="smtp.test",
            port=587,
            sender="recovery@example.test",
            username="mailer",
            password="mailer-secret",
            transport=smtp,
        ),
    )


def _assert_raw_proof_absent(conn: PgConnection, raw_proof: str) -> None:
    leaked = conn.execute(
        """
        SELECT count(*) FROM (
            SELECT row_to_json(c) AS payload
              FROM request_engine.identity_recovery_cases AS c
            UNION ALL
            SELECT row_to_json(t)
              FROM request_engine.identity_recovery_delivery_tickets AS t
            UNION ALL
            SELECT row_to_json(f)
              FROM request_engine.platform_identity_recovery_facts AS f
            UNION ALL
            SELECT row_to_json(i)
              FROM request_engine.native_recovery_intents AS i
        ) AS rows
        WHERE rows.payload::text LIKE %s
        """,
        (f"%{raw_proof}%",),
    ).fetchone()
    assert leaked == (0,)


async def _issue_recovery_case(
    client: AsyncClient,
    *,
    root_headers: dict[str, str],
    approver_headers: dict[str, str],
    target_identity_id: UUID,
    destination_reference: str,
    key_prefix: str,
) -> UUID:
    created = await client.post(
        _CASES_PATH,
        headers={**root_headers, "Idempotency-Key": f"{key_prefix}-create"},
        json={
            "target_native_identity_id": str(target_identity_id),
            "reason_code": "lost_credential",
            "evidence_reference": f"case-ref-{key_prefix}",
            "delivery_destination_reference": destination_reference,
        },
    )
    assert created.status_code == 201, created.text
    case_id = UUID(created.json()["case_id"])
    approved = await client.post(
        f"{_CASES_PATH}/{case_id}:approve",
        headers={**approver_headers, "Idempotency-Key": f"{key_prefix}-approve"},
        json={"expected_revision": 1, "reason_code": "ownership_verified"},
    )
    assert approved.status_code == 200, approved.text
    issued = await client.post(
        f"{_CASES_PATH}/{case_id}:issue",
        headers={**root_headers, "Idempotency-Key": f"{key_prefix}-issue"},
        json={"expected_revision": 2},
    )
    assert issued.status_code == 202, issued.text
    return case_id


@pytest.mark.asyncio
async def test_identity_recovery_delivery(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    recovery_worker_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-real-delivery",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    vault = _VaultKvV2Mock()
    smtp = _SmtpTransportDouble()
    delivery = _real_delivery(vault, smtp)
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=delivery,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        case_id = await _issue_recovery_case(
            client,
            root_headers=root_headers,
            approver_headers=approver_headers,
            target_identity_id=target.identity_id,
            destination_reference=target.login_handle,
            key_prefix="recovery-real-delivery",
        )

        # The real store staged the raw proof into Vault under create-if-absent
        # CAS; only the opaque reference/digest reached PostgreSQL.
        raw_proof = vault.staged_secret(case_id)
        staged_writes = [write for write in vault.data_writes if write.get("options") == {"cas": 0}]
        assert len(staged_writes) == 1
        assert staged_writes[0]["data"]["secret"] == raw_proof
        reference = f"request-engine/identity-recovery/{case_id}/1"
        assert _ticket_state(e2e_admin_conn, case_id) == (
            1,
            "pending",
            reference,
            hashlib.sha256(raw_proof.encode("utf-8")).hexdigest(),
            target.login_handle,
        )
        detail = await client.get(f"{_CASES_PATH}/{case_id}", headers=approver_headers)
        assert detail.status_code == 200, detail.text
        assert raw_proof not in detail.text
        _assert_raw_proof_absent(e2e_admin_conn, raw_proof)

        ticket_row = e2e_admin_conn.execute(
            "SELECT id FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
            (case_id,),
        ).fetchone()
        assert ticket_row is not None
        ticket_id = UUID(str(ticket_row[0]))
        runtime = build_recovery_delivery_worker(recovery_worker_session_factory, delivery)
        outcomes = await runtime.run_once()
        assert [outcome.work_id for outcome in outcomes] == [ticket_id]
        assert [outcome.state.value for outcome in outcomes] == ["completed"]

        # Exactly one real SMTP message left the fake boundary, carrying the proof.
        assert len(smtp.instances) == 1
        assert len(smtp.messages) == 1
        message = smtp.messages[0]
        assert message["To"] == target.login_handle
        assert raw_proof in str(message.get_content())
        assert e2e_admin_conn.execute(
            "SELECT status, delivered_at IS NOT NULL "
            "FROM request_engine.identity_recovery_delivery_tickets WHERE id = %s",
            (ticket_id,),
        ).fetchone() == ("delivered", True)
        assert _case_state(e2e_admin_conn, case_id)[:3] == ("issued", "delivered", 5)

        new_password = "replacement real delivery proof password"
        recovered = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": raw_proof, "new_password": new_password},
        )
        assert recovered.status_code == 204, recovered.text
        old_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": target.password},
        )
        assert old_login.status_code == 401
        new_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": new_password},
        )
        assert new_login.status_code == 201, new_login.text

    _assert_raw_proof_absent(e2e_admin_conn, raw_proof)


@pytest.mark.asyncio
async def test_identity_recovery_ambiguous_delivery_is_not_blindly_retried(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    recovery_worker_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-ambiguous-delivery",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    vault = _VaultKvV2Mock()
    smtp = _SmtpTransportDouble()
    smtp.send_errors = [smtplib.SMTPServerDisconnected()]
    delivery = _real_delivery(vault, smtp)
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=delivery,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        case_id = await _issue_recovery_case(
            client,
            root_headers=root_headers,
            approver_headers=approver_headers,
            target_identity_id=target.identity_id,
            destination_reference=target.login_handle,
            key_prefix="recovery-ambiguous-delivery",
        )
        runtime = build_recovery_delivery_worker(recovery_worker_session_factory, delivery)
        outcomes = await runtime.run_once()
        assert [outcome.state.value for outcome in outcomes] == ["completed"]
        assert len(smtp.instances) == 1
        assert smtp.instances[0].calls.count("send_message") == 1
        assert smtp.messages == []
        assert e2e_admin_conn.execute(
            "SELECT status, last_error_class, attempt_count "
            "FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
            (case_id,),
        ).fetchone() == ("unknown", "ambiguous_delivery_outcome", 1)
        assert _case_state(e2e_admin_conn, case_id)[1] == "unknown"

        # Unknown is terminal for this attempt: reconcile exposes no SMTP query
        # surface, so the worker must not silently republish under the same key.
        assert await runtime.run_once() == ()
        assert len(smtp.instances) == 1
        assert smtp.instances[0].calls.count("send_message") == 1


@pytest.mark.asyncio
async def test_identity_recovery_connection_failure_is_safely_retried(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    recovery_worker_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-retryable-delivery",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    vault = _VaultKvV2Mock()
    smtp = _SmtpTransportDouble()
    smtp.connect_errors = [ConnectionRefusedError()]
    delivery = _real_delivery(vault, smtp)
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=delivery,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        case_id = await _issue_recovery_case(
            client,
            root_headers=root_headers,
            approver_headers=approver_headers,
            target_identity_id=target.identity_id,
            destination_reference=target.login_handle,
            key_prefix="recovery-retryable-delivery",
        )
        raw_proof = vault.staged_secret(case_id)
        runtime = build_recovery_delivery_worker(
            recovery_worker_session_factory,
            delivery,
            config=_FAST_RETRY_CONFIG,
        )
        first = await runtime.run_once()
        assert [outcome.state.value for outcome in first] == ["retry"]
        assert len(smtp.instances) == 1
        assert smtp.instances[0].calls == ["connect"]
        assert smtp.messages == []
        assert e2e_admin_conn.execute(
            "SELECT status, last_error_class, attempt_count "
            "FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
            (case_id,),
        ).fetchone() == ("pending", "RecoveryDeliveryRetryable", 1)

        retry_outcomes = await runtime.run_once()
        for _ in range(5):
            if retry_outcomes:
                break
            retry_outcomes = await runtime.run_once()
        assert [outcome.state.value for outcome in retry_outcomes] == ["completed"]
        assert len(smtp.instances) == 2
        assert smtp.instances[1].calls == [
            "connect",
            "ehlo",
            "starttls",
            "login",
            "send_message",
            "close",
        ]
        assert len(smtp.messages) == 1
        assert raw_proof in str(smtp.messages[0].get_content())
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.identity_recovery_delivery_tickets "
            "WHERE case_id = %s",
            (case_id,),
        ).fetchone() == ("delivered",)


@pytest.mark.asyncio
async def test_identity_recovery_invalid_destination_is_permanent(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    recovery_worker_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, _, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-identity-recovery-invalid-destination",
    )
    approver = _insert_platform_human(
        e2e_admin_conn,
        authority_id=authority_id,
        capabilities=("platform.identity.recovery_approve", "platform.identity.read"),
    )
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    vault = _VaultKvV2Mock()
    smtp = _SmtpTransportDouble()
    delivery = _real_delivery(vault, smtp)
    app = _control_app(
        authority_id=authority_id,
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        delivery=delivery,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        root_headers = await _bearer_headers(client, root_handle, root_password)
        approver_headers = await _bearer_headers(client, approver.login_handle, approver.password)
        case_id = await _issue_recovery_case(
            client,
            root_headers=root_headers,
            approver_headers=approver_headers,
            target_identity_id=target.identity_id,
            destination_reference="not-an-email-address",
            key_prefix="recovery-invalid-destination",
        )
        runtime = build_recovery_delivery_worker(recovery_worker_session_factory, delivery)
        outcomes = await runtime.run_once()
        assert [outcome.state.value for outcome in outcomes] == ["dead"]
        assert smtp.instances == []
        assert smtp.messages == []
        assert e2e_admin_conn.execute(
            "SELECT status, last_error_class "
            "FROM request_engine.identity_recovery_delivery_tickets WHERE case_id = %s",
            (case_id,),
        ).fetchone() == ("failed", "RecoveryDeliveryPermanent")
        assert _case_state(e2e_admin_conn, case_id)[1] == "failed"
