from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.modules.catalog.api.bootstrap_router import create_bootstrap_router
from request_engine.modules.catalog.api.operational_errors import register_input_error_handler
from request_engine.modules.catalog.api.router import create_router
from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    CreateOfferingCommand,
    CreateResourceCapabilityCommand,
    OfferingBootstrapState,
    ResourceCapabilityState,
)
from request_engine.modules.catalog.application.queries.search_offerings import (
    OfferingSummary,
    OfferingVersionInfo,
    SearchOfferingsQuery,
)
from request_engine.platform.security.context import ActorContext


class Resolver:
    organization_id = uuid4()

    async def resolve_actor(self, request: Any) -> ActorContext:
        return ActorContext(
            organization_id=self.organization_id,
            principal_id=uuid4(),
            capabilities=frozenset({"catalog.manage", "catalog.search_offerings"}),
        )


class Bootstrap:
    calls = 0

    async def create_resource_capability(
        self,
        command: CreateResourceCapabilityCommand,
    ) -> ResourceCapabilityState:
        self.calls += 1
        return ResourceCapabilityState(uuid4(), command.capability_key, command.display_name)

    async def create_offering(self, command: CreateOfferingCommand) -> OfferingBootstrapState:
        self.calls += 1
        return OfferingBootstrapState(uuid4(), uuid4(), command.offering_key, 1, ())

    async def set_offering_version_booking_policy(
        self,
        command: policy_commands.SetOfferingVersionBookingPolicyCommand,
    ) -> policy_commands.OfferingVersionBookingPolicyState:
        self.calls += 1
        return policy_commands.OfferingVersionBookingPolicyState(
            command.offering_version_id,
            command.expected_revision + 1,
            command.policy,
        )


@pytest.mark.asyncio
@pytest.mark.adversarial
@pytest.mark.parametrize(
    "overrides",
    [
        {"offering_key": " "},
        {"display_name": " "},
        {"reservation_policy": {"confirmation": True}},
        {"reservation_policy": {"reminders_before_minutes": [-1]}},
        {"reservation_policy": {"channel_policy": {"channels": []}}},
        {"reservation_policy": {"channel_policy": {"channels": ["email", "email"]}}},
        {"reservation_policy": {"channel_policy": {"channels": ["email"], "provider_key": " "}}},
    ],
)
async def test_invalid_owner_input_is_422_without_persistence(overrides: dict[str, object]) -> None:
    handler = Bootstrap()
    app = FastAPI()
    register_input_error_handler(app)
    app.include_router(
        create_bootstrap_router(
            handler=handler,
            policy_handler=handler,
            actor_resolver=Resolver(),
        )
    )  # type: ignore[arg-type]
    payload = {
        "authority_party_id": str(uuid4()),
        "offering_key": "exam",
        "display_name": "Exam",
        "duration_minutes": 30,
        **overrides,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/catalog/offerings",
            json=payload,
            headers={"Idempotency-Key": "invalid"},
        )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_catalog_input"
    assert handler.calls == 0


@pytest.mark.asyncio
async def test_blank_capability_and_duplicate_requirements_do_not_reach_persistence() -> None:
    handler = Bootstrap()
    app = FastAPI()
    register_input_error_handler(app)
    app.include_router(
        create_bootstrap_router(
            handler=handler,
            policy_handler=handler,
            actor_resolver=Resolver(),
        )
    )  # type: ignore[arg-type]
    capability_id = str(uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blank = await client.post(
            "/v1/catalog/resource-capabilities",
            json={
                "authority_party_id": str(uuid4()),
                "capability_key": " ",
                "display_name": "Name",
            },
            headers={"Idempotency-Key": "blank"},
        )
        duplicate = await client.post(
            "/v1/catalog/offerings",
            json={
                "authority_party_id": str(uuid4()),
                "offering_key": "exam",
                "display_name": "Exam",
                "duration_minutes": 30,
                "requirements": [
                    {"capability_id": capability_id},
                    {"capability_id": capability_id},
                ],
            },
            headers={"Idempotency-Key": "duplicate"},
        )
    assert blank.status_code == duplicate.status_code == 422
    assert handler.calls == 0
    schema = app.openapi()["components"]["schemas"]["ResourceCapabilityView"]
    assert {"capability_id", "capability_key", "display_name"} <= set(schema["properties"])


@pytest.mark.asyncio
async def test_default_booking_policy_response_is_typed_and_retains_null_channel_policy() -> None:
    handler = Bootstrap()
    app = FastAPI()
    app.include_router(
        create_bootstrap_router(
            handler=handler,
            policy_handler=handler,
            actor_resolver=Resolver(),
        )
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/v1/catalog/offerings/{uuid4()}/booking-policy",
            json={
                "authority_party_id": str(uuid4()),
                "expected_revision": 0,
                "booking_policy": {},
            },
            headers={"Idempotency-Key": "policy"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["policy"]["communications"]["channel_policy"] is None
    assert response.json()["booking_policy_revision"] == 1


class CatalogReader:
    def __init__(self) -> None:
        version = OfferingVersionInfo(uuid4(), 1, 30, True, True, {})
        self.items = tuple(
            sorted(
                (OfferingSummary(uuid4(), f"exam-{i}", "Exam", None, version) for i in range(3)),
                key=lambda item: item.id,
            )
        )

    async def search_offerings(self, query: SearchOfferingsQuery) -> tuple[OfferingSummary, ...]:
        return tuple(
            item
            for item in self.items
            if query.after_id is None
            or (item.display_name, item.id) > (query.after_display_name or "", query.after_id)
        )[: query.limit + 1]

    async def get_offering_by_key(self, organization_id: Any, offering_key: str) -> None:
        return None


@pytest.mark.asyncio
async def test_offering_pages_continue_across_equal_names_and_reject_filter_change() -> None:
    reader = CatalogReader()
    app = FastAPI()
    register_input_error_handler(app)
    app.include_router(
        create_router(
            business_reader=cast(Any, reader),
            offering_reader=reader,
            actor_resolver=Resolver(),
        )
    )  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/v1/catalog/offerings", params={"limit": 2})
        assert first.status_code == 200
        cursor = first.json()["next_cursor"]
        second = await client.get("/v1/catalog/offerings", params={"limit": 2, "cursor": cursor})
        mismatch = await client.get(
            "/v1/catalog/offerings",
            params={
                "cursor": cursor,
                "bookable": True,
            },
        )
        unknown = await client.get("/v1/catalog/offerings", params={"tenant": str(uuid4())})
        naive = await client.get("/v1/catalog/offerings", params={"effective_at": "2030-01-01"})
    assert second.status_code == 200
    assert second.json().get("next_cursor") is None
    ids = [item["id"] for page in (first, second) for item in page.json()["items"]]
    assert ids == [str(item.id) for item in reader.items]
    assert mismatch.status_code == unknown.status_code == naive.status_code == 422
