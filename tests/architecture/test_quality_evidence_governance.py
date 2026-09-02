from __future__ import annotations

import json
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "docs" / "engineering-quality" / "schemas" / "quality-evidence-v1.schema.json"
PILOT = ROOT / "docs" / "engineering-quality" / "calibration" / "pilot-observations.v1.json"
BEFORE_AFTER = (
    ROOT / "docs" / "engineering-quality" / "calibration" / "reviewer-fixer-evidence.v1.json"
)
CORE_AGENTS = ROOT / "src" / "request_engine" / "AGENTS.md"
MEGA_REGISTRY = ROOT / "docs" / "engineering-quality" / "mega-file-exceptions.v1.json"
MEGA_POLICY = ROOT / "docs" / "engineering-quality" / "mega-file-circuit-breaker.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
VALIDATOR = ROOT / "scripts" / "ci" / "validate_quality_evidence.py"


def _json(path: Path) -> dict[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _object_list(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    items = cast(list[object], value)
    assert all(isinstance(item, dict) for item in items)
    return cast(list[dict[str, object]], items)


def test_quality_evidence_uses_versioned_draft_2020_12_schema() -> None:
    schema = _json(SCHEMA)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    raw_required = schema["required"]
    assert isinstance(raw_required, list)
    required_items = cast(list[object], raw_required)
    required = {str(item) for item in required_items}
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
    assert "Enforce quality-policy separation" in workflow
    assert "check_quality_policy_separation.py" in workflow
    assert "QUALITY_POLICY_BASE_REF" in workflow
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
    typed_policy = cast(dict[str, object], policy)
    assert typed_policy.get("no_imputation") is True


def test_reviewer_fixer_evidence_contains_deterministic_reproof_not_self_certification() -> None:
    payload = _json(BEFORE_AFTER)
    entries = _object_list(payload["entries"])
    assert entries
    proved: list[dict[str, object]] = []
    for item in entries:
        reproof = item.get("deterministic_reproof")
        if not isinstance(reproof, dict):
            continue
        typed_reproof = cast(dict[str, object], reproof)
        if typed_reproof.get("workflow_run_id") is not None:
            proved.append(item)
    assert proved
    assert all(item.get("reviewer_role") != item.get("fixer_role") for item in entries)


def test_core_agent_instructions_make_mega_file_self_approval_invalid() -> None:
    instructions = CORE_AGENTS.read_text(encoding="utf-8")
    for required in (
        "QR-MEGA-001",
        "QR-MEGA-GOV-001",
        "500 effective code-bearing lines",
        "Self-justification is not authority",
        "same implementation change",
        "must be reviewed and merged into the integration base",
        "# @generated",
        "not exemption authority",
        "MUST NOT edit the mega-file checker",
        "Do not split a cohesive file",
    ):
        assert required in instructions


def test_mega_file_registry_starts_bounded_and_base_authority_is_documented() -> None:
    registry = _json(MEGA_REGISTRY)
    assert registry["schema_version"] == "mega-file-exceptions/v1"
    assert registry["exceptions"] == []
    assert "same implementation PR cannot waive QR-MEGA-001" in str(registry["policy"])
    policy = MEGA_POLICY.read_text(encoding="utf-8")
    assert "reads the exception registry from the branch base" in policy
    assert "cannot authorize that PR" in policy
