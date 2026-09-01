"""Pure interpretation of persisted transport outcome reports (F7b T1 / FU-2).

A persisted provider event payload is mapped onto fenced delivery finalize
input. The report contributes only its echoed provider idempotency key and
outcome vocabulary; provider/tenant identity never comes from the payload.
"""

from dataclasses import dataclass
from typing import cast

from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)

_OUTCOME_STATUSES = {
    "accepted": ProviderDeliveryStatus.ACCEPTED,
    "delivered": ProviderDeliveryStatus.DELIVERED,
    "failed": ProviderDeliveryStatus.FAILED,
}


class MalformedDeliveryOutcomeReport(RuntimeError):
    """A persisted outcome report that is terminally uninterpretable."""

    def __init__(self, error_class: str) -> None:
        self.error_class = error_class
        super().__init__(error_class)


@dataclass(frozen=True, slots=True)
class DeliveryOutcomeReport:
    provider_idempotency_key: str
    result: ProviderDeliveryResult


def interpret_delivery_outcome(payload: object) -> DeliveryOutcomeReport:
    """Map one persisted outcome report payload onto fenced finalize input.

    Resolution authority is the (provider_key, provider_idempotency_key) pair:
    provider_key is taken from the authenticated event lease by the caller, so
    the payload may only echo its idempotency key. A client-sent delivery id is
    never trusted. Anything outside the reported outcome vocabulary is a typed
    interpretation failure, never a guessed state.
    """

    if not isinstance(payload, dict):
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_not_object")
    report = cast("dict[object, object]", payload)
    dedupe_key = report.get("dedupe_key")
    if not isinstance(dedupe_key, str) or not dedupe_key.strip():
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_missing_identity")
    raw_status = report.get("status")
    status = _OUTCOME_STATUSES.get(raw_status) if isinstance(raw_status, str) else None
    if status is None:
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_unknown_status")
    retryable = report.get("retryable", False)
    if not isinstance(retryable, bool):
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_invalid_retryable")
    message_id = report.get("provider_message_id")
    if message_id is not None and (not isinstance(message_id, str) or not message_id.strip()):
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_invalid_message_id")
    raw_result_data = report.get("result_data", {})
    if not isinstance(raw_result_data, dict):
        raise MalformedDeliveryOutcomeReport("delivery_outcome_report_invalid_result_data")
    result_data = cast("dict[str, object]", raw_result_data)
    return DeliveryOutcomeReport(
        provider_idempotency_key=dedupe_key,
        result=ProviderDeliveryResult(
            status=status,
            provider_message_id=message_id,
            retryable=retryable,
            result_data=result_data,
        ),
    )
