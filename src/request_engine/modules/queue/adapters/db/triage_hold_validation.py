from datetime import UTC, datetime

from request_engine.modules.queue.application.commands.triage import RecallHoldCommand
from request_engine.modules.queue.application.triage_errors import InvalidRecallHold
from request_engine.modules.queue.contracts.triage import RecallHoldKind


def validate_recall_hold(command: RecallHoldCommand) -> None:
    if command.condition_kind is RecallHoldKind.UNTIL_TIME:
        if command.until_at is None or command.until_at.utcoffset() is None:
            raise InvalidRecallHold("until_time requires a timezone-aware until_at")
        if command.until_at.astimezone(UTC) <= datetime.now(UTC):
            raise InvalidRecallHold("until_at must be in the future")
        if command.event_key is not None:
            raise InvalidRecallHold("until_time cannot include event_key")
        return
    if command.condition_kind is RecallHoldKind.UNTIL_EVENT:
        if command.event_key != "external_step_completed" or command.until_at is not None:
            raise InvalidRecallHold(
                "until_event requires event_key=external_step_completed"
            )
        return
    if command.until_at is not None or command.event_key is not None:
        raise InvalidRecallHold("until_customer_initiates has no condition payload")
