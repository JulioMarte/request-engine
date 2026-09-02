from datetime import UTC, datetime
from uuid import uuid4

import pytest

from request_engine.modules.delivery.api.live_models import ServiceSessionView
from request_engine.modules.delivery.contracts.service_session import (
    ServiceSession,
    ServiceSessionStatus,
)
from request_engine.modules.queue.api.live_models import StaffQueueEntryView
from request_engine.modules.queue.api.models import QueueStatusView
from request_engine.modules.queue.contracts.live_queue import StaffQueueEntry


@pytest.mark.contract
def test_staff_projection_keeps_expected_and_actual_workload_distinct() -> None:
    now = datetime.now(UTC)
    item = StaffQueueEntry(
        queue_entry_id=uuid4(),
        queue_id=uuid4(),
        subject_party_id=uuid4(),
        subject_display_name="Subject",
        reservation_id=uuid4(),
        status="serving",
        scheduled_at=now,
        arrived_at=now,
        admitted_at=now,
        called_at=now,
        expected_workload_key="consult-short",
        service_session_id=uuid4(),
        service_status="active",
        actual_resource_id=uuid4(),
        actual_location_id=uuid4(),
        actual_workload_key="consult-complex",
        service_started_at=now,
        service_completed_at=None,
        queue_revision=3,
        service_revision=1,
    )
    view = StaffQueueEntryView.from_contract(item)
    assert view.expected_workload_key == "consult-short"
    assert view.actual_workload_key == "consult-complex"
    assert view.expected_workload_key != view.actual_workload_key


@pytest.mark.contract
def test_customer_queue_projection_excludes_staff_execution_fields() -> None:
    forbidden = {
        "subject_display_name",
        "expected_workload_key",
        "actual_workload_key",
        "service_session_id",
        "actual_resource_id",
        "actual_location_id",
        "service_started_at",
        "service_completed_at",
        "recall_hold_kind",
        "recall_hold_release_at",
        "recall_hold_reason",
    }
    fields = set(QueueStatusView.model_fields)
    assert forbidden.isdisjoint(fields)


@pytest.mark.contract
def test_service_session_contract_is_execution_not_reservation_planning() -> None:
    now = datetime.now(UTC)
    session = ServiceSession(
        id=uuid4(),
        queue_entry_id=uuid4(),
        resource_id=uuid4(),
        location_id=uuid4(),
        status=ServiceSessionStatus.ACTIVE,
        started_at=now,
        completed_at=None,
        actual_workload_classification_id=uuid4(),
        revision=1,
    )
    view = ServiceSessionView.from_contract(session)
    assert view.resource_id == session.resource_id
    assert view.location_id == session.location_id
    assert {"reservation_id", "offering_version_id", "during"}.isdisjoint(
        ServiceSessionView.model_fields
    )
