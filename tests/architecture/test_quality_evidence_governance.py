from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "engineering-quality" / "schemas" / "quality-evidence-v1.schema.json"
PILOT = ROOT / "docs" / "engineering-quality" / "calibration" / "pilot-observations.v1.json"
BEFORE_AFTER = (
    ROOT / "docs" / "engineering-quality" / "calibration" / "reviewer-fixer-evidence.v1.json"
)
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
VALIDATOR = ROOT / "scripts" / "ci" / "validate_quality_evidence.py"


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _object_list(value: Any) -> list[dict[str, Any]]:
    assert isinstance(value, list)
    assert all(isinstance(item, dict) for item in value)
    return cast(list[dict[str, Any]], value)


def test_quality_evidence_uses_versioned_draft_2020_12_schema() -> None:
    schema = _json(SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    raw_required: Any = schema["required"]
    assert isinstance(raw_required, list)
    required = {str(item) for item in raw_required}
    assert {
        "candidate_id",
        "trigger_ids",
        "base_sha",
        "head_sha",
        "facts",
        "architecture_results",
        "context_manifest",
        "review_questions",
        "provenance",
        "authority",
    } <= required
    validator = VALIDATOR.read_text(encoding="utf-8")
    assert "Draft202012Validator" in validator
    assert "check_schema" in validator


def test_successful_quality_evidence_is_persisted_for_longitudinal_calibration() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Finalize quality evidence packets" in workflow
    assert "Validate quality evidence schema" in workflow
    assert "Summarize semantic review calibration" in workflow
    assert "Upload Python quality evidence" in workflow
    assert "if: always()" in workflow
    assert "retention-days: 90" in workflow
    assert "jsonschema==4.25.1" in workflow


def test_pilot_observations_are_real_model_records_without_fabricated_human_labels() -> None:
    payload = _json(PILOT)
    observations = _object_list(payload["observations"])
    assert len(observations) >= 4
    assert all(bool(item.get("model_verdict")) for item in observations)
    assert any(item.get("human_verdict") is None for item in observations)
    policy = payload["human_label_policy"]
    assert isinstance(policy, dict)
    assert policy.get("no_imputation") is True


def test_reviewer_fixer_evidence_contains_deterministic_reproof_not_self_certification() -> None:
    payload = _json(BEFORE_AFTER)
    entries = _object_list(payload["entries"])
    assert entries
    proved: list[dict[str, Any]] = []
    for item in entries:
        reproof = item.get("deterministic_reproof")
        if isinstance(reproof, dict) and reproof.get("workflow_run_id") is not None:
            proved.append(item)
    assert proved
    assert all(item.get("reviewer_role") != item.get("fixer_role") for item in entries)
