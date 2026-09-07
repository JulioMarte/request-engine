from typing import Any, cast

from fastapi import FastAPI

from request_engine.entrypoints.http import operational_app
from request_engine.modules.catalog.api.operational_profile_router import (
    create_operational_profile_router,
)
from request_engine.modules.catalog.api.operational_schedule_router import (
    create_operational_schedule_router,
)
from request_engine.platform.security.http import CapabilityRequired


class _Resolver:
    async def resolve_actor(self, request: object) -> object:
        del request
        raise AssertionError("actor resolution is not used while building OpenAPI")


def _operation(app: FastAPI, path: str, method: str) -> dict[str, object]:
    return cast(dict[str, object], app.openapi()["paths"][path][method.lower()])


def test_operations_app_maps_capability_failures_instead_of_leaking_500(monkeypatch: Any) -> None:
    monkeypatch.setattr(operational_app, "install_operational_modules", lambda *args, **kwargs: None)
    app = operational_app.create_operational_app(
        session_factory=cast(Any, object()),
        actor_resolver=cast(Any, object()),
    )
    assert CapabilityRequired in app.exception_handlers


def test_catalog_operational_profile_routes_publish_canonical_operation_policy() -> None:
    router = create_operational_profile_router(
        create_handler=cast(Any, object()),
        update_handler=cast(Any, object()),
        contacts_handler=cast(Any, object()),
        actor_resolver=cast(Any, _Resolver()),
    )
    app = FastAPI()
    app.include_router(router)

    expected = {
        ("/v1/operations/locations", "post"): "catalog_location_create",
        ("/v1/operations/locations/{location_id}", "patch"): "catalog_location_update",
        (
            "/v1/operations/locations/{location_id}/contacts",
            "put",
        ): "catalog_location_contacts_update",
    }
    for (path, method), operation_id in expected.items():
        operation = _operation(app, path, method)
        assert operation["operationId"] == operation_id
        assert operation["x-request-engine-operation-id"] == operation_id
        assert operation["x-request-engine-owner"] == "catalog"
        assert operation["x-request-engine-capability"] == "catalog.manage"
        assert operation["x-request-engine-kind"] == "command"
        assert operation["x-request-engine-idempotency"] == "required"
        assert operation["x-request-engine-exposure"] == "operator"


def test_catalog_operational_schedule_routes_publish_canonical_operation_policy() -> None:
    router = create_operational_schedule_router(
        hours_handler=cast(Any, object()),
        exception_handler=cast(Any, object()),
        terms_handler=cast(Any, object()),
        holidays_handler=cast(Any, object()),
        actor_resolver=cast(Any, _Resolver()),
    )
    app = FastAPI()
    app.include_router(router)

    expected = {
        ("/v1/operations/locations/{location_id}/hours", "put"):
            "catalog_location_hours_replace",
        ("/v1/operations/locations/{location_id}/hours-exceptions", "put"):
            "catalog_location_hours_exception_upsert",
        ("/v1/operations/offering-versions/{offering_version_id}/booking-terms", "put"):
            "catalog_offering_booking_terms_configure",
        ("/v1/operations/organization/holidays", "put"):
            "catalog_organization_holidays_replace",
    }
    for (path, method), operation_id in expected.items():
        operation = _operation(app, path, method)
        assert operation["operationId"] == operation_id
        assert operation["x-request-engine-operation-id"] == operation_id
        assert operation["x-request-engine-owner"] == "catalog"
        assert operation["x-request-engine-capability"] == "catalog.manage"
        assert operation["x-request-engine-kind"] == "command"
        assert operation["x-request-engine-idempotency"] == "required"
        assert operation["x-request-engine-exposure"] == "operator"
