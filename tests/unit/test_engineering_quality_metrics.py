from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "scripts" / "ci" / "quality_metrics.py"


def _load_metrics() -> ModuleType:
    spec = importlib.util.spec_from_file_location("quality_metrics_under_test", METRICS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nearest_rank_distribution_is_deterministic() -> None:
    metrics = _load_metrics()
    distribution = cast(Any, metrics.distribution)(list(range(1, 101)))
    assert distribution == {
        "count": 100,
        "min": 1,
        "p50": 50,
        "p75": 75,
        "p90": 90,
        "p95": 95,
        "p99": 99,
        "max": 100,
    }


def test_code_categories_cover_production_tests_scripts_migrations_and_config() -> None:
    metrics = _load_metrics()
    classify = cast(Any, metrics.classify_path)
    assert (
        classify(Path("src/request_engine/modules/booking/domain/policy.py")) == "production_domain"
    )
    assert classify(Path("src/request_engine/bootstrap/runtime.py")) == "production_composition"
    assert classify(Path("tests/unit/test_policy.py")) == "tests"
    assert classify(Path("scripts/ci/probe.py")) == "scripts"
    assert classify(Path("migrations/versions/0002_probe.py")) == "migrations"
    assert classify(Path("pyproject.toml")) == "config"
    assert classify(Path(".github/workflows/ci.yml")) == "config"


def test_generated_detection_is_explicit_and_does_not_treat_migration_header_as_generated() -> None:
    metrics = _load_metrics()
    generated_reason = cast(Any, metrics.generated_reason)
    generated_path_reason = generated_reason(Path("src/generated/client.py"), "value = 1\n")
    assert generated_path_reason == "generated-path:generated"
    assert generated_reason(Path("src/client.py"), "# @generated\nvalue = 1\n") is not None
    assert (
        generated_reason(
            Path("migrations/versions/0002_probe.py"),
            "# generated during migration authoring, review before commit\nvalue = 1\n",
        )
        is None
    )


def test_navigation_observation_identifies_only_obvious_forwarding_shape() -> None:
    metrics = _load_metrics()
    observe = cast(Any, metrics.navigation_observation)
    wrapper = observe(
        Path("src/request_engine/modules/booking/application/wrapper.py"),
        "from .owner import run\n\ndef execute(value: int) -> int:\n    return run(value)\n",
    )
    substantive = observe(
        Path("src/request_engine/modules/booking/application/policy.py"),
        "def decide(value: int) -> int:\n    if value > 0:\n        return value\n    return 0\n",
    )
    assert wrapper["one_call_forwarder_count"] == 1
    assert wrapper["forwarding_only_functions"] is True
    assert substantive["forwarding_only_functions"] is False


def test_ruff_complexity_parser_preserves_measurement_without_interpretation() -> None:
    metrics = _load_metrics()
    parse = cast(Any, metrics.parse_ruff_complexity_payload)
    records = parse(
        [
            {
                "code": "C901",
                "filename": "src/example.py",
                "message": "`decide` is too complex (17 > 0)",
                "location": {"row": 9, "column": 1},
            }
        ]
    )
    assert records == [
        {
            "path": "src/example.py",
            "subject": "decide",
            "line": 9,
            "mccabe": 17,
        }
    ]
