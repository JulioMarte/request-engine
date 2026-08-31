from request_engine.modules.operational_copilot.contracts import (
    CopilotIntent,
    ShowAtRiskReservationsIntent,
)
from request_engine.modules.operational_copilot.parsing.patterns import (
    UUID_PATTERN,
    compile_pattern,
    parse_uuid,
)

_AT_RISK = compile_pattern(rf"show reservations at risk for queue (?P<queue>{UUID_PATTERN})")


def parse_inspection_intent(text: str) -> CopilotIntent | None:
    at_risk = _AT_RISK.fullmatch(text)
    if at_risk is not None:
        return ShowAtRiskReservationsIntent(service_queue_id=parse_uuid(at_risk.group("queue")))
    return None
