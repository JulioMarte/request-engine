from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.json_types import as_mapping

_OPENAPI = {
    "components": {
        "schemas": {
            "CreateThing": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
            }
        }
    },
    "paths": {
        "/v1/platform/things": {
            "post": {
                "operationId": "thing_create",
                "summary": "Create thing",
                "tags": ["Platform things"],
                "x-request-engine-capability": "thing.write",
                "x-request-engine-kind": "command",
                "x-request-engine-idempotency": "required",
                "x-request-engine-exposure": "operator",
                "x-request-engine-owner": "catalog",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CreateThing"}}
                    }
                },
            },
            "get": {
                "operationId": "thing_list",
                "summary": "List things",
                "tags": ["Platform things"],
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer"},
                    }
                ],
            },
        },
        "/v1/setup": {
            "get": {
                "operationId": "instanceSetupDiscovery",
                "summary": "Discovery",
                "tags": ["Instance setup"],
            }
        },
    },
}


def test_catalog_indexes_every_operation() -> None:
    catalog = load_catalog(_OPENAPI)
    assert set(catalog.by_id()) == {"thing_create", "thing_list", "instanceSetupDiscovery"}


def test_catalog_resolves_ref_body_and_metadata() -> None:
    operation = load_catalog(_OPENAPI).by_id()["thing_create"]
    assert operation.capability == "thing.write"
    assert operation.idempotency == "required"
    assert operation.requires_idempotency_key is True
    assert operation.is_platform_operation is True
    assert operation.body_schema is not None
    properties = as_mapping(operation.body_schema.get("properties"))
    assert set(properties) == {"name", "count"}
    assert operation.body_schema.get("required") == ["name"]


def test_catalog_groups_and_setup_flow() -> None:
    catalog = load_catalog(_OPENAPI)
    groups = catalog.groups()
    assert set(groups) == {"Platform things", "Instance setup"}
    discovery = catalog.by_id()["instanceSetupDiscovery"]
    assert discovery.auth_kind == "anonymous"
    assert discovery.console_flow == "setup"
    assert discovery.is_platform_operation is False


def test_catalog_treats_unattributed_mutation_as_no_idempotency() -> None:
    create = load_catalog(_OPENAPI).by_id()["thing_create"]
    list_operation = load_catalog(_OPENAPI).by_id()["thing_list"]
    assert create.requires_idempotency_key is True
    assert list_operation.requires_idempotency_key is False
