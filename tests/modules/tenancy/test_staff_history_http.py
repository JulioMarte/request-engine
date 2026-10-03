"""Typed HTTP projection proof; actual authority/RLS evidence is PostgreSQL-owned."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.staff_history_reads import add_staff_history_reads
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.modules.tenancy.application.errors import (
    StaffMembershipInputInvalid,
    StaffMembershipNotFound,
)
from request_engine.modules.tenancy.application.queries.staff_history import (
    ListStaffHistoryQuery,
    StaffHistoryEntry,
    StaffHistoryPage,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class RecordingHistory:
    def __init__(self) -> None:
        self.calls: list[ListStaffHistoryQuery] = []
        self.failure: Exception | None = None

    async def list_history(
        self, actor: ActorContext, query: ListStaffHistoryQuery
    ) -> StaffHistoryPage:
        self.calls.append(query)
        if self.failure:
            raise self.failure
        return StaffHistoryPage(
            (
                StaffHistoryEntry(
                    UUID(int=1),
                    actor.principal_id,
                    datetime(2026, 1, 1, tzinfo=UTC),
                    "staff.manage_authority",
                    "authority",
                    1,
                    2,
                ),
            ),
            None,
        )


def _app(*, allowed: bool = True, human: bool = True) -> tuple[FastAPI, RecordingHistory]:
    reader = RecordingHistory()
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"staff.read"}) if allowed else frozenset(),
        principal_kind=PrincipalKind.HUMAN if human else PrincipalKind.AGENT,
    )

    async def resolver(request: Request) -> ActorContext:
        del request
        return actor

    router = APIRouter(prefix="/v1/staff")
    add_staff_history_reads(router, reader=reader, authenticated_actor=resolver)
    app = FastAPI()
    app.include_router(router)
    add_staff_membership_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return app, reader


@pytest.mark.asyncio
async def test_history_schema_and_pagination_are_explicit_and_payload_free() -> None:
    app, reader = _app()
    member, cursor = uuid4(), uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/staff/members/{member}/history", params={"after": str(cursor), "limit": "7"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert reader.calls == [ListStaffHistoryQuery(member, cursor, 7)]
    assert set(response.json()) == {"items", "next_cursor"}
    assert set(response.json()["items"][0]) == {
        "event_id",
        "actor_principal_id",
        "occurred_at",
        "command_name",
        "revision_kind",
        "revision_before",
        "revision_after",
    }
    operation = app.openapi()["paths"]["/v1/staff/members/{membership_id}/history"]["get"]
    assert operation["operationId"] == "staff_history_list"
    assert operation["x-request-engine-owner"] == "tenancy"
    assert operation["x-request-engine-capability"] == "staff.read"
    assert operation["x-request-engine-idempotency"] == "none"
    assert "requestBody" not in operation


@pytest.mark.asyncio
@pytest.mark.parametrize(("allowed", "human"), [(False, True), (True, False)])
async def test_history_cannot_infer_read_authority_from_target(allowed: bool, human: bool) -> None:
    app, reader = _app(allowed=allowed, human=human)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/staff/members/{uuid4()}/history")
    assert response.status_code == 403
    assert reader.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"limit": "0"},
        {"limit": "101"},
        {"after": "invalid"},
        {"principal_id": "forged"},
        {"organization_id": "forged"},
    ],
)
async def test_history_rejects_invalid_or_trusted_query_fields(params: dict[str, str]) -> None:
    app, reader = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/staff/members/{uuid4()}/history", params=params)
    assert response.status_code == 422
    assert reader.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (StaffMembershipNotFound("private target"), 404, "staff_membership_not_found"),
        (StaffMembershipInputInvalid("private cursor"), 422, "staff_membership_input_invalid"),
    ],
)
async def test_history_maps_owner_failures_without_private_details(
    error: Exception,
    status: int,
    code: str,
) -> None:
    app, reader = _app()
    reader.failure = error
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/staff/members/{uuid4()}/history")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private" not in response.text
