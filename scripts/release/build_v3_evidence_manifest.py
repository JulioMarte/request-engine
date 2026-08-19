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

from validate_v3_adversarial_failure_artifact import validate_adversarial_failure

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


def _validate_queue_plans(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    proofs = payload.get("proofs")
    failures = payload.get("failures")
    cardinality = payload.get("cardinality")

    if not isinstance(proofs, list) or not proofs:
        errors.append("Queue query-plan proofs are missing")
    elif any(not isinstance(proof, dict) or proof.get("status") != "PASS" for proof in proofs):
        errors.append("one or more Queue query-plan proofs did not pass")
    if failures != []:
        errors.append("Queue query-plan proof reports failures")
    if not isinstance(cardinality, dict):
        errors.append("Queue query-plan cardinality is malformed")
        return errors

    minimums = {
        "tenant_count": 4,
        "queue_history_per_tenant": 2_500,
        "waitlist_candidates_per_tenant": 400,
        "slot_offer_history_per_tenant": 2_500,
    }
    for field, minimum in minimums.items():
        value = cardinality.get(field)
        if not isinstance(value, int) or value < minimum:
            errors.append(f"Queue query-plan cardinality {field} is below {minimum}")
    return errors


def _validate_booking_plans(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    proofs = payload.get("proofs")
    failures = payload.get("failures")
    cardinality = payload.get("cardinality")

    if failures != []:
        errors.append("Booking query-plan proof reports failures")
    if not isinstance(cardinality, dict):
        errors.append("Booking query-plan cardinality is malformed")
    else:
        minimums = {"tenant_count": 4, "history_per_tenant": 1_500}
        for field, minimum in minimums.items():
            value = cardinality.get(field)
            if not isinstance(value, int) or value < minimum:
                errors.append(f"Booking query-plan cardinality {field} is below {minimum}")

    required_proofs = {
        "booking_resource_schedules": "availability_schedules_active_lookup_idx",
        "booking_resource_exceptions": "schedule_exceptions_resource_during_idx",
        "booking_live_capacity_claims": "capacity_claims_active_resource_during_idx",
    }
    if not isinstance(proofs, list):
        errors.append("Booking query-plan proofs are missing")
        return errors

    by_name = {
        proof.get("name"): proof
        for proof in proofs
        if isinstance(proof, dict) and isinstance(proof.get("name"), str)
    }
    for proof_name, required_index in required_proofs.items():
        proof = by_name.get(proof_name)
        if not isinstance(proof, dict):
            errors.append(f"{proof_name}: required Booking query-plan proof is missing")
            continue
        if proof.get("status") != "PASS":
            errors.append(f"{proof_name}: proof did not pass")
        indexes = proof.get("indexes")
        if not isinstance(indexes, list) or required_index not in indexes:
            errors.append(f"{proof_name}: required index {required_index} was not selected")
        if proof.get("forbidden_seq_scans") != []:
            errors.append(f"{proof_name}: forbidden sequential scan was reported")
        if proof.get("shared_read_blocks") != 0:
            errors.append(f"{proof_name}: shared reads are not zero")
        if proof.get("temp_written_blocks") != 0:
            errors.append(f"{proof_name}: temporary blocks were written")
    return errors


def _validate_operational_plans(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    proofs = payload.get("proofs")
    failures = payload.get("failures")
    cardinality = payload.get("cardinality")

    if failures != []:
        errors.append("operational query-plan proof reports failures")
    if not isinstance(cardinality, dict):
        errors.append("operational query-plan cardinality is malformed")
    else:
        minimums = {
            "tenant_count": 4,
            "history_per_tenant": 1_500,
            "reservation_history_per_tenant": 1_500,
            "binding_history_per_tenant": 1_500,
            "reconciliation_history_per_tenant": 1_500,
        }
        for field, minimum in minimums.items():
            value = cardinality.get(field)
            if not isinstance(value, int) or value < minimum:
                errors.append(f"operational query-plan cardinality {field} is below {minimum}")

    required_proofs = {
        "communications_latest_delivery": {
            "communication_deliveries_organization_id_communication_task_key"
        },
        "communications_verified_contacts": {"party_contact_points_verified_lookup_idx"},
        "communications_future_dispatch": {"scheduled_actions_active_subject_idx"},
        "reservation_status_latest_attendance": {
            "reservations_organization_id_id_key",
            "attendance_responses_current_idx",
        },
        "shared_capacity_root_resolution": {
            "shared_capacity_bindings_one_active_resource_idx",
            "shared_capacity_identities_pkey",
        },
        "shared_capacity_live_conflict": {
            "capacity_claims_active_id_idx",
            "shared_capacity_claim_links_root_idx",
        },
        "communications_future_reconciliation": {"scheduled_actions_active_subject_idx"},
    }
    if not isinstance(proofs, list):
        errors.append("operational query-plan proofs are missing")
        return errors

    by_name = {
        proof.get("name"): proof
        for proof in proofs
        if isinstance(proof, dict) and isinstance(proof.get("name"), str)
    }
    for proof_name, required_indexes in required_proofs.items():
        proof = by_name.get(proof_name)
        if not isinstance(proof, dict):
            errors.append(f"{proof_name}: required operational query-plan proof is missing")
            continue
        if proof.get("status") != "PASS":
            errors.append(f"{proof_name}: proof did not pass")
        indexes = proof.get("indexes")
        if not isinstance(indexes, list):
            errors.append(f"{proof_name}: selected-index evidence is malformed")
        else:
            missing_indexes = sorted(required_indexes - set(indexes))
            if missing_indexes:
                missing = ", ".join(missing_indexes)
                errors.append(f"{proof_name}: required indexes were not selected: {missing}")
        if proof.get("forbidden_seq_scans") != []:
            errors.append(f"{proof_name}: forbidden sequential scan was reported")
        if proof.get("shared_read_blocks") != 0:
            errors.append(f"{proof_name}: shared reads are not zero")
        if proof.get("temp_written_blocks") != 0:
            errors.append(f"{proof_name}: temporary blocks were written")
    return errors


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _validate_public_api_contract(payload: dict[str, Any]) -> list[str]:
    errors = _validate_status_payload(payload)
    if payload.get("schema_version") != 1:
        errors.append("public API contract schema_version is not 1")
    if payload.get("failures") != []:
        errors.append("public API contract proof reports failures")
    if payload.get("operation_count") != 24:
        errors.append("public API contract operation_count is not 24")
    if payload.get("capability_count") != 34:
        errors.append("public API contract capability_count is not 34")
    if payload.get("capability_schema_versions") != [1]:
        errors.append("public API contract capability schema versions are not exactly [1]")
    if payload.get("error_code_count") != 51:
        errors.append("public API contract error_code_count is not 51")

    baseline_sha = payload.get("baseline_sha256")
    contract_sha = payload.get("contract_sha256")
    if not _valid_sha256(baseline_sha):
        errors.append("public API contract baseline fingerprint is malformed")
    if not _valid_sha256(contract_sha):
        errors.append("public API contract runtime fingerprint is malformed")

    contract = payload.get("contract")
    if not isinstance(contract, dict):
        errors.append("public API contract snapshot is malformed")
        return errors

    expected_lengths = {
        "operations": 24,
        "capabilities": 34,
        "openapi": 24,
    }
    for field, expected in expected_lengths.items():
        value = contract.get(field)
        if not isinstance(value, list) or len(value) != expected:
            errors.append(
                f"public API contract {field} snapshot does not contain {expected} entries"
            )

    literal_codes = contract.get("literal_error_codes")
    shared_codes = contract.get("shared_error_codes")
    helper_codes = contract.get("request_helper_error_codes")
    if not all(isinstance(value, list) for value in (literal_codes, shared_codes, helper_codes)):
        errors.append("public API contract error-code snapshots are malformed")
    else:
        all_codes = set(literal_codes) | set(shared_codes) | set(helper_codes)
        if len(all_codes) != 51 or any(not isinstance(code, str) for code in all_codes):
            errors.append("public API contract error-code snapshot does not contain 51 strings")

    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if _valid_sha256(contract_sha) and hashlib.sha256(encoded).hexdigest() != contract_sha:
        errors.append("public API contract runtime fingerprint does not match its snapshot")
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
    "queue_query_plans": _validate_queue_plans,
    "booking_query_plans": _validate_booking_plans,
    "operational_query_plans": _validate_operational_plans,
    "public_api_contract": _validate_public_api_contract,
    "test_quality": _validate_test_quality,
    "test_collection": _validate_test_collection,
    "concurrency_stability": _validate_concurrency,
    "test_order_independence": _validate_order,
    "mutation_probes": _validate_mutations,
    "adversarial_failure": validate_adversarial_failure,
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
        "queue_query_plans": ROOT / ".phase6/v3-queue-query-plans.json",
        "booking_query_plans": ROOT / ".phase6/v3-booking-query-plans.json",
        "operational_query_plans": ROOT / ".phase6/v3-operational-query-plans.json",
        "public_api_contract": ROOT / ".phase6/v3-public-api-contract.json",
        "initial_equivalence": ROOT / ".phase6/v3-initial-equivalence.txt",
        "test_quality": ROOT / ".phase6/v3-test-quality.json",
        "test_collection": ROOT / ".phase6/v3-test-collection.json",
        "test_junit": ROOT / ".phase6/v3-tests-junit.xml",
        "concurrency_stability": ROOT / ".phase6/v3-concurrency-stability.json",
        "test_order_independence": ROOT / ".phase6/v3-test-order-independence.json",
        "mutation_probes": ROOT / ".phase6/v3-mutation-probes.json",
        "adversarial_failure": ROOT / ".phase6/v3-adversarial-failure-proof.json",
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
