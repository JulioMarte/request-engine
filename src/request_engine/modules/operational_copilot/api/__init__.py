from fastapi import FastAPI

from request_engine.modules.operational_copilot.adapters.recovery_intake_executor import (
    RecoveryIntakeCopilotExecutor,
)
from request_engine.modules.operational_copilot.api.copilot_router import create_copilot_router
from request_engine.modules.operational_copilot.api.recovery import (
    build_live_capacity_at_risk_reader,
)
from request_engine.modules.operational_copilot.application.copilot import OperationalCopilot
from request_engine.modules.operational_copilot.application.ports import (
    AtRiskReservationReader,
    AuthorityPartyReader,
    RecoveryIntakeExecutor,
    RecoveryProposalReader,
)
from request_engine.platform.security.http import ActorResolver

__all__ = ["install_http", "build_live_capacity_at_risk_reader"]


def install_http(
    app: FastAPI,
    *,
    actor_resolver: ActorResolver,
    at_risk_reader: AtRiskReservationReader,
    proposal_reader: RecoveryProposalReader | None = None,
    authority_reader: AuthorityPartyReader | None = None,
    intake_executor: RecoveryIntakeExecutor | None = None,
) -> None:
    mutation_executors = (
        (RecoveryIntakeCopilotExecutor(intake_executor),) if intake_executor is not None else ()
    )
    copilot = OperationalCopilot(
        at_risk_reader,
        proposal_reader,
        authority_reader,
        mutation_executors,
    )
    app.include_router(create_copilot_router(copilot=copilot, actor_resolver=actor_resolver))
