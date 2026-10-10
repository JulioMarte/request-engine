from request_engine.platform.observability.worker_telemetry import OpenTelemetryWorkerMetrics


class Instrument:
    def __init__(self) -> None:
        self.values: list[tuple[object, dict[str, str]]] = []

    def add(self, value: object, attributes: dict[str, str]) -> None:
        self.values.append((value, attributes))

    def record(self, value: object, attributes: dict[str, str]) -> None:
        self.values.append((value, attributes))


class Meter:
    def __init__(self) -> None:
        self.instruments: dict[str, Instrument] = {}

    def create_counter(self, name: str, **_: object) -> Instrument:
        instrument = Instrument()
        self.instruments[name] = instrument
        return instrument

    def create_histogram(self, name: str, **_: object) -> Instrument:
        instrument = Instrument()
        self.instruments[name] = instrument
        return instrument


def test_worker_metrics_use_only_bounded_dimensions_and_hide_failure_details() -> None:
    meter = Meter()
    metrics = OpenTelemetryWorkerMetrics("outbox", meter)

    metrics.claimed(3)
    metrics.outcome("retry", "provider timeout for private@example.test")
    metrics.outcome("stale", "lease token 123")
    metrics.processing_seconds(0.5)

    assert meter.instruments["worker.claims"].values == [(3, {"worker": "outbox"})]
    assert meter.instruments["worker.outcomes"].values == [
        (1, {"worker": "outbox", "outcome": "retry"}),
        (1, {"worker": "outbox", "outcome": "stale"}),
    ]
    assert meter.instruments["worker.lease_lost"].values == [(1, {"worker": "outbox"})]
    assert meter.instruments["worker.processing.duration"].values == [(0.5, {"worker": "outbox"})]
