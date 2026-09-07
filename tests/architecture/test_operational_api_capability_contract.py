from typing import Any, cast

from fastapi import FastAPI

from request_engine.entrypoints.http import operational_app
from request_engine.modules.booking.api.operational_assignment_router import (
    create_operational_assignment_router,
)
from request_engine.modules.booking.api.resource_bootstrap_router import (
    create_resource_bootstrap_router,
)
from request_engine.modules.catalog.api.operational_profile_router import (
    create_operational_profile_router,
)
from request_engine.modules.catalog.api.operational_schedule_router import (
    create_operational_schedule_router,
)
from request_engine.modules.queue.api.service_queue_bootstrap_router import (
    create_service_queue_bootstrap_router,
)
from request_engine.modules.tenancy.api.operational_router import create_operational_router
from request_engine.platform.security.http import CapabilityRequired


class _Resolver:
    async def resolve_actor(self, request: object) -> object:
        del request
        raise AssertionError("actor resolution is not used while building OpenAPI")


def _operation(app: FastAPI, path: str, method: str) -> dict[str, object]:
    return cast(dict[str, object], app.openapi()["paths"][path][method.lower()])


def _noop_install(*args: object, **kwargs: object) -> None:
    del args, kwargs


def _assert_command_policy(
    operation: dict[str, object],
    *,
    operation_id: str,
    owner: str,
    capability: str,
) -> None:
    assert operation["operationId"] == operation_id
    assert operation["x-request-engine-operation-id"] == operation_id
    assert operation["x-request-engine-owner"] == owner
    assert operation["x-request-engine-capability"] == capability
    assert operation["x-request-engine-kind"] == "command"
    assert operation["x-request-engine-idempotency"] == "required"
    assert operation["x-request-engine-exposure"] == "operator"


def test_operations_app_maps_capability_failures_instead_of_leaking_500(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(operational_app, "install_operational_modules", _noop_install)
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
        _assert_command_policy(
            _operation(app, path, method),
            operation_id=operation_id,
            owner="catalog",
            capability="catalog.manage",
        )


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
        (
            "/v1/operations/locations/{location_id}/hours",
            "put",
        ): "catalog_location_hours_replace",
        (
            "/v1/operations/locations/{location_id}/hours-exceptions",
            "put",
        ): "catalog_location_hours_exception_upsert",
        (
            "/v1/operations/offering-versions/{offering_version_id}/booking-terms",
            "put",
        ): "catalog_offering_booking_terms_configure",
        (
            "/v1/operations/organization/holidays",
            "put",
        ): "catalog_organization_holidays_replace",
    }
    for (path, method), operation_id in expected.items():
        _assert_command_policy(
            _operation(app, path, method),
            operation_id=operation_id,
            owner="catalog",
            capability="catalog.manage",
        )


def test_booking_supply_routes_publish_canonical_operation_policy() -> None:
    app = FastAPI()
    app.include_router(
        create_resource_bootstrap_router(
            handler=cast(Any, object()),
            actor_resolver=cast(Any, _Resolver()),
        )
    )
    app.include_router(
        create_operational_assignment_router(
            assign_handler=cast(Any, object()),
            retire_handler=cast(Any, object()),
            availability_handler=cast(Any, object()),
            actor_resolver=cast(Any, _Resolver()),
        )
    )

    expected = {
        ("/v1/booking/resources", "post"): "booking_resource_create",
        (
            "/v1/operations/resource-assignments",
            "post",
        ): "booking_resource_assignment_create",
        (
            "/v1/operations/resource-assignments/{assignment_id}/retire",
            "post",
        ): "booking_resource_assignment_retire",
        (
            "/v1/operations/resource-assignments/{assignment_id}/availability",
            "put",
        ): "booking_resource_assignment_availability_replace",
    }
    for (path, method), operation_id in expected.items():
        _assert_command_policy(
            _operation(app, path, method),
            operation_id=operation_id,
            owner="booking",
            capability="booking.manage_supply",
        )


def test_queue_setup_route_has_stable_owner_operation_identity() -> None:
    app = FastAPI()
    app.include_router(
        create_service_queue_bootstrap_router(
            handler=cast(Any, object()),
            actor_resolver=cast(Any, _Resolver()),
        )
    )
    _assert_command_policy(
        _operation(app, "/v1/queues", "post"),
        operation_id="queue_service_queue_create",
        owner="queue",
        capability="queue.configure",
    )


def test_tenancy_profile_operations_use_non_bootstrap_management_capability() -> None:
    app = FastAPI()
    app.include_router(
        create_operational_router(
            profile_handler=cast(Any, object()),
            contacts_handler=cast(Any, object()),
            actor_resolver=cast(Any, _Resolver()),
        )
    )

    expected = {
        (
            "/v1/operations/organization/profile",
            "patch",
        ): "tenancy_organization_profile_update",
        (
            "/v1/operations/organization/contacts",
            "put",
        ): "tenancy_organization_contacts_replace",
    }
    for (path, method), operation_id in expected.items():
        _assert_command_policy(
            _operation(app, path, method),
            operation_id=operation_id,
            owner="tenancy",
            capability="organization.manage_profile",
        )
