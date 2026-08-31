from request_engine.modules.discovery.contracts.commands import (
    PublishDiscoverySupplyCommand,
    RevokeDiscoveryPublicationCommand,
)
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
)
from request_engine.modules.operational_copilot.lowering.operations import CopilotOperation


def lower_publish(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, PublishDiscoverySupplyIntent):
        raise TypeError("unsupported publish intent")
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
        effective_start_is_resolved_now=intent.effective_start_is_resolved_now,
    )


def lower_revoke(intent: object, context: CopilotContext) -> CopilotOperation:
    if not isinstance(intent, RevokeDiscoveryPublicationIntent):
        raise TypeError("unsupported revoke intent")
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
