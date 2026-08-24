from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from request_engine.modules.booking.api.discovery_gateway_models import (
    PublishedSlotBatchBody,
    PublishedSlotQueryBody,
)

NOW = datetime(2035, 1, 1, tzinfo=UTC)


def query_body() -> PublishedSlotQueryBody:
    return PublishedSlotQueryBody(
        organization_id=uuid4(),
        publication_id=uuid4(),
        publication_revision=1,
        mapping_id=uuid4(),
        mapping_revision=1,
        offering_version_id=uuid4(),
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        location_id=uuid4(),
        limit=10,
    )


def test_batch_accepts_exact_f2_candidate_ceiling() -> None:
    body = query_body()
    batch = PublishedSlotBatchBody(queries=tuple(body for _ in range(200)))
    assert len(batch.queries) == 200


def test_batch_rejects_candidate_201() -> None:
    body = query_body()
    with pytest.raises(ValidationError):
        PublishedSlotBatchBody(queries=tuple(body for _ in range(201)))
