import runpy
import subprocess
import sys
from collections.abc import Callable
from typing import Any, cast

ProofValidator = Callable[..., tuple[list[str], bool]]


def _registry_validator_module() -> dict[str, Any]:
    return runpy.run_path(
        "scripts/release/validate_v3_invariant_registry.py",
        run_name="v3_invariant_registry_validator_test",
    )


def test_v3_invariant_proof_registry_is_complete_and_owner_bound() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/release/validate_v3_invariant_registry.py"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_communications_registry_requires_exact_existing_pytest_nodes() -> None:
    module = _registry_validator_module()
    exact_ids = cast(set[str], module["EXACT_NODE_EVIDENCE_IDS"])
    assert exact_ids == {f"V3-I{i:02d}" for i in range(44, 52)}

    validate_proof = cast(ProofValidator, module["_validate_proof_reference"])
    valid = (
        "tests/integration/v3_first_vertical/test_reminder_schedule_contract.py"
        "::test_i48_create_plan_persists_explicit_schedule_document_version"
    )
    errors, postgres = validate_proof("V3-I48", valid, require_exact_node=True)
    assert errors == []
    assert postgres is True

    missing_node = "tests/integration/v3_first_vertical/test_reminder_schedule_contract.py"
    errors, _postgres = validate_proof("V3-I48", missing_node, require_exact_node=True)
    assert any("exact pytest node" in error for error in errors)

    nonexistent = missing_node + "::test_does_not_exist"
    errors, _postgres = validate_proof("V3-I48", nonexistent, require_exact_node=True)
    assert any("does not exist" in error for error in errors)
