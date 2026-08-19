#!/usr/bin/env python3
"""Prove behavioral and runtime equivalence for the V3 final-initial candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FREEZE = ROOT / ".phase6/v3-candidate-freeze.json"
DEFAULT_INITIAL_SQL = ROOT / ".phase6/0001_initial.candidate.sql"
DEFAULT_CANDIDATE_SCHEMA = (
    ROOT / ".phase6/v3-initial-equivalence-candidate-schema.json"
)
DEFAULT_CANDIDATE_JUNIT = ROOT / ".phase6/v3-tests-junit.xml"
DEFAULT_INITIAL_SCHEMA = ROOT / ".phase6/v3-final-initial-schema.json"
DEFAULT_INITIAL_JUNIT = ROOT / ".phase6/v3-final-initial-tests-junit.xml"
DEFAULT_RUNTIME = ROOT / ".phase6/v3-final-initial-runtime.json"
DEFAULT_OUTPUT = ROOT / ".phase6/v3-final-initial-equivalence.json"
DEFAULT_RUNTIME_ENV = ROOT / ".ci/v3-final-initial-runtime.env"
DEFAULT_DATABASE = "request_engine_v3_g17_initial"
SELECTOR = "ci_jobs:postgres-v3-candidate:v3-tests"
APPLICATION_SCHEMAS = (
    "request_engine",
    "request_read",
    "request_cmd",
    "request_admin",
)
FINGERPRINT_ROLES = (
    "request_engine_schema_owner",
    "request_engine_app",
    "request_engine_worker",
    "request_engine_admin",
)


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture_output,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return payload


def _junit_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else list(root)
    suites = [suite for suite in suites if suite.tag.rsplit("}", 1)[-1] == "testsuite"]
    if not suites:
        raise ValueError(f"{path} contains no JUnit test suite")

    totals = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    test_ids = sorted(
        f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
        for suite in suites
        for case in suite.iter()
        if case.tag.rsplit("}", 1)[-1] == "testcase"
    )
    if totals["tests"] != len(test_ids):
        raise ValueError(
            f"{path} reports {totals['tests']} tests but exposes {len(test_ids)} testcases"
        )
    if len(test_ids) != len(set(test_ids)):
        raise ValueError(f"{path} contains duplicate testcase identities")
    test_ids_digest = hashlib.sha256("\n".join(test_ids).encode("utf-8")).hexdigest()
    return {
        "selector": SELECTOR,
        "test_count": totals["tests"],
        "failures": totals["failures"],
        "errors": totals["errors"],
        "skipped": totals["skipped"],
        "test_ids": test_ids,
        "test_ids_sha256": test_ids_digest,
        "junit_sha256": _sha256(path),
    }


def _fingerprint_record(payload: dict[str, Any]) -> dict[str, Any]:
    return {"sha256": _canonical_sha256(payload), "payload": payload}


def _validate_database_name(database: str) -> None:
    if not database or len(database) > 63:
        raise ValueError("database name must contain 1..63 characters")
    if not (database[0].isalpha() or database[0] == "_"):
        raise ValueError("database name must begin with a letter or underscore")
    if not all(char.isalnum() or char == "_" for char in database):
        raise ValueError("database name must be a simple PostgreSQL identifier")


def _drop_database(database: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "dropdb",
            "--if-exists",
            "--force",
            f"--maintenance-db={env.get('PGMAINTENANCE_DB', 'postgres')}",
            database,
        ],
        env=env,
        capture_output=True,
    )


def _create_database(database: str, env: dict[str, str]) -> None:
    dropped = _drop_database(database, env)
    if dropped.returncode != 0:
        detail = dropped.stderr.strip() or dropped.stdout.strip()
        raise RuntimeError(f"could not remove stale G17 database: {detail}")
    result = _run(
        [
            "createdb",
            f"--maintenance-db={env.get('PGMAINTENANCE_DB', 'postgres')}",
            "--template=template0",
            database,
        ],
        env=env,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"could not create G17 database: {detail}")


def _install_initial(database: str, initial_sql: Path, env: dict[str, str]) -> None:
    target_env = dict(env)
    target_env["PGDATABASE"] = database
    result = _run(
        ["psql", "--set=ON_ERROR_STOP=1", f"--file={initial_sql}"],
        env=target_env,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"final-initial install failed: {detail}")


def _provision_runtime(
    database: str,
    runtime_output: Path,
    runtime_env: Path,
    env: dict[str, str],
) -> dict[str, Any]:
    target_env = dict(env)
    target_env["PGDATABASE"] = database
    result = _run(
        [
            "uv",
            "run",
            "python",
            "scripts/release/provision_v3_release_runtime.py",
            "--output",
            str(runtime_output),
            "--env-output",
            str(runtime_env),
        ],
        env=target_env,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"final-initial runtime provisioning failed: {detail}")
    payload = _load_json(runtime_output)
    if payload.get("status") != "PASS":
        raise RuntimeError("final-initial runtime provisioning did not report PASS")
    return payload


def _cleanup_runtime(
    database: str,
    runtime_output: Path,
    env: dict[str, str],
) -> str | None:
    if not runtime_output.exists():
        return None
    target_env = dict(env)
    target_env["PGDATABASE"] = database
    result = _run(
        [
            "uv",
            "run",
            "python",
            "scripts/release/provision_v3_release_runtime.py",
            "--output",
            str(runtime_output),
            "--cleanup",
        ],
        env=target_env,
        capture_output=True,
    )
    if result.returncode == 0:
        return None
    return result.stderr.strip() or result.stdout.strip() or "runtime cleanup failed"


def _run_initial_suite(
    database: str,
    runtime_env: Path,
    candidate_junit: Path,
    initial_junit: Path,
    env: dict[str, str],
) -> int:
    with tempfile.TemporaryDirectory(prefix="request-engine-g17-") as temp_dir:
        saved_candidate = Path(temp_dir) / "candidate-junit.xml"
        shutil.copy2(candidate_junit, saved_candidate)
        run_env = dict(env)
        run_env["G17_RUNTIME_ENV"] = str(runtime_env)
        run_env["G17_DATABASE"] = database
        command = (
            'source "$G17_RUNTIME_ENV"; '
            'export PGDATABASE="$G17_DATABASE"; '
            "exec uv run python scripts/ci/ci_jobs.py "
            "postgres-v3-candidate --step v3-tests"
        )
        result = _run(["bash", "-lc", command], env=run_env)
        try:
            if candidate_junit.exists():
                shutil.copy2(candidate_junit, initial_junit)
        finally:
            shutil.copy2(saved_candidate, candidate_junit)
        return result.returncode


def _runtime_record(runtime_payload: dict[str, Any], runtime_output: Path) -> dict[str, Any]:
    return {
        "status": runtime_payload.get("status"),
        "database": runtime_payload.get("database"),
        "postgresql_major": runtime_payload.get("postgresql_major"),
        "secrets_redacted": runtime_payload.get("secrets_redacted"),
        "runtime_roles": runtime_payload.get("runtime_roles"),
        "artifact_sha256": _sha256(runtime_output),
    }


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    parser.add_argument("--initial-sql", type=Path, default=DEFAULT_INITIAL_SQL)
    parser.add_argument("--candidate-schema", type=Path, default=DEFAULT_CANDIDATE_SCHEMA)
    parser.add_argument("--candidate-junit", type=Path, default=DEFAULT_CANDIDATE_JUNIT)
    parser.add_argument("--initial-schema", type=Path, default=DEFAULT_INITIAL_SCHEMA)
    parser.add_argument("--initial-junit", type=Path, default=DEFAULT_INITIAL_JUNIT)
    parser.add_argument("--runtime-output", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--runtime-env", type=Path, default=DEFAULT_RUNTIME_ENV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _validate_database_name(args.database)
    args.initial_schema.parent.mkdir(parents=True, exist_ok=True)
    args.initial_junit.parent.mkdir(parents=True, exist_ok=True)
    args.runtime_env.parent.mkdir(parents=True, exist_ok=True)
    for stale_path in (
        args.initial_junit,
        args.runtime_output,
        args.runtime_env,
        args.output,
    ):
        stale_path.unlink(missing_ok=True)

    failures: list[str] = []
    env = os.environ.copy()
    runtime_payload: dict[str, Any] = {}
    initial_schema_payload: dict[str, Any] = {}
    candidate_schema_payload: dict[str, Any] = {}
    candidate_summary: dict[str, Any] = {}
    initial_summary: dict[str, Any] = {}
    freeze_payload: dict[str, Any] = {}
    database_created = False

    required = (
        args.freeze,
        args.initial_sql,
        args.candidate_schema,
        args.initial_schema,
        args.candidate_junit,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        failures.append(f"required G17 inputs are missing: {', '.join(missing)}")
    else:
        try:
            freeze_payload = _load_json(args.freeze)
            freeze_check = _run(
                [
                    "uv",
                    "run",
                    "python",
                    "scripts/release/validate_v3_candidate_freeze_artifact.py",
                    str(args.freeze),
                ],
                capture_output=True,
            )
            if freeze_check.returncode != 0:
                detail = freeze_check.stderr.strip() or freeze_check.stdout.strip()
                raise RuntimeError(f"candidate freeze validation failed: {detail}")

            candidate_schema_payload = _load_json(args.candidate_schema)
            initial_schema_payload = _load_json(args.initial_schema)
            if candidate_schema_payload != initial_schema_payload:
                raise RuntimeError("clean structural fingerprints differ")
            candidate_summary = _junit_summary(args.candidate_junit)
            if any(candidate_summary[field] != 0 for field in ("failures", "errors", "skipped")):
                raise RuntimeError("candidate canonical V3 suite did not pass cleanly")

            _create_database(args.database, env)
            database_created = True
            _install_initial(args.database, args.initial_sql, env)

            runtime_payload = _provision_runtime(
                args.database, args.runtime_output, args.runtime_env, env
            )
            test_returncode = _run_initial_suite(
                args.database,
                args.runtime_env,
                args.candidate_junit,
                args.initial_junit,
                env,
            )
            if not args.initial_junit.exists():
                raise RuntimeError("final-initial canonical suite produced no JUnit artifact")
            initial_summary = _junit_summary(args.initial_junit)
            if test_returncode != 0:
                failures.append(
                    f"final-initial canonical V3 suite exited with status {test_returncode}"
                )
            if any(initial_summary[field] != 0 for field in ("failures", "errors", "skipped")):
                failures.append("final-initial canonical V3 suite did not pass cleanly")
            if candidate_summary.get("test_ids") != initial_summary.get("test_ids"):
                failures.append("candidate and final-initial test inventories differ")
        except (OSError, RuntimeError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
            failures.append(str(exc))
        finally:
            cleanup_error = _cleanup_runtime(args.database, args.runtime_output, env)
            if cleanup_error is not None:
                failures.append(f"runtime cleanup failed: {cleanup_error}")
            args.runtime_env.unlink(missing_ok=True)
            if database_created:
                dropped = _drop_database(args.database, env)
                if dropped.returncode != 0:
                    detail = dropped.stderr.strip() or dropped.stdout.strip()
                    failures.append(f"database cleanup failed: {detail}")

    head_result = _run(["git", "rev-parse", "HEAD"], capture_output=True)
    head_sha = head_result.stdout.strip() if head_result.returncode == 0 else ""
    structural_equivalent = bool(
        candidate_schema_payload
        and initial_schema_payload
        and candidate_schema_payload == initial_schema_payload
    )
    behavioral_equivalent = bool(
        candidate_summary
        and initial_summary
        and candidate_summary.get("test_ids") == initial_summary.get("test_ids")
        and all(candidate_summary.get(field) == 0 for field in ("failures", "errors", "skipped"))
        and all(initial_summary.get(field) == 0 for field in ("failures", "errors", "skipped"))
    )
    payload = {
        "schema_version": 1,
        "proof": "v3-final-initial-equivalence",
        "status": (
            "PASS" if not failures and structural_equivalent and behavioral_equivalent else "FAIL"
        ),
        "head_sha": head_sha,
        "initial_database": args.database,
        "candidate_freeze": {
            "candidate_source_commit": freeze_payload.get("candidate_source_commit"),
            "current_head": freeze_payload.get("current_head"),
            "migration_set_sha256": freeze_payload.get("migration_set_sha256"),
            "artifact_sha256": _sha256(args.freeze) if args.freeze.exists() else None,
        },
        "initial_sql_sha256": _sha256(args.initial_sql) if args.initial_sql.exists() else None,
        "structural": {
            "equivalent": structural_equivalent,
            "candidate": _fingerprint_record(candidate_schema_payload)
            if candidate_schema_payload
            else None,
            "initial": _fingerprint_record(initial_schema_payload)
            if initial_schema_payload
            else None,
        },
        "behavioral": {
            "equivalent": behavioral_equivalent,
            "candidate": candidate_summary or None,
            "initial": initial_summary or None,
        },
        "runtime": _runtime_record(runtime_payload, args.runtime_output)
        if runtime_payload and args.runtime_output.exists()
        else None,
        "failures": failures,
    }
    _write_output(args.output, payload)
    if payload["status"] != "PASS":
        print("V3 final-initial equivalence proof FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("V3 final-initial equivalence proof PASS")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
