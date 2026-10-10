from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY_DIR = REPO_ROOT / "deploy" / "observability"
MODULES_DIR = REPO_ROOT / "src" / "request_engine" / "modules"

EXPECTED_REQUIREMENTS = {
    "opentelemetry-distro==0.65b0",
    "opentelemetry-sdk==1.44.0",
    "opentelemetry-api==1.44.0",
    "opentelemetry-exporter-otlp-proto-http==1.44.0",
    "opentelemetry-instrumentation-fastapi==0.65b0",
    "opentelemetry-instrumentation-sqlalchemy==0.65b0",
    "opentelemetry-instrumentation-logging==0.65b0",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_observability_runtime_versions_are_pinned() -> None:
    lines = {
        line.strip()
        for line in _read(OBSERVABILITY_DIR / "requirements.txt").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert lines == EXPECTED_REQUIREMENTS


def test_collector_configs_keep_required_otlp_safety_components() -> None:
    local = _read(OBSERVABILITY_DIR / "otel-collector.local.yaml")
    production = _read(OBSERVABILITY_DIR / "otel-collector.production.yaml")

    for config in (local, production):
        assert "otlp:" in config
        assert "0.0.0.0:4317" in config
        assert "0.0.0.0:4318" in config
        assert "memory_limiter:" in config
        assert "batch:" in config
        assert "health_check:" in config
        assert "traces:" in config
        assert "metrics:" in config
        assert "translation_strategy: UnderscoreEscapingWithSuffixes" in config
        assert "resource_to_telemetry_conversion:" in config

    assert "debug:" in local
    assert "      exporters: [debug, prometheus]" in local
    assert "otlphttp/backend:" in production
    assert "${env:REQUEST_ENGINE_OTEL_BACKEND_ENDPOINT}" in production
    assert "${env:REQUEST_ENGINE_OTEL_BACKEND_AUTHORIZATION}" in production
    assert "insecure: true" not in production.lower()
    assert 'endpoint: "0.0.0.0:9464"' in production


def test_operator_alert_stack_has_private_scrape_and_missing_signal_coverage() -> None:
    compose = _read(OBSERVABILITY_DIR / "compose.otel.yaml")
    prometheus = _read(OBSERVABILITY_DIR / "prometheus.yaml")
    rules = _read(OBSERVABILITY_DIR / "alert-rules.yaml")
    receiver = _read(OBSERVABILITY_DIR / "alertmanager.yaml")
    assert '"127.0.0.1:9090:9090"' in compose
    assert '"127.0.0.1:9093:9093"' in compose
    assert 'targets: ["otel-collector:9464"]' in prometheus
    for signal in (
        "worker_cycles_total",
        "scheduled_action_backlog",
        "outbox_backlog",
        "provider_event_backlog",
        "communication_ambiguous_10m",
        "backup_evidence_verified",
        "restore_drill_verified",
        "backup_evidence_age_seconds",
        "restore_drill_evidence_age_seconds",
    ):
        assert signal in rules
    for worker in ("scheduled_action", "outbox", "provider_event"):
        assert f'worker="{worker}"' in rules
    assert "WorkerProgressStalled" in rules
    assert "and on()" in rules
    assert 'outcome=~"completed|dead|rejected"' in rules
    assert "replace-with-operator-receiver.invalid" in receiver
    assert "send_resolved: true" in receiver


def test_collector_image_is_release_pinned_and_loopback_bound_locally() -> None:
    compose = _read(OBSERVABILITY_DIR / "compose.otel.yaml")
    assert "opentelemetry-collector-contrib:0.157.0" in compose
    assert "quay.io/prometheus/prometheus:v3.8.1" in compose
    assert "quay.io/prometheus/alertmanager:v0.31.1" in compose
    assert '"127.0.0.1:4317:4317"' in compose
    assert '"127.0.0.1:4318:4318"' in compose
    assert '"127.0.0.1:13133:13133"' in compose
    assert "no-new-privileges:true" in compose


def test_reference_image_can_install_observability_at_immutable_build_time() -> None:
    dockerfile = _read(REPO_ROOT / "deploy" / "reference" / "Dockerfile")
    dockerignore = _read(REPO_ROOT / ".dockerignore")
    assert "ARG REQUEST_ENGINE_ENABLE_OBSERVABILITY=0" in dockerfile
    assert "REQUEST_ENGINE_ENABLE_OBSERVABILITY" in dockerfile
    assert "COPY deploy/observability/requirements.txt" in dockerfile
    assert "scripts/observability/run_with_otel.py" in dockerfile
    assert "scripts/observability/operator_metrics_collector.py" in dockerfile
    assert "!deploy/observability/requirements.txt" in dockerignore
    assert "!scripts/observability/**" in dockerignore


def test_zero_code_launcher_has_safe_release_defaults() -> None:
    launcher = _read(REPO_ROOT / "scripts" / "observability" / "run_with_otel.py")
    required_fragments = (
        '"OTEL_TRACES_EXPORTER": "otlp"',
        '"OTEL_METRICS_EXPORTER": "otlp"',
        '"OTEL_LOGS_EXPORTER": "none"',
        '"OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf"',
        '"OTEL_PROPAGATORS": "tracecontext,baggage"',
        '"OTEL_TRACES_SAMPLER": "parentbased_traceidratio"',
        '"OTEL_PYTHON_LOG_CORRELATION": "true"',
        '"OTEL_PYTHON_LOG_AUTO_INSTRUMENTATION": "false"',
        'env["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(',
        'resource_attributes.setdefault("service.version", args.service_version)',
        'resource_attributes.setdefault("deployment.environment.name", deployment_environment)',
        "os.execvpe(executable, [executable, *command]",
    )
    for fragment in required_fragments:
        assert fragment in launcher

    assert "OTEL_SERVICE_VERSION" not in launcher
    assert "shell=True" not in launcher


def test_business_modules_do_not_depend_on_opentelemetry_sdk() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in MODULES_DIR.rglob("*.py")
        if "opentelemetry" in _read(path).lower()
    ]
    assert offenders == []


def test_example_environment_exposes_local_otel_defaults() -> None:
    env_example = _read(REPO_ROOT / ".env.example")
    required = (
        "OTEL_SERVICE_NAME=request-engine-api",
        "OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=development,service.version=0.1.0",
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318",
        "OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf",
        "OTEL_TRACES_EXPORTER=otlp",
        "OTEL_METRICS_EXPORTER=otlp",
        "OTEL_LOGS_EXPORTER=none",
        "OTEL_PROPAGATORS=tracecontext,baggage",
        "OTEL_PYTHON_LOG_CORRELATION=true",
    )
    for setting in required:
        assert setting in env_example
