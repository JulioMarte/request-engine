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
