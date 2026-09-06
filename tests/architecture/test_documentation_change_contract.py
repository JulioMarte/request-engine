from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts" / "ci" / "check_documentation_contract.py"
REGISTRY = REPO_ROOT / "docs" / "architecture" / "documentation-contracts.toml"
POLICY_DOC = REPO_ROOT / "docs" / "architecture" / "documentation-change-contract.md"
WORKER_DOC = "docs/v3/10-worker-runtime-hardening.md"
WORKER_CODE = "src/request_engine/platform/worker/runtime.py"
SHARED_CAPACITY_DOC = "docs/v3/12-cross-tenant-shared-capacity-design.md"
SHARED_CAPACITY_BOOKING = "src/request_engine/modules/booking/adapters/db/reservation_commands.py"
SHARED_CAPACITY_COMMITMENTS = (
    "src/request_engine/modules/booking/adapters/db/commitment_commands.py"
)
SHARED_CAPACITY_TEST = "tests/db/test_v3_cross_tenant_slot_offer_integrity_hardening.py"
SHARED_CAPACITY_INTEGRATION_TEST = (
    "tests/integration/v3_booking_commitments/test_cross_tenant_shared_capacity.py"
)


def _run_checker(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_documentation_contract_registry_is_executable() -> None:
    assert REGISTRY.is_file()
    assert POLICY_DOC.is_file()
    result = _run_checker("--validate-only")
    assert result.returncode == 0, result.stderr or result.stdout
    assert "registry valid" in result.stdout


def test_documentation_contract_rejects_unaccompanied_worker_contract_change() -> None:
    result = _run_checker("--changed-file", WORKER_CODE)
    assert result.returncode == 1
    assert "[worker-runtime]" in result.stderr
    assert WORKER_DOC in result.stderr


def test_documentation_contract_accepts_worker_change_with_normative_doc() -> None:
    result = _run_checker(
        "--changed-file",
        WORKER_CODE,
        "--changed-file",
        WORKER_DOC,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "documentation contract satisfied" in result.stdout


def test_shared_capacity_contract_rejects_unaccompanied_protected_change() -> None:
    protected_paths = (
        SHARED_CAPACITY_BOOKING,
        SHARED_CAPACITY_COMMITMENTS,
        SHARED_CAPACITY_TEST,
        SHARED_CAPACITY_INTEGRATION_TEST,
    )
    for protected_path in protected_paths:
        result = _run_checker("--changed-file", protected_path)
        assert result.returncode == 1
        assert "[cross-tenant-shared-capacity]" in result.stderr
        assert SHARED_CAPACITY_DOC in result.stderr


def test_shared_capacity_contract_accepts_change_with_normative_doc() -> None:
    result = _run_checker(
        "--changed-file",
        SHARED_CAPACITY_BOOKING,
        "--changed-file",
        SHARED_CAPACITY_COMMITMENTS,
        "--changed-file",
        SHARED_CAPACITY_TEST,
        "--changed-file",
        SHARED_CAPACITY_INTEGRATION_TEST,
        "--changed-file",
        SHARED_CAPACITY_DOC,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "documentation contract satisfied" in result.stdout


def test_documentation_contract_is_enforced_for_pull_request_diff() -> None:
    env = os.environ.copy()
    if not env.get("GITHUB_BASE_REF") and not env.get("DOCUMENTATION_CONTRACT_BASE_SHA"):
        result = _run_checker(env=env)
        assert result.returncode == 0, result.stderr or result.stdout
        assert "no base ref available" in result.stdout
        return

    result = _run_checker(env=env)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "documentation contract satisfied" in result.stdout
