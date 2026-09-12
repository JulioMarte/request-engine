from uuid import uuid4

from request_engine.entrypoints.http.operation_catalog import authorized_operations
from request_engine.platform.security.context import ActorContext


def _operation(
    operation_id: str,
    capability: str,
    *,
    owner: str = "catalog",
    kind: str = "command",
    tool_name: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "operationId": operation_id,
        "x-request-engine-operation-id": operation_id,
        "x-request-engine-owner": owner,
        "x-request-engine-capability": capability,
        "x-request-engine-kind": kind,
        "x-request-engine-exposure": "operator",
        "x-request-engine-idempotency": "required" if kind == "command" else "none",
        "x-request-engine-expected-revision": "none",
    }
    if tool_name is not None:
        value["x-request-engine-tool-name"] = tool_name
        value["x-request-engine-tool-audiences"] = ["admin"]
    return value


def _actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(capabilities),
    )


def test_catalog_filters_known_admin_operation_when_actor_lacks_capability() -> None:
    openapi: dict[str, object] = {
        "paths": {
            "/v1/operations/locations": {
                "post": _operation("catalog_location_create", "catalog.manage")
            },
            "/v1/appointments/slots": {
                "get": _operation(
                    "appointments_find_slots",
                    "appointments.find_slots",
                    owner="booking",
                    kind="query",
                )
            },
        }
    }

    operations = authorized_operations(openapi, _actor("appointments.find_slots"))

    assert [item.operation_id for item in operations] == ["appointments_find_slots"]
    assert all(item.capability != "catalog.manage" for item in operations)


def test_one_capability_can_authorize_multiple_distinct_operations() -> None:
    openapi: dict[str, object] = {
        "paths": {
            "/v1/operations/locations": {
                "post": _operation("catalog_location_create", "catalog.manage")
            },
            "/v1/operations/locations/{location_id}/hours": {
                "put": _operation("catalog_location_hours_replace", "catalog.manage")
            },
        }
    }

    operations = authorized_operations(openapi, _actor("catalog.manage"))

    assert [item.operation_id for item in operations] == [
        "catalog_location_create",
        "catalog_location_hours_replace",
    ]
    assert {item.capability for item in operations} == {"catalog.manage"}


def test_tool_projection_metadata_is_returned_but_does_not_grant_visibility() -> None:
    openapi: dict[str, object] = {
        "paths": {
            "/v1/operations/locations": {
                "post": _operation(
                    "catalog_location_create",
                    "catalog.manage",
                    tool_name="catalog.location.create",
                )
            }
        }
    }

    assert authorized_operations(openapi, _actor()) == ()

    operations = authorized_operations(openapi, _actor("catalog.manage"))
    assert len(operations) == 1
    assert operations[0].tool_name == "catalog.location.create"
    assert operations[0].tool_audiences == ("admin",)


def test_routes_without_canonical_operation_metadata_are_not_advertised() -> None:
    openapi: dict[str, object] = {
        "paths": {
            "/health": {"get": {"operationId": "health"}},
            "/v1/debug": {
                "get": {
                    "operationId": "debug",
                    "x-request-engine-capability": "catalog.manage",
                }
            },
        }
    }

    assert authorized_operations(openapi, _actor("catalog.manage")) == ()
