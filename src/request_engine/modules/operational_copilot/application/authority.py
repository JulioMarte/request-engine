from dataclasses import replace

from request_engine.modules.operational_copilot.application.ports import AuthorityPartyReader
from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CopilotIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotPolicyRejected

_COPILOT_AUTHORITY_SCOPES = frozenset(
    {
        "operations.manage_profile",
        "operations.manage_supply",
        "operations.manage_discovery",
    }
)

_AuthorityRequiredIntents = (
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
)


async def resolve_trusted_authority_party(
    reader: AuthorityPartyReader,
    context: CopilotContext,
    intent: CopilotIntent,
) -> CopilotContext:
    if not isinstance(intent, _AuthorityRequiredIntents):
        return context
    if context.authority_party_id is not None:
        return context
    party = await reader.resolve_operational_party(
        organization_id=context.organization_id,
        principal_id=context.principal_id,
        scope_keys=_COPILOT_AUTHORITY_SCOPES,
    )
    if party is None:
        raise CopilotPolicyRejected(
            "trusted party authority is required and could not be resolved for this principal"
        )
    return replace(context, authority_party_id=party)
