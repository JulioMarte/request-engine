from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentSchedulePort,
)
from request_engine.modules.operational_copilot.adapters.discovery_publication_executors import (
    DiscoveryPublishCopilotExecutor,
    DiscoveryRevokeCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.operational_extend_day_executor import (
    OperationalExtendDayCopilotExecutor,
)
from request_engine.modules.operational_copilot.adapters.operational_intake_executor import (
    OperationalIntakeCopilotExecutor,
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
from request_engine.modules.operational_copilot.application.ports import (
    CopilotMutationExecutor,
    DiscoveryPublicationExecutor,
    RecoveryCommandExecutor,
    RecoveryExtendDayExecutor,
    RecoveryIntakeExecutor,
)
from request_engine.modules.queue.contracts.intake import QueueIntakeControlPort


def build_mutation_executors(
    *,
    recovery: RecoveryCommandExecutor | None,
    recovery_intake: RecoveryIntakeExecutor | None,
    recovery_extend_day: RecoveryExtendDayExecutor | None,
    operational_intake: QueueIntakeControlPort | None,
    operational_schedule: OperationalAssignmentSchedulePort | None,
    discovery: DiscoveryPublicationExecutor | None,
) -> tuple[CopilotMutationExecutor, ...]:
    values = (
        RecoveryProposalCopilotExecutor(recovery) if recovery else None,
        RecoveryExecutionCopilotExecutor(recovery) if recovery else None,
        RecoveryIntakeCopilotExecutor(recovery_intake) if recovery_intake else None,
        RecoveryExtendDayCopilotExecutor(recovery_extend_day) if recovery_extend_day else None,
        OperationalIntakeCopilotExecutor(operational_intake) if operational_intake else None,
        OperationalExtendDayCopilotExecutor(operational_schedule) if operational_schedule else None,
        DiscoveryPublishCopilotExecutor(discovery) if discovery else None,
        DiscoveryRevokeCopilotExecutor(discovery) if discovery else None,
    )
    return tuple(value for value in values if value is not None)
