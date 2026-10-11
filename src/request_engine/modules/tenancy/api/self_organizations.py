"""Authenticated discovery before tenant selection; never tenant authorization."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.queries.self_organizations import (
    SelfOrganizationReader,
)
from request_engine.platform.security.authentication import AuthenticatedSubjectClass
from request_engine.platform.security.freshness import RecoveryCompletionRequired
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    HttpSubjectResolver,
)
from request_engine.platform.security.tenant_http import ORGANIZATION_HEADER, TenantContextInvalid


class SelfOrganizationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


class SelfOrganizationView(BaseModel):
    organization_id: UUID
    display_name: str
    principal_id: UUID
    membership_id: UUID


class SelfOrganizationPageView(BaseModel):
    items: list[SelfOrganizationView]
    next_after: UUID | None
    requires_owner_validation: Literal[True] = True


def create_self_organization_router(
    *, reader: SelfOrganizationReader, subject_resolver: HttpSubjectResolver
) -> APIRouter:
    router = APIRouter(prefix="/v1/me", tags=["tenancy"])

    async def authenticated_subject(
        request: Request,
        _credential: Annotated[
            HTTPAuthorizationCredentials | None,
            Security(HTTPBearer(scheme_name="SubjectBearer", auto_error=False)),
        ],
    ) -> AuthenticatedHttpSubject:
        if ORGANIZATION_HEADER in request.headers:
            raise TenantContextInvalid("Self discovery does not accept a tenant selector")
        authenticated = await subject_resolver.resolve_subject(request)
        if authenticated.subject.subject_class is not AuthenticatedSubjectClass.HUMAN:
            raise AuthenticationRequired("Human authentication is required")
        if authenticated.subject.metadata.get("recovery_restricted", "").lower() == "true":
            raise RecoveryCompletionRequired("Complete identity recovery before tenant discovery")
        return authenticated

    async def list_organizations(
        params: Annotated[SelfOrganizationParams, Query()],
        authenticated: Annotated[AuthenticatedHttpSubject, Depends(authenticated_subject)],
        response: Response,
    ) -> SelfOrganizationPageView:
        rows = await reader.list_for_subject(
            authenticated.subject, after=params.after, limit=params.limit + 1
        )
        page = rows[: params.limit]
        response.headers["Cache-Control"] = "no-store"
        return SelfOrganizationPageView(
            items=[
                SelfOrganizationView(
                    organization_id=row.organization_id,
                    display_name=row.display_name,
                    principal_id=row.principal_id,
                    membership_id=row.membership_id,
                )
                for row in page
            ],
            next_after=page[-1].organization_id if len(rows) > params.limit else None,
        )

    router.add_api_route(
        "/organizations",
        list_organizations,
        methods=["GET"],
        operation_id="self_organization_list",
        response_model=SelfOrganizationPageView,
        openapi_extra={
            "x-request-engine-owner": "tenancy",
            "x-request-engine-kind": "query",
            "x-request-engine-idempotency": "none",
            "x-request-engine-authentication": "human-subject",
        },
    )
    return router
