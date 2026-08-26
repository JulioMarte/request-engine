from collections.abc import Sequence
from uuid import UUID

from f3_live_ops_fixture import LiveOpsFixture, PgConnection


def align_fixture_to_db_clock(
    conn: PgConnection,
    setup: LiveOpsFixture,
) -> dict[UUID, int]:
    """Move command-race setup around PostgreSQL's real clock and return revisions."""

    conn.execute(
        "UPDATE request_engine.resource_location_assignments "
        "SET effective_during=tstzrange(clock_timestamp()-interval '1 day',"
        "upper(effective_during),'[)') "
        "WHERE organization_id=%s AND resource_id=%s AND location_id=%s",
        (setup.organization_id, setup.resource_id, setup.location_id),
    )
    conn.execute(
        "WITH observed AS (SELECT clock_timestamp() AS now) "
        "UPDATE request_engine.queue_entries AS entry SET "
        "arrived_at=observed.now-interval '6 minutes',"
        "admitted_at=observed.now-interval '5 minutes',"
        "called_at=observed.now-interval '4 minutes',"
        "updated_at=observed.now "
        "FROM observed WHERE entry.id IN (%s,%s)",
        (setup.entry_a_id, setup.entry_b_id),
    )
    rows = conn.execute(
        "SELECT id,revision FROM request_engine.queue_entries WHERE id IN (%s,%s)",
        (setup.entry_a_id, setup.entry_b_id),
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def effects(
    conn: PgConnection,
    organization_id: UUID,
    command: str,
    event: str,
) -> tuple[int, int]:
    audit = conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE organization_id=%s AND command_name=%s",
        (organization_id, command),
    ).fetchone()
    outbox = conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id=%s AND event_type=%s",
        (organization_id, event),
    ).fetchone()
    assert audit is not None and outbox is not None
    return audit[0], outbox[0]


def idempotency_state(
    conn: PgConnection,
    organization_id: UUID,
    principal_id: UUID,
    key: str,
) -> str | None:
    row = conn.execute(
        "SELECT status FROM request_engine.idempotency_records "
        "WHERE organization_id=%s AND principal_id=%s AND idempotency_key=%s",
        (organization_id, principal_id, key),
    ).fetchone()
    return None if row is None else row[0]


def assert_idempotency_outcome(
    conn: PgConnection,
    organization_id: UUID,
    principal_id: UUID,
    winner_key: str,
    loser_key: str,
) -> None:
    assert idempotency_state(conn, organization_id, principal_id, winner_key) == "completed"
    assert idempotency_state(conn, organization_id, principal_id, loser_key) is None


def assert_one_winner(
    results: Sequence[object],
    result_types: tuple[type, ...],
) -> None:
    detail = repr(tuple(results))
    assert sum(isinstance(result, result_types) for result in results) == 1, detail
    assert sum(isinstance(result, Exception) for result in results) == 1, detail
