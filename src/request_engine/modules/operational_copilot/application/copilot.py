from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.application.fingerprint_resolution import (
    resolve_execute_fingerprints,
)
from request_engine.modules.operational_copilot.application.ports import (
    AtRiskReservationReader,
    RecoveryProposalReader,
)
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
    CopilotIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import UnsupportedCopilotIntent
from request_engine.modules.operational_copilot.lowering import (
    CopilotOperation,
    lower_copilot_intent,
)
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.policy import validate_copilot_intent


class OperationalCopilot:
    def __init__(
        self,
        at_risk_reader: AtRiskReservationReader,
        proposal_reader: RecoveryProposalReader | None = None,
    ) -> None:
        self._at_risk_reader = at_risk_reader
        self._proposal_reader = proposal_reader

    async def interpret(self, context: CopilotContext, text: str) -> CopilotOperation:
        intent = parse_copilot_intent(text)
        resolved = await self._resolve(intent, context)
        validated = validate_copilot_intent(context, resolved)
        return lower_copilot_intent(context, validated)

    async def inspect_at_risk(
        self,
        context: CopilotContext,
        text: str,
    ) -> RecoveryCapacityAssessment:
        operation = await self.interpret(context, text)
        return await self.read_at_risk(context, operation)

    async def read_at_risk(
        self,
        context: CopilotContext,
        operation: CopilotOperation,
    ) -> RecoveryCapacityAssessment:
        if not isinstance(operation, AtRiskReservationsQuery):
            raise UnsupportedCopilotIntent("intent is not an inspection query")
        return await self._at_risk_reader.read(operation)

    async def _resolve(self, intent: CopilotIntent, context: CopilotContext) -> CopilotIntent:
        if not isinstance(intent, ExecuteRecoveryIntent):
            return intent
        if self._proposal_reader is None:
            if intent.expected_source_fingerprint is None:
                raise UnsupportedCopilotIntent(
                    "execute intent requires explicit fingerprints in this deployment"
                )
            return intent
        return await resolve_execute_fingerprints(self._proposal_reader, context, intent)
