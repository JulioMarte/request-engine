from __future__ import annotations

from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import cast

ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(name: str, relative_path: str) -> ModuleType:
    spec = spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {relative_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


required_needs = _load_script_module(
    "current_required_needs_under_test", "scripts/ci/require_successful_needs.py"
)
validate_required_needs = cast(
    Callable[[object], list[str]], required_needs.validate_required_needs
)


def test_required_ci_gate_rejects_failed_skipped_and_missing_dependencies() -> None:
    assert validate_required_needs({}) == ["required dependency results are missing or empty"]
    assert validate_required_needs(
        {
            "python-quality": {"result": "success"},
            "observability-contract": {"result": "failure"},
            "postgres-production-head": {"result": "skipped"},
        }
    ) == [
        "observability-contract: expected success, received 'failure'",
        "postgres-production-head: expected success, received 'skipped'",
    ]


def test_required_ci_gate_accepts_only_successful_current_dependencies() -> None:
    assert (
        validate_required_needs(
            {
                "python-quality": {"result": "success"},
                "observability-contract": {"result": "success"},
                "postgres-production-head": {"result": "success"},
            }
        )
        == []
    )


def test_required_aggregate_remains_fail_closed_for_all_current_prerequisites() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    candidate_job = workflow.split("  postgres-v3-candidate:\n", 1)[1]

    # The job name is temporarily retained because the active development ruleset
    # requires this exact status-check context. Its semantics are now a current
    # Request Engine aggregate, not a frozen-V3 compatibility proof.
    assert "name: PostgreSQL 18 V3 candidate and verticals" in candidate_job
    for dependency in (
        "python-quality",
        "observability-contract",
        "postgres-production-head",
    ):
        assert f"- {dependency}" in candidate_job
    for retired_dependency in (
        "postgres-v3-bootstrap-proof",
        "postgres-v3-candidate-proof",
    ):
        assert f"- {retired_dependency}" not in candidate_job
    assert "if: ${{ always() }}" in candidate_job
    assert "REQUIRED_NEEDS_JSON: ${{ toJSON(needs) }}" in candidate_job
    assert "python scripts/ci/require_successful_needs.py" in candidate_job
