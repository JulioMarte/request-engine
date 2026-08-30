from fastapi import FastAPI

from request_engine.modules.operational_copilot.adapters.discovery_publication_executors import (
    DiscoveryPublishCopilotExecutor,
    DiscoveryRevokeCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.recovery_command_executors import (
    RecoveryExecutionCopilotExecutor,
    RecoveryProposalCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.recovery_extend_day_executor import (
    RecoveryExtendDayCopilotExecutor,
)
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
    DiscoveryPublicationExecutor,
    RecoveryCommandExecutor,
    RecoveryExtendDayExecutor,
    RecoveryIntakeExecutor,
    RecoveryProposalReader,
)
from request_engine.platform.security.http import ActorResolver

__all__ = ["build_live_capacity_at_risk_reader", "install_http"]


def install_http(
    app: FastAPI,
    *,
    actor_resolver: ActorResolver,
    at_risk_reader: AtRiskReservationReader,
    proposal_reader: RecoveryProposalReader | None = None,
    authority_reader: AuthorityPartyReader | None = None,
    recovery_executor: RecoveryCommandExecutor | None = None,
    intake_executor: RecoveryIntakeExecutor | None = None,
    extend_day_executor: RecoveryExtendDayExecutor | None = None,
    discovery_executor: DiscoveryPublicationExecutor | None = None,
) -> None:
    executors = (
        RecoveryProposalCopilotExecutor(recovery_executor) if recovery_executor else None,
        RecoveryExecutionCopilotExecutor(recovery_executor) if recovery_executor else None,
        RecoveryIntakeCopilotExecutor(intake_executor) if intake_executor else None,
        RecoveryExtendDayCopilotExecutor(extend_day_executor) if extend_day_executor else None,
        DiscoveryPublishCopilotExecutor(discovery_executor) if discovery_executor else None,
        DiscoveryRevokeCopilotExecutor(discovery_executor) if discovery_executor else None,
    )
    copilot = OperationalCopilot(
        at_risk_reader,
        proposal_reader,
        authority_reader,
        tuple(executor for executor in executors if executor is not None),
    )
    app.include_router(create_copilot_router(copilot=copilot, actor_resolver=actor_resolver))
