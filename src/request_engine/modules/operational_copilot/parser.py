from request_engine.modules.operational_copilot.errors import (
    AmbiguousCopilotIntent,
    UnsupportedCopilotIntent,
)
from request_engine.modules.operational_copilot.parsing.discovery import parse_discovery_intent
from request_engine.modules.operational_copilot.parsing.inspection import parse_inspection_intent
from request_engine.modules.operational_copilot.parsing.recovery import parse_recovery_intent
from request_engine.modules.operational_copilot.parsing.roadmap import parse_roadmap_intent
from request_engine.modules.operational_copilot.parsing.workflow import parse_workflow_intent
from request_engine.modules.operational_copilot.references import CopilotParsedIntent

_PARSERS = (
    parse_roadmap_intent,
    parse_recovery_intent,
    parse_workflow_intent,
    parse_discovery_intent,
    parse_inspection_intent,
)

_ACTION_MARKERS = (
    "propose recovery",
    "execute recovery",
    "walk-ins for incident",
    "extend day for incident",
    "publish offering",
    "revoke discovery publication",
    "show reservations at risk",
    "will work until",
    "stop accepting walk-ins",
    " discovery",
    "show me which reservations are at risk",
)


def parse_copilot_intent(text: str) -> CopilotParsedIntent:
    normalized = " ".join(text.strip().split())
    lowered = normalized.casefold()
    matches = [intent for parse in _PARSERS if (intent := parse(normalized)) is not None]
    if len(matches) > 1:
        raise AmbiguousCopilotIntent("multiple supported actions were requested")
    if not matches:
        counts = [lowered.count(marker) for marker in _ACTION_MARKERS]
        if sum(1 for count in counts if count > 0) > 1 or any(count > 1 for count in counts):
            raise AmbiguousCopilotIntent("multiple supported actions were requested")
        raise UnsupportedCopilotIntent("input is outside the bounded F6 grammar")
    return matches[0]
