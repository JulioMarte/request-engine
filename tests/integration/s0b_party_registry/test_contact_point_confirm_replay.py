"""I-S0b-4 (race): concurrent confirm replay executes a single verification flip.

Two independent transactions run the real `parties.confirm_contact_point`
command with the same idempotency key. Deterministic synchronization holds
both before any commit: the first parks at the audit append point holding the
contact point row lock; the second blocks on the idempotency identity the
first created. Only one transaction executes the UPDATE (one audit record
with `already_verified = false`); both callers observe success and the
durable state is `verified = true`.
"""

import asyncio

import pytest

from request_engine.modules.tenancy.application.commands.confirm_party_contact_point import (
    confirm_party_contact_point,
)
from request_engine.platform.db.session import SessionFactory

from ._party_commands import (
    confirm_command,
    confirm_key,
    registry_commands,
    secondhand_unverified_contact_point,
)
from ._party_support import (
    PgConnection,
    audit_rows,
    connect,
    contact_point_row,
    lock_audit_barrier,
    wait_until_query_blocked,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]


@pytest.mark.asyncio
async def test_concurrent_confirm_replay_executes_single_flip(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    world, party, contact = await secondhand_unverified_contact_point(
        admin_conn, app_session_factory
    )
    commands = registry_commands(app_session_factory)
    key = confirm_key(contact.contact_point_id)
    blocker = connect()
    try:
        lock_audit_barrier(blocker)
        first_task = asyncio.create_task(
            confirm_party_contact_point(
                commands,
                confirm_command(
                    world.organization_id,
                    world.operator_principal_id,
                    party.party_id,
                    contact.contact_point_id,
                    key=key,
                ),
            )
        )
        await wait_until_query_blocked(
            admin_conn,
            "%INSERT INTO request_engine.audit_records%",
            "first confirm never parked at the audit append point",
        )
        second_task = asyncio.create_task(
            confirm_party_contact_point(
                commands,
                confirm_command(
                    world.organization_id,
                    world.operator_principal_id,
                    party.party_id,
                    contact.contact_point_id,
                    key=key,
                ),
            )
        )
        await wait_until_query_blocked(
            admin_conn,
            "%request_cmd.acquire_idempotency%",
            "second confirm never blocked on the idempotency identity",
        )
        blocker.commit()
        first = await asyncio.wait_for(first_task, timeout=5)
        second = await asyncio.wait_for(second_task, timeout=5)
    finally:
        if not blocker.closed:
            blocker.rollback()
        blocker.close()

    assert first.verified and second.verified
    assert first.contact_point_id == second.contact_point_id
    assert contact_point_row(admin_conn, world.organization_id, contact.contact_point_id) == (
        True,
        "subject",
        True,
    )
    audits = audit_rows(admin_conn, world.organization_id, "parties.confirm_contact_point")
    assert len(audits) == 1 and audits[0]["already_verified"] is False
