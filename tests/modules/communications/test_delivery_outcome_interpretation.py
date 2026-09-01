from __future__ import annotations

import pytest

from request_engine.modules.communications.adapters.worker.delivery_outcome_interpretation import (
    DeliveryOutcomeReport,
    MalformedDeliveryOutcomeReport,
    interpret_delivery_outcome,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)

pytestmark = [pytest.mark.unit]


def test_delivered_report_maps_onto_fenced_finalize_input() -> None:
    report = interpret_delivery_outcome(
        {
            "dedupe_key": "communication:task-1:attempt:2",
            "status": "delivered",
            "provider_message_id": "msg-7",
            "result_data": {"http_status": 200},
        }
    )

    assert report == DeliveryOutcomeReport(
        provider_idempotency_key="communication:task-1:attempt:2",
        result=ProviderDeliveryResult(
            status=ProviderDeliveryStatus.DELIVERED,
            provider_message_id="msg-7",
            retryable=False,
            result_data={"http_status": 200},
        ),
    )


def test_failed_report_carries_reported_retryable_flag() -> None:
    report = interpret_delivery_outcome({"dedupe_key": "k", "status": "failed", "retryable": True})

    assert report.result.status is ProviderDeliveryStatus.FAILED
    assert report.result.retryable is True


def test_accepted_report_defaults_to_non_retryable_without_message_id() -> None:
    report = interpret_delivery_outcome({"dedupe_key": "k", "status": "accepted"})

    assert report.result.status is ProviderDeliveryStatus.ACCEPTED
    assert report.result.retryable is False
    assert report.result.provider_message_id is None


def test_report_identity_is_only_the_echoed_idempotency_key() -> None:
    report = interpret_delivery_outcome(
        {
            "dedupe_key": "k",
            "status": "delivered",
            "delivery_id": "forged-delivery-id",
            "provider_key": "forged-provider",
            "organization_id": "forged-tenant",
        }
    )

    assert report.provider_idempotency_key == "k"
    assert report.result.status is ProviderDeliveryStatus.DELIVERED


@pytest.mark.parametrize(
    ("payload", "error_class"),
    [
        ("not-an-object", "delivery_outcome_report_not_object"),
        ({"status": "delivered"}, "delivery_outcome_report_missing_identity"),
        ({"dedupe_key": "  ", "status": "delivered"}, "delivery_outcome_report_missing_identity"),
        ({"dedupe_key": 7, "status": "delivered"}, "delivery_outcome_report_missing_identity"),
        ({"dedupe_key": "k"}, "delivery_outcome_report_unknown_status"),
        ({"dedupe_key": "k", "status": "unknown"}, "delivery_outcome_report_unknown_status"),
        ({"dedupe_key": "k", "status": "not_found"}, "delivery_outcome_report_unknown_status"),
        ({"dedupe_key": "k", "status": 3}, "delivery_outcome_report_unknown_status"),
        (
            {"dedupe_key": "k", "status": "failed", "retryable": "yes"},
            "delivery_outcome_report_invalid_retryable",
        ),
        (
            {"dedupe_key": "k", "status": "delivered", "provider_message_id": 9},
            "delivery_outcome_report_invalid_message_id",
        ),
        (
            {"dedupe_key": "k", "status": "delivered", "result_data": [1]},
            "delivery_outcome_report_invalid_result_data",
        ),
    ],
)
def test_malformed_report_is_a_typed_interpretation_failure(
    payload: object,
    error_class: str,
) -> None:
    with pytest.raises(MalformedDeliveryOutcomeReport) as exc_info:
        interpret_delivery_outcome(payload)

    assert exc_info.value.error_class == error_class
