import asyncio
from uuid import uuid4

from fastapi import Request

from request_engine.bootstrap.http import build_http_app
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.security.capabilities import CapabilityExposure
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.discovery import (
    BaselineTenantCapabilityPolicy,
    discover_capabilities,
)


class StaticActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        del request
        return self._actor


def test_discovered_runtime_operations_have_one_stable_openapi_operation() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(
            {
                "business.get_info",
                "catalog.search_offerings",
                "catalog.get_offering_details",
                "appointments.find_slots",
                "appointments.book",
                "appointments.read",
                "appointments.cancel",
                "appointments.reschedule",
                "appointments.confirm_attendance",
                "queue.list",
                "queue.join",
                "queue.status",
                "queue.leave",
                "queue.call_next",
                "waitlist.join",
                "waitlist.read",
                "waitlist.leave",
                "waitlist.accept_offer",
                "waitlist.decline_offer",
                "requests.submit",
                "requests.read",
                "requests.cancel",
            }
        ),
    )
    engine = create_postgres_engine("postgresql+asyncpg://user:pass@127.0.0.1/request_engine")
    app = build_http_app(
        session_factory=create_session_factory(engine),
        actor_resolver=StaticActorResolver(actor),
        appointment_option_signing_key=b"phase-5-agent-discovery-test-key",
    )
    schema = app.openapi()
    all_operations = [
        operation
        for path_item in schema["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    operation_ids = [operation["operationId"] for operation in all_operations]
    assert len(operation_ids) == len(set(operation_ids))

    discovered = asyncio.run(discover_capabilities(actor, BaselineTenantCapabilityPolicy()))
    expected = {item.definition.key for item in discovered if item.definition.runtime_available}

    operations_by_capability: dict[str, list[str]] = {}
    for operation in all_operations:
        capability = operation.get("x-request-engine-capability")
        if isinstance(capability, str):
            operations_by_capability.setdefault(capability, []).append(operation["operationId"])

    for key in expected:
        operation_ids = operations_by_capability.get(key, [])
        assert len(operation_ids) >= 1, key

    published_capabilities = {capability for capability in operations_by_capability}
    assert "requests.complete" not in published_capabilities
    assert "requests.record_result" not in published_capabilities
    assert "requests.fail" not in published_capabilities

    asyncio.run(engine.dispose())


def test_permission_only_operator_grants_never_claim_an_openapi_operation() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(
            {
                "appointments.subject_override",
                "queue.subject_override",
                "waitlist.subject_override",
                "requests.party_override",
            }
        ),
    )
    discovered = asyncio.run(discover_capabilities(actor, BaselineTenantCapabilityPolicy()))

    permissions = {
        item.definition.key
        for item in discovered
        if item.definition.exposure is CapabilityExposure.OPERATOR
    }
    assert permissions == {
        "appointments.subject_override",
        "queue.subject_override",
        "waitlist.subject_override",
        "requests.party_override",
    }
    assert all(
        item.definition.runtime_available is False
        for item in discovered
        if item.definition.key in permissions
    )
