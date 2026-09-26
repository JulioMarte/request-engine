from __future__ import annotations

import pytest

from request_engine.platform.observability.p7_metrics import (
    P7AlertThresholds,
    P7OperationalMetrics,
)


@pytest.mark.unit
def test_p7_metrics_expose_the_required_secret_free_operational_signals() -> None:
    metrics = P7OperationalMetrics()

    metrics.record_provider_test_failure()
    metrics.record_rotation_failure()
    metrics.observe_config_propagation_lag(12.5)
    metrics.record_secret_backend_failure()
    metrics.observe_last_successful_backup_age(3600.0)
    metrics.observe_restore_drill_age(86_400.0)
    metrics.record_readiness_transition()
    metrics.record_readiness_transition()

    snapshot = metrics.snapshot()

    assert snapshot.provider_test_failures_total == 1
    assert snapshot.rotation_failures_total == 1
    assert snapshot.config_propagation_lag_seconds == 12.5
    assert snapshot.secret_backend_failures_total == 1
    assert snapshot.last_successful_backup_age_seconds == 3600.0
    assert snapshot.restore_drill_age_seconds == 86_400.0
    assert snapshot.readiness_transition_total == 2
    assert set(metrics.metric_names) == {
        "provider_test_failures_total",
        "rotation_failures_total",
        "config_propagation_lag_seconds",
        "secret_backend_failures_total",
        "last_successful_backup_age_seconds",
        "restore_drill_age_seconds",
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
