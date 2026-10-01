from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.errors import capability_required_handler
from request_engine.modules.tenancy.api.staff_membership_errors import (
    add_staff_membership_error_handlers,
)
from request_engine.modules.tenancy.api.staff_membership_reads import (
    add_staff_membership_reads,
)
from request_engine.modules.tenancy.application.queries.staff_membership import (
    ListStaffMembershipsQuery,
    PlanStaffAuthorityQuery,
    StaffAuthorityPlan,
    StaffMembershipSummary,
    StaffOverview,
)
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.http import CapabilityRequired


class RecordingReader:
    def __init__(self) -> None:
        self.overview_calls = 0
        self.plan_queries: list[PlanStaffAuthorityQuery] = []
        self.list_queries: list[ListStaffMembershipsQuery] = []
        self.members: tuple[StaffMembershipSummary, ...] = ()

    async def read_overview(self, actor: ActorContext) -> StaffOverview:
        del actor
        self.overview_calls += 1
        return StaffOverview(
            total=7,
            active=3,
            invited=1,
            suspended=2,
            revoked=1,
            effective_capabilities=("staff.read", "staff.manage_authority"),
            delegable_ceiling=("staff.read",),
        )

    async def list_memberships(
        self, actor: ActorContext, query: ListStaffMembershipsQuery
    ) -> tuple[StaffMembershipSummary, ...]:
        del actor
        self.list_queries.append(query)
        start = 0
        if query.after is not None:
            start = next(
                (
                    index + 1
                    for index, item in enumerate(self.members)
                    if item.membership_id == query.after
                ),
                len(self.members),
            )
        return self.members[start : start + query.limit]

    async def read_membership(
        self, actor: ActorContext, membership_id: UUID
    ) -> StaffMembershipSummary:
        del actor, membership_id
        raise AssertionError("not used")

    async def plan_authority(
        self, actor: ActorContext, query: PlanStaffAuthorityQuery
    ) -> StaffAuthorityPlan:
        del actor
        self.plan_queries.append(query)
        return StaffAuthorityPlan(
            membership_id=query.membership_id,
            authority_revision=query.expected_authority_revision,
            current=("appointments.book", "staff.read"),
            desired=tuple(sorted(query.desired_capabilities)),
            added=("queue.staff_read",),
            removed=("appointments.book",),
            assignable=False,
            blocked_capabilities=("queue.staff_read",),
            can_apply=False,
            blockers=(),
        )


def _actor(*capabilities: str, kind: PrincipalKind = PrincipalKind.HUMAN) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
        principal_kind=kind,
    )


def _app(actor: ActorContext) -> tuple[FastAPI, RecordingReader]:
    reader = RecordingReader()

    async def authenticated_actor(request: Request) -> ActorContext:
        del request
        return actor

    router = APIRouter(prefix="/v1/staff")
    add_staff_membership_reads(router, reader=reader, authenticated_actor=authenticated_actor)
    app = FastAPI()
    app.include_router(router)
    add_staff_membership_error_handlers(app)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    return app, reader


@pytest.mark.asyncio
async def test_overview_is_tenant_reader_projection_with_no_store() -> None:
    app, reader = _app(_actor("staff.read"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/v1/staff/overview")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "total": 7,
        "active": 3,
        "invited": 1,
        "suspended": 2,
        "revoked": 1,
        "effective_capabilities": ["staff.read", "staff.manage_authority"],
        "delegable_ceiling": ["staff.read"],
    }
    assert reader.overview_calls == 1


@pytest.mark.asyncio
async def test_authority_plan_maps_read_only_diff_without_idempotency_key() -> None:
    membership_id = uuid4()
    app, reader = _app(_actor("staff.manage_authority"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(
            f"/v1/staff/members/{membership_id}/authority:plan",
            json={
                "expected_authority_revision": 9,
                "desired_capabilities": ["staff.read", "queue.staff_read"],
            },
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "membership_id": str(membership_id),
        "authority_revision": 9,
        "current": ["appointments.book", "staff.read"],
        "desired": ["queue.staff_read", "staff.read"],
        "added": ["queue.staff_read"],
        "removed": ["appointments.book"],
        "assignable": False,
        "blocked_capabilities": ["queue.staff_read"],
        "can_apply": False,
        "blockers": [],
    }
    assert reader.plan_queries == [
        PlanStaffAuthorityQuery(
            membership_id=membership_id,
            expected_authority_revision=9,
            desired_capabilities=("staff.read", "queue.staff_read"),
        )
    ]

    operation = app.openapi()["paths"]["/v1/staff/members/{membership_id}/authority:plan"]["post"]
    assert operation["x-request-engine-capability"] == "staff.plan_authority"
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"


@pytest.mark.asyncio
async def test_plan_query_grant_is_accepted_without_mutation_grant() -> None:
    app, reader = _app(_actor("staff.plan_authority"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(
            f"/v1/staff/members/{uuid4()}/authority:plan",
            json={"expected_authority_revision": 1, "desired_capabilities": []},
        )

    assert response.status_code == 200, response.text
    assert len(reader.plan_queries) == 1


@pytest.mark.asyncio
async def test_authority_plan_rejects_non_human_before_reader() -> None:
    app, reader = _app(_actor("staff.manage_authority", kind=PrincipalKind.INTEGRATION))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post(
            f"/v1/staff/members/{uuid4()}/authority:plan",
            json={"expected_authority_revision": 1, "desired_capabilities": []},
        )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "staff_membership_forbidden"
    assert reader.plan_queries == []


@pytest.mark.asyncio
async def test_new_reads_require_their_existing_capabilities() -> None:
    app, reader = _app(_actor())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        overview = await http.get("/v1/staff/overview")
        plan = await http.post(
            f"/v1/staff/members/{uuid4()}/authority:plan",
            json={"expected_authority_revision": 1, "desired_capabilities": []},
        )

    assert overview.status_code == 403
    assert plan.status_code == 403
    assert reader.overview_calls == 0
    assert reader.plan_queries == []


@pytest.mark.asyncio
async def test_staff_list_pages_through_more_than_fifty_members_without_loss() -> None:
    app, reader = _app(_actor("staff.read"))
    reader.members = tuple(
        StaffMembershipSummary(
            membership_id=UUID(int=index + 1),
            principal_id=UUID(int=1000 + index),
            status="active",
            membership_revision=1,
            authority_revision=1,
            principal_active=True,
            authority_anchor_party_id=None,
            standing_grants=(),
        )
        for index in range(51)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        first = await http.get("/v1/staff/members?limit=50")
        first_body = first.json()
        second = await http.get(
            "/v1/staff/members",
            params={"limit": 50, "after": first_body["next_cursor"]},
        )
        second_body = second.json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(first_body["items"]) == 50
    assert len(second_body["items"]) == 1
    assert first_body["next_cursor"] == str(UUID(int=50))
    assert second_body["next_cursor"] is None
    seen = [item["membership_id"] for item in first_body["items"] + second_body["items"]]
    assert len(seen) == len(set(seen)) == 51
