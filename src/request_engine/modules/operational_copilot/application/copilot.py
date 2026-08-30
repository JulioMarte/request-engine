from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacityAssessment
from request_engine.modules.operational_copilot.application.authority import (
    resolve_trusted_authority_party,
)
from request_engine.modules.operational_copilot.application.execution import (
    CopilotExecutionRegistry,
)
from request_engine.modules.operational_copilot.application.fingerprint_resolution import (
    resolve_execute_fingerprints,
)
from request_engine.modules.operational_copilot.application.ports import (
    AtRiskReservationReader,
    AuthorityPartyReader,
    CopilotMutationExecutor,
    RecoveryProposalReader,
)
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
    CopilotExecutionReceipt,
    CopilotIntent,
    ExecuteRecoveryIntent,
)
from request_engine.modules.operational_copilot.errors import UnsupportedCopilotIntent
from request_engine.modules.operational_copilot.lowering import lower_copilot_intent
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation
from request_engine.modules.operational_copilot.parser import parse_copilot_intent
from request_engine.modules.operational_copilot.policy import validate_copilot_intent


class OperationalCopilot:
    def __init__(
        self,
        at_risk_reader: AtRiskReservationReader,
        proposal_reader: RecoveryProposalReader | None = None,
        authority_reader: AuthorityPartyReader | None = None,
        mutation_executors: tuple[CopilotMutationExecutor, ...] = (),
    ) -> None:
        self._at_risk_reader = at_risk_reader
        self._proposal_reader = proposal_reader
        self._authority_reader = authority_reader
        self._execution = CopilotExecutionRegistry(mutation_executors)

    async def interpret(self, context: CopilotContext, text: str) -> CopilotOperation:
        intent = parse_copilot_intent(text)
        resolved_context = await self._resolve_authority(intent, context)
        resolved_intent = await self._resolve_fingerprints(intent, resolved_context)
        validated = validate_copilot_intent(resolved_context, resolved_intent)
        return lower_copilot_intent(resolved_context, validated)

    def execution_capability(self, operation: CopilotOperation) -> str:
        return self._execution.owner_capability(operation)

    async def execute(self, operation: CopilotOperation) -> CopilotExecutionReceipt:
        return await self._execution.execute(operation)

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

    async def _resolve_authority(
        self,
        intent: CopilotIntent,
        context: CopilotContext,
    ) -> CopilotContext:
        if self._authority_reader is None:
            return context
        return await resolve_trusted_authority_party(self._authority_reader, context, intent)

    async def _resolve_fingerprints(
        self,
        intent: CopilotIntent,
        context: CopilotContext,
    ) -> CopilotIntent:
        if not isinstance(intent, ExecuteRecoveryIntent):
            return intent
        if self._proposal_reader is None:
            if intent.expected_source_fingerprint is None:
                raise UnsupportedCopilotIntent(
                    "execute intent requires explicit fingerprints in this deployment"
                )
            return intent
        return await resolve_execute_fingerprints(self._proposal_reader, context, intent)
