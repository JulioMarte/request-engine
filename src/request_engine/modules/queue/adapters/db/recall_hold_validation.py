from request_engine.modules.queue.application.commands.recall_hold import RecallHoldCommand
from request_engine.modules.queue.application.same_day_selection_errors import RecallHoldInvalid
from request_engine.modules.queue.contracts.same_day_selection import RecallHoldKind


def validate_recall_hold_shape(command: RecallHoldCommand) -> None:
    if command.reason is not None and len(command.reason) > 500:
        raise RecallHoldInvalid("recall hold reason exceeds 500 characters")
    if command.kind is RecallHoldKind.UNTIL_TIME:
        if command.release_at is None or command.release_at.utcoffset() is None:
            raise RecallHoldInvalid("until_time requires an offset-aware release_at")
    elif command.release_at is not None:
        raise RecallHoldInvalid("until_customer_initiates does not accept release_at")
