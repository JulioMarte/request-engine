from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.tenancy.application.queries.agent_governance import (
    AgentGovernanceReader,
    AgentSummary,
    ListAgentsQuery,
)
from request_engine.modules.tenancy.domain.agent_governance import (
    AgentOperatingMode,
    AgentProfileStatus,
)
from request_engine.platform.http.capability_routes import add_capability_route
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import require_capability


class AgentCredentialMetadataView(BaseModel):
    credential_id: UUID
    status: str
    revision: int
    expires_at: datetime


class AgentView(BaseModel):
    principal_id: UUID
    display_name: str
    purpose: str
    sponsor_principal_id: UUID
    operating_mode: AgentOperatingMode
    status: AgentProfileStatus
    principal_active: bool
    profile_revision: int
    authority_revision: int
    standing_capabilities: list[str] = Field(
        description="Active standing grants, not effective permission for every Party/resource."
    )
    credentials: list[AgentCredentialMetadataView] = Field(
        description="Stored active credentials only; expiry/lifecycle/policy can still deny use."
    )


class AgentPageView(BaseModel):
    items: list[AgentView]
    next_after: UUID | None


class AgentListParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after: UUID | None = None
    limit: int = Field(default=50, ge=1, le=100)


def _view(agent: AgentSummary) -> AgentView:
    return AgentView(
        principal_id=agent.principal_id,
        display_name=agent.display_name,
        purpose=agent.purpose,
        sponsor_principal_id=agent.sponsor_principal_id,
        operating_mode=agent.operating_mode,
        status=agent.status,
        principal_active=agent.principal_active,
        profile_revision=agent.profile_revision,
        authority_revision=agent.authority_revision,
        standing_capabilities=list(agent.standing_capabilities),
        credentials=[
            AgentCredentialMetadataView(
                credential_id=c.credential_id,
                status=c.status,
                revision=c.revision,
                expires_at=c.expires_at,
            )
            for c in agent.credentials
        ],
    )


def add_agent_governance_reads(
    router: APIRouter,
    *,
    reader: AgentGovernanceReader,
    authenticated_actor: Callable[[Request], Awaitable[ActorContext]],
) -> None:
    async def list_agents(
        params: Annotated[AgentListParams, Query()],
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> AgentPageView:
        require_capability(actor, "agent.read")
        rows = await reader.list_agents(actor, ListAgentsQuery(params.after, params.limit))
        response.headers["Cache-Control"] = "no-store"
        return AgentPageView(
            items=[_view(row) for row in rows],
            next_after=rows[-1].principal_id if len(rows) == params.limit else None,
        )

    async def read_agent(
        agent_principal_id: UUID,
        actor: Annotated[ActorContext, Depends(authenticated_actor)],
        response: Response,
    ) -> AgentView:
        require_capability(actor, "agent.read")
        result = await reader.read_agent(actor, agent_principal_id)
        response.headers["Cache-Control"] = "no-store"
        return _view(result)

    add_capability_route(
        router,
        "",
        list_agents,
        methods=["GET"],
        capability="agent.read",
        operation_id="agent_list",
        response_model=AgentPageView,
    )
    add_capability_route(
        router,
        "/{agent_principal_id}",
        read_agent,
        methods=["GET"],
        capability="agent.read",
        operation_id="agent_get",
        response_model=AgentView,
    )
