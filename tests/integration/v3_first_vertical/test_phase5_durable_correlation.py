from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory, actor_transaction
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.scheduling.store import schedule_action
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_correlation_survives_outbox_and_scheduled_action_handoff(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"correlation-{suffix}", f"Correlation {suffix}"),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    correlation_id = uuid4()
    aggregate_id = uuid4()
    actor = ActorContext(
        organization_id=organization_id,
        principal_id=principal_id,
        capabilities=frozenset(),
        correlation_id=correlation_id,
        authentication_method="test_adapter",
    )

    async with actor_transaction(session_factory, actor) as session:
        await append_outbox(
            session,
            organization_id=organization_id,
            event_type="test.correlation.v1",
            aggregate_kind="CorrelationProbe",
            aggregate_id=aggregate_id,
            payload={"probe": True},
        )
        action_id = await schedule_action(
            session,
            organization_id=organization_id,
            owner_module="platform",
            action_type="test.correlation",
            action_version=1,
            dedupe_key=f"correlation:{aggregate_id}",
            execute_at=datetime.now(UTC),
            payload={"probe": True},
        )

    outbox = admin_conn.execute(
        """
        SELECT correlation_data->>'correlation_id'
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'test.correlation.v1'
          AND aggregate_id = %s
        """,
        (organization_id, aggregate_id),
    ).fetchone()
    scheduled = admin_conn.execute(
        """
        SELECT correlation_data->>'correlation_id'
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, action_id),
    ).fetchone()

    assert outbox == (str(correlation_id),)
    assert scheduled == (str(correlation_id),)
