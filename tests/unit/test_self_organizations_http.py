from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.self_organizations import create_self_organization_router
from request_engine.modules.tenancy.application.queries.self_organizations import SelfOrganization
from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

pytestmark = [pytest.mark.unit, pytest.mark.security]


class _SubjectResolver:
    def __init__(self, subject: AuthenticatedSubject) -> None:
        self.subject = subject

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        if request.headers.get("authorization") != "Bearer verified-test-credential":
            raise AuthenticationRequired("Bearer required")
        return AuthenticatedHttpSubject(self.subject, "test")


class _Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[AuthenticatedSubject, UUID | None, int]] = []
        self.rows = tuple(
            SelfOrganization(UUID(int=i), f"Organization {i}", uuid4(), uuid4())
            for i in range(1, 4)
        )

    async def list_for_subject(
        self, subject: AuthenticatedSubject, *, after: UUID | None, limit: int
    ) -> tuple[SelfOrganization, ...]:
        self.calls.append((subject, after, limit))
        return tuple(row for row in self.rows if after is None or row.organization_id > after)[
            :limit
        ]


def _app(subject: AuthenticatedSubject, reader: _Reader) -> FastAPI:
    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(
        create_self_organization_router(reader=reader, subject_resolver=_SubjectResolver(subject))
    )
    return app


@pytest.mark.asyncio
async def test_self_discovery_is_subject_bound_paginated_and_advisory() -> None:
    subject = AuthenticatedSubject(str(uuid4()), str(uuid4()), AuthenticatedSubjectClass.HUMAN)
    reader = _Reader()
    app = _app(subject, reader)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        first = await client.get(
            "/v1/me/organizations?limit=2",
            headers={"Authorization": "Bearer verified-test-credential"},
        )
        assert first.status_code == 200
        assert first.headers["cache-control"] == "no-store"
        assert [item["display_name"] for item in first.json()["items"]] == [
            "Organization 1",
            "Organization 2",
        ]
        assert first.json()["requires_owner_validation"] is True
        assert reader.calls == [(subject, None, 3)]
        second = await client.get(
            "/v1/me/organizations",
            params={"after": first.json()["next_after"], "limit": "2"},
            headers={"Authorization": "Bearer verified-test-credential"},
        )
        assert [item["display_name"] for item in second.json()["items"]] == ["Organization 3"]
        assert second.json()["next_after"] is None
    operation = app.openapi()["paths"]["/v1/me/organizations"]["get"]
    assert operation["operationId"] == "self_organization_list"
    assert operation["x-request-engine-owner"] == "tenancy"
    assert operation["x-request-engine-kind"] == "query"
    assert operation["x-request-engine-idempotency"] == "none"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "subject_id=foreign",
        "identity_authority_id=foreign",
        "organization_id=foreign",
        "principal_id=foreign",
        "limit=0",
        "limit=101",
        "after=invalid",
    ],
)
async def test_self_discovery_rejects_untrusted_selectors_and_invalid_pagination(
    query: str,
) -> None:
    subject = AuthenticatedSubject(str(uuid4()), str(uuid4()), AuthenticatedSubjectClass.HUMAN)
    reader = _Reader()
    async with AsyncClient(
        transport=ASGITransport(app=_app(subject, reader)), base_url="https://test"
    ) as client:
        response = await client.get(
            f"/v1/me/organizations?{query}",
            headers={"Authorization": "Bearer verified-test-credential"},
        )
    assert response.status_code == 422
    assert reader.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status", [("anonymous", 401), ("workload", 401), ("recovery", 403), ("tenant", 400)]
)
async def test_self_discovery_denies_unusable_authentication_before_reader(
    case: str, status: int
) -> None:
    subject = AuthenticatedSubject(
        str(uuid4()),
        str(uuid4()),
        AuthenticatedSubjectClass.WORKLOAD
        if case == "workload"
        else AuthenticatedSubjectClass.HUMAN,
        {"recovery_restricted": "true"} if case == "recovery" else {},
    )
    reader = _Reader()
    headers = {} if case == "anonymous" else {"Authorization": "Bearer verified-test-credential"}
    if case == "tenant":
        headers["X-RE-Organization-ID"] = str(uuid4())
    async with AsyncClient(
        transport=ASGITransport(app=_app(subject, reader)), base_url="https://test"
    ) as client:
        response = await client.get("/v1/me/organizations", headers=headers)
    assert response.status_code == status
    assert reader.calls == []
