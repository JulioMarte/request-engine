from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
)
from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
    evaluate_no_show,
)
from request_engine.modules.booking.contracts.slot_offer_capacity import SlotOfferCapacityPort
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
    expire_slot_offer,
)
from request_engine.modules.queue.application.slot_offer_notifications import (
    SlotOfferNotificationPort,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.worker.runtime import LeaseLostWorkError

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"domain-fence-{suffix}", f"Domain Fence {suffix}"),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_stale_no_show_claim_fails_before_booking_authoritative_access(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    commands = PostgresAttendanceCommands(app_session_factory)

    with pytest.raises(LeaseLostWorkError, match="no_show_authoritative_fence_lost"):
        await evaluate_no_show(
            commands,
            EvaluateNoShowCommand(
                organization_id=organization_id,
                principal_id=uuid4(),
                reservation_id=uuid4(),
                idempotency_key=f"stale-no-show-{uuid4().hex}",
                scheduled_action_id=uuid4(),
                scheduled_action_claim_token=uuid4(),
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_stale_slot_offer_expiry_claim_fails_before_queue_authoritative_access(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id = _organization(admin_conn)
    commands = PostgresSlotOfferCommands(
        app_session_factory,
        capacity=cast(SlotOfferCapacityPort, object()),
        notification=cast(SlotOfferNotificationPort, object()),
    )

    with pytest.raises(
        LeaseLostWorkError,
        match="slot_offer_expiry_authoritative_fence_lost",
    ):
        await expire_slot_offer(
            commands,
            ExpireSlotOfferCommand(
                organization_id=organization_id,
                principal_id=uuid4(),
                slot_offer_id=uuid4(),
                expected_revision=1,
                idempotency_key=f"stale-expiry-{uuid4().hex}",
                scheduled_action_id=uuid4(),
                scheduled_action_claim_token=uuid4(),
            ),
        )
