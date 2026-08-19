import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts/release/validate_v3_final_release_artifact.py"
)
SPEC = importlib.util.spec_from_file_location("v3_final_release_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validator: ModuleType = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def _payload() -> dict[str, object]:
    sha1 = "a" * 40
    sha256 = "b" * 64
    return {
        "schema_version": 1,
        "proof": "v3-final-release-proof",
        "status": "PASS",
        "criteria": {"exact_head_provenance": True, "evidence_valid": True},
        "failures": [],
        "source": {
            "head_sha": sha1,
            "base_sha": sha1,
            "tested_sha": sha1,
            "checkout_sha": sha1,
            "tree_sha": sha1,
            "working_tree_dirty": False,
        },
        "gate_statuses": {
            **{f"G{number:02d}": "PASS" for number in range(1, 20)},
            "G20": "MISSING",
        },
        "evidence_inputs": {name: sha256 for name in validator.REQUIRED_EVIDENCE},
        "registry_digests": {
            "invariant_registry_sha256": sha256,
            "race_registry_sha256": sha256,
            "gate_registry_sha256": sha256,
        },
        "test_inventory_sha256": sha256,
        "runtime": {
            "python": "3.13.7",
            "postgres_target": "18",
            "bootstrap_role": "postgres",
            "application_role": "request_engine_app",
            "worker_role": "request_engine_worker",
            "admin_role": "request_engine_admin",
        },
        "preflight_sha256": sha256,
        "preflight_evidence_status": "VALID",
        "preflight_artifact_set_complete": True,
        "preflight_missing_artifacts": [],
        "preflight_validation_errors": [],
        "preflight_release_status": "NOT_READY",
        "preflight_release_ready": False,
    }


def test_final_release_validator_accepts_bound_preflight_with_g20_missing_or_pass() -> None:
    payload = _payload()
    assert validator.validation_errors(payload) == []

    promoted = deepcopy(payload)
    promoted["gate_statuses"]["G20"] = "PASS"  # type: ignore[index]
    assert validator.validation_errors(promoted) == []


def test_final_release_validator_rejects_lying_pass_and_provenance_drift() -> None:
    payload = _payload()
    payload["source"]["working_tree_dirty"] = True  # type: ignore[index]
    payload["source"]["base_sha"] = "missing"  # type: ignore[index]
    payload["gate_statuses"]["G17"] = "MISSING"  # type: ignore[index]
    payload["preflight_evidence_status"] = "INVALID"
    payload["preflight_release_status"] = "READY"
    payload["preflight_release_ready"] = True

    errors = validator.validation_errors(payload)
    assert "source working tree is not clean" in errors
    assert "source base_sha is malformed" in errors
    assert "G17 is not PASS" in errors
    assert "preflight evidence status is not VALID" in errors
    assert "preflight release status must be NOT_READY" in errors
    assert "preflight release_ready must be false" in errors


def test_final_release_validator_rejects_evidence_and_registry_digest_drift() -> None:
    payload = _payload()
    payload["evidence_inputs"].pop("candidate_freeze")  # type: ignore[union-attr]
    payload["registry_digests"]["gate_registry_sha256"] = "not-a-digest"  # type: ignore[index]

    errors = validator.validation_errors(payload)
    assert "evidence input inventory is incomplete or contains drift" in errors
    assert "one or more registry digests are malformed" in errors


def test_final_release_validator_rejects_invalid_g20_status_and_runtime_roles() -> None:
    payload = _payload()
    payload["gate_statuses"]["G20"] = "PARTIAL"  # type: ignore[index]
    payload["runtime"]["worker_role"] = "request_engine_admin"  # type: ignore[index]

    errors = validator.validation_errors(payload)
    assert "G20 status is neither MISSING nor PASS" in errors
    assert "runtime worker_role does not match the release role contract" in errors
