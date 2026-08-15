from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY_DIR = REPO_ROOT / "deploy" / "observability"
MODULES_DIR = REPO_ROOT / "src" / "request_engine" / "modules"

EXPECTED_REQUIREMENTS = {
    "opentelemetry-distro==0.65b0",
    "opentelemetry-sdk==1.44.0",
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

    assert "debug:" in local
    assert "otlphttp/backend:" in production
    assert "${env:REQUEST_ENGINE_OTEL_BACKEND_ENDPOINT}" in production
    assert "${env:REQUEST_ENGINE_OTEL_BACKEND_AUTHORIZATION}" in production
    assert "insecure: true" not in production.lower()


def test_collector_image_is_release_pinned_and_loopback_bound_locally() -> None:
    compose = _read(OBSERVABILITY_DIR / "compose.otel.yaml")
    assert "otel/opentelemetry-collector-contrib:0.157.0" in compose
    assert '"127.0.0.1:4317:4317"' in compose
    assert '"127.0.0.1:4318:4318"' in compose
    assert '"127.0.0.1:13133:13133"' in compose
    assert "no-new-privileges:true" in compose


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
    )
    for fragment in required_fragments:
        assert fragment in launcher

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
