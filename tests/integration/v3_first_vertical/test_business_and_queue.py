import asyncio
import json
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.catalog.adapters.db.business_info_reader import (
    PostgresBusinessInfoReader,
)
from request_engine.modules.catalog.application.queries.get_business_info import (
    get_business_info,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_reader import (
    PostgresServiceQueueReader,
)
from request_engine.modules.queue.application.commands.call_next import (
    CallNextCommand,
    call_next,
)
from request_engine.modules.queue.application.commands.join_queue import (
    JoinQueueCommand,
    join_queue,
)
from request_engine.modules.queue.application.queries.get_queue_status import get_queue_status
from request_engine.modules.queue.contracts.service_queue import QueueEntryStatus
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_organization(conn: PgConnection, *, profile: dict[str, object] | None = None) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (
            organization_key, display_name, public_profile
        ) VALUES (%s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            f"vertical-{suffix}",
            f"Medical Practice {suffix}",
            json.dumps(profile or {}),
        ),
    )


def _create_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"staff-{uuid4().hex}"),
    )


def _create_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    )


def _create_queue(conn: PgConnection, organization_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name
        ) VALUES (%s, %s, 'Walk-in patients')
        RETURNING id
        """,
        (organization_id, f"walk-in-{uuid4().hex}"),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_business_get_info_returns_structured_profile_and_locations(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _create_organization(
        admin_conn,
        profile={"phone": "+18095550100", "summary": "General medical practice"},
    )
    location_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.locations (
            organization_id,
            location_key,
            display_name,
            timezone,
            public_data
        ) VALUES (%s, 'main', 'Main office', 'America/Santo_Domingo', %s::jsonb)
        RETURNING id
        """,
        (organization_id, json.dumps({"address": "Puerto Plata"})),
    )

    info = await get_business_info(
        PostgresBusinessInfoReader(session_factory),
        organization_id,
    )

    assert info.organization_id == organization_id
    assert info.public_profile["phone"] == "+18095550100"
    assert len(info.locations) == 1
    assert info.locations[0].id == location_id
    assert info.locations[0].timezone == "America/Santo_Domingo"
    assert info.locations[0].public_data == {"address": "Puerto Plata"}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_join_queue_is_idempotent_and_status_reports_entries_ahead(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _create_organization(admin_conn)
    principal_id = _create_principal(admin_conn, organization_id)
    queue_id = _create_queue(admin_conn, organization_id)
    first_subject = _create_party(admin_conn, organization_id, "First patient")
    second_subject = _create_party(admin_conn, organization_id, "Second patient")
    commands = PostgresServiceQueueCommands(session_factory)

    first = await join_queue(
        commands,
        JoinQueueCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            subject_party_id=first_subject,
            idempotency_key=f"join-{uuid4().hex}",
        ),
    )
    second_key = f"join-{uuid4().hex}"
    second_command = JoinQueueCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        subject_party_id=second_subject,
        idempotency_key=second_key,
    )
    second = await join_queue(commands, second_command)
    replay = await join_queue(commands, second_command)

    assert replay == second
    assert first.status is QueueEntryStatus.WAITING
    assert second.status is QueueEntryStatus.WAITING

    status = await get_queue_status(
        PostgresServiceQueueReader(session_factory),
        organization_id=organization_id,
        queue_id=queue_id,
        subject_party_id=second_subject,
    )
    assert status.entry == second
    assert status.entries_ahead == 1

    entry_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.queue_entries
        WHERE organization_id = %s
          AND service_queue_id = %s
          AND subject_party_id = %s
        """,
        (organization_id, queue_id, second_subject),
    ).fetchone()
    assert entry_count == (1,)

    audit_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND command_name = 'queue.join'
        """,
        (organization_id,),
    ).fetchone()
    assert audit_count == (2,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_call_next_is_fifo_idempotent_and_emits_outbox(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _create_organization(admin_conn)
    principal_id = _create_principal(admin_conn, organization_id)
    queue_id = _create_queue(admin_conn, organization_id)
    first_subject = _create_party(admin_conn, organization_id, "Patient A")
    second_subject = _create_party(admin_conn, organization_id, "Patient B")

    first_entry = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id, admitted_at
        ) VALUES (%s, %s, %s, '2026-08-11 12:00:00+00')
        RETURNING id
        """,
        (organization_id, queue_id, first_subject),
    )
    second_entry = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id, admitted_at
        ) VALUES (%s, %s, %s, '2026-08-11 12:01:00+00')
        RETURNING id
        """,
        (organization_id, queue_id, second_subject),
    )

    commands = PostgresServiceQueueCommands(session_factory)
    first_key = f"call-{uuid4().hex}"
    first_command = CallNextCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        idempotency_key=first_key,
    )
    first_called = await call_next(commands, first_command)
    replay = await call_next(commands, first_command)
    second_called = await call_next(
        commands,
        CallNextCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            queue_id=queue_id,
            idempotency_key=f"call-{uuid4().hex}",
        ),
    )

    assert first_called is not None
    assert replay == first_called
    assert second_called is not None
    assert first_called.id == first_entry
    assert second_called.id == second_entry
    assert first_called.status is QueueEntryStatus.CALLED
    assert second_called.status is QueueEntryStatus.CALLED

    outbox_rows = admin_conn.execute(
        """
        SELECT aggregate_id
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'queue.entry_called.v1'
        ORDER BY occurred_at, id
        """,
        (organization_id,),
    ).fetchall()
    assert [row[0] for row in outbox_rows] == [first_entry, second_entry]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_call_next_never_returns_same_entry(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id = _create_organization(admin_conn)
    principal_id = _create_principal(admin_conn, organization_id)
    queue_id = _create_queue(admin_conn, organization_id)
    first_subject = _create_party(admin_conn, organization_id, "Patient C")
    second_subject = _create_party(admin_conn, organization_id, "Patient D")

    expected_ids = {
        _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.queue_entries (
                organization_id, service_queue_id, subject_party_id, admitted_at
            ) VALUES (%s, %s, %s, '2026-08-11 13:00:00+00')
            RETURNING id
            """,
            (organization_id, queue_id, first_subject),
        ),
        _uuid_row(
            admin_conn,
            """
            INSERT INTO request_engine.queue_entries (
                organization_id, service_queue_id, subject_party_id, admitted_at
            ) VALUES (%s, %s, %s, '2026-08-11 13:01:00+00')
            RETURNING id
            """,
            (organization_id, queue_id, second_subject),
        ),
    }

    commands = PostgresServiceQueueCommands(session_factory)
    first_command = CallNextCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        idempotency_key=f"concurrent-{uuid4().hex}",
    )
    second_command = CallNextCommand(
        organization_id=organization_id,
        principal_id=principal_id,
        queue_id=queue_id,
        idempotency_key=f"concurrent-{uuid4().hex}",
    )

    first_result, second_result = await asyncio.gather(
        call_next(commands, first_command),
        call_next(commands, second_command),
    )

    assert first_result is not None
    assert second_result is not None
    assert {first_result.id, second_result.id} == expected_ids
    assert first_result.id != second_result.id
