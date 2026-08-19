import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/validate_v3_adversarial_failure_artifact.py"
SPEC = importlib.util.spec_from_file_location("v3_adversarial_failure_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _proof() -> dict[str, Any]:
    families = [
        {
            "id": family_id,
            "status": "PASS",
            "owners": [f"tests/{family_id}.py"],
            "expected_owner_count": 1,
            "observed_owner_count": 1,
            "failures": [],
        }
        for family_id in sorted(validator.REQUIRED_FAMILIES)
    ]
    races = [
        {
            "id": race_id,
            "status": "PASS",
            "owners": [f"tests/{race_id.lower()}.py"],
            "required_node_selectors": [f"tests/{race_id.lower()}.py::test_{race_id.lower()}"],
            "expected_owner_count": 1,
            "observed_owner_count": 1,
            "expected_node_selector_count": 1,
            "observed_node_selector_count": 1,
        }
        for race_id in sorted(validator.REQUIRED_RACES)
    ]
    return {
        "schema_version": 1,
        "status": "PASS",
        "source": {
            "head_sha": "a" * 40,
            "tested_sha": "b" * 40,
            "checkout_sha": "c" * 40,
            "tree_sha": "d" * 40,
        },
        "environment": {"python": "3.13", "postgres_major": 18},
        "expected_family_count": 6,
        "observed_family_count": 6,
        "families": families,
        "expected_race_count": 29,
        "observed_race_count": 29,
        "races": races,
        "supporting_artifacts": {
            name: {"status": "PASS"} for name in sorted(validator.REQUIRED_SUPPORTING)
        },
        "missing_evidence": [],
        "failures": [],
    }


def test_g18_artifact_semantics_accept_complete_pass_payload() -> None:
    assert validator.validate_adversarial_failure(_proof()) == []


def test_g18_artifact_semantics_reject_top_level_pass_with_missing_race() -> None:
    payload = _proof()
    payload["races"] = payload["races"][1:]
    payload["observed_race_count"] = 28
    errors = validator.validate_adversarial_failure(payload)
    assert any("missing races: R01" in error for error in errors)


def test_g18_artifact_semantics_reject_unobserved_required_pytest_node() -> None:
    payload = _proof()
    first = payload["races"][0]
    first["observed_node_selector_count"] = 0
    errors = validator.validate_adversarial_failure(payload)
    assert any("missing required pytest nodes" in error for error in errors)


def test_g18_artifact_semantics_reject_non_pass_family_and_supporting_artifact() -> None:
    payload = _proof()
    payload["families"][0]["status"] = "FAIL"
    payload["supporting_artifacts"]["mutation_probes"] = {"status": "FAIL"}
    errors = validator.validate_adversarial_failure(payload)
    assert any("family" in error and "is not PASS" in error for error in errors)
    assert "adversarial supporting artifact mutation_probes is not PASS" in errors


def test_g18_artifact_semantics_reject_cardinality_lies() -> None:
    payload = _proof()
    payload["families"][0]["observed_owner_count"] = 0
    payload["races"][0]["expected_node_selector_count"] = 2
    errors = validator.validate_adversarial_failure(payload)
    assert any("is missing owners" in error for error in errors)
    assert any("expected pytest node count is inconsistent" in error for error in errors)


def test_g18_artifact_is_mandatory_in_candidate_manifest_and_ci() -> None:
    manifest = (ROOT / "scripts/release/build_v3_evidence_manifest.py").read_text(encoding="utf-8")
    manifest_base = (ROOT / "scripts/release/build_v3_evidence_manifest_base.py").read_text(
        encoding="utf-8"
    )
    ci_jobs = (ROOT / "scripts/ci/ci_jobs.py").read_text(encoding="utf-8")

    assert "build_v3_evidence_manifest_base.py" in manifest
    assert '"adversarial_failure": _VALIDATE_G18' in manifest_base
    assert "validate_v3_adversarial_failure_artifact.py" in manifest_base
    assert (
        '"adversarial_failure": ROOT / ".phase6/v3-adversarial-failure-proof.json"'
        in manifest_base
    )
    assert '"adversarial-failure-proof"' in ci_jobs
    assert "prove_v3_adversarial_failure.py" in ci_jobs
