from typing import Any, Literal, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
ProviderTerminalStatus = Literal["dead", "rejected"]


def _organization(conn: PgConnection, label: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"provider-replay-{label}-{uuid4().hex}", f"Provider replay {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"provider-replay-operator-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _provider_event(
    conn: PgConnection,
    organization_id: UUID,
    *,
    status: ProviderTerminalStatus,
) -> UUID:
    processed_at_sql = "clock_timestamp()" if status == "rejected" else "NULL"
    row = conn.execute(
        f"""
        INSERT INTO request_engine.provider_events (
            organization_id, provider_key, connection_key,
            provider_event_id, payload_hash, payload, status,
            processed_at, attempt_count, max_attempts, last_error_class
        ) VALUES (
            %s, 'replay-provider', 'primary', %s, %s, '{{}}'::jsonb, %s,
            {processed_at_sql}, 8, 8, %s
        )
        RETURNING id
        """,  # noqa: S608 -- status selects one of two internal SQL literals only.
        (
            organization_id,
            f"event-{uuid4().hex}",
            uuid4().hex,
            status,
            f"terminal_{status}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.postgres
@pytest.mark.parametrize("terminal_status", ("dead", "rejected"))
def test_provider_event_admin_replay_is_privileged_preserves_history_and_is_audited(
    terminal_status: ProviderTerminalStatus,
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn, terminal_status)
    actor_id = _principal(admin_conn, organization_id)
    event_id = _provider_event(admin_conn, organization_id, status=terminal_status)
    correlation_id = uuid4()

    runtime: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        runtime.execute("SET ROLE request_engine_worker")
        with pytest.raises(Error) as exc_info:
            runtime.execute(
                """
                SELECT request_admin.replay_provider_event(
                    %s, %s, 3, 'worker must not replay provider work'
                )
                """,
                (organization_id, event_id),
            ).fetchone()
        assert exc_info.value.sqlstate == "42501"

        runtime.execute("RESET ROLE")
        runtime.execute("SET ROLE request_engine_admin")
        for key, value in {
            "request_engine.organization_id": str(organization_id),
            "request_engine.authenticated_principal_id": str(actor_id),
            "request_engine.principal_kind": "human",
            "request_engine.authentication_method": "test_admin_adapter",
            "request_engine.correlation_id": str(correlation_id),
        }.items():
            runtime.execute("SELECT set_config(%s, %s, false)", (key, value))

        replayed = runtime.execute(
            """
            SELECT request_admin.replay_provider_event(
                %s, %s, 3, 'operator approved provider replay'
            )
            """,
            (organization_id, event_id),
        ).fetchone()
    finally:
        runtime.close()

    assert replayed == (True,)
    state = admin_conn.execute(
        """
        SELECT status, processed_at, claim_token, lease_until,
               attempt_count, max_attempts, replay_count,
               last_replayed_at IS NOT NULL, last_error_class,
               next_attempt_at <= clock_timestamp()
        FROM request_engine.provider_events
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, event_id),
    ).fetchone()
    assert state == (
        "received",
        None,
        None,
        None,
        8,
        11,
        1,
        True,
        None,
        True,
    )

    audit = admin_conn.execute(
        """
        SELECT command_name, actor_principal_id,
               details->>'reason', details->>'additional_attempts',
               correlation_data->>'correlation_id',
               correlation_data->>'principal_kind',
               correlation_data->>'authentication_method'
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'ProviderEvent'
          AND aggregate_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (organization_id, event_id),
    ).fetchone()
    assert audit == (
        "admin.replay_provider_event",
        actor_id,
        "operator approved provider replay",
        "3",
        str(correlation_id),
        "human",
        "test_admin_adapter",
    )
