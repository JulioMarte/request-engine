from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "scripts" / "ci" / "finalize_quality_evidence.py"
CALIBRATION = ROOT / "scripts" / "ci" / "summarize_quality_calibration.py"
VALIDATOR = ROOT / "scripts" / "ci" / "validate_quality_evidence.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finalized_packet_distinguishes_source_head_from_tested_tree(monkeypatch: Any) -> None:
    finalizer = _load(FINALIZER, "quality_finalizer_under_test")

    def tool_version_stub(_command: list[str], _fallback: str) -> str:
        return "ruff 0.test"

    monkeypatch.setattr(finalizer, "_tool_version", tool_version_stub)
    scan: dict[str, Any] = {
        "schema_version": "quality-scan/v1",
        "base_sha": "a" * 40,
        "head_sha": "c" * 40,
        "candidates": [
            {
                "candidate_id": "QR-0123456789ab",
                "classification": "REVIEW_CANDIDATE",
                "trigger_id": "QR-CPLX-001",
                "scope": {
                    "path": "src/request_engine/modules/booking/application/service.py",
                    "category": "production_application",
                    "subject": "decide",
                    "line": 20,
                },
                "facts": [
                    {
                        "kind": "function_mccabe",
                        "subject": "decide",
                        "value": 17,
                        "tool": "ruff:C901",
                        "interpretation": "none",
                    }
                ],
                "deltas": [],
                "review_questions": ["Where is the real reasoning load?"],
            }
        ],
    }
    baseline: dict[str, Any] = {
        "schema_version": "engineering-quality-baseline/v1",
        "repository_sha": "c" * 40,
    }
    architecture_diff: dict[str, Any] = {
        "schema_version": "architecture-diff/v1",
        "provenance": {
            "base_sha": "a" * 40,
            "source_head_sha": "b" * 40,
            "tested_sha": "c" * 40,
            "test_mode": "PR_INTEGRATION_CANDIDATE",
        },
    }
    summary: dict[str, Any] = {
        "job": "python-quality",
        "steps": [
            {"key": "architecture", "status": "PASS", "log": ".ci/logs/architecture.log"},
            {"key": "pyright", "status": "PASS", "log": ".ci/logs/pyright.log"},
        ],
    }
    build_packets = cast(
        Callable[
            [dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]],
            list[dict[str, object]],
        ],
        finalizer.build_packets,
    )
    packets = build_packets(scan, baseline, summary, architecture_diff)
    assert len(packets) == 1
    packet = packets[0]
    assert packet["schema_version"] == "quality-evidence/v2"
    assert packet["base_sha"] == "a" * 40
    assert packet["source_head_sha"] == "b" * 40
    assert packet["tested_sha"] == "c" * 40
    assert packet["test_mode"] == "PR_INTEGRATION_CANDIDATE"
    assert packet["trigger_ids"] == ["QR-CPLX-001"]
    results = cast(list[dict[str, object]], packet["architecture_results"])
    assert any(
        item["fitness_id"] == "FF-ARCHITECTURE-SUITE-001" and item["status"] == "pass"
        for item in results
    )
    assert any(
        item["fitness_id"] == "FF-QUALITY-BASELINE-001" and item["status"] == "pass"
        for item in results
    )
    assert any(
        item["fitness_id"] == "FF-ARCH-DIFF-001" and item["status"] == "pass" for item in results
    )
    context = cast(list[str], packet["context_manifest"])
    assert "docs/engineering-quality/semantic-review-protocol.md" in context
    assert ".ci/architecture-diff.json" in context
    assert packet["authority"] == "heuristic-signals-are-non-blocking"


def test_evidence_finalization_rejects_mismatched_tested_tree(monkeypatch: Any) -> None:
    finalizer = _load(FINALIZER, "quality_finalizer_provenance_under_test")

    def tool_version_stub(_command: list[str], _fallback: str) -> str:
        return "test"

    monkeypatch.setattr(finalizer, "_tool_version", tool_version_stub)
    scan: dict[str, Any] = {
        "base_sha": "a" * 40,
        "head_sha": "c" * 40,
        "candidates": [],
    }
    baseline: dict[str, Any] = {
        "schema_version": "engineering-quality-baseline/v1",
        "repository_sha": "d" * 40,
    }
    architecture_diff: dict[str, Any] = {
        "schema_version": "architecture-diff/v1",
        "provenance": {
            "base_sha": "a" * 40,
            "source_head_sha": "b" * 40,
            "tested_sha": "c" * 40,
            "test_mode": "PR_INTEGRATION_CANDIDATE",
        },
    }
    summary: dict[str, Any] = {}
    try:
        finalizer.build_packets(scan, baseline, summary, architecture_diff)
    except ValueError as exc:
        assert "baseline tree does not match" in str(exc)
    else:
        raise AssertionError("mismatched tested-tree provenance was accepted")


def test_validator_reports_the_selected_schema_version_semantically() -> None:
    validator = _load(VALIDATOR, "quality_validator_under_test")
    resolve_version = cast(Callable[[Any], str], validator.schema_version)
    assert (
        resolve_version(
            {
                "properties": {
                    "schema_version": {
                        "const": "quality-evidence/v2",
                    }
                }
            }
        )
        == "quality-evidence/v2"
    )
    assert resolve_version({"properties": {}}) == "selected quality-evidence schema"


def test_human_model_calibration_never_imputes_missing_human_labels() -> None:
    calibration = _load(CALIBRATION, "quality_calibration_under_test")
    summarize = cast(
        Callable[[dict[str, Any]], dict[str, object]],
        calibration.summarize,
    )
    summary = summarize(
        {
            "schema_version": "semantic-review-pilot/v1",
            "observations": [
                {
                    "case_id": "a",
                    "model_verdict": "HEALTHY_AS_IS",
                    "human_verdict": "HEALTHY_AS_IS",
                    "human_disposition": "ACCEPTED_TRADEOFF",
                    "action_taken": "NONE",
                    "post_change_outcome": "NOT_APPLICABLE",
                    "gaming_observed": False,
                },
                {
                    "case_id": "b",
                    "model_verdict": "REFACTOR_RECOMMENDED",
                    "human_verdict": None,
                },
                {
                    "case_id": "c",
                    "model_verdict": "REVIEW_CONCERN",
                    "human_verdict": "ARCHITECTURE_CONCERN",
                    "human_disposition": "TRUE_POSITIVE",
                    "action_taken": "ARCHITECTURE_CHANGE",
                    "post_change_outcome": "IMPROVED",
                    "gaming_observed": True,
                },
            ],
        }
    )
    assert summary["schema_version"] == "human-model-calibration-summary/v2"
    assert summary["total_model_observations"] == 3
    assert summary["human_labeled_observations"] == 2
    assert summary["paired_observations"] == 2
    assert summary["exact_agreement_count"] == 1
    assert summary["exact_agreement_rate"] == 0.5
    assert summary["pending_human_case_ids"] == ["b"]
    assert summary["human_disposition_counts"] == {
        "ACCEPTED_TRADEOFF": 1,
        "TRUE_POSITIVE": 1,
    }
    assert summary["action_taken_counts"] == {
        "ARCHITECTURE_CHANGE": 1,
        "NONE": 1,
    }
    assert summary["post_change_outcome_counts"] == {
        "IMPROVED": 1,
        "NOT_APPLICABLE": 1,
    }
    assert summary["false_positive_rate"] == 0.0
    assert summary["gaming_labeled_observations"] == 2
    assert summary["gaming_observed_count"] == 1


def test_human_outcome_fields_cannot_exist_without_human_verdict() -> None:
    calibration = _load(CALIBRATION, "quality_calibration_validation_under_test")
    summarize = cast(
        Callable[[dict[str, Any]], dict[str, object]],
        calibration.summarize,
    )
    payload = {
        "schema_version": "semantic-review-pilot/v1",
        "observations": [
            {
                "case_id": "fabricated",
                "model_verdict": "REFACTOR_RECOMMENDED",
                "human_verdict": None,
                "human_disposition": "TRUE_POSITIVE",
            }
        ],
    }
    try:
        summarize(payload)
    except ValueError as exc:
        assert "require a genuine human_verdict" in str(exc)
    else:
        raise AssertionError("human outcome evidence was accepted without a human verdict")
