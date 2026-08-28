from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentSchedulePort,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
    ReplaceResourceRecoveryActionCommand,
    RescheduleRecoveryActionCommand,
    SetRecoveryIntakeCommand,
)
from request_engine.modules.operational_recovery.application.workflow_intake_action import (
    execute_intake_action,
)
from request_engine.modules.operational_recovery.application.workflow_intake_port import (
    RecoveryIntakeControlPort,
)
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionPort,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_replace_resource_action import (
    execute_replace_resource_action,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_action import (
    execute_reschedule_action,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_action import (
    execute_extend_day_action,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryAction


class RecoveryWorkflowService:
    def __init__(
        self,
        *,
        repository: RecoveryWorkflowRepository,
        proposal_repository: RecoveryRepository,
        booking: RecoveryBookingPort,
        intake: RecoveryIntakeControlPort,
        location_schedule: RecoveryLocationExtensionPort,
        assignment_schedule: RecoveryAssignmentSchedulePort,
        capacity: RecoveryCapacitySource,
    ) -> None:
        self._repository = repository
        self._proposal_repository = proposal_repository
        self._booking = booking
        self._intake = intake
        self._location_schedule = location_schedule
        self._assignment_schedule = assignment_schedule
        self._capacity = capacity

    async def set_intake(self, command: SetRecoveryIntakeCommand) -> RecoveryAction:
        return await execute_intake_action(
            command,
            repository=self._repository,
            queue_intake=self._intake,
        )

    async def extend_day(self, command: ExtendRecoveryDayCommand) -> RecoveryAction:
        return await execute_extend_day_action(
            command,
            repository=self._repository,
            location_schedule=self._location_schedule,
            assignment_schedule=self._assignment_schedule,
            capacity=self._capacity,
        )

    async def reschedule(self, command: RescheduleRecoveryActionCommand) -> RecoveryAction:
        return await execute_reschedule_action(
            command,
            workflow_repository=self._repository,
            proposal_repository=self._proposal_repository,
            booking=self._booking,
            capacity=self._capacity,
        )

    async def replace_resource(
        self,
        command: ReplaceResourceRecoveryActionCommand,
    ) -> RecoveryAction:
        return await execute_replace_resource_action(
            command,
            workflow_repository=self._repository,
            proposal_repository=self._proposal_repository,
            booking=self._booking,
            capacity=self._capacity,
        )
