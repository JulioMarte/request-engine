from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.routing import APIRoute

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

_EXPECTED_PUBLIC_OPERATIONS = frozenset(
    {
        ("GET", "/v1/business"),
        ("GET", "/v1/catalog/offerings"),
        ("GET", "/v1/catalog/offerings/{offering_key}"),
        ("GET", "/v1/appointments/slots"),
        ("POST", "/v1/appointments"),
        ("GET", "/v1/appointments/{reservation_id}"),
        ("POST", "/v1/appointments/{reservation_id}/cancel"),
        ("POST", "/v1/appointments/{reservation_id}/reschedule"),
        ("GET", "/v1/queues"),
        ("POST", "/v1/queues/{queue_id}/join"),
        ("GET", "/v1/queues/{queue_id}/status"),
        ("POST", "/v1/queues/{queue_id}/leave"),
        ("POST", "/v1/queues/{queue_id}/call-next"),
        ("POST", "/v1/requests/definitions/{request_key}/submit"),
        ("GET", "/v1/requests/{request_id}"),
        ("POST", "/v1/requests/{request_id}/result"),
        ("POST", "/v1/requests/{request_id}/complete"),
        ("POST", "/v1/requests/{request_id}/cancel"),
        ("POST", "/v1/requests/{request_id}/fail"),
    }
)


class RejectAllResolver:
    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        raise AuthenticationRequired


@pytest.mark.asyncio
@pytest.mark.e2e
@pytest.mark.postgres
async def test_public_http_surface_cannot_grow_without_e2e_classification(
    e2e_session_factory: SessionFactory,
) -> None:
    app = create_app(
        session_factory=e2e_session_factory,
        actor_resolver=RejectAllResolver(),
    )
    actual = frozenset(
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/")
        for method in route.methods
    )

    assert actual == _EXPECTED_PUBLIC_OPERATIONS
