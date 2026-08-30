from functools import singledispatch

from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import (
    AtRiskReservationsQuery,
    CopilotContext,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
    SetRecoveryIntakeIntent,
    ShowAtRiskReservationsIntent,
    ValidatedCopilotIntent,
)
from request_engine.modules.operational_recovery.contracts.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.workflow_commands import (
    ExtendRecoveryDayCommand,
    SetRecoveryIntakeCommand,
)

CopilotOperation = (
    CreateRecoveryProposalCommand
    | ExecuteRecoveryCommand
    | SetRecoveryIntakeCommand
    | ExtendRecoveryDayCommand
    | PublishDiscoverySupplyCommand
    | RevokeDiscoveryPublicationCommand
    | AtRiskReservationsQuery
)


def lower_copilot_intent(
    context: CopilotContext,
    validated: ValidatedCopilotIntent,
) -> CopilotOperation:
    return _lower(validated.value, context)


@singledispatch
def _lower(intent: object, context: CopilotContext) -> CopilotOperation:
    raise TypeError(f"unsupported validated copilot intent: {type(intent).__name__}")


@_lower.register
def _(intent: CreateRecoveryProposalIntent, context: CopilotContext) -> CopilotOperation:
    return CreateRecoveryProposalCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        service_queue_id=intent.service_queue_id,
        idempotency_key=context.idempotency_key,
        search_days=intent.search_days,
    )


@_lower.register
def _(intent: ExecuteRecoveryIntent, context: CopilotContext) -> CopilotOperation:
    if intent.expected_source_fingerprint is None or intent.expected_proposal_fingerprint is None:
        raise TypeError("execute lowering requires resolved fingerprints")
    return ExecuteRecoveryCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        proposal_id=intent.proposal_id,
        reservation_id=intent.reservation_id,
        expected_source_fingerprint=intent.expected_source_fingerprint,
        expected_proposal_fingerprint=intent.expected_proposal_fingerprint,
        idempotency_key=context.idempotency_key,
        allow_subject_override=intent.allow_subject_override,
        notify=intent.notify,
    )


@_lower.register
def _(intent: SetRecoveryIntakeIntent, context: CopilotContext) -> CopilotOperation:
    return SetRecoveryIntakeCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        incident_id=intent.incident_id,
        expected_source_revision=intent.expected_source_revision,
        expected_intake_revision=intent.expected_intake_revision,
        accepting=intent.accepting,
        idempotency_key=context.idempotency_key,
    )


@_lower.register
def _(intent: ExtendRecoveryDayIntent, context: CopilotContext) -> CopilotOperation:
    if context.authority_party_id is None:
        raise TypeError("extend-day lowering requires trusted authority party")
    return ExtendRecoveryDayCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        authority_party_id=context.authority_party_id,
        incident_id=intent.incident_id,
        expected_source_revision=intent.expected_source_revision,
        assignment_id=intent.assignment_id,
        start_at=intent.start_at,
        end_at=intent.end_at,
        expected_location_operational_revision=intent.expected_location_operational_revision,
        expected_resource_availability_revision=intent.expected_resource_availability_revision,
        idempotency_key=context.idempotency_key,
        reason=intent.reason,
    )


@_lower.register
def _(intent: PublishDiscoverySupplyIntent, context: CopilotContext) -> CopilotOperation:
    if context.authority_party_id is None:
        raise TypeError("discovery publication lowering requires trusted authority party")
    return PublishDiscoverySupplyCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        authority_party_id=context.authority_party_id,
        offering_id=intent.offering_id,
        location_id=intent.location_id,
        resource_id=intent.resource_id,
        effective_start=intent.effective_start,
        effective_end=intent.effective_end,
        provider_visibility=intent.provider_visibility,
        idempotency_key=context.idempotency_key,
    )


@_lower.register
def _(intent: RevokeDiscoveryPublicationIntent, context: CopilotContext) -> CopilotOperation:
    if context.authority_party_id is None:
        raise TypeError("discovery revocation lowering requires trusted authority party")
    return RevokeDiscoveryPublicationCommand(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        authority_party_id=context.authority_party_id,
        publication_id=intent.publication_id,
        expected_revision=intent.expected_revision,
        idempotency_key=context.idempotency_key,
    )


@_lower.register
def _(intent: ShowAtRiskReservationsIntent, context: CopilotContext) -> CopilotOperation:
    return AtRiskReservationsQuery(
        organization_id=context.organization_id,
        service_queue_id=intent.service_queue_id,
    )
