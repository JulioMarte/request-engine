from typing import Protocol

from fastapi import FastAPI

from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_copilot import api as operational_copilot_api
from request_engine.modules.operational_copilot.application.ports import (
    RecoveryExtendDayExecutor,
    RecoveryIntakeExecutor,
    RecoveryProposalReader,
)
from request_engine.modules.tenancy import api as tenancy_api
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


class RecoveryWorkflowExecutor(
    RecoveryIntakeExecutor,
    RecoveryExtendDayExecutor,
    Protocol,
):
    pass


def install_operational_copilot(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    recovery_capacity: RecoveryCapacitySource,
    recovery_service: RecoveryProposalReader,
    recovery_workflow: RecoveryWorkflowExecutor,
) -> None:
    operational_copilot_api.install_http(
        app,
        actor_resolver=actor_resolver,
        at_risk_reader=operational_copilot_api.build_live_capacity_at_risk_reader(
            recovery_capacity
        ),
        proposal_reader=recovery_service,
        authority_reader=tenancy_api.build_operational_authority_party_reader(session_factory),
        intake_executor=recovery_workflow,
        extend_day_executor=recovery_workflow,
    )
