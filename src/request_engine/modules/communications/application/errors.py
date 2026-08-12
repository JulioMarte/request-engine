from uuid import UUID

from request_engine.modules.communications.domain.errors import CommunicationsError
from request_engine.modules.communications.domain.errors import (
    DeliveryConfigurationError as DeliveryConfigurationError,
)


class RecipientNotFound(CommunicationsError):
    def __init__(self, party_id: UUID) -> None:
        super().__init__(f"recipient Party {party_id} was not found or is inactive")
        self.party_id = party_id


class ContactPointNotUsable(CommunicationsError):
    def __init__(self, contact_point_id: UUID) -> None:
        super().__init__(
            f"contact point {contact_point_id} does not belong to the active recipient"
        )
        self.contact_point_id = contact_point_id


class InvalidCommunicationWindow(CommunicationsError):
    pass


class CommunicationDedupeConflict(CommunicationsError):
    def __init__(self, dedupe_key: str) -> None:
        super().__init__(f"communication dedupe key {dedupe_key!r} identifies different intent")
        self.dedupe_key = dedupe_key


class DeliveryProviderNotConfigured(CommunicationsError):
    def __init__(self, provider_key: str) -> None:
        super().__init__(f"communication provider {provider_key!r} is not configured")
        self.provider_key = provider_key


class CommunicationTaskNotFound(CommunicationsError):
    def __init__(self, communication_task_id: UUID) -> None:
        super().__init__(f"CommunicationTask {communication_task_id} was not found")
        self.communication_task_id = communication_task_id


class CommunicationDeliveryNotFound(CommunicationsError):
    def __init__(self, delivery_id: UUID) -> None:
        super().__init__(f"CommunicationDelivery {delivery_id} was not found")
        self.delivery_id = delivery_id


class ReminderPlanNotFound(CommunicationsError):
    def __init__(self, reminder_plan_id: UUID) -> None:
        super().__init__(f"ReminderPlan {reminder_plan_id} was not found")
        self.reminder_plan_id = reminder_plan_id


class ReminderPlanNotActive(CommunicationsError):
    def __init__(self, reminder_plan_id: UUID, status: str) -> None:
        super().__init__(f"ReminderPlan {reminder_plan_id} is not active: {status}")
        self.reminder_plan_id = reminder_plan_id
        self.status = status


class UnsupportedScheduledAction(CommunicationsError):
    def __init__(self, owner_module: str, action_type: str, action_version: int) -> None:
        super().__init__(
            f"unsupported scheduled action {owner_module}:{action_type}:v{action_version}"
        )
