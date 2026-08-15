from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class MutationProbe:
    name: str
    path: Path
    original: str
    mutant: str
    pytest_target: str


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


def run_probe(probe: MutationProbe) -> None:
    source = probe.path.read_text(encoding="utf-8")
    if source.count(probe.original) != 1:
        raise SystemExit(f"mutation probe {probe.name} expected exactly one guard occurrence")

    probe.path.write_text(source.replace(probe.original, probe.mutant), encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", probe.pytest_target, "-q"],
            cwd=ROOT,
            check=False,
        )
    finally:
        probe.path.write_text(source, encoding="utf-8")

    if result.returncode == 0:
        raise SystemExit(f"mutation survived: {probe.name}; the regression suite did not detect it")
    print(f"mutation killed: {probe.name}")


def main() -> int:
    for probe in PROBES:
        run_probe(probe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
