import importlib.util
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/release/build_v3_evidence_manifest.py"
SPEC = importlib.util.spec_from_file_location("v3_evidence_manifest", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
manifest: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = manifest
SPEC.loader.exec_module(manifest)


def test_schema_validator_requires_postgres18_application_schemas_and_catalog() -> None:
    assert (
        manifest._validate_schema(
            {
                "postgres_major": 18,
                "application_schemas": sorted(manifest.APPLICATION_SCHEMAS),
                "catalog": {"relations": ["request_engine.organizations"]},
            }
        )
        == []
    )

    errors = manifest._validate_schema(
        {"postgres_major": 17, "application_schemas": ["request_engine"], "catalog": {}}
    )
    assert "postgres_major is not 18" in errors
    assert "application_schemas does not match the V3 contract" in errors
    assert "catalog fingerprint is empty or malformed" in errors


def test_semantic_json_validators_reject_shallow_pass_markers() -> None:
    assert (
        manifest._validate_test_quality({"status": "PASS", "error_count": 0, "tests_audited": 204})
        == []
    )
    assert (
        manifest._validate_test_collection({"status": "PASS", "node_count": 273, "errors": []})
        == []
    )

    quality_errors = manifest._validate_test_quality(
        {"status": "PASS", "error_count": 1, "tests_audited": 0}
    )
    assert "test quality error_count is not zero" in quality_errors
    assert "test quality audit covered zero tests" in quality_errors


def test_worker_plan_validator_requires_measured_index_selection() -> None:
    assert (
        manifest._validate_worker_plans(
            {
                "proofs": [
                    {
                        "name": "scheduled-action-due-claim",
                        "required_index": "scheduled_actions_due_idx",
                        "indexes": ["scheduled_actions_due_idx"],
                    }
                ]
            }
        )
        == []
    )

    errors = manifest._validate_worker_plans(
        {
            "proofs": [
                {
                    "name": "scheduled-action-due-claim",
                    "required_index": "scheduled_actions_due_idx",
                    "indexes": [],
                }
            ]
        }
    )
    assert any("required index was not selected" in error for error in errors)


def test_junit_validator_rejects_failures_errors_and_skips(tmp_path: Path) -> None:
    report = tmp_path / "junit.xml"
    report.write_text(
        '<testsuite tests="4" failures="1" errors="1" skipped="1"/>',
        encoding="utf-8",
    )
    errors = manifest._validate_junit(report)
    assert "JUnit report contains 1 failures" in errors
    assert "JUnit report contains 1 errors" in errors
    assert "JUnit report contains 1 skipped" in errors


def test_equivalence_validator_requires_success_marker_and_fingerprint(tmp_path: Path) -> None:
    proof = tmp_path / "equivalence.txt"
    proof.write_text(
        "generated 0001_initial candidate is catalog-equivalent to the V3 candidate chain\n"
        + "a" * 64
        + "\n",
        encoding="utf-8",
    )
    assert manifest._validate_equivalence(proof) == []

    proof.write_text("catalog-equivalent to the V3 candidate chain", encoding="utf-8")
    assert "catalog-equivalence success marker is missing" in manifest._validate_equivalence(proof)


def test_release_gate_registry_and_release_ready_are_consistent() -> None:
    statuses = manifest._gate_statuses()
    assert set(statuses) == {f"G{number:02d}" for number in range(1, 21)}

    expected_ready = all(status == "PASS" for status in statuses.values())
    assert manifest._release_ready("VALID", statuses) is expected_ready

    degraded = dict(statuses)
    degraded["G20"] = "MISSING"
    assert manifest._release_ready("VALID", degraded) is False
    assert manifest._release_ready("INVALID", statuses) is False


def test_release_ready_requires_all_twenty_gates() -> None:
    all_pass = {f"G{number:02d}": "PASS" for number in range(1, 21)}
    assert manifest._release_ready("VALID", all_pass) is True
    assert manifest._release_ready("INVALID", all_pass) is False
    all_pass.pop("G20")
    assert manifest._release_ready("VALID", all_pass) is False
