"""Proposal decisions require current recent HUMAN authentication before any command runs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.modules.tenancy.api.staff_invitation_proposals import (
    create_staff_invitation_proposal_router,
)
from request_engine.platform.security.assurance import AuthenticationAssurance
from request_engine.platform.security.capabilities import capability_definition
from request_engine.platform.security.capability_types import AuthorityPlane
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.operation_risk import OperationRiskClass

pytestmark = [pytest.mark.unit, pytest.mark.security]


def _actor(*, authenticated_at: datetime | None) -> ActorContext:
    return ActorContext(
        uuid4(),
        uuid4(),
        frozenset({"staff.invite", "staff.read"}),
        authentication_method="native_session",
        authenticated_at=authenticated_at,
        authentication_assurance=AuthenticationAssurance.SINGLE_FACTOR,
    )


def _app(actor: ActorContext, commands: AsyncMock) -> FastAPI:
    async def resolve(_request: Request) -> ActorContext:
        return actor

    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(
        create_staff_invitation_proposal_router(commands=commands, authenticated_actor=resolve)
    )
    return app


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize("authenticated_at", [None, datetime.now(UTC) - timedelta(minutes=30)])
@pytest.mark.asyncio
async def test_stale_or_missing_authentication_cannot_decide(
    action: str, authenticated_at: datetime | None
) -> None:
    commands = AsyncMock()
    async with AsyncClient(
        transport=ASGITransport(app=_app(_actor(authenticated_at=authenticated_at), commands)),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/v1/staff/invitation-proposals/{uuid4()}:{action}",
            headers={"Idempotency-Key": "decision-1"},
            json={"expected_revision": 1, "provenance_reference": "owner"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "recent_authentication_required"
    commands.approve.assert_not_called()
    commands.reject.assert_not_called()


def test_capability_classification_keeps_decisions_human_only() -> None:
    propose = capability_definition("staff.propose_invitation")
    invite = capability_definition("staff.invite")
    assert propose is not None and invite is not None
    assert propose.authority_plane is AuthorityPlane.OPERATIONAL
    assert propose.effective_risk_class is OperationRiskClass.LOW_IMPACT_WRITE
    assert invite.authority_plane is AuthorityPlane.TENANT_CONTROL
    assert invite.effective_risk_class is OperationRiskClass.AUTHORITY_CHANGE
