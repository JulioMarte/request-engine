from uuid import UUID


class CommunicationsError(Exception):
    """Base class for transactional communication failures."""


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
