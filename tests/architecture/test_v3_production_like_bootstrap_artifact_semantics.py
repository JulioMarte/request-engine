import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/validate_v3_production_like_bootstrap_artifact.py"
SPEC = importlib.util.spec_from_file_location("v3_production_like_bootstrap_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _proof() -> dict[str, Any]:
    criteria = [
        {"id": criterion_id, "status": "PASS"}
        for criterion_id in sorted(validator.REQUIRED_CRITERIA)
    ]
    required_nodes = {
        node_id: {
            "node_id": f"tests/{node_id}.py::test_{node_id}",
            "status": "PASS",
        }
        for node_id in sorted(validator.REQUIRED_NODES)
    }
    roles = [
        {
            "role_name": f"re_g19_{index}",
            "parent_role": parent_role,
            "attributes": dict(validator.EXPECTED_ATTRIBUTES),
            "memberships": [parent_role],
            "status": "PASS",
        }
        for index, parent_role in enumerate(sorted(validator.REQUIRED_PARENT_ROLES), start=1)
    ]
    return {
        "schema_version": 1,
        "status": "PASS",
        "criteria": criteria,
        "failures": [],
        "required_nodes": required_nodes,
        "canonical_suite": {
            "tests": 463,
            "collected_nodes": 463,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
            "status": "PASS",
        },
        "runtime": {
            "postgresql_major": 18,
            "database": "request_engine_v3",
            "roles": roles,
            "secrets_redacted": True,
        },
        "clean_start": {
            "status": "PASS",
            "application_schema_count": 0,
            "public_base_table_count": 0,
        },
        "source": {
            "head_sha": "a" * 40,
            "tested_sha": "b" * 40,
            "checkout_sha": "c" * 40,
            "tree_sha": "d" * 40,
        },
    }


def test_g19_artifact_semantics_accept_complete_pass_payload() -> None:
    assert validator.validate_production_like_bootstrap(_proof()) == []


def test_g19_artifact_semantics_reject_shallow_top_level_pass() -> None:
    payload = _proof()
    payload["canonical_suite"]["tests"] = 462
    payload["runtime"]["roles"][0]["attributes"]["bypass_rls"] = True
    payload["clean_start"]["application_schema_count"] = 1

    errors = validator.validate_production_like_bootstrap(payload)

    assert "G19 canonical suite execution does not equal collection" in errors
    assert any("unsafe attributes" in error for error in errors)
    assert "G19 database was not clean before bootstrap" in errors


def test_g19_artifact_semantics_reject_missing_required_node_and_extra_membership() -> None:
    payload = _proof()
    payload["required_nodes"].pop("worker_crash_recovery")
    payload["runtime"]["roles"][0]["memberships"].append("request_engine_worker")

    errors = validator.validate_production_like_bootstrap(payload)

    assert "G19 required-node inventory is not exact" in errors
    assert any("extra memberships" in error for error in errors)


def test_g19_manifest_extension_requires_semantically_valid_artifact(tmp_path: Path) -> None:
    manifest_path = ROOT / "scripts/release/build_v3_evidence_manifest.py"
    manifest_spec = importlib.util.spec_from_file_location(
        "v3_evidence_manifest_g19",
        manifest_path,
    )
    assert manifest_spec is not None and manifest_spec.loader is not None
    manifest: ModuleType = importlib.util.module_from_spec(manifest_spec)
    sys.modules[manifest_spec.name] = manifest
    manifest_spec.loader.exec_module(manifest)

    missing = manifest._validate_g19_artifact(tmp_path / "missing.json")
    assert missing["status"] == "MISSING"

    proof_path = tmp_path / "g19.json"
    proof_path.write_text(json.dumps(_proof()), encoding="utf-8")
    valid = manifest._validate_g19_artifact(proof_path)
    assert valid["status"] == "PASS"

    invalid_payload = _proof()
    invalid_payload["runtime"]["postgresql_major"] = 17
    proof_path.write_text(json.dumps(invalid_payload), encoding="utf-8")
    invalid = manifest._validate_g19_artifact(proof_path)
    assert invalid["status"] == "FAIL"


def test_g19_remains_release_evidence_without_being_regenerated_post_baseline() -> None:
    manifest = (ROOT / "scripts/release/build_v3_evidence_manifest.py").read_text(encoding="utf-8")
    release_wrapper = (ROOT / "scripts/ci/run_v3_candidate_with_g19.sh").read_text(
        encoding="utf-8"
    )
    compatibility_wrapper = (ROOT / "scripts/ci/run_v3_frozen_compatibility.sh").read_text(
        encoding="utf-8"
    )
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "validate_v3_production_like_bootstrap_artifact.py" in manifest
    assert ".phase6/v3-production-like-bootstrap-proof.json" in manifest
    assert "production_like_bootstrap" in manifest
    assert "prove_v3_clean_start.py" in release_wrapper
    assert "provision_v3_release_runtime.py" in release_wrapper
    assert "prove_v3_production_like_bootstrap.py" in release_wrapper
    assert "--cleanup" in release_wrapper
    assert "run_v3_frozen_compatibility.sh" in workflow
    assert "prove_v3_production_like_bootstrap.py" not in compatibility_wrapper
    assert "build_v3_evidence_manifest.py" not in compatibility_wrapper
