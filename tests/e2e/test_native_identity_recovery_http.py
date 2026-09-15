"""Governed identity recovery over the private HTTP control plane.

Production-like journey for the accepted recovery contract: double-control
approval, staging/publishing through a test secret-delivery adapter, the real
fenced delivery worker, one-time consumption, revocation and fail-closed
boundaries. Real PostgreSQL 18, real ASGI HTTP and the real worker runtime;
direct SQL only builds valid preconditions and inspects durable state.
"""

import hashlib
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from psycopg import Connection, sql
from psycopg.conninfo import make_conninfo

from request_engine.bootstrap.recovery_delivery_worker import build_recovery_delivery_worker
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.secrets.delivery import (
    DeliveryOutcome,
    RecoverySecretDelivery,
    StagedRecoverySecret,
)
from request_engine.platform.security.native_auth import hash_password

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
            return existing[0]
        staged = StagedRecoverySecret(
            reference=f"test://{case_id}/{generation}",
            digest=hashlib.sha256(secret.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
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
    )


async def _login(client: AsyncClient, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


async def _bearer_headers(client: AsyncClient, login_handle: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _login(client, login_handle, password)}"}


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
