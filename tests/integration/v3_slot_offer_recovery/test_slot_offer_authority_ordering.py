# pyright: reportPrivateUsage=false

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
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    offer_next_waitlist_candidate,
)
from request_engine.modules.queue.application.errors import SubjectAuthorityRequired
from request_engine.platform.db.session import SessionFactory

from .test_slot_offer_recovery import _fixture, _offer_command, _prepare

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.parametrize("operation", ["accept", "decline"])
async def test_slot_offer_manage_authority_precedes_revision_and_lifecycle_disclosure(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
    operation: str,
) -> None:
    fixture = _fixture(admin_conn)
    commands, opportunity_id, first_entry_id, _ = await _prepare(
        fixture,
        app_session_factory,
    )
    offer = await offer_next_waitlist_candidate(
        commands,
        _offer_command(
            fixture,
            opportunity_id,
            key=f"authority-order-offer-{uuid4().hex}",
        ),
    )
    assert offer is not None

    # Deliberately stale/incorrect revision. A caller with the action capability but
    # no waitlist.manage Representation must not learn whether that revision is
    # current, nor any SlotOffer lifecycle detail, before Party authority is denied.
    stale_revision = offer.revision + 99
    with pytest.raises(SubjectAuthorityRequired):
        if operation == "accept":
            await accept_slot_offer(
                commands,
                AcceptSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=stale_revision,
                    idempotency_key=f"authority-order-accept-{uuid4().hex}",
                    allow_subject_override=False,
                ),
            )
        else:
            await decline_slot_offer(
                commands,
                DeclineSlotOfferCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    slot_offer_id=offer.id,
                    expected_revision=stale_revision,
                    idempotency_key=f"authority-order-decline-{uuid4().hex}",
                    allow_subject_override=False,
                ),
            )

    state = admin_conn.execute(
        """
        SELECT so.status,
               so.revision,
               h.status,
               o.status,
               w.status,
               (
                   SELECT count(*)
                   FROM request_engine.reservations r
                   WHERE r.organization_id = so.organization_id
                     AND r.subject_party_id = w.subject_party_id
               ) AS reservation_count
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_holds h
          ON h.organization_id = so.organization_id
         AND h.id = so.capacity_hold_id
        JOIN request_engine.slot_opportunities o
          ON o.organization_id = so.organization_id
         AND o.id = so.slot_opportunity_id
        JOIN request_engine.waitlist_entries w
          ON w.organization_id = so.organization_id
         AND w.id = so.waitlist_entry_id
        WHERE so.organization_id = %s
          AND so.id = %s
          AND w.id = %s
        """,
        (fixture.organization_id, offer.id, first_entry_id),
    ).fetchone()
    assert state == ("offered", offer.revision, "active", "open", "active", 0)
