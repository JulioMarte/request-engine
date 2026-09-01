"""Staff contact durable-intent atomicity and the 0025 monotone guard.

The verification request commits the pending-code row state and the outbox
event in ONE transaction: while the command transaction is held at the audit
append point, neither is visible to another connection; both appear after
commit. After confirmation, a direct SQL downgrade of `verified` is rejected
with SQLSTATE 23514 for the runtime role and for the table owner.
"""

import asyncio

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from request_engine.platform.db.session import SessionFactory

from ._party_support import (
    PgConnection,
    connect,
    lock_audit_barrier,
    outbox_rows,
    wait_until_query_blocked,
)
from ._staff_support import (
    EVENT_TYPE,
    confirm_command,
    request_command,
    staff_row,
    world_with_registered_contact,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]


@pytest.mark.asyncio
async def test_row_state_and_outbox_commit_in_one_transaction(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    blocker = connect()
    try:
        lock_audit_barrier(blocker)
        task = asyncio.create_task(
            commands.request_principal_contact_verification(
                request_command(world, contact.contact_id, key="req-barrier")
            )
        )
        await wait_until_query_blocked(
            admin_conn,
            "%INSERT INTO request_engine.audit_records%",
            "request never parked at the audit append point",
        )
        assert staff_row(admin_conn, world.organization_id, contact.contact_id)[2] is None
        assert outbox_rows(admin_conn, world.organization_id, EVENT_TYPE) == []
        blocker.commit()
        await asyncio.wait_for(task, timeout=5)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[2] is not None
    assert len(outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)) == 1


@pytest.mark.asyncio
async def test_verified_contact_cannot_be_downgraded_by_any_role(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    world, commands, contact = await world_with_registered_contact(admin_conn, app_session_factory)
    await commands.request_principal_contact_verification(
        request_command(world, contact.contact_id, key="req-guard")
    )
    events = outbox_rows(admin_conn, world.organization_id, EVENT_TYPE)
    code = events[0]["code"]
    await commands.confirm_principal_contact(
        confirm_command(world, contact.contact_id, code, key="confirm-guard")
    )
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[0] is True

    async with app_session_factory() as session:
        await session.execute(
            text("SELECT set_config('request_engine.organization_id', :org, true)"),
            {"org": str(world.organization_id)},
        )
        with pytest.raises(DBAPIError) as runtime_error:
            await session.execute(
                text(
                    "UPDATE request_engine.principal_contacts SET verified = false"
                    " WHERE id = :contact_id"
                ),
                {"contact_id": contact.contact_id},
            )
        assert getattr(runtime_error.value.orig, "sqlstate", None) == "23514"

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        admin_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(world.organization_id),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(
                "UPDATE request_engine.principal_contacts SET verified = false WHERE id = %s",
                (contact.contact_id,),
            )
    finally:
        admin_conn.execute("RESET ROLE")
    assert staff_row(admin_conn, world.organization_id, contact.contact_id)[0] is True
