from __future__ import annotations

import importlib.util
from collections.abc import Callable
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
    distribution = cast(
        Callable[[list[int]], dict[str, int | None]],
        metrics.distribution,
    )
    assert distribution(list(range(1, 101))) == {
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
    classify = cast(Callable[[Path], str | None], metrics.classify_path)
    assert (
        classify(Path("src/request_engine/modules/booking/domain/policy.py")) == "production_domain"
    )
    assert classify(Path("src/request_engine/bootstrap/runtime.py")) == "production_composition"
    assert classify(Path("src/request_engine/entrypoints/http/app.py")) == "production_composition"
    assert classify(Path("tests/unit/test_policy.py")) == "tests"
    assert classify(Path("scripts/ci/probe.py")) == "scripts"
    assert classify(Path("migrations/versions/0002_probe.py")) == "migrations"
    assert classify(Path("pyproject.toml")) == "config"
    assert classify(Path(".github/workflows/ci.yml")) == "config"


def test_business_module_path_excludes_modules_package_root() -> None:
    metrics = _load_metrics()
    module_for_path = cast(
        Callable[[Path], str | None],
        metrics.business_module_for_path,
    )
    assert module_for_path(Path("src/request_engine/modules/__init__.py")) is None
    assert module_for_path(Path("src/request_engine/modules/booking/__init__.py")) == "booking"
    assert module_for_path(Path("src/request_engine/modules/booking/domain/policy.py")) == "booking"


def test_generated_detection_requires_controlled_path_or_filename() -> None:
    metrics = _load_metrics()
    generated_reason = cast(
        Callable[[Path, str | None], str | None],
        metrics.generated_reason,
    )
    generated_path_reason = generated_reason(Path("src/generated/client.py"), "value = 1\n")
    assert generated_path_reason == "generated-path:generated"
    assert generated_reason(Path("src/client_generated.py"), "value = 1\n") == "generated-filename"
    assert generated_reason(Path("src/client.py"), "# @generated\nvalue = 1\n") is None
    assert generated_reason(Path("src/client.py"), "# DO NOT EDIT\nvalue = 1\n") is None
    assert (
        generated_reason(
            Path("migrations/versions/0002_probe.py"),
            "# generated during migration authoring, review before commit\nvalue = 1\n",
        )
        is None
    )


def test_navigation_observation_identifies_only_obvious_forwarding_shape() -> None:
    metrics = _load_metrics()
    observe = cast(
        Callable[[Path, str], dict[str, object]],
        metrics.navigation_observation,
    )
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


def test_module_import_edges_measure_real_cross_module_dependencies() -> None:
    metrics = _load_metrics()
    edges = cast(
        Callable[[Path, str], set[tuple[str, str]]],
        metrics.module_import_edges_from_source,
    )
    path = Path("src/request_engine/modules/booking/application/use_case.py")
    source = "\n".join(
        [
            "from request_engine.modules.queue.contracts import QueueRead",
            "from request_engine.modules import catalog",
            "from ..contracts import ReservationView",
            "from .ports import BookingStore",
            "",
        ]
    )
    assert edges(path, source) == {
        ("booking", "catalog"),
        ("booking", "queue"),
    }


def test_relative_cross_module_import_is_resolved_semantically() -> None:
    metrics = _load_metrics()
    edges = cast(
        Callable[[Path, str], set[tuple[str, str]]],
        metrics.module_import_edges_from_source,
    )
    path = Path("src/request_engine/modules/booking/application/use_case.py")
    source = "from ...queue.contracts import QueueRead\n"
    assert edges(path, source) == {("booking", "queue")}


def test_contract_usage_measures_depth_without_changing_edge_count() -> None:
    metrics = _load_metrics()
    usage = cast(
        Callable[[Path, str], dict[tuple[str, str], set[str]]],
        metrics.module_contract_usage_from_source,
    )
    path = Path("src/request_engine/modules/operational_recovery/application/use_case.py")
    booking_import = (
        "from request_engine.modules.booking.contracts import BookingRead, RescheduleReservation"
    )
    source = "\n".join(
        [
            booking_import,
            "from ...live_capacity.contracts.projection import CapacityCheckpoint",
            "from .ports import RecoveryStore",
            "",
        ]
    )
    assert usage(path, source) == {
        ("operational_recovery", "booking"): {"BookingRead", "RescheduleReservation"},
        ("operational_recovery", "live_capacity"): {"projection.CapacityCheckpoint"},
    }


def test_suppression_observation_counts_comments_without_semantic_verdict() -> None:
    metrics = _load_metrics()
    observe = cast(Callable[[str], dict[str, object]], metrics.suppression_observation)
    result = observe(
        "\n".join(
            [
                "value = call()  # noqa: E501",
                "typed = other()  # type: ignore[assignment]",
                "secure = risky()  # nosec B101",
                "branch = 1  # pragma: no cover",
                "text = '# noqa is data, not a comment suppression'",
                "",
            ]
        )
    )
    assert result["total"] == 4
    assert result["counts"] == {
        "noqa": 1,
        "nosec": 1,
        "pragma_no_cover": 1,
        "type_ignore": 1,
    }
    assert result["interpretation"] == "none"


def test_ruff_complexity_parser_preserves_measurement_without_interpretation() -> None:
    metrics = _load_metrics()
    parse = cast(
        Callable[[Any], list[dict[str, object]]],
        metrics.parse_ruff_complexity_payload,
    )
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
