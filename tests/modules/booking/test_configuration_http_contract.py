"""Booking configuration has typed receipts and rejects invalid transport before writes."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.booking.api.operational_assignment_router import (
    create_operational_assignment_router,
)
from request_engine.modules.booking.api.operational_exception_router import (
    create_operational_exception_router,
)
from request_engine.modules.booking.api.operational_terms_router import (
    create_operational_terms_router,
)
from request_engine.modules.booking.api.resource_bootstrap_router import (
    create_resource_bootstrap_router,
)
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
)
from request_engine.modules.booking.application.commands.create_resource import (
    ResourceBootstrapState,
)
from request_engine.platform.security.context import ActorContext

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _app() -> tuple[FastAPI, list[AsyncMock]]:
    app = FastAPI()
    add_global_error_handlers(app)
    actor = ActorContext(uuid4(), uuid4(), frozenset({"booking.manage_supply", "catalog.manage"}))
    resolver = Mock()
    resolver.resolve_actor = AsyncMock(return_value=actor)
    handlers = [Mock() for _ in range(8)]
    methods = [
        "create_resource",
        "assign_resource_to_location",
        "retire_resource_location_assignment",
        "set_resource_location_availability",
        "configure_booking_context_terms",
        "supersede_booking_context_terms",
        "set_resource_location_schedule_exception",
        "set_resource_schedule_exception",
    ]
    calls = [AsyncMock() for _ in methods]
    for handler, method, call in zip(handlers, methods, calls, strict=True):
        setattr(handler, method, call)
    app.include_router(
        create_resource_bootstrap_router(handler=handlers[0], actor_resolver=resolver)
    )
    app.include_router(
        create_operational_assignment_router(
            assign_handler=handlers[1],
            retire_handler=handlers[2],
            availability_handler=handlers[3],
            actor_resolver=resolver,
        )
    )
    app.include_router(
        create_operational_terms_router(
            configure_handler=handlers[4], supersede_handler=handlers[5], actor_resolver=resolver
        )
    )
    app.include_router(
        create_operational_exception_router(
            assignment_handler=handlers[6], resource_handler=handlers[7], actor_resolver=resolver
        )
    )
    return app, calls


def _invalid_cases() -> list[tuple[str, str, dict[str, Any]]]:
    authority, resource, location, capability = (str(uuid4()) for _ in range(4))
    bootstrap = {
        "authority_party_id": authority,
        "location_id": location,
        "resource_key": "room",
        "display_name": "Consultation room",
    }
    assignment = {
        "authority_party_id": authority,
        "resource_id": resource,
        "location_id": location,
        "effective_from": "2030-01-01T00:00:00Z",
        "expected_resource_availability_revision": 1,
    }
    availability = {
        "authority_party_id": authority,
        "expected_resource_availability_revision": 1,
        "windows": [{"weekday": 0, "local_start": "09:00", "local_end": "08:00"}],
    }
    terms = {
        "authority_party_id": authority,
        "resource_location_assignment_id": resource,
        "offering_version_id": location,
        "effective_from": "2030-01-01T00:00:00Z",
        "planned_duration_minutes": 30,
    }
    exception = {
        "authority_party_id": authority,
        "start_at": "2030-01-01T00:00:00Z",
        "end_at": "2030-01-01T01:00:00Z",
        "exception_kind": "unavailable",
        "expected_resource_availability_revision": 1,
    }
    return [
        ("POST", "/v1/booking/resources", {**bootstrap, "resource_key": "   "}),
        ("POST", "/v1/booking/resources", {**bootstrap, "capacity_units": 2}),
        (
            "POST",
            "/v1/booking/resources",
            {**bootstrap, "capability_ids": [capability, capability]},
        ),
        ("POST", "/v1/booking/resources", {**bootstrap, "organization_id": location}),
        (
            "POST",
            "/v1/operations/resource-assignments",
            {**assignment, "expected_resource_availability_revision": 0},
        ),
        (
            "POST",
            "/v1/operations/resource-assignments",
            {**assignment, "effective_from": "2030-01-01T00:00:00"},
        ),
        (
            "POST",
            "/v1/operations/resource-assignments",
            {**assignment, "unknown_filter": "ignored"},
        ),
        ("PUT", f"/v1/operations/resource-assignments/{resource}/availability", availability),
        ("POST", "/v1/operations/context-terms", {**terms, "currency": "USD"}),
        ("POST", "/v1/operations/context-terms", {**terms, "amount": "NaN", "currency": "USD"}),
        (
            "POST",
            "/v1/operations/context-terms",
            {**terms, "amount": "1.1234567", "currency": "USD"},
        ),
        (
            "POST",
            "/v1/operations/context-terms",
            {**terms, "amount": "100000000000000", "currency": "USD"},
        ),
        (
            "POST",
            f"/v1/operations/context-terms/{resource}/supersede",
            {
                "authority_party_id": authority,
                "expected_current_revision": 1,
                "effective_from": "2030-01-01T00:00:00Z",
                "amount": "1.1234567",
                "currency": "USD",
            },
        ),
        (
            "POST",
            f"/v1/operations/context-terms/{resource}/supersede",
            {
                "authority_party_id": authority,
                "expected_current_revision": 0,
                "effective_from": "2030-01-01T00:00:00Z",
                "bookable": False,
            },
        ),
        ("PUT", f"/v1/operations/resources/{resource}/exceptions", {**exception, "reason": "  "}),
        (
            "PUT",
            f"/v1/operations/resources/{resource}/exceptions",
            {**exception, "end_at": "2029-01-01T01:00:00Z"},
        ),
        (
            "PUT",
            f"/v1/operations/resource-assignments/{resource}/exceptions",
            {**exception, "tenant_id": location},
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,body", _invalid_cases())
async def test_invalid_configuration_is_422_without_invoking_handler(
    method: str, path: str, body: dict[str, Any]
) -> None:
    app, calls = _app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            method, path, json=body, headers={"Idempotency-Key": "case"}
        )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_failed"
    for call in calls:
        call.assert_not_awaited()


def test_every_configuration_command_has_specific_response_schema() -> None:
    app, _ = _app()
    operations = [
        operation for path in app.openapi()["paths"].values() for operation in path.values()
    ]
    assert len(operations) == 8
    for operation in operations:
        successful = operation["responses"].get("201", operation["responses"].get("200"))
        assert successful["content"]["application/json"]["schema"]["$ref"].endswith("View")


@pytest.mark.asyncio
async def test_resource_receipt_serializes_explicit_transport_projection() -> None:
    app, calls = _app()
    resource, capability, assignment = uuid4(), uuid4(), uuid4()
    calls[0].return_value = ResourceBootstrapState(
        resource_id=resource,
        resource_key="room",
        display_name="Consultation room",
        capacity_model="units",
        capacity_units=3,
        availability_revision=4,
        capability_ids=(capability,),
        resource_location_assignment_id=assignment,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/booking/resources",
            json={
                "authority_party_id": str(uuid4()),
                "location_id": str(uuid4()),
                "resource_key": "room",
                "display_name": "Consultation room",
                "capacity_model": "units",
                "capacity_units": 3,
            },
            headers={"Idempotency-Key": "create-room"},
        )
    assert response.status_code == 201, response.text
    assert response.json() == {
        "resource_id": str(resource),
        "resource_key": "room",
        "display_name": "Consultation room",
        "capacity_model": "units",
        "capacity_units": 3,
        "availability_revision": 4,
        "capability_ids": [str(capability)],
        "weekly_availability": [],
        "resource_location_assignment_id": str(assignment),
    }
    calls[0].assert_awaited_once()


@pytest.mark.asyncio
async def test_contextual_money_receipt_preserves_exact_decimal_string() -> None:
    app, calls = _app()
    terms, assignment, version = uuid4(), uuid4(), uuid4()
    calls[4].return_value = BookingContextTermsState(
        context_terms_id=terms,
        resource_location_assignment_id=assignment,
        offering_version_id=version,
        effective_from=datetime(2030, 1, 1, tzinfo=UTC),
        effective_until=None,
        amount=Decimal("12345678901234.123456"),
        currency="USD",
        planned_duration_minutes=30,
        bookable=True,
        revision=1,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/operations/context-terms",
            json={
                "authority_party_id": str(uuid4()),
                "resource_location_assignment_id": str(assignment),
                "offering_version_id": str(version),
                "effective_from": "2030-01-01T00:00:00Z",
                "amount": "12345678901234.123456",
                "currency": "USD",
                "planned_duration_minutes": 30,
            },
            headers={"Idempotency-Key": "exact-money"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["amount"] == "12345678901234.123456"
    assert response.json()["currency"] == "USD"
    assert response.json()["context_terms_id"] == str(terms)
    calls[4].assert_awaited_once()
