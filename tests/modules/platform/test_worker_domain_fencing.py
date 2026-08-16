from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.booking.adapters.db.lifecycle_scheduling import (
    NO_SHOW_ACTION_TYPE,
    NO_SHOW_ACTION_VERSION,
)
from request_engine.modules.booking.adapters.worker.no_show import NoShowScheduledHandler
from request_engine.modules.booking.application.commands.evaluate_no_show import (
    EvaluateNoShowCommand,
    EvaluateNoShowHandler,
    evaluate_no_show,
)
from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState
from request_engine.modules.queue.adapters.worker.slot_offer_expiry import (
    SLOT_OFFER_EXPIRY_ACTION_TYPE,
    SLOT_OFFER_EXPIRY_ACTION_VERSION,
    SlotOfferExpiryScheduledHandler,
)
from request_engine.modules.queue.application.commands.expire_slot_offer import (
    ExpireSlotOfferCommand,
    ExpireSlotOfferExecutor,
    expire_slot_offer,
)
from request_engine.modules.queue.contracts.waitlist import SlotOfferResolution
from request_engine.platform.scheduling.postgres import ScheduledActionLease


class _NoShowCapture:
    def __init__(self) -> None:
        self.command: EvaluateNoShowCommand | None = None

    async def evaluate_no_show(
        self,
        command: EvaluateNoShowCommand,
    ) -> ReservationAttendanceState:
        self.command = command
        return cast(ReservationAttendanceState, object())


class _ExpiryCapture:
    def __init__(self) -> None:
        self.command: ExpireSlotOfferCommand | None = None

    async def expire_slot_offer(
        self,
        command: ExpireSlotOfferCommand,
    ) -> SlotOfferResolution:
        self.command = command
        return cast(SlotOfferResolution, object())


def _lease(
    *,
    owner_module: str,
    action_type: str,
    action_version: int,
    subject_kind: str,
    subject_id: object,
    payload: dict[str, object],
) -> ScheduledActionLease:
    now = datetime.now(UTC)
    return ScheduledActionLease(
        id=uuid4(),
        organization_id=uuid4(),
        claim_token=uuid4(),
        owner_module=owner_module,
        action_type=action_type,
        action_version=action_version,
        subject_kind=subject_kind,
        subject_id=cast(object, subject_id),
        payload=payload,
        attempt_count=1,
        lease_until=now + timedelta(seconds=30),
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_show_adapter_propagates_current_claim_to_domain_command() -> None:
    reservation_id = uuid4()
    capture = _NoShowCapture()
    lease = _lease(
        owner_module="booking",
        action_type=NO_SHOW_ACTION_TYPE,
        action_version=NO_SHOW_ACTION_VERSION,
        subject_kind="Reservation",
        subject_id=reservation_id,
        payload={"reservation_id": str(reservation_id), "lifecycle_key": "generation-1"},
    )

    await NoShowScheduledHandler(capture, worker_principal_id=uuid4()).handle(lease)

    assert capture.command is not None
    assert capture.command.scheduled_action_id == lease.id
    assert capture.command.scheduled_action_claim_token == lease.claim_token


@pytest.mark.asyncio
@pytest.mark.unit
async def test_slot_offer_expiry_adapter_propagates_current_claim_to_domain_command() -> None:
    offer_id = uuid4()
    principal_id = uuid4()
    capture = _ExpiryCapture()
    lease = _lease(
        owner_module="queue",
        action_type=SLOT_OFFER_EXPIRY_ACTION_TYPE,
        action_version=SLOT_OFFER_EXPIRY_ACTION_VERSION,
        subject_kind="SlotOffer",
        subject_id=offer_id,
        payload={
            "slot_offer_id": str(offer_id),
            "expected_revision": 1,
            "principal_id": str(principal_id),
        },
    )

    await SlotOfferExpiryScheduledHandler(capture).handle(lease)

    assert capture.command is not None
    assert capture.command.scheduled_action_id == lease.id
    assert capture.command.scheduled_action_claim_token == lease.claim_token


@pytest.mark.asyncio
@pytest.mark.unit
async def test_no_show_command_rejects_partial_claim_identity() -> None:
    command = EvaluateNoShowCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        reservation_id=uuid4(),
        idempotency_key="test",
        scheduled_action_id=uuid4(),
    )

    with pytest.raises(ValueError, match="must be supplied together"):
        await evaluate_no_show(cast(EvaluateNoShowHandler, _NoShowCapture()), command)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_slot_offer_expiry_command_rejects_partial_claim_identity() -> None:
    command = ExpireSlotOfferCommand(
        organization_id=uuid4(),
        principal_id=uuid4(),
        slot_offer_id=uuid4(),
        expected_revision=1,
        idempotency_key="test",
        scheduled_action_claim_token=uuid4(),
    )

    with pytest.raises(ValueError, match="must be supplied together"):
        await expire_slot_offer(cast(ExpireSlotOfferExecutor, _ExpiryCapture()), command)
