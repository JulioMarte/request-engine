from dataclasses import replace
from uuid import uuid4

from request_engine.entrypoints.http.operation_catalog import authorized_operations
from request_engine.platform.security.agent_policy import AgentPolicySnapshot
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.operation_risk import OperationRiskClass


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


def test_agent_catalog_intersects_policy_and_risk_without_advertising_authority_changes() -> None:
    capabilities = frozenset(
        {
            "parties.lookup",
            "parties.register",
            "appointments.book",
            "agent.suspend",
            "queue.call_next",
            "unknown.capability",
        }
    )
    openapi: dict[str, object] = {
        "paths": {f"/v1/{key}": {"post": _operation(key, key)} for key in capabilities}
    }
    actor = replace(_actor(*capabilities), principal_kind=PrincipalKind.AGENT)
    assert authorized_operations(openapi, actor) == ()
    policy = AgentPolicySnapshot(
        allowed_capabilities=capabilities,
        denied_capabilities=frozenset({"parties.register"}),
        risk_ceiling=OperationRiskClass.LOW_IMPACT_WRITE,
        max_mutations_per_minute=10,
        policy_revision=1,
    )
    actor = replace(actor, agent_policy=policy)
    assert [item.capability for item in authorized_operations(openapi, actor)] == ["parties.lookup"]
    actor = replace(
        actor, agent_policy=replace(policy, risk_ceiling=OperationRiskClass.AUTHORITY_CHANGE)
    )
    assert {item.capability for item in authorized_operations(openapi, actor)} == {
        "appointments.book",
        "parties.lookup",
    }
    actor = replace(actor, agent_policy=replace(policy, allowed_capabilities=frozenset()))
    assert authorized_operations(openapi, actor) == ()


def test_catalog_pointer_resolves_canonical_operation_with_escaped_path() -> None:
    operation = _operation("lookup", "parties.lookup", kind="query")
    openapi: dict[str, object] = {"paths": {"/v1/~lookup/{party_id}": {"get": operation}}}
    view = authorized_operations(openapi, _actor("parties.lookup"))[0]
    assert view.openapi_pointer == "/paths/~1v1~1~0lookup~1{party_id}/get"


def test_catalog_describes_party_authority_requirements_without_granting_them() -> None:
    openapi: dict[str, object] = {
        "paths": {"/v1/appointments": {"post": _operation("book", "appointments.book")}}
    }
    view = authorized_operations(openapi, _actor("appointments.book"))[0]
    assert view.party_scope == "appointments.book"
    assert view.override_capability == "appointments.subject_override"
