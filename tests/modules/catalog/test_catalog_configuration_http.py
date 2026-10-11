from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.catalog.api.configuration_router import create_configuration_router
from request_engine.modules.catalog.application.commands import (
    set_offering_version_booking_policy as policy_commands,
)
from request_engine.modules.catalog.application.commands.bootstrap_catalog import (
    OfferingRequirementInput,
    ResourceCapabilityState,
)
from request_engine.modules.catalog.application.queries.read_configuration import (
    OfferingConfiguration,
)
from request_engine.platform.security.context import ActorContext


@pytest.mark.asyncio
async def test_configuration_queries_require_explicit_grant_and_return_typed_revision() -> None:
    org, principal, version_id, capability_id = uuid4(), uuid4(), uuid4(), uuid4()

    class Resolver:
        async def resolve_actor(self, request: Any) -> ActorContext:
            grants: set[str] = (
                {"catalog.read_configuration"} if request.headers.get("Authorization") else set()
            )
            return ActorContext(
                organization_id=org, principal_id=principal, capabilities=frozenset(grants)
            )

    class Reader:
        calls = 0

        async def list_resource_capabilities(
            self,
            organization_id: UUID,
            *,
            principal_id: UUID,
            limit: int,
            after_id: UUID | None,
        ) -> tuple[ResourceCapabilityState, ...]:
            self.calls += 1
            assert organization_id == org
            assert principal_id == principal
            return (ResourceCapabilityState(capability_id, "exam", "Exam"),)

        async def read_offering_configuration(
            self,
            organization_id: UUID,
            offering_version_id: UUID,
            *,
            principal_id: UUID,
        ) -> OfferingConfiguration | None:
            self.calls += 1
            assert organization_id == org
            assert principal_id == principal
            if offering_version_id != version_id:
                return None
            return OfferingConfiguration(
                uuid4(),
                version_id,
                "exam",
                1,
                True,
                (OfferingRequirementInput(capability_id, 2),),
                3,
                policy_commands.BookingPolicyInput(),
            )

    reader = Reader()
    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(create_configuration_router(reader, Resolver()))
    headers = {"Authorization": "fixture-explicit-grant"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/v1/catalog/resource-capabilities")
        assert reader.calls == 0
        capabilities = await client.get("/v1/catalog/resource-capabilities", headers=headers)
        configuration = await client.get(
            f"/v1/catalog/offering-versions/{version_id}/configuration",
            headers=headers,
        )
        missing = await client.get(
            f"/v1/catalog/offering-versions/{uuid4()}/configuration",
            headers=headers,
        )
        rejected = await client.get(
            "/v1/catalog/resource-capabilities",
            headers=headers,
            params={"organization_id": str(uuid4())},
        )
    assert denied.status_code == 403
    assert capabilities.status_code == configuration.status_code == 200
    assert capabilities.json()["next_cursor"] is None
    assert (
        capabilities.headers["Cache-Control"]
        == configuration.headers["Cache-Control"]
        == "no-store"
    )
    assert configuration.json()["requirements"] == [
        {"capability_id": str(capability_id), "quantity": 2}
    ]
    assert configuration.json()["booking_policy_revision"] == 3
    assert configuration.json()["booking_policy"]["communications"]["channel_policy"] is None
    assert missing.status_code == 404 and rejected.status_code == 422
    assert reader.calls == 3
