from datetime import datetime
from functools import singledispatch

from request_engine.modules.operational_copilot.contracts import (
    CopilotContext,
    CopilotIntent,
    CreateRecoveryProposalIntent,
    ExecuteRecoveryIntent,
    ExtendRecoveryDayIntent,
    PublishDiscoverySupplyIntent,
    RevokeDiscoveryPublicationIntent,
    SetRecoveryIntakeIntent,
    ShowAtRiskReservationsIntent,
    ValidatedCopilotIntent,
)
from request_engine.modules.operational_copilot.errors import CopilotPolicyRejected

_MAX_FINGERPRINT_LENGTH = 512
_ALLOWED_VISIBILITY = frozenset({"hidden", "public"})


def validate_copilot_intent(
    context: CopilotContext,
    intent: CopilotIntent,
) -> ValidatedCopilotIntent:
    if not context.idempotency_key.strip():
        raise CopilotPolicyRejected("idempotency key is required")
    return _validate(intent, context)


@singledispatch
def _validate(intent: CopilotIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    raise CopilotPolicyRejected("intent type is not supported")


@_validate.register
def _(intent: CreateRecoveryProposalIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    if not 1 <= intent.search_days <= 30:
        raise CopilotPolicyRejected("search days must be between 1 and 30")
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: ExecuteRecoveryIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    if intent.expected_source_fingerprint is None or intent.expected_proposal_fingerprint is None:
        raise CopilotPolicyRejected("source and proposal fingerprints are required")
    _require_fingerprint("source", intent.expected_source_fingerprint)
    _require_fingerprint("proposal", intent.expected_proposal_fingerprint)
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: SetRecoveryIntakeIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    _require_revisions(intent.expected_source_revision, intent.expected_intake_revision)
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: ExtendRecoveryDayIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    _require_authority(context)
    _require_revisions(
        intent.expected_source_revision,
        intent.expected_location_operational_revision,
        intent.expected_resource_availability_revision,
    )
    _require_interval(intent.start_at, intent.end_at)
    if not intent.reason.strip():
        raise CopilotPolicyRejected("extend-day reason is required")
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: PublishDiscoverySupplyIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    _require_authority(context)
    visibility = intent.provider_visibility.casefold()
    if visibility not in _ALLOWED_VISIBILITY:
        raise CopilotPolicyRejected("provider visibility must be hidden or public")
    if visibility == "public" and intent.resource_id is None:
        raise CopilotPolicyRejected("public provider visibility requires a resource")
    if intent.effective_end is not None:
        _require_interval(intent.effective_start, intent.effective_end)
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: RevokeDiscoveryPublicationIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    _require_authority(context)
    _require_revisions(intent.expected_revision)
    return ValidatedCopilotIntent(intent)


@_validate.register
def _(intent: ShowAtRiskReservationsIntent, context: CopilotContext) -> ValidatedCopilotIntent:
    return ValidatedCopilotIntent(intent)


def _require_authority(context: CopilotContext) -> None:
    if context.authority_party_id is None:
        raise CopilotPolicyRejected("authority party is required for this intent")


def _require_interval(start_at: datetime, end_at: datetime) -> None:
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise CopilotPolicyRejected("datetimes must be timezone-aware")
    if end_at <= start_at:
        raise CopilotPolicyRejected("end must be after start")


def _require_revisions(*revisions: int) -> None:
    if any(revision < 0 for revision in revisions):
        raise CopilotPolicyRejected("revisions must not be negative")


def _require_fingerprint(name: str, value: str) -> None:
    if not value or len(value) > _MAX_FINGERPRINT_LENGTH:
        raise CopilotPolicyRejected(
            f"{name} fingerprint must contain 1-{_MAX_FINGERPRINT_LENGTH} characters"
        )
