import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery
from request_engine.modules.discovery.adapters.http.published_slot_reader import (
    HttpPublishedSlotReader,
)

NOW = datetime(2035, 1, 1, tzinfo=UTC)


def query() -> PublishedSlotQuery:
    return PublishedSlotQuery(
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


@pytest.mark.asyncio
async def test_http_batch_reader_uses_one_remote_request_for_multiple_candidates() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[[], []])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://booking-internal",
    ) as client:
        reader = HttpPublishedSlotReader(client)
        result = await reader.find_published_slots_batch((query(), query()))

    assert result == ((), ())
    assert len(requests) == 1
    assert requests[0].url.path == "/internal/v1/discovery/published-slots/batch"
    payload = json.loads(requests[0].content)
    assert len(payload["queries"]) == 2


@pytest.mark.asyncio
async def test_http_batch_reader_rejects_misaligned_response_count() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[[]])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://booking-internal",
    ) as client:
        reader = HttpPublishedSlotReader(client)
        with pytest.raises(RuntimeError, match="malformed payload"):
            await reader.find_published_slots_batch((query(), query()))
