from __future__ import annotations

import math

import pytest

from request_engine.platform.observability.p7_metrics import (
    P7AlertThresholds,
    P7OperationalMetrics,
)


@pytest.mark.unit
def test_p7_metrics_expose_the_required_secret_free_operational_signals() -> None:
    metrics = P7OperationalMetrics()

    metrics.observe_active_revision("email.delivery", 4)
    metrics.record_validation("success")
    metrics.record_validation("failure")
    metrics.record_validation("unavailable")
    metrics.record_activation("communications.webhook", 2)
    metrics.record_disable("communications.webhook")
    metrics.record_provider_test_failure()
    metrics.record_rotation_failure()
    metrics.observe_config_propagation_lag(12.5)
    metrics.record_cache_invalidation()
    metrics.record_revision_poll_correction()
    metrics.record_secret_backend_failure()
    metrics.observe_provider_configuration_source("managed")
    metrics.record_worker_configuration_failure()
    metrics.record_worker_secret_store_failure()
    metrics.observe_last_successful_backup_age(3600.0)
    metrics.observe_restore_drill_age(86_400.0)
    metrics.observe_restore_drill_evidence_reference("drill-2026-09-26.json")
    metrics.observe_clone_fence("fenced")
    metrics.record_readiness_transition()
    metrics.record_readiness_transition()

    snapshot = metrics.snapshot()

    assert snapshot.active_revisions == (("email.delivery", 4),)
    assert snapshot.validation_success_total == 1
    assert snapshot.validation_failure_total == 1
    assert snapshot.validation_unavailable_total == 1
    assert snapshot.activation_total == 1
    assert snapshot.disable_total == 1
    assert snapshot.provider_test_failures_total == 1
    assert snapshot.rotation_failures_total == 1
    assert snapshot.config_propagation_lag_seconds == 12.5
    assert snapshot.cache_invalidations_total == 1
    assert snapshot.revision_poll_corrections_total == 1
    assert snapshot.secret_backend_failures_total == 1
    assert snapshot.provider_configuration_source == "managed"
    assert snapshot.worker_configuration_failures_total == 1
    assert snapshot.worker_secret_store_failures_total == 1
    assert snapshot.last_successful_backup_age_seconds == pytest.approx(3600.0, abs=0.1)
    assert snapshot.restore_drill_age_seconds == pytest.approx(86_400.0, abs=0.1)
    assert snapshot.restore_drill_evidence_reference == "drill-2026-09-26.json"
    assert snapshot.clone_fence_state == "fenced"
    assert snapshot.readiness_transition_total == 2
    assert set(metrics.metric_names) == {
        "active_revision",
        "validation_success_total",
        "validation_failure_total",
        "validation_unavailable_total",
        "activation_total",
        "disable_total",
        "provider_test_failures_total",
        "rotation_failures_total",
        "config_propagation_lag_seconds",
        "cache_invalidations_total",
        "revision_poll_corrections_total",
        "secret_backend_failures_total",
        "provider_configuration_source",
        "worker_configuration_failures_total",
        "worker_secret_store_failures_total",
        "last_successful_backup_age_seconds",
        "restore_drill_age_seconds",
        "restore_drill_evidence_reference",
        "clone_fence_state",
        "readiness_transition_total",
    }


@pytest.mark.unit
def test_p7_metrics_raise_actionable_alerts_for_stale_operational_state() -> None:
    metrics = P7OperationalMetrics()
    metrics.observe_config_propagation_lag(61.0)
    metrics.observe_last_successful_backup_age(101.0)
    metrics.observe_restore_drill_age(201.0)

    alerts = metrics.alerts(
        P7AlertThresholds(
            max_config_propagation_lag_seconds=60.0,
            max_backup_age_seconds=100.0,
            max_restore_drill_age_seconds=200.0,
        )
    )

    assert tuple(alert.code for alert in alerts) == (
        "configuration_propagation_stale",
        "backup_stale",
        "restore_drill_stale",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "method_name",
    (
        "observe_config_propagation_lag",
        "observe_last_successful_backup_age",
        "observe_restore_drill_age",
    ),
)
def test_p7_metrics_reject_negative_durations(method_name: str) -> None:
    metrics = P7OperationalMetrics()

    with pytest.raises(ValueError, match="non-negative"):
        getattr(metrics, method_name)(-0.1)


@pytest.mark.unit
def test_backup_and_restore_ages_keep_advancing(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = iter((100.0, 200.0, 160.0, 260.0))
    monkeypatch.setattr(
        "request_engine.platform.observability.p7_metrics.time.monotonic",
        lambda: next(clock),
    )
    metrics = P7OperationalMetrics()
    metrics.observe_last_successful_backup_age(30.0)
    metrics.observe_restore_drill_age(40.0)

    snapshot = metrics.snapshot()

    assert snapshot.last_successful_backup_age_seconds == 90.0
    assert snapshot.restore_drill_age_seconds == 100.0


@pytest.mark.unit
@pytest.mark.adversarial
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, 10**1000, -1.0])
@pytest.mark.parametrize(
    "field",
    [
        "max_config_propagation_lag_seconds",
        "max_backup_age_seconds",
        "max_restore_drill_age_seconds",
    ],
)
def test_alert_thresholds_reject_values_that_can_hide_staleness(field: str, value: float) -> None:
    with pytest.raises(ValueError, match="finite.*non-negative"):
        P7AlertThresholds(**{field: value})


@pytest.mark.unit
@pytest.mark.adversarial
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, 10**1000, -1.0])
@pytest.mark.parametrize(
    "method,field",
    [
        ("observe_config_propagation_lag", "config_propagation_lag_seconds"),
        ("observe_last_successful_backup_age", "last_successful_backup_age_seconds"),
        ("observe_restore_drill_age", "restore_drill_age_seconds"),
    ],
)
def test_invalid_observation_preserves_previous_signal(
    method: str, field: str, value: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "request_engine.platform.observability.p7_metrics.time.monotonic", lambda: 100.0
    )
    metrics = P7OperationalMetrics()
    getattr(metrics, method)(100.0)
    with pytest.raises(ValueError, match="finite.*non-negative"):
        getattr(metrics, method)(value)
    assert getattr(metrics.snapshot(), field) == 100.0


@pytest.mark.unit
@pytest.mark.parametrize("value", [0, 0.0, 1, 1.5])
def test_valid_thresholds_preserve_zero_and_strict_boundary(value: float) -> None:
    metrics = P7OperationalMetrics()
    metrics.observe_config_propagation_lag(value)
    limits = P7AlertThresholds(max_config_propagation_lag_seconds=value)
    assert metrics.alerts(limits) == ()
    metrics.observe_config_propagation_lag(value + 1.0)
    assert tuple(alert.code for alert in metrics.alerts(limits)) == (
        "configuration_propagation_stale",
    )
