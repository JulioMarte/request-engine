from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INVARIANT_DOC = ROOT / "docs/release/v3-invariant-matrix.md"
RACE_DOC = ROOT / "docs/release/v3-race-matrix.md"
GATE_DOC = ROOT / "docs/release/v3-release-gates.md"
APPLICATION_SCHEMAS = {"request_engine", "request_read", "request_cmd", "request_admin"}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _ids(path: Path, pattern: str) -> list[str]:
    return sorted(set(re.findall(pattern, path.read_text(encoding="utf-8"))))


def _gate_statuses() -> dict[str, str]:
    pattern = re.compile(
        r"^\| (G\d{2}) \|[^|]*\| (PASS|PARTIAL|MISSING|BLOCKED) \|",
        flags=re.MULTILINE,
    )
    return dict(pattern.findall(GATE_DOC.read_text(encoding="utf-8")))


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


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON value must be an object")
    return payload


def _validate_status_payload(payload: dict[str, Any]) -> list[str]:
    return [] if payload.get("status") == "PASS" else ["status is not PASS"]


def _validate_schema(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("postgres_major") != 18:
        errors.append("postgres_major is not 18")
    if set(payload.get("application_schemas", [])) != APPLICATION_SCHEMAS:
        errors.append("application_schemas does not match the V3 contract")
    if not isinstance(payload.get("catalog"), dict) or not payload["catalog"]:
        errors.append("catalog fingerprint is empty or malformed")
    return errors


def _validate_catalog_audit(payload: dict[str, Any]) -> list[str]:
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return ["errors is not a list"]
    return [] if not errors else [f"catalog audit contains {len(errors)} blocking error(s)"]


def _validate_worker_plans(payload: dict[str, Any]) -> list[str]:
    proofs = payload.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        return ["worker query-plan proofs are missing"]
    errors: list[str] = []
    for proof in proofs:
        if not isinstance(proof, dict):
            errors.append("worker query-plan proof is malformed")
            continue
        required_index = proof.get("required_index")
        indexes = proof.get("indexes")
        if not isinstance(required_index, str) or not isinstance(indexes, list):
            errors.append(f"{proof.get('name', '<unnamed>')}: proof fields are malformed")
        elif required_index not in indexes:
            errors.append(f"{proof.get('name', '<unnamed>')}: required index was not selected")
    return errors


def _validate_test_quality(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    if payload.get("error_count") != 0:
        errors.append("test quality error_count is not zero")
    if not isinstance(payload.get("tests_audited"), int) or payload["tests_audited"] <= 0:
        errors.append("test quality audit covered zero tests")
    return errors


def _validate_test_collection(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    if not isinstance(payload.get("node_count"), int) or payload["node_count"] <= 0:
        errors.append("test collection contains zero nodes")
    if payload.get("errors") != []:
        errors.append("test collection reports errors")
    return errors


def _validate_concurrency(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    requested = payload.get("requested_rounds")
    completed = payload.get("completed_rounds")
    rounds = payload.get("rounds")
    if not isinstance(requested, int) or requested < 2 or completed != requested:
        errors.append("concurrency proof did not complete every requested round")
    if not isinstance(rounds, list) or len(rounds) != requested:
        errors.append("concurrency round evidence is incomplete")
    elif any(not isinstance(item, dict) or item.get("status") != "PASS" for item in rounds):
        errors.append("one or more concurrency rounds did not pass")
    return errors


def _validate_order(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    if not isinstance(payload.get("node_count"), int) or payload["node_count"] <= 0:
        errors.append("reverse-order proof contains zero nodes")
    reverse = payload.get("reverse")
    if not isinstance(reverse, dict) or reverse.get("status") != "PASS":
        errors.append("reverse-order execution did not pass")
    return errors


def _validate_mutations(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    expected = payload.get("probe_count")
    results = payload.get("results")
    if not isinstance(expected, int) or expected <= 0:
        errors.append("mutation probe_count is invalid")
    if payload.get("completed_probe_count") != expected:
        errors.append("not every mutation probe completed")
    if not isinstance(results, list) or len(results) != expected:
        errors.append("mutation result evidence is incomplete")
    elif any(not isinstance(item, dict) or item.get("status") != "KILLED" for item in results):
        errors.append("one or more mutations survived or were invalid")
    if payload.get("infrastructure_error") is not None:
        errors.append("mutation proof reports an infrastructure error")
    return errors


def _validate_equivalence(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    marker = "generated 0001_initial candidate is catalog-equivalent to the V3 candidate chain"
    if marker not in text:
        return ["catalog-equivalence success marker is missing"]
    if re.search(r"(?m)^[0-9a-f]{64}$", text) is None:
        return ["catalog-equivalence fingerprint is missing"]
    return []


def _validate_junit(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else list(root)
    suites = [suite for suite in suites if suite.tag.rsplit("}", 1)[-1] == "testsuite"]
    if not suites:
        return ["JUnit report contains no test suite"]

    totals = {
        key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    errors: list[str] = []
    if totals["tests"] <= 0:
        errors.append("JUnit report contains zero tests")
    for key in ("failures", "errors", "skipped"):
        if totals[key] != 0:
            errors.append(f"JUnit report contains {totals[key]} {key}")
    return errors


JSON_VALIDATORS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "schema_fingerprint": _validate_schema,
    "catalog_audit": _validate_catalog_audit,
    "worker_query_plans": _validate_worker_plans,
    "test_quality": _validate_test_quality,
    "test_collection": _validate_test_collection,
    "concurrency_stability": _validate_concurrency,
    "test_order_independence": _validate_order,
    "mutation_probes": _validate_mutations,
}


def _validate_artifact(name: str, path: Path) -> dict[str, Any]:
    digest = _sha256(path)
    if digest is None:
        return {"status": "MISSING", "sha256": None, "errors": ["artifact is missing"]}

    try:
        if name in JSON_VALIDATORS:
            errors = JSON_VALIDATORS[name](_load_json(path))
        elif name == "initial_equivalence":
            errors = _validate_equivalence(path)
        elif name == "test_junit":
            errors = _validate_junit(path)
        else:
            errors = ["no semantic validator is registered"]
    except (ET.ParseError, KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        errors = [f"could not parse artifact: {exc}"]

    return {"status": "PASS" if not errors else "FAIL", "sha256": digest, "errors": errors}


def _release_ready(candidate_status: str, gate_statuses: dict[str, str]) -> bool:
    return (
        candidate_status == "VALID"
        and len(gate_statuses) == 20
        and all(status == "PASS" for status in gate_statuses.values())
    )


def build_manifest() -> dict[str, Any]:
    invariants = _ids(INVARIANT_DOC, r"\bV3-I\d{2}\b")
    races = _ids(RACE_DOC, r"\bR\d{2}\b")
    gates = _ids(GATE_DOC, r"\bG\d{2}\b")

    _assert_complete(invariants, [f"V3-I{i:02d}" for i in range(1, 67)], "Invariant")
    _assert_complete(races, [f"R{i:02d}" for i in range(1, 30)], "Race")
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
    artifact_validation = {
        name: _validate_artifact(name, path) for name, path in evidence_paths.items()
    }
    missing_artifacts = sorted(
        name for name, result in artifact_validation.items() if result["status"] == "MISSING"
    )
    validation_errors = [
        f"{name}: {error}"
        for name, result in artifact_validation.items()
        for error in result["errors"]
        if result["status"] == "FAIL"
    ]
    candidate_status = (
        "INCOMPLETE" if missing_artifacts else "INVALID" if validation_errors else "VALID"
    )

    checkout_sha = _git("rev-parse", "HEAD")
    legacy_sha = os.environ.get("PHASE6_COMMIT_SHA")
    head_sha = os.environ.get("PHASE6_HEAD_SHA") or legacy_sha or checkout_sha
    tested_sha = os.environ.get("PHASE6_TESTED_SHA") or legacy_sha or checkout_sha
    base_sha = os.environ.get("PHASE6_BASE_SHA") or None
    gate_statuses = _gate_statuses()
    release_ready = _release_ready(candidate_status, gate_statuses)

    tree_sha = _git("rev-parse", "HEAD^{tree}")
    working_tree_dirty = _tracked_tree_dirty()
    return {
        "schema_version": 4,
        "evidence_scope": "phase6-candidate-ci",
        "evidence_status": candidate_status,
        "artifact_set_complete": not missing_artifacts,
        "missing_artifacts": missing_artifacts,
        "validation_errors": validation_errors,
        "release_ready": release_ready,
        "release_status": "READY" if release_ready else "NOT_READY",
        "source": {
            "head_sha": head_sha,
            "base_sha": base_sha,
            "tested_sha": tested_sha,
            "checkout_sha": checkout_sha,
            "tree_sha": tree_sha,
            "working_tree_dirty": working_tree_dirty,
        },
        # Kept for consumers of the schema-v3 manifest; source.tested_sha is canonical.
        "commit_sha": tested_sha,
        "tree_sha": tree_sha,
        "working_tree_dirty": working_tree_dirty,
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
            "gate_statuses": gate_statuses,
        },
        "tests": _test_inventory(),
        "artifact_validation": artifact_validation,
        "artifacts": {
            **{f"{name}_sha256": result["sha256"] for name, result in artifact_validation.items()},
            "invariant_registry_sha256": _sha256(INVARIANT_DOC),
            "race_registry_sha256": _sha256(RACE_DOC),
            "gate_registry_sha256": _sha256(GATE_DOC),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-valid", action="store_true")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Deprecated alias for --require-valid; completeness alone is not accepted.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = build_manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    status = manifest["evidence_status"]
    if (args.require_valid or args.require_complete) and status != "VALID":
        print(f"V3 candidate evidence is {status}, not VALID.")
        for error in manifest["validation_errors"]:
            print(f"- {error}")
        if manifest["missing_artifacts"]:
            print(f"- missing: {', '.join(manifest['missing_artifacts'])}")
        return 1

    print(
        f"V3 candidate evidence manifest generated {status}; "
        f"overall release status is {manifest['release_status']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
