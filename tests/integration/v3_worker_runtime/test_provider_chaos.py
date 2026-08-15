import os
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.events.errors import ProviderEventDedupeConflict
from request_engine.platform.events.provider_events import record_provider_event

PgConnection = Connection[Any]


def _organization(admin_conn: PgConnection, label: str) -> UUID:
    row = admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"provider-chaos-{label}-{uuid4().hex}", f"Provider chaos {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_provider_duplicate_replay_is_exact_and_payload_mutation_conflicts(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn, "dedupe")
    provider_event_id = f"evt-{uuid4().hex}"
    payload = {"status": "delivered", "message_id": str(uuid4())}

    async with tenant_transaction(app_session_factory, organization_id) as session:
        first = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="hostile-provider",
            connection_key="primary",
            provider_event_id=provider_event_id,
            payload=payload,
        )
    async with tenant_transaction(app_session_factory, organization_id) as session:
        replay = await record_provider_event(
            session,
            organization_id=organization_id,
            provider_key="hostile-provider",
            connection_key="primary",
            provider_event_id=provider_event_id,
            payload=payload,
        )

    assert replay.id == first.id
    assert replay.payload_hash == first.payload_hash
    assert replay.replay is True

    with pytest.raises(ProviderEventDedupeConflict):
        async with tenant_transaction(app_session_factory, organization_id) as session:
            await record_provider_event(
                session,
                organization_id=organization_id,
                provider_key="hostile-provider",
                connection_key="primary",
                provider_event_id=provider_event_id,
                payload={**payload, "status": "failed"},
            )

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.provider_events
        WHERE organization_id = %s
          AND provider_key = 'hostile-provider'
          AND connection_key = 'primary'
          AND provider_event_id = %s
        """,
        (organization_id, provider_event_id),
    ).fetchone() == (1,)


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
def test_terminal_provider_event_cannot_be_reopened_by_stale_worker(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn, "terminal")
    row = admin_conn.execute(
        """
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload,
            next_attempt_at
        ) VALUES (
            %s, 'hostile-provider', 'primary', %s, %s, '{}'::jsonb,
            clock_timestamp() - interval '1 minute'
        )
        RETURNING id
        """,
        (organization_id, f"terminal-{uuid4().hex}", uuid4().hex),
    ).fetchone()
    assert row is not None
    event_id = cast(UUID, row[0])

    # This test intentionally uses SET ROLE after bootstrap authentication. Runtime-role login
    # equivalence is tested independently by the shared F0 harness.
    conninfo = " ".join(
        (
            f"host={os.environ.get('PGHOST', '127.0.0.1')}",
            f"port={os.environ.get('PGPORT', '5432')}",
            f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}",
            f"user={os.environ.get('PGUSER', 'request_engine')}",
            f"password={os.environ.get('PGPASSWORD', 'request_engine')}",
        )
    )
    worker: PgConnection = psycopg.connect(conninfo, autocommit=True)
    try:
        worker.execute("SET ROLE request_engine_worker")
        claims = worker.execute(
            """
            SELECT provider_event_row_id, claim_token
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
            """
        ).fetchall()
        claim = next(value for value in claims if value[0] == event_id)
        token = cast(UUID, claim[1])
        assert worker.execute(
            "SELECT request_cmd.reject_provider_event(%s, %s, 'invalid_payload')",
            (event_id, token),
        ).fetchone() == (True,)

        assert worker.execute(
            "SELECT request_cmd.complete_provider_event(%s, %s)",
            (event_id, token),
        ).fetchone() == (False,)
        assert worker.execute(
            "SELECT request_cmd.retry_provider_event_after(%s, %s, interval '0', 'late')",
            (event_id, token),
        ).fetchone() == ("stale",)

        later_claims = worker.execute(
            """
            SELECT provider_event_row_id
            FROM request_cmd.claim_provider_events(500, interval '30 seconds')
            """
        ).fetchall()
        assert event_id not in {value[0] for value in later_claims}
    finally:
        worker.close()

    assert admin_conn.execute(
        """
        SELECT status, processed_at IS NOT NULL, claim_token, lease_until
        FROM request_engine.provider_events
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, event_id),
    ).fetchone() == ("rejected", True, None, None)
