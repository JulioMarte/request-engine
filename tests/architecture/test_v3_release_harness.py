from __future__ import annotations

import subprocess
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from psycopg.conninfo import conninfo_to_dict

import conftest as root_conftest

ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(name: str, relative_path: str) -> ModuleType:
    spec = spec_from_file_location(name, ROOT / relative_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {relative_path}")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


required_needs = _load_script_module(
    "required_needs_under_test", "scripts/ci/require_successful_needs.py"
)
evidence = _load_script_module(
    "evidence_manifest_under_test", "scripts/release/build_v3_evidence_manifest.py"
)
scratch = _load_script_module(
    "scratch_database_under_test", "scripts/release/v3_scratch_database.py"
)
fingerprint = _load_script_module(
    "schema_fingerprint_under_test", "scripts/db/v3_schema_fingerprint.py"
)
validate_required_needs = cast(
    Callable[[object], list[str]], required_needs.validate_required_needs
)


def _completed(
    command: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


def test_required_ci_gate_rejects_failed_skipped_and_missing_dependencies() -> None:
    assert validate_required_needs({}) == ["required dependency results are missing or empty"]
    assert validate_required_needs(
        {
            "python-quality": {"result": "success"},
            "observability-contract": {"result": "failure"},
            "postgres-v3-bootstrap-proof": {"result": "skipped"},
        }
    ) == [
        "observability-contract: expected success, received 'failure'",
        "postgres-v3-bootstrap-proof: expected success, received 'skipped'",
    ]


def test_required_ci_gate_accepts_only_successful_dependencies() -> None:
    assert (
        validate_required_needs(
            {
                "python-quality": {"result": "success"},
                "observability-contract": {"result": "success"},
                "postgres-v3-bootstrap-proof": {"result": "success"},
            }
        )
        == []
    )


def test_required_candidate_job_always_reports_dependency_failures() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    candidate_job = workflow.split("  postgres-v3-candidate:\n", 1)[1]

    assert "name: PostgreSQL 18 V3 candidate and verticals" in candidate_job
    assert "- postgres-v3-candidate-proof" in candidate_job
    assert "if: ${{ always() }}" in candidate_job
    assert "REQUIRED_NEEDS_JSON: ${{ toJSON(needs) }}" in candidate_job
    assert "python scripts/ci/require_successful_needs.py" in candidate_job


def test_postgres_isolation_conninfo_escapes_values_and_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PGPASSWORD", "spaces and 'quotes' \\ remain data")
    params = conninfo_to_dict(root_conftest.postgres_test_conninfo())

    assert params["password"] == "spaces and 'quotes' \\ remain data"
    assert params["connect_timeout"] == "5"
    assert params["application_name"] == "request-engine-pytest-isolation"
    assert set(root_conftest.APPLICATION_SCHEMAS) == evidence.APPLICATION_SCHEMAS
    assert set(root_conftest.APPLICATION_SCHEMAS) == set(fingerprint.APPLICATION_SCHEMAS)


def test_fresh_database_bootstraps_drops_and_verifies_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str], int]] = []
    monkeypatch.setattr(scratch, "uuid4", lambda: SimpleNamespace(hex="a" * 32))

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_seconds: int = scratch.COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((command, env, timeout_seconds))
        if command[0] == "psql":
            return _completed(command, stdout="0\n")
        return _completed(command)

    monkeypatch.setattr(scratch, "_run", fake_run)
    with scratch.fresh_v3_database("request_engine_proof") as scratch_env:
        assert scratch_env["PGDATABASE"] == f"request_engine_proof_{'a' * 20}"
        assert scratch_env["PGCONNECT_TIMEOUT"] == "5"

    assert [command[0] for command, _, _ in calls] == [
        "createdb",
        "bash",
        "dropdb",
        "psql",
    ]
    assert calls[1][2] == scratch.BOOTSTRAP_TIMEOUT_SECONDS


def test_fresh_database_surfaces_cleanup_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scratch, "uuid4", lambda: SimpleNamespace(hex="b" * 32))

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_seconds: int = scratch.COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        del env, timeout_seconds
        if command[0] == "dropdb":
            return _completed(command, returncode=1, stderr="database is still in use")
        return _completed(command)

    monkeypatch.setattr(scratch, "_run", fake_run)
    with (
        pytest.raises(scratch.ScratchDatabaseError, match="could not drop scratch database"),
        scratch.fresh_v3_database("request_engine_proof"),
    ):
        pass


def test_fresh_database_cleans_an_ambiguous_create_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(scratch, "uuid4", lambda: SimpleNamespace(hex="d" * 32))

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_seconds: int = scratch.COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        del env, timeout_seconds
        commands.append(command)
        if command[0] == "createdb":
            return _completed(command, returncode=1, stderr="connection lost")
        if command[0] == "psql":
            return _completed(command, stdout="0\n")
        return _completed(command)

    monkeypatch.setattr(scratch, "_run", fake_run)
    with (
        pytest.raises(scratch.ScratchDatabaseError, match="could not create scratch database"),
        scratch.fresh_v3_database("request_engine_proof"),
    ):
        pytest.fail("a failed createdb must not yield")

    assert [command[0] for command in commands] == ["createdb", "dropdb", "psql"]
    assert "--if-exists" in commands[1]


def test_fresh_database_preserves_body_error_and_annotates_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scratch, "uuid4", lambda: SimpleNamespace(hex="c" * 32))

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str],
        timeout_seconds: int = scratch.COMMAND_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        del env, timeout_seconds
        if command[0] == "dropdb":
            return _completed(command, returncode=1, stderr="database is still in use")
        return _completed(command)

    monkeypatch.setattr(scratch, "_run", fake_run)
    with (
        pytest.raises(ValueError, match="body failed") as caught,
        scratch.fresh_v3_database("request_engine_proof"),
    ):
        raise ValueError("body failed")

    assert any("cleanup also failed" in note for note in caught.value.__notes__)


def test_scratch_command_timeout_is_a_harness_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def time_out(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired(["createdb"], 60)

    monkeypatch.setattr(subprocess, "run", time_out)
    with pytest.raises(scratch.ScratchDatabaseError, match="timed out after 60 seconds"):
        scratch._run(["createdb"], env={})


def test_shell_database_proofs_do_not_hide_cleanup_failures() -> None:
    proofs = (
        ROOT / "scripts/db/prove_v3_candidate_bootstrap.sh",
        ROOT / "scripts/db/prove_v3_initial_equivalence.sh",
    )

    for proof in proofs:
        source = proof.read_text(encoding="utf-8")
        cleanup = source.split("cleanup() {", 1)[1].split("}\ntrap cleanup EXIT", 1)[0]
        assert "|| true" not in cleanup
        assert "dropdb --if-exists --force" in cleanup
        assert "SELECT count(*) FROM pg_database" in cleanup
        assert 'exit "${cleanup_status}"' in cleanup


def test_evidence_validation_rejects_failed_json_even_when_file_exists(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "quality.json"
    artifact.write_text(
        '{"status":"FAIL","error_count":1,"tests_audited":10}\n',
        encoding="utf-8",
    )

    result = evidence._validate_artifact("test_quality", artifact)

    assert result["status"] == "FAIL"
    assert result["sha256"] is not None
    assert "status is not PASS" in result["errors"]


def test_evidence_validation_rejects_junit_failures_and_skips(tmp_path: Path) -> None:
    artifact = tmp_path / "junit.xml"
    artifact.write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1"/></testsuites>',
        encoding="utf-8",
    )

    result = evidence._validate_artifact("test_junit", artifact)

    assert result["status"] == "FAIL"
    assert result["errors"] == [
        "JUnit report contains 1 failures",
        "JUnit report contains 1 skipped",
    ]


def test_release_manifest_does_not_confuse_candidate_evidence_with_release_readiness() -> None:
    statuses = evidence._gate_statuses()

    assert len(statuses) == 20
    assert any(status != "PASS" for status in statuses.values())
    assert evidence._release_ready("VALID", statuses) is False
    assert evidence._release_ready("INVALID", dict.fromkeys(statuses, "PASS")) is False
