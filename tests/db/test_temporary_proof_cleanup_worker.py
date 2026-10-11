"""Real isolated LOGIN, committed leases, crash reconciliation and fencing."""

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from psycopg import Connection, sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import (
    SessionFactory,
    create_postgres_engine,
    create_session_factory,
)
from request_engine.platform.secrets.temporary_proof_cleanup_admission import (
    TemporaryCleanupAdmission,
)
from request_engine.platform.secrets.temporary_proof_cleanup_worker import (
    TemporaryProofCleanupWorker,
)

pytestmark = [pytest.mark.postgres, pytest.mark.security, pytest.mark.adversarial]


@pytest_asyncio.fixture
async def cleanup_sessions(
    admin_conn: Connection[Any],
    pg_conninfo: str,
) -> AsyncIterator[SessionFactory]:
    role, password = f"cleanup_{uuid4().hex[:12]}", uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN INHERIT NOSUPERUSER NOBYPASSRLS PASSWORD {} "
            "IN ROLE request_proof_cleanup_worker"
        ).format(sql.Identifier(role), sql.Literal(password))
    )
    values = conninfo_to_dict(pg_conninfo)
    engine = create_postgres_engine(
        URL.create(
            "postgresql+asyncpg",
            username=role,
            password=password,
            host=str(values["host"]),
            port=int(str(values["port"])),
            database=str(values["dbname"]),
        ).render_as_string(hide_password=False)
    )
    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def admission(tmp_path: Path, backend: UUID) -> TemporaryCleanupAdmission:
    now = datetime.now(UTC)
    body: dict[str, object] = {
        "schema": "temporary-proof-cleanup-admission/v1",
        "admission_id": str(uuid4()),
        "backend_id": str(backend),
        "provider_origin": "http://127.0.0.1:8200",
        "mount": "secret",
        "namespace": "request-engine/identity-recovery",
        "grace_seconds": 1,
        "certified_at": (now - timedelta(minutes=1)).isoformat(),
        "valid_until": (now + timedelta(minutes=10)).isoformat(),
    }
    for stem in ("policy_bundle", "restore_fence", "acceptance_evidence"):
        path = tmp_path / stem
        path.write_text(f"isolated proof {stem}", encoding="utf-8")
        body[f"{stem}_path"] = stem
        body[f"{stem}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return TemporaryCleanupAdmission.load(path)


def record(admin: Connection[Any], backend: UUID) -> tuple[str, datetime, datetime]:
    now = datetime.now(UTC)
    reference, created, deleted = (
        f"request-engine/identity-recovery/{uuid4()}/1",
        now - timedelta(hours=3),
        now - timedelta(hours=2),
    )
    admin.execute(
        "SELECT request_cmd.record_temporary_proof_retention(%s,%s,%s,%s,%s,%s,%s)",
        (backend, "secret", reference, 1, created, deleted, now - timedelta(hours=1)),
    )
    return reference, created, deleted


@pytest.mark.asyncio
async def test_crash_after_destroy_reconciles_without_second_destroy_and_fences_old_lease(
    admin_conn: Connection[Any],
    cleanup_sessions: SessionFactory,
    tmp_path: Path,
) -> None:
    backend = uuid4()
    reference, created, deleted = record(admin_conn, backend)
    destroyed, posts = False, 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal destroyed, posts
        assert reference in request.url.path
        if request.method == "POST":
            assert "/destroy/" in request.url.path
            assert json.loads(request.content) == {"versions": [1]}
            destroyed, posts = True, posts + 1
            return httpx.Response(503)  # Ambiguous transport result, verified by metadata.
        assert request.method == "GET" and "/metadata/" in request.url.path
        return httpx.Response(
            200,
            json={
                "data": {
                    "versions": {
                        "1": {
                            "created_time": created.isoformat(),
                            "deletion_time": deleted.isoformat(),
                            "destroyed": destroyed,
                        }
                    }
                }
            },
        )

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8200",
        transport=httpx.MockTransport(provider),
        timeout=5,
    ) as client:
        worker = TemporaryProofCleanupWorker(
            cleanup_sessions,
            client,
            admission=admission(tmp_path, backend),
            token="isolated",
            outbound_fenced=False,
        )
        first = await worker.claim()
        assert first is not None
        assert await worker.reconcile(first) == "destroyed"
        # Model a crashed holder's expired lease, not a manufactured success result.
        admin_conn.execute(
            "UPDATE request_engine.temporary_proof_cleanup_work "
            "SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",
            (first.work_id,),
        )
        second = await worker.claim()
        assert second is not None and second.lease_token != first.lease_token
        assert not await worker.finish(first, "destroyed")
        assert await worker.reconcile(second) == "destroyed"
        assert await worker.finish(second, "destroyed")
        assert posts == 1
        assert await worker.claim() is None
    assert admin_conn.execute(
        "SELECT attempt,outcome FROM request_engine.temporary_proof_cleanup_results"
    ).fetchall() == [(2, "destroyed")]


@pytest.mark.asyncio
async def test_runtime_has_no_plaintext_business_or_direct_cleanup_table_access(
    cleanup_sessions: SessionFactory,
) -> None:
    async with cleanup_sessions() as session, session.begin():
        row = (
            await session.execute(
                text("""
            SELECT has_table_privilege(current_user,
                (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname='request_engine' AND c.relname='temporary_proof_cleanup_work'),
                'SELECT'),
                has_table_privilege(current_user,
                (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE n.nspname='request_engine' AND c.relname='native_identities'),'SELECT'),
                has_function_privilege(current_user,
                    'request_cmd.record_temporary_proof_retention(uuid,text,text,bigint,'
                    'timestamp with time zone,timestamp with time zone,timestamp with time zone)',
                    'EXECUTE')
        """)
            )
        ).one()
        assert tuple(row) == (False, False, False)


@pytest.mark.asyncio
async def test_restore_fence_drift_stops_claim_and_provider_io(
    admin_conn: Connection[Any],
    cleanup_sessions: SessionFactory,
    tmp_path: Path,
) -> None:
    backend = uuid4()
    record(admin_conn, backend)
    accepted = admission(tmp_path, backend)
    (tmp_path / "restore_fence").write_text("restored instance", encoding="utf-8")
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8200", trust_env=False) as client:
        worker = TemporaryProofCleanupWorker(
            cleanup_sessions,
            client,
            admission=accepted,
            token="isolated",
            outbound_fenced=False,
        )
        with pytest.raises(ValueError, match="not admitted"):
            await worker.claim()
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.temporary_proof_cleanup_work"
    ).fetchone() == (0,)


@pytest.mark.asyncio
async def test_claim_skips_independently_locked_work_and_never_releases_other_lease(
    admin_conn: Connection[Any],
    cleanup_sessions: SessionFactory,
    tmp_path: Path,
) -> None:
    backend = uuid4()
    record(admin_conn, backend)
    record(admin_conn, backend)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8200", trust_env=False) as client:
        worker = TemporaryProofCleanupWorker(
            cleanup_sessions,
            client,
            admission=admission(tmp_path, backend),
            token="isolated",
            outbound_fenced=False,
        )
        first = await worker.claim()
        assert first is not None
        with admin_conn.transaction():
            row = admin_conn.execute(
                "SELECT id FROM request_engine.temporary_proof_cleanup_work "
                "WHERE id<>%s FOR UPDATE",
                (first.work_id,),
            ).fetchone()
            assert row is not None
            # The independent authoritative row lock is already held, not a timing guess.
            assert await asyncio.wait_for(worker.claim(), timeout=3) is None
        second = await asyncio.wait_for(worker.claim(), timeout=3)
        assert second is not None and second.work_id != first.work_id
        assert second.lease_token != first.lease_token
        assert await worker.finish(first, "retained")
        assert await worker.finish(second, "absent")
    assert admin_conn.execute(
        "SELECT count(*),count(DISTINCT work_id) "
        "FROM request_engine.temporary_proof_cleanup_results"
    ).fetchone() == (2, 2)


@pytest.mark.asyncio
async def test_extra_business_membership_fails_closed_even_with_cleanup_execute(
    admin_conn: Connection[Any],
    cleanup_sessions: SessionFactory,
) -> None:
    async with cleanup_sessions() as session:
        login = str((await session.execute(text("SELECT session_user"))).scalar_one())
    admin_conn.execute(sql.SQL("GRANT request_engine_app TO {}").format(sql.Identifier(login)))
    try:
        async with cleanup_sessions() as session, session.begin():
            with pytest.raises(DBAPIError, match="not isolated"):
                await session.execute(
                    text(
                        "SELECT * FROM request_cmd.claim_temporary_proof_cleanup(:b,'secret',1,60)"
                    ),
                    {"b": uuid4()},
                )
    finally:
        admin_conn.execute(
            sql.SQL("REVOKE request_engine_app FROM {}").format(sql.Identifier(login))
        )


def test_cleanup_primitives_exact_owner_search_path_and_no_public_execution(
    admin_conn: Connection[Any],
) -> None:
    rows = admin_conn.execute("""
        SELECT p.proname,pg_get_userbyid(p.proowner),p.prosecdef,p.proconfig,
            EXISTS(SELECT 1 FROM aclexplode(p.proacl) a
                WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='request_cmd' AND p.proname IN
            ('claim_temporary_proof_cleanup','finish_temporary_proof_cleanup')
        ORDER BY p.proname
    """).fetchall()
    assert rows == [
        (
            name,
            "request_engine_schema_owner",
            True,
            ["search_path=pg_catalog, request_engine, pg_temp"],
            False,
        )
        for name in ("claim_temporary_proof_cleanup", "finish_temporary_proof_cleanup")
    ]
