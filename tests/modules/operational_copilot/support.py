from request_engine.modules.operational_copilot.contracts import CopilotIntent
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.references import UNRESOLVED_INTENT_TYPES


def parse_canonical_intent(text: str) -> CopilotIntent:
    intent = parse_copilot_intent(text)
    assert not isinstance(intent, UNRESOLVED_INTENT_TYPES)
    return intent
