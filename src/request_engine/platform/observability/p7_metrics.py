import math
import time


def _require_finite_non_negative(value: float, name: str) -> None:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be finite and non-negative")


_METRIC_NAMES = (
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
)


class P7MetricSnapshot:
    __slots__ = (
        "active_revisions",
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
    )

    def __init__(
        self,
        *,
        active_revisions: tuple[tuple[str, int], ...],
        validation_success_total: int,
        validation_failure_total: int,
        validation_unavailable_total: int,
        activation_total: int,
        disable_total: int,
        provider_test_failures_total: int,
        rotation_failures_total: int,
        config_propagation_lag_seconds: float,
        cache_invalidations_total: int,
        revision_poll_corrections_total: int,
        secret_backend_failures_total: int,
        provider_configuration_source: str,
        worker_configuration_failures_total: int,
        worker_secret_store_failures_total: int,
        last_successful_backup_age_seconds: float,
        restore_drill_age_seconds: float,
        restore_drill_evidence_reference: str | None,
        clone_fence_state: str,
        readiness_transition_total: int,
    ) -> None:
        self.active_revisions = active_revisions
        self.validation_success_total = validation_success_total
        self.validation_failure_total = validation_failure_total
        self.validation_unavailable_total = validation_unavailable_total
        self.activation_total = activation_total
        self.disable_total = disable_total
        self.provider_test_failures_total = provider_test_failures_total
        self.rotation_failures_total = rotation_failures_total
        self.config_propagation_lag_seconds = config_propagation_lag_seconds
        self.cache_invalidations_total = cache_invalidations_total
        self.revision_poll_corrections_total = revision_poll_corrections_total
        self.secret_backend_failures_total = secret_backend_failures_total
        self.provider_configuration_source = provider_configuration_source
        self.worker_configuration_failures_total = worker_configuration_failures_total
        self.worker_secret_store_failures_total = worker_secret_store_failures_total
        self.last_successful_backup_age_seconds = last_successful_backup_age_seconds
        self.restore_drill_age_seconds = restore_drill_age_seconds
        self.restore_drill_evidence_reference = restore_drill_evidence_reference
        self.clone_fence_state = clone_fence_state
        self.readiness_transition_total = readiness_transition_total


class P7AlertThresholds:
    __slots__ = (
        "max_config_propagation_lag_seconds",
        "max_backup_age_seconds",
        "max_restore_drill_age_seconds",
    )

    def __init__(
        self,
        *,
        max_config_propagation_lag_seconds: float = 60.0,
        max_backup_age_seconds: float = 90_000.0,
        max_restore_drill_age_seconds: float = 2_678_400.0,
    ) -> None:
        _require_finite_non_negative(
            max_config_propagation_lag_seconds, "max_config_propagation_lag_seconds"
        )
        _require_finite_non_negative(max_backup_age_seconds, "max_backup_age_seconds")
        _require_finite_non_negative(max_restore_drill_age_seconds, "max_restore_drill_age_seconds")
        self.max_config_propagation_lag_seconds = max_config_propagation_lag_seconds
        self.max_backup_age_seconds = max_backup_age_seconds
        self.max_restore_drill_age_seconds = max_restore_drill_age_seconds


class P7Alert:
    __slots__ = ("code", "metric", "observed", "threshold")

    def __init__(
        self,
        *,
        code: str,
        metric: str,
        observed: float,
        threshold: float,
    ) -> None:
        self.code = code
        self.metric = metric
        self.observed = observed
        self.threshold = threshold


class P7OperationalMetrics:
    """Secret-free, process-local operational signals for P7.

    These values are advisory telemetry, not authoritative state. Mutation
    correctness remains in PostgreSQL/OpenBao, so metrics never participate in
    authorization, recovery, or reconciliation decisions.
    """

    def __init__(self) -> None:
        self._active_revisions: dict[str, int] = {}
        self._validation_success_total = 0
        self._validation_failure_total = 0
        self._validation_unavailable_total = 0
        self._activation_total = 0
        self._disable_total = 0
        self._provider_test_failures_total = 0
        self._rotation_failures_total = 0
        self._config_propagation_lag_seconds = 0.0
        self._cache_invalidations_total = 0
        self._revision_poll_corrections_total = 0
        self._secret_backend_failures_total = 0
        self._provider_configuration_source = "unknown"
        self._worker_configuration_failures_total = 0
        self._worker_secret_store_failures_total = 0
        self._last_successful_backup_age_seconds = 0.0
        self._last_successful_backup_age_observed_at: float | None = None
        self._restore_drill_age_seconds = 0.0
        self._restore_drill_age_observed_at: float | None = None
        self._restore_drill_evidence_reference: str | None = None
        self._clone_fence_state = "unknown"
        self._readiness_transition_total = 0

    @property
    def metric_names(self) -> tuple[str, ...]:
        return _METRIC_NAMES

    def record_validation(self, outcome: str) -> None:
        if outcome == "success":
            self._validation_success_total += 1
        elif outcome == "failure":
            self._validation_failure_total += 1
        elif outcome == "unavailable":
            self._validation_unavailable_total += 1
        else:
            raise ValueError("validation outcome must be success, failure, or unavailable")

    def observe_active_revision(self, configuration_kind: str, revision: int) -> None:
        if revision <= 0:
            raise ValueError("active revision must be positive")
        self._active_revisions[configuration_kind] = revision

    def record_activation(self, configuration_kind: str, revision: int) -> None:
        self.observe_active_revision(configuration_kind, revision)
        self._activation_total += 1

    def record_disable(self, configuration_kind: str) -> None:
        self._disable_total += 1
        self._active_revisions.pop(configuration_kind, None)

    def record_provider_test_failure(self) -> None:
        self._provider_test_failures_total += 1

    def record_rotation_failure(self) -> None:
        self._rotation_failures_total += 1

    def observe_config_propagation_lag(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        self._config_propagation_lag_seconds = seconds

    def record_cache_invalidation(self) -> None:
        self._cache_invalidations_total += 1

    def record_revision_poll_correction(self) -> None:
        self._revision_poll_corrections_total += 1

    def record_secret_backend_failure(self) -> None:
        self._secret_backend_failures_total += 1

    def observe_provider_configuration_source(self, source: str) -> None:
        if source not in {"bootstrap", "managed", "unconfigured", "unknown"}:
            raise ValueError("unsupported provider configuration source")
        self._provider_configuration_source = source

    def record_worker_configuration_failure(self) -> None:
        self._worker_configuration_failures_total += 1

    def record_worker_secret_store_failure(self) -> None:
        self._worker_secret_store_failures_total += 1

    def observe_last_successful_backup_age(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        self._last_successful_backup_age_seconds = seconds
        self._last_successful_backup_age_observed_at = time.monotonic()

    def observe_restore_drill_age(self, seconds: float) -> None:
        self._require_non_negative(seconds)
        self._restore_drill_age_seconds = seconds
        self._restore_drill_age_observed_at = time.monotonic()

    def observe_restore_drill_evidence_reference(self, reference: str | None) -> None:
        if reference is not None and not reference.strip():
            raise ValueError("restore drill evidence reference cannot be blank")
        self._restore_drill_evidence_reference = reference

    def observe_clone_fence(self, state: str) -> None:
        if state not in {"fenced", "open", "unknown"}:
            raise ValueError("clone fence state must be fenced, open, or unknown")
        self._clone_fence_state = state

    def record_readiness_transition(self) -> None:
        self._readiness_transition_total += 1

    def snapshot(self) -> P7MetricSnapshot:
        return P7MetricSnapshot(
            active_revisions=tuple(sorted(self._active_revisions.items())),
            validation_success_total=self._validation_success_total,
            validation_failure_total=self._validation_failure_total,
            validation_unavailable_total=self._validation_unavailable_total,
            activation_total=self._activation_total,
            disable_total=self._disable_total,
            provider_test_failures_total=self._provider_test_failures_total,
            rotation_failures_total=self._rotation_failures_total,
            config_propagation_lag_seconds=self._config_propagation_lag_seconds,
            cache_invalidations_total=self._cache_invalidations_total,
            revision_poll_corrections_total=self._revision_poll_corrections_total,
            secret_backend_failures_total=self._secret_backend_failures_total,
            provider_configuration_source=self._provider_configuration_source,
            worker_configuration_failures_total=self._worker_configuration_failures_total,
            worker_secret_store_failures_total=self._worker_secret_store_failures_total,
            last_successful_backup_age_seconds=self._current_age(
                self._last_successful_backup_age_seconds,
                self._last_successful_backup_age_observed_at,
            ),
            restore_drill_age_seconds=self._current_age(
                self._restore_drill_age_seconds,
                self._restore_drill_age_observed_at,
            ),
            restore_drill_evidence_reference=self._restore_drill_evidence_reference,
            clone_fence_state=self._clone_fence_state,
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
    def _current_age(value: float, observed_at: float | None) -> float:
        if observed_at is None:
            return value
        return value + max(0.0, time.monotonic() - observed_at)

    @staticmethod
    def _require_non_negative(seconds: float) -> None:
        _require_finite_non_negative(seconds, "metric observations")
