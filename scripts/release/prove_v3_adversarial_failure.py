#!/usr/bin/env python3
"""Compose the mandatory Phase 6 G18 adversarial/failure release proof."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RACE_DOC = ROOT / "docs/release/v3-race-matrix.md"

RACE_OWNERS: dict[str, tuple[str, ...]] = {
    "R01": ("tests/integration/v3_booking_commitments/test_capacity_hold_races.py",),
    "R02": ("tests/integration/v3_booking_commitments/test_g18_adversarial_races.py",),
    "R03": ("tests/integration/v3_booking_commitments/test_reservation_races.py",),
    "R04": ("tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py",),
    "R05": ("tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py",),
    "R06": ("tests/integration/v3_slot_offer_recovery/test_slot_offer_release_races.py",),
    "R07": ("tests/integration/v3_slot_offer_recovery/test_slot_offer_recovery.py",),
    "R08": ("tests/integration/v3_reservation_lifecycle/test_released_slot_recovery_races.py",),
    "R09": ("tests/integration/v3_first_vertical/test_business_and_queue.py",),
    "R10": ("tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py",),
    "R11": (
        "tests/integration/v3_first_vertical/test_http_request_booking_revision_races.py",
        "tests/integration/v3_slot_offer_recovery/test_slot_offer_runtime_revision_race.py",
    ),
    "R12": ("tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py",),
    "R13": (
        "tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py",
        "tests/db/test_v3_worker_expired_leases.py",
    ),
    "R14": ("tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py",),
    "R15": ("tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py",),
    "R16": ("tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py",),
    "R17": ("tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py",),
    "R18": ("tests/integration/v3_reservation_lifecycle/test_provider_business_race.py",),
    "R19": (
        "tests/integration/v3_first_vertical/test_http_idempotency_failure.py",
        "tests/architecture/test_retryable_command_inventory.py",
    ),
    "R20": (
        "tests/e2e/test_communication_reconciliation_release.py",
        "tests/e2e/test_communication_delivery_lease_fence.py",
        "tests/e2e/test_communication_terminal_reconciliation_race.py",
    ),
    "R21": ("tests/integration/v3_first_vertical/test_reminder_occurrence_races.py",),
    "R22": ("tests/integration/v3_first_vertical/test_reminder_plan_races.py",),
    "R23": (
        "tests/db/test_v3_party_authority_state_adversarial.py",
        "tests/integration/v3_reservation_lifecycle/test_appointment_manage_authority_race.py",
    ),
    "R24": (
        "tests/db/test_v3_tenant_isolation_adversarial.py",
        "tests/e2e/test_http_tenant_isolation_matrix.py",
    ),
    "R25": ("tests/integration/v3_booking_commitments/test_cross_tenant_shared_capacity.py",),
    "R26": ("tests/integration/v3_booking_commitments/test_g18_adversarial_races.py",),
    "R27": ("tests/integration/v3_booking_commitments/test_g18_adversarial_races.py",),
    "R28": ("tests/db/test_v3_cross_tenant_shared_capacity_authority_races.py",),
    "R29": (
        "tests/db/test_v3_cross_tenant_shared_capacity_lock_topology.py",
        "tests/integration/v3_booking_commitments/test_cross_tenant_shared_capacity_reschedule_race.py",
    ),
}

FAMILY_OWNERS: dict[str, tuple[str, ...]] = {
    "attack_security": (
        "tests/db/test_v3_tenant_isolation_adversarial.py",
        "tests/db/test_v3_tenant_function_surfaces_adversarial.py",
        "tests/db/test_v3_party_authority_state_adversarial.py",
        "tests/e2e/test_http_security_matrix.py",
        "tests/e2e/test_http_tenant_isolation_matrix.py",
        "tests/integration/v3_first_vertical/test_http_input_adversarial.py",
    ),
    "race_concurrency": tuple(sorted({owner for owners in RACE_OWNERS.values() for owner in owners})),
    "crash_recovery": (
        "tests/integration/v3_worker_runtime/test_process_crash_recovery.py",
        "tests/integration/v3_worker_runtime/test_process_crash_recovery_other_families.py",
        "tests/unit/test_worker_runtime_failure_boundaries.py",
        "tests/e2e/test_communication_delivery_lease_fence.py",
        "tests/e2e/test_communication_reconciliation_release.py",
    ),
    "retry_idempotency": (
        "tests/architecture/test_retryable_command_inventory.py",
        "tests/integration/v3_first_vertical/test_http_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_request_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_reservation_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_attendance_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_queue_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_waitlist_idempotency_failure.py",
        "tests/integration/v3_slot_offer_recovery/test_http_slot_offer_idempotency_failure.py",
        "tests/integration/v3_first_vertical/test_http_reminder_idempotency_failure.py",
    ),
    "order_independence": (".phase6/v3-test-order-independence.json",),
    "mutation_probes": (".phase6/v3-mutation-probes.json",),
}

SUPPORTING_ARTIFACTS = {
    "test_collection": ROOT / ".phase6/v3-test-collection.json",
    "test_junit": ROOT / ".phase6/v3-tests-junit.xml",
    "concurrency_stability": ROOT / ".phase6/v3-concurrency-stability.json",
    "test_order_independence": ROOT / ".phase6/v3-test-order-independence.json",
    "mutation_probes": ROOT / ".phase6/v3-mutation-probes.json",
}


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _json_status(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        return "MISSING", [f"missing artifact: {path.relative_to(ROOT)}"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return "FAIL", [f"malformed artifact {path.relative_to(ROOT)}: {exc}"]
    if not isinstance(payload, dict):
        return "FAIL", [f"malformed artifact {path.relative_to(ROOT)}: top-level is not object"]
    return (
        ("PASS", [])
        if payload.get("status") == "PASS"
        else ("FAIL", [f"artifact is not PASS: {path.relative_to(ROOT)}"])
    )


def _junit_status(path: Path) -> tuple[str, dict[str, int], list[str]]:
    if not path.exists():
        return "MISSING", {}, [f"missing artifact: {path.relative_to(ROOT)}"]
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, OSError) as exc:
        return "FAIL", {}, [f"malformed JUnit artifact: {exc}"]

    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    counts = {key: sum(int(suite.attrib.get(key, "0")) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
    failures: list[str] = []
    if counts["tests"] <= 0:
        failures.append("JUnit contains zero tests")
    for key in ("failures", "errors", "skipped"):
        if counts[key] != 0:
            failures.append(f"JUnit contains {counts[key]} {key}")
    return ("PASS" if not failures else "FAIL"), counts, failures


def _race_statuses() -> dict[str, str]:
    pattern = re.compile(
        r"^\| (R\d{2}) \|[^\n]*?\| (PASS|PARTIAL|MISSING|BLOCKED) \| [^|]+\|$",
        flags=re.MULTILINE,
    )
    return dict(pattern.findall(RACE_DOC.read_text(encoding="utf-8")))


def _owner_inventory(paths: tuple[str, ...]) -> tuple[list[str], list[str]]:
    observed = [path for path in paths if (ROOT / path).exists()]
    missing = [path for path in paths if not (ROOT / path).exists()]
    return observed, missing


def build_proof() -> dict[str, Any]:
    failures: list[str] = []
    race_statuses = _race_statuses()
    expected_races = [f"R{number:02d}" for number in range(1, 30)]
    missing_races = sorted(set(expected_races) - set(race_statuses))
    unmapped_races = sorted(set(expected_races) - set(RACE_OWNERS))
    non_pass_races = sorted(race_id for race_id in expected_races if race_statuses.get(race_id) != "PASS")
    if missing_races:
        failures.append(f"race registry missing: {', '.join(missing_races)}")
    if unmapped_races:
        failures.append(f"race evidence mapping missing: {', '.join(unmapped_races)}")
    if non_pass_races:
        failures.append(f"release-critical races are not PASS: {', '.join(non_pass_races)}")

    race_rows: list[dict[str, Any]] = []
    for race_id in expected_races:
        owners = RACE_OWNERS.get(race_id, ())
        observed, missing = _owner_inventory(owners)
        if missing:
            failures.append(f"{race_id} missing owner(s): {', '.join(missing)}")
        race_rows.append(
            {
                "id": race_id,
                "status": "PASS" if race_statuses.get(race_id) == "PASS" and not missing else "FAIL",
                "owners": list(owners),
                "expected_owner_count": len(owners),
                "observed_owner_count": len(observed),
            }
        )

    supporting: dict[str, dict[str, Any]] = {}
    junit_status, junit_counts, junit_failures = _junit_status(SUPPORTING_ARTIFACTS["test_junit"])
    supporting["test_junit"] = {"status": junit_status, "counts": junit_counts}
    failures.extend(junit_failures)
    for name, path in SUPPORTING_ARTIFACTS.items():
        if name == "test_junit":
            continue
        status, artifact_failures = _json_status(path)
        supporting[name] = {"status": status}
        failures.extend(artifact_failures)

    families: list[dict[str, Any]] = []
    for family_id, owners in FAMILY_OWNERS.items():
        observed, missing = _owner_inventory(owners)
        family_failures = [f"missing owner: {path}" for path in missing]
        if family_id == "race_concurrency" and non_pass_races:
            family_failures.append(f"non-PASS races: {', '.join(non_pass_races)}")
        if family_id == "order_independence" and supporting.get("test_order_independence", {}).get("status") != "PASS":
            family_failures.append("order-independence artifact is not PASS")
        if family_id == "mutation_probes" and supporting.get("mutation_probes", {}).get("status") != "PASS":
            family_failures.append("mutation-probe artifact is not PASS")
        if family_id in {"race_concurrency", "crash_recovery", "retry_idempotency", "attack_security"} and junit_status != "PASS":
            family_failures.append("canonical PostgreSQL JUnit artifact is not PASS")
        if family_id == "race_concurrency" and supporting.get("concurrency_stability", {}).get("status") != "PASS":
            family_failures.append("concurrency-stability artifact is not PASS")
        failures.extend(f"{family_id}: {message}" for message in family_failures)
        families.append(
            {
                "id": family_id,
                "status": "PASS" if not family_failures else "FAIL",
                "owners": list(owners),
                "expected_owner_count": len(owners),
                "observed_owner_count": len(observed),
                "failures": family_failures,
            }
        )

    return {
        "schema_version": 1,
        "status": "PASS" if not failures else "FAIL",
        "source": {
            "head_sha": os.environ.get("PHASE6_HEAD_SHA") or _git("rev-parse", "HEAD"),
            "tested_sha": os.environ.get("PHASE6_TESTED_SHA") or _git("rev-parse", "HEAD"),
            "checkout_sha": _git("rev-parse", "HEAD"),
            "tree_sha": _git("rev-parse", "HEAD^{tree}"),
        },
        "environment": {"python": platform.python_version(), "postgres_major": 18},
        "expected_family_count": 6,
        "observed_family_count": len(families),
        "families": families,
        "expected_race_count": 29,
        "observed_race_count": len(race_rows),
        "races": race_rows,
        "supporting_artifacts": supporting,
        "missing_evidence": sorted(set(missing_races + unmapped_races)),
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-pass", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    proof = build_proof()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"G18 adversarial/failure proof: {proof['status']}")
    if args.require_pass and proof["status"] != "PASS":
        for failure in proof["failures"]:
            print(f"- {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
