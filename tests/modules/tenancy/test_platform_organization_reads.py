from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import APIRouter, FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.modules.tenancy.adapters.db.platform_organization_reader import (
    PostgresPlatformOrganizationReader,
)
from request_engine.modules.tenancy.api.platform_organization_reads import (
    add_platform_organization_reads,
    platform_organization_error_handler,
)
from request_engine.modules.tenancy.application.queries.platform_organization_read import (
    PLATFORM_ORGANIZATION_READ_CAPABILITY,
    GetPlatformOrganizationQuery,
    ListPlatformOrganizationsQuery,
    PlatformOrganizationReader,
    PlatformOrganizationReadError,
    PlatformOrganizationReadForbidden,
    PlatformOrganizationReadNotFound,
    PlatformOrganizationSummary,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext


class _FixedActorResolver:
    def __init__(self, actor: PlatformActorContext) -> None:
        self.actor = actor

    async def __call__(self, request: Request) -> PlatformActorContext:
        del request
        return self.actor


class _RecordingReader:
    def __init__(self, rows: tuple[PlatformOrganizationSummary, ...]) -> None:
        self.rows = rows
        self.list_queries: list[ListPlatformOrganizationsQuery] = []
        self.get_queries: list[GetPlatformOrganizationQuery] = []

    async def list_organizations(
        self,
        actor: PlatformActorContext,
        query: ListPlatformOrganizationsQuery,
    ) -> tuple[PlatformOrganizationSummary, ...]:
        del actor
        self.list_queries.append(query)
        return self.rows

    async def get_organization(
        self,
        actor: PlatformActorContext,
        query: GetPlatformOrganizationQuery,
    ) -> PlatformOrganizationSummary:
        del actor
        self.get_queries.append(query)
        for row in self.rows:
            if row.organization_id == query.organization_id:
                return row
        raise PlatformOrganizationReadNotFound("organization was not found")


def _organization(organization_id: UUID | None = None) -> PlatformOrganizationSummary:
    return PlatformOrganizationSummary(
        organization_id=organization_id or uuid4(),
        organization_key="clinic-north",
        display_name="Clinic North",
        operational_status="active",
        default_timezone="America/Santo_Domingo",
        default_locale="es-DO",
        default_currency="DOP",
        created_at=datetime(2026, 1, 2, 3, 4, tzinfo=UTC),
        updated_at=datetime(2026, 2, 3, 4, 5, tzinfo=UTC),
    )


def _actor() -> PlatformActorContext:
    return PlatformActorContext(
        principal_id=uuid4(),
        principal_kind=PrincipalKind.HUMAN,
        capabilities=frozenset({PLATFORM_ORGANIZATION_READ_CAPABILITY}),
        authority_revision=3,
    )


def _app(reader: _RecordingReader) -> FastAPI:
    router = APIRouter()
    add_platform_organization_reads(
        router,
        reader=cast(PlatformOrganizationReader, reader),
        authenticated_actor=_FixedActorResolver(_actor()),
    )
    app = FastAPI()
    app.add_exception_handler(PlatformOrganizationReadError, platform_organization_error_handler)
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_list_organizations_projects_only_bounded_fields_and_keyset_cursor() -> None:
    first, second = _organization(), _organization()
    reader = _RecordingReader((first, second))
    async with AsyncClient(
        transport=ASGITransport(app=_app(reader)), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/platform/organizations", params={"after": str(first.organization_id), "limit": 2}
        )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert reader.list_queries == [ListPlatformOrganizationsQuery(first.organization_id, 2)]
    assert response.json() == {
        "items": [
            {
                "organization_id": str(row.organization_id),
                "organization_key": "clinic-north",
                "display_name": "Clinic North",
                "operational_status": "active",
                "default_timezone": "America/Santo_Domingo",
                "default_locale": "es-DO",
                "default_currency": "DOP",
                "created_at": "2026-01-02T03:04:00Z",
                "updated_at": "2026-02-03T04:05:00Z",
            }
            for row in (first, second)
        ],
        "next_after": str(second.organization_id),
    }


@pytest.mark.asyncio
async def test_get_uses_path_identity_and_absent_is_a_bounded_404() -> None:
    row = _organization()
    reader = _RecordingReader((row,))
    async with AsyncClient(
        transport=ASGITransport(app=_app(reader)), base_url="http://test"
    ) as client:
        found = await client.get(f"/v1/platform/organizations/{row.organization_id}")
        missing_id = uuid4()
        missing = await client.get(f"/v1/platform/organizations/{missing_id}")

    assert found.status_code == 200, found.text
    assert found.json()["organization_id"] == str(row.organization_id)
    assert reader.get_queries == [
        GetPlatformOrganizationQuery(row.organization_id),
        GetPlatformOrganizationQuery(missing_id),
    ]
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "no-store"
    assert missing.json()["error"]["code"] == "platform_organization_not_found"


def test_routes_publish_distinct_owner_capability_and_operation_metadata() -> None:
    openapi = _app(_RecordingReader(())).openapi()
    list_operation = openapi["paths"]["/v1/platform/organizations"]["get"]
    get_operation = openapi["paths"]["/v1/platform/organizations/{organization_id}"]["get"]

    assert list_operation["operationId"] == "platform_organization_list"
    assert get_operation["operationId"] == "platform_organization_get"
    for operation in (list_operation, get_operation):
        assert operation["x-request-engine-owner"] == "tenancy"
        assert operation["x-request-engine-capability"] == PLATFORM_ORGANIZATION_READ_CAPABILITY
        assert operation["x-request-engine-kind"] == "query"


def test_list_query_rejects_out_of_contract_limits() -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        ListPlatformOrganizationsQuery(limit=0)
    with pytest.raises(ValueError, match="between 1 and 100"):
        ListPlatformOrganizationsQuery(limit=101)


@pytest.mark.asyncio
async def test_reader_denies_missing_authority_before_database_access() -> None:
    class DeniedActor:
        principal_kind = PrincipalKind.HUMAN

        def allows(self, capability: str) -> bool:
            assert capability == PLATFORM_ORGANIZATION_READ_CAPABILITY
            return False

    reader = PostgresPlatformOrganizationReader(cast(SessionFactory, object()))
    with pytest.raises(PlatformOrganizationReadForbidden):
        await reader.list_organizations(
            cast(PlatformActorContext, DeniedActor()), ListPlatformOrganizationsQuery()
        )
