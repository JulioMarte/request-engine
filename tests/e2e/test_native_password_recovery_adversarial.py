"""Adversarial HTTP/PostgreSQL evidence for native recovery consumption.

Covers the handoff requirements that the authored happy-path regression does not:
one-time consumption under a real race, expired/malformed/oversized input,
preservation of revoked authority state, secret exclusion from audit/outbox and
the native-only route composition with no tool projection.
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.platform.db.native_human_auth_store import PostgresNativeHumanAuthStore
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import issue_opaque_token
from request_engine.platform.security.native_human_auth import NativeHumanAuthService

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.adversarial,
    pytest.mark.invariant,
]

_WAIT_SECONDS = 30.0


async def _wait_for_blocked_recovery_consumers(
    admin_conn: PgConnection,
    *,
    minimum: int = 1,
) -> bool:
    for _ in range(int(_WAIT_SECONDS / 0.05)):
        row = admin_conn.execute(
            """
            SELECT count(*)
              FROM pg_stat_activity
             WHERE state = 'active'
               AND wait_event_type = 'Lock'
               AND query LIKE '%consume_native_recovery_intent%'
            """
        ).fetchone()
        if row is not None and int(row[0]) >= minimum:
            return True
        await asyncio.sleep(0.05)
    return False


def _authority(conn: PgConnection) -> UUID:
    authority_id = uuid4()
    conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (id, kind, issuer_or_environment)
        VALUES (%s, 'native', %s)
        """,
        (authority_id, f"recovery-adversarial:{authority_id}"),
    )
    return authority_id


def _app(session_factory: SessionFactory, authority_id: UUID) -> Any:
    return create_native_app(
        session_factory=session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"native-recovery-adversarial-key-1",
    )


def _credential_state(conn: PgConnection, identity_id: UUID) -> dict[str, object]:
    return {
        "credentials": conn.execute(
            "SELECT count(*), coalesce(sum(revision), 0) FROM request_engine.native_credentials "
            "WHERE native_identity_id = %s",
            (identity_id,),
        ).fetchone(),
        "active_sessions": conn.execute(
            "SELECT count(*) FROM request_engine.native_sessions "
            "WHERE native_identity_id = %s AND status = 'active'",
            (identity_id,),
        ).fetchone(),
        "epoch": conn.execute(
            "SELECT session_epoch FROM request_engine.native_identities WHERE id = %s",
            (identity_id,),
        ).fetchone(),
        "intents": conn.execute(
            "SELECT status, count(*) FROM request_engine.native_recovery_intents "
            "WHERE native_identity_id = %s GROUP BY status ORDER BY status",
            (identity_id,),
        ).fetchall(),
    }


@pytest.mark.asyncio
async def test_concurrent_recovery_requests_consume_one_proof_once(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    e2e_barrier_conn: PgConnection,
) -> None:
    authority_id = _authority(e2e_admin_conn)
    app = _app(e2e_session_factory, authority_id)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(e2e_session_factory))
    handle = f"recovery-race-{uuid4().hex}@example.test"
    old_password = "original recovery race password"
    new_password = "replacement recovery race password"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": old_password},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])
        logged_in = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": old_password},
        )
        assert logged_in.status_code == 201, logged_in.text
        issued = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert issued is not None
        payload = {"recovery_token": issued.raw_token, "new_password": new_password}

        # Hold the identity serialization root until both requests queue on it.
        e2e_barrier_conn.execute(
            "SELECT status FROM request_engine.native_identities WHERE id = %s FOR UPDATE",
            (identity_id,),
        )
        first = asyncio.create_task(client.post("/auth/native/password:recover", json=payload))
        second = asyncio.create_task(client.post("/auth/native/password:recover", json=payload))
        wait_ok = await _wait_for_blocked_recovery_consumers(e2e_admin_conn, minimum=2)
        e2e_barrier_conn.commit()
        responses = await asyncio.gather(first, second)
        assert wait_ok, "both recovery requests must queue on the identity lock before release"
        assert sorted(response.status_code for response in responses) == [204, 401]
        accepted = next(response for response in responses if response.status_code == 204)
        rejected = next(response for response in responses if response.status_code == 401)
        assert accepted.content == b""
        assert accepted.headers["cache-control"] == "no-store"
        assert rejected.json()["error"]["code"] == "recovery_intent_invalid"
        assert rejected.headers["cache-control"] == "no-store"

        replay = await client.post("/auth/native/password:recover", json=payload)
        assert replay.status_code == 401
        new_login = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": new_password},
        )
        assert new_login.status_code == 201, new_login.text

    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchone() == (2,)
    assert e2e_admin_conn.execute(
        "SELECT status, count(*) FROM request_engine.native_recovery_intents "
        "WHERE native_identity_id = %s GROUP BY status",
        (identity_id,),
    ).fetchall() == [("consumed", 1)]


@pytest.mark.asyncio
async def test_recovery_rejects_expired_malformed_and_oversized_input_without_mutation(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _authority(e2e_admin_conn)
    app = _app(e2e_session_factory, authority_id)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(e2e_session_factory))
    handle = f"recovery-invalid-{uuid4().hex}@example.test"
    old_password = "original recovery invalid password"
    new_password = "replacement recovery invalid password"
    expired = issue_opaque_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": old_password},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])
        logged_in = await client.post(
            "/auth/native/sessions",
            json={"login_handle": handle, "password": old_password},
        )
        assert logged_in.status_code == 201, logged_in.text
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.native_recovery_intents (
                id, native_identity_id, token_digest, token_fingerprint, status,
                created_at, expires_at
            ) VALUES (
                %s, %s, %s, %s, 'pending',
                clock_timestamp() - interval '2 hours',
                clock_timestamp() - interval '1 hour'
            )
            """,
            (expired.token_id, identity_id, expired.digest, expired.fingerprint),
        )
        state_before = _credential_state(e2e_admin_conn, identity_id)

        denied = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": expired.raw_token, "new_password": new_password},
        )
        assert denied.status_code == 401, denied.text
        assert denied.json()["error"]["code"] == "recovery_intent_invalid"
        assert denied.headers["cache-control"] == "no-store"
        assert expired.raw_token not in denied.text
        assert new_password not in denied.text
        assert _credential_state(e2e_admin_conn, identity_id) == state_before
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.native_recovery_intents WHERE id = %s",
            (expired.token_id,),
        ).fetchone() == ("pending",)

        usable = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert usable is not None
        payload = {"recovery_token": usable.raw_token, "new_password": new_password}
        malformed = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": [usable.raw_token], "new_password": new_password},
        )
        assert malformed.status_code == 422
        assert usable.raw_token not in malformed.text
        assert new_password not in malformed.text
        injected = await client.post(
            "/auth/native/password:recover",
            json={
                **payload,
                "organization_id": str(uuid4()),
                "principal_id": str(uuid4()),
                "identity_authority_id": str(uuid4()),
            },
        )
        assert injected.status_code == 422
        assert usable.raw_token not in injected.text
        oversized_token = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": "x" * 5000, "new_password": new_password},
        )
        assert oversized_token.status_code == 422
        oversized_password = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": usable.raw_token, "new_password": "x" * 5000},
        )
        assert oversized_password.status_code == 422
        assert usable.raw_token not in oversized_password.text
        assert new_password not in oversized_password.text

        recovered = await client.post("/auth/native/password:recover", json=payload)
        assert recovered.status_code == 204, recovered.text
        assert recovered.content == b""

    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchone() == (2,)


@pytest.mark.asyncio
async def test_recovery_preserves_revoked_binding_membership_and_grant(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _authority(e2e_admin_conn)
    app = _app(e2e_session_factory, authority_id)
    service = NativeHumanAuthService(store=PostgresNativeHumanAuthStore(e2e_session_factory))
    handle = f"recovery-bound-{uuid4().hex}@example.test"
    old_password = "original recovery bound password"
    new_password = "replacement recovery bound password"
    organization_id, principal_id, party_id = uuid4(), uuid4(), uuid4()
    binding_id, grant_id, membership_id = uuid4(), uuid4(), uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        enrolled = await client.post(
            "/auth/native/identities",
            json={"login_handle": handle, "password": old_password},
        )
        assert enrolled.status_code == 201, enrolled.text
        identity_id = UUID(enrolled.json()["native_identity_id"])
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.organizations (id, organization_key, display_name)
            VALUES (%s, %s, %s)
            """,
            (organization_id, f"recovery-bound-{uuid4().hex}", "Recovery Bound"),
        )
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.principals (
                id, organization_id, principal_plane, principal_kind, external_subject
            ) VALUES (%s, %s, 'tenant', 'human', %s)
            """,
            (principal_id, organization_id, f"recovery-bound-{uuid4().hex}"),
        )
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.parties (id, organization_id, party_kind, display_name)
            VALUES (%s, %s, 'person', %s)
            """,
            (party_id, organization_id, "Recovery Anchor"),
        )
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (%s, %s, %s, 'tenant', %s, %s, 'active')
            """,
            (binding_id, organization_id, principal_id, authority_id, str(identity_id)),
        )
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.principal_authority_grants (
                id, organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                %s, %s, %s, 'tenant', 'operational', 'appointments.read', false, %s,
                'authority_management', %s
            )
            """,
            (
                grant_id,
                organization_id,
                principal_id,
                principal_id,
                f"recovery-bound:{uuid4().hex}",
            ),
        )
        e2e_admin_conn.execute(
            """
            INSERT INTO request_engine.staff_memberships (
                id, organization_id, principal_id, identity_binding_id,
                authority_anchor_party_id, status, established_by_principal_id,
                provenance_kind, provenance_reference, activated_at
            ) VALUES (
                %s, %s, %s, %s, %s, 'active', %s,
                'staff_invitation', %s, clock_timestamp()
            )
            """,
            (
                membership_id,
                organization_id,
                principal_id,
                binding_id,
                party_id,
                principal_id,
                f"recovery-bound:{uuid4().hex}",
            ),
        )
        e2e_admin_conn.execute(
            "UPDATE request_engine.identity_bindings SET status = 'revoked', "
            "revision = revision + 1, revoked_at = clock_timestamp() WHERE id = %s",
            (binding_id,),
        )
        e2e_admin_conn.execute(
            "UPDATE request_engine.staff_memberships SET status = 'revoked', "
            "revision = revision + 1, revoked_at = clock_timestamp() WHERE id = %s",
            (membership_id,),
        )
        e2e_admin_conn.execute(
            """
            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked', revision = revision + 1,
                   revoked_at = clock_timestamp(), revoked_by_principal_id = %s
             WHERE id = %s
            """,
            (principal_id, grant_id),
        )

        authority_before = _authority_fingerprint(
            e2e_admin_conn, principal_id=principal_id, organization_id=organization_id
        )
        audit_before, dump_before = _audit_outbox_state(e2e_admin_conn)
        issued = await service.issue_recovery(
            identity_authority_id=authority_id, login_handle=handle
        )
        assert issued is not None
        recovered = await client.post(
            "/auth/native/password:recover",
            json={"recovery_token": issued.raw_token, "new_password": new_password},
        )
        assert recovered.status_code == 204, recovered.text

    assert (
        _authority_fingerprint(
            e2e_admin_conn, principal_id=principal_id, organization_id=organization_id
        )
        == authority_before
    )
    audit_after, dump_after = _audit_outbox_state(e2e_admin_conn)
    assert audit_after == audit_before
    assert issued.raw_token not in dump_after
    assert old_password not in dump_after
    assert new_password not in dump_after
    assert dump_after == dump_before
    verifiers = e2e_admin_conn.execute(
        "SELECT verifier FROM request_engine.native_credentials WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchall()
    assert len(verifiers) == 2
    assert all(old_password not in row[0] and new_password not in row[0] for row in verifiers)
    intents = e2e_admin_conn.execute(
        "SELECT token_digest::text, token_fingerprint FROM request_engine.native_recovery_intents "
        "WHERE native_identity_id = %s",
        (identity_id,),
    ).fetchall()
    assert len(intents) == 1
    assert issued.raw_token not in str(intents)


def _authority_fingerprint(
    conn: PgConnection,
    *,
    principal_id: UUID,
    organization_id: UUID,
) -> dict[str, object]:
    return {
        "principal": conn.execute(
            "SELECT authority_revision, active FROM request_engine.principals WHERE id = %s",
            (principal_id,),
        ).fetchone(),
        "bindings": conn.execute(
            "SELECT status, revision, revoked_at IS NOT NULL "
            "FROM request_engine.identity_bindings WHERE principal_id = %s ORDER BY id",
            (principal_id,),
        ).fetchall(),
        "grants": conn.execute(
            "SELECT status, revision, revoked_at IS NOT NULL "
            "FROM request_engine.principal_authority_grants "
            "WHERE principal_id = %s ORDER BY id",
            (principal_id,),
        ).fetchall(),
        "memberships": conn.execute(
            "SELECT status, revision, revoked_at IS NOT NULL "
            "FROM request_engine.staff_memberships WHERE principal_id = %s ORDER BY id",
            (principal_id,),
        ).fetchall(),
        "counts": (
            conn.execute(
                "SELECT count(*) FROM request_engine.principals WHERE organization_id = %s",
                (organization_id,),
            ).fetchone(),
            conn.execute(
                "SELECT count(*) FROM request_engine.identity_bindings WHERE organization_id = %s",
                (organization_id,),
            ).fetchone(),
            conn.execute(
                "SELECT count(*) FROM request_engine.principal_authority_grants "
                "WHERE organization_id = %s",
                (organization_id,),
            ).fetchone(),
            conn.execute(
                "SELECT count(*) FROM request_engine.staff_memberships WHERE organization_id = %s",
                (organization_id,),
            ).fetchone(),
        ),
    }


def _audit_outbox_state(conn: PgConnection) -> tuple[tuple[object, ...], str]:
    counts = (
        conn.execute("SELECT count(*) FROM request_engine.audit_records").fetchone(),
        conn.execute("SELECT count(*) FROM request_engine.outbox_messages").fetchone(),
    )
    row = conn.execute(
        """
        SELECT coalesce(string_agg(record, ' '), '')
          FROM (
            SELECT to_jsonb(a)::text AS record FROM request_engine.audit_records AS a
            UNION ALL
            SELECT to_jsonb(o)::text FROM request_engine.outbox_messages AS o
          ) AS records
        """
    ).fetchone()
    return counts, (str(row[0]) if row is not None else "")


@pytest.mark.asyncio
async def test_recovery_route_is_native_only_and_not_tool_projected(
    e2e_session_factory: SessionFactory,
) -> None:
    app = _app(e2e_session_factory, uuid4())
    schema = app.openapi()
    operation = schema["paths"]["/auth/native/password:recover"]["post"]
    assert operation["operationId"] == "nativePasswordRecover"
    assert "x-request-engine-tool-name" not in operation
    assert "x-request-engine-tool-audiences" not in operation
    native_paths = [path for path in schema["paths"] if path.startswith("/auth/native/")]
    assert sorted(path for path in native_paths if "recover" in path) == [
        "/auth/native/password:recover"
    ]
