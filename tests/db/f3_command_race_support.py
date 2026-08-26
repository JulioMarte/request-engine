from collections.abc import Sequence
from uuid import UUID

from f3_live_ops_fixture import PgConnection


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


def assert_one_winner(
    results: Sequence[object],
    result_types: tuple[type, ...],
) -> None:
    assert sum(isinstance(result, result_types) for result in results) == 1
    assert sum(isinstance(result, Exception) for result in results) == 1
