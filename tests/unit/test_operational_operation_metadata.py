"""Docs 15/16: mounted owner operations remain addressable without granting authority.

The real operational composition/OpenAPI/catalog are exercised. Persistence is excluded:
the session factory raises if called. Missing metadata, ID collisions or capability
leakage must fail this proof; transactional authorization remains PostgreSQL evidence.
"""

from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from httpx import Client

from request_engine.entrypoints.http.operational_app import create_operational_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PREFIX = "/v1/operations"
OPERATIONS = (
    (
        "PUT",
        "/resource-assignments/{assignment_id}/exceptions",
        "booking_resource_assignment_exception_set",
        "booking",
        "booking.manage_supply",
    ),
    (
        "PUT",
        "/resources/{resource_id}/exceptions",
        "booking_resource_exception_set",
        "booking",
        "booking.manage_supply",
    ),
    ("POST", "/context-terms", "booking_context_terms_configure", "booking", "catalog.manage"),
    (
        "POST",
        "/context-terms/{current_context_terms_id}/supersede",
        "booking_context_terms_supersede",
        "booking",
        "catalog.manage",
    ),
    (
        "PUT",
        "/discovery/offerings/{offering_id}/classification",
        "discovery_offering_classification_set",
        "discovery",
        "discovery.manage",
    ),
    (
        "POST",
        "/discovery/offerings/{offering_id}/classification/revoke",
        "discovery_offering_classification_revoke",
        "discovery",
        "discovery.manage",
    ),
    (
        "PUT",
        "/discovery/resources/{resource_id}/public-profile",
        "discovery_resource_public_profile_set",
        "discovery",
        "discovery.manage",
    ),
    (
        "POST",
        "/discovery/resources/{resource_id}/public-profile/deactivate",
        "discovery_resource_public_profile_deactivate",
        "discovery",
        "discovery.manage",
    ),
    (
        "POST",
        "/discovery/publications",
        "discovery_supply_publish",
        "discovery",
        "discovery.manage",
    ),
    (
        "POST",
        "/discovery/publications/{publication_id}/revoke",
        "discovery_publication_revoke",
        "discovery",
        "discovery.manage",
    ),
)

pytestmark = pytest.mark.contract


class _ActorResolver:
    def __init__(self, capabilities: tuple[str, ...]) -> None:
        self.actor = ActorContext(
            organization_id=uuid4(),
            principal_id=uuid4(),
            capabilities=frozenset(capabilities),
        )

    async def resolve_actor(self, request: Request) -> ActorContext:
        return self.actor


def _client(*capabilities: str) -> Client:
    sessions = Mock(side_effect=AssertionError("metadata must not access PostgreSQL"))
    return cast(
        Client,
        TestClient(
            create_operational_app(
                session_factory=cast(SessionFactory, sessions),
                actor_resolver=_ActorResolver(capabilities),
            )
        ),
    )


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    with _client() as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("method,path,operation_id,owner,capability", OPERATIONS)
def test_mounted_operation_metadata(
    schema: dict[str, Any],
    method: str,
    path: str,
    operation_id: str,
    owner: str,
    capability: str,
) -> None:
    operation = schema["paths"][PREFIX + path][method.lower()]
    assert operation["operationId"] == operation_id
    assert operation["x-request-engine-operation-id"] == operation_id
    assert operation["x-request-engine-owner"] == owner
    assert operation["x-request-engine-capability"] == capability
    assert operation["x-request-engine-kind"] == "command"
    assert operation["x-request-engine-exposure"] == "operator"
    assert operation["x-request-engine-schema-version"] == 1
    assert operation["x-request-engine-idempotency"] == "required"
    assert operation["x-request-engine-expected-revision"] == (
        "required" if capability == "booking.manage_supply" else "none"
    )
    assert "x-request-engine-tool-name" not in operation
    assert operation["requestBody"]["required"] is True
    assert any(
        parameter["in"] == "header"
        and parameter["name"] == "Idempotency-Key"
        and parameter["required"] is True
        for parameter in operation["parameters"]
    )


def test_all_mounted_operation_ids_are_unique(schema: dict[str, Any]) -> None:
    identities = [
        operation["operationId"]
        for path in schema["paths"].values()
        for method, operation in path.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    assert len(identities) == len(set(identities))


@pytest.mark.parametrize(
    "capabilities",
    [
        (),
        ("appointments.book",),
        ("booking.manage_supply",),
        ("catalog.manage",),
        ("discovery.manage",),
        ("booking.manage_supply", "catalog.manage", "discovery.manage"),
    ],
)
def test_mounted_catalog_filters_operations_by_actor_capability(
    capabilities: tuple[str, ...],
) -> None:
    with _client(*capabilities) as client:
        response = client.get("/v1/operation-catalog")
    assert response.status_code == 200
    operations = response.json()["operations"]
    target_ids = {item[2] for item in OPERATIONS}
    assert {item["operation_id"] for item in operations} & target_ids == {
        operation_id
        for _, _, operation_id, _, capability in OPERATIONS
        if capability in capabilities
    }
    assert all(item["capability"] in capabilities for item in operations)
    for item in operations:
        if item["operation_id"] in target_ids:
            assert (
                item["method"],
                item["path_template"],
                item["operation_id"],
                item["owner"],
                item["capability"],
            ) in {
                (method, PREFIX + path, operation_id, owner, capability)
                for method, path, operation_id, owner, capability in OPERATIONS
            }
            assert item["tool_name"] is None
