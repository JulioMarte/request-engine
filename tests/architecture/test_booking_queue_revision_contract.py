import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.api.models import CancelReservationBody, RescheduleReservationBody
from request_engine.modules.booking.application.errors import ReservationRevisionConflict
from request_engine.modules.queue.api.errors import queue_error_handler
from request_engine.modules.queue.api.models import LeaveQueueBody
from request_engine.modules.queue.application.commands.leave_queue import LeaveQueueCommand
from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_appointment_mutations_require_positive_expected_revision() -> None:
    with pytest.raises(ValidationError):
        CancelReservationBody.model_validate({})
    with pytest.raises(ValidationError):
        CancelReservationBody.model_validate({"expected_revision": 0})

    reschedule_without_revision = {
        "start_at": "2026-08-17T13:00:00Z",
        "resources": [
            {"requirement_id": str(uuid4()), "resource_id": str(uuid4())},
        ],
    }
    with pytest.raises(ValidationError):
        RescheduleReservationBody.model_validate(reschedule_without_revision)
    with pytest.raises(ValidationError):
        RescheduleReservationBody.model_validate(
            {**reschedule_without_revision, "expected_revision": 0}
        )


def test_queue_leave_targets_entry_identity_and_revision_not_subject_body() -> None:
    entry_id = uuid4()
    body = LeaveQueueBody.model_validate({"expected_revision": 3, "reason": "left"})
    assert body.expected_revision == 3

    with pytest.raises(ValidationError):
        LeaveQueueBody.model_validate({"reason": "left"})
    with pytest.raises(ValidationError):
        LeaveQueueBody.model_validate(
            {
                "subject_party_id": str(uuid4()),
                "expected_revision": 3,
            }
        )

    command_fields = LeaveQueueCommand.__dataclass_fields__
    assert "queue_entry_id" in command_fields
    assert "expected_revision" in command_fields
    assert "subject_party_id" not in command_fields
    assert entry_id != uuid4()


@pytest.mark.asyncio
async def test_reservation_and_queue_entry_conflicts_share_revision_error_shape() -> None:
    reservation_id = uuid4()
    queue_entry_id = uuid4()

    reservation_response = await booking_error_handler(
        _request(),
        ReservationRevisionConflict(reservation_id, 2, 3),
    )
    queue_response = await queue_error_handler(
        _request(),
        QueueEntryRevisionConflict(queue_entry_id, 4, 5),
    )

    reservation_error = json.loads(bytes(reservation_response.body))["error"]
    queue_error = json.loads(bytes(queue_response.body))["error"]

    assert reservation_response.status_code == 409
    assert queue_response.status_code == 409
    assert reservation_error["code"] == queue_error["code"] == "revision_conflict"
    assert reservation_error["details"] == {
        "aggregate_kind": "Reservation",
        "aggregate_id": str(reservation_id),
        "expected_revision": 2,
        "current_revision": 3,
    }
    assert queue_error["details"] == {
        "aggregate_kind": "QueueEntry",
        "aggregate_id": str(queue_entry_id),
        "expected_revision": 4,
        "current_revision": 5,
    }
