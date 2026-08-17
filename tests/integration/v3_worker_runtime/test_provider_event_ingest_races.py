import asyncio
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.errors import ProviderEventDedupeConflict
from request_engine.platform.events.provider_events import ProviderEventReceipt, record_provider_event

PgConnection = Connection[Any]


def _organization(admin_conn: PgConnection, label: str) -> UUID:
    row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"provider-ingest-race-{label}-{uuid4().hex}", f"Provider ingest race {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _record_and_hold_commit(
    session_factory: SessionFactory,
    *,
    organization_id: UUID,
    provider_event_id: str,
    payload: dict[str, object],
    inserted: asyncio.Event,
    release_commit: asyncio.Event,
) -> ProviderEventReceipt:
    async with tenant_transaction(session_factory, organization_id) as session:
        receipt = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="race-provider",
            connection_key="primary",
            provider_event_id=provider_event_id,
            payload=payload,
        )
        inserted.set()
        await release_commit.wait()
        return receipt


async def _record_with_pid(
    session_factory: SessionFactory,
    *,
    organization_id: UUID,
    provider_event_id: str,
    payload: dict[str, object],
    backend_pid: asyncio.Queue[int],
) -> ProviderEventReceipt:
    async with tenant_transaction(session_factory, organization_id) as session:
        pid = cast(int, (await session.execute(text("SELECT pg_backend_pid()"))).scalar_one())
        await backend_pid.put(pid)
        return await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="race-provider",
            connection_key="primary",
            provider_event_id=provider_event_id,
            payload=payload,
        )


async def _wait_until_lock_blocked(admin_conn: PgConnection, backend_pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        row = admin_conn.execute(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
            (backend_pid,),
        ).fetchone()
        if row is not None and row[0] == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"backend {backend_pid} never blocked on provider identity conflict")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r17_simultaneous_duplicate_provider_event_ingest_reuses_one_identity(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn, "same-payload")
    provider_event_id = f"evt-{uuid4().hex}"
    payload: dict[str, object] = {"status": "delivered", "message_id": str(uuid4())}
    inserted = asyncio.Event()
    release_commit = asyncio.Event()
    second_pid: asyncio.Queue[int] = asyncio.Queue()

    first_task = asyncio.create_task(
        _record_and_hold_commit(
            app_session_factory,
            organization_id=organization_id,
            provider_event_id=provider_event_id,
            payload=payload,
            inserted=inserted,
            release_commit=release_commit,
        )
    )
    await inserted.wait()
    second_task = asyncio.create_task(
        _record_with_pid(
            app_session_factory,
            organization_id=organization_id,
            provider_event_id=provider_event_id,
            payload=payload,
            backend_pid=second_pid,
        )
    )
    await _wait_until_lock_blocked(admin_conn, await second_pid.get())
    release_commit.set()

    first, second = await asyncio.gather(first_task, second_task)
    assert first.id == second.id
    assert first.replay is False
    assert second.replay is True
    assert first.payload_hash == second.payload_hash
    assert admin_conn.execute(
        """
        SELECT count(*), min(payload_hash), max(payload_hash)
        FROM request_engine.provider_events
        WHERE organization_id = %s
          AND provider_key = 'race-provider'
          AND connection_key = 'primary'
          AND provider_event_id = %s
        """,
        (organization_id, provider_event_id),
    ).fetchone() == (1, first.payload_hash, first.payload_hash)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r17_simultaneous_same_provider_identity_with_different_payload_conflicts(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn, "different-payload")
    provider_event_id = f"evt-{uuid4().hex}"
    accepted_payload: dict[str, object] = {"status": "delivered", "message_id": str(uuid4())}
    conflicting_payload: dict[str, object] = {
        "status": "failed",
        "message_id": accepted_payload["message_id"],
    }
    inserted = asyncio.Event()
    release_commit = asyncio.Event()
    second_pid: asyncio.Queue[int] = asyncio.Queue()

    first_task = asyncio.create_task(
        _record_and_hold_commit(
            app_session_factory,
            organization_id=organization_id,
            provider_event_id=provider_event_id,
            payload=accepted_payload,
            inserted=inserted,
            release_commit=release_commit,
        )
    )
    await inserted.wait()
    conflicting_task = asyncio.create_task(
        _record_with_pid(
            app_session_factory,
            organization_id=organization_id,
            provider_event_id=provider_event_id,
            payload=conflicting_payload,
            backend_pid=second_pid,
        )
    )
    await _wait_until_lock_blocked(admin_conn, await second_pid.get())
    release_commit.set()

    first = await first_task
    with pytest.raises(ProviderEventDedupeConflict):
        await conflicting_task

    stored = admin_conn.execute(
        """
        SELECT count(*), min(payload_hash), max(payload_hash)
        FROM request_engine.provider_events
        WHERE organization_id = %s
          AND provider_key = 'race-provider'
          AND connection_key = 'primary'
          AND provider_event_id = %s
        """,
        (organization_id, provider_event_id),
    ).fetchone()
    assert stored == (1, first.payload_hash, first.payload_hash)
