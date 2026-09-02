from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
FINALIZER = ROOT / "scripts" / "ci" / "finalize_quality_evidence.py"
CALIBRATION = ROOT / "scripts" / "ci" / "summarize_quality_calibration.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finalized_packet_attaches_deterministic_architecture_results(
    monkeypatch: Any,
) -> None:
    finalizer = _load(FINALIZER, "quality_finalizer_under_test")
    monkeypatch.setattr(finalizer, "_tool_version", lambda _command, _fallback: "ruff 0.test")
    scan = {
        "schema_version": "quality-scan/v1",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
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
    baseline = {
        "schema_version": "engineering-quality-baseline/v1",
        "repository_sha": "b" * 40,
    }
    summary = {
        "job": "python-quality",
        "steps": [
            {"key": "architecture", "status": "PASS", "log": ".ci/logs/architecture.log"},
            {"key": "pyright", "status": "PASS", "log": ".ci/logs/pyright.log"},
        ],
    }
    packets = cast(Any, finalizer.build_packets)(scan, baseline, summary)
    assert len(packets) == 1
    packet = packets[0]
    assert packet["schema_version"] == "quality-evidence/v1"
    assert packet["trigger_ids"] == ["QR-CPLX-001"]
    results = cast(list[dict[str, object]], packet["architecture_results"])
    assert any(
        item["fitness_id"] == "FF-ARCHITECTURE-SUITE-001" and item["status"] == "pass"
        for item in results
    )
    context = cast(list[str], packet["context_manifest"])
    assert "docs/engineering-quality/semantic-review-protocol.md" in context
    assert packet["authority"] == "heuristic-signals-are-non-blocking"


def test_human_model_calibration_never_imputes_missing_human_labels() -> None:
    calibration = _load(CALIBRATION, "quality_calibration_under_test")
    summarize = cast(Any, calibration.summarize)
    summary = summarize(
        {
            "schema_version": "semantic-review-pilot/v1",
            "observations": [
                {
                    "case_id": "a",
                    "model_verdict": "HEALTHY_AS_IS",
                    "human_verdict": "HEALTHY_AS_IS",
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
                },
            ],
        }
    )
    assert summary["total_model_observations"] == 3
    assert summary["human_labeled_observations"] == 2
    assert summary["paired_observations"] == 2
    assert summary["exact_agreement_count"] == 1
    assert summary["exact_agreement_rate"] == 0.5
    assert summary["pending_human_case_ids"] == ["b"]
