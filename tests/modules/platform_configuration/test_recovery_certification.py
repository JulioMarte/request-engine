from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from request_engine.modules.platform_configuration.application.recovery_certification import (
    RecoveryCertificationInvalid,
    parse_recovery_certification,
)


def _payload() -> dict[str, object]:
    return {
        "schema": "request-engine/recovery-certification/v1",
        "outcome": "accepted",
        "bundle_sha256": "a" * 64,
        "backup_completed_at": "2026-09-26T20:00:00+00:00",
        "service_recovered_at": "2026-09-26T20:45:00+00:00",
        "observed_rpo_seconds": 1800.0,
        "observed_rto_seconds": 900.0,
        "accepted_max_rpo_seconds": 3600.0,
        "accepted_max_rto_seconds": 1800.0,
    }


def test_parse_recovery_certification_exposes_secret_free_ages() -> None:
    evidence = parse_recovery_certification(_payload(), reference="/evidence/recovery.json")
    now = datetime(2026, 9, 27, 20, 45, tzinfo=UTC)

    assert evidence.bundle_sha256 == "a" * 64
    assert evidence.backup_age_seconds(now=now) == pytest.approx(89_100.0)
    assert evidence.restore_drill_age_seconds(now=now) == pytest.approx(86_400.0)
    assert evidence.reference == "/evidence/recovery.json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outcome", "rejected"),
        ("bundle_sha256", "not-a-digest"),
        ("observed_rpo_seconds", -1),
        ("accepted_max_rto_seconds", 100.0),
    ],
)
def test_parse_recovery_certification_fails_closed(
    field: str,
    value: object,
) -> None:
    payload = _payload()
    payload[field] = value

    with pytest.raises(RecoveryCertificationInvalid):
        parse_recovery_certification(payload, reference="/evidence/recovery.json")


def test_future_certification_age_is_rejected() -> None:
    evidence = parse_recovery_certification(_payload(), reference="/evidence/recovery.json")

    with pytest.raises(RecoveryCertificationInvalid):
        evidence.restore_drill_age_seconds(now=evidence.service_recovered_at - timedelta(seconds=1))


@pytest.mark.parametrize(
    "field",
    (
        "observed_rpo_seconds",
        "observed_rto_seconds",
        "accepted_max_rpo_seconds",
        "accepted_max_rto_seconds",
    ),
)
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_readiness_rejects_non_finite_recovery_evidence(field: str, value: object) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(RecoveryCertificationInvalid, match="finite"):
        parse_recovery_certification(payload, reference="/evidence/recovery.json")


def test_measurement_without_approved_limits_remains_parseable() -> None:
    payload = _payload()
    payload["accepted_max_rpo_seconds"] = None
    payload["accepted_max_rto_seconds"] = None
    evidence = parse_recovery_certification(payload, reference="/evidence/recovery.json")
    assert evidence.observed_rpo_seconds == 1800
    assert evidence.accepted_max_rpo_seconds is None
    assert evidence.accepted_max_rto_seconds is None
