from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CopilotIntent,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ValidatedCopilotIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotPolicyRejected

_MAX_FINGERPRINT_LENGTH = 512


def validate_copilot_intent(
    context: CopilotContext,
    intent: CopilotIntent,
) -> ValidatedCopilotIntent:
    if not context.idempotency_key.strip():
        raise CopilotPolicyRejected("idempotency key is required")

    if isinstance(intent, CreateRecoveryProposalIntent):
        if not 1 <= intent.search_days <= 30:
            raise CopilotPolicyRejected("search days must be between 1 and 30")
        return ValidatedCopilotIntent(intent)

    if isinstance(intent, ExecuteRecoveryIntent):
        _require_fingerprint("source", intent.expected_source_fingerprint)
        _require_fingerprint("proposal", intent.expected_proposal_fingerprint)
        return ValidatedCopilotIntent(intent)

    raise CopilotPolicyRejected("intent type is not supported")


def _require_fingerprint(name: str, value: str) -> None:
    if not value or len(value) > _MAX_FINGERPRINT_LENGTH:
        raise CopilotPolicyRejected(
            f"{name} fingerprint must contain 1-{_MAX_FINGERPRINT_LENGTH} characters"
        )
