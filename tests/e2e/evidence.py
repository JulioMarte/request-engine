from __future__ import annotations

from dataclasses import dataclass

from . import operational_support as support


@dataclass(frozen=True, slots=True)
class DurableSnapshot:
    """Counts of durable state that security/isolation probes must not change."""

    reservations: int
    capacity_claims: int
    queue_entries: int
    requests: int
    outbox_messages: int
    scheduled_actions: int
    communication_tasks: int
    communication_deliveries: int
    provider_events: int


def durable_snapshot(conn: support.PgConnection) -> DurableSnapshot:
    row = conn.execute(
        """
        SELECT
            (SELECT count(*) FROM request_engine.reservations),
            (SELECT count(*) FROM request_engine.capacity_claims),
            (SELECT count(*) FROM request_engine.queue_entries),
            (SELECT count(*) FROM request_engine.requests),
            (SELECT count(*) FROM request_engine.outbox_messages),
            (SELECT count(*) FROM request_engine.scheduled_actions),
            (SELECT count(*) FROM request_engine.communication_tasks),
            (SELECT count(*) FROM request_engine.communication_deliveries),
            (SELECT count(*) FROM request_engine.provider_events)
        """
    ).fetchone()
    assert row is not None
    return DurableSnapshot(*row)
