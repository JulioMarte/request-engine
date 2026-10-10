"""Worker admission rejects malformed work before touching DB or provider."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from request_engine.modules.communications.adapters.worker.staff_invitation_delivery import (
    StaffInvitationDeliveryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import (
    PostgresScheduledActionWorker,
    ScheduledActionLease,
)
from request_engine.platform.worker.runtime import PermanentWorkError


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["owner", "version", "kind", "id", "extra_payload", "action"])
async def test_malformed_invitation_work_fails_before_db_or_provider(defect: str) -> None:
    delivery_id = uuid4()
    lease = ScheduledActionLease(
        id=uuid4(),
        organization_id=uuid4(),
        claim_token=uuid4(),
        owner_module="communications",
        action_type="dispatch_staff_invitation",
        action_version=1,
        subject_kind="StaffInvitationDelivery",
        subject_id=delivery_id,
        payload={"delivery_id": str(delivery_id)},
        attempt_count=1,
        lease_until=datetime.now(UTC) + timedelta(minutes=1),
    )
    if defect == "owner":
        lease = replace(lease, owner_module="tenancy")
    elif defect == "version":
        lease = replace(lease, action_version=2)
    elif defect == "kind":
        lease = replace(lease, subject_kind="CommunicationTask")
    elif defect == "id":
        lease = replace(lease, payload={"delivery_id": str(uuid4())})
    elif defect == "extra_payload":
        lease = replace(lease, payload={"delivery_id": str(delivery_id), "secret": "untrusted"})
    else:
        lease = replace(lease, action_type="dispatch_task")
    # None boundaries intentionally crash if admission reaches either dependency.
    handler = StaffInvitationDeliveryScheduledHandler(
        cast(SessionFactory, None),
        cast(PostgresScheduledActionWorker, None),
        None,
    )
    with pytest.raises(PermanentWorkError, match="unsupported_staff_invitation_delivery_action"):
        await handler.handle(lease)
