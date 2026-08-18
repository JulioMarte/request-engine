# pyright: reportPrivateUsage=false

import asyncio
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
    accept_slot_offer,
)
from request_engine.modules.queue.application.errors import SlotOfferRevisionConflict
from request_engine.platform.db.session import SessionFactory

from .test_slot_offer_release_races import _issue_offer

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i38_database_rejects_second_active_offer_for_one_opportunity(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, _commands, opportunity_id, second_entry_id, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(minutes=5),
    )
    hold_row = admin_conn.execute(
        """
        SELECT capacity_hold_id, expires_at
        FROM request_engine.slot_offers
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, offer.id),
    ).fetchone()
    assert hold_row is not None
    hold_id = cast(UUID, hold_row[0])
    expires_at = hold_row[1]

    with pytest.raises(Error) as duplicate_error:
        admin_conn.execute(
            """
            INSERT INTO request_engine.slot_offers (
                organization_id,
                slot_opportunity_id,
                waitlist_entry_id,
                capacity_hold_id,
                expires_at
            ) VALUES (%s, %s, %s, %s, %s)
            """,
            (
                fixture.organization_id,
                opportunity_id,
                second_entry_id,
                hold_id,
                expires_at,
            ),
        )
    assert duplicate_error.value.sqlstate == "23505"

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.slot_offers
        WHERE organization_id = %s
          AND slot_opportunity_id = %s
          AND status = 'offered'
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_i42_two_accepts_can_fill_one_opportunity_only_once(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, commands, opportunity_id, _second_entry_id, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(minutes=5),
    )

    async def accept(key: str) -> object:
        return await accept_slot_offer(
            commands,
            AcceptSlotOfferCommand(
                organization_id=fixture.organization_id,
                principal_id=fixture.principal_id,
                slot_offer_id=offer.id,
                expected_revision=offer.revision,
                idempotency_key=key,
                allow_subject_override=True,
            ),
        )

    results = await asyncio.gather(
        accept(f"i42-a-{uuid4().hex}"),
        accept(f"i42-b-{uuid4().hex}"),
        return_exceptions=True,
    )
    successes = [result for result in results if not isinstance(result, BaseException)]
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], SlotOfferRevisionConflict)

    graph = admin_conn.execute(
        """
        SELECT o.status,
               so.status,
               h.status,
               count(DISTINCT cc.reservation_id) FILTER (
                   WHERE cc.reservation_id IS NOT NULL
               )
        FROM request_engine.slot_opportunities o
        JOIN request_engine.slot_offers so
          ON so.organization_id = o.organization_id
         AND so.slot_opportunity_id = o.id
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id
         AND h.id = so.capacity_hold_id
        LEFT JOIN request_engine.capacity_claims cc
          ON cc.organization_id = so.organization_id
         AND cc.hold_id = so.capacity_hold_id
        WHERE o.organization_id = %s AND o.id = %s
        GROUP BY o.status, so.status, h.status
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone()
    assert graph == ("filled", "accepted", "consumed", 1)
