from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from v3_scratch_database import fresh_v3_database

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class MutationProbe:
    name: str
    kind: Literal["python", "sql"]
    path: Path
    original: str
    mutant: str
    pytest_target: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    name: str
    kind: str
    path: str
    pytest_target: str
    status: str
    returncode: int
    seconds: float
    output_tail: list[str]


PROBES = (
    MutationProbe(
        name="idempotency_conflict_mapping",
        kind="python",
        path=ROOT / "src/request_engine/platform/idempotency/postgres.py",
        original='        if sqlstate == "P1001":\n',
        mutant='        if False and sqlstate == "P1001":\n',
        pytest_target=(
            "tests/integration/v3_first_vertical/"
            "test_idempotency_error_contract.py::"
            "test_idempotency_fingerprint_mismatch_has_semantic_error"
        ),
    ),
    MutationProbe(
        name="provider_event_payload_hash_guard",
        kind="python",
        path=ROOT / "src/request_engine/platform/events/provider_events.py",
        original='    if cast(str, existing["payload_hash"]) != payload_hash:\n',
        mutant='    if False and cast(str, existing["payload_hash"]) != payload_hash:\n',
        pytest_target=(
            "tests/integration/v3_worker_runtime/test_provider_chaos.py::"
            "test_provider_duplicate_replay_is_exact_and_payload_mutation_conflicts"
        ),
    ),
    MutationProbe(
        name="db_exact_revision_step_guard",
        kind="sql",
        path=ROOT / "migrations/sql/v3_candidate/007-contract-convergence.sql",
        original="    ELSIF NEW.revision <> OLD.revision + 1 THEN\n",
        mutant="    ELSIF FALSE THEN\n",
        pytest_target=(
            "tests/db/test_v3_contract_convergence.py::"
            "test_revision_step_rejects_skips_and_backwards_values"
        ),
    ),
    MutationProbe(
        name="db_public_execute_revocation",
        kind="sql",
        path=ROOT / "migrations/sql/v3_candidate/021-release-privilege-hardening.sql",
        original="REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_engine FROM PUBLIC;\n",
        mutant="-- mutation: PUBLIC EXECUTE intentionally left in place for request_engine\n",
        pytest_target=(
            "tests/db/test_v3_release_catalog.py::"
            "test_application_functions_are_not_executable_by_public"
        ),
    ),
)


def _completed_result(
    probe: MutationProbe,
    *,
    status: str,
    returncode: int,
    started: float,
    output: list[str],
) -> MutationResult:
    return MutationResult(
        name=probe.name,
        kind=probe.kind,
        path=probe.path.relative_to(ROOT).as_posix(),
        pytest_target=probe.pytest_target,
        status=status,
        returncode=returncode,
        seconds=round(time.monotonic() - started, 3),
        output_tail=output[-80:],
    )


def _run_python_probe(probe: MutationProbe, started: float) -> MutationResult:
    with fresh_v3_database("request_engine_mutation_python") as scratch_env:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", probe.pytest_target, "-q", "--tb=short"],
            cwd=ROOT,
            env=scratch_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    output = (result.stdout + result.stderr).strip().splitlines()
    return _completed_result(
        probe,
        status="KILLED" if result.returncode != 0 else "SURVIVED",
        returncode=result.returncode,
        started=started,
        output=output,
    )


def _run_sql_probe(probe: MutationProbe, started: float) -> MutationResult:
    scratch_database = f"request_engine_mutation_{uuid4().hex[:20]}"
    env = os.environ.copy()
    apply_env = {**env, "PGDATABASE": scratch_database}
    created = False
    try:
        create = subprocess.run(
            ["createdb", scratch_database],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if create.returncode != 0:
            output = (create.stdout + create.stderr).strip().splitlines()
            return _completed_result(
                probe,
                status="INVALID",
                returncode=create.returncode,
                started=started,
                output=["scratch database creation failed", *output],
            )
        created = True

        apply = subprocess.run(
            ["bash", "scripts/db/apply_v3_candidate.sh"],
            cwd=ROOT,
            env=apply_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if apply.returncode != 0:
            output = (apply.stdout + apply.stderr).strip().splitlines()
            return _completed_result(
                probe,
                status="INVALID",
                returncode=apply.returncode,
                started=started,
                output=["mutated candidate did not bootstrap", *output],
            )

        test = subprocess.run(
            [sys.executable, "-m", "pytest", probe.pytest_target, "-q", "--tb=short"],
            cwd=ROOT,
            env=apply_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = (test.stdout + test.stderr).strip().splitlines()
        return _completed_result(
            probe,
            status="KILLED" if test.returncode != 0 else "SURVIVED",
            returncode=test.returncode,
            started=started,
            output=output,
        )
    finally:
        if created:
            subprocess.run(
                ["dropdb", "--force", scratch_database],
                cwd=ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def run_probe(probe: MutationProbe) -> MutationResult:
    source = probe.path.read_text(encoding="utf-8")
    if source.count(probe.original) != 1:
        raise RuntimeError(f"mutation probe {probe.name} expected exactly one guard occurrence")

    probe.path.write_text(source.replace(probe.original, probe.mutant), encoding="utf-8")
    started = time.monotonic()
    try:
        if probe.kind == "sql":
            return _run_sql_probe(probe, started)
        return _run_python_probe(probe, started)
    finally:
        probe.path.write_text(source, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results: list[MutationResult] = []
    infrastructure_error: str | None = None

    for probe in PROBES:
        try:
            result = run_probe(probe)
        except RuntimeError as exc:
            infrastructure_error = str(exc)
            break
        results.append(result)
        if result.status != "KILLED":
            break

    all_killed = len(results) == len(PROBES) and all(
        result.status == "KILLED" for result in results
    )
    payload = {
        "status": "PASS" if all_killed and infrastructure_error is None else "FAIL",
        "probe_count": len(PROBES),
        "completed_probe_count": len(results),
        "python_probe_count": sum(probe.kind == "python" for probe in PROBES),
        "sql_probe_count": sum(probe.kind == "sql" for probe in PROBES),
        "infrastructure_error": infrastructure_error,
        "results": [asdict(result) for result in results],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if payload["status"] == "PASS":
        for result in results:
            print(f"mutation killed: {result.name} [{result.kind}] ({result.seconds:.3f}s)")
        return 0

    if infrastructure_error is not None:
        print(f"mutation probe infrastructure failure: {infrastructure_error}")
    elif results:
        failed = results[-1]
        if failed.status == "INVALID":
            print(f"mutation probe invalid: {failed.name}; mutant could not be exercised")
        else:
            print(f"mutation survived: {failed.name}; regression suite did not detect it")
        for line in failed.output_tail:
            print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
