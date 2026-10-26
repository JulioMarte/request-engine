"""HTTP projection and admission; DB proofs own current Party authority."""

from dataclasses import asdict
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.catalog.api.administration_router import create_administration_router
from request_engine.modules.catalog.application.queries.administration import (
    AdministrativeLocation,
    AdministrativeLocationConfiguration,
    AdministrativeOffering,
    CatalogAdministrationQuery,
)
from request_engine.platform.security.context import ActorContext


@pytest.mark.asyncio
async def test_administrative_inventory_admits_only_trusted_actor_and_bounded_filters() -> None:
    org, principal, party, location_id, offering_id, version_id = (uuid4() for _ in range(6))

    class Resolver:
        async def resolve_actor(self, request: Any) -> ActorContext:
            return ActorContext(
                organization_id=org,
                principal_id=principal,
                capabilities=frozenset({"catalog.read_configuration"})
                if request.headers.get("Authorization")
                else frozenset(),
            )

    class Reader:
        calls: list[CatalogAdministrationQuery] = []

        async def locations(
            self, query: CatalogAdministrationQuery
        ) -> tuple[AdministrativeLocation, ...]:
            self.calls.append(query)
            if query.target_id is not None and query.target_id != location_id:
                return ()
            location = AdministrativeLocation(
                location_id,
                "main",
                "Main office",
                "America/Santo_Domingo",
                False,
                7,
                "Street 1",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            if query.target_id is not None:
                return (
                    AdministrativeLocationConfiguration(
                        **asdict(location),
                        hours_windows=(),
                        public_contacts=(),
                    ),
                )
            return (location,)

        async def offerings(
            self, query: CatalogAdministrationQuery
        ) -> tuple[AdministrativeOffering, ...]:
            self.calls.append(query)
            if query.target_id is not None and query.target_id != offering_id:
                return ()
            return (
                AdministrativeOffering(
                    offering_id, "exam", "Exam", None, False, version_id, 2, 30, True, True, 4, 3
                ),
            )

    reader = Reader()
    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(create_administration_router(reader, Resolver()))
    params = {"authority_party_id": str(party)}
    headers = {"Authorization": "explicit-grant", "X-RE-Organization-ID": str(uuid4())}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/v1/catalog/locations/configuration", params=params)
        assert denied.status_code == 403 and reader.calls == []
        for path in ("locations", "offerings"):
            page = await client.get(
                f"/v1/catalog/{path}/configuration", params=params, headers=headers
            )
            assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"
            assert page.json()["items"][0]["active"] is False
            assert page.json()["next_cursor"] is None
            for invalid in (
                {"limit": "101"},
                {"after": "invalid"},
                {"organization_id": str(uuid4())},
                {"principal_id": str(uuid4())},
            ):
                call_count = len(reader.calls)
                invalid_page = await client.get(
                    f"/v1/catalog/{path}/configuration",
                    params={**params, **invalid},
                    headers=headers,
                )
                assert invalid_page.status_code == 422 and len(reader.calls) == call_count
        location = await client.get(
            f"/v1/catalog/locations/{location_id}/configuration", params=params, headers=headers
        )
        offering = await client.get(
            f"/v1/catalog/offerings/{offering_id}/configuration", params=params, headers=headers
        )
        missing = await client.get(
            f"/v1/catalog/locations/{uuid4()}/configuration", params=params, headers=headers
        )
        assert location.json()["operational_revision"] == 7
        assert location.json()["hours_windows"] == []
        assert location.json()["public_contacts"] == []
        assert offering.json()["offering_version_id"] == str(version_id)
        assert offering.json()["booking_policy_revision"] == 4
        assert missing.status_code == 404
    assert all(
        call.organization_id == org
        and call.principal_id == principal
        and call.authority_party_id == party
        for call in reader.calls
    )
    operations = [
        operation for path in app.openapi()["paths"].values() for operation in path.values()
    ]
    assert {operation["operationId"] for operation in operations} == {
        "catalog_location_configuration_list",
        "catalog_location_configuration_read",
        "catalog_offering_configuration_list",
        "catalog_offering_configuration_read",
    }
    assert all(
        operation["x-request-engine-owner"] == "catalog"
        and operation["x-request-engine-capability"] == "catalog.read_configuration"
        for operation in operations
    )
