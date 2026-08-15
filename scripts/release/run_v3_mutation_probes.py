from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class MutationProbe:
    name: str
    path: Path
    original: str
    mutant: str
    pytest_target: str


@dataclass(frozen=True, slots=True)
class MutationResult:
    name: str
    path: str
    pytest_target: str
    status: str
    returncode: int
    seconds: float
    output_tail: list[str]


PROBES = (
    MutationProbe(
        name="idempotency_conflict_mapping",
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
        path=ROOT / "src/request_engine/platform/events/provider_events.py",
        original='    if cast(str, existing["payload_hash"]) != payload_hash:\n',
        mutant='    if False and cast(str, existing["payload_hash"]) != payload_hash:\n',
        pytest_target=(
            "tests/integration/v3_worker_runtime/test_provider_chaos.py::"
            "test_provider_duplicate_replay_is_exact_and_payload_mutation_conflicts"
        ),
    ),
)


def run_probe(probe: MutationProbe) -> MutationResult:
    source = probe.path.read_text(encoding="utf-8")
    if source.count(probe.original) != 1:
        raise RuntimeError(f"mutation probe {probe.name} expected exactly one guard occurrence")

    probe.path.write_text(source.replace(probe.original, probe.mutant), encoding="utf-8")
    started = time.monotonic()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", probe.pytest_target, "-q", "--tb=short"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    finally:
        probe.path.write_text(source, encoding="utf-8")

    elapsed = round(time.monotonic() - started, 3)
    output = (result.stdout + result.stderr).strip().splitlines()
    return MutationResult(
        name=probe.name,
        path=probe.path.relative_to(ROOT).as_posix(),
        pytest_target=probe.pytest_target,
        status="KILLED" if result.returncode != 0 else "SURVIVED",
        returncode=result.returncode,
        seconds=elapsed,
        output_tail=output[-60:],
    )


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
        if result.status == "SURVIVED":
            break

    all_killed = len(results) == len(PROBES) and all(
        result.status == "KILLED" for result in results
    )
    payload = {
        "status": "PASS" if all_killed and infrastructure_error is None else "FAIL",
        "probe_count": len(PROBES),
        "completed_probe_count": len(results),
        "infrastructure_error": infrastructure_error,
        "results": [asdict(result) for result in results],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if payload["status"] == "PASS":
        for result in results:
            print(f"mutation killed: {result.name} ({result.seconds:.3f}s)")
        return 0

    if infrastructure_error is not None:
        print(f"mutation probe infrastructure failure: {infrastructure_error}")
    elif results:
        survived = results[-1]
        print(f"mutation survived: {survived.name}; regression suite did not detect it")
        for line in survived.output_tail:
            print(line)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
