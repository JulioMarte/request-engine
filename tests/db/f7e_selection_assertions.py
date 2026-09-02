from typing import Any, cast
from uuid import UUID, uuid4

from f7e_selection_fixture import F7eSelectionFixture
from psycopg import Connection

from request_engine.modules.queue.application.commands.call_next import CallNextCommand

PgConnection = Connection[Any]


def call_next_command(world: F7eSelectionFixture, suffix: str) -> CallNextCommand:
    return CallNextCommand(
        organization_id=world.organization_id,
        principal_id=world.principal_id,
        queue_id=world.queue_id,
        idempotency_key=f"call-{suffix}-{uuid4().hex}",
    )


def entry_state(conn: PgConnection, entry_id: UUID) -> tuple[str, object, int]:
    row = conn.execute(
        "SELECT status, admitted_at, revision FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert row is not None
    return cast(tuple[str, object, int], row)


def entry_status(conn: PgConnection, entry_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.queue_entries WHERE id=%s",
        (entry_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])
