from __future__ import annotations

import threading
from dataclasses import dataclass


_METRIC_NAMES = (
    "provider_test_failures_total",
    "rotation_failures_total",
    "config_propagation_lag_seconds",
    "secret_backend_failures_total",
    "last_successful_backup_age_seconds",
    "restore_drill_age_seconds",
    "readiness_transition_total",
)


@dataclass(frozen=True, slots=True)
class P7MetricSnapshot:
    provider_test_failures_total: int
    rotation_failures_total: int
    config_propagation_lag_seconds: float
    secret_backend_failures_total: int
    last_successful_backup_age_seconds: float
    restore_drill_age_seconds: float
    readiness_transition_total: int


@dataclass(frozen=True, slots=True)
class P7AlertThresholds:
    max_config_propagation_lag_seconds: float = 60.0
    max_backup_age_seconds: float = 90_000.0
    max_restore_drill_age_seconds: float = 2_678_400.0

    def __post_init__(self) -> None:
        if self.max_config_propagation_lag_seconds < 0:
            raise ValueError("max_config_propagation_lag_seconds must be non-negative")
        if self.max_backup_age_seconds < 0:
            raise ValueError("max_backup_age_seconds must be non-negative")
        if self.max_restore_drill_age_seconds < 0:
            raise ValueError("max_restore_drill_age_seconds must be non-negative")


@dataclass(frozen=True, slots=True)
class P7Alert:
    code: str
    metric: str
    observed: float
    threshold: float


class P7OperationalMetrics:
    """Process-local P7 metrics with a stable, secret-free snapshot contract.

    The collector intentionally stores only counts, durations, and ages. Provider
    credentials, secret identifiers, destinations, and configuration payloads are
    never accepted by this API, which makes the snapshot safe to bridge into the
    deployment's metrics exporter.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._provider_test_failures_total = 0
        self._rotation_failures_total = 0
        self._config_propagation_lag_seconds = 0.0
        self._secret_backend_failures_total = 0
        self._last_successful_backup_age_seconds = 0.0
        self._restore_drill_age_seconds = 0.0
        self._readiness_transition_total = 0

    @property
    def metric_names(self) -> tuple[str, ...]:
        return _METRIC_NAMES

    def record_provider_test_failure(self) -> None:
        with self._lock:
            self._provider_test_failures_total += 1

    def record_rotation_failure(self) -> None:
        with self._lock:
            self._rotation_failures_total += 1

    def observe_config_propagation_lag(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        with self._lock:
            self._config_propagation_lag_seconds = seconds

    def record_secret_backend_failure(self) -> None:
        with self._lock:
            self._secret_backend_failures_total += 1

    def observe_last_successful_backup_age(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        with self._lock:
            self._last_successful_backup_age_seconds = seconds

    def observe_restore_drill_age(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        with self._lock:
            self._restore_drill_age_seconds = seconds

    def record_readiness_transition(self) -> None:
        with self._lock:
            self._readiness_transition_total += 1

    def snapshot(self) -> P7MetricSnapshot:
        with self._lock:
            return P7MetricSnapshot(
                provider_test_failures_total=self._provider_test_failures_total,
                rotation_failures_total=self._rotation_failures_total,
                config_propagation_lag_seconds=self._config_propagation_lag_seconds,
                secret_backend_failures_total=self._secret_backend_failures_total,
                last_successful_backup_age_seconds=self._last_successful_backup_age_seconds,
                restore_drill_age_seconds=self._restore_drill_age_seconds,
                readiness_transition_total=self._readiness_transition_total,
            )

    def alerts(self, thresholds: P7AlertThresholds | None = None) -> tuple[P7Alert, ...]:
        limits = thresholds or P7AlertThresholds()
        snapshot = self.snapshot()
        alerts: list[P7Alert] = []
        self._append_threshold_alert(
            alerts,
            code="configuration_propagation_stale",
            metric="config_propagation_lag_seconds",
            observed=snapshot.config_propagation_lag_seconds,
            threshold=limits.max_config_propagation_lag_seconds,
        )
        self._append_threshold_alert(
            alerts,
            code="backup_stale",
            metric="last_successful_backup_age_seconds",
            observed=snapshot.last_successful_backup_age_seconds,
            threshold=limits.max_backup_age_seconds,
        )
        self._append_threshold_alert(
            alerts,
            code="restore_drill_stale",
            metric="restore_drill_age_seconds",
            observed=snapshot.restore_drill_age_seconds,
            threshold=limits.max_restore_drill_age_seconds,
        )
        return tuple(alerts)

    @staticmethod
    def _append_threshold_alert(
        alerts: list[P7Alert],
        *,
        code: str,
        metric: str,
        observed: float,
        threshold: float,
    ) -> None:
        if observed > threshold:
            alerts.append(
                P7Alert(
                    code=code,
                    metric=metric,
                    observed=observed,
                    threshold=threshold,
                )
            )

    @staticmethod
    def _require_non_negative(seconds: float) -> None:
        if seconds < 0:
            raise ValueError("metric observations must be non-negative")
