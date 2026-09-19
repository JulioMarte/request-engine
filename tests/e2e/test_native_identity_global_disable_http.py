"""Private HTTP journey for the global native-identity disable surface (D3).

Real PostgreSQL 18, real ASGI HTTP and the real platform control runtime. Direct
SQL only builds valid preconditions and inspects durable authoritative state.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.conninfo import make_conninfo

from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.entrypoints.platform_bootstrap_cli import establish_root, issue_intent
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import hash_password

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.invariant,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_IDENTITIES_PATH = "/v1/platform/native-identities"
_VIEW_FIELDS = frozenset(
    {
        "native_identity_id",
        "identity_authority_id",
        "status",
        "revision",
        "created_at",
        "disabled_at",
    }
)


@dataclass(frozen=True, slots=True)
class _TargetIdentity:
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
    login_handle = f"disable-root-{uuid4().hex}@example.test"
    password = "root native identity disable proof password"
    root_id = establish_root(
        login_handle=login_handle,
        password=password,
        raw_token=intent["ONE-TIME BOOTSTRAP TOKEN"],
    )
    return authority_id, root_id, login_handle, password


def _grant_identity_disable(conn: PgConnection, *, principal_id: UUID) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants "
        "(principal_id, principal_plane, authority_plane, capability_key, delegable, "
        "provenance_kind, provenance_reference) "
        "VALUES (%s, 'platform', 'platform', 'platform.identity.disable', false, "
        "'trust_bootstrap', %s)",
        (principal_id, f"native-identity-disable-http-proof:{uuid4().hex}"),
    )


def _insert_target_identity(conn: PgConnection, *, authority_id: UUID) -> _TargetIdentity:
    identity_id = uuid4()
    login_handle = f"disable-target-{uuid4().hex}@example.test"
    password = "target native identity disable proof password"
    conn.execute(
        "INSERT INTO request_engine.native_identities "
        "(id, identity_authority_id, login_handle) VALUES (%s, %s, %s)",
        (identity_id, authority_id, login_handle),
    )
    conn.execute(
        "INSERT INTO request_engine.native_credentials (id, native_identity_id, verifier) "
        "VALUES (%s, %s, %s)",
        (uuid4(), identity_id, hash_password(password)),
    )
    return _TargetIdentity(identity_id, login_handle, password)


async def _login(client: AsyncClient, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


async def _bearer_headers(client: AsyncClient, login_handle: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {await _login(client, login_handle, password)}"}


@pytest.mark.asyncio
async def test_native_identity_global_disable_http_journey_is_governed_and_audited(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_id, root_id, root_handle, root_password = _bootstrap_root(
        e2e_admin_conn,
        monkeypatch,
        provenance="http-native-identity-global-disable-journey",
    )
    _grant_identity_disable(e2e_admin_conn, principal_id=root_id)
    target = _insert_target_identity(e2e_admin_conn, authority_id=authority_id)
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        assert (await client.get(_IDENTITIES_PATH)).status_code == 401

        root_headers = await _bearer_headers(client, root_handle, root_password)
        await _login(client, target.login_handle, target.password)

        listing = await client.get(_IDENTITIES_PATH, headers=root_headers)
        assert listing.status_code == 200
        assert listing.headers["Cache-Control"] == "no-store"
        items = listing.json()["items"]
        target_item = next(
            item for item in items if item["native_identity_id"] == str(target.identity_id)
        )
        assert set(target_item) == _VIEW_FIELDS
        assert target_item["identity_authority_id"] == str(authority_id)
        assert target_item["status"] == "active"
        assert target_item["revision"] == 1
        assert target_item["disabled_at"] is None
        assert listing.json()["next_cursor"] is None

        fetched = await client.get(f"{_IDENTITIES_PATH}/{target.identity_id}", headers=root_headers)
        assert fetched.status_code == 200
        assert fetched.json() == target_item
        assert (
            await client.get(f"{_IDENTITIES_PATH}/{uuid4()}", headers=root_headers)
        ).status_code == 404

        disable_path = f"{_IDENTITIES_PATH}/{target.identity_id}:disable"
        missing_key = await client.post(
            disable_path,
            headers=root_headers,
            json={"expected_revision": 1, "reason_code": "operator_revocation"},
        )
        assert missing_key.status_code == 422
        missing_revision = await client.post(
            disable_path,
            headers={**root_headers, "Idempotency-Key": "disable-missing-revision"},
            json={"reason_code": "operator_revocation"},
        )
        assert missing_revision.status_code == 422

        stale = await client.post(
            disable_path,
            headers={**root_headers, "Idempotency-Key": "disable-stale-revision"},
            json={"expected_revision": 99, "reason_code": "operator_revocation"},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "native_identity_disable_revision_conflict"

        disable_headers = {**root_headers, "Idempotency-Key": "disable-happy-path"}
        disable_body = {
            "expected_revision": 1,
            "reason_code": "operator_revocation",
            "external_case_reference": "case-native-disable-1",
        }
        disabled = await client.post(disable_path, headers=disable_headers, json=disable_body)
        assert disabled.status_code == 200, disabled.text
        assert disabled.headers["Cache-Control"] == "no-store"
        disable_view = disabled.json()
        assert disable_view["native_identity_id"] == str(target.identity_id)
        assert disable_view["revision_after"] == 2
        assert disable_view["affected_tenant_count"] == 0
        assert disable_view["affected_platform"] is False
        replay = await client.post(disable_path, headers=disable_headers, json=disable_body)
        assert replay.status_code == 200
        assert replay.content == disabled.content

        key_reuse = await client.post(
            disable_path,
            headers=disable_headers,
            json={
                "expected_revision": 1,
                "reason_code": "security_investigation",
                "external_case_reference": "case-native-disable-1",
            },
        )
        assert key_reuse.status_code == 409
        assert key_reuse.json()["error"]["code"] == "native_identity_disable_revision_conflict"

        terminal = await client.get(
            f"{_IDENTITIES_PATH}/{target.identity_id}", headers=root_headers
        )
        assert terminal.status_code == 200
        assert terminal.json()["status"] == "disabled"
        assert terminal.json()["disabled_at"] is not None
        assert terminal.json()["revision"] == 2

        rejected_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": target.login_handle, "password": target.password},
        )
        assert rejected_login.status_code in (401, 403)
        assert rejected_login.status_code != 201

        assert e2e_admin_conn.execute(
            "SELECT status, disabled_at IS NOT NULL FROM request_engine.native_identities "
            "WHERE id = %s",
            (target.identity_id,),
        ).fetchone() == ("disabled", True)
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.native_credentials WHERE native_identity_id = %s",
            (target.identity_id,),
        ).fetchall() == [("revoked",)]
        assert e2e_admin_conn.execute(
            "SELECT status, revocation_reason FROM request_engine.native_sessions "
            "WHERE native_identity_id = %s",
            (target.identity_id,),
        ).fetchall() == [("revoked", "identity_disabled")]

        root_identity_row = e2e_admin_conn.execute(
            "SELECT id, revision FROM request_engine.native_identities WHERE login_handle = %s",
            (root_handle,),
        ).fetchone()
        assert root_identity_row is not None
        root_identity_id = UUID(str(root_identity_row[0]))
        continuity = await client.post(
            f"{_IDENTITIES_PATH}/{root_identity_id}:disable",
            headers={**root_headers, "Idempotency-Key": "disable-last-controller"},
            json={
                "expected_revision": int(root_identity_row[1]),
                "reason_code": "operator_revocation",
            },
        )
        assert continuity.status_code == 409
        assert continuity.json()["error"]["code"] == "native_identity_disable_conflict"
        assert (await client.get(_IDENTITIES_PATH, headers=root_headers)).status_code == 200
        await _login(client, root_handle, root_password)

        foreign = await client.post(
            f"{_IDENTITIES_PATH}/{uuid4()}:disable",
            headers={**root_headers, "Idempotency-Key": "disable-foreign-identity"},
            json={"expected_revision": 1, "reason_code": "operator_revocation"},
        )
        assert foreign.status_code == 404
        assert foreign.json()["error"]["code"] == "native_identity_not_found"

        schema = (await client.get("/openapi.json")).json()
        for path, method, operation_id in (
            (_IDENTITIES_PATH, "get", "platform_native_identity_list"),
            (
                f"{_IDENTITIES_PATH}/{{native_identity_id}}",
                "get",
                "platform_native_identity_get",
            ),
            (
                f"{_IDENTITIES_PATH}/{{native_identity_id}}:disable",
                "post",
                "platform_native_identity_disable",
            ),
        ):
            operation = schema["paths"][path][method]
            assert operation["operationId"] == operation_id
            assert operation["x-request-engine-owner"] == "tenancy"

    facts = e2e_admin_conn.execute(
        "SELECT capability_key, actor_principal_id, revision_before, revision_after, "
        "reason_code, external_case_reference, affected_tenant_count, affected_platform "
        "FROM request_engine.platform_identity_disable_facts "
        "WHERE native_identity_id = %s ORDER BY created_at, id",
        (target.identity_id,),
    ).fetchall()
    assert facts == [
        (
            "platform.identity.disable",
            root_id,
            1,
            2,
            "operator_revocation",
            "case-native-disable-1",
            0,
            False,
        )
    ]
