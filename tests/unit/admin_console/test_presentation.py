from typing import Any

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.presentation import (
    classify_operation,
    coverage_counts,
    coverage_registry,
    operator_coverage_gaps,
)


def _document() -> dict[str, Any]:
    return {
        "paths": {
            "/v1/platform/readiness": {
                "get": {
                    "operationId": "platform_readiness_get",
                    "x-request-engine-exposure": "operator",
                }
            },
            "/v1/platform/native-identities": {
                "get": {
                    "operationId": "platform_native_identity_list",
                    "x-request-engine-exposure": "operator",
                }
            },
            "/v1/platform/new-surface": {
                "get": {
                    "operationId": "platform_new_surface_get",
                    "x-request-engine-exposure": "operator",
                }
            },
            "/auth/native/sessions": {"post": {"operationId": "native_session_create"}},
        }
    }


def test_every_catalog_operation_receives_one_surface_classification() -> None:
    catalog = load_catalog(_document())
    registry = coverage_registry(catalog)
    assert len(registry) == len(catalog.operations)
    assert {entry.operation_id for entry in registry} == set(catalog.by_id())


def test_known_surfaces_and_new_operations_use_the_expected_experience() -> None:
    catalog = load_catalog(_document())
    classified = {
        operation.operation_id: classify_operation(operation) for operation in catalog.operations
    }
    assert classified["platform_readiness_get"].destination == "overview"
    assert classified["platform_native_identity_list"].destination == "native-identities"
    assert classified["platform_new_surface_get"].experience == "advanced"
    assert classified["native_session_create"].experience == "journey"
    assert coverage_counts(catalog) == {"journey": 1, "workspace": 2, "advanced": 1}
    assert operator_coverage_gaps(catalog) == ("platform_new_surface_get",)
