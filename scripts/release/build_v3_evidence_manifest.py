from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INVARIANT_DOC = ROOT / "docs/release/v3-invariant-matrix.md"
RACE_DOC = ROOT / "docs/release/v3-race-matrix.md"
GATE_DOC = ROOT / "docs/release/v3-release-gates.md"


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _ids(path: Path, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, path.read_text(encoding="utf-8"))))


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _test_inventory() -> list[str]:
    return sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("test_*.py")
        if path.is_file()
    )


def _assert_complete(actual: list[str], expected: list[str], label: str) -> None:
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise SystemExit(f"{label} registry is incomplete: missing {', '.join(missing)}")


def _tracked_tree_dirty() -> bool:
    return (
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"],
            cwd=ROOT,
            check=False,
        ).returncode
        != 0
    )


def build_manifest() -> dict[str, Any]:
    invariants = _ids(INVARIANT_DOC, r"\bV3-I\d{2}\b")
    races = _ids(RACE_DOC, r"\bR\d{2}\b")
    gates = _ids(GATE_DOC, r"\bG\d{2}\b")

    _assert_complete(invariants, [f"V3-I{i:02d}" for i in range(1, 62)], "Invariant")
    _assert_complete(races, [f"R{i:02d}" for i in range(1, 25)], "Race")
    _assert_complete(gates, [f"G{i:02d}" for i in range(1, 21)], "Gate")

    evidence_paths = {
        "schema_fingerprint": ROOT / ".phase6/v3-schema.json",
        "catalog_audit": ROOT / ".phase6/v3-catalog-audit.json",
        "worker_query_plans": ROOT / ".phase6/v3-worker-query-plans.json",
        "initial_equivalence": ROOT / ".phase6/v3-initial-equivalence.txt",
        "test_quality": ROOT / ".phase6/v3-test-quality.json",
        "test_junit": ROOT / ".phase6/v3-tests-junit.xml",
        "concurrency_stability": ROOT / ".phase6/v3-concurrency-stability.json",
        "test_order_independence": ROOT / ".phase6/v3-test-order-independence.json",
        "mutation_probes": ROOT / ".phase6/v3-mutation-probes.json",
    }
    evidence_hashes = {name: _sha256(path) for name, path in evidence_paths.items()}
    missing_artifacts = sorted(name for name, digest in evidence_hashes.items() if digest is None)

    commit = os.environ.get("PHASE6_COMMIT_SHA") or _git("rev-parse", "HEAD")

    return {
        "schema_version": 3,
        "evidence_status": "COMPLETE" if not missing_artifacts else "INCOMPLETE",
        "missing_artifacts": missing_artifacts,
        "commit_sha": commit,
        "tree_sha": _git("rev-parse", "HEAD^{tree}"),
        "working_tree_dirty": _tracked_tree_dirty(),
        "runtime": {
            "python": platform.python_version(),
            "postgres_target": "18",
            "bootstrap_role": os.environ.get("PGUSER", "unknown"),
            "application_role": "request_engine_app",
            "worker_role": "request_engine_worker",
            "admin_role": "request_engine_admin",
        },
        "registries": {
            "invariants": invariants,
            "races": races,
            "gates": gates,
        },
        "tests": _test_inventory(),
        "artifacts": {
            **{f"{name}_sha256": digest for name, digest in evidence_hashes.items()},
            "invariant_registry_sha256": _sha256(INVARIANT_DOC),
            "race_registry_sha256": _sha256(RACE_DOC),
            "gate_registry_sha256": _sha256(GATE_DOC),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing = manifest["missing_artifacts"]
    if args.require_complete and missing:
        print(f"V3 release evidence incomplete: missing {', '.join(missing)}")
        return 1

    if missing:
        print(f"V3 release evidence manifest generated INCOMPLETE: missing {', '.join(missing)}")
    else:
        print("V3 release evidence manifest generated COMPLETE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
