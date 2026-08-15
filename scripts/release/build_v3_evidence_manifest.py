from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
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


def _json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name}: invalid JSON ({exc})")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path.name}: root must be a JSON object")
        return None
    return payload


def _require_status(path: Path, errors: list[str], *, expected: str = "PASS") -> None:
    payload = _json(path, errors)
    if payload is not None and payload.get("status") != expected:
        errors.append(f"{path.name}: status is {payload.get('status')!r}, expected {expected!r}")


def _validate_junit(path: Path, errors: list[str]) -> None:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        errors.append(f"{path.name}: invalid JUnit XML ({exc})")
        return
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
    errors_count = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    if tests <= 0 or failures or errors_count or skipped:
        errors.append(
            f"{path.name}: tests={tests}, failures={failures}, errors={errors_count}, "
            f"skipped={skipped}"
        )


def _gate_statuses() -> dict[str, str]:
    statuses: dict[str, str] = {}
    for line in GATE_DOC.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"G\d{2}", cells[0]):
            statuses[cells[0]] = cells[2]
    return statuses


def _validate_artifacts(evidence_paths: dict[str, Path]) -> list[str]:
    errors: list[str] = []
    status_artifacts = (
        "test_quality",
        "test_collection",
        "concurrency_stability",
        "test_order_independence",
        "mutation_probes",
    )
    for name in status_artifacts:
        _require_status(evidence_paths[name], errors)

    catalog = _json(evidence_paths["catalog_audit"], errors)
    if catalog is not None and catalog.get("errors") != []:
        errors.append("v3-catalog-audit.json: blocking catalog errors are present")

    plans = _json(evidence_paths["worker_query_plans"], errors)
    if plans is not None:
        proofs = plans.get("proofs")
        if not isinstance(proofs, list) or not proofs:
            errors.append("v3-worker-query-plans.json: no measured proofs")
        elif any(
            not isinstance(proof, dict)
            or not isinstance(proof.get("indexes"), list)
            or proof.get("required_index") not in proof["indexes"]
            for proof in proofs
        ):
            errors.append("v3-worker-query-plans.json: a required index was not selected")

    schema = _json(evidence_paths["schema_fingerprint"], errors)
    if schema is not None and not schema:
        errors.append("v3-schema.json: empty fingerprint")

    try:
        equivalence = evidence_paths["initial_equivalence"].read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"v3-initial-equivalence.txt: unreadable ({exc})")
    else:
        if "catalog-equivalent to the V3 candidate chain" not in equivalence:
            errors.append("v3-initial-equivalence.txt: PASS marker is absent")

    _validate_junit(evidence_paths["test_junit"], errors)
    return errors


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
        "test_collection": ROOT / ".phase6/v3-test-collection.json",
        "test_junit": ROOT / ".phase6/v3-tests-junit.xml",
        "concurrency_stability": ROOT / ".phase6/v3-concurrency-stability.json",
        "test_order_independence": ROOT / ".phase6/v3-test-order-independence.json",
        "mutation_probes": ROOT / ".phase6/v3-mutation-probes.json",
    }
    evidence_hashes = {name: _sha256(path) for name, path in evidence_paths.items()}
    missing_artifacts = sorted(name for name, digest in evidence_hashes.items() if digest is None)

    checkout_commit = _git("rev-parse", "HEAD")
    commit = os.environ.get("PHASE6_COMMIT_SHA") or checkout_commit
    validation_errors = [] if missing_artifacts else _validate_artifacts(evidence_paths)
    if commit != checkout_commit:
        validation_errors.append(
            f"PHASE6_COMMIT_SHA {commit} does not match checkout HEAD {checkout_commit}"
        )
    gate_statuses = _gate_statuses()
    gate_counts = {
        status: sum(actual == status for actual in gate_statuses.values())
        for status in ("PASS", "PARTIAL", "MISSING", "BLOCKED")
    }
    bundle_valid = not missing_artifacts and not validation_errors
    release_ready = bundle_valid and gate_counts == {
        "PASS": 20,
        "PARTIAL": 0,
        "MISSING": 0,
        "BLOCKED": 0,
    }

    return {
        "schema_version": 4,
        "evidence_bundle_status": "VALID" if bundle_valid else "INVALID",
        "release_status": "READY" if release_ready else "INCOMPLETE",
        "missing_artifacts": missing_artifacts,
        "artifact_validation_errors": validation_errors,
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
        "release_gates": {"statuses": gate_statuses, "counts": gate_counts},
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
    parser.add_argument("--require-valid-bundle", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    missing = manifest["missing_artifacts"]
    validation_errors = manifest["artifact_validation_errors"]
    if args.require_valid_bundle and manifest["evidence_bundle_status"] != "VALID":
        details = [*(f"missing {name}" for name in missing), *validation_errors]
        print("V3 evidence bundle invalid: " + "; ".join(details))
        return 1

    if manifest["evidence_bundle_status"] != "VALID":
        print("V3 evidence bundle manifest generated INVALID.")
    else:
        print(
            "V3 evidence bundle manifest generated VALID; "
            f"release status is {manifest['release_status']}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
