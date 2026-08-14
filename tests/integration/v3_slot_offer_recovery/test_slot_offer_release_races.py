import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
    accept_slot_offer,
)
from request_engine.modules.queue.application.commands.decline_slot_offer import (
    DeclineSlotOfferCommand,
    decline_slot_offer,
)
from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
    expire_slot_offer,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.modules.queue.application.errors import (
    SlotOfferExpired,
    SlotOfferNotActionable,
    SlotOfferRevisionConflict,
)
from request_engine.platform.db.session import SessionFactory

from .test_slot_offer_recovery import _fixture, _prepare

PgConnection = Connection[Any]


async def _issue_offer(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    *,
    ttl: timedelta,
):
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, second_entry_id = await _prepare(
        fixture,
        session_factory,
    )
    offer = await offer_next_waitlist_candidate(
        commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_opportunity_id=opportunity_id,
            offer_expires_at=datetime.now(UTC) + ttl,
            idempotency_key=f"race-offer-{uuid4().hex}",
        ),
    )
    assert offer is not None
    assert offer.waitlist_entry_id == first_entry_id
    return fixture, commands, opportunity_id, second_entry_id, offer


async def _start_behind_opportunity_lock(
    admin_conn: PgConnection,
    *,
    organization_id,
    opportunity_id,
    coroutines,
    hold_seconds: float = 0.1,
):
    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
              FROM request_engine.slot_opportunities
             WHERE organization_id = %s
               AND id = %s
             FOR UPDATE
            """,
            (organization_id, opportunity_id),
        ).fetchone()
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        await asyncio.sleep(hold_seconds)

    return await asyncio.gather(*tasks, return_exceptions=True)


def _terminal_graph(
    admin_conn: PgConnection,
    *,
    organization_id,
    opportunity_id,
    offer_id,
):
    row = admin_conn.execute(
        """
        SELECT so.status,
               h.status,
               o.status,
               (SELECT count(*)
                  FROM request_engine.reservations r
                 WHERE r.organization_id = so.organization_id
                   AND r.id = h.reservation_id),
               (SELECT count(*)
                  FROM request_engine.slot_offers active_offer
                 WHERE active_offer.organization_id = so.organization_id
                   AND active_offer.slot_opportunity_id = so.slot_opportunity_id
                   AND active_offer.status = 'offered')
          FROM request_engine.slot_offers so
          JOIN request_engine.capacity_holds h
            ON h.organization_id = so.organization_id
           AND h.id = so.capacity_hold_id
          JOIN request_engine.slot_opportunities o
            ON o.organization_id = so.organization_id
           AND o.id = so.slot_opportunity_id
         WHERE so.organization_id = %s
           AND so.slot_opportunity_id = %s
           AND so.id = %s
        """,
        (organization_id, opportunity_id, offer_id),
    ).fetchone()
    assert row is not None
    return row


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_accept_and_decline_serialize_to_one_terminal_effect(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, commands, opportunity_id, _, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(minutes=5),
    )

    accept_result, decline_result = await _start_behind_opportunity_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        coroutines=(
            accept_slot_offer(
                commands,
                AcceptSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-accept-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            decline_slot_offer(
                commands,
                DeclineSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-decline-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
        ),
    )

    accept_succeeded = not isinstance(accept_result, BaseException)
    decline_succeeded = not isinstance(decline_result, BaseException)
    assert accept_succeeded + decline_succeeded == 1

    loser = decline_result if accept_succeeded else accept_result
    assert isinstance(loser, SlotOfferRevisionConflict)

    graph = _terminal_graph(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        offer_id=offer.id,
    )
    if accept_succeeded:
        assert graph == ("accepted", "consumed", "filled", 1, 0)
    else:
        assert graph == ("declined", "released", "open", 0, 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_accept_wins_semantically_against_premature_expiry(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, commands, opportunity_id, _, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(minutes=5),
    )

    accept_result, expire_result = await _start_behind_opportunity_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        coroutines=(
            accept_slot_offer(
                commands,
                AcceptSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-accept-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            expire_slot_offer(
                commands,
                ExpireSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-expire-{uuid4().hex}",
                ),
            ),
        ),
    )

    assert not isinstance(accept_result, BaseException)
    if isinstance(expire_result, BaseException):
        assert isinstance(expire_result, SlotOfferNotActionable)

    assert _terminal_graph(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        offer_id=offer.id,
    ) == ("accepted", "consumed", "filled", 1, 0)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_expiry_wins_semantically_once_offer_is_expired(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, commands, opportunity_id, second_entry_id, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(seconds=1),
    )

    accept_result, expire_result = await _start_behind_opportunity_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        coroutines=(
            accept_slot_offer(
                commands,
                AcceptSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-accept-expired-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            expire_slot_offer(
                commands,
                ExpireSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-expire-{uuid4().hex}",
                ),
            ),
        ),
        hold_seconds=1.2,
    )

    assert not isinstance(expire_result, BaseException)
    assert isinstance(accept_result, (SlotOfferExpired, SlotOfferRevisionConflict))
    assert _terminal_graph(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        offer_id=offer.id,
    ) == ("expired", "expired", "open", 0, 1)

    next_offer = admin_conn.execute(
        """
        SELECT waitlist_entry_id
          FROM request_engine.slot_offers
         WHERE organization_id = %s
           AND slot_opportunity_id = %s
           AND status = 'offered'
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchone()
    assert next_offer == (second_entry_id,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_decline_cannot_release_twice_when_expiry_is_due(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture, commands, opportunity_id, second_entry_id, offer = await _issue_offer(
        admin_conn,
        session_factory,
        ttl=timedelta(seconds=1),
    )

    decline_result, expire_result = await _start_behind_opportunity_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        coroutines=(
            decline_slot_offer(
                commands,
                DeclineSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-decline-expired-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            expire_slot_offer(
                commands,
                ExpireSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=offer.revision,
                    idempotency_key=f"race-expire-{uuid4().hex}",
                ),
            ),
        ),
        hold_seconds=1.2,
    )

    assert not isinstance(expire_result, BaseException)
    assert isinstance(decline_result, (SlotOfferExpired, SlotOfferRevisionConflict))
    assert _terminal_graph(
        admin_conn,
        organization_id=fixture.organization_id,
        opportunity_id=opportunity_id,
        offer_id=offer.id,
    ) == ("expired", "expired", "open", 0, 1)

    next_offers = admin_conn.execute(
        """
        SELECT waitlist_entry_id
          FROM request_engine.slot_offers
         WHERE organization_id = %s
           AND slot_opportunity_id = %s
           AND status = 'offered'
         ORDER BY id
        """,
        (fixture.organization_id, opportunity_id),
    ).fetchall()
    assert next_offers == [(second_entry_id,)]
